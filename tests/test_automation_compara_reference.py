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

"""Unit tests for the compara_reference homology reference collection checks."""

import shutil
import sqlite3
import warnings
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
from ensembl.datacheck.checks.automation import conftest as automation_conftest
from ensembl.datacheck.checks.automation.compara_reference import (
    homology_reference_collections as hrc,
)

METADATA_DB = Path(__file__).parent / "database" / "ensembl_genome_metadata.db"

# Genomes and releases present in the test metadata database
ECOLI = ("escherichia_coli_str_k_12_substr_mg1655", "a73351f7-93e7-11ec-a39d-005056b38ce3", 1)
PLASMODIUM = ("plasmodium_falciparum", "a73356e1-93e7-11ec-a39d-005056b38ce3", 12)
YEAST = ("saccharomyces_cerevisiae", "a733574a-93e7-11ec-a39d-005056b38ce3", 201)
WORM = ("caenorhabditis_elegans", "a733550b-93e7-11ec-a39d-005056b38ce3", 203)
# Only in releases that are not Released or Archived
UNRELEASED = ("homo_sapiens_gca018469875v1", "75b7ac15-6373-4ad5-9fb7-23813a5355a4", 6)
PARTIAL_RELEASE_ID = 1
INTEGRATED_RELEASE_ID = 7
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"


def _csv(*genomes):
    return "".join(f"{production_name},{genome_uuid}\n" for production_name, genome_uuid, *_ in genomes)


@pytest.fixture
def metadata_db(tmp_path):
    """Copy the test metadata database and add compara_reference genome groups to it.

    Groups:
        2 / Bacteria: E. coli current, worm current but not in the collection.
        Protists / Protists (named as in production, matched to protists.csv case-insensitively): Plasmodium current twice, yeast only in an integrated release.
        9999 / Orphan: E. coli current, no collection file.
        7742 / Vertebrata: structural_variant type, must be ignored.
    """
    db_path = tmp_path / "metadata.db"
    shutil.copy(METADATA_DB, db_path)
    with sqlite3.connect(db_path) as connection:
        # The shared fixture contains production-like compara_reference groups.
        # This unit-test fixture defines its own complete compara_reference state.
        connection.execute(
            "DELETE FROM genome_group_member WHERE genome_group_id IN "
            "(SELECT genome_group_id FROM genome_group WHERE type = 'compara_reference')"
        )
        connection.execute("DELETE FROM genome_group WHERE type = 'compara_reference'")

        # Allocate IDs above the remaining rows so future fixture additions do
        # not collide with this test data.
        first_group_id = connection.execute(
            "SELECT COALESCE(MAX(genome_group_id), 0) + 1 FROM genome_group"
        ).fetchone()[0]
        bacteria_group_id, protists_group_id, orphan_group_id, ignored_group_id = range(
            first_group_id, first_group_id + 4
        )
        connection.executemany(
            "INSERT INTO genome_group (genome_group_id, type, name, label, searchable, genome_group_uuid) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            [
                (bacteria_group_id, "compara_reference", "2", "Bacteria", "00000000-0000-0000-0000-00000000gg01"),
                (protists_group_id, "compara_reference", "Protists", "Protists", "00000000-0000-0000-0000-00000000gg02"),
                (orphan_group_id, "compara_reference", "9999", "Orphan", "00000000-0000-0000-0000-00000000gg03"),
                (ignored_group_id, "structural_variant", "7742", "Vertebrata", "00000000-0000-0000-0000-00000000gg04"),
            ],
        )
        connection.executemany(
            "INSERT INTO genome_group_member (is_reference, genome_id, genome_group_id, release_id, is_current) "
            "VALUES (0, ?, ?, ?, ?)",
            [
                (ECOLI[2], bacteria_group_id, PARTIAL_RELEASE_ID, 1),
                (WORM[2], bacteria_group_id, PARTIAL_RELEASE_ID, 1),
                (YEAST[2], bacteria_group_id, PARTIAL_RELEASE_ID, 0),  # dropped member
                (PLASMODIUM[2], protists_group_id, PARTIAL_RELEASE_ID, 1),
                (PLASMODIUM[2], protists_group_id, PARTIAL_RELEASE_ID, 1),  # duplicate
                (YEAST[2], protists_group_id, INTEGRATED_RELEASE_ID, 1),  # not a partial release
                (ECOLI[2], orphan_group_id, PARTIAL_RELEASE_ID, 1),
                (WORM[2], ignored_group_id, PARTIAL_RELEASE_ID, 1),
            ],
        )
    return db_path


@pytest.fixture
def db_session(metadata_db):
    with Session(create_engine(f"sqlite:///{metadata_db}")) as session:
        yield session


@pytest.fixture
def collections_dir(tmp_path):
    """Write collection files matching the metadata_db fixture."""
    path = tmp_path / "collections"
    path.mkdir()
    (path / "2_bacteria.csv").write_text(_csv(ECOLI))
    (path / "protists.csv").write_text(_csv(PLASMODIUM, YEAST, ("unknown_genome", UNKNOWN_UUID)))
    (path / "33208_metazoa.csv").write_text(_csv(WORM))
    (path / "2_bacteria.tsv").write_text("ignored\n")
    return path


@pytest.fixture
def context(collections_dir, db_session):
    collections, all_collections = hrc.load_collections(str(collections_dir))
    return hrc.build_context(str(collections_dir), collections, db_session, all_collections=all_collections)


def _failure_lines(check, context):
    with pytest.raises(AssertionError) as exc_info:
        check(context)
    return str(exc_info.value).splitlines()


@pytest.mark.parametrize(
    "file_name, expected",
    [
        ("2_bacteria.csv", ("2", "bacteria")),
        ("40674_mammalia.csv", ("40674", "mammalia")),
        ("protists.csv", ("protists", "protists")),
        ("collections/7742_vertebrata.csv", ("7742", "vertebrata")),
    ],
)
def test_parse_collection_file_name(file_name, expected):
    assert hrc.parse_collection_file_name(file_name) == expected


def test_parse_collection_reads_rows_and_reports_problems():
    collection = hrc.parse_collection(
        "2_bacteria.csv",
        "ecoli, uuid-1\n\nbad_row\necoli_again,uuid-1\nno_uuid,\nother,uuid-2\n",
    )

    assert collection.group_name == "2"
    assert collection.label == "bacteria"
    assert collection.genomes == {"uuid-1": "ecoli", "uuid-2": "other"}
    assert collection.problems == [
        "2_bacteria.csv:3: expected '<production_name>,<genome_uuid>', found 'bad_row'",
        "2_bacteria.csv:4: duplicate genome UUID uuid-1",
        "2_bacteria.csv:5: expected '<production_name>,<genome_uuid>', found 'no_uuid,'",
    ]


def test_load_collections_reads_only_csv_files_in_directory(collections_dir):
    collections, all_collections = hrc.load_collections(str(collections_dir))

    assert all_collections is True
    assert [collection.file_name for collection in collections] == [
        "2_bacteria.csv",
        "33208_metazoa.csv",
        "protists.csv",
    ]


def test_load_collections_reads_single_file(collections_dir):
    collections, all_collections = hrc.load_collections(str(collections_dir / "2_bacteria.csv"))

    assert all_collections is False
    assert [collection.file_name for collection in collections] == ["2_bacteria.csv"]
    assert collections[0].genomes == {ECOLI[1]: ECOLI[0]}


@pytest.mark.parametrize("path", [None, ""])
def test_load_collections_requires_path(path):
    with pytest.raises(AssertionError, match="Set compara_reference.path"):
        hrc.load_collections(path)


def test_load_collections_requires_existing_path(tmp_path):
    with pytest.raises(AssertionError, match="path does not exist"):
        hrc.load_collections(str(tmp_path / "missing.csv"))


def test_load_collections_rejects_non_csv_file(collections_dir):
    with pytest.raises(AssertionError, match="not a CSV file"):
        hrc.load_collections(str(collections_dir / "2_bacteria.tsv"))


def test_load_collections_requires_csv_files_in_directory(tmp_path):
    with pytest.raises(AssertionError, match="No collection CSV files"):
        hrc.load_collections(str(tmp_path))


def test_build_context_requires_database():
    with pytest.raises(AssertionError, match="Missing --database"):
        hrc.build_context("source", [], None)


def test_build_context_reads_current_partial_members(context):
    assert context.groups == {"2": "Bacteria", "protists": "Protists", "9999": "Orphan"}
    assert context.members == {
        "2": {ECOLI[1]: ECOLI[0], WORM[1]: WORM[0]},
        "protists": {PLASMODIUM[1]: PLASMODIUM[0]},
        "9999": {ECOLI[1]: ECOLI[0]},
    }
    assert context.member_counts[("protists", PLASMODIUM[1])] == 2
    assert context.group_names["protists"] == "Protists"
    assert UNKNOWN_UUID not in context.genomes
    assert context.genomes[ECOLI[1]] == hrc.GenomeInfo(ECOLI[0], False, None)
    assert context.released_genome_uuids == {ECOLI[1], PLASMODIUM[1], YEAST[1], WORM[1]}


def test_protists_collection_matches_capitalised_group_name(context):
    """protists.csv must match the genome group named 'Protists' in the database."""
    hrc.check_compara_reference_collection_files_are_valid(context)
    lines = _failure_lines(hrc.check_compara_reference_groups_have_collection, context)

    assert not any("Protists" in line for line in lines)
    assert [line for line in lines[2:] if "protists" in line.casefold()] == []


def test_check_collection_files_are_valid_passes(context):
    hrc.check_compara_reference_collection_files_are_valid(context)


def test_check_collection_files_are_valid_fails(context):
    context.collections[0].problems.append("2_bacteria.csv:2: duplicate genome UUID x")

    lines = _failure_lines(hrc.check_compara_reference_collection_files_are_valid, context)

    assert lines[0].startswith("Malformed collection rows: 1. Collections: ")
    assert lines[1:] == ["Full list:", "2_bacteria.csv:2: duplicate genome UUID x"]


def test_check_collections_have_genome_group(context):
    lines = _failure_lines(hrc.check_compara_reference_collections_have_genome_group, context)

    assert lines[0].startswith("Collections without a matching genome group: 1.")
    assert lines[2:] == ["33208_metazoa.csv: no compara_reference genome group with name '33208'"]


def test_check_collections_have_genome_group_reports_label_mismatch(context):
    context.groups["2"] = "Archaea"

    lines = _failure_lines(hrc.check_compara_reference_collections_have_genome_group, context)

    assert "2_bacteria.csv: genome group '2' has label 'Archaea', expected 'bacteria'" in lines


def test_check_genomes_exist(context):
    lines = _failure_lines(hrc.check_compara_reference_genomes_exist, context)

    assert lines[2:] == [f"protists.csv: {UNKNOWN_UUID} (unknown_genome)"]


def test_check_missing_group_members(context):
    lines = _failure_lines(hrc.check_compara_reference_missing_group_members, context)

    # Yeast is only current in an integrated release; metazoa has no group and is not repeated here
    assert lines[2:] == [
        f"protists.csv: {YEAST[1]} ({YEAST[0]})",
        f"protists.csv: {UNKNOWN_UUID} (unknown_genome)",
    ]


def test_check_extra_group_members(context):
    lines = _failure_lines(hrc.check_compara_reference_extra_group_members, context)

    assert lines[2:] == [f"2_bacteria.csv: {WORM[1]} ({WORM[0]})"]


def test_check_duplicate_group_members(context):
    lines = _failure_lines(hrc.check_compara_reference_duplicate_group_members, context)

    assert lines[2:] == [f"genome group 'Protists': {PLASMODIUM[1]} has 2 current rows"]


def test_check_groups_have_collection(context):
    lines = _failure_lines(hrc.check_compara_reference_groups_have_collection, context)

    assert lines[2:] == ["genome group '9999' (Orphan) has 1 current members"]


def test_check_groups_have_collection_skipped_for_single_file(collections_dir, db_session):
    collections, all_collections = hrc.load_collections(str(collections_dir / "2_bacteria.csv"))
    context = hrc.build_context("2_bacteria.csv", collections, db_session, all_collections=all_collections)

    with pytest.raises(pytest.skip.Exception, match="single collection file"):
        hrc.check_compara_reference_groups_have_collection(context)


def test_duplicate_members_single_file_only_checks_its_own_group(collections_dir, db_session):
    """Protists has a duplicate member, which must not fail a run on 2_bacteria.csv alone."""
    bacteria, _ = hrc.load_collections(str(collections_dir / "2_bacteria.csv"))
    hrc.check_compara_reference_duplicate_group_members(
        hrc.build_context("2_bacteria.csv", bacteria, db_session, all_collections=False)
    )

    protists, _ = hrc.load_collections(str(collections_dir / "protists.csv"))
    context = hrc.build_context("protists.csv", protists, db_session, all_collections=False)
    lines = _failure_lines(hrc.check_compara_reference_duplicate_group_members, context)
    assert lines[2:] == [f"genome group 'Protists': {PLASMODIUM[1]} has 2 current rows"]


def test_single_file_only_compares_its_own_group(collections_dir, db_session):
    collections, all_collections = hrc.load_collections(str(collections_dir / "2_bacteria.csv"))
    context = hrc.build_context("2_bacteria.csv", collections, db_session, all_collections=all_collections)

    hrc.check_compara_reference_missing_group_members(context)
    lines = _failure_lines(hrc.check_compara_reference_extra_group_members, context)
    assert lines[2:] == [f"2_bacteria.csv: {WORM[1]} ({WORM[0]})"]


def test_checks_pass_when_collections_match(tmp_path, db_session):
    collections_dir = tmp_path / "matching"
    collections_dir.mkdir()
    (collections_dir / "2_bacteria.csv").write_text(_csv(ECOLI, WORM))
    (collections_dir / "9999_orphan.csv").write_text(_csv(ECOLI))
    (collections_dir / "protists.csv").write_text(_csv(PLASMODIUM))
    collections, all_collections = hrc.load_collections(str(collections_dir))
    context = hrc.build_context(str(collections_dir), collections, db_session, all_collections=all_collections)

    hrc.check_compara_reference_collection_files_are_valid(context)
    hrc.check_compara_reference_collections_have_genome_group(context)
    hrc.check_compara_reference_genomes_exist(context)
    hrc.check_compara_reference_genomes_not_suppressed(context)
    hrc.check_compara_reference_genomes_released(context)
    hrc.check_compara_reference_missing_group_members(context)
    hrc.check_compara_reference_extra_group_members(context)
    hrc.check_compara_reference_groups_have_collection(context)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        hrc.check_compara_reference_production_names(context)


def _context_for(tmp_path, db_session, csv_content, file_name="2_bacteria.csv"):
    collections_dir = tmp_path / "single"
    collections_dir.mkdir()
    (collections_dir / file_name).write_text(csv_content)
    collections, all_collections = hrc.load_collections(str(collections_dir))
    return hrc.build_context(str(collections_dir), collections, db_session, all_collections=all_collections)


def test_check_genomes_not_suppressed(tmp_path, metadata_db):
    with sqlite3.connect(metadata_db) as connection:
        connection.execute(
            "UPDATE genome SET suppressed = 1, suppression_details = 'Replaced by a newer assembly' "
            "WHERE genome_id = ?",
            (WORM[2],),
        )
    with Session(create_engine(f"sqlite:///{metadata_db}")) as session:
        context = _context_for(tmp_path, session, _csv(ECOLI, WORM, ("unknown_genome", UNKNOWN_UUID)))

        lines = _failure_lines(hrc.check_compara_reference_genomes_not_suppressed, context)

    assert lines[0].startswith("Suppressed genomes in collections: 1.")
    assert lines[2:] == [f"2_bacteria.csv: {WORM[1]} ({WORM[0]}): Replaced by a newer assembly"]


def test_check_genomes_released(tmp_path, db_session):
    context = _context_for(tmp_path, db_session, _csv(ECOLI, UNRELEASED, ("unknown_genome", UNKNOWN_UUID)))

    lines = _failure_lines(hrc.check_compara_reference_genomes_released, context)

    # The unknown UUID is reported by check_compara_reference_genomes_exist, not here
    assert lines[0].startswith("Collection genomes that have not been released: 1.")
    assert lines[2:] == [f"2_bacteria.csv: {UNRELEASED[1]} ({UNRELEASED[0]})"]


def test_check_production_names_warns_without_failing(tmp_path, db_session):
    context = _context_for(tmp_path, db_session, _csv(("escherichia_coli", ECOLI[1]), WORM))

    with pytest.warns(EnsemblDatacheckWarning) as records:
        hrc.check_compara_reference_production_names(context)

    # EnsemblDatacheckWarning prefixes the message with "Warning::<file>::<function>: "
    message_lines = str(records[0].message).splitlines()
    assert "Collection production names that differ from the metadata DB: 1." in message_lines[0]
    assert message_lines[1:] == [
        f"2_bacteria.csv: {ECOLI[1]} CSV 'escherichia_coli', metadata DB '{ECOLI[0]}'"
    ]


def test_bundled_config_has_compara_reference_section():
    config = automation_conftest._build_automation_resource_config(
        config_path=None, environ={}, raw_params=[]
    )

    assert config["compara_reference"] == {"ignore": "False", "path": ""}


def test_compara_reference_path_overrides():
    from_params = automation_conftest._build_automation_resource_config(
        config_path=None, environ={}, raw_params=["compara_reference.path=/data/collections"]
    )
    from_env = automation_conftest._build_automation_resource_config(
        config_path=None,
        environ={"ENSEMBL_DATACHECK_COMPARA_REFERENCE__PATH": "/data/2_bacteria.csv"},
        raw_params=[],
    )

    assert from_params["compara_reference"]["path"] == "/data/collections"
    assert from_env["compara_reference"]["path"] == "/data/2_bacteria.csv"
