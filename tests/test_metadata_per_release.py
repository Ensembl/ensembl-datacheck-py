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

"""Tests for per-release metadata datachecks."""

from pathlib import Path
import shutil

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ensembl.datacheck.checks.metadata_per_release import CheckMetadataPerRelease
from ensembl.production.metadata.api.models import (
    Attribute,
    Dataset,
    DatasetAttribute,
    DatasetStatus,
    EnsemblRelease,
    Genome,
    GenomeDataset,
    GenomeRelease,
    ReleaseStatus,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Could not instantiate type <class 'sqlalchemy.sql.sqltypes.INTEGER'> with reflected arguments \\['1'\\]; using no arguments\\.:sqlalchemy.exc.SAWarning"
)


@pytest.fixture
def metadata_session(tmp_path):
    """Create a writable copy of the metadata DB fixture."""
    source_db = Path(__file__).parent / "database" / "ensembl_genome_metadata.db"
    copied_db = tmp_path / "ensembl_genome_metadata.db"
    shutil.copyfile(source_db, copied_db)

    engine = create_engine(f"sqlite:///{copied_db}")
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _released_release(metadata_session):
    release = (
        metadata_session.query(EnsemblRelease)
        .filter(EnsemblRelease.status == ReleaseStatus.RELEASED)
        .filter(EnsemblRelease.name.isnot(None))
        .filter(EnsemblRelease.name != "")
        .order_by(EnsemblRelease.name)
        .first()
    )
    assert release is not None
    return release


def _checker(metadata_session, release_name):
    checker = CheckMetadataPerRelease()
    checker.db_session = metadata_session
    checker.release_name = release_name
    return checker


def test_check_genomes_in_release_are_current_passes_when_counts_match(metadata_session):
    release = _released_release(metadata_session)

    _checker(metadata_session, release.name).check_genomes_in_release_are_current()


def test_check_genomes_in_release_are_current_fails_when_counts_differ(metadata_session):
    release = _released_release(metadata_session)
    genome_release = (
        metadata_session.query(GenomeRelease)
        .filter(GenomeRelease.release_id == release.release_id)
        .filter(GenomeRelease.is_current == 1)
        .first()
    )
    assert genome_release is not None
    genome_release.is_current = 0
    metadata_session.flush()

    with pytest.raises(AssertionError, match="released genomes.*is_current"):
        _checker(metadata_session, release.name).check_genomes_in_release_are_current()


def test_check_genomes_in_release_are_current_fails_when_no_released_genomes(metadata_session):
    with pytest.raises(AssertionError, match="Assign all genomes to a release first"):
        _checker(metadata_session, "no_such_release").check_genomes_in_release_are_current()


def _released_genome_datasets(metadata_session, release):
    rows = (
        metadata_session.query(GenomeDataset)
        .join(Dataset, Dataset.dataset_id == GenomeDataset.dataset_id)
        .filter(GenomeDataset.release_id == release.release_id)
        .filter(Dataset.status == DatasetStatus.RELEASED)
        .all()
    )
    assert rows
    return rows


def test_check_genome_datasets_in_release_are_current_passes_when_counts_match(metadata_session):
    release = _released_release(metadata_session)
    for genome_dataset in _released_genome_datasets(metadata_session, release):
        genome_dataset.is_current = 1
    metadata_session.flush()

    _checker(metadata_session, release.name).check_genome_datasets_in_release_are_current()


def test_check_genome_datasets_in_release_are_current_fails_when_counts_differ(metadata_session):
    release = _released_release(metadata_session)
    genome_datasets = _released_genome_datasets(metadata_session, release)
    for genome_dataset in genome_datasets:
        genome_dataset.is_current = 1
    genome_datasets[0].is_current = 0
    metadata_session.flush()

    with pytest.raises(AssertionError, match="released genome datasets.*is_current"):
        _checker(metadata_session, release.name).check_genome_datasets_in_release_are_current()


def test_check_genome_datasets_in_release_are_current_fails_when_no_released_datasets(metadata_session):
    with pytest.raises(AssertionError, match="Attach all datasets to a release first"):
        _checker(metadata_session, "no_such_release").check_genome_datasets_in_release_are_current()


def _release_genome_dataset_rows(metadata_session, release):
    rows = (
        metadata_session.query(
            Genome.genome_id,
            Genome.genome_uuid,
            GenomeDataset.dataset_id
        )
        .join(GenomeDataset, GenomeDataset.genome_id == Genome.genome_id)
        .filter(GenomeDataset.release_id == release.release_id)
        .order_by(Genome.genome_id)
        .all()
    )
    assert rows

    rows_by_genome = {}
    for genome_id, genome_uuid, dataset_id in rows:
        rows_by_genome.setdefault(genome_id, (genome_uuid, dataset_id))
    return list(rows_by_genome.values())


def _prepare_required_attribute_values(
    metadata_session,
    release,
    missing_genome_uuid=None,
    empty_value_genome_uuid=None,
):
    for attribute in metadata_session.query(Attribute).all():
        attribute.required = 0

    required_attribute = Attribute(
        name="datacheck.required.attribute",
        label="Datacheck required attribute",
        type="string",
        required=1,
    )
    metadata_session.add(required_attribute)
    metadata_session.flush()

    genome_dataset_rows = _release_genome_dataset_rows(metadata_session, release)
    for genome_uuid, dataset_id in genome_dataset_rows:
        if genome_uuid == missing_genome_uuid:
            continue
        value = "" if genome_uuid == empty_value_genome_uuid else "present"
        metadata_session.add(
            DatasetAttribute(
                dataset_id=dataset_id,
                attribute_id=required_attribute.attribute_id,
                value=value,
            )
        )

    metadata_session.flush()
    return required_attribute.name, genome_dataset_rows


def test_check_genomes_in_release_have_required_attributes_passes_when_values_present(metadata_session):
    release = _released_release(metadata_session)
    _prepare_required_attribute_values(metadata_session, release)

    _checker(metadata_session, release.name).check_genomes_in_release_have_required_attributes()


def test_check_genomes_in_release_have_required_attributes_fails_when_attribute_missing(metadata_session):
    release = _released_release(metadata_session)
    genome_dataset_rows = _release_genome_dataset_rows(metadata_session, release)
    missing_genome_uuid = genome_dataset_rows[0][0]
    required_attribute_name, _ = _prepare_required_attribute_values(
        metadata_session,
        release,
        missing_genome_uuid=missing_genome_uuid,
    )

    with pytest.raises(AssertionError, match=required_attribute_name):
        _checker(metadata_session, release.name).check_genomes_in_release_have_required_attributes()


def test_check_genomes_in_release_have_required_attributes_fails_when_value_empty(metadata_session):
    release = _released_release(metadata_session)
    genome_dataset_rows = _release_genome_dataset_rows(metadata_session, release)
    required_attribute_name, _ = _prepare_required_attribute_values(
        metadata_session,
        release,
        empty_value_genome_uuid=genome_dataset_rows[0][0],
    )

    with pytest.raises(AssertionError, match=required_attribute_name):
        _checker(metadata_session, release.name).check_genomes_in_release_have_required_attributes()


def _genome_release_for_release(metadata_session, release):
    genome_release = (
        metadata_session.query(GenomeRelease)
        .filter(GenomeRelease.release_id == release.release_id)
        .first()
    )
    assert genome_release is not None
    genome = (
        metadata_session.query(Genome)
        .filter(Genome.genome_id == genome_release.genome_id)
        .one()
    )
    return genome, genome_release


def test_check_suppressed_genomes_in_release_are_not_current_passes_when_not_current(metadata_session):
    release = _released_release(metadata_session)
    genome, genome_release = _genome_release_for_release(metadata_session, release)
    genome.suppressed = 1
    genome_release.is_current = 0
    metadata_session.flush()

    _checker(metadata_session, release.name).check_suppressed_genomes_in_release_are_not_current()


def test_check_suppressed_genomes_in_release_are_not_current_fails_when_current(metadata_session):
    release = _released_release(metadata_session)
    genome, genome_release = _genome_release_for_release(metadata_session, release)
    genome.suppressed = 1
    genome_release.is_current = 1
    metadata_session.flush()

    with pytest.raises(AssertionError, match=genome.genome_uuid):
        _checker(metadata_session, release.name).check_suppressed_genomes_in_release_are_not_current()
