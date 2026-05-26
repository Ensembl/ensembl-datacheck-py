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

"""Unit tests for FTP automation checks."""

import pytest

from ensembl.datacheck.checks.automation import automation_ftp_expected_files as ftp_checks
from ensembl.datacheck.checks.automation.utils import validate_expected_files


class _DummyCli:
    def __init__(self, options):
        self._options = options

    def getoption(self, name):
        return self._options.get(name)


def test_check_ftp_resource_accepts_list_of_dataset_paths(monkeypatch):
    captured = {}

    def _fake_get_ftp_paths(metadata_uri, taxonomy_uri, genome_uuid):
        assert metadata_uri
        assert taxonomy_uri
        assert genome_uuid == "uuid-1"
        return [{"dataset_type": "genebuild", "path": "species/path/geneset/2026_05"}]

    def _fake_validate_expected_files(base_path, relative_path, expected_files, resource_label):
        captured["base_path"] = base_path
        captured["relative_path"] = relative_path
        captured["expected_files"] = expected_files
        captured["resource_label"] = resource_label

    monkeypatch.setattr(ftp_checks, "get_ftp_paths", _fake_get_ftp_paths)
    monkeypatch.setattr(ftp_checks, "validate_expected_files", _fake_validate_expected_files)

    ftp_checks._check_ftp_resource(
        user_cli=_DummyCli({
            "--database": "sqlite:///metadata.db",
            "--taxonomy_database": "sqlite:///taxonomy.db",
        }),
        genomes={"genome_uuid": "uuid-1"},
        automation_resource_config={
            "ftp_dumps_geneset": {
                "base_path": "/base",
                "expected_files": ["cdna.fa.bgz"],
            }
        },
        resource_key="ftp_dumps_geneset",
        dataset_name="genebuild",
    )

    assert captured["base_path"] == "/base"
    assert captured["relative_path"] == "species/path/geneset/2026_05"
    assert captured["expected_files"] == ["cdna.fa.bgz"]
    assert "ftp_dumps_geneset" in captured["resource_label"]


def test_check_ftp_resource_fails_with_clear_message_when_dataset_missing(monkeypatch):
    def _fake_get_ftp_paths(metadata_uri, taxonomy_uri, genome_uuid):
        return [{"dataset_type": "genebuild", "path": "species/path/geneset/2026_05"}]

    monkeypatch.setattr(ftp_checks, "get_ftp_paths", _fake_get_ftp_paths)

    with pytest.raises(AssertionError, match="Dataset type 'assembly' not found"):
        ftp_checks._check_ftp_resource(
            user_cli=_DummyCli({
                "--database": "sqlite:///metadata.db",
                "--taxonomy_database": "sqlite:///taxonomy.db",
            }),
            genomes={"genome_uuid": "uuid-1"},
            automation_resource_config={
                "ftp_dumps_genomes": {
                    "base_path": "/base",
                    "expected_files": ["unmasked.fa.bgz"],
                }
            },
            resource_key="ftp_dumps_genomes",
            dataset_name="assembly",
        )


def test_validate_expected_files_accepts_file_relative_path_with_sidecar(tmp_path):
    resource_dir = tmp_path / "Senecio_sylvaticus" / "GCA_965199645.1" / "vep" / "ensembl" / "geneset" / "2026_02"
    resource_dir.mkdir(parents=True)
    (resource_dir / "genes.gff3.bgz").write_text("")
    (resource_dir / "genes.gff3.bgz.csi").write_text("")

    validate_expected_files(
        base_path=tmp_path,
        relative_path="Senecio_sylvaticus/GCA_965199645.1/vep/ensembl/geneset/2026_02/genes.gff3.bgz",
        expected_files=["genes.gff3.bgz", "genes.gff3.bgz.csi"],
        resource_label="ftp_dumps_vep_geneset",
    )


def test_validate_expected_files_reports_missing_sidecar_for_file_relative_path(tmp_path):
    resource_dir = tmp_path / "Senecio_sylvaticus" / "GCA_965199645.1" / "vep" / "ensembl" / "geneset" / "2026_02"
    resource_dir.mkdir(parents=True)
    (resource_dir / "genes.gff3.bgz").write_text("")

    with pytest.raises(AssertionError, match="genes.gff3.bgz.csi"):
        validate_expected_files(
            base_path=tmp_path,
            relative_path="Senecio_sylvaticus/GCA_965199645.1/vep/ensembl/geneset/2026_02/genes.gff3.bgz",
            expected_files=["genes.gff3.bgz", "genes.gff3.bgz.csi"],
            resource_label="ftp_dumps_vep_geneset",
        )
