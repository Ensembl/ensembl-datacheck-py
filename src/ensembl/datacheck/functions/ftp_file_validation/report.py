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

"""The ftp_file_validation summary: JSON file under --output-dir and the terminal block."""

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from .common import FAIL, PASS, SKIP

OUTPUT_REPORT_NAME = "ftp_file_validation_report.json"


def file_report_record(file_report, output_file, genome):
    """One --output-dir entry: the file, its conclusion and the result of each stage."""
    result = {}
    for stage in file_report.stages:
        entry = {"status": stage.status}
        if stage.reason:
            entry["reason"] = stage.reason
        if stage.details:
            entry["details"] = list(stage.details)
        if stage.expected_skip:
            entry["not_applicable"] = True
        result[stage.stage] = entry
    return {
        "file": str(file_report.path),
        "file_type": output_file.key,
        "gff3_reference": str(Path(output_file.gff3_path).resolve()) if output_file.gff3_path else None,
        "genome_uuid": (genome or {}).get("genome_uuid"),
        "conclusion": file_report.overall,
        "result": result,
        "warnings": list(file_report.warnings),
    }


def summarise_records(records, run_info):
    """Build the report document; the run's conclusion is FAIL if the file failed, else SKIP if it was skipped."""
    counts = {status: sum(r["conclusion"] == status for r in records) for status in (PASS, FAIL, SKIP)}
    conclusion = FAIL if counts[FAIL] else SKIP if counts[SKIP] else PASS
    return {**run_info, "conclusion": conclusion, "summary": {"files": len(records), **counts},
            "files": sorted(records, key=lambda r: (r["genome_uuid"] or "", r["file"]))}


class OutputReportWriter:
    """Collect file records; with --output-dir, write them to <output_dir>/ftp_file_validation_report.json.

    The records are always printed in the terminal (TerminalSummary); the JSON file is optional.
    Every pytest process writes at session end. pytest-xdist workers share a run id
    (testrunuid), so each worker merges its records into the file under a lock; a file left
    by an earlier run (different run id) is replaced.
    """

    def __init__(self, output_dir, run_info):
        self.output_dir = Path(output_dir).expanduser() if output_dir else None
        self.run_info = run_info
        self.records = []
        self.written = None  # path of the JSON file once written

    def document(self):
        return summarise_records(self.records, self.run_info)

    def add(self, file_report, output_file, genome):
        self.records.append(file_report_record(file_report, output_file, genome))

    @property
    def path(self):
        return self.output_dir / OUTPUT_REPORT_NAME

    def write(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with open(self.output_dir / f".{OUTPUT_REPORT_NAME}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            records = list(self.records)
            if self.path.exists():
                try:
                    previous = json.loads(self.path.read_text())
                except ValueError:
                    previous = {}
                if previous.get("run_id") == self.run_info["run_id"]:
                    records = previous.get("files", []) + records
            temporary = self.path.with_name(f".{OUTPUT_REPORT_NAME}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps(summarise_records(records, self.run_info), indent=2) + "\n")
            os.replace(temporary, self.path)
        self.written = self.path
        return self.path


def _run_info(config):
    workerinput = getattr(config, "workerinput", None)
    run_id = workerinput["testrunuid"] if workerinput else uuid.uuid4().hex
    return {"test": "ftp_file_validation", "run_id": run_id,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input": config.getoption("target_file"), "genome_uuid": config.getoption("genome_uuid"),
            "file_type": config.getoption("file_type", None), "base_path": config.getoption("base_path", None)}


REPORT_KEY = pytest.StashKey()


STATUS_MARKUP = {PASS: {"green": True}, FAIL: {"red": True}, SKIP: {"yellow": True}}


def format_terminal_report(document, json_path=None):
    """Turn the report document into (text, markup) lines: one block per file, then the JSON location."""
    lines = []
    for record in document["files"]:
        if lines:
            lines.append(("", {}))
        genome = record["genome_uuid"] or "not given (completeness needs --database and --genome_uuid)"
        lines += [(f"File:    {record['file']}", {"bold": True}),
                  (f"Type:    {record['file_type']}", {}),
                  (f"Genome:  {genome}", {})]
        if record.get("gff3_reference"):
            lines.append((f"GFF3:    {record['gff3_reference']}", {}))
        width = max(len(stage) for stage in record["result"]) if record["result"] else 0
        for stage, entry in record["result"].items():
            reason = entry.get("reason", "")
            lines.append((f"  {stage:<{width}}  {entry['status']}  {reason}".rstrip(),
                          {} if entry.get("not_applicable") else STATUS_MARKUP[entry["status"]]))
            for detail in entry.get("details", []):
                if detail != reason:
                    lines.append((f"  {'':<{width}}        - {detail}", {}))
        if record["warnings"]:
            lines.append(("Warnings:", {"yellow": True}))
            lines += [(f"  - {warning}", {"yellow": True}) for warning in record["warnings"]]
        lines.append((f"Result:  {record['conclusion']}", {"bold": True, **STATUS_MARKUP[record["conclusion"]]}))
    lines.append(("", {}))
    lines.append((f"JSON:    {json_path}" if json_path else "JSON:    not written (add --output-dir DIR to save it)", {}))
    return lines


class TerminalSummary:
    """Prints the results of the -f file as the last block before pytest's own summary line."""

    name = "ftp_file_validation_terminal_summary"

    @pytest.hookimpl(trylast=True)
    def pytest_terminal_summary(self, terminalreporter, config):
        writer = config.stash.get(REPORT_KEY, None)
        if writer is None or not writer.records:
            return
        terminalreporter.write_sep("=", "FTP file validation", bold=True)
        for text, markup in format_terminal_report(writer.document(), writer.written):
            terminalreporter.write_line(text, **markup)
