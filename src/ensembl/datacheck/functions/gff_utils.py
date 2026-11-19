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
gff_utils.py

Shared helpers for GFF parsing and feature type counting.
"""

import tempfile
from collections import Counter
from pathlib import Path

import gffutils


def gff_reader(gff_file_path: str | Path) -> gffutils.FeatureDB:
    """
    Provide a gffutils FeatureDB database opened on a GFF file path.

    Args:
        gff_file_path (str or pathlib.Path): The path to the GFF file.

    Raises:
        Exception: Propagates import/open failures from gffutils.
    """

    with tempfile.NamedTemporaryFile() as temporary_file:
        return gffutils.create_db(gff_file_path, temporary_file.name)


def get_gff_feature_type_counts(gff_file_path: str | Path):
    gff_db = gff_reader(gff_file_path)
    return Counter(
        {
            feature_type: gff_db.count_features_of_type(feature_type)
            for feature_type in gff_db.featuretypes()
        }
    )
