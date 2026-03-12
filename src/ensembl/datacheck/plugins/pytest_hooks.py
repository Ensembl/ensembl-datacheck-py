# See the NOTICE file distributed with this work for additional information
# regarding copyright ownership.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pathlib
from collections import defaultdict
import pytest
import os
import warnings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from .custom_summary_plugin import CustomSummaryPlugin
from .cache_manager import CacheManager
from collections import defaultdict
from datetime import datetime
import json

PARSED_PARAMS_STASH_KEY = pytest.StashKey[dict[str, str]]()


def _parse_params(raw_params):
    """
    Parse key-value command-line parameters into a dictionary.

    Args:
        raw_params (list[str] or None): Parameters provided through --params.
            Each value may contain a comma-separated key=value list.

    Returns:
        dict: Parsed parameter dictionary where keys and values are strings.

    Raises:
        pytest.UsageError: If any parameter is not in key=value format.
    """
    parsed_params = {}
    if not raw_params:
        return parsed_params

    for raw_param in raw_params:
        for param in raw_param.split(","):
            param = param.strip()
            if not param:
                raise pytest.UsageError(
                    f"Invalid --params value '{raw_param}'. Empty parameter found."
                )
            if "=" not in param:
                raise pytest.UsageError(
                    f"Invalid --params value '{param}'. Expected format: key=value."
                )
            key, value = param.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise pytest.UsageError(
                    f"Invalid --params value '{param}'. Parameter key cannot be empty."
                )
            if key in parsed_params:
                raise pytest.UsageError(
                    f"Duplicate --params key '{key}' is not allowed."
                )
            parsed_params[key] = value
    return parsed_params


def pytest_addoption(parser):
    """
    Adds command-line options to pytest.

    Args:
        parser (pytest.Parser): The pytest parser object.
    """
    parser.addoption("--target-file", "--file", dest="target_file", default=None, help="Path to the target file to be tested")
    parser.addoption("--source-file", dest="source_file", default=None, help="Optional path to a source file for comparison checks")
    parser.addoption("--params", action="append", default=[], help="Additional test parameters as key=value,key=value")
    parser.addoption("--test", required=True, help="Name of the test to run")
    parser.addoption("--no-warnings", action="store_true", default=False, help="Disable warnings display")
    parser.addoption("--native-output", action="store_true", default=False, help="Use native warnings display")
    parser.addoption("--no-cache-results", action="store_true", default=False, help="Disable caching of results")
    parser.addoption("--load-test-results", action="store_true", default=False, help="Load previous test results if "
                                                                                     "available")
    parser.addoption("--database", help="Database URL for SQLAlchemy")
    parser.addoption("--automation_resource", action="store", help="Indicates that the datacheck "
                                                                   "is being run in an automation "
                                                                   "resource context")
    parser.addoption("--release_name", default=None, help="Release name for the datacheck run")
    parser.addoption("--genome_uuid", default=None, help="Genome UUID for the datacheck run")
    parser.addoption("--automation_resource_config", action="store",
                     help="Indicates the path to the automation resource config file")
    parser.addoption("--tag", default=datetime.now().strftime("%Y%m%d_%H%M%S"),
                     help="Custom tag to include in the JSON report metadata for each test item")
    parser.addoption("--other_database", help="Additional Database URL for SQLAlchemy, if needed for specific checks,"
                                              " eg. production db or metadata db for core database")
    parser.addoption("--taxonomy_database", help="Additional Database URL for SQLAlchemy, if needed for specific checks,"
                                                 " eg. production db or metadata db for taxonomy database")


def pytest_runtest_setup(item):
    """
    Pytest hook checks if the test item has any markers named "automation_resource". If such markers are present
    and the --automation_resource option is provided, it verifies that the value of the option matches
    one of the marker arguments.
    If there is no match, the test is skipped with a message indicating the required automation resources.
    Args:
        item (pytest.Item): The test item being set up.

    """
    automation_resource = [mark.args[0] for mark in item.iter_markers(name="automation_resource")]
    if automation_resource and item.config.getoption("--automation_resource"):
        if item.config.getoption("--automation_resource") not in automation_resource:
            pytest.skip(f"test requires automation_resource in {automation_resource!r}")


@pytest.fixture
def target_file(request):
    """
    Pytest fixture to get the target file path from the command-line options.

    Args:
        request (pytest.FixtureRequest): The fixture request object.

    Returns:
        pathlib.Path or None: The target file path, or None if not provided.
    """
    target_file = request.config.getoption("target_file")
    if target_file:
        target_file = pathlib.Path(target_file).expanduser()
    return target_file


@pytest.fixture
def source_file(request):
    """
    Pytest fixture to get the source file path from the command-line options.

    Args:
        request (pytest.FixtureRequest): The fixture request object.

    Returns:
        pathlib.Path or None: The source file path, or None if not provided.
    """
    source_file = request.config.getoption("source_file")
    if source_file:
        source_file = pathlib.Path(source_file).expanduser()
    return source_file

# db session factory
def _create_session_fixture(option_name):
    @pytest.fixture(scope="session")
    def _fixture(request):
        database_url = request.config.getoption(option_name)

        if database_url:
            engine = create_engine(database_url)
            Session = sessionmaker(bind=engine)
            session = Session()
            yield session
            session.close()
        else:
            yield None

    return _fixture


# Prepare fixture for db session
db_session = _create_session_fixture("database")
other_db_session = _create_session_fixture("other_database")



def pytest_cmdline_main(config):
    """
    Ensures only the specified test file or directory is run.

    Priority:
    1. checks/<name>.py
    2. checks/<name>/ (all *.py inside)
    """

    test_name = config.getoption("--test")
    if not test_name:
        return None

    base_path = pathlib.Path(__file__).parent.parent / "checks"

    # First: check for file checks/<name>.py
    test_file = base_path / f"{test_name}.py"
    if test_file.is_file():
        config.args[:] = [str(test_file)]
        return None

    # Fallback: check for directory checks/<name>/
    dir_path = base_path / test_name
    if dir_path.is_dir():
        py_files = sorted(
            str(path)
            for path in dir_path.glob("*.py")
            if path.name != "conftest.py"
        )
        if not py_files:
            raise pytest.UsageError(f"No .py files found in directory {dir_path}")
        config.args[:] = py_files
        return None

    # If neither exists → fail
    raise pytest.UsageError(
        f"No test file '{test_file}' or directory '{dir_path}' found."
    )


def pytest_configure(config):
    """
    Configures pytest with custom warning formats and caching logic.

    Args:
        config (pytest.Config): The pytest configuration object.
    """

    def custom_warning_format(message, category, filename, lineno, file=None, line=None):
        """
        Custom warning format for EnsemblDatacheckWarning.

        Args:
            message (str): Warning message.
            category (Warning): Warning category.
            filename (str): Name of the file issuing the warning.
            lineno (int): Line number of the warning.

        Returns:
            str: Formatted warning message.
        """
        if issubclass(category, EnsemblDatacheckWarning):
            return str(message) + '\n'
        else:
            return f"{filename}:{lineno}: {category.__name__}: {message}\n"

    # Apply custom warning format
    warnings.formatwarning = custom_warning_format

    # Parse and validate key-value parameters
    config.stash[PARSED_PARAMS_STASH_KEY] = _parse_params(config.getoption("--params"))

    # Handle warning options
    if not config.getoption("--native-output"):
        config.pluginmanager.register(CustomSummaryPlugin(config), "custom_summary_plugin")

    # Handle caching logic
    target_file = config.getoption("target_file")
    database = config.getoption("--database")
    load_test_results = config.getoption("--load-test-results")
    if (target_file or database) and not config.getoption("--no-cache-results"):
        cache_manager = CacheManager(config)
        if load_test_results:
            cache_manager.load_test_results()
        cache_manager.setup_cache()

    # register an additional marker for automation resources to group the test and run it
    config.addinivalue_line(
        "markers", "automation_resource(name): mark test to run only on named automation resources"
    )
    # Place the selected test and write to a file to run the test parallely in nextflow or any other workflow manager.
    config.selected_tests = defaultdict(list)

    # Prevent pytest from automatically running tests here
    config.option.runpytest = False


@pytest.hookimpl(tryfirst=True)
def pytest_report_header(config):
    """
    Adds a custom header to the pytest report.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        list: List of header strings.
    """
    return ["ensembl-datacheck"]


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Custom summary for the pytest terminal output.

    Args:
        terminalreporter (pytest.TerminalReporter): The pytest terminal reporter plugin.
        exitstatus (int): Exit status of the pytest run.
        config (pytest.Config): The pytest configuration object.
    """
    yield
    if config.getoption("--collect-only"):
        return

    target_file = config.getoption("target_file")
    database = config.getoption("--database")
    if (target_file or database) and not config.getoption("--no-cache-results"):
        cache_manager = CacheManager(config)
        cache_manager.handle_cache_post_run(terminalreporter)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """
    Actions to perform at the start of the pytest session.

    Args:
        session (pytest.Session): The pytest session object.
    """
    print("Ensembl Datacheck")
    print("https://github.com/Ensembl/ensembl-datacheck-py")
    print("Documentation available at TODO")
    print("Contributions are always welcome")


# # ### JSON Report Setup on param --json-report  enabled #####
def pytest_collection_modifyitems(items, config):
    for item in items:
        callspec = getattr(item, "callspec", None)

        # Store the selected test item in the config for later use for nextflow or any other workflow manager
        if config.getoption("--collect-only"):
            config.selected_tests[item.originalname].append(
                {
                    "nodeid": item.nodeid,
                    "test": item.originalname,
                    "name": item.name,
                    "runtest": item.runtest,
                    "path": item.path,
                    "params": callspec.params if callspec else None
                }
            )
        # prepare the json report
        if callspec and "genomes" in callspec.params and "genomes" in item.fixturenames:
            genome = callspec.params["genomes"]
            item.genome_uuid = genome["genome_uuid"]


def pytest_json_runtest_metadata(item, call):
    """
    Adds custom metadata to the JSON report for each test item.
    Args:
        item (pytest.Item): The test item being executed.
        call (pytest.CallInfo): Information about the test call, including the phase (setup, call, teardown).
    Returns:
        dict: A dictionary of metadata to be included in the JSON report for the test item.
    """

    if call.when != 'setup':
        return {}  # Only add metadata during the setup phase to avoid duplication

    config = item.config  # Access the pytest configuration object to retrieve command-line options
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    datacheck_tag = config.getoption("--tag") or f"default_tag_{timestamp}"

    if call.when == 'setup' and hasattr(item, "genome_uuid"):
        return {'start': call.start, 'stop': call.stop, "tag": datacheck_tag, "genome_uuid": item.genome_uuid}

    return {'start': call.start, "tag": datacheck_tag, 'stop': call.stop}


def pytest_json_modifyreport(json_report):
    """
    Modifies the JSON report to group test results by genome UUID and include error information.
    Args:
        json_report: The original JSON report generated by pytest, which includes test outcomes and metadata.

    Returns:
        None. The function modifies the json_report in place to restructure the test results.

    """
    tests = json_report["tests"]
    genomes = defaultdict(lambda: {
    })
    tag = f"default_tag_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # group tests per genome if not set under All
    for test in tests:
        meta = test.get("metadata", {})
        genome_uuid = meta.get("genome_uuid")
        tag = meta.get("tag", tag)
        if not genome_uuid:
            genome_uuid = "All"

        test_name = test["nodeid"].split("::")[-1]  #.split("[")[0]

        error_info = test.get("call", {}).get("crash", None) or test.get("call", {}).get("longrepr", None)
        genomes[genome_uuid][test_name] = {"status": test["outcome"], "error": error_info}

    # delete the existing result format and replace with the new one grouped by genome_uuid
    json_report.pop("tests", "Not found `test` key in json report")
    json_report.pop("collectors", "Not found `collectors` key in json report")

    json_report["results"] = genomes
    json_report["status"] = "failed" if json_report["summary"]["failed"] > 0 else "passed"
    json_report["tag"] = tag


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--collect-only"):
        with open("selected_tests.txt", "w") as f1, open("selected_test_details.txt", "w") as f2:
            for test in session.config.selected_tests:
                f1.write(f"{str(test)}\n")
                for test_detail in session.config.selected_tests[test]:
                    f2.write(f"{str(test_detail)}\n")
