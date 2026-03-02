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
Check that the beta resources are loaded for the genome in the Compara MongoDB.
Checks performed:
    - Check genome_uuid  present in specified collection (genome_discovery_compara) of Compara MongoDB.
"""

from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
import pytest


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_mongo")
@pytest.mark.parametrize(
    "mongo_client",
    ["compara_mongo_uri"],
    indirect=True
)
def check_compara_mongo_loaded(genomes, mongo_client):
    """
    Check that the beta resources  loaded in Compara MongoDB.
    Args:
        genomes (list): List of genome UUIDs to check.
        mongo_client: A MongoClient instance connected to the Compara MongoDB, provided by the pytest fixture.
    Raises:
        AssertionError: If the beta resources for a genome not loaded in MongoDB.
    """

    resource_type = "compara_public"
    db_name = "compara"
    collection_name = "genome_discovery_compara"
    doc_key = "query_genome_id"
    genome_uuid = genomes['genome_uuid']

    db = mongo_client[db_name]
    collection = db[collection_name]

    if collection.count_documents({doc_key: genome_uuid}, limit=1) == 0 :
        raise AssertionError(f"Beta resources for {resource_type} are not loaded for genome_uuid: {genome_uuid}")
