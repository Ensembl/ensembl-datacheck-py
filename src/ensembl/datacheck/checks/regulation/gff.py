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

"""Regulation-specific GFF checks.

Checks performed:
1. check_exist: Imported generic GFF existence check.
2. check_has_gff_gz_extension: Imported generic GFF extension check.
3. check_is_bgzf_gff_file: Imported generic BGZF compression check.
4. check_has_valid_index_file: Imported generic GFF index check.
5. check_validity: Imported generic GFF structural validation.
6. check_header: Confirms the Ensembl Regulation metadata headers are present.
7. check_feature_types: Confirms only supported regulatory feature types occur.
"""

from gzip import open as gzip_open
from pathlib import Path

import pytest

from ensembl.datacheck.checks.gff import *
from ensembl.datacheck.checks.regulation.conftest import SUPPORTED_FEATURE_TYPES
from ensembl.datacheck.functions.gff_utils import get_gff_feature_type_counts

pytestmark = [
    pytest.mark.dataset_type("regulation_tracks"),
    pytest.mark.file_extension("gff.gz"),
]


def check_header(target_file: Path | None) -> None:
    """Check that the regulatory GFF has Ensembl Regulation metadata headers.

    Args:
        target_file: Path to the regulatory GFF file.

    Raises:
        AssertionError: If either required metadata header is absent.
    """
    assert target_file is not None, "A target regulatory GFF file is required."

    headers = []
    with gzip_open(target_file, "rt", encoding="utf-8") as gff_file:
        for line in gff_file:
            if not line.startswith("#"):
                break
            headers.append(line.rstrip("\n"))

    assert any(
        header.startswith("# Ensembl Regulation version ") for header in headers
    ), "Ensembl Regulation version header is missing from the GFF file."
    assert any(header.startswith("# Gene annotation ") for header in headers), (
        "Gene annotation header is missing from the GFF file."
    )


def check_feature_types(target_file: Path | None) -> None:
    """Check that the GFF contains only supported regulatory feature types.

    Args:
        target_file: Path to the regulatory GFF file.

    Raises:
        AssertionError: If no feature type is present, a feature type is
            unexpected, or an observed feature type has no records.
    """
    assert target_file is not None, "A target regulatory GFF file is required."

    feature_type_counts = get_gff_feature_type_counts(target_file)
    assert feature_type_counts, "Regulatory GFF contains no feature types."
    assert set(feature_type_counts) <= SUPPORTED_FEATURE_TYPES, (
        "Unexpected regulatory GFF feature types. "
        f"Allowed: {sorted(SUPPORTED_FEATURE_TYPES)}; "
        f"observed: {sorted(feature_type_counts)}"
    )
    assert all(
        count > 0 for count in feature_type_counts.values()
    ), (
        f"Regulatory GFF contains an empty feature type: "
        f"{dict(sorted(feature_type_counts.items()))}"
    )
