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
variation/bigwig.py

This module performs variation-specific BigWig checks.

Checks performed:
1. check_exist: Imported generic BigWig existence check.
2. check_validity: Imported generic BigWig validity check.
3. check_compare_count_with_source: Compares BigWig variant count against source VCF variant count.
4. check_variant_exist_from_source: Confirms source VCF variants are represented in BigWig.
"""

import warnings

import numpy as np

from ensembl.datacheck.checks.bigwig import check_exist, check_validity
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import bb_bw_reader, vcf_reader
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from ensembl.datacheck.functions.vcf_sampling import (
    build_variant_list_from_source,
    get_vcf_variant_count,
)


def _get_bigwig_variant_count(target_file, chroms=None):
    """
    Get BigWig variant count from target_file by counting non-zero positions.

    Args:
        target_file (pathlib.Path or str): Path to target BigWig file.
        chroms (list[str] or None): Optional chromosome names to restrict the scan.

    Returns:
        int: Number of non-zero positions in scanned BigWig regions.

    Raises:
        AssertionError: If BigWig cannot be read or counted.
    """
    reader = None
    try:
        reader = bb_bw_reader(target_file)
        assert reader is not None, "Could not open target file as BigWig."
        assert reader.isBigWig(), "The target file is not recognised as BigWig."

        variant_counts = 0
        if chroms is None:
            chroms = reader.chroms()

        for chrom in chroms:
            end = reader.chroms(chrom)
            window = 10000000

            for start_idx in range(0, end, window):
                end_idx = min(start_idx + window, end)
                values = np.array(reader.values(chrom, start_idx, end_idx))
                variant_counts += np.count_nonzero(values)

        return int(variant_counts)
    except Exception as exc:
        raise AssertionError(
            f"Could not get variant count from target BigWig: {exc}"
        ) from exc
    finally:
        if reader is not None:
            reader.close()


def check_compare_count_with_source(target_file, source_file):
    """
    Compare target BigWig variant count with source VCF variant count.

    The check asserts:
    - source_file is provided
    - bigWig_count / vcf_count > min_count_ratio (default 0.95)
    - if source VCF count is 0, target BigWig count must also be 0

    Args:
        target_file (pathlib.Path or None): Path to target BigWig file.
        source_file (pathlib.Path or None): Path to source VCF file.

    Warns:
        EnsemblDatacheckWarning: If source VCF count is 0 and ratio comparison
            is skipped.

    Raises:
        AssertionError: If inputs are missing/invalid, if count ratio is below
            threshold, or if source count is 0 while BigWig count is non-zero.
    """
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."

    vcf_count = get_vcf_variant_count(source_file)
    min_count_ratio = 0.95

    source_reader = None
    try:
        source_reader = vcf_reader(source_file)
        chroms = source_reader.seqnames
        bigwig_count = _get_bigwig_variant_count(target_file, chroms)
    except Exception:
        bigwig_count = _get_bigwig_variant_count(target_file)
    finally:
        if source_reader is not None:
            source_reader.close()

    if vcf_count == 0:
        warnings.warn(
            EnsemblDatacheckWarning(
                "Source VCF has 0 variants; ratio comparison is skipped.",
                "bigwig",
                "check_compare_count_with_source",
            )
        )
        assert bigwig_count == 0, (
            "Source VCF has 0 variants but BigWig has "
            f"{bigwig_count} entries."
        )
        return

    observed_ratio = bigwig_count / vcf_count
    assert observed_ratio > min_count_ratio, (
        f"BigWig to VCF count ratio is too low: {observed_ratio:.4f} "
        f"(bigWig={bigwig_count}, vcf={vcf_count}, required>{min_count_ratio})."
    )


def check_variant_exist_from_source(target_file, source_file, variation_params):
    """
    Check that sampled source variants exist in target BigWig entries.

    Args:
        target_file (pathlib.Path or None): Path to target BigWig file.
        source_file (pathlib.Path or None): Path to source VCF file.
        variation_params (dict): Variation-specific parsed command-line params.

    Warns:
        EnsemblDatacheckWarning: If no source variants are sampled; validation
            is skipped in that case.

    Raises:
        AssertionError: If required files are missing, unreadable, or sampled
            source variants are not represented in BigWig.
    """
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."

    variant_list = build_variant_list_from_source(source_file, variation_params)
    if not variant_list:
        warnings.warn(
            EnsemblDatacheckWarning(
                "No source variants were sampled; no BigWig position comparisons were performed. "
                "Consider increasing max_random_regions.",
                "bigwig",
                "check_variant_exist_from_source",
            )
        )
        return

    reader = None
    try:
        reader = bb_bw_reader(target_file)
        assert reader is not None, "Could not open target file as BigWig."
        assert reader.isBigWig(), "The target file is not recognised as BigWig."

        for variant_id in variant_list:
            chrom = variant_list[variant_id]["chrom"]
            start = variant_list[variant_id]["pos"] - 1
            end = start + 2

            bw_state = reader.stats(chrom, start, end)[0]
            if bw_state is None or not bw_state > 0.0:
                raise AssertionError(
                    "bigWig value does not exist or match with source - "
                    f"{chrom}:{start}-{end} (variant_id={variant_id})"
                )
    finally:
        if reader is not None:
            reader.close()
