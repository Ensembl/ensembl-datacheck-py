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

"""Tests for full metadata datachecks."""

from pathlib import Path
import shutil

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ensembl.datacheck.checks.metadata_full import (
    check_released_datasets_have_released_releases,
)
from ensembl.production.metadata.api.models import (
    Dataset,
    DatasetStatus,
    EnsemblRelease,
    Genome,
    GenomeDataset,
    GenomeRelease,
    ReleaseStatus,
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


def test_released_assembly_attached_to_unreleased_genome_is_valid(metadata_session):
    """A released assembly can be reused by a genome awaiting release."""
    assembly_dataset = (
        metadata_session.query(Dataset)
        .filter(
            Dataset.status == DatasetStatus.RELEASED,
            Dataset.name == "assembly",
        )
        .first()
    )
    assert assembly_dataset is not None
    assert any(
        genome_dataset.release_id is not None
        for genome_dataset in assembly_dataset.genome_datasets
    )

    unreleased_genome = (
        metadata_session.query(Genome)
        .filter(
            Genome.genome_releases.any(
                GenomeRelease.ensembl_release.has(
                    EnsemblRelease.status != ReleaseStatus.RELEASED
                )
            )
        )
        .filter(
            ~Genome.genome_releases.any(
                GenomeRelease.ensembl_release.has(
                    EnsemblRelease.status == ReleaseStatus.RELEASED
                )
            )
        )
        .filter(
            ~Genome.genome_datasets.any(
                GenomeDataset.dataset_id == assembly_dataset.dataset_id
            )
        )
        .first()
    )
    assert unreleased_genome is not None

    metadata_session.add(
        GenomeDataset(
            dataset_id=assembly_dataset.dataset_id,
            genome_id=unreleased_genome.genome_id,
            is_current=1,
        )
    )
    metadata_session.flush()

    check_released_datasets_have_released_releases(metadata_session)


def test_released_dataset_without_any_released_attachment_fails(metadata_session):
    """Released datasets still need at least one release-scoped attachment."""
    dataset = (
        metadata_session.query(Dataset)
        .filter(Dataset.status == DatasetStatus.RELEASED)
        .first()
    )
    assert dataset is not None

    for genome_dataset in dataset.genome_datasets:
        genome_dataset.release_id = None
    metadata_session.flush()

    with pytest.raises(AssertionError, match="Released datasets without a release"):
        check_released_datasets_have_released_releases(metadata_session)
