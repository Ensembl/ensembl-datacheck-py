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

from pathlib import Path
import re
import shutil
import subprocess

from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.io_utils import load_bigbed_info


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
    """Check that the target file is readable as bigChain.

    This function requires the bigBedToBed executable.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target file is missing, unreadable, or not bigChain.
    """
    try:
        load_bigbed_info(target_file)
    except (RuntimeError, ValueError) as exc:
        raise AssertionError("The target file is not recognised as bigChain.") from exc
    except FileNotFoundError as exc:
        raise FileNotFoundError("The target file does not exist.") from exc

    bigbed_to_bed_exe = shutil.which("bigBedToBed")
    if not bigbed_to_bed_exe:
        raise RuntimeError("bigBedToBed executable not found")

    cmd_args = [bigbed_to_bed_exe, "-maxItems=1", str(target_file), "/dev/null"]
    process = subprocess.run(cmd_args, stderr=subprocess.PIPE, check=False, text=True)

    if process.returncode != 0:
        err_msg = process.stderr.strip()
        read_err_regex = re.compile(fr"udc couldn't read [0-9]+ bytes from {target_file}, did read [0-9]+")
        if read_err_regex.fullmatch(err_msg):
            raise ValueError(f"bigChain data accessibility: {err_msg}")
        raise RuntimeError(err_msg)


def check_nonzero_entries(target_file: Path) -> None:
    """
    Check that the bigChain file has at least one entry.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target bigChain file is unreadable,
            or it has no entries.
    """
    bigbed_info = load_bigbed_info(target_file)
    assert bigbed_info["itemCount"] > 0, "bigChain file has no entries."


def check_nonzero_target_coverage(target_file: Path) -> None:
    """
    Check that the target assembly has nonzero coverage.

    Args:
        target_file: Path of target file.

    Raises:
        AssertionError: If the target file is unreadable, or
            the target assembly has no coverage.
    """
    bigbed_info = load_bigbed_info(target_file)
    assert bigbed_info["basesCovered"] > 0, "Target assembly has no coverage."
