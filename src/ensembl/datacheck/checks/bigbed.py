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
bigbed.py

This module performs basic BigBed checks.

Checks performed:
1. check_exist: Asserts that the target BigBed path exists.
2. check_validity: Asserts that the target file is readable as BigBed.
3. check_compare_count_with_source: Compares BigBed variant count against source VCF variant count.
4. check_variant_exist_from_source: Confirms source VCF variants are represented in BigBed.
"""

import shutil
import subprocess
import warnings
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import bb_bw_reader
from ensembl.datacheck.functions.vcf_sampling import (
    build_variant_list_from_source,
    get_vcf_variant_count,
)
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning

def check_exist(target_file):
    """
    Check that the target file exists on disk.

    Args:
        target_file (pathlib.Path or None): Path to the target file.

    Raises:
        AssertionError: If the target file is missing.
    """
    assert file_exists(target_file), "The target file does not exist."

def check_validity(target_file):
    """
    Check that the target file is recognised as BigBed.

    Args:
        target_file (pathlib.Path or None): Path to the target file.

    Raises:
        AssertionError: If the file is missing, unreadable, or not BigBed.
    """
    assert file_exists(target_file), "The target file does not exist."
    reader = None
    try:
        reader = bb_bw_reader(target_file)
        assert reader is not None, "Could not open target file as BigBed."
        assert reader.isBigBed(), "The target file is not recognised as BigBed."
    except Exception as exc:
        raise AssertionError(
            f"Could not validate target file as BigBed: {exc}"
        ) from exc
    finally:
        if reader is not None:
            reader.close()

def _get_bigbed_variant_count(target_file):
    """
    Get BigBed item count from target_file using bigBedInfo.

    Args:
        target_file (pathlib.Path or str): Path to target BigBed file.

    Returns:
        int: Total number of entries reported by bigBedInfo.

    Raises:
        AssertionError: If bigBedInfo is unavailable, command fails, or
            itemCount cannot be parsed.
    """
    assert shutil.which("bigBedInfo") is not None, "bigBedInfo is required but not available in PATH."

    process = subprocess.run(
        ["bigBedInfo", str(target_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.returncode == 0, (
        "Could not get item count from target BigBed using bigBedInfo: "
        f"{process.stderr.strip()}"
    )

    for line in process.stdout.splitlines():
        if "itemCount" in line:
            value = line.split(":", 1)[1].replace(",", "").strip()
            try:
                return int(value)
            except ValueError as exc:
                raise AssertionError(
                    f"Could not parse itemCount from bigBedInfo output: '{line}'"
                ) from exc

    raise AssertionError("Could not find itemCount in bigBedInfo output.")

def check_compare_count_with_source(target_file, source_file):
    """
    Compare target BigBed item count with source VCF variant count.

    The check asserts:
    - source_file is provided
    - bigBed_count / vcf_count > min_count_ratio (default 0.95)
    - if source VCF count is 0, target BigBed count must also be 0

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.
        source_file (pathlib.Path or None): Path to source VCF file.

    Warns:
        EnsemblDatacheckWarning: If source VCF count is 0 and ratio comparison
            is skipped.

    Raises:
        AssertionError: If inputs are missing/invalid, if count ratio is below
            threshold, or if source count is 0 while BigBed count is non-zero.
    """
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."
    # TODO: assert that source_file is a VCF (use logic that ML will add)

    vcf_count = get_vcf_variant_count(source_file)
    bigbed_count = _get_bigbed_variant_count(target_file)
    min_count_ratio = 0.95

    if vcf_count == 0:
        warnings.warn(
            EnsemblDatacheckWarning(
                "Source VCF has 0 variants; ratio comparison is skipped.",
                "bigbed",
                "check_compare_count_with_source",
            )
        )
        assert bigbed_count == 0, (
            "Source VCF has 0 variants but BigBed has "
            f"{bigbed_count} entries."
        )
        return

    observed_ratio = bigbed_count / vcf_count
    assert observed_ratio > min_count_ratio, (
        f"BigBed to VCF count ratio is too low: {observed_ratio:.4f} "
        f"(bigBed={bigbed_count}, vcf={vcf_count}, required>{min_count_ratio})."
    )

def check_variant_exist_from_source(target_file, source_file, params):
    """
    Check that sampled source variants exist in target BigBed entries.

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.
        source_file (pathlib.Path or None): Path to source VCF file.
        params (dict): Parsed command-line params.

    Warns:
        EnsemblDatacheckWarning: If no source variants are sampled; validation
            is skipped in that case.

    Raises:
        AssertionError: If required files are missing, unreadable, or sampled
            source variants are not represented in BigBed.
    """
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."
    # TODO: assert that source_file is a VCF (use logic that ML will add)

    variant_list = build_variant_list_from_source(source_file, params)
    if not variant_list:
        warnings.warn(
            EnsemblDatacheckWarning(
                "No source variants were sampled; no BigBed ID comparisons were performed. "
                "Consider increasing max_random_regions.",
                "bigbed",
                "check_variant_exist_from_source",
            )
        )
        return

    reader = None
    try:
        reader = bb_bw_reader(target_file)
        assert reader is not None, "Could not open target file as BigBed."
        assert reader.isBigBed(), "The target file is not recognised as BigBed."

        for variant_id in variant_list:
            chrom = variant_list[variant_id]["chrom"]
            start = variant_list[variant_id]["pos"] - 1
            end = start + 2

            bb_entries = reader.entries(chrom, start, end)
            if bb_entries is None or len(bb_entries) < 1:
                raise AssertionError(
                    "bigBed entries do not exist or do not match source - "
                    f"{chrom}:{start}-{end}"
                )

            ids_in_bb = []
            for bb_entry in bb_entries:
                bb_entry_id = bb_entry[2].split("\t")[0]
                ids_in_bb.append(bb_entry_id)

            assert variant_id in ids_in_bb, (
                f"Variant ID '{variant_id}' was not found in BigBed entries for "
                f"{chrom}:{start}-{end}. IDs found: "
                f"{ids_in_bb[:10]}{'...' if len(ids_in_bb) > 10 else ''}"
            )
    finally:
        if reader is not None:
            reader.close()
