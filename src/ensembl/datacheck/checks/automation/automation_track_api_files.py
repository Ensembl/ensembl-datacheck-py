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
Validate Track API SQLite content and deployed files for a genome.

Inputs:
    - metadata database from ``--database`` for genome/dataset attachment checks
    - Track API SQLite file from ``track_api_files.database_file``
    - deployed track root from ``track_api_files.base_path``
    - required non-track files from ``track_api_files.required_files``
    - required Track API specifications from ``track_api_files.required_tracks``
    - required and optional dataset type names from the automation resource config

Checks performed:
    - the genome has tracks loaded in the Track API SQLite database
    - all required specifications are present for that genome
    - every file listed in Track.datafiles exists on disk
    - every ``.bb`` and ``.bw`` file passes the generic or variation file validator
    - required non-track files such as ``chrom.sizes`` and ``chrom.sizes.ncd`` are present
    - every other file in the genome directory is referenced by a loaded track
    - every loaded Track API dataset is attached to the genome in metadata and uses an allowed dataset type
    - required dataset types are attached to the genome, and optional dataset types are allowed
    - optional dataset attachments can be ignored for reverse-checking from a configured release onward
    - optionally, release information in ``tracks_datasetrelease`` matches the genome release label
"""

from __future__ import annotations

import json
from importlib import import_module
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from ensembl.production.metadata.api.models import (
    Dataset,
    DatasetStatus,
    DatasetType,
    EnsemblRelease,
    Genome,
    GenomeDataset,
)


def _bool_param(value, default=False):
    """Parse a truthy/falsy config value."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _canonical_uuid(value):
    """Return a canonical lowercase hex UUID string."""
    return UUID(str(value)).hex


def _uuid_query_values(value):
    """Return common UUID encodings used by SQLite-backed Track API tables."""
    parsed = UUID(str(value))
    return (str(parsed), parsed.hex, parsed.hex.upper())


def _split_csv_list(value):
    """Split a comma-separated config field into a cleaned list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _release_sort_value(value):
    """Return a comparable value for release names."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def _is_release_at_or_after_cutoff(release_name, cutoff_release_name):
    """Return whether release_name is at or after the configured cutoff."""
    if cutoff_release_name in (None, "") or release_name in (None, ""):
        return False

    release_value = _release_sort_value(release_name)
    cutoff_value = _release_sort_value(cutoff_release_name)
    if isinstance(release_value, int) and isinstance(cutoff_value, int):
        return release_value >= cutoff_value
    if isinstance(release_value, str) and isinstance(cutoff_value, str):
        return release_value >= cutoff_value
    return False


def _include_metadata_row(row, ignore_attached_optional_datasets_from_release=None):
    """Return whether a metadata attachment should participate in Track API checks."""
    if getattr(row, "release_type", None) != "partial":
        return False
    if getattr(row, "dataset_type_name", None) in {"short_variants", "regulation_tracks"}:
        if _is_release_at_or_after_cutoff(
            getattr(row, "release_name", None),
            ignore_attached_optional_datasets_from_release,
        ):
            return False
    return True


def _resolve_path_value(value, genomes):
    """Resolve optional release placeholders in automation path config values."""
    if value is None:
        return None

    resolved_value = str(value)
    release_name = genomes.get("release_name")
    if release_name is None:
        release_name = genomes.get("release_label")

    if release_name is not None:
        resolved_value = resolved_value.format(
            release=str(release_name),
            release_name=str(release_name),
        )
    return resolved_value


def _resolve_track_api_root(base_path, genomes, subfolder="", use_alt_base_path=False):
    """Resolve the release-specific track root from base_path and subfolder."""
    release_name = genomes.get("release_name")
    if release_name is None:
        release_name = genomes.get("release_label")
    assert release_name is not None, (
        f"Missing release_name/release_label for genome_uuid={genomes['genome_uuid']}"
    )

    base = Path(_resolve_path_value(base_path, genomes))
    genome_uuid = genomes["genome_uuid"]

    if _looks_like_track_root(base, genome_uuid):
        return base

    if use_alt_base_path:
        return base / f"release-{release_name}" / subfolder if subfolder else base / f"release-{release_name}"
    return base / subfolder / f"release_{release_name}" if subfolder else base / f"release_{release_name}"


def _resolve_track_api_database_file(database_file, track_root, genomes):
    """Resolve the Track API SQLite path, allowing relative paths under the resolved track root."""
    resolved_database_file = Path(_resolve_path_value(database_file, genomes))
    if resolved_database_file.is_absolute():
        return resolved_database_file
    return track_root / resolved_database_file


def _track_directory_candidates(base_path, genome_uuid):
    """Return the supported genome directory layout under a track root."""
    return [Path(base_path) / genome_uuid[:3].lower() / genome_uuid]


def _looks_like_track_root(base_path, genome_uuid):
    """Return whether base_path already points at a track root containing genome directories."""
    return any(candidate.is_dir() for candidate in _track_directory_candidates(base_path, genome_uuid))


def _track_directory(base_path, genome_uuid):
    """Return the expected destination directory for a genome."""
    candidates = _track_directory_candidates(base_path, genome_uuid)
    existing_candidates = [candidate for candidate in candidates if candidate.is_dir()]
    if existing_candidates:
        return existing_candidates[0]
    return candidates[-1]


def _load_track_rows(database_file, genome_uuid):
    """Load Track API rows for one genome from SQLite."""
    connection = sqlite3.connect(database_file)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
              t.id AS track_pk,
              t.track_id AS track_id,
              t.dataset_id AS dataset_id,
              t.genome_id AS genome_id,
              t.datafiles AS datafiles,
              s.name AS specification
            FROM tracks_track t
            LEFT JOIN tracks_track_specifications tts ON t.id = tts.track_id
            LEFT JOIN tracks_specifications s ON tts.specifications_id = s.id
            WHERE lower(t.genome_id) IN (?, ?, ?)
            ORDER BY t.id
            """,
            _uuid_query_values(genome_uuid),
        ).fetchall()
    finally:
        connection.close()

    grouped = {}
    for row in rows:
        key = row["track_pk"]
        grouped_row = grouped.setdefault(
            key,
            {
                "track_id": row["track_id"],
                "dataset_id": _canonical_uuid(row["dataset_id"]),
                "dataset_id_raw": str(row["dataset_id"]),
                "genome_id": _canonical_uuid(row["genome_id"]),
                "specifications": set(),
                "datafiles": json.loads(row["datafiles"]) if row["datafiles"] else {},
            },
        )
        if row["specification"]:
            grouped_row["specifications"].add(row["specification"])
    return list(grouped.values())


def _load_release_rows(database_file, genome_uuid):
    """Load DatasetRelease rows for one genome from SQLite."""
    connection = sqlite3.connect(database_file)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT dataset_id, genome_id, release_label
            FROM tracks_datasetrelease
            WHERE lower(genome_id) IN (?, ?, ?)
            """,
            _uuid_query_values(genome_uuid),
        ).fetchall()
    finally:
        connection.close()

    return [
        {
            "dataset_id": _canonical_uuid(row["dataset_id"]),
            "dataset_id_raw": str(row["dataset_id"]),
            "genome_id": _canonical_uuid(row["genome_id"]),
            "release_label": row["release_label"],
        }
        for row in rows
    ]


def _fetch_metadata_dataset_rows(db_session, genome_uuid):
    """Return non-faulty metadata dataset attachments for a genome."""
    assert db_session is not None, (
        "The track_api_files datacheck requires --database to point to "
        "the ensembl_genome_metadata database."
    )
    return (
        db_session.query(
            Dataset.dataset_uuid.label("dataset_uuid"),
            Dataset.name.label("dataset_name"),
            DatasetType.name.label("dataset_type_name"),
            EnsemblRelease.name.label("release_name"),
            EnsemblRelease.label.label("release_label"),
            EnsemblRelease.release_type.label("release_type"),
        )
        .join(DatasetType, Dataset.dataset_type_id == DatasetType.dataset_type_id)
        .join(GenomeDataset, Dataset.dataset_id == GenomeDataset.dataset_id)
        .join(Genome, Genome.genome_id == GenomeDataset.genome_id)
        .outerjoin(EnsemblRelease, EnsemblRelease.release_id == GenomeDataset.release_id)
        .filter(Genome.genome_uuid == genome_uuid)
        .filter(Dataset.status != DatasetStatus.FAULTY)
        .all()
    )


def _validate_track_file_content(target_file, dataset_name):
    """Run the appropriate file-content validator for a deployed track file."""
    suffix = target_file.suffix.lower()
    is_variation_dataset = dataset_name == "short_variants"

    if suffix in {".bb", ".bigbed"}:
        if is_variation_dataset:
            import_module("ensembl.datacheck.checks.variation.bigbed").check_validity(target_file)
        else:
            import_module("ensembl.datacheck.checks.bigbed").check_validity(target_file)
    elif suffix in {".bw", ".bigwig"}:
        if is_variation_dataset:
            import_module("ensembl.datacheck.checks.variation.bigwig").check_validity(target_file)
        else:
            import_module("ensembl.datacheck.checks.bigwig").check_validity(target_file)


def _resolve_track_datafile_path(base_path, genome_uuid, stored_path):
    """Resolve a Track.datafiles entry to an on-disk path."""
    relative_path = Path(stored_path)
    if relative_path.is_absolute():
        return relative_path

    direct_path = Path(base_path) / relative_path
    if direct_path.exists():
        return direct_path

    fallback_path = _track_directory(base_path, genome_uuid) / relative_path.name
    return fallback_path


def _expected_relative_path(resolved_path, base_path):
    """Return a track file path relative to base_path when it lives under that root."""
    try:
        return resolved_path.relative_to(Path(base_path))
    except ValueError:
        return None


def _validate_track_rows(track_rows, base_path, genome_uuid, metadata_rows_by_dataset_id):
    """Validate every stored Track.datafiles entry and return expected relative filenames."""
    expected_relative_paths = set()
    for track_row in track_rows:
        assert track_row["datafiles"], (
            f"Track {track_row['track_id']} for genome_uuid={genome_uuid} has no datafiles recorded."
        )
        metadata_row = metadata_rows_by_dataset_id.get(track_row["dataset_id"])
        assert metadata_row is not None, (
            f"Track API dataset {track_row['dataset_id']} is not attached to genome_uuid={genome_uuid} in metadata."
        )
        dataset_prefix = f"{metadata_row.dataset_uuid}_"
        for stored_path in track_row["datafiles"].values():
            resolved_path = _resolve_track_datafile_path(base_path, genome_uuid, stored_path)
            assert resolved_path.exists(), (
                f"Track file listed in SQLite does not exist for genome_uuid={genome_uuid}: {stored_path}"
            )
            _validate_track_file_content(resolved_path, metadata_row.dataset_name)
            assert resolved_path.name.startswith(dataset_prefix), (
                f"Track file does not use the expected dataset-prefixed name {dataset_prefix}: "
                f"{resolved_path.name}"
            )
            relative_path = _expected_relative_path(resolved_path, base_path)
            if relative_path is not None:
                expected_relative_paths.add(relative_path)
    return expected_relative_paths


def _validate_expected_directory_contents(base_path, genome_uuid, track_relative_paths, required_files):
    """Validate required non-track files and reject extras."""
    genome_dir = _track_directory(base_path, genome_uuid)
    assert genome_dir.is_dir(), f"Track API genome directory does not exist: {genome_dir}"

    missing_non_track_files = sorted(
        file_name for file_name in required_files if not (genome_dir / file_name).exists()
    )
    assert not missing_non_track_files, (
        f"Missing required non-track files in {genome_dir}: {missing_non_track_files}"
    )

    expected_relative_paths = {Path(file_name) for file_name in required_files}
    genome_relative_dir = genome_dir.relative_to(Path(base_path))
    expected_relative_paths.update(
        relative_path.relative_to(genome_relative_dir)
        for relative_path in track_relative_paths
        if relative_path.parent == genome_relative_dir
    )

    actual_relative_paths = {
        path.relative_to(genome_dir)
        for path in genome_dir.rglob("*")
        if path.is_file()
    }
    unexpected_files = sorted(
        str(path)
        for path in actual_relative_paths - expected_relative_paths
    )
    assert not unexpected_files, f"Unexpected files present in {genome_dir}: {unexpected_files}"


def _validate_dataset_attachments(track_rows, metadata_rows, genome_uuid):
    """Validate that all Track API dataset UUIDs are attached to the genome in metadata."""
    metadata_dataset_ids = {_canonical_uuid(row.dataset_uuid) for row in metadata_rows}
    track_dataset_ids = {
        track_row["dataset_id"]: track_row["dataset_id_raw"]
        for track_row in track_rows
    }
    unattached_dataset_ids = sorted(
        raw_dataset_id
        for dataset_id, raw_dataset_id in track_dataset_ids.items()
        if dataset_id not in metadata_dataset_ids
    )
    assert not unattached_dataset_ids, (
        f"Track API datasets are not attached to genome_uuid={genome_uuid} in metadata: "
        f"{unattached_dataset_ids}"
    )


def _validate_attached_optional_datasets_have_tracks(
    track_rows,
    metadata_rows,
    genome_uuid,
    optional_dataset_names,
    ignore_attached_optional_datasets_from_release=None,
):
    """Validate that attached optional datasets are represented in the Track API database."""
    attached_optional_dataset_ids = {
        _canonical_uuid(row.dataset_uuid): str(row.dataset_uuid)
        for row in metadata_rows
        if row.dataset_type_name in set(optional_dataset_names)
    }
    track_dataset_ids = {track_row["dataset_id"] for track_row in track_rows}
    missing_track_dataset_ids = sorted(
        raw_dataset_id
        for dataset_id, raw_dataset_id in attached_optional_dataset_ids.items()
        if dataset_id not in track_dataset_ids
    )
    assert not missing_track_dataset_ids, (
        f"Attached optional datasets for genome_uuid={genome_uuid} have no Track API tracks: "
        f"{missing_track_dataset_ids}"
    )


def _validate_dataset_types(track_rows, metadata_rows, genome_uuid, required_dataset_names, optional_dataset_names):
    """Validate required and allowed dataset type names for the genome and its loaded track datasets."""
    attached_dataset_names = {row.dataset_type_name for row in metadata_rows}
    allowed_dataset_names = set(required_dataset_names) | set(optional_dataset_names)
    missing_required_dataset_names = sorted(set(required_dataset_names) - attached_dataset_names)
    assert not missing_required_dataset_names, (
        f"Missing required attached dataset types for genome_uuid={genome_uuid}: "
        f"{missing_required_dataset_names}"
    )

    metadata_rows_by_dataset_id = {
        _canonical_uuid(row.dataset_uuid): row
        for row in metadata_rows
    }
    disallowed_track_datasets = sorted(
        {
            (
                f"{track_row['dataset_id']}:"
                f"{metadata_rows_by_dataset_id[track_row['dataset_id']].dataset_type_name}"
            )
            for track_row in track_rows
            if track_row["dataset_id"] in metadata_rows_by_dataset_id
            and metadata_rows_by_dataset_id[track_row["dataset_id"]].dataset_type_name
            not in allowed_dataset_names
        }
    )
    assert not disallowed_track_datasets, (
        f"Track API datasets for genome_uuid={genome_uuid} use unsupported dataset types: "
        f"{disallowed_track_datasets}"
    )
    return metadata_rows_by_dataset_id


def _validate_release_info(
    track_rows,
    release_rows,
    metadata_rows,
    genome_uuid,
    optional_dataset_names,
    ignore_attached_optional_datasets_from_release=None,
):
    """Validate Track API DatasetRelease rows against the participating metadata attachments."""
    track_dataset_ids = {
        track_row["dataset_id"]: track_row["dataset_id_raw"]
        for track_row in track_rows
    }
    ignored_release_pairs = {
        (_canonical_uuid(row.dataset_uuid), row.release_label)
        for row in metadata_rows
        if row.release_label is not None
        and row.dataset_type_name in set(optional_dataset_names)
        and _is_release_at_or_after_cutoff(
            getattr(row, "release_name", None),
            ignore_attached_optional_datasets_from_release,
        )
    }
    expected_release_pairs = {
        (_canonical_uuid(row.dataset_uuid), row.release_label)
        for row in metadata_rows
        if row.release_label is not None
        and _canonical_uuid(row.dataset_uuid) in track_dataset_ids
        and (_canonical_uuid(row.dataset_uuid), row.release_label) not in ignored_release_pairs
    }
    actual_release_pairs = {
        (row["dataset_id"], row["release_label"]): row["dataset_id_raw"]
        for row in release_rows
        if row["dataset_id"] in track_dataset_ids
        and (row["dataset_id"], row["release_label"]) not in ignored_release_pairs
    }

    missing_release_rows = sorted(
        f"{track_dataset_ids[dataset_id]}@{release_label}"
        for dataset_id, release_label in expected_release_pairs
        if (dataset_id, release_label) not in actual_release_pairs
    )
    unexpected_release_rows = sorted(
        f"{raw_dataset_id}@{release_label}"
        for (dataset_id, release_label), raw_dataset_id in actual_release_pairs.items()
        if (dataset_id, release_label) not in expected_release_pairs
    )

    assert not missing_release_rows, (
        f"Missing tracks_datasetrelease rows for genome_uuid={genome_uuid}: "
        f"{missing_release_rows}"
    )
    assert not unexpected_release_rows, (
        f"Unexpected tracks_datasetrelease rows for genome_uuid={genome_uuid}: "
        f"{unexpected_release_rows}"
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("track_api_files")
def check_track_api_files(genomes, automation_resource_config, db_session):
    """Validate Track API SQLite content and destination files for one genome."""
    track_api_config = automation_resource_config.get("track_api_files")
    assert track_api_config, "Missing 'track_api_files' section in automation resource config."

    base_path = track_api_config.get("base_path")
    assert base_path, "Missing track_api_files.base_path in automation resource config."
    subfolder = track_api_config.get("subfolder", "")
    use_alt = track_api_config.get("use_alt_base_path", False)
    track_root = _resolve_track_api_root(
        base_path=base_path,
        genomes=genomes,
        subfolder=subfolder,
        use_alt_base_path=use_alt,
    )

    database_file = track_api_config.get("database_file")
    assert database_file, "Missing track_api_files.database_file in automation resource config."
    database_file = _resolve_track_api_database_file(database_file, track_root, genomes)
    assert database_file.is_file(), f"Track API SQLite database file does not exist: {database_file}"
    required_files = set(_split_csv_list(track_api_config.get("required_files")))
    assert required_files, "Missing track_api_files.required_files in automation resource config."

    required_specifications = set(_split_csv_list(track_api_config.get("required_tracks")))
    assert required_specifications, (
        "Missing track_api_files.required_tracks in automation resource config."
    )

    genome_uuid = genomes["genome_uuid"]
    track_rows = _load_track_rows(str(database_file), genome_uuid)
    assert track_rows, f"No Track API tracks found in SQLite for genome_uuid={genome_uuid}"

    metadata_rows = _fetch_metadata_dataset_rows(db_session, genome_uuid)
    release_metadata_rows = list(metadata_rows)
    required_dataset_names = _split_csv_list(track_api_config.get("required_datasets"))
    optional_dataset_names = _split_csv_list(track_api_config.get("optional_datasets"))
    ignore_optional_from_release = track_api_config.get(
        "ignore_attached_optional_datasets_from_release"
    )
    metadata_rows = [
        row
        for row in metadata_rows
        if _include_metadata_row(
            row,
            ignore_attached_optional_datasets_from_release=ignore_optional_from_release,
        )
    ]
    _validate_dataset_attachments(track_rows, metadata_rows, genome_uuid)
    _validate_attached_optional_datasets_have_tracks(
        track_rows,
        metadata_rows,
        genome_uuid,
        optional_dataset_names,
        ignore_attached_optional_datasets_from_release=ignore_optional_from_release,
    )
    metadata_rows_by_dataset_id = _validate_dataset_types(
        track_rows=track_rows,
        metadata_rows=metadata_rows,
        genome_uuid=genome_uuid,
        required_dataset_names=required_dataset_names,
        optional_dataset_names=optional_dataset_names,
    )
    loaded_specifications = {
        specification
        for track_row in track_rows
        for specification in track_row["specifications"]
    }
    missing_required_specifications = sorted(required_specifications - loaded_specifications)
    assert not missing_required_specifications, (
        f"Missing required Track API specifications for genome_uuid={genome_uuid}: "
        f"{missing_required_specifications}"
    )

    track_relative_paths = _validate_track_rows(
        track_rows,
        str(track_root),
        genome_uuid,
        metadata_rows_by_dataset_id,
    )
    _validate_expected_directory_contents(
        base_path=str(track_root),
        genome_uuid=genome_uuid,
        track_relative_paths=track_relative_paths,
        required_files=required_files,
    )

    if _bool_param(track_api_config.get("check_release_info"), default=False):
        release_rows = _load_release_rows(str(database_file), genome_uuid)
        _validate_release_info(
            track_rows,
            release_rows,
            release_metadata_rows,
            genome_uuid,
            optional_dataset_names,
            ignore_attached_optional_datasets_from_release=ignore_optional_from_release,
        )
