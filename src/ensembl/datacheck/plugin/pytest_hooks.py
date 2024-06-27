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

def pytest_addoption(parser):
    """
    Adds command-line options to pytest.

    Args:
        parser (pytest.Parser): The pytest parser object.
    """
    parser.addoption("--file", default=None, help="Paths to the files to be tested")
    parser.addoption("--test", required=True, help="Name of the test to run")
    parser.addoption("--no-warnings", action="store_true", default=False, help="Disable warnings display")
    parser.addoption("--native-output", action="store_true", default=False, help="Use native warnings display")
    parser.addoption("--no-cache-results", action="store_true", default=False, help="Disable caching of results")
    parser.addoption("--load-test-results", action="store_true", default=False, help="Load previous test results if available")
    parser.addoption("--database", help="Database URL for SQLAlchemy")

@pytest.fixture
def file_path(request):
    """
    Pytest fixture to get the file path from the command-line options.

    Args:
        request (pytest.FixtureRequest): The fixture request object.

    Returns:
        pathlib.Path or None: The file path, or None if not provided.
    """
    file_path = request.config.getoption("--file")
    if file_path:
        file_path = pathlib.Path(file_path).expanduser()
    return file_path

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

    # Handle warning options
    if not config.getoption("--native-output"):
        config.pluginmanager.register(CustomSummaryPlugin(config), "custom_summary_plugin")

    # Handle caching logic
    file_path = config.getoption("--file")
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
