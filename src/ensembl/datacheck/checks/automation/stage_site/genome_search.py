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
Check that each genome can be found through the staging site genome selector search.
The genome selector page (<site>/genome-selector/search?query=...) is rendered client side
from the search API (<site>/api/search/genomes?query=...), so the API is queried directly.
Checks performed:
    - Search by genome_uuid returns a match whose genome_id is the genome_uuid,
      and whose assembly url responds with 200.
    - Search by assembly accession returns a match whose genome_id is the genome_uuid,
      and whose assembly url responds with 200.
"""

import logging

import pytest
import requests

GENOME_SEARCH_PATH = "/api/search/genomes"


def _build_genome_search_url(base_url):
    """Build the genome search API URL for a site."""
    return f"{base_url.rstrip('/')}{GENOME_SEARCH_PATH}"


def _search_genomes(base_url, query):
    """Query the genome search API and return (url, matches)."""
    url = _build_genome_search_url(base_url)
    logging.info("Genome search: %s?query=%s", url, query)
    response = requests.get(url, params={"query": query}, timeout=60)

    if response.status_code != 200:
        raise AssertionError(
            f"Genome search endpoint failed for URL: {response.url} "
            f"with status code: {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"Genome search endpoint did not return valid JSON for URL: {response.url}"
        ) from exc

    return response.url, payload.get("matches") or []


def _check_genome_search(base_url, genome_uuid, query_field, query):
    """
    Search by query and check the genome_uuid is matched and its assembly url responds with 200.
    """
    url, matches = _search_genomes(base_url, query)
    match = next((match for match in matches if match.get("genome_id") == genome_uuid), None)
    assert match, (
        f"{genome_uuid}: not found by genome search for {query_field}={query!r} ({url}); "
        f"found {[match.get('genome_id') for match in matches]}"
    )

    assembly_url = (match.get("assembly") or {}).get("url")
    assert assembly_url, f"{genome_uuid}: missing assembly url ({url})"
    assembly_response = requests.head(assembly_url, allow_redirects=True, timeout=60)
    assert assembly_response.status_code == 200, (
        f"{genome_uuid}: assembly url {assembly_url} is not reachable "
        f"(status code: {assembly_response.status_code})"
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("stage_site")
class TestStageSiteGenomeSearch:
    """
    Check that each genome is searchable in the staging site genome selector.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, stage_site_resource):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.genome_uuid = genomes["genome_uuid"]
        self.assembly_accession = genomes["assembly_accession"]
        self.base_url = stage_site_resource

    def check_genome_search_by_genome_uuid(self):
        """
        Check that searching by genome_uuid returns the genome.
        Raises:
            AssertionError: If the genome is not matched or its assembly url is not reachable.
        """
        _check_genome_search(self.base_url, self.genome_uuid, "genome_uuid", self.genome_uuid)

    def check_genome_search_by_assembly_accession(self):
        """
        Check that searching by assembly accession returns the genome.
        Raises:
            AssertionError: If the genome is not matched or its assembly url is not reachable.
        """
        _check_genome_search(
            self.base_url, self.genome_uuid, "assembly_accession", self.assembly_accession
        )
