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

import os

def line_length_check(file_path, max_length=80):
    """
    Check for lines longer than the specified maximum length in a file.

    Args:
        file_path (str): The path to the file.
        max_length (int): The maximum allowed line length. Defaults to 80.

    Returns:
        list: A list of warnings for lines longer than the specified length.
    """
    warnings = []
    with open(file_path, 'r') as file:
        for i, line in enumerate(file, 1):
            if len(line.rstrip()) > max_length:
                warnings.append(f"Line {i} is longer than {max_length} characters.")
    return warnings

def determine_fasta_type(file_path):
    """
    Determine if a FASTA file contains nucleotide or protein sequences.

    Args:
        file_path (str): The path to the FASTA file.

    Returns:
        str: 'nucleotide' if the file contains nucleotide sequences,
             'protein' if it contains protein sequences,
             'unknown' if the type cannot be determined.
    """
    nucleotide_chars = set("ACGTUMRSWYKVHDBN-")
    protein_chars = set("ABCDEFGHIKLMNPQRSTVWXYZ*-")

    with open(file_path, 'r') as file:
        for line in file:
            if line.startswith(">"):
                continue
            for char in line.strip():
                if char.upper() in protein_chars and char.upper() not in nucleotide_chars:
                    return 'protein'
                if char.upper() in nucleotide_chars and char.upper() not in protein_chars:
                    return 'nucleotide'
    return 'unknown'

def allowed_character_check(file_path, allowed_chars):
    """
    Check if a file contains only allowed characters.

    Args:
        file_path (str): The path to the file.
        allowed_chars (str): A string of allowed characters.

    Returns:
        int or bool: The line number of the first disallowed character, or True if all characters are allowed.
    """
    count = 0
    allowed_chars = set(allowed_chars.upper())
    with open(file_path, 'r') as file:
        for line in file:
            count += 1
            if line.startswith(">"):
                continue
            for char in line.strip():
                if char.upper() not in allowed_chars:
                    return count
    return True

def ends_with_newline(file_path):
    """
    Check if a file ends with a newline character.

    Args:
        file_path (str): The path to the file.

    Returns:
        bool: True if the file ends with a newline character, False otherwise.
    """
    with open(file_path, 'rb') as file:
        file.seek(-1, os.SEEK_END)
        return file.read(1) == b'\n'
