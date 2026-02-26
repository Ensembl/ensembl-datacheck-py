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
line_count_match.py

This module provides a minimal comparative check for two text files.

Checks performed:
1. target_file is provided (Error)
2. source_file is provided (Error)
3. target_file and source_file have the same number of lines (Error)
"""

def check_line_count_match(target_file, source_file):
    """
    Check that target_file and source_file have the same number of lines.

    Args:
        target_file (pathlib.Path or None): The target file path.
        source_file (pathlib.Path or None): The source file path.

    Raises:
        AssertionError: If either file path is missing or line counts differ.
    """
    assert target_file is not None, "A target file is required (--target-file or --file)."
    assert source_file is not None, "A source file is required (--source-file)."

    with open(target_file, "r") as target_handle:
        target_line_count = sum(1 for _ in target_handle)

    with open(source_file, "r") as source_handle:
        source_line_count = sum(1 for _ in source_handle)

    assert target_line_count == source_line_count, (
        f"Line counts differ: target_file has {target_line_count} lines, "
        f"source_file has {source_line_count} lines."
    )
