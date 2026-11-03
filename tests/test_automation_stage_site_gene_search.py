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

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ensembl.datacheck.checks.automation.stage_site import gene_search
from ensembl.datacheck.functions.utils import get_genome_dataset_attribute

METADATA_DB = Path(__file__).parent / "database" / "ensembl_genome_metadata.db"
GENOME_UUID = "59871324-7803-4234-856e-2a2bd96d7b3c"
SAMPLE_GENE = "ENSG00000139618"


class _DummyResponse:
    def __init__(self, status_code=200, json_payload=None, url="http://example.org"):
        self.status_code = status_code
        self._json_payload = json_payload
        self.url = url

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


def _payload(*genome_ids):
    return {
        "meta": {"total_hits": len(genome_ids), "page": 1, "per_page": 50},
        "matches": [{"stable_id": f"{SAMPLE_GENE}.19", "genome_id": genome_id} for genome_id in genome_ids],
    }


def _run_check(monkeypatch, response, sample_gene=SAMPLE_GENE):
    check = gene_search.TestStageSiteGeneSearch()
    check.genome_uuid = GENOME_UUID
    check.base_url = "https://staging.example.org/"
    check.sample_gene = sample_gene
    calls = []

    def _post(url, json=None, **kwargs):
        calls.append((url, json))
        return response

    monkeypatch.setattr(gene_search.requests, "post", _post)
    check.check_gene_search_by_sample_gene()
    return calls


def test_get_genome_dataset_attribute_returns_sample_gene():
    with Session(create_engine(f"sqlite:///{METADATA_DB}")) as session:
        assert get_genome_dataset_attribute(
            session, "3704ceb1-948d-11ec-a39d-005056b38ce3", "genebuild.sample_gene"
        ) == SAMPLE_GENE
        assert get_genome_dataset_attribute(session, "missing-uuid", "genebuild.sample_gene") is None


def test_build_gene_search_url():
    assert gene_search._build_gene_search_url("https://staging-2020.ensembl.org/") == (
        "https://staging-2020.ensembl.org/api/search/genes"
    )


def test_passes_when_genome_matched(monkeypatch):
    calls = _run_check(monkeypatch, _DummyResponse(json_payload=_payload(GENOME_UUID)))
    assert calls == [
        ("https://staging.example.org/api/search/genes", {"query": SAMPLE_GENE, "genome_ids": [GENOME_UUID]})
    ]


def test_fails_when_sample_gene_missing(monkeypatch):
    with pytest.raises(AssertionError, match="missing genebuild.sample_gene"):
        _run_check(monkeypatch, _DummyResponse(json_payload=_payload(GENOME_UUID)), sample_gene=None)


def test_fails_when_no_hits(monkeypatch):
    with pytest.raises(AssertionError, match="no gene search hits"):
        _run_check(monkeypatch, _DummyResponse(json_payload=_payload()))


def test_fails_when_genome_not_matched(monkeypatch):
    with pytest.raises(AssertionError, match="no match for the genome"):
        _run_check(monkeypatch, _DummyResponse(json_payload=_payload("other-genome")))


def test_fails_on_non_200_status(monkeypatch):
    with pytest.raises(AssertionError, match="status code: 422"):
        _run_check(monkeypatch, _DummyResponse(status_code=422))


def test_fails_on_invalid_json(monkeypatch):
    with pytest.raises(AssertionError, match="valid JSON"):
        _run_check(monkeypatch, _DummyResponse())
