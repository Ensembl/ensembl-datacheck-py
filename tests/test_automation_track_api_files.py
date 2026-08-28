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

"""Unit tests for Track API SQLite and file automation checks."""

import sqlite3
from collections import namedtuple
from pathlib import Path
from uuid import uuid4

import pytest

from ensembl.datacheck.checks.automation import automation_track_api_files as track_checks

MetadataRow = namedtuple(
    "MetadataRow",
    [
        "dataset_uuid",
        "dataset_name",
        "dataset_type_name",
        "release_label",
        "release_name",
        "release_type",
    ],
    defaults=["I2", "partial"],
)


class _DummyValidatorModule:
    def __init__(self, callback):
        self.check_validity = callback


def _patch_validators(monkeypatch):
    monkeypatch.setattr(
        track_checks,
        "import_module",
        lambda module_name: _DummyValidatorModule(lambda target_file: None),
    )


def _track_api_config(base_path, database_file):
    return {
        "track_api_files": {
            "base_path": str(base_path),
            "subfolder": "tracks",
            "use_alt_base_path": True,
            "database_file": str(database_file),
            "required_files": ["chrom.sizes", "chrom.sizes.ncd"],
            "required_tracks": [
                "gc",
                "contigs",
                "transcripts-gene-other-fwd",
                "transcripts-gene-other-rev",
                "transcripts-gene-pc-fwd",
                "transcripts-gene-pc-rev",
                "simple-features-cpg",
                "simple-features-tssp",
            ],
            "required_datasets": ["core_tracks"],
            "optional_datasets": ["short_variants", "regulation_tracks"],
        }
    }


def _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label=None):
    database_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_file)
    try:
        connection.executescript(
            """
            CREATE TABLE tracks_track (
                id integer PRIMARY KEY,
                track_id text NOT NULL,
                dataset_id text NOT NULL,
                genome_id text NOT NULL,
                datafiles text NOT NULL
            );
            CREATE TABLE tracks_specifications (
                id integer PRIMARY KEY,
                name text NOT NULL UNIQUE
            );
            CREATE TABLE tracks_track_specifications (
                id integer PRIMARY KEY,
                track_id integer NOT NULL,
                specifications_id integer NOT NULL
            );
            CREATE TABLE tracks_datasetrelease (
                id integer PRIMARY KEY,
                dataset_id text NOT NULL,
                genome_id text NOT NULL,
                release_label text NOT NULL
            );
            """
        )

        specification_names = [
            "contigs",
            "gc",
            "simple-features-cpg",
            "simple-features-tssp",
            "transcripts-gene-other-fwd",
            "transcripts-gene-other-rev",
            "transcripts-gene-pc-fwd",
            "transcripts-gene-pc-rev",
        ]
        for specification_id, specification_name in enumerate(specification_names, start=1):
            connection.execute(
                "INSERT INTO tracks_specifications (id, name) VALUES (?, ?)",
                (specification_id, specification_name),
            )

        track_rows = [
            (
                1,
                str(uuid4()),
                dataset_uuid.replace("-", ""),
                genome_uuid.replace("-", ""),
                '{"contig":"%s/%s/%s_contigs.bb"}' % (
                    genome_uuid[:3].lower(),
                    genome_uuid,
                    dataset_uuid.replace("-", "")[:32],
                ),
                [1],
            ),
            (
                2,
                str(uuid4()),
                dataset_uuid.replace("-", ""),
                genome_uuid.replace("-", ""),
                '{"gc":"%s/%s/%s_gc.bw"}' % (
                    genome_uuid[:3].lower(),
                    genome_uuid,
                    dataset_uuid.replace("-", "")[:32],
                ),
                [2],
            ),
            (
                3,
                str(uuid4()),
                dataset_uuid.replace("-", ""),
                genome_uuid.replace("-", ""),
                '{"simple":"%s/%s/%s_simple-features.bb"}' % (
                    genome_uuid[:3].lower(),
                    genome_uuid,
                    dataset_uuid.replace("-", "")[:32],
                ),
                [3, 4],
            ),
            (
                4,
                str(uuid4()),
                dataset_uuid.replace("-", ""),
                genome_uuid.replace("-", ""),
                '{"transcripts":"%s/%s/%s_transcripts.bb"}' % (
                    genome_uuid[:3].lower(),
                    genome_uuid,
                    dataset_uuid.replace("-", "")[:32],
                ),
                [5, 6, 7, 8],
            ),
        ]

        for track_id, track_uuid, dataset_id, genome_id, datafiles, spec_ids in track_rows:
            connection.execute(
                """
                INSERT INTO tracks_track (id, track_id, dataset_id, genome_id, datafiles)
                VALUES (?, ?, ?, ?, ?)
                """,
                (track_id, track_uuid, dataset_id, genome_id, datafiles),
            )
            for offset, specification_id in enumerate(spec_ids, start=1):
                connection.execute(
                    """
                    INSERT INTO tracks_track_specifications (id, track_id, specifications_id)
                    VALUES (?, ?, ?)
                    """,
                    (track_id * 10 + offset, track_id, specification_id),
                )

        if release_label is not None:
            connection.execute(
                """
                INSERT INTO tracks_datasetrelease (dataset_id, genome_id, release_label)
                VALUES (?, ?, ?)
                """,
                (dataset_uuid.replace("-", ""), genome_uuid.replace("-", ""), release_label),
            )
        connection.commit()
    finally:
        connection.close()


def _create_track_directory(track_root, genome_uuid, dataset_uuid):
    genome_dir = Path(track_root) / genome_uuid[:3].lower() / genome_uuid
    genome_dir.mkdir(parents=True)
    dataset_prefix = dataset_uuid
    for file_name in (
        "chrom.sizes",
        "chrom.sizes.ncd",
        f"{dataset_prefix}_contigs.bb",
        f"{dataset_prefix}_gc.bw",
        f"{dataset_prefix}_simple-features.bb",
        f"{dataset_prefix}_transcripts.bb",
    ):
        (genome_dir / file_name).touch()
    return genome_dir


def test_split_csv_list_accepts_lists_and_csv_strings():
    assert set(track_checks._split_csv_list(["gc", "contigs"])) == {"gc", "contigs"}
    assert set(track_checks._split_csv_list("gc, contigs")) == {"gc", "contigs"}


def test_resolve_path_value_expands_release_name_placeholder():
    assert track_checks._resolve_path_value(
        "/nfs/production/release-{release_name}/tracks",
        {"release_name": 24},
    ) == "/nfs/production/release-24/tracks"


def test_is_release_at_or_after_cutoff_returns_false_for_mixed_string_and_int_types():
    assert track_checks._is_release_at_or_after_cutoff("main", 29) is False


def test_resolve_track_api_root_supports_alt_layout():
    assert track_checks._resolve_track_api_root(
        base_path="/hps/nobackup/flicek/ensembl/production/ensembl_dumps",
        genomes={"genome_uuid": str(uuid4()), "release_name": 24},
        subfolder="tracks",
        use_alt_base_path=True,
    ) == Path("/hps/nobackup/flicek/ensembl/production/ensembl_dumps/release-24/tracks")


def test_resolve_track_api_root_accepts_direct_track_root(tmp_path):
    genome_uuid = str(uuid4())
    direct_root = tmp_path / "genome_browser" / "9"
    (direct_root / genome_uuid[:3].lower() / genome_uuid).mkdir(parents=True)

    assert track_checks._resolve_track_api_root(
        base_path=str(direct_root),
        genomes={"genome_uuid": genome_uuid, "release_name": 24},
        subfolder="tracks",
        use_alt_base_path=True,
    ) == direct_root


def test_resolve_track_api_database_file_supports_relative_path():
    track_root = Path("/hps/nobackup/flicek/ensembl/production/ensembl_dumps/release-24/tracks")

    assert track_checks._resolve_track_api_database_file(
        "tracks.sqlite3",
        track_root,
        {"release_name": 24},
    ) == track_root / "tracks.sqlite3"


def test_required_tracks_from_config_are_expected():
    required_specifications = {
        "contigs",
        "gc",
        "simple-features-cpg",
        "simple-features-tssp",
        "transcripts-gene-other-fwd",
        "transcripts-gene-other-rev",
        "transcripts-gene-pc-fwd",
        "transcripts-gene-pc-rev",
    }

    assert required_specifications == {
        "contigs",
        "gc",
        "simple-features-cpg",
        "simple-features-tssp",
        "transcripts-gene-other-fwd",
        "transcripts-gene-other-rev",
        "transcripts-gene-pc-fwd",
        "transcripts-gene-pc-rev",
    }


def test_track_directory_uses_three_character_prefix(tmp_path):
    genome_uuid = str(uuid4())
    expected_dir = tmp_path / genome_uuid[:3].lower() / genome_uuid
    expected_dir.mkdir(parents=True)

    assert track_checks._track_directory(tmp_path, genome_uuid) == expected_dir


def test_check_track_api_files_passes(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
            ),
        ],
    )

    track_checks.check_track_api_files(
        genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
        automation_resource_config=_track_api_config(tmp_path, database_file),
        db_session=object(),
    )


def test_check_track_api_files_fails_on_unexpected_file(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2024-01-01")
    genome_dir = _create_track_directory(track_root, genome_uuid, dataset_uuid)
    (genome_dir / "unexpected.txt").touch()

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
            ),
        ],
    )

    with pytest.raises(AssertionError, match="Unexpected files present"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )


def test_check_track_api_files_fails_for_unattached_dataset(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(track_checks, "_fetch_metadata_dataset_rows", lambda db_session, genome_id: [])

    with pytest.raises(AssertionError, match="not attached"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )


def test_check_track_api_files_optional_release_validation(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label=None)
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
            ),
        ],
    )

    with pytest.raises(AssertionError, match=r"Missing tracks_datasetrelease rows.*@2024-01-01"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config={
                "track_api_files": {
                    **_track_api_config(tmp_path, database_file)["track_api_files"],
                    "check_release_info": True,
                }
            },
            db_session=object(),
        )


def test_check_track_api_files_release_validation_uses_metadata_release_labels(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2025-08-13")
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2025-08-13",
                release_name="I2",
                release_type="partial",
            ),
        ],
    )

    track_checks.check_track_api_files(
        genomes={"genome_uuid": genome_uuid, "release_label": "2025-06-30"},
        automation_resource_config={
            "track_api_files": {
                **_track_api_config(tmp_path, database_file)["track_api_files"],
                "check_release_info": True,
            }
        },
        db_session=object(),
    )


def test_check_track_api_files_release_validation_uses_all_metadata_release_labels(
    monkeypatch, tmp_path
):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2025-08-13")
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    connection = sqlite3.connect(database_file)
    try:
        connection.execute(
            """
            INSERT INTO tracks_datasetrelease (dataset_id, genome_id, release_label)
            VALUES (?, ?, ?)
            """,
            (dataset_uuid.replace("-", ""), genome_uuid.replace("-", ""), "2026-08-25"),
        )
        connection.commit()
    finally:
        connection.close()

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2025-08-13",
                release_name="I2",
                release_type="partial",
            ),
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2026-08-25",
                release_name=29,
                release_type="regular",
            ),
        ],
    )

    track_checks.check_track_api_files(
        genomes={"genome_uuid": genome_uuid, "release_label": "2025-06-30"},
        automation_resource_config={
            "track_api_files": {
                **_track_api_config(tmp_path, database_file)["track_api_files"],
                "check_release_info": True,
            }
        },
        db_session=object(),
    )


def test_check_track_api_files_fails_when_loaded_track_file_is_missing(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2024-01-01")
    genome_dir = _create_track_directory(track_root, genome_uuid, dataset_uuid)
    (genome_dir / f"{dataset_uuid}_gc.bw").unlink()

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
            ),
        ],
    )

    with pytest.raises(AssertionError, match="does not exist"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )


def test_check_track_api_files_allows_track_file_in_another_genome_directory(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    other_genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    source_genome_dir = track_root / other_genome_uuid[:3].lower() / other_genome_uuid
    source_genome_dir.mkdir(parents=True)
    shared_track = source_genome_dir / f"{dataset_uuid}_gc.bw"
    shared_track.touch()
    target_track = track_root / genome_uuid[:3].lower() / genome_uuid / f"{dataset_uuid}_gc.bw"
    target_track.unlink()

    connection = sqlite3.connect(database_file)
    try:
        connection.execute(
            """
            UPDATE tracks_track
            SET datafiles = ?
            WHERE genome_id = ? AND datafiles LIKE ?
            """,
            (
                '{"gc":"%s/%s/%s_gc.bw"}' % (
                    other_genome_uuid[:3].lower(),
                    other_genome_uuid,
                    dataset_uuid,
                ),
                genome_uuid.replace("-", ""),
                '%_gc.bw"}',
            ),
        )
        connection.commit()
    finally:
        connection.close()

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
                release_name="I2",
                release_type="partial",
            ),
        ],
    )

    track_checks.check_track_api_files(
        genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
        automation_resource_config=_track_api_config(tmp_path, database_file),
        db_session=object(),
    )


def test_validate_track_file_content_uses_variation_checks_for_short_variants(monkeypatch, tmp_path):
    calls = []
    target_file = tmp_path / "variant-eva-summary.bw"
    target_file.touch()

    monkeypatch.setattr(
        track_checks,
        "import_module",
        lambda module_name: _DummyValidatorModule(
            lambda path: calls.append(
                ("variation_bw" if module_name.endswith("variation.bigwig") else "generic_bw", path.name)
            )
        ),
    )

    track_checks._validate_track_file_content(target_file, "short_variants")

    assert calls == [("variation_bw", "variant-eva-summary.bw")]


def test_validate_track_file_content_uses_generic_checks_for_core_tracks(monkeypatch, tmp_path):
    calls = []
    target_file = tmp_path / "core-track.bb"
    target_file.touch()

    monkeypatch.setattr(
        track_checks,
        "import_module",
        lambda module_name: _DummyValidatorModule(
            lambda path: calls.append(
                ("generic_bb" if module_name.endswith("checks.bigbed") else "variation_bb", path.name)
            )
        ),
    )

    track_checks._validate_track_file_content(target_file, "core_tracks")

    assert calls == [("generic_bb", "core-track.bb")]


def test_check_track_api_files_fails_for_missing_required_dataset(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="short_variants",
                release_label="2024-01-01",
            ),
        ],
    )

    with pytest.raises(AssertionError, match="Missing required attached dataset types"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )


def test_check_track_api_files_fails_when_attached_short_variants_dataset_has_no_tracks(
    monkeypatch, tmp_path
):
    genome_uuid = str(uuid4())
    core_dataset_uuid = str(uuid4())
    short_variants_dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, core_dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, core_dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=core_dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
            ),
            MetadataRow(
                dataset_uuid=short_variants_dataset_uuid,
                dataset_name="variation_browser_files",
                dataset_type_name="short_variants",
                release_label="2024-01-01",
            ),
        ],
    )

    with pytest.raises(AssertionError, match="Attached optional datasets.*have no Track API tracks"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )


def test_check_track_api_files_fails_when_attached_regulation_tracks_dataset_has_no_tracks(
    monkeypatch, tmp_path
):
    genome_uuid = str(uuid4())
    core_dataset_uuid = str(uuid4())
    regulation_dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, core_dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, core_dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=core_dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
            ),
            MetadataRow(
                dataset_uuid=regulation_dataset_uuid,
                dataset_name="regulation_browser_files",
                dataset_type_name="regulation_tracks",
                release_label="2024-01-01",
            ),
        ],
    )

    with pytest.raises(AssertionError, match="Attached optional datasets.*have no Track API tracks"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )


def test_check_track_api_files_ignores_optional_dataset_attached_from_cutoff_release(
    monkeypatch, tmp_path
):
    genome_uuid = str(uuid4())
    core_dataset_uuid = str(uuid4())
    short_variants_dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, core_dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, core_dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=core_dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
                release_name=28,
            ),
            MetadataRow(
                dataset_uuid=short_variants_dataset_uuid,
                dataset_name="variation_browser_files",
                dataset_type_name="short_variants",
                release_label="2025-01-01",
                release_name=29,
            ),
        ],
    )

    track_checks.check_track_api_files(
        genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
        automation_resource_config={
            "track_api_files": {
                **_track_api_config(tmp_path, database_file)["track_api_files"],
                "ignore_attached_optional_datasets_from_release": 29,
            }
        },
        db_session=object(),
    )


def test_check_track_api_files_ignores_non_partial_optional_dataset(
    monkeypatch, tmp_path
):
    genome_uuid = str(uuid4())
    core_dataset_uuid = str(uuid4())
    short_variants_dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, core_dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, core_dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=core_dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
                release_name=28,
            ),
            MetadataRow(
                dataset_uuid=short_variants_dataset_uuid,
                dataset_name="variation_browser_files",
                dataset_type_name="short_variants",
                release_label="2024-01-01",
                release_name=28,
            ),
        ],
    )

    track_checks.check_track_api_files(
        genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
        automation_resource_config={
            "track_api_files": {
                **_track_api_config(tmp_path, database_file)["track_api_files"],
                "ignore_attached_optional_datasets_from_release": 29,
            }
        },
        db_session=object(),
    )


def test_check_track_api_files_requires_partial_release_optional_dataset(monkeypatch, tmp_path):
    genome_uuid = str(uuid4())
    core_dataset_uuid = str(uuid4())
    short_variants_dataset_uuid = str(uuid4())
    track_root = tmp_path / "release-2024-01-01" / "tracks"
    database_file = track_root / "track_api.sqlite3"
    _create_track_api_db(database_file, genome_uuid, core_dataset_uuid, release_label="2024-01-01")
    _create_track_directory(track_root, genome_uuid, core_dataset_uuid)

    _patch_validators(monkeypatch)
    monkeypatch.setattr(
        track_checks,
        "_fetch_metadata_dataset_rows",
        lambda db_session, genome_id: [
            MetadataRow(
                dataset_uuid=core_dataset_uuid,
                dataset_name="genebuild_browser_files",
                dataset_type_name="core_tracks",
                release_label="2024-01-01",
                release_name=28,
            ),
            MetadataRow(
                dataset_uuid=short_variants_dataset_uuid,
                dataset_name="variation_browser_files",
                dataset_type_name="short_variants",
                release_label="2024-06-01",
                release_name="I2",
                release_type="partial",
            ),
        ],
    )

    with pytest.raises(AssertionError, match="Attached optional datasets.*have no Track API tracks"):
        track_checks.check_track_api_files(
            genomes={"genome_uuid": genome_uuid, "release_label": "2024-01-01"},
            automation_resource_config=_track_api_config(tmp_path, database_file),
            db_session=object(),
        )
