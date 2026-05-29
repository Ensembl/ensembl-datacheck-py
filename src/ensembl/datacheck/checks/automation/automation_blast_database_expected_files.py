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
Check that BLAST database directories exist and contain all configured expected files.
Checks performed:
    - Validate that the base_path exists and is a directory.
    - Validate that the expected_files list is not empty.
    - Validate that each expected file exists in the base_path for each genome.
"""

from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation.utils import validate_expected_files


def _resolve_blast_database_files_relative_path(
    base_path,
    release_name,
    genome_uuid,
    subfolder=None,
    use_alt_base_path=False,
):
    """Resolve BLAST database path.

    Default layout (base/subfolder/release_X/genome_uuid):
        base_path is the root; subfolder and release_X are prepended in that order.
    Alt layout (base/release-X/subfolder/genome_uuid, used when use_alt_base_path=True):
        release comes first (hyphen-separated), then subfolder, then genome_uuid.
    """
    base = Path(base_path)

    if use_alt_base_path:
        release_dir = Path(f"release-{release_name}")
        uuid_prefix = genome_uuid[:3]
        parts = [release_dir]
        if subfolder:
            parts.append(Path(subfolder))
        parts.extend([Path(uuid_prefix), Path(genome_uuid)])
        relative = Path(*parts)
        assert (base / relative).is_dir(), (
            f"blast_database_files path does not exist for genome_uuid={genome_uuid}: "
            f"{base / relative}"
        )
        return relative

    effective_base = base / subfolder if subfolder else base
    release_root_relative = Path(f"release_{release_name}")
    release_root = effective_base / release_root_relative
    assert release_root.is_dir(), f"Release directory does not exist: {release_root}"

    prefix = Path(subfolder) if subfolder else Path()
    direct_relative = prefix / release_root_relative / genome_uuid
    if (base / direct_relative).is_dir():
        return direct_relative

    nested_candidates = sorted(
        prefix / candidate.relative_to(effective_base)
        for candidate in release_root.glob(f"*/{genome_uuid}")
        if candidate.is_dir()
    )
    assert nested_candidates, (
        f"blast_database_files path does not exist for genome_uuid={genome_uuid} "
        f"under {release_root} (checked direct and one-level nested directories)"
    )
    assert len(nested_candidates) == 1, (
        f"Multiple blast_database_files directories found for genome_uuid={genome_uuid}: "
        f"{[str(path) for path in nested_candidates]}"
    )
    return nested_candidates[0]


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_files")
def check_blast_database_files_expected_files(genomes, automation_resource_config):
    """Validate BLAST database expected files for each genome from the automation config."""
    blast_database_files_config = automation_resource_config.get("blast_database_files")
    assert blast_database_files_config, (
        "Missing 'blast_database_files' section in automation resource config."
    )

    base_path = blast_database_files_config.get("base_path")
    assert base_path, "Missing blast_database_files.base_path in automation resource config."

    expected_files = blast_database_files_config.get("expected_files", [])
    assert expected_files, (
        "Missing blast_database_files.expected_files in automation resource config."
    )

    genome_uuid = genomes["genome_uuid"]
    release_name = genomes.get("release_name")
    assert release_name is not None, f"Missing release_name for genome_uuid={genome_uuid}"

    subfolder = blast_database_files_config.get("subfolder")
    use_alt = blast_database_files_config.get("use_alt_base_path", False)
    relative_path = _resolve_blast_database_files_relative_path(
        base_path=base_path,
        release_name=release_name,
        genome_uuid=genome_uuid,
        subfolder=subfolder,
        use_alt_base_path=use_alt,
    )

    validate_expected_files(
        base_path=base_path,
        relative_path=relative_path,
        expected_files=expected_files,
        resource_label=f"blast_database_files (release={release_name}, genome_uuid={genome_uuid})",
    )
