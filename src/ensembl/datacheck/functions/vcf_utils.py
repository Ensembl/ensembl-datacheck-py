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
vcf_utils.py

Shared helpers for VCF parsing, record counting and random-region variant sampling.
"""

from pathlib import Path
import random
import shutil
import subprocess
from typing import Any
import warnings

from cyvcf2 import VCF
from pysam import HTSFile

from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning


def is_vcf_file(hts_file: HTSFile) -> bool:
    """
    Check if the given file object (opened as HTSFile) is a VCF file.

    Args:
        hts_file: HTSFile object received from pysam.VariantFile

    Returns:
        bool: True if the file is a VCF file, False otherwise.
    """
    return  hts_file.is_vcf


def is_bgzf_compressed_file(hts_file: HTSFile) -> bool:
    """
    Check if the given file object (opened as HTSFile) is a bgzipped file.

    Args:
        hts_file: HTSFile object received from pysam.VariantFile

    Returns:
        bool: True if the file is a bgzipped file, False otherwise.
    """
    return hts_file.compression == 'BGZF'


def find_vcf_index(vcf_file: Path | str) -> Path | None:
    """
    Find the index file for a VCF file.

    Args:
        vcf_file: Path to the VCF file.

    Returns:
        Path: Path to the index file if found, None otherwise.
    """
    csi_path = str(vcf_file) + '.csi'
    tbi_path = str(vcf_file) + '.tbi'

    index_file: str | None = None
    if file_exists(csi_path):
        index_file = csi_path
    elif file_exists(tbi_path):
        index_file = tbi_path
    else:
        return None

    return Path(index_file)


def vcf_reader(vcf_file_path: str | Path) -> VCF:
    """
    Provide a cyvcf2 VCF reader opened on a VCF file path.

    Args:
        vcf_file_path: The path to the VCF file.

    Returns:
        cyvcf2.cyvcf2.VCF: Open reader on success.

    Raises:
        Exception: Propagates import/open failures from cyvcf2.
    """
    return VCF(str(vcf_file_path))


def get_vcf_variant_count(file_path: Path | str) -> int | None:
    """
    Get total number of VCF records in a file using bcftools.

    Args:
        file_path: Path to a VCF file.

    Returns:
        int: Total number of VCF records.

    Raises:
        AssertionError: If bcftools is unavailable, command fails, or
            output cannot be parsed.
    """
    assert shutil.which("bcftools") is not None, "bcftools is required but not available in PATH."

    # Query the index file rather than the VCF itself to prevent weirdness with index discovery on non-standard filename extensions (like .vcf.bgzf).
    process = subprocess.run(
        ["bcftools", "index", "--nrecords", str(file_path)],
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


def get_vcf_variant_count_by_chr(filepath: str) -> dict | None:
    """Return per-chromosome variant counts for a VCF.

    Attempts to use 'bcftools index --stats'.
    Falls back to file content iterating if the command fails.

    Args:
        vcf (str): Path to VCF file.

    Returns:
        dict|int: Mapping {chrom: count} or None on failure.
    """
    if filepath is None:
        warnings.warn(
            EnsemblDatacheckWarning(
                "Could not get variant count - no file provided",
                'functions/vcf_utils.py',
                'get_vcf_variant_count_by_chr')
        )
        return None

    process = subprocess.run(
        ["bcftools", "index", "--stats", filepath],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if process.returncode == 0:
        chrom_variant_counts = {}
        for chrom_stat in process.stdout.decode().strip().split("\n"):
            (chrom, _, count) = chrom_stat.split("\t")
            chrom_variant_counts[chrom] = int(count)

        return chrom_variant_counts

    else:
        return None


def get_max_random_regions(params):
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

def parse_CSQ_format(vcf_file: Path | str) -> list[str]:
    try:
        with vcf_reader(vcf_file) as reader:
            csq_info_description = str(reader.get_header_type("CSQ")["Description"])
            csq_fields = [
                csq.strip(' "')
                for csq in csq_info_description.split("Format: ")[1].split("|")
            ]
        return csq_fields

    except Exception as exc:
        raise AssertionError(
            f"Failed to parse CSQ format: {exc}"
        ) from exc


def subsample_variants_from_file(vcf_file: Path | str, params: dict, no_variants:int=10000) -> dict[str, dict[str, Any]]:
    """
    Build a sampled variant dictionary from source VCF.

    The logic mirrors the old datacheck fixture:
    - sample by random chromosome + random start region hops
    - stop after collecting no_variants samples, or when region hops reach
      max_random_regions (default 1000; alias no_rvariants)
    - keep variants in a dict keyed by ID
    - for each sampled region, include at most 11 variants

    Args:
        vcf_file: Path to VCF file to sample.
        params: Parsed command-line params.
        no_variants: Target number of sampled variants. Defaults to 10000.

    Returns:
        dict: Variant dictionary keyed by variant ID; duplicate IDs overwrite
            earlier entries.

    Raises:
        AssertionError: If source VCF cannot be read or lacks required headers.
    """
    max_random_regions = get_max_random_regions(params)
    SUMMARY_STATS_FIELDS = ["NVPHN", "NGPHN", "NTCSQ", "NRCSQ", "NGENE", "NCITE", "RAF"]

    reader = None
    try:
        csq_fields = parse_CSQ_format(vcf_file)

        reader = vcf_reader(vcf_file)

        chroms = reader.seqnames
        assert chroms, "Source VCF has no sequence names in the header."

        variant_list = {}
        total_no_variants = 0
        iteration = 0

        while total_no_variants < no_variants:
            chrom = random.choice(chroms)
            start = random.choice(range(1000, 100000000))

            no_variants_in_region = 0
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

                for ss_field in SUMMARY_STATS_FIELDS:
                    variant_list[variant_id][ss_field] = variant.INFO.get(ss_field, None)

                total_no_variants += 1
                no_variants_in_region += 1
                if no_variants_in_region > 10:
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
