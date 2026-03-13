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
Check that genesearch  file exists for each genome UUID.
Checks performed:
    - Validate that the base_path exists and is a directory.
    - Validate that the genesearch_file exists for each genome.
"""

from pathlib import Path

import pytest


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("genesearch")
def check_genesearch_expected_file(genomes, automation_resource_config):
    """Validate genesearch expected file for each genome from the automation config."""
    genesearch_config = automation_resource_config.get("genesearch")
    assert genesearch_config, "Missing 'genesearch' section in automation resource config."

    base_path = genesearch_config.get("base_path")
    assert base_path, "Missing genesearch.base_path in automation resource config."

    genome_uuid = genomes["genome_uuid"]
    genesearch_file = Path(base_path) / f"{genome_uuid}_toplevel_solr.json"
    assert genesearch_file.is_file(), (
        f"genesearch file does not exist for genome_uuid={genome_uuid}: {genesearch_file}"
    )
