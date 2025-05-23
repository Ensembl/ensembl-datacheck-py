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

This module checks for the validity of a VCF file. See: https://samtools.github.io/hts-specs/

Checks performed:
1. File is a text file (Error): Ensures the file is identified as a text file.
2. File ends with newline (Warning): Ensures the file ends with a newline character.

Checks to add:
1. File contains meta-information lines (prefixed with '##').
2. File contains a header line (prefixed with '#').
3. Data lines are tab-delimited, fields with no data have a '.', no tab at end of line, last data line must end with a line separator, 8 fixed fields.

These checks are run to ensure the proper formatting and validity of VCF files.
"""

import warnings
from ensembl.datacheck.functions.content_checks import ends_with_newline
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


def check_ends_with_newline(file_path):
    """
    Check that the file ends with a newline character.

    Args:
        file_path (str): The path to the file.
    """
    if not ends_with_newline(file_path):
        warning = f"The file {file_path} does not end in a newline character."
        warnings.warn(EnsemblDatacheckWarning(warning, "vcf", "check_ends_with_newline"))
