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
variation/structural_variant_vcf.py

This module performs checks specific to structural variant VCF files.

Checks performed:
1. check_sv_extent: Every record has a usable extent (INFO/SVLEN or INFO/END).
2. check_symbolic_alts_well_formed: Symbolic ALTs are well formed, including <CN=n>.
3. check_non_symbolic_min_size: Non-symbolic records are at least 50 bp.
"""

from pathlib import Path
import re

import pytest

from ensembl.datacheck.functions.vcf_utils import vcf_reader

pytestmark = [
                pytest.mark.dataset_type("structural_variant"),
                pytest.mark.file_extension("vcf"),
                pytest.mark.file_extension("vcf.gz")
            ]

MIN_SV_SIZE = 50
MAX_REPORTED_FAILURES = 10
SYMBOLIC_ALT = re.compile(r"^<[^<>\s,]+>$")
COPY_NUMBER_ALT = re.compile(r"^<CN=?\d+>$")
NON_SYMBOLIC_ALT = re.compile(r"^[ACGTNacgtn]+$")


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _record_label(record) -> str:
    return record.ID or f"{record.CHROM}:{record.POS}:{record.REF}"


def _assert_no_failures(failures: list[str], message: str) -> None:
    assert not failures, (
        f"{message} Showing up to {MAX_REPORTED_FAILURES}: "
        + "; ".join(failures[:MAX_REPORTED_FAILURES])
    )


def check_sv_extent(target_file: Path):
    """
    Check that every record has a usable extent.

    A record needs a non-zero INFO/SVLEN or an INFO/END greater than POS,
    otherwise the variant cannot be given an extent downstream.

    Args:
        target_file: Path to the structural variant VCF file.

    Raises:
        AssertionError: If any record has neither a non-zero SVLEN nor END > POS.
    """
    reader = vcf_reader(target_file)
    failures = []
    try:
        for record in reader:
            svlens = [
                value for value in _as_list(record.INFO.get("SVLEN"))
                if isinstance(value, (int, float)) and value != 0
            ]
            end = record.INFO.get("END")
            has_proper_end = isinstance(end, (int, float)) and end > record.POS
            if not svlens and not has_proper_end:
                failures.append(_record_label(record))
    finally:
        reader.close()

    _assert_no_failures(
        failures, f"{len(failures)} record(s) have neither a non-zero SVLEN nor END > POS."
    )


def check_symbolic_alts_well_formed(target_file: Path):
    """
    Check that symbolic ALT alleles are well formed.

    Symbolic alleles must look like <TYPE>, and copy number alleles must be
    <CN=n> (or <CNn>) with n a non-negative integer.

    Args:
        target_file: Path to the structural variant VCF file.

    Raises:
        AssertionError: If any symbolic ALT is malformed.
    """
    reader = vcf_reader(target_file)
    failures = []
    try:
        for record in reader:
            for alt in record.ALT:
                if NON_SYMBOLIC_ALT.match(alt) or alt in ("*", "."):
                    continue
                if not SYMBOLIC_ALT.match(alt):
                    failures.append(f"{_record_label(record)} ({alt})")
                elif alt.startswith("<CN") and not COPY_NUMBER_ALT.match(alt):
                    failures.append(f"{_record_label(record)} ({alt})")
    finally:
        reader.close()

    _assert_no_failures(
        failures, f"{len(failures)} record(s) have a malformed symbolic ALT."
    )


def check_non_symbolic_min_size(target_file: Path):
    """
    Check that records without symbolic ALTs are at least 50 bp.

    Smaller non-symbolic records are short variants, not structural variants.
    The size is the longest of REF and the ALT alleles.

    Args:
        target_file: Path to the structural variant VCF file.

    Raises:
        AssertionError: If any non-symbolic record is smaller than 50 bp.
    """
    reader = vcf_reader(target_file)
    failures = []
    try:
        for record in reader:
            alts = record.ALT
            if not alts or not all(NON_SYMBOLIC_ALT.match(alt) for alt in alts):
                continue
            size = max(len(record.REF), *(len(alt) for alt in alts))
            if size < MIN_SV_SIZE:
                failures.append(f"{_record_label(record)} ({size} bp)")
    finally:
        reader.close()

    _assert_no_failures(
        failures,
        f"{len(failures)} non-symbolic record(s) are smaller than {MIN_SV_SIZE} bp.",
    )
