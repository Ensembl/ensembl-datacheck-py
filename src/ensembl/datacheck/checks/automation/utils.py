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
This module provides functionality to validate the existence of required files
within a resource path.

The module ensures that all specified files, including those that match
wildcard patterns, are present in the specified directory. If any files are
missing, an assertion is raised indicating the missing files.
"""


from pathlib import Path
from ensembl.production.metadata.api.adaptors.genome import GenomeAdaptor

def get_ftp_paths(metadata_uri, taxonomy_uri, genome_uuid) :
    """
    Prepare FTP relative paths for the given genome uuid from metadata.
    """
    return GenomeAdaptor(metadata_uri, taxonomy_uri).get_public_path(genome_uuid)

def validate_expected_files(base_path, relative_path, expected_files, resource_label):
    """Validate that a resource path exists and contains all expected files."""
    resource_path = Path(base_path) / relative_path
    assert resource_path.exists(), f"{resource_label} path does not exist: {resource_path}"

    missing_files = []
    for expected_file in expected_files:
        expected_path = resource_path / expected_file
        if any(char in expected_file for char in "*?[]"):
            if not list(resource_path.glob(expected_file)):
                missing_files.append(expected_file)
        elif not expected_path.exists():
            missing_files.append(expected_file)

    assert not missing_files, (
        f"Missing {resource_label} files in {resource_path}: {missing_files}"
    )
