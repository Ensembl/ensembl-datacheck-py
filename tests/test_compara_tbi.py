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
"""Unit tests for Compara tabix index checks."""

from pathlib import Path
from time import sleep

from pytest import fixture, raises

from ensembl.datacheck.checks.compara import tbi


def _setup_compara_tbi_test_file(test_file_name: str) -> Path:
    test_file_dir_path = Path(__file__).parent / "file" / "compara" / "tbi"
    return test_file_dir_path / test_file_name


@fixture(scope="module")
def nonexistent_tsv_bgz():
    """Nonexistent data file fixture."""
    yield _setup_compara_tbi_test_file("nonexistent.tsv.bgz")


@fixture(scope="module")
def nonexistent_tsv_bgz_tbi():
    """Nonexistent index file fixture."""
    yield _setup_compara_tbi_test_file("nonexistent.tsv.bgz.tbi")


@fixture(scope="module")
def homology_header_tsv_bgz():
    """Header-only homology TSV file fixture."""
    yield _setup_compara_tbi_test_file("homology_header.tsv.bgz")


@fixture(scope="module")
def homology_header_tsv_bgz_tbi():
    """Header-only homology TSV index file fixture."""
    yield _setup_compara_tbi_test_file("homology_header.tsv.bgz.tbi")


@fixture(scope="module")
def homology_record_tsv_bgz():
    """Single-record homology TSV file fixture."""
    yield _setup_compara_tbi_test_file("homology_record.tsv.bgz")


@fixture(scope="module")
def homology_record_tsv_bgz_tbi():
    """Single-record homology TSV index file fixture."""
    yield _setup_compara_tbi_test_file("homology_record.tsv.bgz.tbi")


@fixture(scope="module")
def homology_header_tsv_gz():
    """File fixture for gzip-compressed homology TSV file."""
    yield _setup_compara_tbi_test_file("homology_header.tsv.gz")


@fixture(scope="module")
def homology_header_tsv_gz_tbi():
    """File fixture for index of gzip-compressed homology TSV file."""
    yield _setup_compara_tbi_test_file("homology_header.tsv.gz.tbi")


@fixture(scope="module")
def truncated_tsv_bgz():
    """Truncated homology TSV file fixture."""
    yield _setup_compara_tbi_test_file("truncated.tsv.bgz")


@fixture(scope="module")
def older_tsv_bgz_tbi():
    """Older index file fixture."""
    older_tsv_bgz_tbi_path = _setup_compara_tbi_test_file("older.tsv.bgz.tbi")
    older_tsv_bgz_tbi_path.touch()
    yield older_tsv_bgz_tbi_path
    older_tsv_bgz_tbi_path.unlink()


@fixture(scope="module")
def older_tsv_bgz(older_tsv_bgz_tbi):
    """Older data file fixture."""
    older_tsv_bgz_path = _setup_compara_tbi_test_file("older.tsv.bgz")
    older_tsv_bgz_path.touch()
    sleep(0.01)  # we need the mtime of 'older_tsv_bgz' to be distinguishable from others
    yield older_tsv_bgz_path
    older_tsv_bgz_path.unlink()


@fixture(scope="module")
def newer_tsv_bgz(older_tsv_bgz):
    """Newer data file fixture."""
    newer_tsv_bgz_path = _setup_compara_tbi_test_file("newer.tsv.bgz")
    newer_tsv_bgz_path.touch()
    sleep(0.01)  # we need the mtime of 'newer_tsv_bgz' to be distinguishable from others
    yield newer_tsv_bgz_path
    newer_tsv_bgz_path.unlink()


@fixture(scope="module")
def newer_tsv_bgz_tbi(newer_tsv_bgz):
    """Newer index file fixture."""
    newer_tsv_bgz_tbi_path = _setup_compara_tbi_test_file("newer.tsv.bgz.tbi")
    newer_tsv_bgz_tbi_path.touch()
    sleep(0.01)  # we need the mtime of 'newer_tsv_bgz_tbi' to be distinguishable from others
    yield newer_tsv_bgz_tbi_path
    newer_tsv_bgz_tbi_path.unlink()


def test_check_existing_index(homology_header_tsv_bgz_tbi):
    """Test existence check on existing index file."""
    assert homology_header_tsv_bgz_tbi.exists(), f"file exists: {homology_header_tsv_bgz_tbi}"
    tbi.check_target_file_exists(homology_header_tsv_bgz_tbi)


def test_check_nonexistent_index(nonexistent_tsv_bgz_tbi):
    """Test existence check on nonexistent index file."""
    with raises(AssertionError, match="tabix index file not found"):
        tbi.check_target_file_exists(nonexistent_tsv_bgz_tbi)


def test_check_valid_index(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi):
    """Test validity check on valid index file."""
    tbi.check_target_file_valid(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi)


def test_check_invalid_index(homology_record_tsv_bgz_tbi, homology_record_tsv_bgz):
    """Test validity check on invalid index file."""
    with raises(AssertionError, match="could not open target file as tabix index"):
        tbi.check_target_file_valid(homology_record_tsv_bgz_tbi, homology_record_tsv_bgz)


def test_check_current_index(older_tsv_bgz, newer_tsv_bgz_tbi):
    """Test staleness check on current index file."""
    tbi.check_target_file_current(older_tsv_bgz, newer_tsv_bgz_tbi)


def test_check_stale_index(newer_tsv_bgz, older_tsv_bgz_tbi):
    """Test staleness check on stale index file."""
    with raises(AssertionError, match="tabix index file is older than data file"):
        tbi.check_target_file_current(newer_tsv_bgz, older_tsv_bgz_tbi)


def test_check_bgzip_data_file(homology_header_tsv_bgz, homology_header_tsv_bgz_tbi):
    """Test compression-type check on bgzip-compressed data file."""
    tbi.check_source_file_compression(homology_header_tsv_bgz, homology_header_tsv_bgz_tbi)


def test_check_gzip_data_file(homology_header_tsv_gz, homology_header_tsv_gz_tbi):
    """Test compression-type check on gzip-compressed data file."""
    with raises(AssertionError, match="tabix-indexed data file must be bgzip-compressed"):
        tbi.check_source_file_compression(homology_header_tsv_gz, homology_header_tsv_gz_tbi)


def test_check_complete_data_file(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi):
    """Test truncation check on complete data file."""
    tbi.check_source_file_truncation(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi)


def test_check_truncated_data_file(truncated_tsv_bgz, homology_record_tsv_bgz_tbi):
    """Test truncation check on truncated data file."""
    with raises(AssertionError, match="no BGZF EOF marker; tabix-indexed data file may be truncated"):
        tbi.check_source_file_truncation(truncated_tsv_bgz, homology_record_tsv_bgz_tbi)


def test_check_nonzero_reference_count(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi):
    """Test nonzero reference-count check on single-entry data file."""
    tbi.check_nonzero_reference_count(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi)


def test_check_zero_reference_count(homology_header_tsv_bgz, homology_header_tsv_bgz_tbi):
    """Test nonzero reference-count check on header-only data file."""
    with raises(AssertionError, match="tabix index file contains no references"):
        tbi.check_nonzero_reference_count(homology_header_tsv_bgz, homology_header_tsv_bgz_tbi)


def test_check_nonzero_row_counts(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi):
    """Test nonzero row-count check on single-entry data file."""
    tbi.check_nonzero_row_counts(homology_record_tsv_bgz, homology_record_tsv_bgz_tbi)


def test_check_zero_row_counts(homology_header_tsv_bgz, homology_header_tsv_bgz_tbi):
    """Test nonzero row-count check on header-only data file."""
    with raises(AssertionError, match="tabix index file contains no references"):
        tbi.check_nonzero_row_counts(homology_header_tsv_bgz, homology_header_tsv_bgz_tbi)
