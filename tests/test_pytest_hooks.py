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

"""Unit tests for pytest hook helpers."""

import json
import os
import subprocess
import sys

import pytest

from ensembl.datacheck.plugins.pytest_hooks import (
    _configure_json_report_defaults,
    _format_json_subtest_error,
    _get_json_report_failure_details,
    _get_json_report_error_info,
    pytest_json_modifyreport,
)


class _DummyConfig:
    class _Options:
        pass

    def __init__(self, json_report, json_report_indent):
        self.option = self._Options()
        self.option.json_report = json_report
        self.option.json_report_indent = json_report_indent


def test_configure_json_report_defaults_sets_pretty_indent():
    config = _DummyConfig(json_report=True, json_report_indent=None)

    _configure_json_report_defaults(config)

    assert config.option.json_report_indent == 2


def test_configure_json_report_defaults_keeps_explicit_indent():
    config = _DummyConfig(json_report=True, json_report_indent=4)

    _configure_json_report_defaults(config)

    assert config.option.json_report_indent == 4


def test_configure_json_report_defaults_ignores_non_json_report_runs():
    config = _DummyConfig(json_report=False, json_report_indent=None)

    _configure_json_report_defaults(config)

    assert config.option.json_report_indent is None


def test_get_json_report_error_info_prefers_short_crash_message():
    test_report = {
        "call": {
            "crash": {
                "message": (
                    "AssertionError: Missing files: 2. "
                    "Release path: /tmp/release"
                ),
            },
            "longrepr": (
                "E   AssertionError: Missing files: 2. "
                "Release path: /tmp/release\n"
                "E   Full list:\n"
                "E   000/example/cdna.nhr\n"
            ),
        }
    }

    assert _get_json_report_error_info(test_report) == (
        "Missing files: 2. Release path: /tmp/release"
    )


def test_get_json_report_error_info_falls_back_to_assertion_message():
    test_report = {
        "call": {
            "longrepr": (
                "E   AssertionError: Missing files: 2. "
                "Release path: /tmp/release\n"
                "E   Full list:\n"
                "E   000/example/cdna.nhr\n"
            ),
        }
    }

    assert _get_json_report_error_info(test_report) == (
        "Missing files: 2. Release path: /tmp/release"
    )


def test_format_json_subtest_error_groups_cases_by_subtest_message():
    failed_subtests = [
        {
            "message": "Evaluating presence of CSQ subfield",
            "parameters": "(field='AF', spec={'species': 'homo_sapiens'})",
        },
        {
            "message": "Evaluating presence of CSQ subfield",
            "parameters": "(field='AFR_AF', spec={'species': 'homo_sapiens'})",
        },
        {
            "message": "Evaluating presence of CSQ subfield",
            "parameters": "(field='AMR_AF', spec={'species': 'homo_sapiens'})",
        },
        {
            "message": "Evaluating presence of CSQ subfield",
            "parameters": "(field='EAS_AF', spec={'species': 'homo_sapiens'})",
        },
    ]

    assert _format_json_subtest_error(failed_subtests) == (
        "1 subtests failed on 4 cases. "
        "Evaluating presence of CSQ subfield failed on "
        "[(field='AF', spec={'species': 'homo_sapiens'}), "
        "(field='AFR_AF', spec={'species': 'homo_sapiens'}), "
        "(field='AMR_AF', spec={'species': 'homo_sapiens'}), "
        "(field='EAS_AF', spec={'species': 'homo_sapiens'})]"
    )


def test_get_json_report_failure_details_parses_datacheck_assertion():
    test_report = {
        "call": {
            "longrepr": (
                "E   AssertionError: Missing files: 2. "
                "Release path: /tmp/release\n"
                "E   Full list:\n"
                "E   000/example/cdna.nhr\n"
                "E   000/example/cdna.nin\n"
            ),
        }
    }

    assert _get_json_report_failure_details(test_report) == {
        "label": "Missing files",
        "count": 2,
        "release_path": "/tmp/release",
        "items": [
            "000/example/cdna.nhr",
            "000/example/cdna.nin",
        ],
    }


def test_get_json_report_failure_details_parses_raw_assertion_body():
    test_report = {
        "call": {
            "longrepr": (
                "AssertionError: Extra files: 1. "
                "Release path: /tmp/release\n"
                "Full list:\n"
                "000/example/extra.nhr\n"
            ),
        }
    }

    assert _get_json_report_failure_details(test_report) == {
        "label": "Extra files",
        "count": 1,
        "release_path": "/tmp/release",
        "items": [
            "000/example/extra.nhr",
        ],
    }


def test_get_json_report_failure_details_ignores_non_datacheck_assertion():
    test_report = {
        "call": {
            "longrepr": "E   AssertionError: plain failure",
        }
    }

    assert _get_json_report_failure_details(test_report) is None


def test_pytest_json_modifyreport_uses_short_error_and_structured_details():
    json_report = {
        "tests": [
            {
                "nodeid": "checks/automation/test.py::check_example",
                "outcome": "failed",
                "metadata": {"tag": "test_tag"},
                "call": {
                    "crash": {
                        "message": (
                            "AssertionError: Missing files: 1. "
                            "Release path: /tmp/release"
                        ),
                    },
                    "longrepr": (
                        "E   AssertionError: Missing files: 1. "
                        "Release path: /tmp/release\n"
                        "E   Full list:\n"
                        "E   000/example/cdna.nhr\n"
                    ),
                },
            }
        ],
        "collectors": [],
        "summary": {"failed": 1},
    }

    pytest_json_modifyreport(json_report)

    assert json_report["results"]["All"]["check_example"] == {
        "status": "failed",
        "error": "Missing files: 1. Release path: /tmp/release",
        "details": {
            "label": "Missing files",
            "count": 1,
            "release_path": "/tmp/release",
            "items": ["000/example/cdna.nhr"],
        },
    }
    assert json_report["status"] == "failed"
    assert json_report["tag"] == "test_tag"


def test_pytest_json_modifyreport_uses_subtest_error_summary():
    json_report = {
        "tests": [
            {
                "nodeid": "checks/variation/vcf.py::check_csq_in_header",
                "outcome": "failed",
                "metadata": {"tag": "test_tag"},
                "call": {"longrepr": "contains 2 failed subtests"},
                "_datacheck_failed_subtests": [
                    {
                        "message": "Evaluating presence of CSQ subfield",
                        "parameters": "(field='AF')",
                    },
                    {
                        "message": "Evaluating presence of CSQ subfield",
                        "parameters": "(field='AFR_AF')",
                    },
                ],
            }
        ],
        "collectors": [],
        "summary": {"failed": 1},
    }

    pytest_json_modifyreport(json_report)

    assert json_report["results"]["All"]["check_csq_in_header"] == {
        "status": "failed",
        "error": (
            "1 subtests failed on 2 cases. "
            "Evaluating presence of CSQ subfield failed on "
            "[(field='AF'), (field='AFR_AF')]"
        ),
    }


@pytest.mark.parametrize("workers", [0, 2])
@pytest.mark.parametrize("native_output", [False, True])
def test_subtest_failures_reach_json_report(tmp_path, workers, native_output):
    check = tmp_path / "sample_check.py"
    check.write_text(
        "def check_csq_in_header(subtests):\n"
        "    for field in ('AF', 'AFR_AF', 'AMR_AF', 'EAS_AF'):\n"
        "        with subtests.test('Evaluating presence of CSQ subfield', "
        "field=field, spec={'species': 'homo_sapiens'}):\n"
        "            assert False, f'missing {field}'\n"
        "\n"
        "def check_mixed_failure(subtests):\n"
        "    with subtests.test('Subtest failure', field='AF'):\n"
        "        assert False\n"
        "    assert False, 'parent assertion'\n"
    )
    report_path = tmp_path / "report.json"
    command = [
        sys.executable, "-m", "ensembl.datacheck.runner",
        "--test", str(check.with_suffix("")),
        "--json-report", f"--json-report-file={report_path}",
        "--no-cache-results", "--no-warnings", "-q",
    ]
    if workers:
        command.extend(["-n", str(workers)])
    if native_output:
        command.append("--native-output")
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)

    run = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)

    assert run.returncode == 1, run.stdout + run.stderr
    report = json.loads(report_path.read_text())
    result = report["results"]["All"]["check_csq_in_header"]
    assert result == {
        "status": "failed",
        "error": (
            "1 subtests failed on 4 cases. "
            "Evaluating presence of CSQ subfield failed on "
            "[(field='AF', spec={'species': 'homo_sapiens'}), "
            "(field='AFR_AF', spec={'species': 'homo_sapiens'}), "
            "(field='AMR_AF', spec={'species': 'homo_sapiens'}), "
            "(field='EAS_AF', spec={'species': 'homo_sapiens'})]"
        ),
    }
    mixed = report["results"]["All"]["check_mixed_failure"]
    assert mixed["status"] == "failed"
    assert "Subtest failure failed on [(field='AF')]" in mixed["error"]
    assert "parent assertion" in mixed["error"]
