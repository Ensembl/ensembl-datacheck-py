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
Check that refget directories exist and contain all configured expected files.
Checks performed:
    - Validate that the base_path exists and is a directory.
    - Validate that the expected_files are present in the refget directories.
"""

import pytest
from pathlib import Path
from ensembl.datacheck.checks.automation.utils import resolve_genome_relative_path, validate_expected_files


def _validate_only_expected_refget_files(base_path, relative_path, expected_files, resource_label):
    """Fail if any file other than expected_files exists under the resolved refget path."""
    resource_path = Path(base_path) / relative_path

    expected_set = {Path(path).as_posix() for path in expected_files}
    actual_set = {
        file_path.relative_to(resource_path).as_posix()
        for file_path in resource_path.rglob("*")
        if file_path.is_file()
    }

    unexpected_files = sorted(actual_set - expected_set)
    assert not unexpected_files, (
        f"Unexpected {resource_label} files in {resource_path}: {unexpected_files}"
    )


def _resolve_refget_relative_path(base_path, release_name, genome_uuid):
    """Resolve refget path, allowing an optional one-level subdirectory under release."""
    return resolve_genome_relative_path(base_path, Path(f"release_{release_name}"), genome_uuid, "refget")


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("refget")
def check_refget_expected_files(genomes, automation_resource_config):
    """Validate refget expected files for each genome from the automation config."""
    refget_config = automation_resource_config.get("refget")
    assert refget_config, "Missing 'refget' section in automation resource config."

    base_path = refget_config.get("base_path")
    assert base_path, "Missing refget.base_path in automation resource config."

    expected_files = refget_config.get("expected_files", [])
    assert expected_files, "Missing refget.expected_files in automation resource config."

    genome_uuid = genomes["genome_uuid"]
    release_name = genomes.get("release_name")
    assert release_name is not None, f"Missing release_name for genome_uuid={genome_uuid}"

    subfolder = refget_config.get("subfolder", "")
    use_alt = refget_config.get("use_alt_base_path", False)
    if use_alt:
        relative_path = resolve_genome_relative_path(
            base_path=base_path,
            release_root_relative=Path(f"release-{release_name}") / subfolder,
            genome_uuid=genome_uuid,
            resource_label="refget",
        )
        check_base = base_path
    else:
        effective_base = str(Path(base_path) / subfolder) if subfolder else base_path
        relative_path = _resolve_refget_relative_path(
            base_path=effective_base,
            release_name=release_name,
            genome_uuid=genome_uuid,
        )
        check_base = effective_base

    validate_expected_files(
        base_path=check_base,
        relative_path=relative_path,
        expected_files=expected_files,
        resource_label=f"refget (release={release_name}, genome_uuid={genome_uuid})",
    )
    _validate_only_expected_refget_files(
        base_path=check_base,
        relative_path=relative_path,
        expected_files=expected_files,
        resource_label=f"refget (release={release_name}, genome_uuid={genome_uuid})",
    )
