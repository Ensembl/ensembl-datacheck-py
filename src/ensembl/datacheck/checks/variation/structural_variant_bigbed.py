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
variation/structural_variant_bigbed.py

This module performs checks specific to structural variant BigBed files.

The BigBed layout follows structural_variant_bedfields.json in the variation
pipelines: chromosome, start, end, then the extra fields
id, variety, reference, alts, group, severity, extent.

Checks performed:
1. check_field_layout: Entries have the expected extra fields and numeric types.
2. check_coordinates_and_extent: Coordinates and extent are consistent.
3. check_variant_group_greater_than_10: Every entry has a variant group greater than 10.

The checks run on the BigBed entries of variants sampled from the source VCF
(see source_variants_subsample), so --source-file is required and
--subsample-size controls how many entries are checked (0 checks all of them).
"""

import re
import warnings

import pytest

from ensembl.datacheck.functions.bb_bw_utils import bb_bw_reader
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning

pytestmark = [
                pytest.mark.dataset_type("structural_variants"),
                pytest.mark.file_extension("bb"),
                pytest.mark.file_extension("bigbed")
            ]

EXTRA_FIELDS = ["id", "variety", "reference", "alts", "group", "severity", "extent"]
MAX_REPORTED_FAILURES = 10
# Insertions and breakpoints are placed on a single point (end == start)
POINT_VARIETY_SUFFIXES = ("insertion", "breakpoint")
# A stricter check for integer fields: optional minus sign followed by one or more digits.
INTEGER_FIELD = re.compile(r"-?[0-9]+")


@pytest.fixture(scope="module")
def target_entries_subsample(target_file, source_file, request: pytest.FixtureRequest) -> list[tuple[str, int, int, list[str]]]:
    """
    BigBed entries for the variants sampled from the source VCF.

    For each sampled source variant, only the BigBed region around its position is
    read, and the entry with the same ID is kept. Variants without a matching entry
    are left to bigbed.py's check_variant_exist_from_source.

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.
        source_file (pathlib.Path or None): Path to source VCF file.
        request (pytest.FixtureRequest): Used to load source_variants_subsample
            only once source_file is known to be set.

    Returns:
        list: (chrom, start, end, extra fields) per matched entry.

    Raises:
        AssertionError: If the target file is missing or not a readable BigBed.
    """
    if source_file is None:
        pytest.skip("--source-file is required to sample structural variant BigBed entries.")

    assert file_exists(target_file), "The target file does not exist."
    source_variants_subsample = request.getfixturevalue("source_variants_subsample")

    reader = bb_bw_reader(target_file)
    assert reader is not None, "Could not open target file as BigBed."
    entries = []
    try:
        assert reader.isBigBed(), "The target file is not recognised as BigBed."
        chroms = reader.chroms()
        for variant_id, variant in source_variants_subsample.items():
            chrom = variant["chrom"]
            if chrom not in chroms:
                continue
            start = variant["pos"] - 1
            for entry_start, entry_end, rest in reader.entries(chrom, start, start + 2) or []:
                fields = rest.split("\t")
                if fields[0] == variant_id:
                    entries.append((chrom, entry_start, entry_end, fields))
    finally:
        reader.close()

    if not entries:
        warnings.warn(
            EnsemblDatacheckWarning(
                "No BigBed entries matched the sampled source variants; no entries were checked. "
                "Consider increasing max_random_regions or --subsample-size.",
                "structural_variant_bigbed",
                "target_entries_subsample",
            )
        )
    return entries


def _assert_no_failures(failures: list[str], message: str) -> None:
    assert not failures, (
        f"{message} Showing up to {MAX_REPORTED_FAILURES}: "
        + "; ".join(failures[:MAX_REPORTED_FAILURES])
    )


def check_field_layout(target_entries_subsample):
    """
    Check that entries have the structural variant extra fields.

    Each entry must have the 7 fields after chromosome/start/end, and group
    and extent must be integers.

    Args:
        target_entries_subsample (list): BigBed entries of the sampled source variants.

    Raises:
        AssertionError: If any entry has the wrong number of fields or non-integer group/extent.
    """
    failures = []
    for chrom, start, _, fields in target_entries_subsample:
        label = f"{chrom}:{start}"
        if len(fields) != len(EXTRA_FIELDS):
            failures.append(f"{label} has {len(fields)} fields, expected {len(EXTRA_FIELDS)}")
            continue
        named = dict(zip(EXTRA_FIELDS, fields))
        for numeric in ("group", "extent"):
            if not INTEGER_FIELD.fullmatch(named[numeric]):
                failures.append(f"{label} {numeric}='{named[numeric]}' is not an integer")

    _assert_no_failures(failures, f"{len(failures)} entries have an invalid field layout.")


def check_coordinates_and_extent(target_entries_subsample):
    """
    Check that entry coordinates and extent are consistent.

    The check asserts:
    - end >= start, and end > start unless the variety is an insertion or breakpoint
    - extent > 0
    - extent == end - start unless the variety is an insertion or breakpoint

    Args:
        target_entries_subsample (list): BigBed entries of the sampled source variants.

    Raises:
        AssertionError: If any entry is inconsistent.
    """
    failures = []
    for chrom, start, end, fields in target_entries_subsample:
        if len(fields) != len(EXTRA_FIELDS):
            continue  # reported by check_field_layout
        named = dict(zip(EXTRA_FIELDS, fields))
        label = f"{named['id']} ({chrom}:{start}-{end})"
        is_point = named["variety"].endswith(POINT_VARIETY_SUFFIXES)

        try:
            extent = int(named["extent"])
        except ValueError:
            continue  # reported by check_field_layout

        if extent <= 0:
            failures.append(f"{label} has extent {extent}")
        if end < start or (not is_point and end == start):
            failures.append(f"{label} has end not after start")
        elif not is_point and extent != end - start:
            failures.append(f"{label} extent {extent} != end - start {end - start}")

    _assert_no_failures(
        failures, f"{len(failures)} entries have inconsistent coordinates or extent."
    )


def check_variant_group_greater_than_10(target_entries_subsample):
    """
    Check that every entry has a variant group greater than 10.

    Structural variant groups start at 11; lower groups are used for short variants.

    Args:
        target_entries_subsample (list): BigBed entries of the sampled source variants.

    Raises:
        AssertionError: If any entry has a group of 10 or less.
    """
    failures = []
    for chrom, start, _, fields in target_entries_subsample:
        if len(fields) != len(EXTRA_FIELDS):
            continue  # reported by check_field_layout
        named = dict(zip(EXTRA_FIELDS, fields))
        try:
            group = int(named["group"])
        except ValueError:
            continue  # reported by check_field_layout
        if group <= 10:
            failures.append(f"{named['id']} ({chrom}:{start}) group={group}")

    _assert_no_failures(failures, f"{len(failures)} entries have a group of 10 or less.")
