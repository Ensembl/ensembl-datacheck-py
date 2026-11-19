"""Tests for generic GFF checks."""

from gzip import open as gzip_open

import pysam
import pytest

from ensembl.datacheck.checks import gff


def _write_gff(path, record="1\tEnsembl\tenhancer\t1\t10\t.\t.\t.\tID=ENSR1"):
    with gzip_open(path, "wt", encoding="utf-8") as gff_file:
        gff_file.write(f"{record}\n")


def _write_bgzipped_and_indexed_gff(path):
    uncompressed_file = path.with_suffix("")
    uncompressed_file.write_text("1\tEnsembl\tenhancer\t1\t10\t.\t.\t.\tID=ENSR1\n")
    pysam.tabix_compress(str(uncompressed_file), str(path), force=True)
    pysam.tabix_index(str(path), preset="gff", csi=True, force=True)


def test_generic_gff_checks_accept_target_and_source(tmp_path):
    target_file = tmp_path / "target.gff.gz"
    source_file = tmp_path / "source.gff.gz"
    _write_gff(target_file)
    _write_gff(source_file)

    gff.check_exist(target_file, source_file)
    gff.check_has_gff_gz_extension(target_file, source_file)
    gff.check_validity(target_file, source_file)


def test_check_validity_reports_gff_reader_failure(monkeypatch, tmp_path):
    target_file = tmp_path / "target.gff.gz"
    _write_gff(target_file)
    monkeypatch.setattr(
        gff,
        "gff_reader",
        lambda path: (_ for _ in ()).throw(ValueError("invalid GFF")),
    )

    with pytest.raises(AssertionError, match="Could not parse GFF file"):
        gff.check_validity(target_file, None)


def test_bgzf_and_index_checks_accept_indexed_gff(tmp_path):
    target_file = tmp_path / "target.gff.gz"
    _write_bgzipped_and_indexed_gff(target_file)

    gff.check_is_bgzf_gff_file(target_file, None)
    gff.check_has_valid_index_file(target_file, None)


def test_bgzf_and_index_checks_reject_plain_gzip_and_missing_index(tmp_path):
    target_file = tmp_path / "target.gff.gz"
    _write_gff(target_file)

    with pytest.raises(AssertionError, match="BGZF-compressed"):
        gff.check_is_bgzf_gff_file(target_file, None)
    with pytest.raises(AssertionError, match="Could not find an index file"):
        gff.check_has_valid_index_file(target_file, None)
