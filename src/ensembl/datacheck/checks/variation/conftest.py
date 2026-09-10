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
variation/conftest.py

Pytest fixtures for variation-specific datachecks.

Fixtures provided:
1. variation_params: Merges variation default sampling parameters with any
   user-supplied --params values.
"""

from pathlib import Path
from typing import Any

import pytest

from ensembl.datacheck.checks.variation.types import Csq_subfield_spec
from ensembl.datacheck.functions.vcf_utils import subsample_variants_from_file

# Constants
DEFAULT_MAX_RANDOM_REGIONS = "1000"

# pytest fixtures
@pytest.fixture(scope="session")
def CSQ_SPECS() -> dict[str, Csq_subfield_spec]:
    """
    Dictionary of CSQ subfield specifications/requirements.

    Keys are CSQ subfield names, values are the subfield specs as `Csq_subfield_spec`.
    """
    return {
        "Allele": {"canbe_empty": False, "species": "all"},
        "Consequence": {"canbe_empty": False, "species": "all"},
        "Feature": {"species": "all"},
        "VARIANT_CLASS": {"canbe_empty": False, "species": "all"},
        "SPDI": {"canbe_empty": False, "species": "all"},
        "PUBMED": {"species": "all"},
        "VAR_SYNONYMS": {"species": "all"},
        "Conservation": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_afr": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_afr": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_afr": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_amr": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_amr": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_amr": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_asj": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_asj": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_asj": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_eas": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_eas": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_eas": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_fin": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_fin": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_fin": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_nfe": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_nfe": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_nfe": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_remaining": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_remaining": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_remaining": {"species": "homo_sapiens"},
        "gnomAD_exomes_AF_sas": {"species": "homo_sapiens"},
        "gnomAD_exomes_AC_sas": {"species": "homo_sapiens"},
        "gnomAD_exomes_AN_sas": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_afr": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_afr": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_afr": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_amr": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_amr": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_amr": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_asj": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_asj": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_asj": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_eas": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_eas": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_eas": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_fin": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_fin": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_fin": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_nfe": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_nfe": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_nfe": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_remaining": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_remaining": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_remaining": {"species": "homo_sapiens"},
        "gnomAD_genomes_AF_sas": {"species": "homo_sapiens"},
        "gnomAD_genomes_AC_sas": {"species": "homo_sapiens"},
        "gnomAD_genomes_AN_sas": {"species": "homo_sapiens"},
        "AF": {"species": "homo_sapiens"},
        "AFR_AF": {"species": "homo_sapiens"},
        "AMR_AF": {"species": "homo_sapiens"},
        "EAS_AF": {"species": "homo_sapiens"},
        "EUR_AF": {"species": "homo_sapiens"},
        "SAS_AF": {"species": "homo_sapiens"},
    }


@pytest.fixture(scope="session")
def csq_specs_species_filtered(CSQ_SPECS: dict[str, Csq_subfield_spec], params: dict[str, str]) -> dict[str, Csq_subfield_spec]:
    """
    CSQ subfield specs filtered to be relevant for the input species.

    Args:
        CSQ_SPECS (dict[str, Csq_subfield_spec]): unfiltered CSQ subfield specs.
        params (dict[str, str]): Parsed command-line parameters.

    Returns:
        dict[str, Csq_subfield_spec]: Filtered CSQ subfield specs.

    Raises:
        ValueError: If species param is not defined.
    """

    param_species = params.get('species')
    if param_species is None:
        raise ValueError("species param must be defined for CSQ checks.")

    filtered_specs = {}
    for field, spec in CSQ_SPECS.items():
        spec_species = spec.get('species', None)
        if spec_species == 'all' or spec_species == param_species:
            filtered_specs[field] = spec
    return filtered_specs


@pytest.fixture(scope="session")
def variation_params(params: dict[str, str]) -> dict[str, str]:
    """
    Variation-specific default parameters for source-file sampling checks.

    Args:
        params (dict): Parsed command-line params from the shared plugin.

    Returns:
        dict: User params merged over variation defaults.
    """
    resolved_params = {"max_random_regions": DEFAULT_MAX_RANDOM_REGIONS}
    resolved_params.update(params)
    return resolved_params


@pytest.fixture(scope="session")
def source_variants_subsample(source_file: Path | None, params: dict[str, str]) -> dict[str, dict[str, Any]]:
    """
    Subsample variants from the source file.

    Args:
        source_file: Path to the source VCF file.
        params: the CLI input parameters.

    Returns:
        dict: Subsampled variants.

    Raises:
        ValueError: If source_file param is not defined.
    """
    if source_file is None:
        raise ValueError("source_file param must be defined for source subsampling.")

    return subsample_variants_from_file(source_file, params)

@pytest.fixture(scope="session")
def target_variants_subsample(target_file: Path | None, params: dict[str, str]) -> dict[str, dict[str, Any]]:
    """
    Subsample variants from the target file.

    Args:
        target_file: Path to the target VCF file.
        params: the CLI input parameters.

    Returns:
        dict: Subsampled variants.

    Raises:
        ValueError: If target_file param is not defined.
    """
    if target_file is None:
        raise ValueError("target_file param must be defined for taret subsampling.")

    return subsample_variants_from_file(target_file, params)
