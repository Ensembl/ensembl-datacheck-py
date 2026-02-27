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
bigbed.py

This module performs basic BigBed checks.

Checks performed:
1. check_exist: Asserts that the target BigBed path exists.
2. check_validity: Asserts that the target file is readable as BigBed.
"""

from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import bb_bw_reader

def check_exist(target_file):
    """
    Check that the target file exists on disk.

    Args:
        target_file (pathlib.Path or None): Path to the target file.

    Raises:
        AssertionError: If the target file is missing.
    """
    assert file_exists(target_file), "The target file does not exist."

def check_validity(target_file):
    """
    Check that the target file is recognised as BigBed.

    Args:
        target_file (pathlib.Path or None): Path to the target file.

    Raises:
        AssertionError: If the file is missing, unreadable, or not BigBed.
    """
    assert file_exists(target_file), "The target file does not exist."
    reader = None
    try:
        reader = bb_bw_reader(target_file)
        assert reader is not None, "Could not open target file as BigBed."
        assert reader.isBigBed(), "The target file is not recognised as BigBed."
    except Exception as exc:
        raise AssertionError(
            f"Could not validate target file as BigBed: {exc}"
        ) from exc
    finally:
        if reader is not None:
            reader.close()
