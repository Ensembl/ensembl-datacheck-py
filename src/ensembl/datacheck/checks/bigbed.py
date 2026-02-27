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

import random
import shutil
import subprocess
import warnings
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import bb_bw_reader, vcf_reader
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning

NO_VARIANTS = 10000

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

    vcf_count = _get_vcf_variant_count(source_file)
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
    # can remove this print statement for prod, but nice to confirm in dev
    print(
        f"Observed BigBed/VCF count ratio: {observed_ratio:.4f} "
        f"(bigBed={bigbed_count}, vcf={vcf_count})"
    )
    assert observed_ratio > min_count_ratio, (
        f"BigBed to VCF count ratio is too low: {observed_ratio:.4f} "
        f"(bigBed={bigbed_count}, vcf={vcf_count}, required>{min_count_ratio})."
    )

def _get_max_random_regions(params):
    """
    Get the random-region iteration cap for source-variant sampling.

    Args:
        params (dict): Parsed command-line params.

    Returns:
        int: Maximum number of random region attempts.

    Raises:
        AssertionError: If max_random_regions (or alias no_rvariants)
            is provided but is not a positive integer.
    """
    if not params:
        return 1000

    if "max_random_regions" in params:
        param_name = "max_random_regions"
        raw_value = params["max_random_regions"]
    elif "no_rvariants" in params:
        param_name = "no_rvariants"
        raw_value = params["no_rvariants"]
    else:
        return 1000

    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise AssertionError(
            f"Parameter {param_name} must be a positive integer, got '{raw_value}'."
        ) from exc
    assert parsed_value > 0, f"Parameter {param_name} must be a positive integer."
    return parsed_value

def _build_variant_list_from_source(source_file, params):
    """
    Build a sampled variant dictionary from source VCF.

    The logic mirrors the old datacheck fixture:
    - sample by random chromosome + random start region hops
    - stop after collecting NO_VARIANTS samples, or when region hops reach
      max_random_regions (default 1000; alias no_rvariants)
    - keep variants in a dict keyed by ID
    - for each sampled region, include at most 11 variants

    Args:
        source_file (pathlib.Path or str): Path to source VCF.
        params (dict): Parsed command-line params.

    Returns:
        dict: Variant dictionary keyed by variant ID; duplicate IDs overwrite
            earlier entries.

    Raises:
        AssertionError: If source VCF cannot be read or lacks required headers.
    """
    max_random_regions = _get_max_random_regions(params)
    summary_stats_fields = ["NVPHN", "NGPHN", "NTCSQ", "NRCSQ", "NGENE", "NCITE", "RAF"]

    reader = None
    try:
        # TODO: assert that source_file is a VCF (use logic that ML will add)
        reader = vcf_reader(source_file)
        csq_info_description = reader.get_header_type("CSQ")["Description"]
        csq_fields = [
            csq.strip()
            for csq in csq_info_description.split("Format: ")[1].split("|")
        ]

        chroms = reader.seqnames
        assert chroms, "Source VCF has no sequence names in the header."

        variant_list = {}
        total_no_variants = 0
        iteration = 0

        while total_no_variants < NO_VARIANTS:
            chrom = random.choice(chroms)
            start = random.choice(range(1000, 100000000))

            no_variants = 0
            for variant in reader(f"{chrom}:{start}"):
                variant_id = variant.ID
                variant_list[variant_id] = {
                    "chrom": variant.CHROM,
                    "pos": variant.POS,
                    "ref": variant.REF,
                    "alts": variant.ALT,
                    "csqs": [],
                }

                for csq in variant.INFO["CSQ"].split(","):
                    csq_values = csq.split("|")
                    csq_hash = {
                        csq_fields[idx]: csq_value
                        for idx, csq_value in enumerate(csq_values)
                    }
                    variant_list[variant_id]["csqs"].append(csq_hash)

                for ss_field in summary_stats_fields:
                    variant_list[variant_id][ss_field] = variant.INFO.get(ss_field, None)

                total_no_variants += 1
                no_variants += 1
                if no_variants > 10:
                    break

            iteration += 1
            if iteration >= max_random_regions:
                break

        return variant_list
    except Exception as exc:
        raise AssertionError(
            f"Could not build source variant list from VCF: {exc}"
        ) from exc
    finally:
        if reader is not None:
            reader.close()

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

    variant_list = _build_variant_list_from_source(source_file, params)
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
