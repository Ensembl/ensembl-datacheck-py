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


def _assert_discrepancy_failure(
    exc_info,
    tmp_path,
    label,
    expected_item,
    expected_count=1,
):
    error_message = str(exc_info.value)
    error_lines = error_message.splitlines()

    assert error_lines[0] == (
        f"{label}: {expected_count}. Release path: {tmp_path / '2026_05'}"
    )
    assert error_lines[1] == "Full list:"
    assert expected_item in error_message
    assert not list(tmp_path.glob("blast_database_release_*.txt"))


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


def test_resolve_release_path_uses_base_dir(tmp_path):
    assert blast_release._resolve_release_path(tmp_path) == tmp_path


def test_resolve_release_path_requires_existing_directory(tmp_path):
    missing_path = tmp_path / "missing"

    with pytest.raises(AssertionError) as exc_info:
        blast_release._resolve_release_path(missing_path)

    assert "BLAST database release directory does not exist" in str(exc_info.value)


def test_expected_relative_file_paths_uses_first_three_uuid_characters():
    expected_paths = blast_release._expected_relative_file_paths(
        genome_uuids=["0003e543-fe3d-4cc5-beea-02d2bfaa90f4"],
        expected_files=["cdna.nhr"],
    )

    assert expected_paths == {
        "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr",
    }


def test_get_blast_database_release_context_builds_expected_context(monkeypatch, tmp_path):
    release_path = tmp_path / "blastdb"
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
            "--params": [f"base_dir={release_path}"],
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
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    release_path = tmp_path / "2026_05"
    release_path.mkdir()
    missing_genome_uuid = "abc3e543-fe3d-4cc5-beea-02d2bfaa90f4"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_genomes({
            "release_path": release_path,
            "genome_uuids": [missing_genome_uuid],
        })

    _assert_discrepancy_failure(
        exc_info=exc_info,
        tmp_path=tmp_path,
        label="Missing genomes",
        expected_item=missing_genome_uuid,
    )


def test_check_blast_database_release_missing_files_reports_missing_files(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    missing_file = "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_files({
            "release_path": tmp_path / "2026_05",
            "expected_file_paths": {missing_file},
            "actual_file_paths": set(),
        })

    _assert_discrepancy_failure(
        exc_info=exc_info,
        tmp_path=tmp_path,
        label="Missing files",
        expected_item=missing_file,
    )


def test_check_blast_database_release_extra_files_reports_extra_files(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    extra_file = "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_extra_files({
            "release_path": tmp_path / "2026_05",
            "expected_file_paths": set(),
            "actual_file_paths": {extra_file},
        })

    _assert_discrepancy_failure(
        exc_info=exc_info,
        tmp_path=tmp_path,
        label="Extra files",
        expected_item=extra_file,
    )


def test_check_blast_database_release_missing_manifest_files_reports_missing_entries(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    missing_file = "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/cdna.nhr"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_manifest_files({
            "release_path": tmp_path / "2026_05",
            "expected_file_paths": {missing_file},
            "manifest_file_paths": set(),
            "malformed_manifest_lines": [],
        })

    _assert_discrepancy_failure(
        exc_info=exc_info,
        tmp_path=tmp_path,
        label="Missing manifest files",
        expected_item=missing_file,
    )


def test_check_blast_database_release_missing_manifest_files_reports_malformed_lines(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    malformed_line = "12: missing_path_column"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_missing_manifest_files({
            "release_path": tmp_path / "2026_05",
            "expected_file_paths": set(),
            "manifest_file_paths": set(),
            "malformed_manifest_lines": [malformed_line],
        })

    _assert_discrepancy_failure(
        exc_info=exc_info,
        tmp_path=tmp_path,
        label="Malformed manifest lines",
        expected_item=malformed_line,
    )


def test_check_blast_database_release_extra_manifest_files_reports_extra_entries(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    extra_file = "000/0003e543-fe3d-4cc5-beea-02d2bfaa90f4/extra.nhr"

    with pytest.raises(AssertionError) as exc_info:
        blast_release.check_blast_database_release_extra_manifest_files({
            "release_path": tmp_path / "2026_05",
            "expected_file_paths": set(),
            "manifest_file_paths": {extra_file},
        })

    _assert_discrepancy_failure(
        exc_info=exc_info,
        tmp_path=tmp_path,
        label="Extra manifest files",
        expected_item=extra_file,
    )
