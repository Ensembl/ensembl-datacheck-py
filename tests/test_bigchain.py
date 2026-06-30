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

"""Unit tests for generic bigChain checks."""

import os
from pathlib import Path
import re
import subprocess

from pytest import fixture, raises

from ensembl.datacheck.checks import bigchain


def _setup_bigchain_file(bed_file_name, bigbed_file_name=None, truncate_length=None):
    test_file_dir_path = Path(__file__).parent / "file" / "bigchain"

    bed_file_path = test_file_dir_path / bed_file_name
    chrom_sizes_file_path = test_file_dir_path / "human.chrom.sizes"
    bigchain_autosql_file_path = test_file_dir_path / "bigChain.as"

    if bigbed_file_name:
        bigchain_file_path = test_file_dir_path / bigbed_file_name
    else:
        bigchain_file_path = bed_file_path.with_suffix(".bb")

    cmd_args = [
        "bedToBigBed",
        bed_file_path,
        chrom_sizes_file_path,
        bigchain_file_path,
        f"-as={bigchain_autosql_file_path}",
        "-tab",
        "-type=bed6+6",
    ]
    subprocess.check_call(cmd_args)

    if truncate_length is not None:
        os.truncate(bigchain_file_path, truncate_length)

    return bigchain_file_path


@fixture(scope="module")
def single_entry_bigchain_file():
    """Single-entry bigChain file fixture."""
    single_entry_bigchain_path = _setup_bigchain_file("human_chimp.single.bed")
    yield single_entry_bigchain_path
    single_entry_bigchain_path.unlink()


@fixture(scope="module")
def truncated_bigchain_file():
    """Truncated bigChain file fixture."""
    truncated_bigchain_path = _setup_bigchain_file(
        "human_chimp.single.bed", bigbed_file_name="human_chimp.truncated.bb", truncate_length=1234,
    )
    yield truncated_bigchain_path
    truncated_bigchain_path.unlink()


@fixture(scope="module")
def zero_entry_bigchain_file():
    """Empty bigChain file fixture."""
    empty_bigchain_path = _setup_bigchain_file("human_chimp.empty.bed")
    yield empty_bigchain_path
    empty_bigchain_path.unlink()


def test_check_exist_no_file():
    """Test bigChain existence check on nonexistent file."""
    with raises(AssertionError, match=re.escape("The target file does not exist.")):
        bigchain.check_exist("/path/to/nonexistent/file")


def test_check_exist_zero_entry_bigchain_file(zero_entry_bigchain_file):
    """Test bigChain existence check on zero-entry bigChain file."""
    bigchain.check_exist(zero_entry_bigchain_file)


def test_check_validity_no_file():
    """Test bigChain validity check on nonexistent file."""
    with raises(FileNotFoundError, match=re.escape("The target file does not exist.")):
        bigchain.check_validity("/path/to/nonexistent/file")


def test_check_validity_non_bigchain_file():
    """Test bigChain validity check on non-bigChain file."""
    test_script_file_path = Path(__file__)
    with raises(AssertionError, match=re.escape("The target file is not recognised as bigChain.")):
        bigchain.check_validity(test_script_file_path)


def test_check_validity_single_entry_bigchain_file(single_entry_bigchain_file):
    """Test bigChain validity check on single-entry bigChain file."""
    bigchain.check_validity(single_entry_bigchain_file)


def test_check_validity_truncated_bigchain_file(truncated_bigchain_file):
    """Test bigChain validity check on truncated bigChain file."""
    with raises(ValueError, match="bigChain data accessibility"):
        bigchain.check_validity(truncated_bigchain_file)


def test_check_validity_zero_entry_bigchain_file(zero_entry_bigchain_file):
    """Test bigChain validity check on zero-entry bigChain file."""
    bigchain.check_validity(zero_entry_bigchain_file)


def test_check_nonzero_entries_single_entry_bigchain_file(single_entry_bigchain_file):
    """Test bigChain nonzero entries check on single-entry bigChain file."""
    bigchain.check_nonzero_entries(single_entry_bigchain_file)


def test_check_nonzero_entries_zero_entry_bigchain_file(zero_entry_bigchain_file):
    """Test bigChain nonzero entries check on zero-entry bigChain file."""
    with raises(AssertionError, match=re.escape("bigChain file has no entries.")):
        bigchain.check_nonzero_entries(zero_entry_bigchain_file)


def test_check_nonzero_target_coverage_single_entry_bigchain_file(single_entry_bigchain_file):
    """Test nonzero target coverage check on single-entry bigChain file."""
    bigchain.check_nonzero_target_coverage(single_entry_bigchain_file)


def test_check_nonzero_target_coverage_zero_entry_bigchain_file(zero_entry_bigchain_file):
    """Test nonzero target coverage check on zero-entry bigChain file."""
    with raises(AssertionError, match=re.escape("Target assembly has no coverage.")):
        bigchain.check_nonzero_target_coverage(zero_entry_bigchain_file)
