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

"""OutputValidationBase: the compression -> index -> format -> completeness stage runner."""

import struct
import zlib
from pathlib import Path

import pytest

from .common import (FAIL, PASS, SKIP, STAGES, FileReport, Outcome, StageResult, inspect_compression,
                     stage_from_outcome)
from .file_types import INDEX_SUFFIXES
from .gene_models import cached_gff3_scan


class OutputValidationBase:
    """Shared stage logic: compression, index, format and completeness."""

    def __init__(self, metadata, settings):
        self.metadata = metadata
        self.settings = settings

    def check_compression(self, path, require_bgzf=True, require_gzip=False):
        info = inspect_compression(path)
        if info.kind == "missing":
            return StageResult("compression", FAIL, info.error), info
        if not info.readable:
            return StageResult("compression", FAIL, info.error), info
        if info.kind == "plain":
            if require_bgzf or require_gzip:
                return StageResult("compression", FAIL, "File is not gzip/BGZF compressed"), info
            return StageResult("compression", SKIP, "Plain text file; compression not required",
                               expected_skip=True), info
        if info.kind == "gzip" and require_bgzf:
            return StageResult("compression", FAIL, "File is gzip but not BGZF compressed"), info
        if info.kind == "bgzf" and not info.has_eof:
            return StageResult("compression", FAIL, "Missing BGZF EOF marker; file may be truncated"), info
        return StageResult("compression", PASS, f"{info.kind}, {info.uncompressed_size} bytes uncompressed"), info

    def check_index(self, path, info, parsed, checker):
        try:
            outcome = checker(path, info, parsed)
        except (OSError, ValueError, struct.error, zlib.error, EOFError) as exc:
            outcome = Outcome(errors=[f"Index could not be read: {exc}"])
        data_path = Path(path)
        data_mtime = data_path.stat().st_mtime_ns
        for suffix in INDEX_SUFFIXES:
            index_path = Path(f"{data_path}{suffix}")
            if index_path.is_file() and data_mtime > index_path.stat().st_mtime_ns:
                outcome.warnings.append(
                    f"Data file {data_path.name} is newer than index {index_path.name}; "
                    "the index may be stale and should be regenerated")
        return stage_from_outcome("index", outcome), outcome.warnings

    def check_format(self, path, scanner):
        try:
            parsed = scanner(path)
        except (OSError, ValueError, zlib.error, EOFError) as exc:
            return StageResult("format", FAIL, f"File could not be parsed: {exc}"), None, []
        outcome = Outcome(errors=parsed.errors, warnings=parsed.warnings, skip=getattr(parsed, "skip", None))
        return stage_from_outcome("format", outcome), parsed, parsed.warnings

    def check_completeness(self, parsed, checker):
        try:
            outcome = checker(parsed)
        except (OSError, ValueError, zlib.error, EOFError) as exc:
            outcome = Outcome(skip=f"Completeness check could not run: {exc}")
        return stage_from_outcome("completeness", outcome), outcome.warnings

    def run_selected_stage(self, stage, path, label, scanner, index_checker,
                           completeness_checker, require_bgzf, require_gzip,
                           not_applicable_reason, format_checker):
        """Run one requested stage, reading only the supporting data it needs."""
        path = Path(path)
        report = FileReport(label, path)
        if stage == "compression":
            result, _ = self.check_compression(path, require_bgzf, require_gzip)
        elif stage == "index":
            if index_checker is None:
                result = StageResult(stage, SKIP, "No index expected for this file", expected_skip=True)
            else:
                info = inspect_compression(path)
                if not info.readable:
                    result = StageResult(stage, FAIL, f"Cannot read data for index validation: {info.error}")
                else:
                    result, notes = self.check_index(path, info, None, index_checker)
                    report.warnings.extend(notes)
        else:
            if stage == "completeness" and completeness_checker is None:
                result = StageResult(stage, SKIP, not_applicable_reason, expected_skip=True)
            else:
                parsed_result, parsed, notes = self.check_format(path, scanner)
                report.warnings.extend(notes)
                if stage == "format":
                    result = parsed_result
                    if result.status == PASS and format_checker is not None:
                        try:
                            external = format_checker(path)
                        except (OSError, ValueError, zlib.error, EOFError) as exc:
                            external = Outcome(errors=[f"Format validator could not run: {exc}"])
                        result = stage_from_outcome(stage, external, external.note)
                        report.warnings.extend(external.warnings)
                elif parsed is None or parsed_result.status != PASS:
                    result = StageResult(stage, FAIL,
                                         f"Cannot read records for completeness: {parsed_result.reason}")
                else:
                    result, notes = self.check_completeness(parsed, completeness_checker)
                    report.warnings.extend(notes)
        for name in STAGES:
            report.add(result if name == stage else StageResult(
                name, SKIP, "Not selected", expected_skip=True))
        return report

    def run(self, path, label, scanner, index_checker, completeness_checker, require_bgzf=True,
            require_gzip=False, not_applicable_reason="Not applicable for this file", format_checker=None):
        """Run all stages in order applying the stop rules from readme.md.

        Index structure and retrieval run first; parsed-content consistency belongs to format.

        index_checker / completeness_checker may be None when the stage does not apply; the stage is
        then reported as SKIP with not_applicable_reason and does not affect the overall result.
        """
        selected = self.settings.get("validation_stage", "all")
        selected = {"bgzip": "compression", "bgzf": "compression", "completness": "completeness"}.get(selected, selected)
        if selected != "all":
            if selected not in STAGES:
                raise pytest.UsageError(f"Unknown validation stage: {selected}")
            return self.run_selected_stage(selected, path, label, scanner, index_checker,
                                           completeness_checker, require_bgzf, require_gzip,
                                           not_applicable_reason, format_checker)
        path = Path(path)
        report = FileReport(label, path)
        compression, info = self.check_compression(path, require_bgzf, require_gzip)
        report.add(compression)
        if compression.status == FAIL:
            report.skip_remaining(f"Compression validation failed: {compression.reason}")
            return report

        if index_checker is None:
            report.add(StageResult("index", SKIP, "No index expected for this file", expected_skip=True))
        else:
            index_result, index_warnings = self.check_index(path, info, None, index_checker)
            report.add(index_result)
            report.warnings.extend(f"index: {w}" for w in index_warnings)
            if index_result.status != PASS:
                report.skip_remaining(f"Index validation did not pass: {index_result.reason}")
                return report

        format_result, parsed, format_warnings = self.check_format(path, scanner)
        if format_result.status == PASS and index_checker is not None:
            consistency = self.index_content_checker(path, parsed)
            if consistency.errors:
                format_result = stage_from_outcome("format", consistency)
        if format_result.status == PASS and format_checker is not None:
            try:
                external = format_checker(path)
            except (OSError, ValueError, zlib.error, EOFError) as exc:
                external = Outcome(errors=[f"Format validator could not run: {exc}"])
            format_result = stage_from_outcome("format", external, external.note)
            format_warnings = [*format_warnings, *external.warnings]
        report.add(format_result)
        report.warnings.extend(f"format: {w}" for w in format_warnings)
        if format_result.status == FAIL or parsed is None:
            report.add(StageResult("completeness", SKIP, "Format validation failed"))
            return report
        if completeness_checker is None:
            report.add(StageResult("completeness", SKIP, not_applicable_reason, expected_skip=True))
            return report
        completeness, completeness_warnings = self.check_completeness(parsed, completeness_checker)
        report.add(completeness)
        report.warnings.extend(f"completeness: {w}" for w in completeness_warnings)
        return report

    def _gff3_or_skip(self, gff3_path):
        if gff3_path is None or not Path(gff3_path).is_file():
            return None, "GFF3 cross-reference unavailable: GFF3 file not found"
        try:
            scan = cached_gff3_scan(gff3_path)
            if scan.errors:
                return None, "GFF3 cross-reference unavailable: invalid GFF3: " + "; ".join(scan.errors.summary())
            return scan, None
        except (OSError, ValueError, zlib.error, EOFError) as exc:
            return None, f"GFF3 cross-reference unavailable: {exc}"

    def count_check(self, outcome, label, observed, expected):
        """Compare a count with a metadata statistic (warning unless strict_metadata_counts)."""
        if expected is None:
            outcome.warnings.append(f"{label} not available in metadata; count {observed} not compared")
        elif observed != expected:
            message = f"{label} mismatch: file {observed} vs metadata {expected}"
            (outcome.errors if self.settings["strict_metadata_counts"] else outcome.warnings).append(message)

    def index_content_checker(self, path, scan):
        """Compare parsed data with the index during format validation; subclasses override."""
        return Outcome()
