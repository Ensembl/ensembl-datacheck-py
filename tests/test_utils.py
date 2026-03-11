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

"""Integration tests for utility helpers backed by a real metadata SQLite DB."""

from pathlib import Path

import pytest

from ensembl.datacheck.functions.utils import get_genomes_from_metadata_db

pytestmark = pytest.mark.filterwarnings(
    "ignore:Could not instantiate type <class 'sqlalchemy.sql.sqltypes.INTEGER'> with reflected arguments \\['1'\\]; using no arguments\\.:sqlalchemy.exc.SAWarning"
)


def _metadata_db_url():
    """Build SQLAlchemy connection URL for the test metadata DB."""
    db_path = Path(__file__).parent / "database" / "ensembl_genome_metadata.db"
    return f"sqlite:///{db_path.resolve()}"


def test_get_genomes_from_metadata_db_reads_data_from_sqlite_fixture():
    """Verify genomes are fetched from the real metadata SQLite database."""
    genomes = list(get_genomes_from_metadata_db(db_url=_metadata_db_url()))

    assert genomes
    assert isinstance(genomes[0], dict)
    assert {
        "release_id",
        "release_name",
        "release_version",
        "release_status",
        "release_label",
        "release_is_current",
        "genome_uuid",
        "species",
        "genome_submitted",
        "genebuild_date",
        "scientific_name",
        "db_name",
        "assembly_accession",
        "assembly_name",
        "dataset_uuid",
        "dataset_status",
        "dataset_name",
        "dataset_type",
        "genome_release",
        "genome_dataset_release_id",
        "genome_dataset_is_current",
    }.issubset(genomes[0].keys())
    assert {row["dataset_name"] for row in genomes} == {"genebuild"}
    assert {row["dataset_type"] for row in genomes} == {"genebuild"}


def test_get_genomes_from_metadata_db_filters_by_release_name_with_real_db():
    """Verify comma-separated release_name input filters rows from the real DB."""
    all_genomes = list(get_genomes_from_metadata_db(db_url=_metadata_db_url()))
    available_releases = sorted({row["release_name"] for row in all_genomes})
    assert len(available_releases) >= 2

    target_releases = available_releases[:2]
    filtered = list(
        get_genomes_from_metadata_db(
            db_url=_metadata_db_url(),
            release_name=",".join(target_releases),
        )
    )
    expected = [row for row in all_genomes if row["release_name"] in set(target_releases)]

    assert filtered
    assert len(filtered) == len(expected)
    assert {row["release_name"] for row in filtered} == set(target_releases)


def test_get_genomes_from_metadata_db_filters_by_genome_uuid_with_real_db():
    """Verify genome_uuids input limits results to the requested genome UUIDs."""
    all_genomes = list(get_genomes_from_metadata_db(db_url=_metadata_db_url()))
    available_uuids = sorted({row["genome_uuid"] for row in all_genomes})
    assert len(available_uuids) >= 2

    requested_uuids = available_uuids[:2]
    filtered = list(
        get_genomes_from_metadata_db(
            db_url=_metadata_db_url(),
            genome_uuids=requested_uuids,
        )
    )

    assert filtered
    assert {row["genome_uuid"] for row in filtered}.issubset(set(requested_uuids))
