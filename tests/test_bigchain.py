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
import shutil
import subprocess
from textwrap import dedent
from typing import Generator, Sequence


from pytest import fixture, MonkeyPatch, raises

from ensembl.datacheck.checks import bigchain


def _fake_shutil_which(cmd: str) -> str:
    return cmd


def _fake_subprocess_run(
    cmd_args: Sequence,
    *args,  # pylint: disable=unused-argument
    **kwargs,  # pylint: disable=unused-argument
) -> subprocess.CompletedProcess:
    """Monkeypatched subproccess.run call."""

    # To facilitate pattern matching, we simplify arguments,
    # replacing each Path with its basename.
    simplified_args = [
        cmd_arg.name if isinstance(cmd_arg, Path) else cmd_arg
        for cmd_arg in cmd_args
    ]

    bigbed_info_by_file_name = {
        "human_chimp.empty.bb": dedent(
            """\
        version: 4
        fieldCount: 12
        hasHeaderExtension: yes
        isCompressed: yes
        isSwapped: 0
        extraIndexCount: 0
        itemCount: 0
        primaryDataSize: 8
        zoomLevels: 0
        chromCount: 0
        basesCovered: 0
        meanDepth (of bases covered): 0.000000
        minDepth: 0.000000
        maxDepth: 0.000000
        std of depth: 0.000000
        """
        ),
        "human_chimp.single.bb": dedent(
            """\
        version: 4
        fieldCount: 12
        hasHeaderExtension: yes
        isCompressed: yes
        isSwapped: 0
        extraIndexCount: 0
        itemCount: 1
        primaryDataSize: 74
        primaryIndexSize: 6,204
        zoomLevels: 1
        chromCount: 1
        basesCovered: 399
        meanDepth (of bases covered): 1.000000
        minDepth: 1.000000
        maxDepth: 1.000000
        std of depth: 0.000000
        """
        ),
        "human_chimp.truncated.bb": dedent(
            """\
        version: 4
        fieldCount: 12
        hasHeaderExtension: yes
        isCompressed: yes
        isSwapped: 0
        extraIndexCount: 0
        itemCount: 1
        primaryDataSize: 74
        primaryIndexSize: 6,204
        zoomLevels: 1
        chromCount: 1
        basesCovered: 399
        meanDepth (of bases covered): 1.000000
        minDepth: 1.000000
        maxDepth: 1.000000
        std of depth: 0.000000
        """
        ),
    }

    match simplified_args:
        case ["bigBedInfo", "human.chrom.sizes"]:

            file_path = cmd_args[1]
            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=255,
                stdout="",
                stderr=f"{file_path} is not a big bed file\n",
            )

        case ["bigBedInfo", "human_chimp.empty.bb"]:

            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout=bigbed_info_by_file_name["human_chimp.empty.bb"],
                stderr="",
            )

        case ["bigBedInfo", "human_chimp.single.bb"]:

            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout=bigbed_info_by_file_name["human_chimp.single.bb"],
                stderr="",
            )

        case ["bigBedInfo", "human_chimp.truncated.bb"]:

            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout=bigbed_info_by_file_name["human_chimp.truncated.bb"],
                stderr="",
            )

        case ["bigBedInfo", "nonexistent_file.txt"]:

            file_path = cmd_args[1]
            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=255,
                stdout="",
                stderr=f"Couldn't open {file_path}\n",
            )

        case ["bigBedToBed", "-maxItems=1", "human_chimp.empty.bb", "/dev/null"]:

            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout="",
                stderr="",
            )

        case ["bigBedToBed", "-maxItems=1", "human_chimp.single.bb", "/dev/null"]:

            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=0,
                stdout="",
                stderr="",
            )

        case ["bigBedToBed", "-maxItems=1", "human_chimp.truncated.bb", "/dev/null"]:

            file_path = cmd_args[2]
            process = subprocess.CompletedProcess(
                args=cmd_args,
                returncode=255,
                stdout="",
                stderr=f"udc couldn't read 4 bytes from {file_path}, did read 0\n",
            )

        case _:
            raise ValueError(f"fake subprocess not implemented for command arguments: {cmd_args}")

    return process


def _setup_bigchain_file(bigbed_file_name: str) -> Path:
    test_file_dir_path = Path(__file__).parent / "file" / "bigchain"
    return test_file_dir_path / bigbed_file_name


@fixture(scope="module")
def human_chrom_sizes_file() -> Generator[Path, None, None]:
    """Human chrom-sizes file fixture."""
    test_file_dir_path = Path(__file__).parent / "file" / "bigchain"
    yield test_file_dir_path / "human.chrom.sizes"


@fixture(scope="module")
def single_entry_bigchain_file() -> Generator[Path, None, None]:
    """Single-entry bigChain file fixture."""
    single_entry_bigchain_path = _setup_bigchain_file("human_chimp.single.bb")
    yield single_entry_bigchain_path


@fixture(scope="module")
def truncated_bigchain_file() -> Generator[Path, None, None]:
    """Truncated bigChain file fixture."""
    single_entry_bigchain_path = _setup_bigchain_file("human_chimp.single.bb")
    truncated_bigchain_path = _setup_bigchain_file("human_chimp.truncated.bb")
    shutil.copy(single_entry_bigchain_path, truncated_bigchain_path)
    os.truncate(truncated_bigchain_path, 1234)
    yield truncated_bigchain_path
    truncated_bigchain_path.unlink()


@fixture(scope="module")
def zero_entry_bigchain_file() -> Generator[Path, None, None]:
    """Empty bigChain file fixture."""
    empty_bigchain_path = _setup_bigchain_file("human_chimp.empty.bb")
    yield empty_bigchain_path


def test_check_exist_no_file():
    """Test bigChain existence check on nonexistent file."""
    with raises(AssertionError, match=re.escape("The target file does not exist.")):
        bigchain.check_exist(Path("/path/to/nonexistent_file.txt"))


def test_check_exist_zero_entry_bigchain_file(zero_entry_bigchain_file: Path):
    """Test bigChain existence check on zero-entry bigChain file."""
    bigchain.check_exist(zero_entry_bigchain_file)


def test_check_validity_no_file(monkeypatch: MonkeyPatch):
    """Test bigChain validity check on nonexistent file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    with raises(FileNotFoundError, match=re.escape("The target file does not exist.")):
        bigchain.check_validity(Path("/path/to/nonexistent_file.txt"))


def test_check_validity_non_bigchain_file(monkeypatch: MonkeyPatch, human_chrom_sizes_file: Path):
    """Test bigChain validity check on non-bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    with raises(AssertionError, match=re.escape("The target file is not recognised as bigChain.")):
        bigchain.check_validity(human_chrom_sizes_file)


def test_check_validity_single_entry_bigchain_file(
    monkeypatch: MonkeyPatch, single_entry_bigchain_file: Path
):
    """Test bigChain validity check on single-entry bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    bigchain.check_validity(single_entry_bigchain_file)


def test_check_validity_truncated_bigchain_file(monkeypatch: MonkeyPatch, truncated_bigchain_file: Path):
    """Test bigChain validity check on truncated bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    with raises(ValueError, match="bigChain data accessibility"):
        bigchain.check_validity(truncated_bigchain_file)


def test_check_validity_zero_entry_bigchain_file(monkeypatch: MonkeyPatch, zero_entry_bigchain_file: Path):
    """Test bigChain validity check on zero-entry bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    bigchain.check_validity(zero_entry_bigchain_file)


def test_check_nonzero_entries_single_entry_bigchain_file(
    monkeypatch: MonkeyPatch, single_entry_bigchain_file: Path
):
    """Test bigChain nonzero entries check on single-entry bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    bigchain.check_nonzero_entries(single_entry_bigchain_file)


def test_check_nonzero_entries_zero_entry_bigchain_file(
    monkeypatch: MonkeyPatch, zero_entry_bigchain_file: Path
):
    """Test bigChain nonzero entries check on zero-entry bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    with raises(AssertionError, match=re.escape("bigChain file has no entries.")):
        bigchain.check_nonzero_entries(zero_entry_bigchain_file)


def test_check_nonzero_target_coverage_single_entry_bigchain_file(
    monkeypatch: MonkeyPatch, single_entry_bigchain_file: Path
):
    """Test nonzero target coverage check on single-entry bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    bigchain.check_nonzero_target_coverage(single_entry_bigchain_file)


def test_check_nonzero_target_coverage_zero_entry_bigchain_file(
    monkeypatch: MonkeyPatch, zero_entry_bigchain_file: Path
):
    """Test nonzero target coverage check on zero-entry bigChain file."""
    monkeypatch.setattr(shutil, "which", _fake_shutil_which)
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    with raises(AssertionError, match=re.escape("Target assembly has no coverage.")):
        bigchain.check_nonzero_target_coverage(zero_entry_bigchain_file)
