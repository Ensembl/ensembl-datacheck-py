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

from ensembl.datacheck.checks.automation import conftest as automation_conftest
from ensembl.datacheck.checks.automation import automation_track_api_load


class _DummyRequest:
    def __init__(self, param):
        self.param = param


def test_track_api_resource_returns_configured_uri():
    resource_config = {
        "track_api_stage": {
            "ignore": "False",
            "uri": "https://example.org",
        }
    }

    uri = automation_conftest.track_api_resource.__wrapped__(
        _DummyRequest("track_api_stage"),
        resource_config,
    )

    assert uri == "https://example.org"


def test_track_api_resource_skips_ignored_resource():
    resource_config = {
        "track_api_stage": {
            "ignore": "True",
            "uri": "https://example.org",
        }
    }

    with pytest.raises(pytest.skip.Exception):
        automation_conftest.track_api_resource.__wrapped__(
            _DummyRequest("track_api_stage"),
            resource_config,
        )


def test_get_track_category_ids_finds_expected_categories():
    payload = {
        "track_categories": [
            {
                "label": "Genes & transcripts",
                "track_category_id": "genes-transcripts",
                "type": "Genomic",
                "track_list": [],
            },
            {
                "label": "Assembly",
                "track_category_id": "assembly",
                "type": "Genomic",
                "track_list": [],
            },
        ]
    }

    category_ids = automation_track_api_load._get_track_category_ids(payload)

    assert automation_track_api_load.EXPECTED_TRACK_CATEGORY_IDS.issubset(category_ids)


def test_get_track_category_ids_reports_missing_expected_category():
    payload = {
        "track_categories": [
            {
                "label": "Assembly",
                "track_category_id": "assembly",
                "type": "Genomic",
                "track_list": [],
            },
        ]
    }

    category_ids = automation_track_api_load._get_track_category_ids(payload)
    missing_category_ids = (
        automation_track_api_load.EXPECTED_TRACK_CATEGORY_IDS - category_ids
    )

    assert missing_category_ids == {"genes-transcripts"}
