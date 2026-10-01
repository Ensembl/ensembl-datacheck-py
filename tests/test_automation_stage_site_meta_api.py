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

from ensembl.datacheck.checks.automation.stage_site import meta_api

GENOME_UUID = "6067e162-ad73-413b-bdac-ecb69a6b9ad2"
BASE_URL = "https://staging.example.org/"


class _DummyResponse:
    def __init__(self, status_code=200, json_payload=None):
        self.status_code = status_code
        self._json_payload = json_payload

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


def _make_check(monkeypatch, response):
    check = meta_api.TestStageSiteMetaApi()
    check.genome_uuid = GENOME_UUID
    check.base_url = BASE_URL
    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        return response

    monkeypatch.setattr(meta_api.requests, "get", _get)
    return check, calls


def test_build_genome_metadata_url():
    assert meta_api._build_genome_metadata_url(BASE_URL, GENOME_UUID, "stats") == (
        f"https://staging.example.org/api/metadata/genome/{GENOME_UUID}/stats"
    )


def test_example_objects_passes(monkeypatch):
    payload = [{"type": "gene", "id": "ENSCABG00000015264"}, {"type": "location", "id": "1:1-100"}]
    check, calls = _make_check(monkeypatch, _DummyResponse(json_payload=payload))
    check.check_meta_api_example_objects()
    assert calls == [f"https://staging.example.org/api/metadata/genome/{GENOME_UUID}/example_objects"]


@pytest.mark.parametrize(
    "payload,error",
    [([], "no example objects"), ([{"type": "gene"}], "without type or id")],
)
def test_example_objects_fails(monkeypatch, payload, error):
    check, _ = _make_check(monkeypatch, _DummyResponse(json_payload=payload))
    with pytest.raises(AssertionError, match=error):
        check.check_meta_api_example_objects()


@pytest.mark.parametrize("endpoint", ["explain", "details"])
def test_genome_id_passes(monkeypatch, endpoint):
    check, calls = _make_check(monkeypatch, _DummyResponse(json_payload={"genome_id": GENOME_UUID}))
    check.check_meta_api_genome_id(endpoint)
    assert calls == [f"https://staging.example.org/api/metadata/genome/{GENOME_UUID}/{endpoint}"]


@pytest.mark.parametrize("endpoint", ["explain", "details"])
def test_genome_id_fails_on_mismatch(monkeypatch, endpoint):
    check, _ = _make_check(monkeypatch, _DummyResponse(json_payload={"genome_id": "other"}))
    with pytest.raises(AssertionError, match=f"{endpoint} returned genome_id='other'"):
        check.check_meta_api_genome_id(endpoint)


def test_stats_passes(monkeypatch):
    payload = {"genome_stats": {"assembly_stats": {"contig_n50": 73186, "chromosomes": None}}}
    check, _ = _make_check(monkeypatch, _DummyResponse(json_payload=payload))
    check.check_meta_api_stats()


def test_stats_fails_when_all_null(monkeypatch):
    payload = {"genome_stats": {"assembly_stats": {"contig_n50": None, "total_genome_length": None}}}
    check, _ = _make_check(monkeypatch, _DummyResponse(json_payload=payload))
    with pytest.raises(AssertionError, match="no assembly stats"):
        check.check_meta_api_stats()


def test_fails_on_non_200_status(monkeypatch):
    check, _ = _make_check(monkeypatch, _DummyResponse(status_code=404, json_payload={}))
    with pytest.raises(AssertionError, match="status code: 404"):
        check.check_meta_api_genome_id("explain")


def test_fails_on_invalid_json(monkeypatch):
    check, _ = _make_check(monkeypatch, _DummyResponse())
    with pytest.raises(AssertionError, match="valid JSON"):
        check.check_meta_api_stats()
