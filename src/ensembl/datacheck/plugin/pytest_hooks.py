# plugin/pytest_hooks.py
import pathlib
import pytest
import os
import warnings
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from .custom_summary_plugin import CustomSummaryPlugin
from .cache_manager import CacheManager

def pytest_addoption(parser):
    parser.addoption("--file", default=None, help="Paths to the files to be tested")
    parser.addoption("--test", required=True, help="Name of the test to run")
    parser.addoption("--no-warnings", action="store_true", default=False, help="Disable warnings display")
    parser.addoption("--native-output", action="store_true", default=False, help="Use native warnings display")
    parser.addoption("--no-cache-results", action="store_true", default=False, help="Disable caching of results")
    parser.addoption("--load-test-results", action="store_true", default=False, help="Load previous test results if available")

@pytest.fixture
def file_path(request):
    file_path = request.config.getoption("--file")
    if file_path:
        file_path = pathlib.Path(file_path).expanduser()
    return file_path

def pytest_cmdline_main(config):
    test_name = config.getoption("--test")
    if test_name:
        test_file = pathlib.Path(__file__).parent.parent / "checks" / f"{test_name}.py"
        if not os.path.isfile(test_file):
            raise pytest.UsageError(f"Test file {test_file} does not exist.")
        config.args[:] = [str(test_file)]  # Ensure only the specified test file is run
    return None

def pytest_configure(config):
    # Define custom warning format
    def custom_warning_format(message, category, filename, lineno, file=None, line=None):
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
    load_test_results = config.getoption("--load-test-results")
    if file_path and not config.getoption("--no-cache-results"):
        cache_manager = CacheManager(config)
        if load_test_results:
            cache_manager.load_test_results()
        cache_manager.setup_cache()

    # Prevent pytest from automatically running tests here
    config.option.runpytest = False

# Swap test for check in naming convention
def pytest_pycollect_makeitem(collector, name, obj):
    if name.startswith("check_") and callable(obj):
        return pytest.Function.from_parent(collector, name=name)

@pytest.hookimpl(tryfirst=True)
def pytest_report_header(config):
    return ["ensembl-datacheck"]

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    yield
    cache_manager = CacheManager(config)
    cache_manager.handle_cache_post_run(terminalreporter)

@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    print("Ensembl Datacheck")
    print("https://github.com/Ensembl/ensembl-datacheck-py")
    print("Documentation available at TODO")
    print("Contributions are always welcome")
