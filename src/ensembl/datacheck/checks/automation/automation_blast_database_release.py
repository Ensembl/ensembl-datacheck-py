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
Check that a BLAST database release contains every live genome and expected file.
Checks performed:
    - Use ensembl-metadata-api search utils to get live genome UUIDs.
    - Validate missing genomes.
    - Validate missing files.
    - Validate extra files.
    - Validate missing manifest entries.
    - Validate extra manifest entries.
"""

from pathlib import Path

import pytest

DEFAULT_BLAST_DATABASE_RELEASE_BASE_DIR = (
    "/nfs/production/flicek/ensembl/production/blastdb"
)

# Files with these extensions are optional: present or absent is equally valid.
# In the long term these should be generated every time.
_OPTIONAL_EXTENSIONS = frozenset({'.njs', '.pjs'})


def _get_blast_database_release_config(automation_resource_config):
    """Return blast_database_release config, failing clearly when absent."""
    release_config = automation_resource_config.get("blast_database_release")
    assert release_config is not None, (
        "Missing 'blast_database_release' section in automation resource config."
    )
    return release_config


def _get_blast_database_release_base_dir(automation_resource_config):
    """Resolve base directory from config or default."""
    release_config = _get_blast_database_release_config(automation_resource_config)
    return (
        release_config.get("base_path")
        or DEFAULT_BLAST_DATABASE_RELEASE_BASE_DIR
    )


def _get_blast_database_release_expected_files(automation_resource_config):
    """Resolve expected BLAST database release files from config."""
    release_config = _get_blast_database_release_config(automation_resource_config)
    expected_files = release_config.get("expected_files", [])
    assert expected_files, (
        "Missing blast_database_release.expected_files in automation resource config."
    )
    return expected_files


def _resolve_release_path(base_dir):
    """Resolve the BLAST database release directory from the configured base path."""
    release_path = Path(base_dir)
    assert release_path.is_dir(), (
        f"BLAST database release directory does not exist: {release_path}"
    )
    return release_path


def _get_live_genome_uuids(db_session):
    """Fetch live genome UUIDs via ensembl-metadata-api search utils."""
    assert db_session is not None, (
        "Missing --database for blast_database_release. "
        "Provide a metadata database URL with --database."
    )
    try:
        from ensembl.production.metadata.api.search.utils import get_all_live_genomes
    except ImportError as exc:
        raise AssertionError(
            "Unable to import get_all_live_genomes from "
            "ensembl.production.metadata.api.search.utils. "
            "Install an ensembl-metadata-api version that provides this helper."
        ) from exc

    genomes = get_all_live_genomes(db_session)
    genome_uuids = sorted({genome.genome_uuid for genome in genomes})
    assert genome_uuids, "No live genomes returned by get_all_live_genomes."
    return genome_uuids


def _expected_relative_file_paths(genome_uuids, expected_files):
    """Build expected release-relative BLAST database file paths."""
    return {
        (Path(genome_uuid[:3]) / genome_uuid / expected_file).as_posix()
        for genome_uuid in genome_uuids
        for expected_file in expected_files
    }


def _read_manifest_file_paths(manifest_path):
    """Read manifest file paths, ignoring checksums."""
    assert manifest_path.is_file(), f"Manifest file does not exist: {manifest_path}"

    manifest_file_paths = set()
    malformed_manifest_lines = []

    with manifest_path.open() as manifest_file:
        for line_number, line in enumerate(manifest_file, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            parts = stripped_line.split()
            if len(parts) < 2:
                malformed_manifest_lines.append(f"{line_number}: {stripped_line}")
                continue
            manifest_file_paths.add(parts[1])

    return manifest_file_paths, malformed_manifest_lines


def _actual_release_file_paths(release_path):
    """Return all release-relative files except the manifest itself."""
    return {
        file_path.relative_to(release_path).as_posix()
        for file_path in release_path.rglob("*")
        if file_path.is_file() and file_path.name != "manifest"
    }


def _assert_no_discrepancies(label, release_path, items):
    """Fail with a concise first line followed by the full discrepancy list."""
    sorted_items = sorted(items)
    if not sorted_items:
        return

    error_lines = [
        f"{label}: {len(sorted_items)}. Release path: {release_path}",
        "Full list:",
        *sorted_items,
    ]
    raise AssertionError("\n".join(error_lines))


def _get_blast_database_release_context(user_cli, db_session, automation_resource_config):
    """Build shared BLAST database release validation context."""
    base_dir = _get_blast_database_release_base_dir(automation_resource_config)
    release_path = _resolve_release_path(base_dir=base_dir)
    genome_uuids = _get_live_genome_uuids(db_session)
    expected_files = _get_blast_database_release_expected_files(
        automation_resource_config
    )
    expected_file_paths = _expected_relative_file_paths(genome_uuids, expected_files)
    actual_file_paths = _actual_release_file_paths(release_path)
    manifest_file_paths, malformed_manifest_lines = _read_manifest_file_paths(
        release_path / "manifest"
    )

    return {
        "release_path": release_path,
        "genome_uuids": genome_uuids,
        "expected_file_paths": expected_file_paths,
        "actual_file_paths": actual_file_paths,
        "manifest_file_paths": manifest_file_paths,
        "malformed_manifest_lines": malformed_manifest_lines,
    }


@pytest.fixture(scope="session")
def blast_database_release_context(user_cli, db_session, automation_resource_config):
    """Build shared context for BLAST database release checks."""
    return _get_blast_database_release_context(
        user_cli=user_cli,
        db_session=db_session,
        automation_resource_config=automation_resource_config,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_release")
def check_blast_database_release_missing_genomes(blast_database_release_context):
    """Check that every expected genome directory is present."""
    release_path = blast_database_release_context["release_path"]
    genome_uuids = blast_database_release_context["genome_uuids"]

    missing_genomes = sorted(
        genome_uuid
        for genome_uuid in genome_uuids
        if not (release_path / genome_uuid[:3] / genome_uuid).is_dir()
    )
    _assert_no_discrepancies(
        label="Missing genomes",
        release_path=release_path,
        items=missing_genomes,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_release")
def check_blast_database_release_missing_files(blast_database_release_context):
    """Check that every expected BLAST database file is present."""
    release_path = blast_database_release_context["release_path"]
    missing_files = sorted(
        path for path in (
            blast_database_release_context["expected_file_paths"]
            - blast_database_release_context["actual_file_paths"]
        )
        if Path(path).suffix not in _OPTIONAL_EXTENSIONS
    )
    _assert_no_discrepancies(
        label="Missing files",
        release_path=release_path,
        items=missing_files,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_release")
def check_blast_database_release_extra_files(blast_database_release_context):
    """Check that the release contains no unexpected BLAST database files."""
    release_path = blast_database_release_context["release_path"]
    extra_files = sorted(
        path for path in (
            blast_database_release_context["actual_file_paths"]
            - blast_database_release_context["expected_file_paths"]
        )
        if Path(path).suffix not in _OPTIONAL_EXTENSIONS
    )
    _assert_no_discrepancies(
        label="Extra files",
        release_path=release_path,
        items=extra_files,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_release")
def check_blast_database_release_missing_manifest_files(blast_database_release_context):
    """Check that every expected BLAST database file is listed in manifest."""
    release_path = blast_database_release_context["release_path"]
    _assert_no_discrepancies(
        label="Malformed manifest lines",
        release_path=release_path,
        items=blast_database_release_context["malformed_manifest_lines"],
    )
    missing_manifest_files = sorted(
        blast_database_release_context["expected_file_paths"]
        - blast_database_release_context["manifest_file_paths"]
    )
    _assert_no_discrepancies(
        label="Missing manifest files",
        release_path=release_path,
        items=missing_manifest_files,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_release")
def check_blast_database_release_extra_manifest_files(blast_database_release_context):
    """Check that manifest contains no unexpected BLAST database file paths."""
    release_path = blast_database_release_context["release_path"]
    extra_manifest_files = sorted(
        path for path in (
            blast_database_release_context["manifest_file_paths"]
            - blast_database_release_context["expected_file_paths"]
        )
        if Path(path).suffix not in _OPTIONAL_EXTENSIONS
    )
    _assert_no_discrepancies(
        label="Extra manifest files",
        release_path=release_path,
        items=extra_manifest_files,
    )
