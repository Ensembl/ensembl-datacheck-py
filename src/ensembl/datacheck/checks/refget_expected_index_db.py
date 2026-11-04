#!/usr/bin/env python3
# See the NOTICE file distributed with this work for additional information
# regarding copyright ownership.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Check assembly_sequence and MongoDB MD5 keys separately in refget.

Only explicitly supplied genome UUIDs are tested; no release selection is made.
Standalone: set METADATA_DB_URL and THOAS_MONGO_URI, then run with
--genome-uuid UUID1,UUID2 --mongo-database release_116_5 --index-file indexdb.tkh.
validate_genome_index also accepts automation-style genome records containing
genome_uuid and release_version; the latter only identifies the Mongo database.
Requires SQLAlchemy, a MySQL driver, PyMongo, and either the optional tkrzw
Python binding (preferred) or tkrzw_dbm_util on PATH. All DB access is read-only.
"""

import argparse
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def normalize_genomes(genomes):
    """Accept explicit UUIDs or the genome records used by automation checks."""
    if isinstance(genomes, str):
        genomes = genomes.split(",")
    elif isinstance(genomes, dict):
        genomes = [genomes]
    selected = {}
    for value in genomes or []:
        record = dict(value) if isinstance(value, dict) else {"genome_uuid": value}
        uuid = record.get("genome_uuid")
        if not isinstance(uuid, str) or not uuid.strip():
            raise ValueError("Each genome must have a non-empty genome_uuid.")
        uuid = uuid.strip()
        record["genome_uuid"] = uuid
        previous = selected.get(uuid)
        if previous and previous.get("release_version") != record.get("release_version"):
            raise ValueError(f"Conflicting release_version records for genome {uuid}.")
        selected[uuid] = record
    if not selected:
        raise ValueError("An explicit, non-empty genome UUID list is required; no release selection is performed.")
    return selected


def fetch_assembly_checksums(session, genome_uuids):
    """Fetch all selected genomes' assembly MD5s in one bound metadata query.

    LEFT JOIN preserves unknown genomes and assemblies without sequences so
    either condition fails explicitly. No release or genebuild filters apply.
    """
    selected = normalize_genomes(genome_uuids)
    expected = {uuid: set() for uuid in selected}
    statement = text("""
        SELECT g.genome_uuid, s.assembly_sequence_id, s.md5
        FROM genome AS g
        LEFT JOIN assembly_sequence AS s ON s.assembly_id = g.assembly_id
        WHERE g.genome_uuid IN :genome_uuids
    """).bindparams(bindparam("genome_uuids", expanding=True))
    result = session.execute(
        statement.execution_options(stream_results=True, yield_per=10000),
        {"genome_uuids": sorted(selected)},
    )
    seen = set()
    try:
        for row in result.mappings():
            uuid, checksum = row["genome_uuid"], row["md5"]
            seen.add(uuid)
            if row["assembly_sequence_id"] is None:
                continue
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", checksum):
                raise ValueError(f"Invalid assembly_sequence MD5 for genome {uuid}.")
            expected[uuid].add(checksum.lower())
    finally:
        result.close()
    unknown = sorted(set(selected) - seen)
    if unknown:
        raise ValueError(f"Unknown metadata genome UUIDs: {unknown[:20]}")
    empty = sorted(uuid for uuid, checksums in expected.items() if not checksums)
    if empty:
        raise ValueError(f"No assembly_sequence MD5s found for genomes: {empty[:20]}")
    return expected


MONGO_CHECKSUM_PROJECTIONS = {
    "region": {"_id": 0, "genome_id": 1, "sequence.checksum": 1},
    "protein": {
        "_id": 0, "genome_id": 1,
        "sequence.checksum": 1, "sequence_checksum": 1,
    },
    "transcript": {
        "_id": 0, "genome_id": 1,
        "product_generating_contexts.cds.sequence.checksum": 1,
        "product_generating_contexts.cds.sequence_checksum": 1,
        "product_generating_contexts.cdna.sequence.checksum": 1,
        "product_generating_contexts.cdna.sequence_checksum": 1,
    },
}


def _checksum_values(value):
    """Walk only projected checksum fields, including every product context."""
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"checksum", "sequence_checksum"}:
                yield child
            else:
                yield from _checksum_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _checksum_values(child)


def fetch_mongo_checksums(database, genome_uuids):
    """Bulk-read each sequence collection once for all selected genomes.

    Use indexed genome_id $in filters and project checksums only. Do not transfer
    sequences or query per genome. Deduplicate checksum aliases and shared CDS/
    cDNA/protein sequences. Genomes with no checksums fail rather than pass.
    """
    expected = {uuid: set() for uuid in genome_uuids}
    if not expected:
        raise ValueError("No genome UUIDs selected for MongoDB checksum lookup.")
    query = {"genome_id": {"$in": sorted(expected)}}
    counts = {}
    for collection, projection in MONGO_CHECKSUM_PROJECTIONS.items():
        cursor = database[collection].find(query, projection, batch_size=1000)
        counts[collection] = 0
        try:
            for document in cursor:
                uuid = document.get("genome_id")
                if uuid not in expected:
                    raise ValueError(f"Unexpected genome_id in MongoDB {collection}.")
                counts[collection] += 1
                for checksum in _checksum_values(document):
                    # An unavailable CDS can have a null/empty checksum. Every
                    # non-empty checksum is validated; none are silently lost.
                    if checksum is None or checksum == "":
                        continue
                    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", checksum):
                        raise ValueError(
                            f"Invalid MongoDB MD5 in {collection} for genome {uuid}; "
                            "expected 32 hexadecimal characters."
                        )
                    expected[uuid].add(checksum.lower())
        finally:
            cursor.close()
    empty = sorted(uuid for uuid, values in expected.items() if not values)
    if empty:
        raise ValueError(
            f"No MongoDB sequence checksums found for {len(empty)} selected genomes. "
            f"First 20: {empty[:20]}"
        )
    return expected, counts


def _load_tkrzw():
    """Load the optional Python binding already used by the refget project."""
    return importlib.import_module("tkrzw")


def _missing_index_md5s_python(index_path, expected, tkrzw):
    """Use direct read-only lookups rather than scanning a billion-record file."""
    dbm = tkrzw.DBM()
    status = dbm.Open(str(index_path), False, dbm="HashDBM", no_wait=True)
    if not status.IsOK():
        raise RuntimeError(f"Unable to open refget index {index_path}: {status}")
    missing = []
    try:
        status = tkrzw.Status()
        for md5 in expected:
            dbm.Get(md5, status)
            code = status.GetCode()
            if code == tkrzw.Status.NOT_FOUND_ERROR:
                missing.append(md5)
            elif code != tkrzw.Status.SUCCESS:
                raise RuntimeError(f"Unable to read refget index {index_path}: {status}")
    finally:
        closed = dbm.Close()
        if not closed.IsOK():
            raise RuntimeError(f"Unable to close refget index {index_path}: {closed}")
    return sorted(missing)


def missing_index_md5s(index_file, expected, backend="auto"):
    """Prefer native indexed lookups; retain the CLI scan as a fallback."""
    index_path = Path(index_file).expanduser().resolve()
    if not index_path.is_file():
        raise FileNotFoundError(f"Refget index does not exist: {index_path}")
    if backend not in {"auto", "python", "cli"}:
        raise ValueError("Index backend must be auto, python or cli.")
    if backend != "cli":
        try:
            tkrzw = _load_tkrzw()
        except ModuleNotFoundError as error:
            if error.name != "tkrzw":
                raise
            if backend == "python":
                raise RuntimeError("The Python tkrzw binding is required for index_backend=python.") from error
        else:
            return _missing_index_md5s_python(index_path, expected, tkrzw)
    return _missing_index_md5s_cli(index_path, expected)


def _missing_index_md5s_cli(index_file, expected):
    """Stream every index key once, keeping only the expected MD5 set in memory.

    Refget's indexer writes db[md5] = sha and db[sha] = metadata. Therefore the
    correct presence test is the MD5 key, not a genome UUID or a metadata scan.
    Escape keys so malformed/binary keys cannot create fake lines. Hexadecimal
    MD5 keys are unaffected. Do not infer or add missing leading zeroes.
    """
    index_path = Path(index_file).expanduser().resolve()
    if not index_path.is_file():
        raise FileNotFoundError(f"Refget index does not exist: {index_path}")
    executable = shutil.which("tkrzw_dbm_util")
    if executable is None:
        raise FileNotFoundError("tkrzw_dbm_util is required on PATH.")
    missing = {md5.encode("ascii") for md5 in expected}
    # Request the CLI's full ProcessEach traversal explicitly. For in-place
    # HashDBM files this scans physical records sequentially, avoiding billions
    # of random bucket lookups. This mode may emit values despite --keys, so
    # parse the key from the first TSV column below. Escaping keeps embedded
    # newlines/tabs inside a key/value from corrupting record boundaries.
    command = [
        executable, "list", "--dbm", "hash", "--no_wait", "--escape",
        "--items", str(2**63 - 1), str(index_path),
    ]
    # A temporary stderr file avoids pipe deadlock and unbounded RAM usage.
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors) as process:
            try:
                for line in process.stdout:
                    # Accept key-only output and older CLI key/value output.
                    key = line.rstrip(b"\r\n").split(b"\t", 1)[0]
                    missing.discard(key.lower())
                returncode = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
        if returncode:
            errors.seek(0)
            detail = errors.read(4096).decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Unable to read refget index (exit {returncode}): {detail}"
            )
    return sorted(md5.decode("ascii") for md5 in missing)


def _coverage_report(expected_by_genome, missing):
    expected = set().union(*expected_by_genome.values())
    missing = expected & missing
    genomes = {}
    for uuid, checksums in sorted(expected_by_genome.items()):
        genome_missing = sorted(checksums & missing)
        genomes[uuid] = {
            "expected_md5_count": len(checksums),
            "matched_md5_count": len(checksums) - len(genome_missing),
            "missing_md5_count": len(genome_missing),
            "missing_md5s": genome_missing,
        }
    return {
        "passed": not missing,
        "expected_md5_count": len(expected),
        "matched_md5_count": len(expected) - len(missing),
        "missing_md5_count": len(missing),
        "missing_md5s": sorted(missing),
        "genomes": genomes,
    }


def validate_genome_index(
    session, genome_uuids, index_file, mongo_client=None,
    mongo_database=None, index_backend="auto",
):
    """Report assembly and Mongo coverage independently for explicit genomes.

    Query metadata once and each Mongo collection once per database. Check the
    union against Tkrzw once, then attribute missing keys to each source. Genome
    records may supply release_version as in automation_thoas_mongo_load.py;
    otherwise an explicit Mongo database is required. No release is fetched.
    """
    selected = normalize_genomes(genome_uuids)
    if mongo_client is None:
        raise ValueError("A MongoDB client is required for sequence checksums.")
    groups = {}
    for uuid, record in selected.items():
        database_name = mongo_database
        if not database_name:
            version = record.get("release_version")
            if version is None or str(version).strip() == "":
                raise ValueError("Pass mongo_database or genome records containing release_version.")
            database_name = f"release_{str(version).replace('.', '_')}"
        groups.setdefault(database_name, []).append(uuid)
    assembly = fetch_assembly_checksums(session, list(selected))
    mongo = {}
    counts = {}
    for database_name, uuids in sorted(groups.items()):
        values, counts[database_name] = fetch_mongo_checksums(mongo_client[database_name], uuids)
        mongo.update(values)
    expected = set().union(*assembly.values(), *mongo.values())
    missing = set(missing_index_md5s(index_file, expected, backend=index_backend))
    sources = {
        "assembly_sequence": _coverage_report(assembly, missing),
        "mongodb": _coverage_report(mongo, missing),
    }
    sources["mongodb"]["document_counts"] = counts
    return {
        "passed": all(source["passed"] for source in sources.values()),
        "selected_genome_count": len(selected),
        "genome_uuids": sorted(selected),
        "mongo_databases": sorted(groups),
        "index_backend": index_backend,
        "index_file": str(Path(index_file).expanduser().resolve()),
        "sources": sources,
    }


@pytest.fixture(scope="module")
def refget_index_report(db_session, request, params):
    """Run both sources once for the caller's UUID list, sharing the report."""
    if db_session is None:
        raise ValueError("--database is required for assembly_sequence checksums.")
    genomes = request.config.getoption("genome_uuid")
    normalize_genomes(genomes)  # Never default to a release or all genomes.
    index_file = params.get("index_file")
    if not index_file:
        raise ValueError("Pass --params index_file=/path/to/indexdb.tkh.")
    mongo_uri = params.get("mongo_uri") or os.environ.get("THOAS_MONGO_URI")
    if not mongo_uri:
        raise ValueError("Set THOAS_MONGO_URI or --params mongo_uri=... .")
    with MongoClient(mongo_uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=10000) as client:
        report = validate_genome_index(
            db_session, genomes, index_file, mongo_client=client,
            mongo_database=params.get("mongo_database"),
            index_backend=params.get("index_backend", "auto"),
        )
    if params.get("report"):
        Path(params["report"]).write_text(json.dumps(report, indent=2) + "\n")
    return report


def _assert_source(report, source):
    coverage = report["sources"][source]
    assert coverage["passed"], (
        f"{source}: {coverage['missing_md5_count']} / "
        f"{coverage['expected_md5_count']} MD5s missing from {report['index_file']}. "
        f"First 20: {coverage['missing_md5s'][:20]}"
    )


def check_refget_assembly_sequence_index_db(refget_index_report):
    """Check metadata assembly_sequence MD5 keys independently of MongoDB."""
    _assert_source(refget_index_report, "assembly_sequence")


def check_refget_mongo_index_db(refget_index_report):
    """Check Mongo region/protein/transcript MD5 keys independently."""
    _assert_source(refget_index_report, "mongodb")


def main(argv=None):
    """Exit 0 for complete coverage, 1 for missing MD5s, 2 for setup/read errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.environ.get("METADATA_DB_URL"))
    parser.add_argument("--mongo-uri", default=os.environ.get("THOAS_MONGO_URI"))
    parser.add_argument("--mongo-database", required=True, help="Explicit Mongo database; no release lookup")
    parser.add_argument(
        "--genome-uuid", "--genome_uuid", required=True,
        help="Required comma-separated genome UUID list, as in automation checks",
    )
    parser.add_argument("--index-file", type=Path, required=True)
    parser.add_argument("--index-backend", choices=["auto", "python", "cli"], default="auto")
    parser.add_argument("--report", type=Path, help="Write JSON including all missing MD5s")
    args = parser.parse_args(argv)
    if not args.database:
        parser.error("Set METADATA_DB_URL or pass --database.")
    if not args.mongo_uri:
        parser.error("Set THOAS_MONGO_URI or pass --mongo-uri.")
    engine = None
    try:
        url = make_url(args.database)
        if url.drivername == "mysql":
            url = url.set(drivername="mysql+pymysql")
        connect_args = {"connect_timeout": 10} if url.drivername == "mysql+pymysql" else {}
        engine = create_engine(url, connect_args=connect_args)
        with Session(engine) as session, MongoClient(
            args.mongo_uri, serverSelectionTimeoutMS=15000, connectTimeoutMS=10000,
        ) as client:
            report = validate_genome_index(
                session, args.genome_uuid, args.index_file,
                mongo_client=client, mongo_database=args.mongo_database,
                index_backend=args.index_backend,
            )
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        for name, coverage in report["sources"].items():
            print(
                f"{name}: {coverage['matched_md5_count']} / "
                f"{coverage['expected_md5_count']} MD5s found; "
                f"{coverage['missing_md5_count']} missing."
            )
            for md5 in coverage["missing_md5s"][:20]:
                print(f"{name} missing: {md5}")
            if coverage["missing_md5_count"] > 20:
                print("Only first 20 shown; use --report for the full list.")
        return 0 if report["passed"] else 1
    except PyMongoError as exc:
        print(f"MongoDB checksum query failed ({type(exc).__name__}); check connectivity/authentication/database.", file=sys.stderr)
        return 2
    except SQLAlchemyError as exc:
        # Do not include connection URLs/passwords in error output.
        print(f"Metadata query failed ({type(exc).__name__}); check connectivity/schema.", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
