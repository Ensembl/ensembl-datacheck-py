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
from ensembl.datacheck_functions.content_checks import check_line_length,determine_fasta_type, check_allowed_characters,check_ends_with_newline
from ensembl.datacheck_functions.file_checks import is_text_file

def test_is_text_file(file_path):
    """Check that file is a text file"""
    assert is_text_file(file_path), f"The file {file_path} is not identified as a text file."

def test_check_line_length(file_path, max_length=80):
    """Check for lines longer than max_length and return warnings."""
    line_warnings = check_line_length(file_path, max_length)
    if line_warnings:
        for warning in line_warnings:
            warnings.warn(warning, UserWarning)

def test_check_allowed_characters(file_path):
    """Check that file contains only allowed characters"""
    type = determine_fasta_type(file_path)
    assert type != 'unknown', f"The file {file_path} does not match either Nucleotide or Protein configurations."
    if type == 'nucleotide':
        allowed_chars = "ACGTUMRSWYKVHDBN-"
        assert check_allowed_characters(file_path, allowed_chars) is True , f"The file {file_path} is not a valid nucleotide file."
    elif type == 'protein':
        allowed_chars = "ABCDEFGHIKLMNPQRSTVWXYZ*-"
        assert check_allowed_characters(file_path, allowed_chars) is True , f"The file {file_path} is not a valid nucleotide file."

def test_check_ends_with_newline(file_path):
    """Check that file ends properly"""
    if not check_ends_with_newline(file_path):
        warning = f"The file {file_path} does not end in a newline character."
        warnings.warn(warning, UserWarning)
