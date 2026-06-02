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

"""Unit tests for generic BLAST database checks."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from ensembl.datacheck.checks import blast_db  # noqa: E402


def test_blast_db_prefix_strips_volume_suffix():
    assert blast_db._blast_db_prefix("/tmp/softmasked.nsq") == "/tmp/softmasked"


def test_check_exist_accepts_any_files_matching_blast_database_prefix(tmp_path):
    prefix = tmp_path / "softmasked"
    (tmp_path / "softmasked.nhr").touch()
    (tmp_path / "softmasked.nin").touch()
    (tmp_path / "softmasked.nsq").touch()

    blast_db.check_exist(prefix)


def test_check_exist_accepts_volume_file_path(tmp_path):
    prefix = tmp_path / "softmasked"
    (tmp_path / "softmasked.nsq").touch()

    blast_db.check_exist(prefix.with_suffix(".nsq"))


def test_check_exist_fails_when_no_blast_database_files_match(tmp_path):
    with pytest.raises(AssertionError, match="No BLAST database files found"):
        blast_db.check_exist(tmp_path / "missing")


def test_check_validity_runs_info_and_blastdbcheck_against_prefix(monkeypatch, tmp_path):
    prefix = tmp_path / "softmasked"
    (tmp_path / "softmasked.nsq").touch()
    calls = {}

    def fake_blastdbcmd_info(db_prefix, taxdb_dir=None):
        calls["info"] = (db_prefix, taxdb_dir)
        return SimpleNamespace(returncode=0, stdout="Database: softmasked", stderr="")

    def fake_blastdbcheck(db_prefix, taxdb_dir=None, full=False):
        calls["check"] = (db_prefix, taxdb_dir, full)
        return True, []

    monkeypatch.setattr(blast_db, "_run_blastdbcmd_info", fake_blastdbcmd_info)
    monkeypatch.setattr(blast_db, "_run_blastdbcheck", fake_blastdbcheck)

    blast_db.check_validity(prefix.with_suffix(".nsq"), taxdb_dir="/taxdb", full=True)

    assert calls == {
        "info": (prefix.with_suffix(".nsq"), "/taxdb"),
        "check": (prefix.with_suffix(".nsq"), "/taxdb", True),
    }


def test_check_validity_fails_when_blastdbcmd_cannot_open_database(
    monkeypatch,
    tmp_path,
):
    prefix = tmp_path / "softmasked"
    (tmp_path / "softmasked.nsq").touch()

    monkeypatch.setattr(
        blast_db,
        "_run_blastdbcmd_info",
        lambda db_prefix, taxdb_dir=None: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="No alias or index file found",
        ),
    )

    with pytest.raises(AssertionError, match="could not be opened"):
        blast_db.check_validity(prefix)


def test_check_validity_reports_blastdbcheck_errors(monkeypatch, tmp_path):
    prefix = tmp_path / "softmasked"
    (tmp_path / "softmasked.nsq").touch()

    monkeypatch.setattr(
        blast_db,
        "_run_blastdbcmd_info",
        lambda db_prefix, taxdb_dir=None: SimpleNamespace(
            returncode=0,
            stdout="Database: softmasked",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        blast_db,
        "_run_blastdbcheck",
        lambda db_prefix, taxdb_dir=None, full=False: (
            False,
            ["Sample: 1 sampled OID(s) did not PASS"],
        ),
    )

    with pytest.raises(AssertionError, match="blastdbcheck reported errors"):
        blast_db.check_validity(prefix)


def test_collect_real_errors_ignores_taxid_lookup_noise():
    output = """
/tmp/softmasked / MetaData: NCBI C++ Exception:
    GetTaxInfo() - Taxid 9606 not found
/tmp/softmasked / Sample: Status for OID 0: PASS
"""

    assert blast_db._collect_real_errors(output) == []


def test_collect_real_errors_reports_non_pass_sample():
    output = "/tmp/softmasked / Sample: Status for OID 0: FAIL"

    assert blast_db._collect_real_errors(output) == [
        "Sample: 1 sampled OID(s) did not PASS",
    ]
