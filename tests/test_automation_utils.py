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

"""Integration tests for automation utility functions."""

import re
import sqlite3
from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation.utils import get_ftp_paths

pytestmark = pytest.mark.filterwarnings(
    "ignore:Could not instantiate type <class 'sqlalchemy.sql.sqltypes.INTEGER'> with reflected arguments \\['1'\\]; using no arguments\\.:sqlalchemy.exc.SAWarning"
)


def _metadata_db_path():
    """Return the metadata SQLite fixture path."""
    return Path(__file__).parent / "database" / "ensembl_genome_metadata.db"

def _taxonomy_db_path():
    """Return the taxonomy SQLite fixture path."""
    return Path(__file__).parent / "database" / "ncbi_taxonomy.db"


def _metadata_db_url():
    """Build SQLAlchemy connection URL for the metadata SQLite fixture."""
    return f"sqlite:///{_metadata_db_path().resolve()}"

def _taxonomy_db_url():
    """Build SQLAlchemy connection URL for the metadata SQLite fixture."""
    return f"sqlite:///{_taxonomy_db_path().resolve()}"


def _get_genome_uuid():
    """Find a genome UUID with metadata required by get_public_path templates."""
    query = """
        SELECT distinct g.genome_uuid
        FROM genome AS g
        JOIN genome_dataset AS gd ON gd.genome_id = g.genome_id
        JOIN dataset AS d ON d.dataset_id = gd.dataset_id
        JOIN dataset_type AS dt ON dt.dataset_type_id = d.dataset_type_id
        WHERE dt.name = 'genebuild'
    """
    with sqlite3.connect(str(_metadata_db_path())) as conn:
        row = conn.execute(query).fetchone()
    assert row is not None, "No suitable genome UUID found in metadata test fixture"
    return row[0]


def test_get_ftp_paths_returns_paths_from_metadata_fixture():
    """Verify get_ftp_paths returns dataset/path records matching path_templates."""
    genome_uuid = _get_genome_uuid()
    ftp_paths = get_ftp_paths(
        metadata_uri=_metadata_db_url(),
        taxonomy_uri=_taxonomy_db_url(),
        genome_uuid=genome_uuid,
    )

    assert isinstance(ftp_paths, list)
    assert ftp_paths
    assert all(set(item.keys()) == {"dataset_type", "path"} for item in ftp_paths)
    assert all(isinstance(item["path"], str) and item["path"] for item in ftp_paths)

    path_by_dataset_type = {item["dataset_type"]: item["path"] for item in ftp_paths}
    assert len(path_by_dataset_type) == len(ftp_paths)

    dataset_types = {item["dataset_type"] for item in ftp_paths}
    assert dataset_types.issubset(
        {"genebuild", "assembly", "homologies", "regulation", "variation"}
    )
    assert "genebuild" in dataset_types

    if "assembly" in path_by_dataset_type:
        assert re.match(r"^[^/]+/[^/]+/genome$", path_by_dataset_type["assembly"])
    if "genebuild" in path_by_dataset_type:
        assert re.match(r"^[^/]+/[^/]+/[^/]+/geneset/\d{4}_\d{2}$", path_by_dataset_type["genebuild"])
    if "homologies" in path_by_dataset_type:
        assert re.match(r"^[^/]+/[^/]+/[^/]+/homology/\d{4}_\d{2}$", path_by_dataset_type["homologies"])
    if "regulation" in path_by_dataset_type:
        assert re.match(r"^[^/]+/[^/]+/[^/]+/regulation$", path_by_dataset_type["regulation"])
    if "variation" in path_by_dataset_type:
        assert re.match(r"^[^/]+/[^/]+/[^/]+/variation/\d{4}_\d{2}$", path_by_dataset_type["variation"])

    common_path_candidates = []
    if "genebuild" in path_by_dataset_type:
        common_path_candidates.append(path_by_dataset_type["genebuild"].split("/geneset/")[0])
    if "homologies" in path_by_dataset_type:
        common_path_candidates.append(path_by_dataset_type["homologies"].split("/homology/")[0])
    if "regulation" in path_by_dataset_type:
        common_path_candidates.append(path_by_dataset_type["regulation"].removesuffix("/regulation"))
    if "variation" in path_by_dataset_type:
        common_path_candidates.append(path_by_dataset_type["variation"].split("/variation/")[0])

    if common_path_candidates:
        assert len(set(common_path_candidates)) == 1
        common_path = common_path_candidates[0]
        if "assembly" in path_by_dataset_type:
            base_path = path_by_dataset_type["assembly"].removesuffix("/genome")
            assert common_path.startswith(base_path + "/")
