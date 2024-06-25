# plugin/custom_summary_plugin.py
import pytest
import warnings

class CustomSummaryPlugin:
    def __init__(self, config):
        self.warnings = []
        self.failures = []
        self.passed_tests = []
        self.no_warnings = config.getoption("--no-warnings")
        self.passed = 0
        self.skipped = 0
        self.config = config

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            outcome = yield
            self.warnings.extend(w)

    def pytest_runtest_logreport(self, report):
        if report.passed and report.when == "call":
            self.passed += 1
            self.passed_tests.append(report.nodeid)
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

        assertion_message = None
        for line in longreprtext.splitlines():
            if "AssertionError" in line:
                line = line.split("AssertionError: ")[1]
                assertion_message = line
                break

        if assertion_message is None:
            assertion_message = longreprtext

        return f"FAILED::{test_name}::{assertion_message}"

    def pytest_terminal_summary(self, terminalreporter):
        if not self.no_warnings:
            self._print_warnings_summary(terminalreporter)
        self._print_passed_summary(terminalreporter)
        self._print_failures_summary(terminalreporter)

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

    def _print_passed_summary(self, terminalreporter):
        if self.passed_tests:
            dark_green = "\033[32m"
            reset = "\033[0m"
            terminalreporter.write_sep("=", f"{dark_green}Passed summary{reset}")
            for passed in self.passed_tests:
                formatted_passed = self._format_passed_test(passed)
                terminalreporter.write_line(f"{dark_green}{formatted_passed}{reset}")
            total_passed = len(self.passed_tests)
            if total_passed > 1:
                terminalreporter.write_sep("=", f"{dark_green}There are {total_passed} passed tests{reset}")
            else:
                terminalreporter.write_sep("=", f"{dark_green}There is {total_passed} passed test{reset}")

    def _format_passed_test(self, passed_test):
        parts = passed_test.split("::")
        test_name = parts[-1]
        module_path = parts[0].split("/")[-1].replace(".py", "")
        return f"Pass::{module_path}::{test_name}"

    def write_summary_to_file(self, file_path):
        with open(file_path, 'w') as f:
            if not self.no_warnings:
                self._write_warnings_summary(f)
            self._write_failures_summary(f)
            self._write_passed_summary(f)

    def _write_warnings_summary(self, file):
        if self.warnings:
            file.write(f"Warnings summary\n")
            for warning in self.warnings:
                file.write(f"{warning.message}\n")
            total_warnings = len(self.warnings)
            if total_warnings > 1:
                file.write(f"There are {total_warnings} warnings\n")
            else:
                file.write(f"There is {total_warnings} warning\n")

    def _write_failures_summary(self, file):
        if self.failures:
            file.write(f"Failures summary\n")
            for failure in self.failures:
                file.write(f"{failure}\n")
            total_failures = len(self.failures)
            if total_failures > 1:
                file.write(f"There are {total_failures} failures\n")
            else:
                file.write(f"There is {total_failures} failure\n")

    def _write_passed_summary(self, file):
        if self.passed_tests:
            file.write(f"Passed summary\n")
            for passed in self.passed_tests:
                formatted_passed = self._format_passed_test(passed)
                file.write(f"{formatted_passed}\n")
            total_passed = len(self.passed_tests)
            if total_passed > 1:
                file.write(f"There are {total_passed} passed tests\n")
            else:
                file.write(f"There is {total_passed} passed test\n")
