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
This module performs checks on the Ensembl genome metadata database.

Checks performed:
1. check_database: Ensures the database session is available
2. check_tables: Ensures that all tables contain data
3. check_no_invalid_string_values: Ensures no columns contain "NULL", "null", "", or " " strings
4. check_released_datasets_have_released_releases: Ensures all Released datasets are attached to Released releases
5. check_one_reference_per_biosample: Ensures each biosample has only one reference assembly
6. check_no_faulty_datasets_in_releases: Ensures no Faulty datasets are attached to releases
7. check_only_one_current_dataset_per_type: Ensures each genome has only one is_current dataset per type
8. check_genome_released_with_datasets: Ensures all Released genomes have required datasets
9. check_orphan: Ensures no orphaned records (datasets, organisms, assemblies, etc.)
10. check_missing_checksums: Ensures all Released assembly sequences have checksums
11. check_one_current_genome_per_assembly_provider: Ensures that we don't have multiple current genomes for the same set

To Be implemented when attributes are fixed:
Required attributes are present
"""
import warnings

import pytest
from sqlalchemy import or_, func, String, Text
from ensembl.production.metadata.api.models import Dataset, GenomeDataset, DatasetStatus, EnsemblRelease, ReleaseStatus, \
    Organism, Genome, OrganismGroup, OrganismGroupMember, Assembly, AssemblySequence, DatasetSource, GenomeRelease, \
    DatasetType, GenomeGroup, GenomeGroupMember
from ensembl.production.metadata.api.models.base import Base
from ensembl.datacheck.functions.db_checks import (
    database_connection_check,
    find_orphans
)
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning


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
def check_no_invalid_string_values(db_session):
    """
    Check that no columns contain invalid string values like "NULL", "null", "", or " ".
    Actual NULL values (None) are allowed.
    Note: This check is slow and queries every string column in the database.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any invalid string values are found.
    """
    invalid_values = ["NULL", "null", "", " "]
    problems = []

    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, (String, Text)):
                for invalid_value in invalid_values:
                    count = (
                        db_session.query(func.count())
                        .select_from(table)
                        .filter(column == invalid_value)
                        .scalar()
                    )
                    if count > 0:
                        problems.append({
                            'table': table.name,
                            'column': column.name,
                            'invalid_value': repr(invalid_value),
                            'count': count
                        })

    if problems:
        error_msg = "Found invalid string values in database:\n"
        for problem in problems:
            error_msg += f"  Table '{problem['table']}', Column '{problem['column']}': "
            error_msg += f"{problem['count']} rows with value {problem['invalid_value']}\n"
        pytest.fail(error_msg)


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
    datasets_without_release = (
        db_session.query(Dataset)
        .outerjoin(Dataset.genome_datasets)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            or_(
                GenomeDataset.dataset_id == None,
                GenomeDataset.release_id == None
            )
        )
        .all()
    )

    if datasets_without_release:
        dataset_ids = [ds.dataset_uuid for ds in datasets_without_release]
        assert False, f"Found {len(datasets_without_release)} Released datasets without a release: {dataset_ids}"

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

    problematic_dataset_ids = datasets_with_unreleased_release - datasets_with_released_release

    if problematic_dataset_ids:
        problematic_datasets = (
            db_session.query(Dataset)
            .filter(Dataset.dataset_id.in_(problematic_dataset_ids))
            .all()
        )
        dataset_uuids = [ds.dataset_uuid for ds in problematic_datasets]
        assert False, f"Found {len(problematic_dataset_ids)} Released datasets not attached to any Released releases: {dataset_uuids}"


@pytest.mark.usefixtures("db_session")
def check_one_reference_per_biosample(db_session):
    """
    Check that each biosample has only one assembly marked as is_reference=1.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any biosample has multiple reference assemblies.
    """
    results = (
        db_session.query(
            Organism.biosample_id,
            func.count(Assembly.assembly_id.distinct()).label('reference_count')
        )
        .select_from(Assembly)
        .join(Genome, Assembly.assembly_id == Genome.assembly_id)
        .join(Organism, Organism.organism_id == Genome.organism_id)
        .join(GenomeRelease)
        .filter(GenomeRelease.is_current == 1)
        .filter(Assembly.is_reference == 1)
        .group_by(Organism.biosample_id)
        .having(func.count(Assembly.assembly_id.distinct()) > 1)
        .all()
    )

    if results:
        error_details = []
        for row in results:
            assemblies = (
                db_session.query(Assembly.assembly_uuid)
                .join(Genome)
                .join(Organism)
                .join(GenomeRelease)
                .filter(
                    Organism.biosample_id == row.biosample_id,
                    Assembly.is_reference == 1,
                    GenomeRelease.is_current == 1
                )
                .distinct()
                .all()
            )
            assembly_uuids = [a[0] for a in assemblies]
            error_details.append(f"Biosample {row.biosample_id}: {assembly_uuids}")

        error_msg = f"Found {len(results)} biosamples with multiple reference assemblies:\n  " + "\n  ".join(
            error_details)
        assert False, error_msg


@pytest.mark.usefixtures("db_session")
def check_no_faulty_datasets_in_releases(db_session):
    """
    Check that no Faulty datasets are attached to any releases.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any Faulty datasets are found in releases.
    """
    faulty_datasets_in_releases = (
        db_session.query(Dataset)
        .join(Dataset.genome_datasets)
        .join(GenomeDataset.genome)
        .join(Genome.genome_releases)
        .join(GenomeRelease.ensembl_release)
        .filter(Dataset.status == DatasetStatus.FAULTY)
        .filter(GenomeDataset.release_id.isnot(None))
        .distinct()
        .all()
    )

    if faulty_datasets_in_releases:
        dataset_info = [f"{ds.dataset_uuid} ({ds.name})" for ds in faulty_datasets_in_releases]
        assert False, f"Found {len(faulty_datasets_in_releases)} Faulty datasets attached to releases: {dataset_info}"


@pytest.mark.usefixtures("db_session")
def check_only_one_current_dataset_per_type(db_session):
    """
    Check that each genome has only one is_current dataset for each dataset_type
    in partial released releases.

    For dataset types with multiple_current=0, only one is_current dataset is
    allowed per type per genome.
    For dataset types with multiple_current=1, multiple is_current datasets are
    allowed per type, but only one per dataset name per genome.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any genome has multiple is_current datasets of the same type
                        (or same type+name for multiple_current types).
    """
    base_query = (
        db_session.query(
            Genome.genome_id,
            Genome.production_name,
            DatasetType.name.label('dataset_type'),
            func.count().label('current_count')
        )
        .join(GenomeDataset, Genome.genome_id == GenomeDataset.genome_id)
        .join(Dataset, GenomeDataset.dataset_id == Dataset.dataset_id)
        .join(DatasetType, Dataset.dataset_type_id == DatasetType.dataset_type_id)
        .join(EnsemblRelease, GenomeDataset.release_id == EnsemblRelease.release_id)
        .filter(
            GenomeDataset.is_current == 1,
            EnsemblRelease.release_type == 'partial',
            EnsemblRelease.status == ReleaseStatus.RELEASED
        )
    )

    # For single-current types: only one is_current allowed per type per genome
    single_current_results = (
        base_query
        .filter(DatasetType.multiple_current == 0)
        .group_by(Genome.genome_id, Dataset.dataset_type_id)
        .having(func.count() > 1)
        .all()
    )

    # For multiple-current types: only one is_current allowed per type+name per genome
    multi_current_results = (
        base_query
        .add_columns(Dataset.name.label('dataset_name'))
        .filter(DatasetType.multiple_current == 1)
        .group_by(Genome.genome_id, Dataset.dataset_type_id, Dataset.name)
        .having(func.count() > 1)
        .all()
    )

    problems = []

    for row in single_current_results:
        problems.append(
            f"  Genome {row.genome_id} ({row.production_name}): "
            f"{row.current_count} current '{row.dataset_type}' datasets"
        )

    for row in multi_current_results:
        problems.append(
            f"  Genome {row.genome_id} ({row.production_name}): "
            f"{row.current_count} current '{row.dataset_type}' datasets with name '{row.dataset_name}'"
        )

    if problems:
        error_msg = "Found genomes with multiple is_current datasets of the same type:\n"
        error_msg += "\n".join(problems)
        pytest.fail(error_msg)


@pytest.mark.usefixtures("db_session")
def check_genome_released_with_datasets(db_session):
    """
    Check that all Released genomes have appropriate released datasets.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any genome is missing a released genebuild or assembly dataset.
        Warning: If any genome is missing a released compara dataset.
    """
    all_released_genomes = set(
        db_session.query(Genome.genome_id)
        .join(GenomeRelease)
        .join(EnsemblRelease)
        .filter(EnsemblRelease.status == ReleaseStatus.RELEASED)
        .distinct()
        .all()
    )
    all_released_genomes = {g[0] for g in all_released_genomes}

    genomes_with_genebuild = set(
        db_session.query(Genome.genome_id)
        .join(GenomeDataset)
        .join(Dataset)
        .join(DatasetType)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            DatasetType.name == 'genebuild'
        )
        .distinct()
        .all()
    )
    genomes_with_genebuild = {g[0] for g in genomes_with_genebuild}

    genomes_with_assembly = set(
        db_session.query(Genome.genome_id)
        .join(GenomeDataset)
        .join(Dataset)
        .join(DatasetType)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            DatasetType.name == 'assembly'
        )
        .distinct()
        .all()
    )
    genomes_with_assembly = {g[0] for g in genomes_with_assembly}

    genomes_with_compara = set(
        db_session.query(Genome.genome_id)
        .join(GenomeDataset)
        .join(Dataset)
        .join(DatasetType)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            DatasetType.name == 'homologies'
        )
        .distinct()
        .all()
    )
    genomes_with_compara = {g[0] for g in genomes_with_compara}

    missing_genebuild = all_released_genomes - genomes_with_genebuild
    missing_assembly = all_released_genomes - genomes_with_assembly
    missing_compara = all_released_genomes - genomes_with_compara

    problems = []
    minor_problems = []

    if missing_genebuild:
        genomes = db_session.query(Genome).filter(Genome.genome_id.in_(missing_genebuild)).all()
        for g in genomes:
            problems.append(f"{g.genome_uuid} ({g.production_name}): missing genebuild")

    if missing_assembly:
        genomes = db_session.query(Genome).filter(Genome.genome_id.in_(missing_assembly)).all()
        for g in genomes:
            problems.append(f"{g.genome_uuid} ({g.production_name}): missing assembly")

    if missing_compara:
        genomes = db_session.query(Genome).filter(Genome.genome_id.in_(missing_compara)).all()
        for g in genomes:
            minor_problems.append(f"{g.genome_uuid} ({g.production_name}): missing compara")

    if problems:
        error_msg = "Found Released genomes missing required datasets:\n  " + "\n  ".join(problems)
        pytest.fail(error_msg)

    if minor_problems:
        error_msg = "Found Released genomes missing compara datasets:\n  " + "\n  ".join(minor_problems)
        warnings.warn(
            EnsemblDatacheckWarning(error_msg, "ensembl_genome_metadata", "check_genome_released_with_datasets"))


@pytest.mark.usefixtures("db_session")
def check_orphan(db_session):
    """
    Check that all records have appropriate parent relationships.

    Checks for:
    - Datasets without genome_dataset entries (Fail)
    - Organisms without genomes (Fail)
    - Organism groups without members (Warn)
    - Assemblies without genomes (Fail)
    - Genome groups without members (Warn)
    - Dataset sources without datasets (Warn)

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any critical orphaned records are found.
    """
    find_orphans(
        db_session,
        source_model=Dataset,
        join_target=Dataset.genome_datasets,
        filter_column=GenomeDataset.dataset_id,
        uuid_field='dataset_uuid',
        entity_name='datasets'
    )

    find_orphans(
        db_session,
        source_model=Organism,
        join_target=Genome,
        filter_column=Genome.organism_id,
        uuid_field='organism_uuid',
        entity_name='organisms'
    )

    find_orphans(
        db_session,
        source_model=OrganismGroup,
        join_target=OrganismGroupMember,
        filter_column=OrganismGroupMember.organism_group_id,
        uuid_field='name',
        entity_name='organism_group',
        warn=True
    )

    find_orphans(
        db_session,
        source_model=GenomeGroup,
        join_target=GenomeGroupMember,
        filter_column=GenomeGroupMember.genome_group_id,
        uuid_field='name',
        entity_name='genome_group',
        warn=True
    )
    find_orphans(
        db_session,
        source_model=Assembly,
        join_target=Genome,
        filter_column=Genome.assembly_id,
        uuid_field='assembly_uuid',
        entity_name='assembly'
    )

    find_orphans(
        db_session,
        source_model=DatasetSource,
        join_target=Dataset,
        filter_column=Dataset.dataset_source_id,
        uuid_field='name',
        entity_name='dataset_source',
        warn=True
    )


@pytest.mark.usefixtures("db_session")
def check_missing_checksums(db_session):
    """
    Check that all Released assembly_sequences have checksums.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any checksums are missing for released datasets.
    """
    assemblies_missing_checksums = (
        db_session.query(Assembly)
        .join(Assembly.assembly_sequences)
        .join(Assembly.genomes)
        .join(Genome.genome_releases)
        .join(GenomeRelease.ensembl_release)
        .filter(EnsemblRelease.status == ReleaseStatus.RELEASED)
        .filter(
            or_(
                AssemblySequence.md5.is_(None),
                AssemblySequence.sha512t24u.is_(None)
            )
        )
        .distinct()
        .all()
    )

    if assemblies_missing_checksums:
        assembly_ids = [a.assembly_uuid for a in assemblies_missing_checksums]
        assert False, f"Found {len(assemblies_missing_checksums)} Released assemblies with missing checksums: {assembly_ids}"

@pytest.mark.usefixtures("db_session")
def check_one_current_genome_per_assembly_provider(db_session):
    """
    Check that for each (assembly, provider) combination, only one genome has
    an is_current GenomeRelease entry in a partial released release.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any (assembly, provider) group has more than one is_current genome.
    """
    results = (
        db_session.query(
            Assembly.assembly_uuid,
            Genome.provider_name,
            func.count().label('current_count'),
            func.group_concat(Genome.genome_uuid).label('genome_uuids')
        )
        .join(Genome, Genome.assembly_id == Assembly.assembly_id)
        .join(GenomeRelease, GenomeRelease.genome_id == Genome.genome_id)
        .join(EnsemblRelease, EnsemblRelease.release_id == GenomeRelease.release_id)
        .filter(
            GenomeRelease.is_current == 1,
            EnsemblRelease.release_type == 'partial',
            EnsemblRelease.status == ReleaseStatus.RELEASED
        )
        .group_by(Assembly.assembly_uuid, Genome.provider_name)
        .having(func.count() > 1)
        .all()
    )

    if results:
        problems = []
        for row in results:
            problems.append(
                f"  Assembly {row.assembly_uuid}, provider '{row.provider_name}': "
                f"{row.current_count} is_current genomes ({row.genome_uuids})"
            )
        error_msg = "Found multiple is_current genomes for the same assembly/provider combination:\n"
        error_msg += "\n".join(problems)
        pytest.fail(error_msg)