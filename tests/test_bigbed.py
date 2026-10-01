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

"""Integration tests for bigbed functions."""


from pathlib import Path

import pytest

from ensembl.datacheck.checks import bigbed


class _DummyReader:
    def __init__(self, is_bigbed=True):
        self._is_bigbed = is_bigbed
        self.closed = False

    def isBigBed(self):
        return self._is_bigbed

    def close(self):
        self.closed = True


def test_check_validity_accepts_pybigwig_reader(monkeypatch, tmp_path):
    target_file = tmp_path / "track.bb"
    target_file.touch()
    reader = _DummyReader()

    monkeypatch.setattr(bigbed, "bb_bw_reader", lambda path: reader)

    bigbed.check_validity(target_file)

    assert reader.closed is True


def test_check_validity_falls_back_to_bigbedinfo(monkeypatch, tmp_path):
    target_file = tmp_path / "track.bb"
    target_file.touch()

    monkeypatch.setattr(
        bigbed,
        "bb_bw_reader",
        lambda path: (_ for _ in ()).throw(
            SystemError("initialization of pyBigWig failed without raising an exception")
        ),
    )
    monkeypatch.setattr(bigbed.shutil, "which", lambda name: "/usr/bin/bigBedInfo")

    class _CompletedProcess:
        returncode = 0
        stdout = "itemCount: 1\n"
        stderr = ""

    monkeypatch.setattr(bigbed.subprocess, "run", lambda *args, **kwargs: _CompletedProcess())

    bigbed.check_validity(target_file)


def test_check_validity_reports_both_failures(monkeypatch, tmp_path):
    target_file = tmp_path / "track.bb"
    target_file.touch()

    monkeypatch.setattr(
        bigbed,
        "bb_bw_reader",
        lambda path: (_ for _ in ()).throw(
            SystemError("initialization of pyBigWig failed without raising an exception")
        ),
    )
    monkeypatch.setattr(bigbed.shutil, "which", lambda name: "/usr/bin/bigBedInfo")

    class _CompletedProcess:
        returncode = 1
        stdout = ""
        stderr = "not a big bed"

    monkeypatch.setattr(bigbed.subprocess, "run", lambda *args, **kwargs: _CompletedProcess())

    with pytest.raises(AssertionError, match="pyBigWig"):
        bigbed.check_validity(target_file)
