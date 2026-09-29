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
from ensembl.datacheck.checks.automation.utils import resolve_genome_relative_path, validate_expected_files

ALLOWED_GENOME_BROWSER_FILE_ENDINGS = {
    ".hashes",
    ".hashes.ncd",
    ".sizes",
    ".sizes.ncd",
    ".bb",
    ".bed",
    ".bw",
    ".wig",
    ".txt",
    ".ncd",
}


def _validate_only_allowed_genome_browser_extensions(base_path, relative_path, resource_label):
    """Fail if any file has an extension not in ALLOWED_GENOME_BROWSER_FILE_ENDINGS."""
    resource_path = Path(base_path) / relative_path
    unexpected_files = sorted(
        file_path.relative_to(resource_path).as_posix()
        for file_path in resource_path.rglob("*")
        if file_path.is_file()
        and not any(file_path.name.endswith(ending) for ending in ALLOWED_GENOME_BROWSER_FILE_ENDINGS)
    )
    assert not unexpected_files, (
        f"Unexpected {resource_label} files with disallowed extensions in {resource_path}: "
        f"{unexpected_files}"
    )


def _validate_required_genome_browser_extensions_present(base_path, relative_path, resource_label):
    """Fail if any required extension from ALLOWED_GENOME_BROWSER_FILE_ENDINGS is absent."""
    resource_path = Path(base_path) / relative_path
    file_names = [file_path.name for file_path in resource_path.rglob("*") if file_path.is_file()]
    present_endings = {
        ending
        for ending in ALLOWED_GENOME_BROWSER_FILE_ENDINGS
        if any(name.endswith(ending) for name in file_names)
    }
    missing_endings = sorted(ALLOWED_GENOME_BROWSER_FILE_ENDINGS - present_endings)
    assert not missing_endings, (
        f"Missing {resource_label} required file extensions in {resource_path}: {missing_endings}"
    )


def _resolve_genome_browser_relative_path(base_path, release_name, genome_uuid):
    """Resolve genome browser path, allowing an optional one-level subdirectory under release."""
    return resolve_genome_relative_path(
        base_path, Path(f"release_{release_name}"), genome_uuid, "genome_browser_files"
    )


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

    subfolder = browser_config.get("subfolder", "")
    use_alt = browser_config.get("use_alt_base_path", False)
    if use_alt:
        relative_path = resolve_genome_relative_path(
            base_path=base_path,
            release_root_relative=Path(f"release-{release_name}") / subfolder,
            genome_uuid=genome_uuid,
            resource_label="genome_browser_files",
        )
        check_base = base_path
    else:
        effective_base = str(Path(base_path) / subfolder) if subfolder else base_path
        relative_path = _resolve_genome_browser_relative_path(
            base_path=effective_base,
            release_name=release_name,
            genome_uuid=genome_uuid,
        )
        check_base = effective_base

    validate_expected_files(
        base_path=check_base,
        relative_path=relative_path,
        expected_files=expected_files,
        resource_label=f"genome_browser_files (release={release_name}, genome_uuid={genome_uuid})",
    )
    _validate_only_allowed_genome_browser_extensions(
        base_path=check_base,
        relative_path=relative_path,
        resource_label=f"genome_browser_files (release={release_name}, genome_uuid={genome_uuid})",
    )
    _validate_required_genome_browser_extensions_present(
        base_path=check_base,
        relative_path=relative_path,
        resource_label=f"genome_browser_files (release={release_name}, genome_uuid={genome_uuid})",
    )
