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

from sqlalchemy import inspect
from sqlalchemy.orm import class_mapper

def check_database_connection(db_session):
    """
    Check if the database connection is established.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Returns:
        bool: True if the database connection is established, False otherwise.
    """
    return db_session is not None

def check_tables_not_empty(db_session):
    """
    Check that all tables in the database are not empty.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.

    Returns:
        tuple: A tuple containing a boolean indicating the result and a message.
               The boolean is True if all tables are not empty, False otherwise.
               The message contains the name of the empty table if any.
    """
    inspector = inspect(db_session.get_bind())
    for table_name in inspector.get_table_names():
        count = db_session.execute(f"SELECT COUNT(*) FROM {table_name}").scalar()
        if count == 0:
            return False, f"Table {table_name} is empty"
    return True, ""

def check_foreign_key_link(db_session, SourceModel, TargetModel, source_key, target_key):
    """
    Check that all entries in SourceModel are linked to at least one entry in TargetModel.

    Args:
        db_session (sqlalchemy.orm.Session): The database session.
        SourceModel (sqlalchemy.ext.declarative.api.Base): The source model class.
        TargetModel (sqlalchemy.ext.declarative.api.Base): The target model class.
        source_key (str): The attribute name in the source model to be checked.
        target_key (str): The attribute name in the target model to be checked.

    Returns:
        tuple: A tuple containing a boolean indicating the result and a message.
               The boolean is True if all entries are linked, False otherwise.
               The message contains the details of the unlinked entry if any.
    """
    source_entries = db_session.query(SourceModel).all()
    for entry in source_entries:
        if db_session.query(TargetModel).filter_by(**{target_key: getattr(entry, source_key)}).count() == 0:
            return False, f"Entry {getattr(entry, source_key)} in {SourceModel.__name__} is not linked to any entry in {TargetModel.__name__}"
    return True, ""

def check_attribute_presence(db_session, Model, attribute):
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
            return False, f"Entry {getattr(entry, class_mapper(Model).primary_key[0].name)} in {Model.__name__} does not have a valid {attribute}"
    return True, ""
