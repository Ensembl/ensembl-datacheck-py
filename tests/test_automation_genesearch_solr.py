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

from ensembl.datacheck.checks.automation import automation_genesearch_solr


class _DummyRequest:
    def __init__(self, param):
        self.param = param


class _DummyResponse:
    def __init__(self, status_code=200, json_payload=None, url="http://example.org"):
        self.status_code = status_code
        self._json_payload = json_payload
        self.url = url

    def json(self):
        return self._json_payload


def test_solr_api_resource_returns_configured_uri():
    resource_config = {
        "solr_api_stage": {
            "ignore": "False",
            "uri": "https://example.org",
        }
    }

    uri = automation_genesearch_solr.solr_api_resource.__wrapped__(
        _DummyRequest("solr_api_stage"),
        resource_config,
    )

    assert uri == "https://example.org"


def test_solr_api_resource_skips_ignored_resource():
    resource_config = {
        "solr_api_stage": {
            "ignore": "True",
            "uri": "https://example.org",
        }
    }

    with pytest.raises(pytest.skip.Exception):
        automation_genesearch_solr.solr_api_resource.__wrapped__(
            _DummyRequest("solr_api_stage"),
            resource_config,
        )


def test_solr_api_resource_skips_missing_uri():
    resource_config = {
        "solr_api_stage": {
            "ignore": "False",
            "uri": "",
        }
    }

    with pytest.raises(pytest.skip.Exception):
        automation_genesearch_solr.solr_api_resource.__wrapped__(
            _DummyRequest("solr_api_stage"),
            resource_config,
        )


def test_solr_api_resource_skips_unknown_resource():
    with pytest.raises(pytest.skip.Exception):
        automation_genesearch_solr.solr_api_resource.__wrapped__(
            _DummyRequest("solr_api_prod"),
            {},
        )


@pytest.mark.parametrize(
    "release_name,expected_collection",
    [(117, "beta_odd"), (118, "beta_even"), ("118", "beta_even")],
)
def test_get_solr_collection(release_name, expected_collection):
    assert automation_genesearch_solr._get_solr_collection(release_name) == expected_collection


def test_build_solr_select_url_matches_expected_format():
    url = automation_genesearch_solr._build_solr_select_url(
        "http://hh-rke-wp-webadmin-40-worker-1.caas.ebi.ac.uk:30265/",
        "beta_even",
        "abcd-1234-uuid",
    )

    assert url == (
        "http://hh-rke-wp-webadmin-40-worker-1.caas.ebi.ac.uk:30265"
        "/solr/beta_even/select?q=*&fq=genome_id:abcd-1234-uuid&wt=json"
    )


def test_get_num_found_returns_zero_for_missing_genome():
    payload = {"response": {"numFound": 0, "docs": []}}

    assert automation_genesearch_solr._get_num_found(payload) == 0


def test_get_num_found_returns_positive_count_for_found_genome():
    payload = {"response": {"numFound": 3, "docs": [{}, {}, {}]}}

    assert automation_genesearch_solr._get_num_found(payload) == 3


class TestGenesearchSolrIndexedCheck:
    """
    Exercise TestGenesearchSolrLoaded.check_genesearch_solr_indexed without a live Solr host.
    """

    def _make_check(self, monkeypatch, response):
        check = automation_genesearch_solr.TestGenesearchSolrLoaded()
        check.genome_uuid = "abcd-1234-uuid"
        check.base_url = "http://solr.example.org"
        check.solr_collection = "beta_even"
        monkeypatch.setattr(
            automation_genesearch_solr.requests, "get", lambda *args, **kwargs: response
        )
        return check

    def test_check_passes_when_genome_uuid_found(self, monkeypatch):
        response = _DummyResponse(json_payload={"response": {"numFound": 1, "docs": [{}]}})
        check = self._make_check(monkeypatch, response)

        check.check_genesearch_solr_indexed()

    def test_check_fails_when_genome_uuid_missing(self, monkeypatch):
        response = _DummyResponse(json_payload={"response": {"numFound": 0, "docs": []}})
        check = self._make_check(monkeypatch, response)

        with pytest.raises(AssertionError, match="missing from Solr collection"):
            check.check_genesearch_solr_indexed()

    def test_check_fails_on_non_200_status(self, monkeypatch):
        response = _DummyResponse(status_code=500, json_payload={})
        check = self._make_check(monkeypatch, response)

        with pytest.raises(AssertionError, match="status code: 500"):
            check.check_genesearch_solr_indexed()
