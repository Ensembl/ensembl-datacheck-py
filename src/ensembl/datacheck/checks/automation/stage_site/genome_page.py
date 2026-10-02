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
Check that each genome's page loads on the staging site by assembly accession.
The page (<site>/genome/<assembly_accession>) is server side rendered: a known genome responds
with 200 and embeds the loaded genome in window.__PRELOADED_STATE__, an unknown one with 404.
Checks performed:
    - <site>/genome/<assembly_accession> responds with 200, and its preloaded state contains
      a genome with the assembly accession.
"""

import json
import logging

import pytest
import requests

GENOME_PAGE_PATH = "/genome"
PRELOADED_STATE_MARKER = "window.__PRELOADED_STATE__ = "


def _build_genome_page_url(base_url, assembly_accession):
    """Build the genome page URL for an assembly accession."""
    return f"{base_url.rstrip('/')}{GENOME_PAGE_PATH}/{assembly_accession}"


def _get_preloaded_state(html):
    """Extract the window.__PRELOADED_STATE__ JSON object from a server rendered page."""
    start = html.find(PRELOADED_STATE_MARKER)
    if start == -1:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(html[start + len(PRELOADED_STATE_MARKER):])
    except ValueError:
        return None
    return state


def _loaded_accessions(state):
    """Return the assembly accessions of the genomes loaded in the preloaded state."""
    genomes = ((state or {}).get("genome") or {}).get("genomes") or {}
    return {
        (genome.get("assembly") or {}).get("accession_id")
        for genome in genomes.values()
    }


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("stage_site")
class TestStageSiteGenomePage:
    """
    Check that each genome's page loads on the staging site.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, stage_site_resource):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.genome_uuid = genomes["genome_uuid"]
        self.assembly_accession = genomes["assembly_accession"]
        self.base_url = stage_site_resource

    def check_genome_page_by_assembly_accession(self):
        """
        Check that the genome page for the assembly accession loads.
        Checks for:
            - <site>/genome/<assembly_accession> returns HTTP 200.
            - The page's preloaded state contains a genome with the assembly accession.
        Raises:
            AssertionError: If the page fails to load or does not load the genome.
        """
        url = _build_genome_page_url(self.base_url, self.assembly_accession)
        logging.info("Genome page: %s", url)
        response = requests.get(url, timeout=60)

        assert response.status_code == 200, (
            f"{self.genome_uuid}: genome page {url} failed with status code: {response.status_code}"
        )

        state = _get_preloaded_state(response.text)
        assert state is not None, (
            f"{self.genome_uuid}: genome page {url} has no valid preloaded state"
        )

        loaded_accessions = _loaded_accessions(state)
        assert self.assembly_accession in loaded_accessions, (
            f"{self.genome_uuid}: genome page {url} did not load assembly "
            f"{self.assembly_accession!r}; loaded {sorted(filter(None, loaded_accessions))}"
        )
