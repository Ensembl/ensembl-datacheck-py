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
3. check_group_greater_than_10: Every entry has a variant group greater than 10.
"""

import pytest

from ensembl.datacheck.functions.bb_bw_utils import bb_bw_reader
from ensembl.datacheck.functions.file_checks import file_exists

pytestmark = pytest.mark.dataset_type("structural_variant")

EXTRA_FIELDS = ["id", "variety", "reference", "alts", "group", "severity", "extent"]
MAX_ENTRIES_PER_CHROM = 10000
MAX_REPORTED_FAILURES = 10
# Insertions and breakpoints are placed on a single point (end == start)
POINT_VARIETY_SUFFIXES = ("insertion", "breakpoint")


def _iter_entries(target_file):
    """Yield (chrom, start, end, fields) for up to MAX_ENTRIES_PER_CHROM entries per chromosome."""
    assert file_exists(target_file), "The target file does not exist."

    reader = bb_bw_reader(target_file)
    assert reader is not None, "Could not open target file as BigBed."
    try:
        assert reader.isBigBed(), "The target file is not recognised as BigBed."
        for chrom, length in reader.chroms().items():
            entries = reader.entries(chrom, 0, length) or []
            for start, end, rest in entries[:MAX_ENTRIES_PER_CHROM]:
                yield chrom, start, end, rest.split("\t")
    finally:
        reader.close()


def _assert_no_failures(failures: list[str], message: str) -> None:
    assert not failures, (
        f"{message} Showing up to {MAX_REPORTED_FAILURES}: "
        + "; ".join(failures[:MAX_REPORTED_FAILURES])
    )


def check_field_layout(target_file):
    """
    Check that entries have the structural variant extra fields.

    Each entry must have the 7 fields after chromosome/start/end, and group
    and extent must be integers.

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.

    Raises:
        AssertionError: If the file is missing/unreadable or any entry has the
            wrong number of fields or non-integer group/extent.
    """
    failures = []
    for chrom, start, _, fields in _iter_entries(target_file):
        label = f"{chrom}:{start}"
        if len(fields) != len(EXTRA_FIELDS):
            failures.append(f"{label} has {len(fields)} fields, expected {len(EXTRA_FIELDS)}")
            continue
        named = dict(zip(EXTRA_FIELDS, fields))
        for numeric in ("group", "extent"):
            if not named[numeric].lstrip("-").isdigit():
                failures.append(f"{label} {numeric}='{named[numeric]}' is not an integer")

    _assert_no_failures(failures, f"{len(failures)} entries have an invalid field layout.")


def check_coordinates_and_extent(target_file):
    """
    Check that entry coordinates and extent are consistent.

    The check asserts:
    - end >= start, and end > start unless the variety is an insertion or breakpoint
    - extent > 0
    - extent == end - start unless the variety is an insertion or breakpoint

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.

    Raises:
        AssertionError: If the file is missing/unreadable or any entry is inconsistent.
    """
    failures = []
    for chrom, start, end, fields in _iter_entries(target_file):
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


def check_variant_group_greater_than_10(target_file):
    """
    Check that every entry has a variant group greater than 10.

    Structural variant groups start at 11; lower groups are used for short variants.

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.

    Raises:
        AssertionError: If the file is missing/unreadable or any entry has a
            group of 10 or less.
    """
    failures = []
    for chrom, start, _, fields in _iter_entries(target_file):
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
