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
Check that each genome's sample gene can be found through the staging site gene search.
The gene search API (<site>/api/search/genes) takes a POST with {"query", "genome_ids"}.
Checks performed:
    - Search for the genebuild.sample_gene dataset attribute value, restricted to the genome,
      responds with 200, has at least one hit, and a match's genome_id is the genome_uuid.
"""

import logging

import pytest
import requests

from ensembl.datacheck.functions.utils import get_genome_dataset_attribute

GENE_SEARCH_PATH = "/api/search/genes"
SAMPLE_GENE_ATTRIBUTE = "genebuild.sample_gene"


def _build_gene_search_url(base_url):
    """Build the gene search API URL for a site."""
    return f"{base_url.rstrip('/')}{GENE_SEARCH_PATH}"


def _search_genes(base_url, query, genome_uuid):
    """Query the gene search API for a genome and return (url, payload)."""
    url = _build_gene_search_url(base_url)
    logging.info("Gene search: %s query=%s genome_id=%s", url, query, genome_uuid)
    response = requests.post(url, json={"query": query, "genome_ids": [genome_uuid]}, timeout=60)

    if response.status_code != 200:
        raise AssertionError(
            f"Gene search endpoint failed for URL: {response.url} "
            f"with status code: {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"Gene search endpoint did not return valid JSON for URL: {response.url}"
        ) from exc

    return response.url, payload


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("stage_site")
class TestStageSiteGeneSearch:
    """
    Check that each genome's sample gene is searchable in the staging site.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, stage_site_resource, db_session):
        """
        Prepare commonly used attributes for each test invocation.
        """
        assert db_session is not None, (
            "Missing --database for gene search checks. Provide a metadata database URL with --database."
        )
        self.genome_uuid = genomes["genome_uuid"]
        self.base_url = stage_site_resource
        self.sample_gene = get_genome_dataset_attribute(
            db_session, self.genome_uuid, SAMPLE_GENE_ATTRIBUTE
        )

    def check_gene_search_by_sample_gene(self):
        """
        Check that searching for the genome's sample gene returns a hit for the genome.
        Checks for:
            - Gene search endpoint returns HTTP 200.
            - meta.total_hits is at least 1.
            - A match's genome_id is the genome_uuid.
        Raises:
            AssertionError: If the sample gene is missing, or the search does not find it.
        """
        assert self.sample_gene, (
            f"{self.genome_uuid}: missing {SAMPLE_GENE_ATTRIBUTE} dataset attribute in metadata"
        )

        url, payload = _search_genes(self.base_url, self.sample_gene, self.genome_uuid)
        total_hits = (payload.get("meta") or {}).get("total_hits", 0)
        assert total_hits >= 1, (
            f"{self.genome_uuid}: no gene search hits for sample gene {self.sample_gene!r} ({url})"
        )

        found_genome_ids = [match.get("genome_id") for match in payload.get("matches") or []]
        assert self.genome_uuid in found_genome_ids, (
            f"{self.genome_uuid}: gene search for sample gene {self.sample_gene!r} returned "
            f"no match for the genome ({url}); found {found_genome_ids}"
        )
