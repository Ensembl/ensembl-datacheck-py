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
This module performs checks on the Ensembl genome metadata database per release.

Checks performed:
1. check_database: Ensures the database session is available.
2. check_genomes_in_release_are_current: Ensures all genomes in the release have
   genome_release.is_current set to true.
3. check_genome_datasets_in_release_are_current: Ensures all Released datasets
   attached to the release have genome_dataset.is_current set to true.
4. check_genomes_in_release_have_required_attributes: Ensures every genome in
   the release has all required attributes with non-empty values.
5. check_suppressed_genomes_in_release_are_not_current: Ensures suppressed
   genomes in the release do not have genome_release.is_current set to true.

Example:
    ensembl-datacheck --test metadata_per_release \
        --database mysql+pymysql://user:password@host/ensembl_genome_metadata \
        --release_name 1 \
        --no-cache-results
"""
import warnings

import pytest
from sqlalchemy import or_, func, String, Text
from ensembl.production.metadata.api.models import Dataset, GenomeDataset, DatasetStatus, EnsemblRelease, ReleaseStatus, \
    Organism, Genome, OrganismGroup, OrganismGroupMember, Assembly, AssemblySequence, DatasetSource, GenomeRelease, \
    DatasetType, GenomeGroup, GenomeGroupMember, Attribute, DatasetAttribute
from ensembl.production.metadata.api.models.base import Base
from ensembl.datacheck.functions.db_checks import (
    database_connection_check,
    find_orphans
)
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning




class CheckMetadataPerRelease:
    """
    Check that the beta resources are loaded in multiple collections of Thoas MongoDB.
    """

    @pytest.fixture(autouse=True)
    def setup(self,  db_session, request):
        """
        Prepare commonly used attributes for each test invocation.
        """
        self.release_name = request.config.getoption("--release_name")
        self.db_session = db_session

    
    def check_database(self):
        """
        Check if the database connection is established.

        Args:
            db_session (sqlalchemy.orm.Session): The database session.

        Raises:
            AssertionError: If the database session is not available.
        """
        assert database_connection_check(self.db_session), "Database session is not available"


    def check_genomes_in_release_are_current(self):
        genomes_released_count = (
            self.db_session.query(func.count(func.distinct(Genome.genome_id)))
            .join(GenomeRelease, GenomeRelease.genome_id == Genome.genome_id)
            .join(EnsemblRelease, EnsemblRelease.release_id == GenomeRelease.release_id)
            .filter(EnsemblRelease.status == ReleaseStatus.RELEASED)
            .filter(EnsemblRelease.name == self.release_name)
            .scalar()
        )

        assert genomes_released_count > 0, (
            f"No released genomes found for release {self.release_name}. "
            "Assign all genomes to a release first and set the EnsemblRelease.status to Released."
        )

        genomes_released_is_current_count = (
            self.db_session.query(func.count(func.distinct(Genome.genome_id)))
            .join(GenomeRelease, GenomeRelease.genome_id == Genome.genome_id)
            .join(EnsemblRelease, EnsemblRelease.release_id == GenomeRelease.release_id)
            .filter(EnsemblRelease.status == ReleaseStatus.RELEASED)
            .filter(EnsemblRelease.name == self.release_name)
            .filter(GenomeRelease.is_current == 1)
            .scalar()
        )

        difference = genomes_released_count - genomes_released_is_current_count
        assert difference == 0, (
            f"Found {difference} released genomes in release {self.release_name} "
            "where genome_release.is_current is not true "
            f"(released count={genomes_released_count}, "
            f"current count={genomes_released_is_current_count})"
        )

    def check_genome_datasets_in_release_are_current(self):
        genome_datasets_released_count = (
            self.db_session.query(func.count())
            .select_from(Genome)
            .join(GenomeDataset, GenomeDataset.genome_id == Genome.genome_id)
            .join(Dataset, Dataset.dataset_id == GenomeDataset.dataset_id)
            .join(EnsemblRelease, EnsemblRelease.release_id == GenomeDataset.release_id)
            .filter(EnsemblRelease.name == self.release_name)
            .filter(Dataset.status == DatasetStatus.RELEASED)
            .scalar()
        )

        assert genome_datasets_released_count > 0, (
            f"No released genome datasets found for release {self.release_name}. "
            "Attach all datasets to a release first."
        )

        genome_datasets_released_is_current_count = (
            self.db_session.query(func.count())
            .select_from(Genome)
            .join(GenomeDataset, GenomeDataset.genome_id == Genome.genome_id)
            .join(Dataset, Dataset.dataset_id == GenomeDataset.dataset_id)
            .join(EnsemblRelease, EnsemblRelease.release_id == GenomeDataset.release_id)
            .filter(EnsemblRelease.name == self.release_name)
            .filter(Dataset.status == DatasetStatus.RELEASED)
            .filter(GenomeDataset.is_current == 1)
            .scalar()
        )

        difference = genome_datasets_released_count - genome_datasets_released_is_current_count
        assert difference == 0, (
            f"Found {difference} released genome datasets in release {self.release_name} "
            "where genome_dataset.is_current is not true "
            f"(released count={genome_datasets_released_count}, "
            f"current count={genome_datasets_released_is_current_count})"
        )

    def check_genomes_in_release_have_required_attributes(self):
        required_attribute_names = {
            name
            for (name,) in (
                self.db_session.query(Attribute.name)
                .filter(Attribute.required == 1)
                .all()
            )
        }

        if not required_attribute_names:
            return

        genome_uuids = {
            genome_uuid
            for (genome_uuid,) in (
                self.db_session.query(Genome.genome_uuid)
                .join(GenomeDataset, GenomeDataset.genome_id == Genome.genome_id)
                .join(EnsemblRelease, EnsemblRelease.release_id == GenomeDataset.release_id)
                .filter(EnsemblRelease.name == self.release_name)
                .distinct()
                .all()
            )
        }

        genome_attribute_names = {genome_uuid: set() for genome_uuid in genome_uuids}
        attribute_rows = (
            self.db_session.query(
                Genome.genome_uuid,
                Attribute.name,
                DatasetAttribute.value
            )
            .join(GenomeDataset, GenomeDataset.genome_id == Genome.genome_id)
            .join(Dataset, Dataset.dataset_id == GenomeDataset.dataset_id)
            .join(DatasetAttribute, DatasetAttribute.dataset_id == Dataset.dataset_id)
            .join(Attribute, Attribute.attribute_id == DatasetAttribute.attribute_id)
            .join(EnsemblRelease, EnsemblRelease.release_id == GenomeDataset.release_id)
            .filter(EnsemblRelease.name == self.release_name)
            .filter(Attribute.required == 1)
            .all()
        )

        for genome_uuid, attribute_name, attribute_value in attribute_rows:
            if attribute_value is not None and str(attribute_value).strip():
                genome_attribute_names.setdefault(genome_uuid, set()).add(attribute_name)

        genomes_missing_attributes = {
            genome_uuid: sorted(required_attribute_names - attribute_names)
            for genome_uuid, attribute_names in genome_attribute_names.items()
            if required_attribute_names - attribute_names
        }

        assert not genomes_missing_attributes, (
            f"Found {len(genomes_missing_attributes)} genomes in release {self.release_name} "
            "missing required attributes with values: "
            f"{genomes_missing_attributes}"
        )

    def check_suppressed_genomes_in_release_are_not_current(self):
        current_suppressed_genomes = (
            self.db_session.query(
                Genome.genome_uuid,
                GenomeRelease.is_current,
                EnsemblRelease.name
            )
            .join(GenomeRelease, GenomeRelease.genome_id == Genome.genome_id)
            .join(EnsemblRelease, EnsemblRelease.release_id == GenomeRelease.release_id)
            .filter(Genome.suppressed == 1)
            .filter(EnsemblRelease.name == self.release_name)
            .filter(GenomeRelease.is_current == 1)
            .all()
        )

        assert not current_suppressed_genomes, (
            f"Found {len(current_suppressed_genomes)} suppressed genomes in release "
            f"{self.release_name} where genome_release.is_current is true: "
            f"{[(row.genome_uuid, row.name) for row in current_suppressed_genomes]}"
        )
