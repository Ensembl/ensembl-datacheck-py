# See the NOTICE file distributed with this work for additional information
# regarding copyright ownership.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest

from ensembl.datacheck.checks.automation import automation_solr_duplicates as checks


class _DummyResponse:
    def __init__(self, payload=None, status_code=200, url="http://solr.example/select"):
        self.payload = payload
        self.status_code = status_code
        self.url = url

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _config(**overrides):
    config = {
        "solr_url": "http://solr.example/solr",
        "collection": "beta_even",
        "page_size": 5000,
        "timeout": 30,
        "ignored_fields": ("id", "_version_"),
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize(
    "solr_url,expected",
    [
        ("http://solr.example", "http://solr.example/solr/beta_even/select"),
        ("http://solr.example/solr/", "http://solr.example/solr/beta_even/select"),
    ],
)
def test_build_solr_select_url_accepts_host_or_solr_url(solr_url, expected):
    assert checks._build_solr_select_url(solr_url, "beta_even") == expected


def test_canonical_digest_ignores_id_and_version():
    first = {"id": "one", "_version_": 1, "genome_id": "uuid", "name": "gene"}
    second = {"id": "two", "_version_": 2, "name": "gene", "genome_id": "uuid"}

    assert checks._canonical_digest(first) == checks._canonical_digest(second)


def test_get_config_reads_uri_collection_and_scan_options():
    config = checks._get_solr_duplicate_config({
        "solr_duplicates": {
            "uri": "http://solr.example/solr",
            "collection": "beta_odd",
            "page_size": "1000",
            "timeout": "45",
            "ignored_fields": "id,_version_,score",
        }
    })

    assert config == {
        "solr_url": "http://solr.example/solr",
        "collection": "beta_odd",
        "page_size": 1000,
        "timeout": 45.0,
        "ignored_fields": ("id", "_version_", "score"),
    }


def test_get_config_skips_ignored_resource():
    with pytest.raises(pytest.skip.Exception):
        checks._get_solr_duplicate_config({"solr_duplicates": {"ignore": "True"}})


def test_automation_check_uses_genome_uuid_from_standard_genomes_fixture(monkeypatch):
    captured = {}
    config = _config()
    monkeypatch.setattr(checks, "_get_solr_duplicate_config", lambda resource_config: config)
    monkeypatch.setattr(
        checks,
        "_check_genome_documents",
        lambda genome_uuid, resolved_config: captured.update(
            genome_uuid=genome_uuid,
            config=resolved_config,
        ),
    )

    checks.check_solr_genome_documents_are_unique(
        genomes={"genome_uuid": "selected-uuid"},
        automation_resource_config={"solr_duplicates": {}},
    )

    assert captured == {"genome_uuid": "selected-uuid", "config": config}


def test_check_genome_documents_passes_after_all_cursor_pages(monkeypatch):
    responses = iter([
        _DummyResponse({
            "response": {
                "numFound": 2,
                "docs": [
                    {"id": "one", "_version_": 1, "genome_id": "uuid", "name": "a"},
                    {"id": "two", "_version_": 2, "genome_id": "uuid", "name": "b"},
                ],
            },
            "nextCursorMark": "cursor-1",
        }),
        _DummyResponse({
            "response": {"numFound": 2, "docs": []},
            "nextCursorMark": "cursor-1",
        }),
    ])
    calls = []

    def _post(url, data, timeout):
        calls.append((url, data, timeout))
        return next(responses)

    monkeypatch.setattr(checks.requests, "post", _post)

    checks._check_genome_documents("uuid", _config())

    assert [call[1]["cursorMark"] for call in calls] == ["*", "cursor-1"]
    assert all(call[1]["fq"] == 'genome_id:"uuid"' for call in calls)


def test_check_genome_documents_fails_for_identical_documents(monkeypatch):
    response = _DummyResponse({
        "response": {
            "numFound": 2,
            "docs": [
                {"id": "one", "_version_": 1, "genome_id": "uuid", "name": "same"},
                {"id": "two", "_version_": 2, "genome_id": "uuid", "name": "same"},
            ],
        },
        "nextCursorMark": "cursor-1",
    })
    monkeypatch.setattr(checks.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(AssertionError, match="identical documents found"):
        checks._check_genome_documents("uuid", _config())


def test_check_genome_documents_fails_when_genome_is_missing(monkeypatch):
    response = _DummyResponse({
        "response": {"numFound": 0, "docs": []},
        "nextCursorMark": "*",
    })
    monkeypatch.setattr(checks.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(AssertionError, match="no documents found"):
        checks._check_genome_documents("missing-uuid", _config())


def test_request_page_fails_for_http_error(monkeypatch):
    monkeypatch.setattr(
        checks.requests,
        "post",
        lambda *args, **kwargs: _DummyResponse(payload={}, status_code=503),
    )

    with pytest.raises(AssertionError, match="status code 503"):
        checks._request_page("http://solr.example/select", {}, 30)
