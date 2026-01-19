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
        list: A list with the lines longer than the specified length.
    """
    incorrect_lines = []
    with open(file_path, "r") as file:
        incorrect_lines = [i for i, line in enumerate(file, 1) if len(line.rstrip()) > max_length]
    return incorrect_lines


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

    with open(file_path, "r") as file:
        for line in file:
            if line.startswith(">"):
                continue
            # Check if the characters in the line are a subset of nucleotide or protein, but not
            # both. If unsure, check next line until one makes it clear.
            line_chars = set(map(str.upper, line.strip()))
            if line_chars.issubset(nucleotide_chars):
                if not line_chars.issubset(protein_chars):
                    return "nucleotide"
            elif line_chars.issubset(protein_chars):
                return "protein"
    return "unknown"


def allowed_character_check(file_path, allowed_chars):
    """
    Check if a file contains only allowed characters.

    Args:
        file_path (str): The path to the file.
        allowed_chars (str): A string of allowed characters.

    Returns:
        list: A list with the lines containing disallowed character.
    """
    allowed_chars = set(allowed_chars.upper())
    incorrect_lines = []
    with open(file_path, "r") as file:
        for i, line in enumerate(file, 1):
            if line.startswith(">"):
                continue
            line_chars = set(map(str.upper, line.strip()))
            if not line_chars.issubset(allowed_chars):
                incorrect_lines.append(i)
    return incorrect_lines


def ends_with_newline(file_path):
    """
    Check if a file ends with a newline character.

    Args:
        file_path (str): The path to the file.

    Returns:
        bool: True if the file ends with a newline character, False otherwise.
    """
    with open(file_path, "rb") as file:
        file.seek(-1, os.SEEK_END)
        return file.read(1) == b"\n"
