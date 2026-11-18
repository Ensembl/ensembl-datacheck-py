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

"""Tests for the JSON validator datacheck."""

import json

import pytest

from ensembl.datacheck.checks import json_validator


def _payload():
    return {
        "data_type": "rnaseq",
        "display_label": "DRR169427",
        "metadata": {
            "genotype": {
                "value": "Wild Type",
                "provenance": {
                    "source": "ENA BioSample",
                    "source_field": "genotype",
                    "source_id": "SAMD00156646",
                    "source_value": "wild type",
                    "normalization": "explicit_display_label_rule",
                },
            },
            "organism": {
                "value": "Sus scrofa",
                "provenance": {
                    "source": "ENA BioSample",
                    "source_field": "organism",
                    "source_id": "SAMD00156646",
                    "source_value": "Sus scrofa",
                },
            },
            "sex": {
                "value": "Female",
                "provenance": {
                    "source": "ENA BioSample",
                    "source_field": "sex",
                    "source_id": "SAMD00156646",
                    "source_value": "female",
                    "normalization": "explicit_display_label_rule",
                },
            },
            "study": {
                "value": "PRJDB7878",
                "provenance": {
                    "source": "ENA run metadata",
                    "source_field": "study_accession",
                    "source_id": "DRR169427",
                    "source_value": "PRJDB7878",
                },
            },
            "tissue": {
                "value": "MGC",
                "provenance": {
                    "source": "ENA BioSample",
                    "source_field": "tissue",
                    "source_id": "SAMD00156646",
                    "source_value": "MGC",
                },
            },
        },
        "provenance": {
            "biosample_accession": "SAMD00156646",
            "run_accessions": ["DRR169427"],
            "study_accession": "PRJDB7878",
        },
        "schema_version": "transcriptomic-selection-0.3.1",
        "selection_id": "sus_scrofa_pilot_run_DRR169427_coverage_forward",
        "selection_hierarchy": ["tissue", "biosample", "run"],
        "selection_level": "run",
        "target_genome": {
            "assembly": "GCA_000003025.6",
            "assembly_uuid": "da38d82b-df50-419b-af74-886463b7bfa3",
            "species": "Sus scrofa",
        },
    }


def test_check_validity_accepts_transcriptomic_selection_payload(tmp_path):
    target_file = tmp_path / "selection.json"
    target_file.write_text(json.dumps(_payload()))

    json_validator.check_validity(target_file, {"schema": "transcriptomic_selection"})


def test_check_validity_reports_schema_errors(tmp_path):
    payload = _payload()
    del payload["target_genome"]["assembly_uuid"]
    target_file = tmp_path / "selection.json"
    target_file.write_text(json.dumps(payload))

    with pytest.raises(AssertionError, match="assembly_uuid"):
        json_validator.check_validity(target_file, {"schema": "transcriptomic_selection"})


def test_check_validity_requires_known_schema(tmp_path):
    target_file = tmp_path / "selection.json"
    target_file.write_text(json.dumps(_payload()))

    with pytest.raises(AssertionError, match="Unknown JSON schema"):
        json_validator.check_validity(target_file, {"schema": "unknown"})


def test_load_file_handover_schemas_allows_package_to_be_absent(monkeypatch):
    def package_not_installed(_):
        raise ModuleNotFoundError(
            "No module named 'ensembl.production'", name="ensembl.production"
        )

    monkeypatch.setattr(json_validator, "import_module", package_not_installed)

    assert json_validator._load_file_handover_schemas() == {}


def test_optional_file_handover_schema_fails_only_when_selected(monkeypatch, tmp_path):
    target_file = tmp_path / "selection.json"
    target_file.write_text(json.dumps(_payload()))

    monkeypatch.setattr(json_validator, "FILE_HANDOVER_SCHEMAS", {})
    monkeypatch.delitem(json_validator.SCHEMAS, "short_variants", raising=False)

    with pytest.raises(AssertionError, match="requires the optional file-handover package"):
        json_validator.check_validity(target_file, {"schema": "short_variants"})
