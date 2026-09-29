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
Check that the genesearch document for each genome UUID is indexed in Solr.
Checks performed:
    - Check that the genome_uuid is present (numFound > 0) in the Solr collection,
      for both staging and production environments.
"""

import logging

import requests
import pytest

SOLR_QUERY_FIELD = "genome_id"


def _get_solr_collection(release_name):
    """Return the Solr collection name (beta_even/beta_odd) for a release."""
    return "beta_even" if int(release_name) % 2 == 0 else "beta_odd"


def _build_solr_select_url(base_url, collection, genome_uuid):
    """Build the Solr select URL used to look up a genome_id document."""
    return (
        f"{base_url.rstrip('/')}/solr/{collection}/select"
        f"?q=*&fq={SOLR_QUERY_FIELD}:{genome_uuid}&wt=json"
    )


def _get_num_found(payload):
    """Extract numFound from a Solr select response payload."""
    response_section = payload.get("response", {})
    assert isinstance(response_section, dict), "Solr response field 'response' is not an object."
    return response_section.get("numFound", 0)


@pytest.fixture(scope="session")
def solr_api_resource(request, automation_resource_config):
    """
    Return a Solr API base URI for the parametrized resource type.
    """
    resource_type = getattr(request, "param", None)
    if not resource_type:
        raise ValueError("Please parametrize the solr_api_resource fixture with a resource type")

    resource = automation_resource_config.get(resource_type)
    if not resource:
        pytest.skip(f"Resource '{resource_type}' not found in config file")

    if resource.get("ignore") == "True":
        pytest.skip(f"Skipped '{resource_type}' check as ignore=True in config")

    uri = resource.get("uri")
    if not uri:
        pytest.skip(f"Solr API URI missing for '{resource_type}'")

    return uri


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("solr")
@pytest.mark.parametrize(
    "solr_api_resource",
    [
        "solr_api_stage",
        "solr_api_prod",
    ],
    indirect=True
)
class TestGenesearchSolrLoaded:
    """
    Check that each genome's genesearch document is indexed in Solr for stage and prod.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, solr_api_resource):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.genome_uuid = genomes["genome_uuid"]
        self.base_url = solr_api_resource
        self.solr_collection = _get_solr_collection(genomes["release_name"])

    def _get_solr_select_response(self):
        url = _build_solr_select_url(self.base_url, self.solr_collection, self.genome_uuid)

        logging.info(f"Checking Solr index for genome UUID: {self.genome_uuid}")
        logging.info(f"URL: {url}")

        return requests.get(url, timeout=30)

    def check_genesearch_solr_indexed(self):
        """
        Check that the genome's genesearch document is present in Solr.
        Checks for:
            - Solr select endpoint returns HTTP 200.
            - Solr numFound for genome_id is greater than 0.
        Raises:
            AssertionError: If the endpoint fails, or the genome is missing from the Solr index.
        """
        response = self._get_solr_select_response()

        if response.status_code != 200:
            raise AssertionError(
                f"Solr select endpoint failed for URL: {response.url} "
                f"with status code: {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AssertionError(
                f"Solr select endpoint did not return valid JSON for URL: {response.url}"
            ) from exc

        num_found = _get_num_found(payload)
        if num_found == 0:
            raise AssertionError(
                f"{self.genome_uuid}: missing from Solr collection '{self.solr_collection}'"
            )
