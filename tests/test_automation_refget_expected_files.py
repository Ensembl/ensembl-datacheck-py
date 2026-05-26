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

"""Unit tests for refget automation checks."""

from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation.automation_refget_expected_files import (
    _resolve_refget_relative_path,
    _validate_only_expected_refget_files,
)

REFGET_EXPECTED_FILES = [
    "cdna.hashes",
    "cds.hashes",
    "chrom.hashes",
    "pep.hashes",
    "seqs/cdna.txt.zst",
    "seqs/cds.txt.zst",
    "seqs/pep.txt.zst",
    "seqs/seq.txt.zst",
]


def test_resolve_refget_relative_path_supports_direct_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "release_22" / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_refget_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
    )

    assert relative_path == Path("release_22") / genome_uuid


def test_resolve_refget_relative_path_supports_one_level_nested_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "release_22" / "22_4" / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_refget_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
    )

    assert relative_path == Path("release_22") / "22_4" / genome_uuid


def test_resolve_refget_relative_path_fails_on_multiple_nested_matches(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "release_22" / "22_0" / genome_uuid).mkdir(parents=True)
    (tmp_path / "release_22" / "22_1" / genome_uuid).mkdir(parents=True)

    with pytest.raises(AssertionError, match="Multiple refget directories found"):
        _resolve_refget_relative_path(
            base_path=str(tmp_path),
            release_name=22,
            genome_uuid=genome_uuid,
        )


def test_validate_only_expected_refget_files_passes_when_exact_match(tmp_path):
    resource_relative = Path("release_22") / "22_4" / "6f93d0b5-3660-414e-8cda-6caf5df23371"
    resource_path = tmp_path / resource_relative
    resource_path.mkdir(parents=True)

    for expected_file in REFGET_EXPECTED_FILES:
        file_path = resource_path / expected_file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

    _validate_only_expected_refget_files(
        base_path=str(tmp_path),
        relative_path=resource_relative,
        expected_files=REFGET_EXPECTED_FILES,
        resource_label="refget",
    )


def test_validate_only_expected_refget_files_fails_when_extra_file_exists(tmp_path):
    resource_relative = Path("release_22") / "22_4" / "6f93d0b5-3660-414e-8cda-6caf5df23371"
    resource_path = tmp_path / resource_relative
    resource_path.mkdir(parents=True)

    for expected_file in REFGET_EXPECTED_FILES:
        file_path = resource_path / expected_file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

    (resource_path / "seqs" / "unexpected.txt").touch()

    with pytest.raises(AssertionError, match="Unexpected refget files"):
        _validate_only_expected_refget_files(
            base_path=str(tmp_path),
            relative_path=resource_relative,
            expected_files=REFGET_EXPECTED_FILES,
            resource_label="refget",
        )
