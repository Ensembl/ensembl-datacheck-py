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

"""
Check that track API track_categories endpoint is reachable
for both staging and production environments.

Checks performed:
    - Check track_categories endpoint returns HTTP 200
    - Check expected track category IDs are present
"""
import logging

import requests
import pytest

EXPECTED_TRACK_CATEGORY_IDS = {"genes-transcripts", "assembly"}


def _get_track_category_ids(payload):
    """Extract track category IDs from a Track API response payload."""
    track_categories = payload.get("track_categories", ['genes-transcripts','assembly'])
    assert isinstance(track_categories, list), "Track API response field 'track_categories' is not a list."

    return {
        category.get("track_category_id")
        for category in track_categories
        if isinstance(category, dict)
    }


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("track_api")
@pytest.mark.parametrize(
    "track_api_resource",
    [
        "track_api_stage",
        "track_api_prod",
    ],
    indirect=True
)
class TestTrackCategoriesEndpoint:
    """
    Check track_categories endpoint for stage and prod.
    """

    endpoint = "/api/tracks/track_categories"

    @pytest.fixture(autouse=True)
    def setup(self, genomes, track_api_resource):
        """
        Prepare commonly used attributes for each test invocation.
        """

        self.genome_uuid = genomes["genome_uuid"]
        self.base_url = track_api_resource.rstrip("/")

    def _get_track_categories_response(self):
        url = f"{self.base_url}{self.endpoint}/{self.genome_uuid}"

        logging.info(f"Checking track categories endpoint for genome UUID: {self.genome_uuid}")
        logging.info(f"URL: {url}")

        return requests.get(url, timeout=30)

    def check_track_categories_status_code(self):
        """
        Check track_categories endpoint returns HTTP 200.

        Raises:
            AssertionError:
                If endpoint does not return status code 200.
        """

        response = self._get_track_categories_response()

        if response.status_code != 200:
            raise AssertionError(
                f"Track API endpoint failed for URL: {response.url} "
                f"with status code: {response.status_code}"
            )

    def check_track_categories_expected_category_ids(self):
        """
        Check that expected track category IDs exist in the response.

        Raises:
            AssertionError:
                If the response does not include the expected category IDs.
        """
        response = self._get_track_categories_response()

        if response.status_code != 200:
            raise AssertionError(
                f"Track API endpoint failed for URL: {response.url} "
                f"with status code: {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AssertionError(
                f"Track API endpoint did not return valid JSON for URL: {response.url}"
            ) from exc

        category_ids = _get_track_category_ids(payload)
        missing_category_ids = EXPECTED_TRACK_CATEGORY_IDS - category_ids

        assert not missing_category_ids, (
            "Missing expected track category IDs: "
            f"{sorted(missing_category_ids)}. Found: {sorted(category_ids)}"
        )
