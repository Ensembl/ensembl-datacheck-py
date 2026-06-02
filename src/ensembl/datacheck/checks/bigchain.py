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
