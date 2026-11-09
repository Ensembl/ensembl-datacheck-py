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

"""Regression tests for one-query metadata selection and Tkrzw coverage."""

import json
import sys
from types import SimpleNamespace
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, event, text
from pymongo.errors import OperationFailure
from sqlalchemy.orm import Session

from ensembl.datacheck.checks import refget_expected_index_db as checks

MD5_A = "3099a81e4164ced9510c2e5ec0117007"
MD5_B = "21dfe5b38ad3946803ccaed6639146b8"
MD5_OTHER = "6e16c4b00bf0c104ddc4abe4bae08f3d"


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs
        self.closed = False
    def __iter__(self):
        return iter(self.docs)
    def close(self):
        self.closed = True


class FakeDatabase:
    def __init__(self):
        self.calls = []
        self.cursors = []
        self.documents = {
            "region": [{"genome_id": uuid, "sequence": {"checksum": MD5_A}} for uuid in ["genome-2", "genome-3"]],
            "protein": [{"genome_id": uuid, "sequence": {"checksum": MD5_B}, "sequence_checksum": MD5_B} for uuid in ["genome-2", "genome-3"]],
            "transcript": [{"genome_id": uuid, "product_generating_contexts": [
                {"cds": {"sequence": {"checksum": MD5_A}, "sequence_checksum": MD5_A},
                 "cdna": {"sequence": {"checksum": MD5_B}, "sequence_checksum": MD5_B}}
            ]} for uuid in ["genome-2", "genome-3"]],
        }
    def __getitem__(self, collection):
        def find(query, projection, batch_size):
            self.calls.append((collection, deepcopy(query), dict(projection), batch_size))
            cursor = FakeCursor([doc for doc in self.documents[collection] if doc["genome_id"] in query["genome_id"]["$in"]])
            self.cursors.append(cursor)
            return cursor
        return SimpleNamespace(find=find)


class FakeMongoClient:
    def __init__(self):
        self.database = FakeDatabase()
        self.names = []
        self.closed = False
    def __getitem__(self, name):
        self.names.append(name)
        return self.database
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_mongo(monkeypatch):
    client = FakeMongoClient()
    monkeypatch.setattr(checks, "MongoClient", lambda *args, **kwargs: client)
    monkeypatch.setenv("THOAS_MONGO_URI", "mongodb://test.invalid")
    return client


@pytest.fixture
def metadata_session():
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        for ddl in (
            "CREATE TABLE ensembl_release (release_id INTEGER, name TEXT, version NUMERIC, release_date TEXT, status TEXT, site_id INTEGER, release_type TEXT)",
            "CREATE TABLE genome (genome_id INTEGER, assembly_id INTEGER, genome_uuid TEXT, organism_id INTEGER)",
            "CREATE TABLE genome_release (genome_id INTEGER, release_id INTEGER)",
            "CREATE TABLE assembly (assembly_id INTEGER)",
            "CREATE TABLE organism (organism_id INTEGER)",
            "CREATE TABLE genome_dataset (genome_id INTEGER, dataset_id INTEGER, release_id INTEGER)",
            "CREATE TABLE dataset (dataset_id INTEGER, name TEXT, dataset_type_id INTEGER, dataset_source_id INTEGER)",
            "CREATE TABLE dataset_type (dataset_type_id INTEGER, name TEXT)",
            "CREATE TABLE dataset_source (dataset_source_id INTEGER)",
            "CREATE TABLE assembly_sequence (assembly_sequence_id INTEGER, assembly_id INTEGER, md5 TEXT)",
        ):
            session.execute(text(ddl))
        session.execute(text("""
            INSERT INTO ensembl_release VALUES
            (1, '29', 116.4, '2026-08-25', 'Released', 1, 'partial'),
            (2, '30', 116.5, '2026-09-22', 'Released', 1, 'partial'),
            (3, '31', 116.6, '2026-10-20', 'Preparing', 1, 'partial'),
            (4, '99', 999, '2026-10-21', 'Released', 2, 'partial'),
            (5, 'I1', 1, '2026-07-01', 'Released', 1, 'integrated')
        """))
        for sql in (
            "INSERT INTO genome VALUES (1, 10, 'genome-1', 1), (2, 20, 'genome-2', 1), (3, 20, 'genome-3', 1), (4, 30, 'genome-4', 1)",
            "INSERT INTO genome_release VALUES (1, 1), (2, 2), (3, 2), (4, 2)",
            "INSERT INTO assembly VALUES (10), (20), (30)",
            "INSERT INTO organism VALUES (1)",
            "INSERT INTO genome_dataset VALUES (1, 1, 1), (2, 1, 2), (3, 1, 2), (4, 2, 2)",
            "INSERT INTO dataset VALUES (1, 'genebuild', 1, 1), (2, 'other', 1, 1)",
            "INSERT INTO dataset_type VALUES (1, 'genebuild')",
            "INSERT INTO dataset_source VALUES (1)",
        ):
            session.execute(text(sql))
        session.execute(text("INSERT INTO assembly_sequence VALUES (1, 10, :other), (2, 20, :a), (3, 20, :b), (4, 20, :a), (5, 30, :other)"),
                        {"a": MD5_A, "b": MD5_B, "other": MD5_OTHER})
        yield session
    engine.dispose()


@pytest.fixture
def fake_index(tmp_path, monkeypatch):
    """Exercise a real child process without requiring the Tkrzw installation."""
    def no_python_binding():
        raise ModuleNotFoundError("tkrzw missing", name="tkrzw")
    monkeypatch.setattr(checks, "_load_tkrzw", no_python_binding)
    index = tmp_path / "indexdb.tkh"
    index.touch()
    output = tmp_path / "keys.txt"
    output.write_text(MD5_A + "\n" + MD5_B + "\n")
    executable = tmp_path / "tkrzw_dbm_util"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "assert sys.argv[1] == 'list'\n"
        "assert '--escape' in sys.argv\n"
        "assert '--no_wait' in sys.argv\n"
        "assert int(sys.argv[sys.argv.index('--items') + 1]) == 2**63 - 1\n"
        "sys.stdout.buffer.write(pathlib.Path(os.environ['FAKE_KEYS']).read_bytes())\n"
        "sys.stderr.write('injected index read error')\n"
        "sys.exit(int(os.environ.get('FAKE_RETURN_CODE', '0')))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("FAKE_KEYS", str(output))
    monkeypatch.setattr(checks.shutil, "which", lambda _: str(executable))
    return index, output


def test_explicit_uuid_query_once_without_release_filters(metadata_session):
    statements = []
    engine = metadata_session.get_bind()
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = checks.fetch_assembly_checksums(metadata_session, ["genome-1", "genome-2", "genome-4"])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result == {"genome-1": {MD5_OTHER}, "genome-2": {MD5_A, MD5_B}, "genome-4": {MD5_OTHER}}
    assert len(statements) == 1
    assert "assembly_sequence" in statements[0]
    assert "release" not in statements[0]
    assert "dataset" not in statements[0]


@pytest.mark.parametrize("values", [None, [], "", [" "], [{"genome_uuid": None}]])
def test_explicit_nonempty_selection_required(values):
    with pytest.raises(ValueError):
        checks.normalize_genomes(values)


def test_unknown_uuid_does_not_silently_disappear(metadata_session):
    with pytest.raises(ValueError, match="Unknown metadata genome UUIDs"):
        checks.fetch_assembly_checksums(metadata_session, ["genome-2", "x') OR 1=1 --"])


@pytest.mark.parametrize("bad", [None, "", "not-md5", 123])
def test_invalid_assembly_md5_fails(metadata_session, bad):
    metadata_session.execute(text("UPDATE assembly_sequence SET md5=:bad WHERE assembly_sequence_id=2"), {"bad": bad})
    with pytest.raises(ValueError, match="Invalid assembly_sequence MD5"):
        checks.fetch_assembly_checksums(metadata_session, ["genome-2"])


def test_missing_assembly_sequences_fail(metadata_session):
    metadata_session.execute(text("DELETE FROM assembly_sequence WHERE assembly_id=20"))
    with pytest.raises(ValueError, match="No assembly_sequence MD5s"):
        checks.fetch_assembly_checksums(metadata_session, ["genome-2"])


def validate(session, index, client, **kwargs):
    kwargs.setdefault("mongo_database", "release_116_5")
    return checks.validate_genome_index(session, ["genome-2", "genome-3"], index, mongo_client=client, **kwargs)


def test_both_sources_report_separately_with_one_index_pass(metadata_session, fake_index, fake_mongo, monkeypatch):
    index, _ = fake_index
    fake_mongo.database.documents["protein"][0]["sequence"]["checksum"] = MD5_OTHER
    calls = []
    def lookup(path, expected, backend):
        calls.append(set(expected))
        return [MD5_B, MD5_OTHER]
    monkeypatch.setattr(checks, "missing_index_md5s", lookup)
    statements = []
    engine = metadata_session.get_bind()
    def capture(*args): statements.append(args[2])
    event.listen(engine, "before_cursor_execute", capture)
    try:
        report = validate(metadata_session, index, fake_mongo)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert calls == [{MD5_A, MD5_B, MD5_OTHER}]
    assert len(statements) == 1
    assert len(fake_mongo.database.calls) == 3
    assert all(call[1] == {"genome_id": {"$in": ["genome-2", "genome-3"]}} for call in fake_mongo.database.calls)
    assert report["sources"]["assembly_sequence"]["missing_md5s"] == [MD5_B]
    assert report["sources"]["mongodb"]["missing_md5s"] == sorted([MD5_B, MD5_OTHER])
    assert report["sources"]["assembly_sequence"]["genomes"]["genome-2"]["expected_md5_count"] == 2
    assert report["passed"] is False


def test_mongo_failure_does_not_fail_assembly_check(metadata_session, fake_index, fake_mongo):
    index, _ = fake_index
    fake_mongo.database.documents["region"][0]["sequence"]["checksum"] = MD5_OTHER
    report = validate(metadata_session, index, fake_mongo)
    checks.check_refget_assembly_sequence_index_db(report)
    with pytest.raises(AssertionError, match="mongodb: 1 / 3"):
        checks.check_refget_mongo_index_db(report)


def test_assembly_failure_does_not_fail_mongo_check(metadata_session, fake_index, fake_mongo):
    index, _ = fake_index
    metadata_session.execute(text("UPDATE assembly_sequence SET md5=:v WHERE assembly_sequence_id=2"), {"v": MD5_OTHER})
    report = validate(metadata_session, index, fake_mongo)
    checks.check_refget_mongo_index_db(report)
    with pytest.raises(AssertionError, match="assembly_sequence: 1 / 3"):
        checks.check_refget_assembly_sequence_index_db(report)


def test_automation_genome_records_identify_mongo_database(metadata_session, fake_index, fake_mongo):
    index, _ = fake_index
    report = checks.validate_genome_index(metadata_session, [
        {"genome_uuid": "genome-2", "release_version": "116.5"},
        {"genome_uuid": "genome-3", "release_version": "116.6"},
    ], index, mongo_client=fake_mongo)
    assert report["mongo_databases"] == ["release_116_5", "release_116_6"]
    assert report["passed"]
    assert len(fake_mongo.database.calls) == 6


def test_uuid_only_requires_explicit_mongo_database(metadata_session, fake_index, fake_mongo):
    index, _ = fake_index
    with pytest.raises(ValueError, match="mongo_database"):
        checks.validate_genome_index(metadata_session, "genome-2", index, mongo_client=fake_mongo)


@pytest.mark.parametrize("bad", ["not-an-md5", 123, "z" * 32])
def test_invalid_mongo_checksum_fails(fake_mongo, bad):
    fake_mongo.database.documents["region"][0]["sequence"]["checksum"] = bad
    with pytest.raises(ValueError, match="Invalid MongoDB MD5"):
        checks.fetch_mongo_checksums(fake_mongo.database, ["genome-2"])
    assert fake_mongo.database.cursors[-1].closed


def test_all_contexts_and_checksum_aliases_are_read(fake_mongo):
    fake_mongo.database.documents["transcript"][0]["product_generating_contexts"].append(
        {"cdna": {"sequence_checksum": MD5_OTHER.upper()}, "cds": {"sequence_checksum": None}})
    expected, _ = checks.fetch_mongo_checksums(fake_mongo.database, ["genome-2"])
    assert expected["genome-2"] == {MD5_A, MD5_B, MD5_OTHER}
    assert all(cursor.closed for cursor in fake_mongo.database.cursors)


def test_genome_without_mongo_checksums_fails(fake_mongo):
    with pytest.raises(ValueError, match="No MongoDB sequence checksums.*genome-absent"):
        checks.fetch_mongo_checksums(fake_mongo.database, ["genome-2", "genome-absent"])


def test_reads_beyond_first_twenty_and_ignores_metadata_values(fake_index):
    index, output = fake_index
    output.write_text("unrelated\n" * 25 + MD5_A + "\n")
    assert checks.missing_index_md5s(index, {MD5_A, MD5_B}, backend="cli") == [MD5_B]


def test_late_process_failure_does_not_pass(fake_index, monkeypatch):
    index, _ = fake_index
    monkeypatch.setenv("FAKE_RETURN_CODE", "1")
    with pytest.raises(RuntimeError, match="injected index read error"):
        checks.missing_index_md5s(index, {MD5_A, MD5_B})


def test_missing_tool_fails(fake_index, monkeypatch):
    index, _ = fake_index
    monkeypatch.setattr(checks.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="required on PATH"):
        checks.missing_index_md5s(index, {MD5_A})


def test_missing_index_fails(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        checks.missing_index_md5s(tmp_path / "missing.tkh", {MD5_A})


@pytest.mark.parametrize("missing, expected_exit", [([], 0), ([MD5_B], 1)])
def test_cli_exit_and_separate_report(fake_index, tmp_path, monkeypatch, missing, expected_exit):
    index, _ = fake_index
    coverage = checks._coverage_report({"genome-2": {MD5_A, MD5_B}}, set(missing))
    monkeypatch.setattr(checks, "validate_genome_index", lambda *a, **kw: {
        "passed": not missing, "sources": {"assembly_sequence": coverage, "mongodb": coverage},
    })
    report_path = tmp_path / "report.json"
    assert checks.main(["--database", "sqlite://", "--index-file", str(index),
        "--genome-uuid", "genome-2", "--mongo-database", "release_explicit",
        "--report", str(report_path)]) == expected_exit
    assert json.loads(report_path.read_text())["sources"]["assembly_sequence"]["missing_md5s"] == missing


def test_fixture_uses_only_explicit_uuids_and_writes_report(metadata_session, fake_index, tmp_path):
    index, _ = fake_index
    path = tmp_path / "report.json"
    requested = []
    def getoption(name):
        requested.append(name)
        assert name == "genome_uuid"
        return "genome-2"
    request = SimpleNamespace(config=SimpleNamespace(getoption=getoption))
    report = checks.refget_index_report.__wrapped__(metadata_session, request, {
        "index_file": str(index), "mongo_database": "release_explicit", "report": str(path),
    })
    assert report["genome_uuids"] == ["genome-2"]
    assert json.loads(path.read_text()) == report
    assert requested == ["genome_uuid"]


def test_cli_mongo_failure_is_sanitized(fake_index, monkeypatch, capsys):
    index, _ = fake_index
    def fail(*args, **kwargs): raise OperationFailure("sensitive server details")
    monkeypatch.setattr(checks, "validate_genome_index", fail)
    assert checks.main(["--database", "sqlite://", "--index-file", str(index),
        "--genome-uuid", "genome-2", "--mongo-database", "release_explicit"]) == 2
    assert "sensitive server details" not in capsys.readouterr().err


def test_cli_rejects_release_option(fake_index):
    index, _ = fake_index
    with pytest.raises(SystemExit) as error:
        checks.main(["--database", "sqlite://", "--index-file", str(index),
            "--genome-uuid", "genome-2", "--mongo-database", "release_explicit", "--release", "latest"])
    assert error.value.code == 2


def test_cli_key_value_output_does_not_report_present_md5_missing(fake_index):
    index, output = fake_index
    output.write_text(MD5_A + "\tsha-key\n" + MD5_B + "\tother-sha-key\n")
    assert checks.missing_index_md5s(index, {MD5_A, MD5_B}) == []


def test_real_tkrzw_cli_positive_and_negative_controls(tmp_path):
    """Catch CLI parsing/output behavior that a mocked subprocess cannot cover."""
    import shutil
    import subprocess
    executable = shutil.which('tkrzw_dbm_util')
    if executable is None:
        pytest.skip('tkrzw_dbm_util is not installed')
    index = tmp_path / 'control.tkh'
    subprocess.run([executable, 'create', '--dbm', 'hash', '--buckets', '17', str(index)], check=True, capture_output=True)
    subprocess.run([executable, 'set', str(index), MD5_A, 'sha-key'], check=True, capture_output=True)
    assert checks.missing_index_md5s(index, {MD5_A, MD5_B}, backend="cli") == [MD5_B]


def test_native_python_binding_positive_and_negative_controls(tmp_path):
    tkrzw = pytest.importorskip('tkrzw')
    index = tmp_path / 'native-control.tkh'
    dbm = tkrzw.DBM()
    dbm.Open(str(index), True, dbm='HashDBM', num_buckets=17).OrDie()
    dbm.Set(MD5_A, 'sha-key').OrDie()
    dbm.Close().OrDie()
    assert checks.missing_index_md5s(index, {MD5_A, MD5_B}, backend='python') == [MD5_B]


def test_native_read_error_is_not_a_missing_key(fake_index, monkeypatch):
    index, _ = fake_index
    closed = []
    class Status:
        SUCCESS = 0
        NOT_FOUND_ERROR = 7
        def IsOK(self): return True
        def GetCode(self): return 9
    class DBM:
        def Open(self, *args, **kwargs):
            assert args[1] is False
            assert kwargs['no_wait'] is True
            return Status()
        def Get(self, *args): return None
        def Close(self): closed.append(True); return Status()
    monkeypatch.setattr(checks, '_load_tkrzw', lambda: SimpleNamespace(DBM=DBM, Status=Status))
    with pytest.raises(RuntimeError, match='Unable to read'):
        checks.missing_index_md5s(index, {MD5_A}, backend='python')
    assert closed == [True]


def test_requested_native_backend_requires_binding(fake_index):
    index, _ = fake_index
    with pytest.raises(RuntimeError, match='Python tkrzw binding'):
        checks.missing_index_md5s(index, {MD5_A}, backend='python')


def test_automation_uses_existing_mongo_fixture_with_configured_resource(tmp_path):
    """Exercise real pytest collection, shared fixture caching and cleanup."""
    import os
    import subprocess
    from pathlib import Path
    log = tmp_path / 'events.txt'
    (tmp_path / 'pytest.ini').write_text('[pytest]\npython_functions = check_*\nmarkers =\n    automation_resource(name): automation resource\n')
    (tmp_path / 'conftest.py').write_text('''
import os
from pathlib import Path
import pytest
import pymongo
from ensembl.datacheck.checks.automation.conftest import (
    pytest_generate_tests, automation_resource_config, mongo_client,
    refget_index_config, refget_index_genomes,
)
from ensembl.datacheck.checks import refget_expected_index_db as engine

log = Path(os.environ['REFGET_FIXTURE_TEST_LOG'])
def record(value):
    with log.open('a') as out: out.write(value + '\\n')

class Client:
    def __init__(self, uri): record('create:' + uri)
    def close(self): record('close')
pymongo.MongoClient = Client

def validate(session, genomes, index_file, mongo_client, **kwargs):
    assert isinstance(mongo_client, Client)
    assert genomes == [{'genome_uuid': 'uuid-1'}, {'genome_uuid': 'uuid-2'}]
    record('validate')
    return {'sources': {'assembly_sequence': {'passed': True}, 'mongodb': {'passed': True}}}
engine.validate_genome_index = validate

@pytest.fixture(scope='session')
def db_session(): return object()

def pytest_addoption(parser):
    parser.addoption('--test', default='automation/automation_refget_expected_index_db')
    parser.addoption('--genome_uuid', default='uuid-1,uuid-2')
    parser.addoption('--automation_resource_config', default=None)
    parser.addoption('--params', action='append', default=[])
    parser.addoption('--use_alt', dest='use_alt', action='store_true')
''')
    (tmp_path / 'test_checks.py').write_text('''
from ensembl.datacheck.checks.automation.automation_refget_expected_index_db import (
    refget_index_report, check_refget_assembly_sequence_index_db, check_refget_mongo_index_db,
)
''')
    env = dict(os.environ, REFGET_FIXTURE_TEST_LOG=str(log))
    result = subprocess.run([
        sys.executable, '-m', 'pytest', '-c', str(tmp_path/'pytest.ini'),
        str(tmp_path/'test_checks.py'), '-q', '-p', 'no:cacheprovider',
        '--params', 'refget_index.index_file=/test/index.tkh,refget_index.mongo_database=release_116_1,refget_index.mongo_resource=thoas_mongo_public_resource_uri,thoas_mongo_public_resource_uri.uri=mongodb://configured.invalid',
    ], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '2 passed' in result.stdout
    assert log.read_text().splitlines() == ['create:mongodb://configured.invalid', 'validate', 'close']


def test_automation_report_passes_existing_client_unchanged(monkeypatch, tmp_path):
    from ensembl.datacheck.checks.automation import automation_refget_expected_index_db as automation
    from ensembl.datacheck.checks.automation import conftest as fixtures
    client = object()
    captured = []
    def validate(*args, **kwargs):
        captured.append(kwargs['mongo_client'])
        return {'sources': {'assembly_sequence': {'passed': True}, 'mongodb': {'passed': True}}}
    monkeypatch.setattr(automation.refget, 'validate_genome_index', validate)
    automation.refget_index_report.__wrapped__(object(), [{'genome_uuid': 'uuid-1'}], {
        'index_file': '/test/index.tkh', 'mongo_database': 'release_116_1',
    }, client)
    assert captured == [client]
    assert not hasattr(fixtures, 'refget_index_mongo_client')


@pytest.mark.parametrize('resource_name', ['thoas_mongo_internal_resource_uri', 'refget_index'])
def test_existing_mongo_fixture_resolves_direct_and_configured_resources(monkeypatch, resource_name):
    from ensembl.datacheck.checks.automation import conftest as fixtures
    selected = []
    closed = []
    client = SimpleNamespace(close=lambda: closed.append(True))
    resources = {'refget_index': {'mongo_resource': 'thoas_mongo_internal_resource_uri'},
                 'thoas_mongo_internal_resource_uri': {'uri': 'mongodb://test.invalid'}}
    def create(name, config):
        selected.append(name)
        assert config is resources
        return client
    monkeypatch.setattr(fixtures, '_create_mongo_resource_client', create)
    fixture = fixtures.mongo_client.__wrapped__(SimpleNamespace(param=resource_name), resources)
    assert next(fixture) is client
    fixture.close()
    assert selected == ['thoas_mongo_internal_resource_uri']
    assert closed == [True]
