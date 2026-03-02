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
vcf_sampling.py

Shared helpers for VCF record counting and random-region variant sampling.
"""

import random
import shutil
import subprocess
from ensembl.datacheck.functions.io_utils import vcf_reader


def get_vcf_variant_count(source_file):
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


def build_variant_list_from_source(source_file, params, no_variants=10000):
    """
    Build a sampled variant dictionary from source VCF.

    The logic mirrors the old datacheck fixture:
    - sample by random chromosome + random start region hops
    - stop after collecting no_variants samples, or when region hops reach
      max_random_regions (default 1000; alias no_rvariants)
    - keep variants in a dict keyed by ID
    - for each sampled region, include at most 11 variants

    Args:
        source_file (pathlib.Path or str): Path to source VCF.
        params (dict): Parsed command-line params.
        no_variants (int): Target number of sampled variants. Defaults to 10000.

    Returns:
        dict: Variant dictionary keyed by variant ID; duplicate IDs overwrite
            earlier entries.

    Raises:
        AssertionError: If source VCF cannot be read or lacks required headers.
    """
    max_random_regions = get_max_random_regions(params)
    summary_stats_fields = ["NVPHN", "NGPHN", "NTCSQ", "NRCSQ", "NGENE", "NCITE", "RAF"]

    reader = None
    try:
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

                for ss_field in summary_stats_fields:
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
