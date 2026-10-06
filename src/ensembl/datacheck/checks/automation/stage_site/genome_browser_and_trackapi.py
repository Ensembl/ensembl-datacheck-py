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
Check the staging site genome browser and track API for each genome, using the genome's
example gene and location from <site>/api/metadata/genome/<genome_uuid>/example_objects.
Checks performed:
    - validate_location: the example location is valid (region, start and end).
    - genome browser: <site>/genome-browser/<assembly_accession>?focus=gene:<gene>&location=<location>
      responds with 200, and the focus gene resolves in the Core GraphQL API the browser loads it
      from (the page itself is rendered client side, so it responds with 200 for any focus).
    - track API: <site>/api/tracks/track_categories/<genome_uuid> responds with 200 and has the
      Assembly and Genes & transcripts track categories.
"""

import logging
from functools import lru_cache

import pytest
import requests

REQUIRED_TRACK_CATEGORIES = ("Assembly", "Genes & transcripts")
GENE_QUERY = (
    "query Gene($genome_id: String!, $stable_id: String!) "
    "{ gene(by_id: {genome_id: $genome_id, stable_id: $stable_id}) { stable_id } }"
)


def _get_json(url, genome_uuid, **kwargs):
    """GET or POST (when json is given) a URL and return its JSON payload, failing on non 200."""
    logging.info("Request: %s", url)
    if "json" in kwargs:
        response = requests.post(url, timeout=60, **kwargs)
    else:
        response = requests.get(url, timeout=60, **kwargs)

    if response.status_code != 200:
        raise AssertionError(
            f"{genome_uuid}: {response.url} failed with status code: {response.status_code}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise AssertionError(f"{genome_uuid}: {response.url} did not return valid JSON") from exc


@lru_cache(maxsize=128)
def _get_example_objects(base_url, genome_uuid):
    """Return the genome's example objects as {type: id}, cached as each check needs them."""
    url = f"{base_url.rstrip('/')}/api/metadata/genome/{genome_uuid}/example_objects"
    payload = _get_json(url, genome_uuid)
    return {obj.get("type"): obj.get("id") for obj in payload or [] if isinstance(obj, dict)}


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("stage_site")
class TestStageSiteGenomeBrowserAndTrackApi:
    """
    Check the genome browser and track API on the staging site for each genome.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, stage_site_resource):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.genome_uuid = genomes["genome_uuid"]
        self.assembly_accession = genomes["assembly_accession"]
        self.base_url = stage_site_resource.rstrip("/")

    def _example_object(self, object_type):
        """Return the genome's example object id of a type, failing if there is none."""
        object_id = _get_example_objects(self.base_url, self.genome_uuid).get(object_type)
        assert object_id, f"{self.genome_uuid}: no example {object_type} in example_objects"
        return object_id

    def check_validate_location(self):
        """
        Check that the example location is valid for the genome.
        Raises:
            AssertionError: If region, start or end of the location is not valid.
        """
        location = self._example_object("location")
        url = f"{self.base_url}/api/metadata/validate_location"
        payload = _get_json(url, self.genome_uuid, params={"genome_id": self.genome_uuid, "location": location})

        invalid = {
            part: (payload.get(part) or {}).get("error_message")
            for part in ("region", "start", "end")
            if not (payload.get(part) or {}).get("is_valid")
        }
        assert not invalid, (
            f"{self.genome_uuid}: example location {location!r} is not valid: {invalid}"
        )

    def check_genome_browser_focus_gene(self):
        """
        Check that the genome browser loads for the example gene and location.
        Raises:
            AssertionError: If the page fails, or the focus gene is not found.
        """
        gene_id = self._example_object("gene")
        location = self._example_object("location")

        url = f"{self.base_url}/genome-browser/{self.assembly_accession}"
        logging.info("Genome browser: %s focus=gene:%s location=%s", url, gene_id, location)
        response = requests.get(url, params={"focus": f"gene:{gene_id}", "location": location}, timeout=60)
        assert response.status_code == 200, (
            f"{self.genome_uuid}: genome browser {response.url} failed with status code: "
            f"{response.status_code}"
        )

        payload = _get_json(
            f"{self.base_url}/api/graphql/core",
            self.genome_uuid,
            json={"query": GENE_QUERY, "variables": {"genome_id": self.genome_uuid, "stable_id": gene_id}},
        )
        gene = (payload.get("data") or {}).get("gene")
        errors = [error.get("message") for error in payload.get("errors") or []]
        assert gene, (
            f"{self.genome_uuid}: genome browser focus gene {gene_id!r} not found: {errors}"
        )

    def check_track_categories(self):
        """
        Check that the track API has the required track categories for the genome.
        Raises:
            AssertionError: If the endpoint fails, or a required category is missing.
        """
        url = f"{self.base_url}/api/tracks/track_categories/{self.genome_uuid}"
        payload = _get_json(url, self.genome_uuid)

        labels = [category.get("label") for category in payload.get("track_categories") or []]
        missing = [label for label in REQUIRED_TRACK_CATEGORIES if label not in labels]
        assert not missing, (
            f"{self.genome_uuid}: missing track categories {missing} ({url}); found {labels}"
        )
