import pytest

from ensembl.datacheck.checks import bigwig


class _DummyReader:
    def __init__(self, is_bigwig=True):
        self._is_bigwig = is_bigwig
        self.closed = False

    def isBigWig(self):
        return self._is_bigwig

    def close(self):
        self.closed = True


def test_check_validity_accepts_pybigwig_reader(monkeypatch, tmp_path):
    target_file = tmp_path / "track.bw"
    target_file.touch()
    reader = _DummyReader()

    monkeypatch.setattr(bigwig, "bb_bw_reader", lambda path: reader)

    bigwig.check_validity(target_file)

    assert reader.closed is True


def test_check_validity_falls_back_to_bigwiginfo(monkeypatch, tmp_path):
    target_file = tmp_path / "track.bw"
    target_file.touch()

    monkeypatch.setattr(
        bigwig,
        "bb_bw_reader",
        lambda path: (_ for _ in ()).throw(
            SystemError("initialization of pyBigWig failed without raising an exception")
        ),
    )
    monkeypatch.setattr(bigwig.shutil, "which", lambda name: "/usr/bin/bigWigInfo")

    class _CompletedProcess:
        returncode = 0
        stdout = "basesCovered: 1\n"
        stderr = ""

    monkeypatch.setattr(bigwig.subprocess, "run", lambda *args, **kwargs: _CompletedProcess())

    bigwig.check_validity(target_file)


def test_check_validity_reports_both_failures(monkeypatch, tmp_path):
    target_file = tmp_path / "track.bw"
    target_file.touch()

    monkeypatch.setattr(
        bigwig,
        "bb_bw_reader",
        lambda path: (_ for _ in ()).throw(
            SystemError("initialization of pyBigWig failed without raising an exception")
        ),
    )
    monkeypatch.setattr(bigwig.shutil, "which", lambda name: "/usr/bin/bigWigInfo")

    class _CompletedProcess:
        returncode = 1
        stdout = ""
        stderr = "not a big wig"

    monkeypatch.setattr(bigwig.subprocess, "run", lambda *args, **kwargs: _CompletedProcess())

    with pytest.raises(AssertionError, match="pyBigWig"):
        bigwig.check_validity(target_file)
