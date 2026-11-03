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

from decimal import Decimal

import pytest

from ensembl.datacheck.checks.automation import automation_thoas_genome_mapping

GENOME_UUID = "a73351f7-93e7-11ec-a39d-005056b38ce3"
MAPPING_DOCUMENT = {
    "_id": f"{GENOME_UUID}:1",
    "genome_uuid": GENOME_UUID,
    "release_version": "110.1",
    "release_name": "1",
}


class _DummyCollection:
    def __init__(self, documents):
        self.documents = documents

    def find_one(self, query):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None


def _make_check(documents, release_name="1", release_version=Decimal("110.1")):
    check = automation_thoas_genome_mapping.TestThoasGenomeMapping()
    check.genome_uuid = GENOME_UUID
    check.release_name = release_name
    check.release_version = release_version
    check.collection = _DummyCollection(documents)
    return check


def test_find_genome_mapping_returns_document():
    collection = _DummyCollection([MAPPING_DOCUMENT])

    assert automation_thoas_genome_mapping._find_genome_mapping(collection, GENOME_UUID, "1") == MAPPING_DOCUMENT


def test_find_genome_mapping_matches_non_string_release_name():
    collection = _DummyCollection([MAPPING_DOCUMENT])

    assert automation_thoas_genome_mapping._find_genome_mapping(collection, GENOME_UUID, 1) == MAPPING_DOCUMENT


def test_find_genome_mapping_returns_none_for_other_release():
    collection = _DummyCollection([MAPPING_DOCUMENT])

    assert automation_thoas_genome_mapping._find_genome_mapping(collection, GENOME_UUID, "2") is None


class TestThoasGenomeMappingCheck:
    """
    Exercise TestThoasGenomeMapping.check_thoas_genome_mapping_loaded without a live MongoDB.
    """

    def test_check_passes_when_document_present(self):
        check = _make_check([MAPPING_DOCUMENT])

        check.check_thoas_genome_mapping_loaded()

    def test_check_fails_when_genome_missing(self):
        check = _make_check([])

        with pytest.raises(AssertionError, match="Genome mapping not loaded"):
            check.check_thoas_genome_mapping_loaded()

    def test_check_fails_when_only_other_release_loaded(self):
        check = _make_check([MAPPING_DOCUMENT], release_name="2", release_version=Decimal("111.1"))

        with pytest.raises(AssertionError, match="Genome mapping not loaded"):
            check.check_thoas_genome_mapping_loaded()

    def test_check_fails_on_release_version_mismatch(self):
        check = _make_check([dict(MAPPING_DOCUMENT, release_version="110.2")])

        with pytest.raises(AssertionError, match="expected 110.1, found 110.2"):
            check.check_thoas_genome_mapping_loaded()

    def test_check_fails_when_release_name_missing(self):
        check = _make_check([MAPPING_DOCUMENT], release_name=None)

        with pytest.raises(AssertionError, match="Missing release_name"):
            check.check_thoas_genome_mapping_loaded()
