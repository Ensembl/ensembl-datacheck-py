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
