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
