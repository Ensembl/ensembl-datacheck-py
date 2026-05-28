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

"""Unit tests for BLAST database release automation checks."""

import pytest

from ensembl.datacheck.checks.automation import (
    automation_blast_database_release as blast_release,
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


class _DummyCli:
    def __init__(self, options):
        self._options = options

    def getoption(self, name):
        return self._options.get(name)


def _write_manifest(release_path, relative_paths):
    manifest_path = release_path / "manifest"
    manifest_path.write_text(
        "".join(
            f"ignored_checksum  {relative_path}\n"
            for relative_path in relative_paths
        )
    )


def test_get_blast_database_release_base_dir_defaults_to_nfs_path():
    assert blast_release._get_blast_database_release_base_dir(
        user_cli=_DummyCli({}),
        automation_resource_config={"blast_database_release": {}},
    ) == (
        "/nfs/production/flicek/ensembl/production/blastdb"
    )


def test_get_blast_database_release_base_dir_accepts_base_dir_param():
    user_cli = _DummyCli({"--params": ["base_dir=/tmp/blastdb"]})

    assert blast_release._get_blast_database_release_base_dir(
        user_cli=user_cli,
        automation_resource_config={
            "blast_database_release": {
                "base_path": "/configured/blastdb",
            }
        },
    ) == "/tmp/blastdb"


def test_get_blast_database_release_base_dir_uses_config_base_path():
    assert blast_release._get_blast_database_release_base_dir(
        user_cli=_DummyCli({}),
        automation_resource_config={
            "blast_database_release": {
                "base_path": "/configured/blastdb",
            }
        },
    ) == "/configured/blastdb"


def test_get_blast_database_release_expected_files_uses_config():
    assert blast_release._get_blast_database_release_expected_files({
        "blast_database_release": {
            "expected_files": BLAST_DATABASE_EXPECTED_FILES,
        }
    }) == BLAST_DATABASE_EXPECTED_FILES


def test_resolve_release_path_uses_release_name_subdirectory(tmp_path):
    release_path = tmp_path / "2026_05"
    release_path.mkdir()
    (release_path / "manifest").touch()

    assert blast_release._resolve_release_path(tmp_path, "2026_05") == release_path


def test_expected_relative_file_paths_uses_first_three_uuid_characters():
    expected_paths = blast_release._expected_relative_file_paths(
        genome_uuids=["0003e543-fe3d-4cc5-beea-02d2bfaa90f4"],
        expected_files=["cdna.nhr"],
    )

    assert expected_paths == {
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr",
    }


def test_get_blast_database_release_context_builds_expected_context(monkeypatch, tmp_path):
    release_path = tmp_path / "2026_05"
    genome_uuid = "0003e543-fe3d-4cc5-beea-02d2bfaa90f4"
    expected_files = ["cdna.nhr", "cdna.nin"]
    expected_paths = blast_release._expected_relative_file_paths(
        genome_uuids=[genome_uuid],
        expected_files=expected_files,
    )
    for relative_path in expected_paths:
        file_path = release_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
    _write_manifest(release_path, sorted(expected_paths))

    monkeypatch.setattr(
        blast_release,
        "_get_live_genome_uuids",
        lambda db_session: [genome_uuid],
    )

    context = blast_release._get_blast_database_release_context(
        user_cli=_DummyCli({
            "--release_name": "2026_05",
            "--params": [f"base_dir={tmp_path}"],
        }),
        db_session=object(),
        automation_resource_config={
            "blast_database_release": {
                "expected_files": expected_files,
            }
        },
    )

    assert context["release_path"] == release_path
    assert context["genome_uuids"] == [genome_uuid]
    assert context["expected_file_paths"] == expected_paths
    assert context["actual_file_paths"] == expected_paths
    assert context["manifest_file_paths"] == expected_paths


def test_check_blast_database_release_missing_genomes_reports_missing_genomes(
    tmp_path,
):
    release_path = tmp_path / "2026_05"
    release_path.mkdir()
    missing_genome_uuid = "abc3e543-fe3d-4cc5-beea-02d2bfaa90f4"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_genomes({
            "release_path": release_path,
            "genome_uuids": [missing_genome_uuid],
        })

    error_message = str(exc_info.value)
    assert "Missing genomes" in error_message
    assert missing_genome_uuid in error_message


def test_check_blast_database_release_missing_files_reports_missing_files():
    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_files({
            "expected_file_paths": {
                "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr",
            },
            "actual_file_paths": set(),
        })

    error_message = str(exc_info.value)
    assert "Missing files" in error_message
    assert (
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr"
        in error_message
    )


def test_check_blast_database_release_extra_files_reports_extra_files():
    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_extra_files({
            "expected_file_paths": set(),
            "actual_file_paths": {
                "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr",
            },
        })

    error_message = str(exc_info.value)
    assert "Extra files" in error_message
    assert (
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr"
        in error_message
    )


def test_check_blast_database_release_missing_manifest_files_reports_missing_entries():
    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_manifest_files({
            "expected_file_paths": {
                "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr",
            },
            "manifest_file_paths": set(),
            "malformed_manifest_lines": [],
        })

    error_message = str(exc_info.value)
    assert "Missing manifest files" in error_message
    assert (
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr"
        in error_message
    )


def test_check_blast_database_release_extra_manifest_files_reports_extra_entries():
    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_extra_manifest_files({
            "expected_file_paths": set(),
            "manifest_file_paths": {
                "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr",
            },
        })

    error_message = str(exc_info.value)
    assert "Extra manifest files" in error_message
    assert (
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr"
        in error_message
    )
