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
Check that BLAST dump directories exist and contain all configured expected files.
Checks performed:
    - Validate that the base_path exists and is a directory.
    - Validate that the expected_files list is not empty.
    - Validate that each expected file exists in the base_path for each genome.
"""

import pytest
from ensembl.datacheck.checks.automation.utils import validate_expected_files


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast")
def check_blast_expected_files(genomes, automation_resource_config):
    """
    Validate BLAST expected files for each genome from the automation config.

    Expected path shape:
        <blast.base_path>/<genome_uuid>/
    """
    blast_config = automation_resource_config.get("blast")
    assert blast_config, "Missing 'blast' section in automation resource config."

    base_path = blast_config.get("base_path")
    assert base_path, "Missing blast.base_path in automation resource config."

    expected_files = blast_config.get("expected_files", [])
    assert expected_files, "Missing blast.expected_files in automation resource config."

    genome_uuid = genomes["genome_uuid"]
    validate_expected_files(
        base_path=base_path,
        relative_path=genome_uuid,
        expected_files=expected_files,
        resource_label=f"BLAST (genome_uuid={genome_uuid})",
    )
