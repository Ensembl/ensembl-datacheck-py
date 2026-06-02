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

"""
bigchain.py

This module performs generic bigChain checks.

Checks performed:
1. check_exist: Asserts that the target bigChain path exists.
2. check_validity: Asserts that the target file is readable as bigChain.
3. check_nonzero_entries: Checks bigChain has at least one entry.
4. check_nonzero_target_coverage: Checks bigChain has nonzero target coverage.
"""

from contextlib import ExitStack
from pathlib import Path

from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import bb_bw_reader


def check_exist(target_file: Path) -> None:
    """
    Check that the target file exists on disk.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target file is missing.
    """
    assert file_exists(target_file), "The target file does not exist."


def check_validity(target_file: Path) -> None:
    """Check that the target file is recognised as bigChain.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target file is missing, unreadable, or not bigChain.
    """
    with ExitStack() as stack:
        try:
            reader = stack.enter_context(bb_bw_reader(target_file))
        except Exception as exc:
            raise AssertionError(f"Could not open target file as bigChain: {exc}") from exc
        try:
            is_bigbed = reader.isBigBed()
        except AttributeError as exc:
            raise AssertionError(f"Could not open target file as bigChain: {exc}") from exc
        assert is_bigbed, "The target file is not recognised as bigChain."


def check_nonzero_entries(target_file: Path) -> None:
    """
    Check that the target assembly has at least one entry.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target file is unreadable, or
            the target assembly has no entries.
    """
    with bb_bw_reader(target_file) as reader:
        try:
            target_chrom_sizes = reader.chroms()
        except AttributeError as exc:
            raise AssertionError(f"Could not open target file as bigChain: {exc}") from exc
        entry_found = False
        for chrom_id, chrom_size in target_chrom_sizes.items():
            for _entry in reader.entries(chrom_id, 0, chrom_size):
                entry_found = True
                break
            if entry_found:
                break
        assert entry_found, "Target assembly has no entries."


def check_nonzero_target_coverage(target_file: Path) -> None:
    """
    Check that the target assembly has nonzero coverage.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target file is unreadable, or
            the target assembly has no coverage.
    """
    with bb_bw_reader(target_file) as reader:
        try:
            bigchain_header = reader.header()
        except AttributeError as exc:
            raise AssertionError(f"Could not open target file as bigChain: {exc}") from exc
        target_coverage = bigchain_header["nBasesCovered"]
        assert target_coverage > 0, "Target assembly has no coverage."
