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
import warnings

from sqlalchemy import inspect, text
from sqlalchemy.orm import class_mapper

from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning


def database_connection_check(db_session):
    """
    Check if the database connection is established.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Returns:
        bool: True if the database connection is established, False otherwise.
    """
    return db_session is not None


def tables_not_empty_check(db_session):
    """
    Check that all tables in the database are not empty.
    """
    inspector = inspect(db_session.get_bind())
    for table_name in inspector.get_table_names():
        count = db_session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        if count == 0:
            return False, f"Table {table_name} is empty"
    return True, ""


def find_orphans(
    db_session,
    source_model,
    join_target,
    filter_column,
    uuid_field,
    entity_name,
    warn=False,
):
    """
    Generic function to check for orphaned records.

    Args:
        db_session: SQLAlchemy session
        source_model: The model to query (e.g., Dataset, Organism)
        join_target: The relationship or model to join (e.g., Dataset.genome_datasets, Genome)
        filter_column: The column to check for None (e.g., GenomeDataset.dataset_id)
        uuid_field: The UUID field name on source_model (e.g., 'dataset_uuid')
        entity_name: Human-readable name for error messages
        warn: Return warnings rather than exceptions
    """
    orphans = (
        db_session.query(source_model)
        .outerjoin(join_target)
        .filter(filter_column == None)
        .all()
    )

    if orphans:
        ids = [getattr(obj, uuid_field) for obj in orphans]
        if warn:
            # self, message, file_name, function_name)
            warnings.warn(
                EnsemblDatacheckWarning(
                    f"Found {len(orphans)} orphaned {entity_name}: {ids}",
                    "ensembl_genome_metadata",
                    "check_orphan",
                )
            )
        else:
            assert False, f"Found {len(orphans)} orphaned {entity_name}: {ids}"


def attribute_presence_check(db_session, Model, attribute):
    """
    Check that each entry in Model has the specified attribute.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.
        Model (sqlalchemy.ext.declarative.api.Base): The model class.
        attribute (str): The attribute name to be checked.

    Returns:
        tuple: A tuple containing a boolean indicating the result and a message.
               The boolean is True if all entries have the attribute, False otherwise.
               The message contains the details of the entry without the attribute if any.
    """
    entries = db_session.query(Model).all()
    for entry in entries:
        if not getattr(entry, attribute):
            return (
                False,
                f"Entry {getattr(entry, class_mapper(Model).primary_key[0].name)} in {Model.__name__} does not have a valid {attribute}",
            )
    return True, ""
