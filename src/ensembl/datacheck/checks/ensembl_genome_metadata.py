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
3. Organism-Assembly link check (Error): Ensures that each organism is linked to an assembly.
4. Assembly-Genome link check (Error): Ensures that each assembly is linked to a genome.
5. Genome production name presence check (Error): Ensures that each genome has a production name.
6. GenomeRelease-EnsemblRelease link check (Error): Ensures that each genome release is linked to an Ensembl release.

These checks are run to verify the integrity and completeness of the metadata in the new Ensembl metadata database.
"""

import pytest
from ensembl.production.metadata.api.models import Organism, Assembly, Genome, GenomeRelease, EnsemblRelease
from ensembl.datacheck.functions.db_checks import (
    check_database_connection, check_tables_not_empty, check_foreign_key_link, check_attribute_presence
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
    assert check_database_connection(db_session), "Database session is not available"

@pytest.mark.usefixtures("db_session")
def check_tables(db_session):
    """
    Check that all tables in the database are not empty.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any table is empty.
    """
    result, message = check_tables_not_empty(db_session)
    assert result, message

@pytest.mark.usefixtures("db_session")
def check_organism_assembly_link(db_session):
    """
    Check that each organism is linked to at least one assembly.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any organism is not linked to an assembly.
    """
    result, message = check_foreign_key_link(db_session, Organism, Assembly, 'organism_id', 'organism_id')
    assert result, message

@pytest.mark.usefixtures("db_session")
def check_assembly_genome_link(db_session):
    """
    Check that each assembly is linked to at least one genome.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any assembly is not linked to a genome.
    """
    result, message = check_foreign_key_link(db_session, Assembly, Genome, 'assembly_id', 'assembly_id')
    assert result, message

@pytest.mark.usefixtures("db_session")
def check_genome_production_name(db_session):
    """
    Check that each genome has a production name.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any genome does not have a production name.
    """
    result, message = check_attribute_presence(db_session, Genome, 'production_name')
    assert result, message

@pytest.mark.usefixtures("db_session")
def test_genome_release_has_ensembl_release(db_session):
    """
    Check that each genome release is linked to an Ensembl release.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Raises:
        AssertionError: If any genome release is not linked to an Ensembl release.
    """
    result, message = check_foreign_key_link(db_session, GenomeRelease, EnsemblRelease, 'release_id', 'release_id')
    assert result, message
