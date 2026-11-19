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

"""Regulation-specific BigBed checks.

Checks performed:
1. check_exist: Imported generic BigBed existence check.
2. check_validity: Imported generic BigBed validity check.
3. check_feature_types_match: Compares feature-type names and counts in a
   regulatory BigBed with its source GFF.
"""

from collections import Counter
from pathlib import Path

import pytest

from ensembl.datacheck.checks.bigbed import check_exist, check_validity
from ensembl.datacheck.functions.bb_bw_utils import bb_bw_reader
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.gff_utils import get_gff_feature_type_counts

pytestmark = [
    pytest.mark.dataset_type("regulation_tracks"),
    pytest.mark.file_extension("bb"),
    pytest.mark.file_extension("bigbed"),
]


def _get_target_feature_type_counts(target_file_path: str | Path) -> Counter:
    """Return counts of normalised feature types in a regulatory BigBed.

    The regulatory feature type is read from the penultimate tab-delimited
    field of each BigBed entry. Spaces are converted to underscores to match
    the corresponding GFF feature-type convention.

    Args:
        target_file_path: Path to the target BigBed file.

    Returns:
        Counter: Mapping of normalised feature types to their entry counts.

    Raises:
        AssertionError: If the target BigBed cannot be opened or is invalid.
    """
    target_reader = bb_bw_reader(target_file_path)
    assert target_reader is not None, "Could not open the target file as BigBed."
    assert target_reader.isBigBed(), "The target file is not recognised as BigBed."

    target_feature_type_counts = Counter()
    for chromosome, chromosome_length in target_reader.chroms().items():
        entries = target_reader.entries(chromosome, 0, chromosome_length)
        for entry in entries or []:
            feature_type = entry[2].split("\t")[-2].replace(" ", "_")
            target_feature_type_counts[feature_type] += 1

    return target_feature_type_counts


def check_feature_types_match(target_file, source_file):
    """Check that feature-type names and counts match the source GFF.

    BigBed feature types are normalised by replacing spaces with underscores
    before comparison. GFF feature-type counts are obtained with
    :func:`get_gff_feature_type_counts`.

    Args:
        target_file (pathlib.Path or None): Path to the regulatory BigBed file.
        source_file (pathlib.Path or None): Path to the regulatory GFF file.

    Raises:
        AssertionError: If either input is missing or the feature types or
            their counts differ.
    """
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."

    target_reader = None
    try:
        target_feature_type_counts = _get_target_feature_type_counts(target_file)
        source_feature_type_counts = get_gff_feature_type_counts(source_file)

        assert target_feature_type_counts == source_feature_type_counts, (
            "BigBed and GFF feature types do not match. "
            f"BigBed counts: {dict(sorted(target_feature_type_counts.items()))}; "
            f"GFF counts: {dict(sorted(source_feature_type_counts.items()))}"
        )
    finally:
        if target_reader is not None:
            target_reader.close()
