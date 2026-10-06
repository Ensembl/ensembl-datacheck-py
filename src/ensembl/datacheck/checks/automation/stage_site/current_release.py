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
Check that the staging site serves the current partial release from the metadata database.
Checks performed:
    - <site>/api/metadata/releases?current_only=true responds with 200, and the names of its
      partial releases match the labels of the current partial releases in ensembl_release.
"""

import logging

import pytest
import requests

from ensembl.datacheck.functions.utils import get_current_release_labels

RELEASES_PATH = "/api/metadata/releases"
PARTIAL_RELEASE_TYPE = "partial"


def _build_releases_url(base_url):
    """Build the current releases API URL for a site."""
    return f"{base_url.rstrip('/')}{RELEASES_PATH}"


def _get_current_releases(base_url):
    """Query the current releases API and return (url, releases)."""
    url = _build_releases_url(base_url)
    logging.info("Current releases: %s?current_only=true", url)
    response = requests.get(url, params={"current_only": "true"}, timeout=60)

    if response.status_code != 200:
        raise AssertionError(
            f"Releases endpoint failed for URL: {response.url} "
            f"with status code: {response.status_code}"
        )
    try:
        releases = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"Releases endpoint did not return valid JSON for URL: {response.url}"
        ) from exc

    assert isinstance(releases, list), (
        f"Releases endpoint did not return a list for URL: {response.url}"
    )
    return response.url, releases


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("stage_site")
def check_current_partial_release(stage_site_resource, db_session):
    """
    Check that the site's current partial release matches the metadata database.
    Checks for:
        - Releases endpoint returns HTTP 200 with a list of releases.
        - Names of releases with type partial equal the labels of the current partial
          releases in ensembl_release.
    Raises:
        AssertionError: If the endpoint fails, or the partial releases differ.
    """
    assert db_session is not None, (
        "Missing --database for current release check. Provide a metadata database URL with --database."
    )
    db_labels = set(get_current_release_labels(db_session, PARTIAL_RELEASE_TYPE))
    assert db_labels, "No current partial release found in ensembl_release"

    url, releases = _get_current_releases(stage_site_resource)
    site_names = {
        release.get("name")
        for release in releases
        if release.get("type") == PARTIAL_RELEASE_TYPE
    }

    assert site_names == db_labels, (
        f"Current partial release mismatch ({url}): "
        f"ensembl_release label={sorted(db_labels)} site name={sorted(filter(None, site_names))}"
    )
