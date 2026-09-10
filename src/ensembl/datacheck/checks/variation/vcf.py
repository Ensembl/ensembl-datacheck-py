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
variation/vcf.py

This module performs variation-specific vcf checks.
"""

from math import isclose
from pathlib import Path
import warnings

import pytest

from ensembl.datacheck.checks.variation.types import Csq_subfield_spec
from ensembl.datacheck.checks.vcf import *
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from ensembl.datacheck.functions.vcf_utils import (
    get_vcf_variant_count_by_chr,
    get_vcf_variant_count,
    parse_CSQ_format,
    vcf_reader
)

# module level marker to select test per filetype and dataset type
pytestmark = [
    pytest.mark.dataset_type('short_variants'),
    pytest.mark.file_extension("vcf.gz")
]


# Header checks
def check_csq_in_header(subtests: pytest.Subtests, target_file: Path, csq_specs_species_filtered: dict[str, Csq_subfield_spec]):
    """
    Check that the VCF INFO header contains the CSQ field.

    Args:
        target_file: The path to the file.

    Raises:
        AssertionError: If the VCF info header does not contain the CSQ field.
    """

    reader = vcf_reader(target_file)

    assert reader.get_header_type('CSQ'), "CSQ field not found in the VCF (INFO) header."

    # Parse the CSQ format described in the field description
    csq_fields = parse_CSQ_format(target_file)

    for field,spec in csq_specs_species_filtered.items():
        with subtests.test("Evaluating presence of CSQ subfield", field=field, spec=spec):
            assert field in csq_fields, f"CSQ field '{field}' not found in the CSQ fromat string."


def check_csq_format_matches_value_count(target_file: Path, target_variants_subsample: dict):
    """
    Check that the CSQ subfield count as specified in the format description
    matches the number of values defined in the CSQ field on data records.

    Args:
        target_file: The path to the file.
        target_variants_subsample: A subset of the variants in the target file.
    """

    csq_fields = parse_CSQ_format(target_file)

    for variant_id, variant in target_variants_subsample.items():
        csqs = variant['csqs']
        for csq in csqs:
            assert len(csq) == len(csq_fields), f"Variant '{variant_id}' has {len(csq)} CSQ subfields, but the format description specifies {len(csq_fields)}."


def check_source_in_header(target_file: Path):
    """
    Check that the VCF header contains the source field.

    Args:
        target_file: The path to the file.

    Raises:
        AssertionError: If the VCF header does not contain the source field.
    """

    reader = vcf_reader(target_file)

    assert reader.get_header_type('source'), "source field not found in the VCF header."


# Source comparison checks
def check_variant_count_source_comparison(target_file: Path, source_file: Path | None):
    """
    Compare target VCF variant count with source VCF variant count.

    The check asserts:
    - source_file is provided
    - at least 90% of the source variant count is found in the target
    - source variant count does not exceed target variant count

    Args:
        target_file: Path to target VCF file.
        source_file: Path to source VCF file (required).

    Raises:
        `AssertionError` if:
          * inputs are missing/invalid
          * count ratio is below threshold
          * target count exceeds source count
    """
    assert source_file is not None, "A source file is required (--source-file)."

    target_variant_count: int | None = get_vcf_variant_count(target_file)
    source_variant_count: int | None = get_vcf_variant_count(source_file)

    assert target_variant_count is not None
    assert source_variant_count is not None
    assert (target_variant_count / source_variant_count) > 0.90, "Target file variant count is less than 90% of the source file variant count."
    assert (target_variant_count / source_variant_count) <= 1, "Target file contains more variants than the source file."


def check_per_chr_variant_count_source_comparison(subtests: pytest.Subtests, target_file: Path, source_file: Path | None):
    """
    Compare target VCF variant counts with source VCF variant counts per chromosome.
    Only comparses common chromosomes between target and source.

    The check asserts:
    - source_file is provided
    - for each of the common chromosomes between target and source:
        * at least 95% of the source variant count is found in the target
        * source variant count does not exceed target variant count

    Args:
        target_file: Path to target VCF file.
        source_file: Path to source VCF file (required).

    Raises:
        `AssertionError` if:
          * inputs are missing/invalid
          * Count ratio is below threshold.
          * Target count exceeds source count for any chr.
    """
    assert source_file is not None, "A source file is required (--source-file)."

    target_chrs: list[str]
    with vcf_reader(target_file) as reader:
        target_chrs = reader.seqnames
    source_chrs: list[str]
    with vcf_reader(source_file) as reader:
        source_chrs = reader.seqnames

    common_chrs = list(set(target_chrs) & set(source_chrs))

    target_variant_counts = get_vcf_variant_count_by_chr(str(target_file))
    source_variant_counts = get_vcf_variant_count_by_chr(str(source_file))

    assert target_variant_counts is not None
    assert source_variant_counts is not None

    for chr in common_chrs:
        # Note: Not all chr will be present in source VCF (vcf_prepper rename some of them),
        #       nor in the target vcf (vcf_prepper remove some chr variants).
        if chr in target_variant_counts and chr in source_variant_counts:
            with subtests.test(f"Comparing variant counts for chr '{chr}'", chr=chr):
                recovery_ratio = target_variant_counts[chr] / source_variant_counts[chr]
                assert recovery_ratio > 0.90, f"ADVISORY: Target file variant count is only {recovery_ratio * 100}%  (<90%) of the source file variant count for chr {chr}."
                assert recovery_ratio <= 1, f"Target file contains more variants than the source file for chr {chr}."


# Content checks
def check_subsample_csq_content(csq_specs_species_filtered: dict[str, Csq_subfield_spec], subtests: pytest.Subtests, target_file: Path, target_variants_subsample: dict):
    """
    Check that the CSQ field is populated as expected
    for a random subset of variants from the target file.

    Args:
        target_variants_subsample (dict): A subsample of variants from the target file to check.
        csq_specs_species_filtered: Dictionary of CSQ subfield specifications, filtered to fields relevant for the input species only.

    Raises:
        AssertionError: If the CSQ field is not populated as expected in any of the tested variants.
    """
    assert target_variants_subsample is not None and len(target_variants_subsample) > 0, "Failed to sample variants from target file."

    csq_fields_in_header = parse_CSQ_format(target_file)

    for field,spec in csq_specs_species_filtered.items():
        with subtests.test("Evaluating CSQ subfield content", field=field, spec=spec):
            # Skip this check if the field is not present (failure already covered by check_csq_in_header)
            if field not in csq_fields_in_header:
                warnings.warn(
                    EnsemblDatacheckWarning(
                        f"CSQ field '{field}' not found in the VCF (INFO) header; Content check skipped.",
                        "vcf",
                        "check_subsample_csq_content",
                    )
                )
                continue

            canbe_empty = spec.get('canbe_empty', True)

            csq_field_cnt = 0
            for variant_id in target_variants_subsample:
                first_csq = target_variants_subsample[variant_id]['csqs'][0]
                if first_csq.get(field, "") != "":
                    csq_field_cnt += 1

            subsample_size = len(target_variants_subsample)
            if not canbe_empty:
                assert csq_field_cnt == subsample_size, f"Required CSQ field '{field}' is missing in {subsample_size - csq_field_cnt} out of {subsample_size} sampled variants."
            else:
                assert csq_field_cnt > 0, f"ADVISORY: Optional CSQ field '{field}' not found in any of the sampled variants ({subsample_size}). Consider increasing param max_random_regions."


# Summary statistics checks
def check_summary_stats_per_variant(target_variants_subsample: dict):
    """
    Validate per-variant summary fields (NCITE compared to CSQ PUBMED entries).

    Args:
        target_variants_subsample: A subsample of variants from the target file to check.

    Raises:
        AssertionError: If NCITE does not match citation count from CSQ PUBMED entries.
    """

    for variant_id in target_variants_subsample:
        chrom = target_variants_subsample[variant_id]["chrom"]
        pos = target_variants_subsample[variant_id]["pos"]
        citation = set()

        csqs = target_variants_subsample[variant_id]['csqs']
        for csq in csqs:
            if "PUBMED" in csq:
                cites = csq.get("PUBMED", "")
                for cite in cites.split("&"):
                    if cite != "":
                        citation.add(cite)

        if len(citation) > 0:
            pubmed_count = len(citation)
            ncite = int(target_variants_subsample[variant_id]['NCITE'])
            assert pubmed_count == ncite, f"[{chrom}:{pos}:{variant_id}] pubmed_count - {pubmed_count}; ncite - {ncite}"


def check_summary_stats_per_allele(target_variants_subsample: dict):
    """
    Validate per-allele summary fields.

    Args:
        target_variants_subsample: A subsample of variants from the target file to check.

    Raises:
        AssertionError: If any of the per-allele summary statistics fields do not match the corresponding data-set.
    """

    PER_ALLELE_SUMMARY_FIELDS: list[str] = [
        "NTCSQ",
        "NRCSQ",
        "NGENE",
        "NVPHN",
        "NGPHN"
    ]

    SKIP_CONSEQUENCE = [
        "downstream_gene_variant",
        "upstream_gene_variant",
        "intergenic_variant",
        "TF_binding_site_variant",
        "TFBS_ablation",
        "TFBS_amplification",
    ]
    """Consequence types to skip when aggregating per-allele summary stats."""

    for variant_id in target_variants_subsample:
        per_allele_summary_data: dict[str, dict[str, set[str]]] = {
            fieldname: {}
            for fieldname in PER_ALLELE_SUMMARY_FIELDS
        }
        """Mapping of VCF allele-summary stats field names to per-allele sets of corresponding data."""

        # Collect per-allele data sets
        csqs = target_variants_subsample[variant_id]['csqs']
        for csq in csqs:
            allele_key: str = f"{csq['ALLELE_NUM']}-{csq['Allele']}"
            consequences: str = str(csq["Consequence"])
            feature_stable_id: str = str(csq["Feature"])

            for consequence in consequences.split("&"):
                if consequence in SKIP_CONSEQUENCE:
                    continue

                if consequence.startswith("regulatory"):
                    if allele_key not in per_allele_summary_data['NRCSQ']:
                        per_allele_summary_data['NRCSQ'][allele_key] = set()
                    per_allele_summary_data['NRCSQ'][allele_key].add(
                        f"{feature_stable_id}:{consequences}"  # Intentionally using consequences because represented as single row in entity viewer
                    )
                else:
                    if allele_key not in per_allele_summary_data['NTCSQ']:
                        per_allele_summary_data['NTCSQ'][allele_key] = set()
                    per_allele_summary_data['NTCSQ'][allele_key].add(
                        f"{feature_stable_id}:{consequences}"  # Intentionally using consequences because represented as single row in entity viewer
                    )

                gene = csq.get("Gene")
                if gene:
                    if allele_key not in per_allele_summary_data['NGENE']:
                        per_allele_summary_data['NGENE'][allele_key] = set()
                    per_allele_summary_data['NGENE'][allele_key].add(csq["Gene"])

            phenotypes = csq.get("PHENOTYPES", "")
            for phenotype in phenotypes.split("&"):
                pheno_per_allele_fields = phenotype.split("+")
                if len(pheno_per_allele_fields) != 3:
                    continue

                (name, source, feature) = pheno_per_allele_fields
                if feature.startswith("ENS"):
                    if allele_key not in per_allele_summary_data['NGPHN']:
                        per_allele_summary_data['NGPHN'][allele_key] = set()
                    per_allele_summary_data['NGPHN'][allele_key].add(f"{name}:{source}:{feature}")
                else:
                    if allele_key not in per_allele_summary_data['NVPHN']:
                        per_allele_summary_data['NVPHN'][allele_key] = set()
                    per_allele_summary_data['NVPHN'][allele_key].add(
                        f"{name}:{source}:{feature}"
                    )

        chrom = target_variants_subsample[variant_id]["chrom"]
        pos = target_variants_subsample[variant_id]["pos"]

        # Validate per-allele summary stats
        for summary_fieldname in PER_ALLELE_SUMMARY_FIELDS:
            field_datasets = per_allele_summary_data[summary_fieldname]

            dataset_counts: tuple[int, ...]
            if len(field_datasets) >= 1:
                # Sort by field_datasets keys (=ALLELE_NUM from CSQ), in order to match summary field allele order.
                dataset_counts = tuple([len(v) for (_, v) in sorted(field_datasets.items(), key=lambda item: item[0])])
            else:
                dataset_counts = ()

            vcf_summary_stat: tuple | str | int | list[int] | None = target_variants_subsample[variant_id].get(summary_fieldname)

            summary_stats: tuple[int, ...]
            if isinstance(vcf_summary_stat, tuple):
                summary_stats = vcf_summary_stat
            elif isinstance(vcf_summary_stat, int):
                summary_stats = (vcf_summary_stat,)
            elif isinstance(vcf_summary_stat, list):
                summary_stats = tuple(vcf_summary_stat)
            elif isinstance(vcf_summary_stat, str):
                summary_stats = tuple([int(stat) for stat in vcf_summary_stat.split(",")])
            elif vcf_summary_stat is None:
                summary_stats = ()
            else:
                raise ValueError(f"Unexpected summary stats type: {type(vcf_summary_stat)}. Value: {vcf_summary_stat}")

            assert dataset_counts == summary_stats, f"[{chrom}:{pos}:{variant_id} - {summary_fieldname}] dataset_counts - {dataset_counts}; datasets - {field_datasets}; summary_stat - {summary_stats}"


def check_summary_stats_frequency(target_variants_subsample: dict, params: dict[str, str]):
        """Validate representative allele frequency (RAF) matches frequencies from CSQ fields.
        This test is only applicable to human species (GRCh38 and GRCh37).

        Args:
            target_variants_subsample (dict): Subsampled variants.
            params (dict[str, str]): Parsed command-line parameters.

        Raises:
            ValueError: If species param is not defined.
            AssertionError: If RAF does not match frequencies from CSQ fields.
        """

        species = params.get('species')
        if species is None:
            raise ValueError("species param must be defined for summary stats frequency check.")

        if species != "homo_sapiens":
            pytest.skip(f"Check not relevant for species {species}, skipping ...")

        for variant_id in target_variants_subsample:
            chrom = target_variants_subsample[variant_id]["chrom"]
            pos = target_variants_subsample[variant_id]["pos"]
            frequency: dict[str, float] = {}

            csqs = target_variants_subsample[variant_id]['csqs']
            skip_variant = False
            for csq in csqs:
                allele_key = f"{csq['ALLELE_NUM']}-{csq['Allele']}"
                freq = csq["gnomAD_genomes_AF"]

                if freq != "":
                    # skip variants with multiple frequencies (separated by &, currently not supported)
                    if "&" in freq:
                        skip_variant = True
                        break

                    frequency[allele_key] = float(freq)

            if skip_variant:
                continue

            a_t = 1.0
            r_t = 1e-5

            if len(frequency) >= 1:
                csq_freqs = tuple(v for (_, v) in sorted(frequency.items(), key=lambda item: item[0]))
                raf_stats: tuple[float, ...]
                if type(target_variants_subsample[variant_id]["RAF"]) is tuple:
                    raf_stats = tuple([val for val in target_variants_subsample[variant_id]["RAF"] if val is not None])
                else:
                    if target_variants_subsample[variant_id]['RAF'] is not None:
                        raf_stats = (target_variants_subsample[variant_id]['RAF'],)
                    else:
                        raf_stats = ()

                assert len(csq_freqs) == len(raf_stats), f"[{chrom}:{pos}:{variant_id}] number of CSQ allele frequencies does not match summary statistics'; csq_freqs - {csq_freqs}; raf_stats - {raf_stats}"
                for idx, _ in enumerate(csq_freqs):
                    assert isclose(csq_freqs[idx], raf_stats[idx], rel_tol=r_t, abs_tol=a_t), f"[{chrom}:{pos}:{variant_id}] csq_freqs - {csq_freqs[idx]}; raf_stats - {raf_stats[idx]}"
            else:
                assert target_variants_subsample[variant_id]["RAF"] is None, f"[{chrom}:{pos}:{variant_id}] csq_freqs - no frequency data found; raf_stats - {target_variants_subsample[variant_id]['RAF']}"
