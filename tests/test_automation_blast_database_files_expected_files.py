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

"""Unit tests for BLAST database file automation checks."""

import json
from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation import (
    automation_blast_database_expected_files as blast_db_checks,
)
from ensembl.datacheck.checks.automation.automation_blast_database_expected_files import (
    _resolve_blast_database_files_relative_path,
)

BLAST_DATABASE_EXPECTED_FILES = [
    "cdna.nhr",
    "cds.nhr",
    "pep.phr",
    "softmasked.nhr",
    "unmasked.nhr",
    "cdna.nin",
    "cds.nin",
    "pep.pin",
    "softmasked.nin",
    "unmasked.nin",
    "cdna.njs",
    "cds.njs",
    "pep.pjs",
    "softmasked.njs",
    "unmasked.njs",
    "cdna.nsq",
    "cds.nsq",
    "pep.psq",
    "softmasked.nsq",
    "unmasked.nsq",
]


def test_resolve_blast_database_files_relative_path_supports_direct_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "blast_db" / "release_22" / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_blast_database_files_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
        subfolder="blast_db",
    )

    assert relative_path == Path("blast_db") / "release_22" / genome_uuid


def test_resolve_blast_database_files_relative_path_supports_one_level_nested_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "blast_db" / "release_22" / "22_4" / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_blast_database_files_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
        subfolder="blast_db",
    )

    assert relative_path == Path("blast_db") / "release_22" / "22_4" / genome_uuid


def test_resolve_blast_database_files_relative_path_supports_alt_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    uuid_prefix = genome_uuid[:3]
    (tmp_path / "release-22" / "blast_db" / uuid_prefix / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_blast_database_files_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
        subfolder="blast_db",
        use_alt_base_path=True,
    )

    assert relative_path == Path("release-22") / "blast_db" / uuid_prefix / genome_uuid


def test_resolve_blast_database_files_relative_path_fails_on_multiple_nested_matches(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "blast_db" / "release_22" / "22_0" / genome_uuid).mkdir(parents=True)
    (tmp_path / "blast_db" / "release_22" / "22_1" / genome_uuid).mkdir(parents=True)

    with pytest.raises(
        AssertionError,
        match="Multiple blast_database_files directories found",
    ):
        _resolve_blast_database_files_relative_path(
            base_path=str(tmp_path),
            release_name=22,
            genome_uuid=genome_uuid,
            subfolder="blast_db",
        )


def test_check_blast_database_files_expected_files_uses_configured_paths(monkeypatch, tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "blast_db" / "release_22" / genome_uuid).mkdir(parents=True)
    captured = {}

    def _fake_validate_expected_files(base_path, relative_path, expected_files, resource_label):
        captured["base_path"] = base_path
        captured["relative_path"] = relative_path
        captured["expected_files"] = expected_files
        captured["resource_label"] = resource_label

    monkeypatch.setattr(
        blast_db_checks,
        "validate_expected_files",
        _fake_validate_expected_files,
    )

    blast_db_checks.check_blast_database_files_expected_files(
        genomes={"genome_uuid": genome_uuid, "release_name": 22},
        automation_resource_config={
            "blast_database_files": {
                "base_path": str(tmp_path),
                "subfolder": "blast_db",
                "expected_files": BLAST_DATABASE_EXPECTED_FILES,
            }
        },
    )

    assert captured["base_path"] == str(tmp_path)
    assert captured["relative_path"] == Path("blast_db") / "release_22" / genome_uuid
    assert captured["expected_files"] == BLAST_DATABASE_EXPECTED_FILES
    assert "blast_database_files" in captured["resource_label"]


def test_check_blast_database_files_expected_files_uses_alt_layout(monkeypatch, tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    uuid_prefix = genome_uuid[:3]
    (tmp_path / "release-22" / "blast_db" / uuid_prefix / genome_uuid).mkdir(parents=True)
    captured = {}

    def _fake_validate_expected_files(base_path, relative_path, expected_files, resource_label):
        captured["base_path"] = base_path
        captured["relative_path"] = relative_path
        captured["expected_files"] = expected_files
        captured["resource_label"] = resource_label

    monkeypatch.setattr(
        blast_db_checks,
        "validate_expected_files",
        _fake_validate_expected_files,
    )

    blast_db_checks.check_blast_database_files_expected_files(
        genomes={"genome_uuid": genome_uuid, "release_name": 22},
        automation_resource_config={
            "blast_database_files": {
                "base_path": str(tmp_path),
                "subfolder": "blast_db",
                "use_alt_base_path": True,
                "expected_files": BLAST_DATABASE_EXPECTED_FILES,
            }
        },
    )

    assert captured["base_path"] == str(tmp_path)
    assert captured["relative_path"] == Path("release-22") / "blast_db" / uuid_prefix / genome_uuid
    assert captured["expected_files"] == BLAST_DATABASE_EXPECTED_FILES


def test_resource_config_defines_blast_database_files():
    config_path = (
        Path(__file__).parents[1]
        / "src"
        / "ensembl"
        / "datacheck"
        / "checks"
        / "automation"
        / "resource_config.json"
    )
    config = json.loads(config_path.read_text())

    assert config["blast_database_files"]["base_path"] == (
        "/hps/nobackup/flicek/ensembl/production/ensembl_dumps"
    )
    assert config["blast_database_files"]["subfolder"] == "blast_db"
    assert "alt_base_path" not in config["blast_database_files"]
    assert config["blast_database_files"]["expected_files"] == BLAST_DATABASE_EXPECTED_FILES
