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
Check that every genome in the release has a genome mapping document in Thoas MongoDB.
Checks performed:
    - Check a document for genome_uuid and release_name is present in the metadata.genome_mapping collection.
    - Check the document's release_version matches the release version in the metadata database.
"""

import pytest

DB_NAME = "metadata"
COLLECTION_NAME = "genome_mapping"


def _find_genome_mapping(collection, genome_uuid, release_name):
    """Return the genome_mapping document for a genome in a release, or None if it is missing."""
    return collection.find_one({"genome_uuid": genome_uuid, "release_name": str(release_name)})


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("thoas_mongo")
@pytest.mark.automation_resource("thoas_genome_mapping")
@pytest.mark.parametrize(
    "mongo_client",
    ["thoas_mongo_public_resource_uri", "thoas_mongo_internal_resource_uri"],
    indirect=True
)
class TestThoasGenomeMapping:
    """
    Check that every genome in the release has a genome mapping document in Thoas MongoDB.
    """

    @pytest.fixture(autouse=True)
    def setup(self, genomes, mongo_client):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.genome_uuid = genomes["genome_uuid"]
        self.release_name = genomes["release_name"]
        self.release_version = genomes["release_version"]
        self.collection = mongo_client[DB_NAME][COLLECTION_NAME]

    def check_thoas_genome_mapping_loaded(self):
        """
        Check that the genome mapping document is loaded for the genome in the release.
        Checks for:
            - Document with genome_uuid and release_name present in metadata.genome_mapping.
            - Document release_version matches the metadata database release version.
        Raises:
            AssertionError: If the document is missing or its release_version does not match.
        """
        assert self.release_name is not None, f"Missing release_name for genome_uuid={self.genome_uuid}"

        document = _find_genome_mapping(self.collection, self.genome_uuid, self.release_name)
        if document is None:
            raise AssertionError(
                f"Genome mapping not loaded for genome_uuid: {self.genome_uuid} release_name: {self.release_name} "
                f"in collection {DB_NAME}.{COLLECTION_NAME}"
            )

        expected_version = str(self.release_version)
        if str(document.get("release_version")) != expected_version:
            raise AssertionError(
                f"Genome mapping release_version mismatch for genome_uuid: {self.genome_uuid} "
                f"release_name: {self.release_name}: expected {expected_version}, "
                f"found {document.get('release_version')}"
            )
