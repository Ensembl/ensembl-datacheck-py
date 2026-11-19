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

"""Generic GFF checks.

Checks performed:
1. check_exist: Confirms the target and optional source files exist.
2. check_has_gff_gz_extension: Confirms files use the ``.gff.gz`` extension.
3. check_is_bgzf_gff_file: Confirms files use BGZF compression.
4. check_has_valid_index_file: Confirms files have a readable CSI or TBI index.
5. check_validity: Confirms files can be parsed as GFF files.
"""

from pathlib import Path

from pysam import BGZFile, TabixFile

from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.gff_utils import gff_reader

__all__ = [
    "check_exist",
    "check_has_gff_gz_extension",
    "check_has_valid_index_file",
    "check_is_bgzf_gff_file",
    "check_validity",
]


def check_exist(target_file: Path | None, source_file: Path | None) -> None:
    """Check that the target and optional source GFF files exist.

    Args:
        target_file: Path to the target GFF file.
        source_file: Optional path to a source GFF file.

    Raises:
        AssertionError: If a supplied file is missing.
    """
    assert file_exists(target_file), "The target GFF file does not exist."
    if source_file is not None:
        assert file_exists(source_file), "The source GFF file does not exist."


def check_has_gff_gz_extension(
    target_file: Path | None, source_file: Path | None
) -> None:
    """Check that supplied GFF files use the ``.gff.gz`` extension.

    Args:
        target_file: Path to the target GFF file.
        source_file: Optional path to a source GFF file.

    Raises:
        AssertionError: If a supplied file does not have a ``.gff.gz`` suffix.
    """
    for file_path in (target_file, source_file):
        if file_path is None:
            continue
        assert file_path.suffixes[-2:] == [".gff", ".gz"], (
            f"File does not have a .gff.gz extension: {file_path}"
        )


def check_is_bgzf_gff_file(target_file: Path | None, source_file: Path | None) -> None:
    """Check that supplied GFF files use BGZF compression.

    Args:
        target_file: Path to the target GFF file.
        source_file: Optional path to a source GFF file.

    Raises:
        AssertionError: If a supplied file cannot be read as a BGZF file.
    """
    for file_path in (target_file, source_file):
        if file_path is None:
            continue

        try:
            with BGZFile(str(file_path), "rb") as gff_file:
                gff_file.read(1)
        except (OSError, ValueError) as exc:
            raise AssertionError(
                f"File is not identified as BGZF-compressed: {file_path}"
            ) from exc
        except AssertionError as exc:
            raise AssertionError(
                f"File is not identified as BGZF-compressed: {file_path}"
            ) from exc


def check_has_valid_index_file(
    target_file: Path | None, source_file: Path | None
) -> None:
    """Check that supplied GFF files have readable CSI or TBI indexes.

    Args:
        target_file: Path to the target GFF file.
        source_file: Optional path to a source GFF file.

    Raises:
        AssertionError: If an index is absent or cannot be read as a Tabix
            index.
    """
    for file_path in (target_file, source_file):
        if file_path is None:
            continue

        csi_path = Path(f"{file_path}.csi")
        tbi_path = Path(f"{file_path}.tbi")
        if file_exists(csi_path):
            index_file = csi_path
        elif file_exists(tbi_path):
            index_file = tbi_path
        else:
            raise AssertionError(
                f"Could not find an index file for GFF file {file_path}."
            )

        try:
            with TabixFile(filename=str(file_path), index=str(index_file)):
                pass
        except (OSError, ValueError) as exc:
            raise AssertionError(
                f"Could not read GFF index file: {index_file}"
            ) from exc


def check_validity(target_file: Path | None, source_file: Path | None) -> None:
    """Check that supplied files can be parsed as GFF files.

    Args:
        target_file: Path to the target GFF file.
        source_file: Optional path to a source GFF file.

    Raises:
        AssertionError: If a supplied file cannot be parsed by ``gffutils``.
    """
    for file_path in (target_file, source_file):
        if file_path is not None:
            try:
                gff_reader(file_path)
            except Exception as exc:
                raise AssertionError(f"Could not parse GFF file: {file_path}") from exc
