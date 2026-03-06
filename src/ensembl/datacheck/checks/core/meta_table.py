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
Check that all required metakeys from the metadata database are present in the core database and have non-empty values.
Checks performed:
    - Fetch required attributes from the metadata database (other_db_session).
    - Fetch core database meta_key and meta_value for required attributes (db_session).
    - Check that all required metakeys exist in the core database.
    - Check that all required metakeys have non-empty values in the core database.
"""

import pytest
from sqlalchemy import text
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from ensembl.production.metadata.api.models.dataset import Attribute


@pytest.mark.usefixtures("db_session", "other_db_session")
class CheckCoreDBMetaKeys:
    """
    Check that all required metakeys from the metadata database are present in the core database and have non-empty values.
    Checks for:
        - Fetch required attributes from the metadata database (other_db_session).
        - Fetch core database meta_key and meta_value for required attributes (db_session).
        - Check that all required metakeys exist in the core database.
        - Check that all required metakeys have non-empty values in the core database.
    """

    @pytest.fixture(autouse=True)
    def setup(self, db_session, other_db_session):
        """Fetch required attributes and core DB values once per class."""
        self.db_session = db_session
        self.other_db_session = other_db_session

        # 1️⃣ Fetch required attributes from metadata DB
        self.required_attributes = [
            attr.name
            for attr in other_db_session.query(Attribute).filter(
                Attribute.required == 1
            ).all()
        ]

        # 2️⃣ Fetch core DB meta_key and meta_value for required attributes
        if self.required_attributes:
            keys_str = ",".join(f"'{attr}'" for attr in self.required_attributes)
            query = text(f"""
                SELECT meta_key, meta_value
                FROM meta
                WHERE meta_key IN ({keys_str})
            """)
            self.core_metakeys_and_values = db_session.execute(query).fetchall()
            self.core_metakeys = [row[0] for row in self.core_metakeys_and_values]
        else:
            self.core_metakeys_and_values = []
            self.core_metakeys = []

    def check_required_metakeys_exist_in_core_db(self):
        """Check that all required metakeys exist in the core DB."""
        missing_metakeys = set(self.required_attributes) - set(self.core_metakeys)
        assert not missing_metakeys, f"Missing required metakeys in core DB: {', '.join(missing_metakeys)}"

    def check_required_metakeys_have_values(self):
        """Check that all required metakeys have non-empty values."""
        empty_value_metakeys = [row[0] for row in self.core_metakeys_and_values if not row[1]]
        found_str = ", ".join(f"{row[0]}: {row[1]}" for row in self.core_metakeys_and_values)
        assert not empty_value_metakeys, (
            f"Required metakeys with empty values in core DB: {', '.join(empty_value_metakeys)}. "
            f"Found metakeys and values: {found_str}"
        )
