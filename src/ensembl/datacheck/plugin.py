import pathlib
import pytest
import os
import warnings
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning

def pytest_addoption(parser):
    parser.addoption("--file", default=None, help="Paths to the files to be tested")
    parser.addoption("--test", required=True, help="Name of the test to run")
    parser.addoption("--no-warnings", action="store_true", default=False, help="Disable warnings display")
    parser.addoption("--native-output", action="store_true", default=False, help="Use native warnings display")

@pytest.fixture
def file_path(request):
    file_path = request.config.getoption("--file")
    if file_path:
        file_path = pathlib.Path(file_path).expanduser()
    return file_path

def pytest_cmdline_main(config):
    test_name = config.getoption("--test")
    if test_name:
        test_file = pathlib.Path(__file__).parent / "checks" / f"{test_name}.py"
        if not os.path.isfile(test_file):
            raise pytest.UsageError(f"Test file {test_file} does not exist.")
        config.args.insert(0, test_file)
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

def pytest_pycollect_makeitem(collector, name, obj):
    if name.startswith("check_") and callable(obj):
        return pytest.Function.from_parent(collector, name=name)

@pytest.hookimpl(tryfirst=True)
def pytest_report_header(config):
    return ["ensembl-datacheck"]

class CustomSummaryPlugin:
    def __init__(self, config):
        self.warnings = []
        self.failures = []
        self.no_warnings = config.getoption("--no-warnings")
        self.passed = 0
        self.skipped = 0

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            outcome = yield
            self.warnings.extend(w)

    def pytest_runtest_logreport(self, report):
        if report.passed and report.when == "call":
            self.passed += 1
        elif report.failed and report.when == "call":
            formatted_error = self._format_assertion_error(report)
            self.failures.append(formatted_error)
        elif report.skipped:
            self.skipped += 1

    def _format_assertion_error(self, report):
        file_path, line_number, test_name = report.location
        if isinstance(report.longrepr, tuple):
            longreprtext = "\n".join(map(str, report.longrepr))
        else:
            longreprtext = str(report.longrepr)

        # Extract only the assertion message
        assertion_message = None
        for line in longreprtext.splitlines():
            if "AssertionError" in line:
                line = line.split("AssertionError: ")[1]
                assertion_message = line
                break
        # Fallback
        if assertion_message is None:
            assertion_message = longreprtext

        return f"FAILED::{test_name}::{assertion_message}"

    def pytest_terminal_summary(self, terminalreporter):
        if not self.no_warnings:
            self._print_warnings_summary(terminalreporter)
        self._print_failures_summary(terminalreporter)

        # Loop over all failures and set longrepr to ''
        if 'failed' in terminalreporter.stats:
            for report in terminalreporter.stats['failed']:
                test_name = report.nodeid.split("::")[1]
                test_name = test_name.split("-")[0]
                report.nodeid = test_name
                report.longrepr = ''
    def _print_warnings_summary(self, terminalreporter):
        if self.warnings:
            dark_yellow = "\033[33m"
            reset = "\033[0m"
            terminalreporter.write_sep("=", f"{dark_yellow}Warnings summary{reset}")
            for warning in self.warnings:
                terminalreporter.write_line(f"{dark_yellow}{warning.message}{reset}")
            total_warnings = len(self.warnings)
            if total_warnings > 1:
                terminalreporter.write_sep("=", f"{dark_yellow}There are {total_warnings} warnings{reset}")
            else:
                terminalreporter.write_sep("=", f"{dark_yellow}There is {total_warnings} warning{reset}")

    def _print_failures_summary(self, terminalreporter):
        if self.failures:
            dark_red = "\033[31m"
            reset = "\033[0m"
            terminalreporter.write_sep("=", f"{dark_red}Failures summary{reset}")
            for failure in self.failures:
                terminalreporter.write_line(f"{dark_red}{failure}{reset}")
            total_failures = len(self.failures)
            if total_failures > 1:
                terminalreporter.write_sep("=", f"{dark_red}There are {total_failures} failures{reset}")
            else:
                terminalreporter.write_sep("=", f"{dark_red}There is {total_failures} failure{reset}")

    # def _print_short_test_summary(self, terminalreporter):
    #     dark_blue = "\033[34m"
    #     reset = "\033[0m"
    #     terminalreporter.write_sep("=", f"{dark_blue}Short test summary info{reset}")
    #     total_tests = self.passed + self.skipped + len(self.failures)
    #     terminalreporter.write_line(f"{dark_blue}{total_tests} Total, {self.passed} Passed, {len(self.failures)} Failure(s), {len(self.warnings)} Warning(s){reset}")
