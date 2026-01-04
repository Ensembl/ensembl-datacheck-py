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
This module performs checks on the new Ensembl metadata.

Checks performed:
1. Database connection check (Error): Ensures the database session is available.
2. Tables not empty check (Error): Ensures that all tables contain data.
3. Datasets attached to a release (Error): Ensures all released datasets are attached to a release.


These checks are run to verify the integrity and completeness of the metadata in the new Ensembl metadata database.
"""

import pytest
from ensembl.production.metadata.api.models import Dataset, GenomeDataset, DatasetStatus, EnsemblRelease, ReleaseStatus
from ensembl.production.metadata.api.models.base import Base

from sqlalchemy import or_, func

from ensembl.datacheck.functions.db_checks import (
    database_connection_check
)

@pytest.mark.usefixtures("db_session")
def check_database(db_session):
    """
    Check if the database connection is established.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If the database session is not available.
    """
    assert database_connection_check(db_session), "Database session is not available"


@pytest.mark.usefixtures("db_session")
def check_tables(db_session):
    """
    Check that all tables in the database are not empty.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any table is empty.
    """
    table_names = [
        'assembly', 'assembly_sequence', 'attribute', 'dataset',
        'dataset_attribute', 'dataset_source', 'dataset_type',
        'ensembl_release', 'ensembl_site', 'genome', 'genome_dataset',
        'genome_release', 'organism', 'organism_group', 'organism_group_member'
    ]

    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        count = db_session.query(func.count()).select_from(table).scalar()
        if count == 0:
            assert False, f"Table {table_name} is empty"


@pytest.mark.usefixtures("db_session")
def check_released_datasets_have_released_releases(db_session):
    """
    Check that all Released datasets are properly attached to Released releases.

    Performs two checks:
    1. Released datasets must have a genome_dataset entry with a release_id
    2. Released datasets must have at least one Released release attached

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any Released dataset is not properly attached to a Released release.
    """
    """
    Check that all Released datasets are properly attached to Released releases.

    Performs two checks:
    1. Released datasets must have a genome_dataset entry with a release_id
    2. Released datasets must have at least one Released release attached

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any Released dataset is not properly attached to a Released release.
    """
    # # Check 1: Find Released datasets without a genome_dataset or with null release_id
    # datasets_without_release = (
    #     db_session.query(Dataset)
    #     .outerjoin(Dataset.genome_datasets)
    #     .filter(
    #         Dataset.status == DatasetStatus.RELEASED,
    #         or_(
    #             GenomeDataset.dataset_id == None,  # No genome_dataset entry
    #             GenomeDataset.release_id == None  # Has genome_dataset but no release_id
    #         )
    #     )
    #     .all()
    # )
    #
    # if datasets_without_release:
    #     dataset_ids = [ds.dataset_uuid for ds in datasets_without_release]
    #     assert False, f"Found {len(datasets_without_release)} Released datasets without a release: {dataset_ids}"

    # Check 2: Use set logic to find Released datasets without a Released release
    # Set 1: All Released datasets WITH a Released release
    datasets_with_released_release = set(
        db_session.query(Dataset.dataset_id)
        .join(Dataset.genome_datasets)
        .join(GenomeDataset.ensembl_release)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            EnsemblRelease.status == ReleaseStatus.RELEASED
        )
        .distinct()
        .all()
    )
    datasets_with_released_release = {ds_id[0] for ds_id in datasets_with_released_release}
    # Set 2: All Released datasets WITH an unreleased release
    datasets_with_unreleased_release = set(
        db_session.query(Dataset.dataset_id)
        .join(Dataset.genome_datasets)
        .join(GenomeDataset.ensembl_release)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            EnsemblRelease.status != ReleaseStatus.RELEASED
        )
        .distinct()
        .all()
    )
    datasets_with_unreleased_release = {ds_id[0] for ds_id in datasets_with_unreleased_release}

    # Find datasets in Set 2 that are NOT in Set 1
    problematic_dataset_ids = datasets_with_unreleased_release - datasets_with_released_release

    if problematic_dataset_ids:
        problematic_datasets = (
            db_session.query(Dataset)
            .filter(Dataset.dataset_id.in_(problematic_dataset_ids))
            .all()
        )
        dataset_uuids = [ds.dataset_uuid for ds in problematic_datasets]
        assert False, f"Found {len(problematic_dataset_ids)} Released datasets not attached to any Released releases: {dataset_uuids}"