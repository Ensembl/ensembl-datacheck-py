import os

def file_exists(file_path):
    """Check if the file exists"""
    if not file_path:
        return False
    return os.path.exists(file_path)

def file_size(file_path):
    if not file_path or not os.path.exists(file_path):
        return None
    return os.path.getsize(file_path)


def is_text_file(file_path):
    """Check if the file is a text file."""
    try:
        with open(file_path, 'r') as file:
            file.read()
        return True
    except Exception:
        return False