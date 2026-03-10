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
Check that genome browser directories exist and contain all configured expected files.
Checks performed:
    - Validate that the base_path exists and is a directory.
    - Validate that the expected files are present in the genome browser directories.
"""

from pathlib import Path

import pytest
from ensembl.datacheck.checks.automation.utils import validate_expected_files


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("genome_browser_files")
def check_genome_browser_files_expected_files(genomes, automation_resource_config):
    """Validate genome browser expected files for each genome from the automation config."""
    browser_config = automation_resource_config.get("genome_browser_files")
    assert browser_config, "Missing 'genome_browser_files' section in automation resource config."

    base_path = browser_config.get("base_path")
    assert base_path, "Missing genome_browser_files.base_path in automation resource config."

    expected_files = browser_config.get("expected_files", [])
    assert expected_files, "Missing genome_browser_files.expected_files in automation resource config."

    genome_uuid = genomes["genome_uuid"]
    release_name = genomes.get("release_name")
    assert release_name is not None, f"Missing release_name for genome_uuid={genome_uuid}"

    validate_expected_files(
        base_path=base_path,
        relative_path=Path(f"release_{release_name}") / genome_uuid,
        expected_files=expected_files,
        resource_label=f"genome_browser_files (release={release_name}, genome_uuid={genome_uuid})",
    )
