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

from ensembl.datacheck.checks.automation.stage_site import genome_browser_and_trackapi as gb

GENOME_UUID = "a6757041-937e-4329-8100-aadc4675920e"
ACCESSION = "GCA_001445615.2"
GENE = "TMP_alenIFM54703_2"
LOCATION = "BCLY01000001:9725-10346"
BASE_URL = "https://staging.example.org"

EXAMPLE_OBJECTS = [{"type": "gene", "id": GENE}, {"type": "location", "id": LOCATION}]
VALID_LOCATION = {
    "region": {"is_valid": True, "error_message": None},
    "start": {"is_valid": True, "error_message": None},
    "end": {"is_valid": True, "error_message": None},
}
INVALID_LOCATION = {
    "region": {"is_valid": True, "error_message": None},
    "start": {"is_valid": False, "error_message": None},
    "end": {"is_valid": False, "error_message": "end should be between 1 and 151758149"},
}
GENE_FOUND = {"data": {"gene": {"stable_id": GENE}}}
GENE_NOT_FOUND = {"data": {"gene": None}, "errors": [{"message": f"Failed to find gene with ids: stable_id={GENE}"}]}
TRACKS = {"track_categories": [{"label": "Assembly"}, {"label": "Genes & transcripts"}]}


class _DummyResponse:
    def __init__(self, status_code=200, json_payload=None, url="http://example.org"):
        self.status_code = status_code
        self._json_payload = json_payload
        self.url = url

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


@pytest.fixture(autouse=True)
def clear_example_objects_cache():
    gb._get_example_objects.cache_clear()
    yield
    gb._get_example_objects.cache_clear()


def _make_check(monkeypatch, responses):
    """Patch requests so each URL path suffix returns its response; record calls."""
    check = gb.TestStageSiteGenomeBrowserAndTrackApi()
    check.genome_uuid = GENOME_UUID
    check.assembly_accession = ACCESSION
    check.base_url = BASE_URL
    calls = []

    def _respond(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params") or kwargs.get("json")))
        for suffix, response in responses.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected request {url}")

    monkeypatch.setattr(gb.requests, "get", lambda url, **kwargs: _respond("GET", url, **kwargs))
    monkeypatch.setattr(gb.requests, "post", lambda url, **kwargs: _respond("POST", url, **kwargs))
    return check, calls


def _example_objects(payload=EXAMPLE_OBJECTS):
    return {"/example_objects": _DummyResponse(json_payload=payload)}


def test_validate_location_passes(monkeypatch):
    check, calls = _make_check(
        monkeypatch, {**_example_objects(), "/validate_location": _DummyResponse(json_payload=VALID_LOCATION)}
    )
    check.check_validate_location()
    assert calls[-1] == (
        "GET",
        f"{BASE_URL}/api/metadata/validate_location",
        {"genome_id": GENOME_UUID, "location": LOCATION},
    )


def test_validate_location_fails_when_invalid(monkeypatch):
    check, _ = _make_check(
        monkeypatch, {**_example_objects(), "/validate_location": _DummyResponse(json_payload=INVALID_LOCATION)}
    )
    with pytest.raises(AssertionError, match="is not valid: .*'start'.*'end'"):
        check.check_validate_location()


def test_fails_when_example_location_missing(monkeypatch):
    check, _ = _make_check(monkeypatch, _example_objects([{"type": "gene", "id": GENE}]))
    with pytest.raises(AssertionError, match="no example location"):
        check.check_validate_location()


def test_example_objects_fetched_once(monkeypatch):
    check, calls = _make_check(
        monkeypatch,
        {
            **_example_objects(),
            "/validate_location": _DummyResponse(json_payload=VALID_LOCATION),
            f"/genome-browser/{ACCESSION}": _DummyResponse(),
            "/api/graphql/core": _DummyResponse(json_payload=GENE_FOUND),
        },
    )
    check.check_validate_location()
    check.check_genome_browser_focus_gene()
    assert sum(url.endswith("/example_objects") for _, url, _ in calls) == 1


def test_genome_browser_focus_gene_passes(monkeypatch):
    check, calls = _make_check(
        monkeypatch,
        {
            **_example_objects(),
            f"/genome-browser/{ACCESSION}": _DummyResponse(),
            "/api/graphql/core": _DummyResponse(json_payload=GENE_FOUND),
        },
    )
    check.check_genome_browser_focus_gene()
    assert ("GET", f"{BASE_URL}/genome-browser/{ACCESSION}", {"focus": f"gene:{GENE}", "location": LOCATION}) in calls
    assert calls[-1][2]["variables"] == {"genome_id": GENOME_UUID, "stable_id": GENE}


def test_genome_browser_fails_when_page_fails(monkeypatch):
    check, _ = _make_check(
        monkeypatch, {**_example_objects(), f"/genome-browser/{ACCESSION}": _DummyResponse(status_code=502)}
    )
    with pytest.raises(AssertionError, match="genome browser .* status code: 502"):
        check.check_genome_browser_focus_gene()


def test_genome_browser_fails_when_gene_not_found(monkeypatch):
    check, _ = _make_check(
        monkeypatch,
        {
            **_example_objects(),
            f"/genome-browser/{ACCESSION}": _DummyResponse(),
            "/api/graphql/core": _DummyResponse(json_payload=GENE_NOT_FOUND),
        },
    )
    with pytest.raises(AssertionError, match="focus gene 'TMP_alenIFM54703_2' not found"):
        check.check_genome_browser_focus_gene()


def test_track_categories_passes(monkeypatch):
    check, _ = _make_check(monkeypatch, {f"/track_categories/{GENOME_UUID}": _DummyResponse(json_payload=TRACKS)})
    check.check_track_categories()


def test_track_categories_fails_when_category_missing(monkeypatch):
    payload = {"track_categories": [{"label": "Assembly"}]}
    check, _ = _make_check(monkeypatch, {f"/track_categories/{GENOME_UUID}": _DummyResponse(json_payload=payload)})
    with pytest.raises(AssertionError, match=r"missing track categories \['Genes & transcripts'\]"):
        check.check_track_categories()


def test_track_categories_fails_on_404(monkeypatch):
    check, _ = _make_check(
        monkeypatch, {f"/track_categories/{GENOME_UUID}": _DummyResponse(status_code=404, json_payload={})}
    )
    with pytest.raises(AssertionError, match="status code: 404"):
        check.check_track_categories()
