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
Check that the beta resources are loaded for the genome in the specified collection of Thoas MongoDB.
Checks performed:
    - Check genome_uuid  present in specified collection (genome, gene, transcript, protein, region) .
    - Check scientific_name  present in specified collection (species, organism) .
"""

from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
import pytest

@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("thoas_mongo")
@pytest.mark.parametrize(
    "mongo_client",
    ["thoas_mongo_public_resource_uri", "thoas_mongo_internal_resource_uri"],
    indirect=True
)
class TestThoasMongoLoaded:
    """
    Check that the beta resources are loaded in multiple collections of Thoas MongoDB.
    """

    # collections to check
    collections_to_check = ["genome", "gene", "transcript", "protein", "region"]

    @pytest.fixture(autouse=True)
    def setup(self, genomes, mongo_client):
        """
        Prepare commonly used attributes for each test invocation.
        """
        release_version = str(genomes["release_version"])
        self.db_name = f"release_{release_version.replace('.', '_')}"
        self.doc_key = "genome_id"
        self.genome_uuid = genomes["genome_uuid"]
        self.scientific_name = genomes["scientific_name"]
        self.mongo_client = mongo_client
        self.db = self.mongo_client[self.db_name]

    @pytest.mark.parametrize("collection_name", collections_to_check)
    def check_thoas_mongo_loaded_for_collection(self, collection_name):
        """
        Check that the beta resources are loaded for the genome in the specified collection of Thoas MongoDB.
        Checks for:
            - Check genome_uuid  present in specified collection (genome, gene, transcript, protein, region) .
        Args:
            collection_name (str): The name of the MongoDB collection to check.
        Raises:
            AssertionError: If the beta resources for the genome are not loaded in the specified collection.

        """
        collection = self.db[collection_name]

        if collection.count_documents({self.doc_key: self.genome_uuid}, limit=1) == 0:
            raise AssertionError(
                f"Beta resources thoas not loaded with genome_uuid: {self.genome_uuid} in collection {collection_name}"
            )

    @pytest.mark.parametrize("collection_scientific_name", ['species', 'organism'])
    def check_thoas_mongo_scientific_name(self, collection_scientific_name):
        """
        Check that the beta resources are loaded for the genome in the specified collection of Thoas MongoDB based on scientific name.
        Checks for:
            - Check scientific_name  present in specified collection (species, organism) .
        Args:
            collection_scientific_name (str): The name of the MongoDB collection to check for scientific name.
        Raises:
            AssertionError: If the beta resources for the genome are not loaded in the specified collection based on scientific name.
        """
        collection = self.db[collection_scientific_name]
        if collection.count_documents({"scientific_name": self.scientific_name}, limit=1) == 0:
            raise AssertionError(
                f"Beta resources thoas not loaded with scientific name: {self.scientific_name} in collection {collection_scientific_name}"
            )