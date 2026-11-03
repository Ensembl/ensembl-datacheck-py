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

from ensembl.datacheck.checks.automation.stage_site import current_release
from ensembl.datacheck.functions.utils import get_current_release_labels

METADATA_DB = Path(__file__).parent / "database" / "ensembl_genome_metadata.db"
# Current partial release label in the test metadata database
DB_PARTIAL_LABEL = "2020-10-18"


class _DummyResponse:
    def __init__(self, status_code=200, json_payload=None, url="http://example.org"):
        self.status_code = status_code
        self._json_payload = json_payload
        self.url = url

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


def _releases(partial_name=DB_PARTIAL_LABEL):
    return [
        {"name": "2026-07", "type": "integrated", "is_current": True},
        {"name": partial_name, "type": "partial", "is_current": True},
    ]


@pytest.fixture
def db_session():
    with Session(create_engine(f"sqlite:///{METADATA_DB}")) as session:
        yield session


def _run_check(monkeypatch, db_session, response):
    calls = []

    def _get(url, params=None, **kwargs):
        calls.append((url, params))
        return response

    monkeypatch.setattr(current_release.requests, "get", _get)
    current_release.check_current_partial_release("https://staging.example.org/", db_session)
    return calls


def test_get_current_release_labels(db_session):
    assert get_current_release_labels(db_session, "partial") == [DB_PARTIAL_LABEL]
    assert get_current_release_labels(db_session, "integrated") == ["2025-07"]


def test_build_releases_url():
    assert current_release._build_releases_url("https://staging-2020.ensembl.org/") == (
        "https://staging-2020.ensembl.org/api/metadata/releases"
    )


def test_passes_when_partial_release_matches(monkeypatch, db_session):
    calls = _run_check(monkeypatch, db_session, _DummyResponse(json_payload=_releases()))
    assert calls == [("https://staging.example.org/api/metadata/releases", {"current_only": "true"})]


def test_fails_when_partial_release_differs(monkeypatch, db_session):
    with pytest.raises(AssertionError, match="Current partial release mismatch"):
        _run_check(monkeypatch, db_session, _DummyResponse(json_payload=_releases("2026-09-22")))


def test_fails_when_site_has_no_partial_release(monkeypatch, db_session):
    payload = [{"name": "2026-07", "type": "integrated", "is_current": True}]
    with pytest.raises(AssertionError, match="Current partial release mismatch"):
        _run_check(monkeypatch, db_session, _DummyResponse(json_payload=payload))


def test_fails_without_database(monkeypatch):
    with pytest.raises(AssertionError, match="Missing --database"):
        _run_check(monkeypatch, None, _DummyResponse(json_payload=_releases()))


def test_fails_on_non_200_status(monkeypatch, db_session):
    with pytest.raises(AssertionError, match="status code: 500"):
        _run_check(monkeypatch, db_session, _DummyResponse(status_code=500))


def test_fails_on_invalid_json(monkeypatch, db_session):
    with pytest.raises(AssertionError, match="valid JSON"):
        _run_check(monkeypatch, db_session, _DummyResponse())
