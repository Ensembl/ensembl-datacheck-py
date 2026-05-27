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
import logging
from pathlib import Path
from ensembl.production.metadata.api.adaptors.genome import GenomeAdaptor
from ensembl.production.metadata.api.adaptors.vep import  VepAdaptor

def get_ftp_paths(metadata_uri, taxonomy_uri, genome_uuid, dataset_name=None ) :
    """
    Prepare FTP relative paths for the given genome uuid from metadata.
    """

    if dataset_name and dataset_name.startswith("vep") :
        file_type = dataset_name.split("_", maxsplit=1)[-1] # vep_faa_location is split into ["vep", "faa_location"] and fetch faa_location
        file_location = VepAdaptor(metadata_uri, file=file_type).fetch_vep_locations(genome_uuid)
        if isinstance(file_location, dict):
            file_location = file_location[file_type]
        return {dataset_name: file_location}
    return GenomeAdaptor(metadata_uri, taxonomy_uri).get_public_path(genome_uuid)

def validate_expected_files(base_path, relative_path, expected_files, resource_label):
    """Validate that a resource path exists and contains all expected files."""
    resource_path = Path(base_path) / relative_path
    assert resource_path.exists(), f"{resource_label} path does not exist: {resource_path}"

    search_path = resource_path.parent if resource_path.is_file() else resource_path

    missing_files = []
    for expected_file in expected_files:
        expected_path = search_path / expected_file
        if any(char in expected_file for char in "*?[]"):
            if not list(search_path.glob(expected_file)):
                missing_files.append(expected_file)
        elif not expected_path.exists():
            missing_files.append(expected_file)

    assert not missing_files, (
        f"Missing {resource_label} files in {search_path}: {missing_files}"
    )
