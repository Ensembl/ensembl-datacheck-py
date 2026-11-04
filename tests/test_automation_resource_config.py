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

"""Unit tests for automation resource config loading."""

import json

from ensembl.datacheck.checks.automation import conftest as automation_conftest


class _DummyConfig:
    def __init__(self, options):
        self._options = options

    def getoption(self, name):
        return self._options.get(name)


class _DummyRequest:
    def __init__(self, options):
        self.config = _DummyConfig(options)


def _build_config(config_path=None, environ=None, params=None, use_alt=False):
    return automation_conftest._build_automation_resource_config(
        config_path=config_path,
        environ=environ or {},
        raw_params=params or [],
        use_alt=use_alt,
    )


def test_automation_resource_config_uses_bundled_config_by_default():
    resource_config = _build_config()

    assert "blast_database_release" in resource_config
    assert resource_config["blast_database_release"]["expected_files"]


def test_automation_resource_config_supports_historical_relative_resource_config_path():
    resource_config = _build_config(
        config_path=(
            "src/ensembl/datacheck/checks/automation/resource_config.json"
        )
    )

    assert "blast_database_release" in resource_config
    assert resource_config["blast_database_release"]["expected_files"]


def test_automation_resource_config_merges_json_override(tmp_path):
    config_path = tmp_path / "resource_config.json"
    config_path.write_text(json.dumps({
        "blast_database_files": {"base_path": "/specified/blastdb"},
        "custom_resource": {"base_path": "/tmp"},
    }))

    resource_config = _build_config(config_path=str(config_path))

    assert resource_config["blast_database_files"]["base_path"] == (
        "/specified/blastdb"
    )
    assert resource_config["blast_database_files"]["expected_files"]
    assert resource_config["custom_resource"] == {"base_path": "/tmp"}


def test_automation_resource_config_applies_environment_override(tmp_path):
    config_path = tmp_path / "resource_config.json"
    config_path.write_text(json.dumps({
        "blast_database_files": {"base_path": "/specified/blastdb"},
    }))

    resource_config = _build_config(
        config_path=str(config_path),
        environ={
            "ENSEMBL_DATACHECK_BLAST_DATABASE_FILES_BASE_PATH": "/env/blastdb",
        },
    )

    assert resource_config["blast_database_files"]["base_path"] == "/env/blastdb"


def test_automation_resource_config_applies_cli_override_over_environment(tmp_path):
    config_path = tmp_path / "resource_config.json"
    config_path.write_text(json.dumps({
        "blast_database_files": {"base_path": "/specified/blastdb"},
    }))

    resource_config = _build_config(
        config_path=str(config_path),
        environ={
            "ENSEMBL_DATACHECK_BLAST_DATABASE_FILES_BASE_PATH": "/env/blastdb",
        },
        params=["blast_database_files.base_path=/cli/blastdb"],
    )

    assert resource_config["blast_database_files"]["base_path"] == "/cli/blastdb"


def test_automation_resource_config_use_alt_sets_use_alt_flag(tmp_path):
    config_path = tmp_path / "resource_config.json"
    config_path.write_text(json.dumps({
        "blast_database_files": {
            "base_path": "/specified/blastdb",
            "subfolder": "blast_db",
        },
    }))

    resource_config = _build_config(config_path=str(config_path), use_alt=True)

    assert resource_config["blast_database_files"]["base_path"] == "/specified/blastdb"
    assert resource_config["blast_database_files"]["use_alt_base_path"] is True


def test_automation_resource_config_use_alt_does_not_affect_resources_without_subfolder(
    tmp_path,
):
    config_path = tmp_path / "resource_config.json"
    config_path.write_text(json.dumps({
        "resource_without_subfolder": {
            "base_path": "/specified/release",
        },
    }))

    resource_config = _build_config(config_path=str(config_path), use_alt=True)

    assert resource_config["resource_without_subfolder"]["base_path"] == "/specified/release"
    assert "use_alt_base_path" not in resource_config["resource_without_subfolder"]


def test_automation_resource_config_cli_base_path_override_wins_over_use_alt(tmp_path):
    config_path = tmp_path / "resource_config.json"
    config_path.write_text(json.dumps({
        "blast_database_files": {
            "base_path": "/specified/blastdb",
            "subfolder": "blast_db",
        },
    }))

    resource_config = _build_config(
        config_path=str(config_path),
        params=["blast_database_files.base_path=/cli/blastdb"],
        use_alt=True,
    )

    assert resource_config["blast_database_files"]["base_path"] == "/cli/blastdb"
    assert resource_config["blast_database_files"]["use_alt_base_path"] is True


def test_automation_resource_config_accepts_double_underscore_environment_key():
    resource_config = _build_config(
        environ={
            "ENSEMBL_DATACHECK_BLAST_DATABASE_RELEASE__BASE_PATH": (
                "/env/release"
            ),
        },
    )

    assert resource_config["blast_database_release"]["base_path"] == "/env/release"


def test_automation_resource_config_keeps_release_base_dir_cli_alias():
    resource_config = _build_config(params=["base_dir=/cli/release"])

    assert resource_config["blast_database_release"]["base_path"] == "/cli/release"


def test_automation_resource_config_fixture_uses_request_options(monkeypatch):
    monkeypatch.setenv(
        "ENSEMBL_DATACHECK_BLAST_DATABASE_FILES_BASE_PATH",
        "/env/blastdb",
    )

    resource_config = automation_conftest.automation_resource_config.__wrapped__(
        _DummyRequest({
            "--automation_resource_config": None,
            "--params": ["blast_database_files.base_path=/cli/blastdb"],
            "use_alt": False,
        })
    )

    assert resource_config["blast_database_files"]["base_path"] == "/cli/blastdb"


def test_automation_resource_config_supports_track_api_files_check_release_info_override():
    resource_config = _build_config(
        params=["track_api_files.check_release_info=true"]
    )

    assert resource_config["track_api_files"]["check_release_info"] == "true"


def test_automation_resource_config_supports_track_api_optional_dataset_cutoff_override():
    resource_config = _build_config(
        params=["track_api_files.ignore_attached_optional_datasets_from_release=29"]
    )

    assert (
        resource_config["track_api_files"]["ignore_attached_optional_datasets_from_release"]
        == "29"
    )


def test_refget_index_uses_generic_runtime_placeholder():
    config = _build_config(environ={"REFGET_INDEX_FILE": "/local/indexdb.tkh"})
    assert config["refget_index"]["index_file"] == "/local/indexdb.tkh"
    assert config["refget_index"]["mongo_resource"] == "thoas_mongo_internal_resource_uri"


def test_refget_index_placeholder_can_map_a_different_environment():
    config = _build_config(environ={"REFGET_INDEX_FILE": "/production/refget/index.tkh"})
    assert config["refget_index"]["index_file"] == "/production/refget/index.tkh"


def test_refget_index_config_file_overrides_bundled_placeholder(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"refget_index": {"index_file": "/file/index.tkh"}}))
    config = _build_config(config_path=str(path), environ={"REFGET_INDEX_FILE": "/generic/index.tkh"})
    assert config["refget_index"]["index_file"] == "/file/index.tkh"


def test_refget_index_environment_override_wins_over_generic_placeholder():
    config = _build_config(environ={
        "REFGET_INDEX_FILE": "/generic/index.tkh",
        "ENSEMBL_DATACHECK_REFGET_INDEX_INDEX_FILE": "/override/index.tkh",
    })
    assert config["refget_index"]["index_file"] == "/override/index.tkh"


def test_refget_index_cli_override_does_not_require_placeholder_environment():
    config = _build_config(params=["refget_index.index_file=/cli/index.tkh"])
    assert config["refget_index"]["index_file"] == "/cli/index.tkh"
    assert automation_conftest.refget_index_config.__wrapped__(config) is config["refget_index"]


def test_refget_index_missing_environment_gives_actionable_error():
    import pytest
    config = _build_config()
    assert config["refget_index"]["index_file"] == "${REFGET_INDEX_FILE}"
    with pytest.raises(AssertionError, match="Set REFGET_INDEX_FILE or override refget_index.index_file"):
        automation_conftest.refget_index_config.__wrapped__(config)


def test_environment_expansion_handles_nested_values_without_mutation():
    original = {"path": "${BASE_DUMPS}/refget", "files": ["${REFGET_INDEX_FILE}", None, 1, False],
                "uri": "mongodb://user:literal$token@example.invalid", "unset": "${NOT_CONFIGURED}"}
    expanded = automation_conftest._expand_environment_placeholders(original, {
        "BASE_DUMPS": "/env/dumps", "REFGET_INDEX_FILE": "/env/index.tkh",
    })
    assert expanded["path"] == "/env/dumps/refget"
    assert expanded["files"] == ["/env/index.tkh", None, 1, False]
    assert expanded["uri"] == original["uri"]
    assert expanded["unset"] == "${NOT_CONFIGURED}"
    assert original["path"] == "${BASE_DUMPS}/refget"
