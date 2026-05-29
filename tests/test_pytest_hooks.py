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

from ensembl.datacheck.plugins.pytest_hooks import (
    _configure_json_report_defaults,
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
