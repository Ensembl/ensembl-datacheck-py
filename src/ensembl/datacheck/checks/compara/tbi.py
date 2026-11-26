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
"""Module of Compara tabix index checks."""

from contextlib import ExitStack
from pathlib import Path
import re

from pysam import TabixFile


def check_target_file_exists(target_file: Path | None):
    """Check that the tabix index file exists.

    Args:
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the tabix index file is not found.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert target_file.is_file(), "tabix index file not found"


def check_target_file_valid(source_file: Path | None, target_file: Path | None):
    """Check that the target file is a valid tabix index.

    Args:
        source_file: Path of tabix-indexed data file path.
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the target file is missing, unreadable, or not a tabix index.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert source_file is not None, "--source-file must specify a tabix-indexed data file"
    with ExitStack() as stack:
        try:
            _tbx = stack.enter_context(TabixFile(source_file, index=target_file))
        except OSError as exc:
            exc_msg = str(exc)
            if exc_msg == f"file `{source_file}` not found":
                raise AssertionError("tabix-indexed data file not found") from exc
            if exc_msg == f"index `{target_file}` not found":
                raise AssertionError("tabix index file not found") from exc
            if exc_msg in (
                f"could not open file `{source_file}`",
                f"could not open index for `{source_file}`",
            ):
                raise AssertionError("could not open target file as tabix index") from exc
            raise


def check_target_file_current(source_file: Path | None, target_file: Path | None):
    """Check that the target file is a current tabix index.

    Args:
        source_file: Path of tabix-indexed data file path.
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the target file is not a current tabix index.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert source_file is not None, "--source-file must specify a tabix-indexed data file"
    assert target_file.is_file(), "tabix index file not found"
    assert source_file.is_file(), "tabix-indexed data file not found"

    target_file_mtime = target_file.stat().st_mtime
    source_file_mtime = source_file.stat().st_mtime
    assert target_file_mtime >= source_file_mtime, "tabix index file is older than data file"


def check_source_file_compression(source_file: Path | None, target_file: Path | None):
    """Check that the source file is bgzip-compressed.

    Args:
        source_file: Path of tabix-indexed data file path.
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the source file is not bgzip-compressed.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert source_file is not None, "--source-file must specify a tabix-indexed data file"
    assert target_file.is_file(), "tabix index file not found"
    assert source_file.is_file(), "tabix-indexed data file not found"

    non_bgzf_msg = "tabix-indexed data file must be bgzip-compressed"
    with ExitStack() as stack:
        try:
            tbx = stack.enter_context(TabixFile(source_file, index=target_file))
        except NotImplementedError as exc:
            # source_file may be compressed by another method
            no_seek_regex = re.compile(r"seek not implemented in files compressed by method \S+")
            if no_seek_regex.fullmatch(str(exc)):
                raise AssertionError(non_bgzf_msg) from exc
            raise
        assert tbx.compression == "BGZF", non_bgzf_msg


def check_source_file_truncation(source_file: Path | None, target_file: Path | None):
    """Check that the source file is truncated.

    Args:
        source_file: Path of tabix-indexed data file path.
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the source file is truncated.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert source_file is not None, "--source-file must specify a tabix-indexed data file"
    assert target_file.is_file(), "tabix index file not found"
    assert source_file.is_file(), "tabix-indexed data file not found"
    with TabixFile(source_file, index=target_file) as tbx:
        try:
            tbx.check_truncation()
        except OSError as exc:
            exc_msg = str(exc)
            if exc_msg == "no BGZF EOF marker; file may be truncated":
                raise AssertionError("no BGZF EOF marker; tabix-indexed data file may be truncated") from exc
            raise


def check_nonzero_reference_count(source_file: Path | None, target_file: Path | None):
    """Check that the tabix index file has at least one reference.

    Args:
        source_file: Path of tabix-indexed data file path.
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the tabix index file contains no references.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert source_file is not None, "--source-file must specify a tabix-indexed data file"
    assert target_file.is_file(), "tabix index file not found"
    assert source_file.is_file(), "tabix-indexed data file not found"
    with TabixFile(source_file, index=target_file) as tbx:
        assert len(tbx.contigs) != 0, "tabix index file contains no references"


def check_nonzero_row_counts(source_file: Path | None, target_file: Path | None):
    """Check that the tabix-indexed data file has at least one row for each reference.

    Args:
        source_file: Path of tabix-indexed data file path.
        target_file: Path of tabix index file.

    Raises:
        AssertionError: If the data file lacks rows for a reference.
    """
    assert target_file is not None, "--target-file must specify a tabix index file"
    assert source_file is not None, "--source-file must specify a tabix-indexed data file"
    assert target_file.is_file(), "tabix index file not found"
    assert source_file.is_file(), "tabix-indexed data file not found"
    with TabixFile(source_file, index=target_file) as tbx:
        # NB: this check could fail HARD without this confirmation the source file is BGZF.
        assert tbx.compression == "BGZF", "tabix-indexed data file must be bgzip-compressed"
        # We check references in reverse order, on the assumption we're more likely to
        # find issues near the end of the tabix-indexed data file than near the start.
        ref_ids = list(reversed(tbx.contigs))
        assert len(ref_ids) != 0, "tabix index file contains no references"
        for ref_id in ref_ids:
            ref_row_count = 0
            for _row in tbx.fetch(reference=ref_id):
                ref_row_count += 1
                break
            assert ref_row_count != 0, f"tabix-indexed data file has no entries for reference {ref_id}"
