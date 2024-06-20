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

This tests for proper formatting of a fasta file. See: https://zhanggroup.org/FASTA/
The tests are:
File is a text file
Line length is under 80 char (warning only)
Only has allowed characters
Print allowed type
Ensure the file ends properly (warning only)
"""

import warnings
from ensembl.datacheck.functions.content_checks import line_length_check, allowed_character_check, ends_with_newline
from ensembl.datacheck.functions.file_checks import is_text_file
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning
def check_if_text_file(file_path):
    """Check that file is a text file"""
    assert is_text_file(file_path), f"The file is not identified as a text file."

def check_line_length(file_path, max_length=80):
    """Check for lines longer than max_length and return warnings."""
    line_warnings = line_length_check(file_path, max_length)
    if line_warnings:
        for warning in line_warnings:
            warnings.warn(EnsemblDatacheckWarning(warning, "fasta", "check_line_length"))

def check_allowed_character(file_path):
    """Check that file contains only allowed characters"""
    line = allowed_character_check(file_path, "ABCDEFGHIKLMNPQRSTUVWXYZ*-")
    assert not isinstance(line, int), f"Line {line} does not match either Nucleotide or Protein configurations."

def check_ends_with_newline(file_path):
    """Check that file ends properly"""
    if not ends_with_newline(file_path):
        warning = f"The file {file_path} does not end in a newline character."
        warnings.warn(EnsemblDatacheckWarning(warning, "fasta", "check_ends_with_newline"))
