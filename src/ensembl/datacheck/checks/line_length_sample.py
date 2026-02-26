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
line_length_sample.py

This module provides a minimal params-driven check for text files.

Checks performed:
1. target_file is provided (Error)
2. params contains N (Error)
3. N is a positive integer (Error)
4. target_file has at least N lines (Error)
5. N random lines have length 3, excluding newline characters (Error)
"""

import random


def check_random_sample_line_length(target_file, params):
    """
    Sample N random lines from target_file and ensure each sampled line has length 3.

    Args:
        target_file (pathlib.Path or None): The target file path.
        params (dict): Parsed command-line params from --params.

    Raises:
        AssertionError: If inputs are missing/invalid, file has too few lines, or any
            sampled line does not have length 3.
    """
    assert target_file is not None, "A target file is required (--target-file or --file)."
    assert "N" in params, "Parameter N is required (--params N=<positive integer>)."

    try:
        sample_size = int(params["N"])
    except ValueError as exc:
        raise AssertionError("Parameter N must be an integer.") from exc

    assert sample_size > 0, "Parameter N must be greater than 0."

    with open(target_file, "r") as file_handle:
        lines = file_handle.readlines()

    total_lines = len(lines)
    assert total_lines >= sample_size, (
        f"Requested N={sample_size} lines but target_file has only {total_lines} lines."
    )

    sampled_indexes = random.sample(range(total_lines), sample_size)
    invalid_lines = []

    for line_index in sampled_indexes:
        line_value = lines[line_index].rstrip("\r\n")
        if len(line_value) != 3:
            invalid_lines.append((line_index + 1, len(line_value)))

    assert not invalid_lines, (
        "Sampled lines must each have length 3. "
        f"Invalid sampled lines (line_number, length): {invalid_lines}"
    )
