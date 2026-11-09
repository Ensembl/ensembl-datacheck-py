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

"""Unit tests for the custom terminal summary plugin."""

from _pytest.reports import TestReport
from _pytest.subtests import SubtestContext, SubtestReport

from ensembl.datacheck.plugins.custom_summary_plugin import CustomSummaryPlugin


class _DummyConfig:
    def getoption(self, name):
        if name == "--no-warnings":
            return False
        return None


class _DummyReport:
    location = ("checks/automation/example.py", 10, "check_example")
    longrepr = (
        "E   AssertionError: Missing files: 2. Release path: /tmp/release\n"
        "E   Full list:\n"
        "E   000/example/cdna.nhr\n"
    )


def test_custom_summary_uses_first_assertion_line_only():
    plugin = CustomSummaryPlugin(_DummyConfig())

    assert plugin._format_assertion_error(_DummyReport()) == (
        "FAILED::check_example::"
        "Missing files: 2. Release path: /tmp/release"
    )


def _make_report(report_type, *, outcome, longrepr):
    return report_type(
        nodeid="checks/variation/vcf.py::check_csq_in_header",
        location=("checks/variation/vcf.py", 66, "check_csq_in_header"),
        keywords={},
        outcome=outcome,
        longrepr=longrepr,
        when="call",
    )


def test_custom_summary_records_subtest_failure_with_context():
    plugin = CustomSummaryPlugin(_DummyConfig())
    subtest_report = _make_report(
        SubtestReport,
        outcome="failed",
        longrepr="E   AssertionError: CSQ field 'BIOTYPE' not found",
    )
    subtest_report.context = SubtestContext(
        msg="Evaluating presence of CSQ subfield",
        kwargs={"field": "BIOTYPE"},
    )

    plugin.pytest_runtest_logreport(subtest_report)

    assert plugin.failures == [
        "FAILED::check_csq_in_header "
        "[Evaluating presence of CSQ subfield] (field='BIOTYPE')::"
        "CSQ field 'BIOTYPE' not found"
    ]


def test_custom_summary_ignores_parent_subtest_aggregate_failure():
    plugin = CustomSummaryPlugin(_DummyConfig())
    report = _make_report(
        TestReport,
        outcome="failed",
        longrepr="contains 2 failed subtests",
    )

    plugin.pytest_runtest_logreport(report)

    assert plugin.failures == []


def test_custom_summary_does_not_mark_parent_with_failed_subtests_as_passed():
    plugin = CustomSummaryPlugin(_DummyConfig())
    subtest_report = _make_report(
        SubtestReport,
        outcome="failed",
        longrepr="E   AssertionError: CSQ field 'BIOTYPE' not found",
    )
    subtest_report.context = SubtestContext(msg=None, kwargs={})
    parent_report = _make_report(TestReport, outcome="passed", longrepr=None)

    plugin.pytest_runtest_logreport(subtest_report)
    plugin.pytest_runtest_logreport(parent_report)

    assert plugin.passed_tests == []


def test_custom_summary_preserves_regular_parent_failure():
    plugin = CustomSummaryPlugin(_DummyConfig())
    report = _make_report(
        TestReport,
        outcome="failed",
        longrepr="E   AssertionError: A regular failure",
    )

    plugin.pytest_runtest_logreport(report)

    assert plugin.failures == [
        "FAILED::check_csq_in_header::A regular failure"
    ]
