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

"""Unit tests for genome browser automation checks."""

from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation.automation_genome_browser_files_expected_files import (
    _resolve_genome_browser_relative_path,
    _validate_only_allowed_genome_browser_extensions,
    _validate_required_genome_browser_extensions_present,
)


def test_resolve_genome_browser_relative_path_supports_direct_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "release_22" / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_genome_browser_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
    )

    assert relative_path == Path("release_22") / genome_uuid


def test_resolve_genome_browser_relative_path_supports_one_level_nested_layout(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "release_22" / "22_4" / genome_uuid).mkdir(parents=True)

    relative_path = _resolve_genome_browser_relative_path(
        base_path=str(tmp_path),
        release_name=22,
        genome_uuid=genome_uuid,
    )

    assert relative_path == Path("release_22") / "22_4" / genome_uuid


def test_resolve_genome_browser_relative_path_fails_on_multiple_nested_matches(tmp_path):
    genome_uuid = "6f93d0b5-3660-414e-8cda-6caf5df23371"
    (tmp_path / "release_22" / "22_0" / genome_uuid).mkdir(parents=True)
    (tmp_path / "release_22" / "22_1" / genome_uuid).mkdir(parents=True)

    with pytest.raises(AssertionError, match="Multiple genome_browser_files directories found"):
        _resolve_genome_browser_relative_path(
            base_path=str(tmp_path),
            release_name=22,
            genome_uuid=genome_uuid,
        )


def test_validate_only_allowed_genome_browser_extensions_passes_for_allowed_files(tmp_path):
    resource_relative = Path("release_22") / "22_4" / "6f93d0b5-3660-414e-8cda-6caf5df23371"
    resource_path = tmp_path / resource_relative
    resource_path.mkdir(parents=True)

    allowed_files = [
        "chrom.hashes",
        "chrom.hashes.ncd",
        "chrom.sizes",
        "chrom.sizes.ncd",
        "contigs.bb",
        "contigs.bed",
        "gc.bw",
        "gc.wig",
        "genome_report.txt",
        "jump.ncd",
        "jump.txt",
        "repeats.dust.bb",
        "repeats.dust.bed",
        "repeats.repeatdetector.bb",
        "repeats.repeatdetector.bed",
        "repeats.trf.bb",
        "repeats.trf.bed",
        "simple-features.bb",
        "simple-features.bed",
        "transcripts.bb",
        "transcripts.bed",
    ]
    for file_name in allowed_files:
        (resource_path / file_name).touch()

    _validate_only_allowed_genome_browser_extensions(
        base_path=str(tmp_path),
        relative_path=resource_relative,
        resource_label="genome_browser_files",
    )


def test_validate_only_allowed_genome_browser_extensions_fails_on_disallowed_file(tmp_path):
    resource_relative = Path("release_22") / "22_4" / "6f93d0b5-3660-414e-8cda-6caf5df23371"
    resource_path = tmp_path / resource_relative
    resource_path.mkdir(parents=True)

    (resource_path / "chrom.hashes").touch()
    (resource_path / "unexpected.json").touch()

    with pytest.raises(AssertionError, match="Unexpected genome_browser_files files with disallowed extensions"):
        _validate_only_allowed_genome_browser_extensions(
            base_path=str(tmp_path),
            relative_path=resource_relative,
            resource_label="genome_browser_files",
        )


def test_validate_required_genome_browser_extensions_fails_when_extension_missing(tmp_path):
    resource_relative = Path("release_22") / "22_4" / "6f93d0b5-3660-414e-8cda-6caf5df23371"
    resource_path = tmp_path / resource_relative
    resource_path.mkdir(parents=True)

    files_missing_wig = [
        "chrom.hashes",
        "chrom.hashes.ncd",
        "chrom.sizes",
        "chrom.sizes.ncd",
        "contigs.bb",
        "contigs.bed",
        "gc.bw",
        "genome_report.txt",
        "jump.ncd",
        "jump.txt",
        "repeats.dust.bb",
        "repeats.dust.bed",
        "repeats.repeatdetector.bb",
        "repeats.repeatdetector.bed",
        "repeats.trf.bb",
        "repeats.trf.bed",
        "simple-features.bb",
        "simple-features.bed",
        "transcripts.bb",
        "transcripts.bed",
    ]
    for file_name in files_missing_wig:
        (resource_path / file_name).touch()

    with pytest.raises(AssertionError, match="Missing genome_browser_files required file extensions"):
        _validate_required_genome_browser_extensions_present(
            base_path=str(tmp_path),
            relative_path=resource_relative,
            resource_label="genome_browser_files",
        )
