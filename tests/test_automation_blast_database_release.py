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


def test_assert_blast_database_release_is_complete_passes_for_exact_release(tmp_path):
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

    blast_release._assert_blast_database_release_is_complete(
        release_path=release_path,
        genome_uuids=[genome_uuid],
        expected_files=expected_files,
    )


def test_assert_blast_database_release_reports_missing_genomes_missing_files_and_extra_files(
    tmp_path,
):
    release_path = tmp_path / "2026_05"
    release_path.mkdir()
    present_genome_uuid = "0003e543-fe3d-4cc5-beea-02d2bfaa90f4"
    missing_genome_uuid = "abc3e543-fe3d-4cc5-beea-02d2bfaa90f4"
    present_file = release_path / "000" / present_genome_uuid / "cdna.nhr"
    present_file.parent.mkdir(parents=True)
    present_file.touch()
    extra_file = release_path / "000" / present_genome_uuid / "extra.nhr"
    extra_file.touch()
    _write_manifest(
        release_path,
        ["000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr"],
    )

    with pytest.raises(AssertionError) as exc_info:
        blast_release._assert_blast_database_release_is_complete(
            release_path=release_path,
            genome_uuids=[present_genome_uuid, missing_genome_uuid],
            expected_files=["cdna.nhr", "cdna.nin"],
        )

    error_message = str(exc_info.value)
    assert "Missing genomes" in error_message
    assert missing_genome_uuid in error_message
    assert "Missing files" in error_message
    assert (
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nin"
        in error_message
    )
    assert "Extra files" in error_message
    assert (
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr"
        in error_message
    )


def test_check_blast_database_release_uses_live_genomes_and_cli_inputs(
    monkeypatch,
    tmp_path,
):
    release_path = tmp_path / "2026_05"
    release_path.mkdir()
    (release_path / "manifest").touch()
    captured = {}

    monkeypatch.setattr(
        blast_release,
        "_get_live_genome_uuids",
        lambda db_session: ["0003e543-fe3d-4cc5-beea-02d2bfaa90f4"],
    )

    def _fake_assert_blast_database_release_is_complete(
        release_path,
        genome_uuids,
        expected_files,
    ):
        captured["release_path"] = release_path
        captured["genome_uuids"] = genome_uuids
        captured["expected_files"] = expected_files

    monkeypatch.setattr(
        blast_release,
        "_assert_blast_database_release_is_complete",
        _fake_assert_blast_database_release_is_complete,
    )

    blast_release.check_blast_database_release(
        user_cli=_DummyCli({
            "--release_name": "2026_05",
            "--params": [f"base_dir={tmp_path}"],
        }),
        db_session=object(),
        automation_resource_config={
            "blast_database_release": {
                "expected_files": BLAST_DATABASE_EXPECTED_FILES,
            }
        },
    )

    assert captured["release_path"] == release_path
    assert captured["genome_uuids"] == ["0003e543-fe3d-4cc5-beea-02d2bfaa90f4"]
    assert captured["expected_files"] == BLAST_DATABASE_EXPECTED_FILES
