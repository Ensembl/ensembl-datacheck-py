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

import pytest

from ensembl.datacheck.checks.automation.stage_site import conftest as stage_site_conftest
from ensembl.datacheck.checks.automation.stage_site import genome_search

GENOME_UUID = "6067e162-ad73-413b-bdac-ecb69a6b9ad2"
ACCESSION = "GCA_003597395.1"
ASSEMBLY_URL = f"https://identifiers.org/insdc.gca/{ACCESSION}"

# check method name -> query it is expected to search with
CHECKS = {
    "check_genome_search_by_genome_uuid": GENOME_UUID,
    "check_genome_search_by_assembly_accession": ACCESSION,
}


class _DummyResponse:
    def __init__(self, status_code=200, json_payload=None, url="http://example.org"):
        self.status_code = status_code
        self._json_payload = json_payload
        self.url = url

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


def _match(genome_id=GENOME_UUID, assembly_url=ASSEMBLY_URL):
    return {"genome_id": genome_id, "assembly": {"accession_id": ACCESSION, "url": assembly_url}}


def _run_check(monkeypatch, check_name, search_response, head_status=200):
    check = genome_search.TestStageSiteGenomeSearch()
    check.genome_uuid = GENOME_UUID
    check.assembly_accession = ACCESSION
    check.base_url = "https://staging.example.org/"
    calls = {"get": [], "head": []}

    def _get(url, params=None, **kwargs):
        calls["get"].append((url, params))
        return search_response

    def _head(url, **kwargs):
        calls["head"].append(url)
        return _DummyResponse(status_code=head_status)

    monkeypatch.setattr(genome_search.requests, "get", _get)
    monkeypatch.setattr(genome_search.requests, "head", _head)
    getattr(check, check_name)()
    return calls


def test_stage_site_resource_returns_configured_uri():
    uri = stage_site_conftest.stage_site_resource.__wrapped__(
        {"stage_site": {"ignore": "False", "uri": "https://example.org"}}
    )
    assert uri == "https://example.org"


@pytest.mark.parametrize(
    "resource_config",
    [{}, {"stage_site": {"ignore": "True", "uri": "https://example.org"}}, {"stage_site": {"uri": ""}}],
)
def test_stage_site_resource_skips(resource_config):
    with pytest.raises(pytest.skip.Exception):
        stage_site_conftest.stage_site_resource.__wrapped__(resource_config)


def test_build_genome_search_url():
    assert genome_search._build_genome_search_url("https://staging-2020.ensembl.org/") == (
        "https://staging-2020.ensembl.org/api/search/genomes/v3"
    )


@pytest.mark.parametrize("check_name,query", CHECKS.items())
class TestGenomeSearchChecks:

    def test_passes_when_genome_among_matches(self, monkeypatch, check_name, query):
        response = _DummyResponse(json_payload={"matches": [_match(genome_id="other"), _match()]})
        calls = _run_check(monkeypatch, check_name, response)
        assert calls["get"] == [
            ("https://staging.example.org/api/search/genomes/v3", {"query": query, "page": 1, "per_page": 100})
        ]
        assert calls["head"] == [ASSEMBLY_URL]

    def test_fails_when_genome_missing(self, monkeypatch, check_name, query):
        response = _DummyResponse(json_payload={"matches": [_match(genome_id="other")]})
        with pytest.raises(AssertionError, match="not found by genome search"):
            _run_check(monkeypatch, check_name, response)

    def test_fails_when_assembly_url_missing(self, monkeypatch, check_name, query):
        response = _DummyResponse(json_payload={"matches": [_match(assembly_url=None)]})
        with pytest.raises(AssertionError, match="missing assembly url"):
            _run_check(monkeypatch, check_name, response)

    def test_fails_when_assembly_url_unreachable(self, monkeypatch, check_name, query):
        response = _DummyResponse(json_payload={"matches": [_match()]})
        with pytest.raises(AssertionError, match="is not reachable"):
            _run_check(monkeypatch, check_name, response, head_status=404)

    def test_fails_on_non_200_status(self, monkeypatch, check_name, query):
        with pytest.raises(AssertionError, match="status code: 502"):
            _run_check(monkeypatch, check_name, _DummyResponse(status_code=502))

    def test_fails_on_invalid_json(self, monkeypatch, check_name, query):
        with pytest.raises(AssertionError, match="valid JSON"):
            _run_check(monkeypatch, check_name, _DummyResponse())
