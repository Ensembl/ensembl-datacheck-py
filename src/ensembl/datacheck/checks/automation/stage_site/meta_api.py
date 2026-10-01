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
Check the staging site metadata API genome endpoints for each genome.
Checks performed, for <site>/api/metadata/genome/<genome_uuid>/<endpoint>:
    - example_objects: responds with 200 and a non-empty list of objects with type and id.
    - explain: responds with 200 and genome_id is the genome_uuid.
    - details: responds with 200 and genome_id is the genome_uuid.
    - stats: responds with 200 and assembly_stats has values (an unknown genome
      also responds with 200, but with every stat null).
"""

import logging

import pytest
import requests

GENOME_METADATA_PATH = "/api/metadata/genome"


def _build_genome_metadata_url(base_url, genome_uuid, endpoint):
    """Build a metadata API genome endpoint URL."""
    return f"{base_url.rstrip('/')}{GENOME_METADATA_PATH}/{genome_uuid}/{endpoint}"


def _get_genome_metadata(base_url, genome_uuid, endpoint):
    """Query a metadata API genome endpoint and return (url, payload)."""
    url = _build_genome_metadata_url(base_url, genome_uuid, endpoint)
    logging.info("Metadata API: %s", url)
    response = requests.get(url, timeout=60)

    if response.status_code != 200:
        raise AssertionError(
            f"{genome_uuid}: metadata endpoint {url} failed with status code: {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"{genome_uuid}: metadata endpoint {url} did not return valid JSON"
        ) from exc

    return url, payload


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("stage_site")
class TestStageSiteMetaApi:
    """
    Check the metadata API genome endpoints on the staging site for each genome.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, stage_site_resource):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.genome_uuid = genomes["genome_uuid"]
        self.base_url = stage_site_resource

    def check_meta_api_example_objects(self):
        """
        Check that example_objects returns a non-empty list of objects with type and id.
        """
        url, payload = _get_genome_metadata(self.base_url, self.genome_uuid, "example_objects")
        assert isinstance(payload, list) and payload, (
            f"{self.genome_uuid}: no example objects returned by {url}"
        )
        invalid_objects = [obj for obj in payload if not (obj.get("type") and obj.get("id"))]
        assert not invalid_objects, (
            f"{self.genome_uuid}: example objects without type or id returned by {url}: {invalid_objects}"
        )

    @pytest.mark.parametrize("endpoint", ["explain", "details"])
    def check_meta_api_genome_id(self, endpoint):
        """
        Check that explain and details return the genome_uuid as genome_id.
        """
        url, payload = _get_genome_metadata(self.base_url, self.genome_uuid, endpoint)
        genome_id = payload.get("genome_id") if isinstance(payload, dict) else None
        assert genome_id == self.genome_uuid, (
            f"{self.genome_uuid}: {endpoint} returned genome_id={genome_id!r} ({url})"
        )

    def check_meta_api_stats(self):
        """
        Check that stats returns assembly stats with values.
        """
        url, payload = _get_genome_metadata(self.base_url, self.genome_uuid, "stats")
        assembly_stats = ((payload or {}).get("genome_stats") or {}).get("assembly_stats") or {}
        assert any(value is not None for value in assembly_stats.values()), (
            f"{self.genome_uuid}: stats returned no assembly stats ({url})"
        )
