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

"""Validate the files copied into a BLAST database release.

This is intentionally narrower than ``automation_blast_database_release``.
It verifies the just-generated source manifest against the target release and
does not inspect metadata or pre-existing release entries.  It can therefore
run between rsync and stale-data cleanup.
"""

import hashlib
from pathlib import Path

import pytest


CHUNK_SIZE = 1024 * 1024


def _get_sync_config(automation_resource_config):
    """Return the BLAST database release-sync configuration section."""
    config = automation_resource_config.get("blast_database_release_sync")
    assert config is not None, (
        "Missing 'blast_database_release_sync' section in automation resource config."
    )
    return config


def _get_required_path(config, key):
    """Return an existing path required by the release-sync configuration."""
    value = config.get(key)
    assert value, f"Missing blast_database_release_sync.{key} in automation resource config."
    path = Path(value)
    assert path.exists(), f"BLAST database release sync {key} does not exist: {path}"
    return path


def _read_manifest(manifest_path):
    """Return ``(checksum, relative_path)`` entries from an md5sum manifest."""
    entries = []
    malformed_lines = []

    with manifest_path.open(encoding="utf-8") as manifest:
        for line_number, line in enumerate(manifest, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(None, 1)
            if len(parts) != 2 or len(parts[0]) != 32:
                malformed_lines.append(f"{line_number}: {stripped}")
                continue
            try:
                int(parts[0], 16)
            except ValueError:
                malformed_lines.append(f"{line_number}: {stripped}")
                continue
            relative_path = Path(parts[1].strip())
            if relative_path.is_absolute() or ".." in relative_path.parts:
                malformed_lines.append(f"{line_number}: {stripped}")
                continue
            entries.append((parts[0].lower(), relative_path))

    assert not malformed_lines, "Malformed manifest lines:\n" + "\n".join(malformed_lines)
    assert entries, f"Manifest contains no file entries: {manifest_path}"
    return entries


def _md5sum(path):
    """Calculate and return the hexadecimal MD5 checksum for ``path``."""
    try:
        digest = hashlib.md5(usedforsecurity=False)
    except TypeError:
        digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="session")
def blast_database_release_sync_context(automation_resource_config):
    """Load the target directory and source manifest once per test session."""
    config = _get_sync_config(automation_resource_config)
    release_path = _get_required_path(config, "base_path")
    assert release_path.is_dir(), (
        f"BLAST database release sync base_path is not a directory: {release_path}"
    )
    manifest_path = _get_required_path(config, "manifest_path")
    assert manifest_path.is_file(), (
        f"BLAST database release sync manifest_path is not a file: {manifest_path}"
    )
    return {"release_path": release_path, "entries": _read_manifest(manifest_path)}


@pytest.mark.automation_resource("blast_database_release_sync")
def check_blast_database_release_sync_files_exist(blast_database_release_sync_context):
    """Check that each source-manifest file was copied to the release path."""
    release_path = blast_database_release_sync_context["release_path"]
    missing = [
        relative_path.as_posix()
        for _, relative_path in blast_database_release_sync_context["entries"]
        if not (release_path / relative_path).is_file()
    ]
    assert not missing, "Missing copied BLAST files:\n" + "\n".join(sorted(missing))


@pytest.mark.automation_resource("blast_database_release_sync")
def check_blast_database_release_sync_checksums(blast_database_release_sync_context):
    """Check that each copied file has the checksum in the source manifest."""
    release_path = blast_database_release_sync_context["release_path"]
    mismatches = []
    for expected_checksum, relative_path in blast_database_release_sync_context["entries"]:
        target_path = release_path / relative_path
        if target_path.is_file() and _md5sum(target_path) != expected_checksum:
            mismatches.append(relative_path.as_posix())
    assert not mismatches, "BLAST file checksum mismatches:\n" + "\n".join(sorted(mismatches))
