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
from ensembl.datacheck.checks.automation.utils import validate_expected_files


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
    base = Path(base_path)
    release_root_relative = Path(f"release_{release_name}")
    release_root = base / release_root_relative
    assert release_root.is_dir(), f"Release directory does not exist: {release_root}"

    direct_relative = release_root_relative / genome_uuid
    if (base / direct_relative).is_dir():
        return direct_relative

    nested_candidates = sorted(
        candidate.relative_to(base)
        for candidate in release_root.glob(f"*/{genome_uuid}")
        if candidate.is_dir()
    )
    assert nested_candidates, (
        f"refget path does not exist for genome_uuid={genome_uuid} "
        f"under {release_root} (checked direct and one-level nested directories)"
    )
    assert len(nested_candidates) == 1, (
        f"Multiple refget directories found for genome_uuid={genome_uuid}: "
        f"{[str(path) for path in nested_candidates]}"
    )
    return nested_candidates[0]


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
        relative_path = Path(f"release-{release_name}") / subfolder / genome_uuid if subfolder else Path(f"release-{release_name}") / genome_uuid
        assert (Path(base_path) / relative_path).is_dir(), (
            f"refget path does not exist for genome_uuid={genome_uuid}: "
            f"{Path(base_path) / relative_path}"
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
