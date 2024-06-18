import os

def check_line_length(file_path, max_length=80):
    """Check for lines longer than max_length and return warnings."""
    warnings = []
    with open(file_path, 'r') as file:
        for i, line in enumerate(file, 1):
            if len(line.rstrip()) > max_length:
                warnings.append(f"Line {i} is longer than {max_length} characters.")
    return warnings


def determine_fasta_type(file_path):
    """Determine if the FASTA file is nucleotide or protein."""
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
def check_allowed_characters(file_path, allowed_chars):
    """Check for allowed characters in a file."""
    allowed_chars = set(allowed_chars.upper())
    with open(file_path, 'r') as file:
        for line in file:
            if line.startswith(">"):
                continue
            for char in line.strip():
                if char.upper() not in allowed_chars:
                    return False
    return True

def check_ends_with_newline(file_path):
    """Check if the file ends with a newline character."""
    with open(file_path, 'rb') as file:
        file.seek(-1, os.SEEK_END)
        return file.read(1) == b'\n'