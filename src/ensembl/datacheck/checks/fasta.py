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
fasta.py

This module checks for the validity of a FASTA file. See: https://zhanggroup.org/FASTA/

Checks performed:
1. File is a text file (Error): Ensures the file is identified as a text file.
2. Line length check (Warning): Ensures all lines are under 80 characters.
3. Allowed characters check (Error): Ensures the file contains only allowed characters for nucleotide or protein sequences.
4. File ends with newline (Warning): Ensures the file ends with a newline character.

These checks are run to ensure the proper formatting and validity of FASTA files.
"""

import warnings
from ensembl.datacheck.functions.content_checks import line_length_check, allowed_character_check, ends_with_newline
from ensembl.datacheck.functions.file_checks import is_text_file
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning

def check_if_text_file(file_path):
    """
    Check that the file is a text file.

    Args:
        file_path (str): The path to the file.

    Raises:
        AssertionError: If the file is not identified as a text file.
    """
    assert is_text_file(file_path), "The file is not identified as a text file."

def check_line_length(file_path, max_length=80):
    """
    Check for lines longer than the specified maximum length and issue warnings.

    Args:
        file_path (str): The path to the file.
        max_length (int): The maximum allowed line length. Defaults to 80.
    """
    line_warnings = line_length_check(file_path, max_length)
    if line_warnings:
        for warning in line_warnings:
            warnings.warn(EnsemblDatacheckWarning(warning, "fasta", "check_line_length"))

def check_allowed_character(file_path):
    """
    Check that the file contains only allowed characters for nucleotide or protein sequences.

    Args:
        file_path (str): The path to the file.

    Raises:
        AssertionError: If any line contains characters not allowed in nucleotide or protein sequences.
    """
    line = allowed_character_check(file_path, "ABCDEFGHIKLMNPQRSTUVWXYZ*-")
    assert line is True or line is None, f"Line {line} does not match either nucleotide or protein configurations."

def check_ends_with_newline(file_path):
    """
    Check that the file ends with a newline character.

    Args:
        file_path (str): The path to the file.
    """
    if not ends_with_newline(file_path):
        warning = f"The file {file_path} does not end in a newline character."
        warnings.warn(EnsemblDatacheckWarning(warning, "fasta", "check_ends_with_newline"))
