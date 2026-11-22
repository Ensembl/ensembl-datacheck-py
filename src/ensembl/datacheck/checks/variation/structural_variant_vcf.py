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
1. check_id_is_not_graph_node: Identifiers do not contain graph nodes.
2. check_symbolic_alts_well_formed: Symbolic ALTs are well formed, including <CN=n>.
3. check_non_symbolic_min_size: Non-symbolic records are at least 50 bp.

The checks run on the target_variants_subsample fixture, so --subsample-size
controls how many records are checked (0 checks every record).
"""

import re
from typing import Any

import pytest

pytestmark = [
                pytest.mark.dataset_type("structural_variants"),
                pytest.mark.file_extension("vcf.gz")
            ]

MIN_SV_SIZE = 50
MAX_REPORTED_FAILURES = 10
SYMBOLIC_ALT = re.compile(r"^<[^<>\s,]+>$")
COPY_NUMBER_ALT = re.compile(r"^<CN=?\d+>$")
NON_SYMBOLIC_ALT = re.compile(r"^[ACGTNacgtn]+$")
GRAPH_NODE_ID = re.compile(r"(?:[<>]\d+)+")


def _variant_label(variant_id: str | None, variant: dict[str, Any]) -> str:
    return variant_id or f"{variant['chrom']}:{variant['pos']}:{variant['ref']}"


def _assert_no_failures(failures: list[str], message: str) -> None:
    assert not failures, (
        f"{message} Showing up to {MAX_REPORTED_FAILURES}: "
        + "; ".join(failures[:MAX_REPORTED_FAILURES])
    )


def check_id_is_not_graph_node(target_variants_subsample: dict[str, dict[str, Any]]):
    """
    Check that the identifier field does not contain graph nodes.

    Specifically, HGSVC3 source file are non-accessioned identifier with graph node ids
    and we replace them with modified SPDI identifiers.

    Args:
        target_variants_subsample: Variants sampled from the structural variant VCF, keyed by ID.

    Raises:
        AssertionError: If any identifier are malformed such as containing graph nodes.
    """
    failures = []
    for variant_id, variant in target_variants_subsample.items():
        if variant_id and GRAPH_NODE_ID.fullmatch(variant_id):
            failures.append(f"{variant['chrom']}:{variant['pos']} ({variant_id})")

    _assert_no_failures(
        failures, f"{len(failures)} record(s) have a malformed identifier."
    )


def check_symbolic_alts_well_formed(target_variants_subsample: dict[str, dict[str, Any]]):
    """
    Check that symbolic ALT alleles are well formed.

    Symbolic alleles must look like <TYPE>, and copy number alleles must be
    <CN=n> (or <CNn>) with n a non-negative integer.

    Args:
        target_variants_subsample: Variants sampled from the structural variant VCF, keyed by ID.

    Raises:
        AssertionError: If any symbolic ALT is malformed.
    """
    failures = []
    for variant_id, variant in target_variants_subsample.items():
        for alt in variant["alts"]:
            if NON_SYMBOLIC_ALT.match(alt) or alt in ("*", "."):
                continue
            if not SYMBOLIC_ALT.match(alt):
                failures.append(f"{_variant_label(variant_id, variant)} ({alt})")
            elif alt.startswith("<CN") and not COPY_NUMBER_ALT.match(alt):
                failures.append(f"{_variant_label(variant_id, variant)} ({alt})")

    _assert_no_failures(
        failures, f"{len(failures)} record(s) have a malformed symbolic ALT."
    )


def check_non_symbolic_min_size(target_variants_subsample: dict[str, dict[str, Any]]):
    """
    Check that records without symbolic ALTs are at least 50 bp.

    Smaller non-symbolic records are short variants, not structural variants.
    The size is the longest of REF and the ALT alleles.

    Args:
        target_variants_subsample: Variants sampled from the structural variant VCF, keyed by ID.

    Raises:
        AssertionError: If any non-symbolic record is smaller than 50 bp.
    """
    failures = []
    for variant_id, variant in target_variants_subsample.items():
        alts = variant["alts"]
        if not alts or not all(NON_SYMBOLIC_ALT.match(alt) for alt in alts):
            continue
        size = max(len(variant["ref"]), *(len(alt) for alt in alts))
        if size < MIN_SV_SIZE:
            failures.append(f"{_variant_label(variant_id, variant)} ({size} bp)")

    _assert_no_failures(
        failures,
        f"{len(failures)} non-symbolic record(s) are smaller than {MIN_SV_SIZE} bp.",
    )
