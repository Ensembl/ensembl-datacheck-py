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

import json

import pytest

from ensembl.datacheck.checks.automation.stage_site import genome_page

GENOME_UUID = "a6757041-937e-4329-8100-aadc4675920e"
ACCESSION = "GCA_001445615.2"


class _DummyResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _page(*accessions):
    state = {
        "pageMeta": {"title": "Ensembl"},
        "genome": {
            "genomes": {
                f"uuid-{accession}": {"assembly": {"accession_id": accession}}
                for accession in accessions
            }
        },
    }
    return (
        "<html><head><script>window.__PRELOADED_STATE__ = "
        f"{json.dumps(state)};</script></head><body></body></html>"
    )


def _run_check(monkeypatch, response):
    check = genome_page.TestStageSiteGenomePage()
    check.genome_uuid = GENOME_UUID
    check.assembly_accession = ACCESSION
    check.base_url = "https://staging.example.org/"
    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        return response

    monkeypatch.setattr(genome_page.requests, "get", _get)
    check.check_genome_page_by_assembly_accession()
    return calls


def test_build_genome_page_url():
    assert genome_page._build_genome_page_url("https://staging-2020.ensembl.org/", ACCESSION) == (
        f"https://staging-2020.ensembl.org/genome/{ACCESSION}"
    )


def test_get_preloaded_state():
    assert genome_page._get_preloaded_state(_page(ACCESSION))["genome"]["genomes"]
    assert genome_page._get_preloaded_state("<html></html>") is None
    assert genome_page._get_preloaded_state("window.__PRELOADED_STATE__ = {broken") is None


def test_passes_when_genome_loaded(monkeypatch):
    calls = _run_check(monkeypatch, _DummyResponse(text=_page(ACCESSION)))
    assert calls == [f"https://staging.example.org/genome/{ACCESSION}"]


def test_fails_on_non_200_status(monkeypatch):
    with pytest.raises(AssertionError, match="status code: 404"):
        _run_check(monkeypatch, _DummyResponse(status_code=404, text=_page()))


def test_fails_without_preloaded_state(monkeypatch):
    with pytest.raises(AssertionError, match="no valid preloaded state"):
        _run_check(monkeypatch, _DummyResponse(text="<html></html>"))


def test_fails_when_genome_not_loaded(monkeypatch):
    with pytest.raises(AssertionError, match="did not load assembly"):
        _run_check(monkeypatch, _DummyResponse(text=_page("GCA_000000000.1")))
