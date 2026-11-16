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
Check that the homology reference collections match the compara_reference genome groups
in the metadata database.

The collections are the CSV files under ``collections/`` in
https://gitlab.ebi.ac.uk/ensembl-data-teams/homology-reference-collections, read from the
path set in ``compara_reference.path``: one CSV file, or a directory of them. Each file is
named ``<genome_group.name>_<genome_group.label>.csv`` (for example ``2_bacteria.csv``), or
``<label>.csv`` for a collection without a taxonomy ID (``protists.csv``, whose genome
group name is ``protists``). Each row is ``<production_name>,<genome_uuid>``, with no header.

A genome is a current member of a genome group when its genome_group_member row has
is_current = 1 and a release of type 'partial'.

Checks performed:
    - Collection files are well formed: two columns per row and no duplicate genome UUIDs.
    - Every collection has a compara_reference genome group with the same name and label.
    - Every genome UUID in a collection exists in the genome table.
    - Every genome UUID in a collection is a current member of its genome group.
    - No genome group has current members that are not in its collection.
    - No genome is a current member of the same genome group more than once.
    - Every compara_reference genome group with current members has a collection file
      (only when compara_reference.path is a directory).
"""

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pytest
from sqlalchemy import select

from ensembl.production.metadata.api.models import (
    EnsemblRelease,
    Genome,
    GenomeGroup,
    GenomeGroupMember,
)

GROUP_TYPE = "compara_reference"


def group_key(group_name):
    """Return the key used to match genome group names.

    Names are matched case-insensitively, as MySQL compares them with its default collation:
    ``protists.csv`` gives ``protists`` and must match a genome group named ``Protists``.
    """
    return group_name.casefold()


@dataclass
class Collection:
    """A homology reference collection read from one CSV file."""

    file_name: str
    group_name: str
    label: str
    genomes: dict = field(default_factory=dict)  # genome_uuid -> production_name
    problems: list = field(default_factory=list)  # malformed or duplicate rows

    @property
    def group_key(self):
        """Key matching this collection's genome group."""
        return group_key(self.group_name)


@dataclass
class ComparaReferenceContext:
    """Collections and the metadata database state they are compared with.

    Genome groups are keyed by group_key(genome_group.name).
    """

    source: str
    collections: list
    all_collections: bool  # True when every collection file was read (path is a directory)
    group_names: dict  # group key -> genome_group.name as stored in the database
    groups: dict  # group key -> genome_group.label
    members: dict  # group key -> {genome_uuid: production_name}
    member_counts: Counter  # (group key, genome_uuid) -> number of current rows
    existing_genome_uuids: set


def parse_collection_file_name(file_name):
    """Return (genome_group.name, genome_group.label) for a collection file name.

    ``2_bacteria.csv`` gives ("2", "bacteria"); ``protists.csv`` gives ("protists", "protists").
    This matches how cicd/generate_sql_patch.py names genome groups.
    """
    stem = PurePosixPath(file_name).stem
    if "_" in stem:
        group_name, label = stem.split("_", 1)
    else:
        group_name = label = stem
    return group_name, label


def parse_collection(file_name, content):
    """Parse the content of a headerless ``<production_name>,<genome_uuid>`` collection file."""
    group_name, label = parse_collection_file_name(file_name)
    collection = Collection(file_name=file_name, group_name=group_name, label=label)
    for line_number, row in enumerate(csv.reader(content.splitlines()), start=1):
        cells = [cell.strip() for cell in row]
        if not any(cells):
            continue
        if len(cells) != 2 or not all(cells):
            collection.problems.append(
                f"{file_name}:{line_number}: expected '<production_name>,<genome_uuid>', "
                f"found {','.join(row)!r}"
            )
            continue
        production_name, genome_uuid = cells
        if genome_uuid in collection.genomes:
            collection.problems.append(
                f"{file_name}:{line_number}: duplicate genome UUID {genome_uuid}"
            )
            continue
        collection.genomes[genome_uuid] = production_name
    return collection


def load_collections(collections_path):
    """Read one CSV collection file, or every CSV collection file in a directory.

    Returns:
        A (collections, all_collections) tuple. all_collections is True when a directory
        was read, so genome groups without a file in it can be reported.
    """
    assert collections_path, (
        "Set compara_reference.path to a collection CSV file or a directory of them, "
        "for example --params compara_reference.path=/path/to/collections"
    )
    path = Path(collections_path).expanduser()
    if path.is_dir():
        files = sorted(path.glob("*.csv"))
        assert files, f"No collection CSV files found in {path}"
        return [parse_collection(file.name, file.read_text()) for file in files], True

    assert path.is_file(), f"Homology reference collection path does not exist: {path}"
    assert path.suffix == ".csv", f"Homology reference collection file is not a CSV file: {path}"
    return [parse_collection(path.name, path.read_text())], False


def fetch_compara_reference_groups(db_session):
    """Return {genome_group.name: genome_group.label} for every compara_reference genome group."""
    rows = db_session.execute(
        select(GenomeGroup.name, GenomeGroup.label).where(GenomeGroup.type == GROUP_TYPE)
    ).all()
    return {name: label for name, label in rows}


def fetch_current_group_members(db_session):
    """Return (genome_group.name, genome_uuid, production_name) for every current member row.

    A genome listed twice in a group is returned twice.
    """
    statement = (
        select(GenomeGroup.name, Genome.genome_uuid, Genome.production_name)
        .join(GenomeGroupMember, GenomeGroupMember.genome_group_id == GenomeGroup.genome_group_id)
        .join(Genome, Genome.genome_id == GenomeGroupMember.genome_id)
        .join(EnsemblRelease, EnsemblRelease.release_id == GenomeGroupMember.release_id)
        .where(
            GenomeGroup.type == GROUP_TYPE,
            GenomeGroupMember.is_current == 1,
            EnsemblRelease.release_type == "partial",
        )
    )
    return [tuple(row) for row in db_session.execute(statement).all()]


def fetch_existing_genome_uuids(db_session, genome_uuids):
    """Return the subset of genome_uuids present in the genome table."""
    if not genome_uuids:
        return set()
    rows = db_session.execute(
        select(Genome.genome_uuid).where(Genome.genome_uuid.in_(sorted(genome_uuids)))
    ).scalars()
    return set(rows)


def build_context(source, collections, db_session, all_collections=True):
    """Query the metadata database and combine it with the loaded collections."""
    assert db_session is not None, (
        "Missing --database for compara_reference. Provide a metadata database URL with --database."
    )
    db_groups = fetch_compara_reference_groups(db_session)
    member_rows = fetch_current_group_members(db_session)
    members = {}
    for group_name, genome_uuid, production_name in member_rows:
        members.setdefault(group_key(group_name), {})[genome_uuid] = production_name
    collection_uuids = {uuid for collection in collections for uuid in collection.genomes}
    return ComparaReferenceContext(
        source=source,
        collections=collections,
        all_collections=all_collections,
        group_names={group_key(name): name for name in db_groups},
        groups={group_key(name): label for name, label in db_groups.items()},
        members=members,
        member_counts=Counter((group_key(group_name), uuid) for group_name, uuid, _ in member_rows),
        existing_genome_uuids=fetch_existing_genome_uuids(db_session, collection_uuids),
    )


def _assert_no_discrepancies(label, source, items):
    """Fail with a one-line count followed by the full discrepancy list."""
    if not items:
        return
    raise AssertionError(
        "\n".join([f"{label}: {len(items)}. Collections: {source}", "Full list:", *items])
    )


def _collections_with_group(context):
    """Yield the collections whose genome group exists in the metadata database."""
    return (collection for collection in context.collections if collection.group_key in context.groups)


@pytest.fixture(scope="session")
def compara_reference_context(compara_reference_resource, db_session):
    """Load the collections and the compara_reference genome groups once per session."""
    collections_path = compara_reference_resource.get("path")
    collections, all_collections = load_collections(collections_path)
    return build_context(
        str(Path(collections_path).expanduser()), collections, db_session, all_collections=all_collections
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_collection_files_are_valid(compara_reference_context):
    """Check every collection row is '<production_name>,<genome_uuid>' with no duplicate UUIDs."""
    _assert_no_discrepancies(
        label="Malformed collection rows",
        source=compara_reference_context.source,
        items=[problem for collection in compara_reference_context.collections for problem in collection.problems],
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_collections_have_genome_group(compara_reference_context):
    """Check every collection has a compara_reference genome group with the same name and label.

    Names and labels are compared case-insensitively.
    """
    items = []
    for collection in compara_reference_context.collections:
        db_label = compara_reference_context.groups.get(collection.group_key)
        if db_label is None:
            items.append(
                f"{collection.file_name}: no {GROUP_TYPE} genome group with name '{collection.group_name}'"
            )
        elif db_label.casefold() != collection.label.casefold():
            items.append(
                f"{collection.file_name}: genome group "
                f"'{compara_reference_context.group_names[collection.group_key]}' has label "
                f"'{db_label}', expected '{collection.label}'"
            )
    _assert_no_discrepancies(
        label="Collections without a matching genome group",
        source=compara_reference_context.source,
        items=items,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_genomes_exist(compara_reference_context):
    """Check every genome UUID in a collection exists in the genome table."""
    items = [
        f"{collection.file_name}: {genome_uuid} ({production_name})"
        for collection in compara_reference_context.collections
        for genome_uuid, production_name in collection.genomes.items()
        if genome_uuid not in compara_reference_context.existing_genome_uuids
    ]
    _assert_no_discrepancies(
        label="Genome UUIDs not found in the metadata database",
        source=compara_reference_context.source,
        items=items,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_missing_group_members(compara_reference_context):
    """Check every genome UUID in a collection is a current member of its genome group.

    Collections without a genome group are reported by
    check_compara_reference_collections_have_genome_group instead.
    """
    items = []
    for collection in _collections_with_group(compara_reference_context):
        current = compara_reference_context.members.get(collection.group_key, {})
        items.extend(
            f"{collection.file_name}: {genome_uuid} ({production_name})"
            for genome_uuid, production_name in collection.genomes.items()
            if genome_uuid not in current
        )
    _assert_no_discrepancies(
        label="Collection genomes that are not current genome group members",
        source=compara_reference_context.source,
        items=items,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_extra_group_members(compara_reference_context):
    """Check no genome group has current members that are missing from its collection."""
    items = []
    for collection in _collections_with_group(compara_reference_context):
        current = compara_reference_context.members.get(collection.group_key, {})
        items.extend(
            f"{collection.file_name}: {genome_uuid} ({production_name})"
            for genome_uuid, production_name in sorted(current.items())
            if genome_uuid not in collection.genomes
        )
    _assert_no_discrepancies(
        label="Current genome group members that are not in the collection",
        source=compara_reference_context.source,
        items=items,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_duplicate_group_members(compara_reference_context):
    """Check no genome is a current member of the same genome group more than once."""
    items = [
        f"genome group '{compara_reference_context.group_names[key]}': {genome_uuid} has {count} current rows"
        for (key, genome_uuid), count in sorted(compara_reference_context.member_counts.items())
        if count > 1
    ]
    _assert_no_discrepancies(
        label="Duplicate current genome group members",
        source=compara_reference_context.source,
        items=items,
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("compara_reference")
def check_compara_reference_groups_have_collection(compara_reference_context):
    """Check every compara_reference genome group with current members has a collection file.

    Skipped when compara_reference.path is a single file, since the other groups' files were not read.
    """
    if not compara_reference_context.all_collections:
        pytest.skip("compara_reference.path is a single collection file, not a directory of them")
    collection_groups = {collection.group_key for collection in compara_reference_context.collections}
    items = [
        f"genome group '{compara_reference_context.group_names[key]}' "
        f"({compara_reference_context.groups[key]}) has {len(members)} current members"
        for key, members in sorted(compara_reference_context.members.items())
        if key not in collection_groups
    ]
    _assert_no_discrepancies(
        label="Genome groups without a collection file",
        source=compara_reference_context.source,
        items=items,
    )
