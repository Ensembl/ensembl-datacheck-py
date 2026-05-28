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
    - Validate that each genome directory exists under <uuid[:3]>/<uuid>.
    - Validate that each expected BLAST database file exists for every genome.
    - Validate that manifest paths match the expected genome file locations.
"""

from pathlib import Path

import pytest

DEFAULT_BLAST_DATABASE_RELEASE_BASE_DIR = (
    "/nfs/production/flicek/ensembl/production/blastdb"
)


def _getoption(user_cli, name, default=None):
    """Return a pytest config option, tolerating lightweight test doubles."""
    try:
        value = user_cli.getoption(name)
    except (AttributeError, ValueError):
        return default
    return default if value is None else value


def _parse_key_value_params(raw_params):
    """Parse --params values into a dict for this check's optional inputs."""
    parsed_params = {}
    for raw_param in raw_params or []:
        for param in raw_param.split(","):
            param = param.strip()
            if not param:
                continue
            if "=" not in param:
                continue
            key, value = param.split("=", 1)
            parsed_params[key.strip()] = value.strip()
    return parsed_params


def _get_blast_database_release_config(automation_resource_config):
    """Return blast_database_release config, failing clearly when absent."""
    release_config = automation_resource_config.get("blast_database_release")
    assert release_config is not None, (
        "Missing 'blast_database_release' section in automation resource config."
    )
    return release_config


def _get_blast_database_release_base_dir(user_cli, automation_resource_config):
    """Resolve base directory from --params, config, or default."""
    params = _parse_key_value_params(
        _getoption(user_cli, "--params", _getoption(user_cli, "params", []))
    )
    release_config = _get_blast_database_release_config(automation_resource_config)
    return (
        params.get("blast_database_release_base_dir")
        or params.get("base_dir")
        or release_config.get("base_path")
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


def _resolve_release_path(base_dir, release_name):
    """Resolve the release directory under base_dir, with a compatibility fallback."""
    base_path = Path(base_dir)
    candidate_paths = [base_path / str(release_name)]
    if not str(release_name).startswith("release_"):
        candidate_paths.append(base_path / f"release_{release_name}")
    candidate_paths.append(base_path)

    unique_candidate_paths = []
    for candidate_path in candidate_paths:
        if candidate_path not in unique_candidate_paths:
            unique_candidate_paths.append(candidate_path)

    for candidate_path in unique_candidate_paths:
        if candidate_path.is_dir() and (candidate_path / "manifest").is_file():
            return candidate_path

    for candidate_path in unique_candidate_paths:
        if candidate_path.is_dir():
            return candidate_path

    searched_paths = [str(path) for path in unique_candidate_paths]
    raise AssertionError(
        f"BLAST database release '{release_name}' was not found under {base_path}. "
        f"Checked release directories: {searched_paths}"
    )


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


def _assert_blast_database_release_is_complete(release_path, genome_uuids, expected_files):
    """Validate filesystem and manifest contents for a BLAST database release."""
    expected_file_paths = _expected_relative_file_paths(genome_uuids, expected_files)
    actual_file_paths = _actual_release_file_paths(release_path)
    manifest_file_paths, malformed_manifest_lines = _read_manifest_file_paths(
        release_path / "manifest"
    )

    missing_genomes = sorted(
        genome_uuid
        for genome_uuid in genome_uuids
        if not (release_path / genome_uuid[:3] / genome_uuid).is_dir()
    )
    missing_files = sorted(expected_file_paths - actual_file_paths)
    extra_files = sorted(actual_file_paths - expected_file_paths)
    missing_manifest_files = sorted(expected_file_paths - manifest_file_paths)
    extra_manifest_files = sorted(manifest_file_paths - expected_file_paths)

    failure_messages = []
    if missing_genomes:
        failure_messages.append(f"Missing genomes: {missing_genomes}")
    if missing_files:
        failure_messages.append(f"Missing files: {missing_files}")
    if extra_files:
        failure_messages.append(f"Extra files: {extra_files}")
    if missing_manifest_files:
        failure_messages.append(f"Missing manifest files: {missing_manifest_files}")
    if extra_manifest_files:
        failure_messages.append(f"Extra manifest files: {extra_manifest_files}")
    if malformed_manifest_lines:
        failure_messages.append(f"Malformed manifest lines: {malformed_manifest_lines}")

    assert not failure_messages, (
        f"BLAST database release validation failed for {release_path}:\n"
        + "\n".join(failure_messages)
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("blast_database_release")
def check_blast_database_release(user_cli, db_session, automation_resource_config):
    """Validate a complete BLAST database release directory."""
    release_name = _getoption(
        user_cli,
        "--release_name",
        _getoption(user_cli, "release_name"),
    )
    assert release_name, "Missing --release_name for blast_database_release."

    base_dir = _get_blast_database_release_base_dir(
        user_cli=user_cli,
        automation_resource_config=automation_resource_config,
    )
    release_path = _resolve_release_path(base_dir=base_dir, release_name=release_name)
    genome_uuids = _get_live_genome_uuids(db_session)
    expected_files = _get_blast_database_release_expected_files(
        automation_resource_config
    )

    _assert_blast_database_release_is_complete(
        release_path=release_path,
        genome_uuids=genome_uuids,
        expected_files=expected_files,
    )
