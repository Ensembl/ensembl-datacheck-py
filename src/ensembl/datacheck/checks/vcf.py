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
vcf.py

This module performs generic vcf checks.
"""

from pathlib import Path

from pysam import HTSFile, TabixFile, VariantFile

from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.vcf_utils import is_bgzf_compressed_file, is_vcf_file, vcf_reader


def check_exist(target_file: Path | None, source_file: Path | None):
    """
    Check that the target file exists on disk.

    Args:
        target_file: Path to the target file.
        source_file: Optional Path to the source file

    Raises:
        AssertionError: If the target file is missing.
    """
    assert file_exists(target_file), "The target VCF file does not exist."
    if source_file is not None:
        assert file_exists(source_file), "The source VCF file does not exist."

def check_has_vcf_gz_extension(target_file: Path | None, source_file: Path | None):
    """
    Check that the file(s) provided have the .vcf.gz extension.

    Standard extension is important for compatibility with older (<=1.24) versions of bcftools.

    Args:
        target_file: Path to the target file.
        source_file: Optional Path to the source file

    Raises:
        AssertionError: If the file does not have the .vcf.gz extension.
    """
    for file_path in [target_file, source_file]:
        if file_path is None:
            continue

        assert file_path.suffixes[-2:] == ['.vcf', '.gz'], f"File does not have .vcf.gz extension: {file_path}"

def check_is_bgzf_vcf_file(target_file: Path | None, source_file: Path | None):
    """
    Check that the file(s) provided is/are valid bgzipped vcf file(s).

    Args:
        target_file: The path to the file.
        source_file: Optional Path to the source file

    Raises:
        AssertionError: If the file is not identified as a bgzipped vcf file.
    """
    for file_path in [target_file, source_file]:
        if file_path is None:
            continue

        try:
            file: HTSFile
            with VariantFile(str(file_path), mode="r") as file:
                # Assess compression
                assert (
                    is_bgzf_compressed_file(file)
                ), f"File is not identified as a bgzipped file: {file_path}"

                # Assess format
                assert (
                    is_vcf_file(file)
                ), f"File is not identified as a vcf file: {file_path}"

        except (OSError, ValueError, NotImplementedError) as ex:
            raise AssertionError(
                f"Exception caught during VariantFile assessment of {file_path}:"
                + f" {ex}."
            ) from ex


def check_has_valid_index_file(target_file: Path, source_file: Path | None):
    """
    Check that an accompanying index file can be found and read appropriately.

    Args:
        target_file: The path to the file.
        source_file: Optional Path to the source file

    Raises:
        AssertionError: If the expected index file is not found or not readable
            as a TabixFile index.
    """

    for file_path in [target_file, source_file]:
        if file_path is None:
            continue

        csi_path = str(file_path) + '.csi'
        tbi_path = str(file_path) + '.tbi'

        index_file: str
        if file_exists(csi_path):
            index_file = csi_path
        elif file_exists(tbi_path):
            index_file = tbi_path
        else:
            raise AssertionError(
                f"Could not find index file for VCF file {file_path}."
            )

        try:
            with TabixFile(filename=str(file_path), index=index_file, mode="r"):
                pass
        except (ValueError) as ex:
            raise AssertionError(
                f"Missing index file: {index_file}"
            ) from ex
        except IOError as ex:
            raise AssertionError(
                f"Failed to open index file: {index_file}"
            ) from ex


def check_header(target_file: Path, source_file: Path | None):
    """
    Check that the VCF header has all fields required for bcftools processing.

    Args:
        target_file: Path to the target file.
        source_file: Optional Path to the source file

    Raises:
        AssertionError: If the file is not identified as a gzipped text file.
    """

    for file_path in [target_file, source_file]:
        if file_path is None:
            continue

        reader = vcf_reader(file_path)

        assert reader.get_header_type('fileformat') is not None, "The fileformat field is missing from the VCF header."

        column_header_line = str(reader.raw_header.rstrip('\n').split('\n')[-1])
        assert column_header_line.startswith('#'), "Column header line does not start with '#'."

        columns = column_header_line[1:].split('\t')

        assert columns[0] == 'CHROM', "Column header 'CHROM' not found at expected position."
        assert columns[1] == 'POS', "Column header 'POS' not found at expected position."
        assert columns[2] == 'ID', "Column header 'ID' not found at expected position."
        assert columns[3] == 'REF', "Column header 'REF' not found at expected position."
        assert columns[4] == 'ALT', "Column header 'ALT' not found at expected position."
