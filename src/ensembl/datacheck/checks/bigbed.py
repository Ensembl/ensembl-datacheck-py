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
3. check_compare_count_with_source: Compares BigBed item count against source VCF variant count.
"""

import shutil
import subprocess
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import bb_bw_reader

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

def _get_vcf_variant_count(source_file):
    """
    Get total number of VCF records from source_file using bcftools.

    Args:
        source_file (pathlib.Path or str): Path to source VCF file.

    Returns:
        int: Total number of VCF records.

    Raises:
        AssertionError: If bcftools is unavailable, command fails, or
            output cannot be parsed.
    """
    assert shutil.which("bcftools") is not None, "bcftools is required but not available in PATH."

    process = subprocess.run(
        ["bcftools", "index", "--nrecords", str(source_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.returncode == 0, (
        "Could not get variant count from source VCF using bcftools: "
        f"{process.stderr.strip()}"
    )

    output = process.stdout.strip()
    try:
        return int(output)
    except ValueError as exc:
        raise AssertionError(
            f"Could not parse bcftools record count output: '{output}'"
        ) from exc

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

def check_compare_count_with_source(target_file, source_file, params):
    """
    Compare target BigBed item count with source VCF variant count.

    The check asserts:
    - source_file is provided
    - bigBed_count / vcf_count >= min_count_ratio (default 0.95)

    Args:
        target_file (pathlib.Path or None): Path to target BigBed file.
        source_file (pathlib.Path or None): Path to source VCF file.
        params (dict): Parsed command-line params.

    Raises:
        AssertionError: If inputs are missing/invalid or count ratio is below threshold.
    """
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."

    vcf_count = _get_vcf_variant_count(source_file)
    bigbed_count = _get_bigbed_variant_count(target_file)
    min_count_ratio = 0.95

    if vcf_count == 0:
        assert bigbed_count == 0, (
            "Source VCF has 0 variants but BigBed has "
            f"{bigbed_count} entries."
        )
        return

    observed_ratio = bigbed_count / vcf_count
    assert observed_ratio >= min_count_ratio, (
        f"BigBed to VCF count ratio is too low: {observed_ratio:.4f} "
        f"(bigBed={bigbed_count}, vcf={vcf_count}, required>={min_count_ratio})."
    )
