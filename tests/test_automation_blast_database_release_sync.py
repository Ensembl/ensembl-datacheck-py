"""Unit tests for the BLAST database release sync datacheck."""

import hashlib
from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation import (
    automation_blast_database_release_sync as blast_sync,
)


def _md5(value):
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def test_read_manifest_accepts_md5sum_entries(tmp_path):
    manifest = tmp_path / "manifest"
    manifest.write_text(f"{_md5(b'content')}  abc/genome/cdna.nhr\n")

    assert blast_sync._read_manifest(manifest) == [
        (_md5(b"content"), Path("abc/genome/cdna.nhr")),
    ]


@pytest.mark.parametrize("line", ["not-a-manifest-line", "z" * 32 + "  file", "a" * 32 + "  ../file"])
def test_read_manifest_rejects_malformed_entries(tmp_path, line):
    manifest = tmp_path / "manifest"
    manifest.write_text(line + "\n")

    with pytest.raises(AssertionError, match="Malformed manifest lines"):
        blast_sync._read_manifest(manifest)


def test_sync_checks_pass_for_copied_file(tmp_path):
    target = tmp_path / "release" / "abc" / "genome"
    target.mkdir(parents=True)
    copied_file = target / "cdna.nhr"
    copied_file.write_bytes(b"content")
    context = {
        "release_path": tmp_path / "release",
        "entries": [(_md5(b"content"), copied_file.relative_to(tmp_path / "release"))],
    }

    blast_sync.check_blast_database_release_sync_files_exist(context)
    blast_sync.check_blast_database_release_sync_checksums(context)


def test_sync_files_check_reports_missing_file(tmp_path):
    context = {"release_path": tmp_path, "entries": [("a" * 32, Path("missing"))]}

    with pytest.raises(AssertionError, match="Missing copied BLAST files"):
        blast_sync.check_blast_database_release_sync_files_exist(context)


def test_sync_checksum_check_reports_mismatch(tmp_path):
    copied_file = tmp_path / "copied"
    copied_file.write_bytes(b"different")
    context = {"release_path": tmp_path, "entries": [(_md5(b"expected"), copied_file.relative_to(tmp_path))]}

    with pytest.raises(AssertionError, match="BLAST file checksum mismatches"):
        blast_sync.check_blast_database_release_sync_checksums(context)
