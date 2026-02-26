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
import pytest
import os
import warnings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from .custom_summary_plugin import CustomSummaryPlugin
from .cache_manager import CacheManager
from datetime import datetime

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
    parser.addoption("--load-test-results", action="store_true", default=False, help="Load previous test results if available")
    parser.addoption("--database", help="Database URL for SQLAlchemy")

@pytest.fixture
def target_file(request):
    """
    Pytest fixture to get the target file path from the command-line options.

    Args:
        request (pytest.FixtureRequest): The fixture request object.

    Returns:
        pathlib.Path or None: The target file path, or None if not provided.
    """
    file_path = request.config.getoption("target_file")
    if file_path:
        file_path = pathlib.Path(file_path).expanduser()
    return file_path

@pytest.fixture
def file_path(target_file):
    """
    Backward-compatible fixture alias for target_file.

    Args:
        target_file (pathlib.Path or None): The resolved target file path.

    Returns:
        pathlib.Path or None: The target file path, or None if not provided.
    """
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

@pytest.fixture(scope="session")
def db_session(request):
    """
    Pytest fixture to create a SQLAlchemy database session.

    Args:
        request (pytest.FixtureRequest): The fixture request object.

    Yields:
        sqlalchemy.orm.Session or None: The database session, or None if not provided.
    """
    database_url = request.config.getoption("--database")
    if database_url:
        engine = create_engine(database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
    else:
        yield None

@pytest.fixture(scope="session")
def params(request):
    """
    Pytest fixture to get parsed key-value parameters from command-line options.

    Args:
        request (pytest.FixtureRequest): The fixture request object.

    Returns:
        dict: Parsed parameters from --params (keys and values as strings).
    """
    return request.config._parsed_params

def pytest_cmdline_main(config):
    """
    Ensures only the specified test file is run.

    Args:
        config (pytest.Config): The pytest configuration object.

    Raises:
        pytest.UsageError: If the specified test file does not exist.
    """
    test_name = config.getoption("--test")
    if test_name:
        test_file = pathlib.Path(__file__).parent.parent / "checks" / f"{test_name}.py"
        if not os.path.isfile(test_file):
            raise pytest.UsageError(f"Test file {test_file} does not exist.")
        config.args[:] = [str(test_file)]  # Ensure only the specified test file is run
    return None

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
    config._parsed_params = _parse_params(config.getoption("--params"))

    # Handle warning options
    if not config.getoption("--native-output"):
        config.pluginmanager.register(CustomSummaryPlugin(config), "custom_summary_plugin")

    # Handle caching logic
    file_path = config.getoption("target_file")
    database = config.getoption("--database")
    load_test_results = config.getoption("--load-test-results")
    if (file_path or database) and not config.getoption("--no-cache-results"):
        cache_manager = CacheManager(config)
        if load_test_results:
            cache_manager.load_test_results()
        cache_manager.setup_cache()

    # Prevent pytest from automatically running tests here
    config.option.runpytest = False

def pytest_pycollect_makeitem(collector, name, obj):
    """
    Custom item collection to support test naming convention.

    Args:
        collector (pytest.Collector): The collector object.
        name (str): Name of the test item.
        obj (callable): The test function.

    Returns:
        pytest.Function: The pytest Function item if the naming convention matches, else None.
    """
    if name.startswith("check_") and callable(obj):
        return pytest.Function.from_parent(collector, name=name)

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
