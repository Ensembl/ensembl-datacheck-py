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
Check that FTP dump directories exist and contain all configured expected files.
Checks performed:
    - Validate that the base_path exists and is a directory.
    - Validate that the expected_files list is not empty.
    - Validate that each expected file exists in the base_path for each genome.
    - Validate that the expected files are present in the FTP directory.

"""


import pytest
from ensembl.datacheck.checks.automation.utils import validate_expected_files
from ensembl.datacheck.checks.automation.utils import get_ftp_paths




def _check_ftp_resource(user_cli, genomes,  automation_resource_config, resource_key, dataset_name):
    """Shared FTP resource validation."""
    resource_config = automation_resource_config.get(resource_key)
    assert resource_config, f"Missing '{resource_key}' section in automation resource config."

    base_path = resource_config.get("base_path")
    assert base_path, f"Missing {resource_key}.base_path in automation resource config."

    expected_files = resource_config.get("expected_files", [])
    assert expected_files, f"Missing {resource_key}.expected_files in automation resource config."

    metadata_db_uri = user_cli.getoption("--database")
    taxonomy_db_uri = user_cli.getoption("--taxonomy_database")

    ftp_paths = get_ftp_paths(metadata_uri=metadata_db_uri, taxonomy_uri=taxonomy_db_uri, genome_uuid=genomes['genome_uuid'])

    validate_expected_files(
        base_path=base_path,
        relative_path=ftp_paths[dataset_name],
        expected_files=expected_files,
        resource_label=f"{resource_key} (genome_uuid={genomes['genome_uuid']})",
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("ftp_dumps")
@pytest.mark.automation_resource("ftp_dumps_geneset")
def check_ftp_dumps_geneset_expected_files(user_cli, genomes, automation_resource_config):
    """Validate expected files for ftp_dumps_geneset."""
    _check_ftp_resource(genomes, automation_resource_config, "ftp_dumps_geneset", 'genebuild')


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("ftp_dumps")
@pytest.mark.automation_resource("ftp_dumps_genomes")
def check_ftp_dumps_genomes_expected_files(user_cli, genomes,  automation_resource_config):
    """Validate expected files for ftp_dumps_genomes."""
    _check_ftp_resource(user_cli, genomes, automation_resource_config, "ftp_dumps_genomes", 'assembly')


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("ftp_dumps")
@pytest.mark.automation_resource("ftp_dumps_homology")
def check_ftp_dumps_homology_expected_files(user_cli, genomes, automation_resource_config):
    """Validate expected files for ftp_dumps_homology."""
    _check_ftp_resource(user_cli, genomes, automation_resource_config, "ftp_dumps_homology", 'homologies')


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("ftp_dumps")
@pytest.mark.automation_resource("ftp_dumps_vep_geneset")
def check_ftp_dumps_vep_geneset_expected_files(user_cli, genomes, automation_resource_config):
    """Validate expected files for ftp_dumps_vep_geneset."""
    _check_ftp_resource(user_cli, genomes,  automation_resource_config, "ftp_dumps_vep_geneset", 'genebuild')


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("ftp_dumps")
@pytest.mark.automation_resource("ftp_dumps_vep_genome")
def check_ftp_dumps_vep_genome_expected_files(user_cli, genomes, automation_resource_config):
    """Validate expected files for ftp_dumps_vep_genome."""
    _check_ftp_resource(user_cli, genomes, automation_resource_config, "ftp_dumps_vep_genome", 'genebuild')
