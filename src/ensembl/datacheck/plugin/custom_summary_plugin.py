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

import pytest
import warnings

class CustomSummaryPlugin:
    """
    A pytest plugin to provide custom summaries for test results, including warnings, failures, and passed tests.

    Attributes:
        warnings (list): A list to store warning messages.
        failures (list): A list to store formatted failure messages.
        passed_tests (list): A list to store passed test identifiers.
        no_warnings (bool): Flag to determine whether warnings should be displayed.
        passed (int): Count of passed tests.
        skipped (int): Count of skipped tests.
        config (pytest.Config): Pytest configuration object.
    """

    def __init__(self, config):
        """
        Initializes the CustomSummaryPlugin with the given configuration.

        Args:
            config (pytest.Config): Pytest configuration object.
        """
        self.warnings = []
        self.failures = []
        self.passed_tests = []
        self.no_warnings = config.getoption("--no-warnings")
        self.passed = 0
        self.skipped = 0
        self.config = config

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        """
        Hook to catch warnings during the test run.

        Args:
            item (pytest.Item): The test item being executed.
            nextitem (pytest.Item): The next test item to be executed.
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            outcome = yield
            self.warnings.extend(w)

    def pytest_runtest_logreport(self, report):
        """
        Hook to log the results of each test.

        Args:
            report (pytest.TestReport): The test report object.
        """
        if report.passed and report.when == "call":
            self.passed += 1
            self.passed_tests.append(report.nodeid)
        elif report.failed and report.when == "call":
            formatted_error = self._format_assertion_error(report)
            self.failures.append(formatted_error)
        elif report.skipped:
            self.skipped += 1

    def _format_assertion_error(self, report):
        """
        Formats assertion error messages for better readability.

        Args:
            report (pytest.TestReport): The test report object containing the error.

        Returns:
            str: Formatted assertion error message.
        """
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
        """
        Hook to print custom summaries in the terminal after the test run.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
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
        """
        Prints a summary of warnings in the terminal.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
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
        """
        Prints a summary of failures in the terminal.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
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
        """
        Prints a summary of passed tests in the terminal.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
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
        """
        Formats passed test identifiers for better readability.

        Args:
            passed_test (str): The identifier of the passed test.

        Returns:
            str: Formatted passed test identifier.
        """
        parts = passed_test.split("::")
        test_name = parts[-1]
        module_path = parts[0].split("/")[-1].replace(".py", "")
        return f"Pass::{module_path}::{test_name}"

    def write_summary_to_file(self, file_path):
        """
        Writes the test summary to a file.

        Args:
            file_path (str): Path to the file where the summary should be written.
        """
        with open(file_path, 'w') as f:
            if not self.no_warnings:
                self._write_warnings_summary(f)
            self._write_failures_summary(f)
            self._write_passed_summary(f)

    def _write_warnings_summary(self, file):
        """
        Writes the warnings summary to a file.

        Args:
            file (file object): File object where the summary should be written.
        """
        if self.warnings:
            file.write("Warnings summary\n")
            for warning in self.warnings:
                file.write(f"{warning.message}\n")
            total_warnings = len(self.warnings)
            if total_warnings > 1:
                file.write(f"There are {total_warnings} warnings\n")
            else:
                file.write(f"There is {total_warnings} warning\n")

    def _write_failures_summary(self, file):
        """
        Writes the failures summary to a file.

        Args:
            file (file object): File object where the summary should be written.
        """
        if self.failures:
            file.write("Failures summary\n")
            for failure in self.failures:
                file.write(f"{failure}\n")
            total_failures = len(self.failures)
            if total_failures > 1:
                file.write(f"There are {total_failures} failures\n")
            else:
                file.write(f"There is {total_failures} failure\n")

    def _write_passed_summary(self, file):
        """
        Writes the passed tests summary to a file.

        Args:
            file (file object): File object where the summary should be written.
        """
        if self.passed_tests:
            file.write("Passed summary\n")
            for passed in self.passed_tests:
                formatted_passed = self._format_passed_test(passed)
                file.write(f"{formatted_passed}\n")
            total_passed = len(self.passed_tests)
            if total_passed > 1:
                file.write(f"There are {total_passed} passed tests\n")
            else:
                file.write(f"There is {total_passed} passed test\n")
