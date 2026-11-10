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

"""CSI index, external GFF3/GTF validators, raw geneset and chromosome TSV checks, GenesetValidation."""

import gzip
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import xxhash

from .base import OutputValidationBase
from .common import (FAIL, GZIP_MAGIC, NO_METADATA, BgzfReader, ErrorCollector, Outcome, StageResult, _file_magic,
                     _sample, open_binary_lines, summarise_items)
from .gene_models import _check_feature_columns, _parse_gtf_attributes, cached_gff3_scan, scan_gtf


@dataclass
class CsiIndex:
    names: list
    first_offsets: list  # per reference: smallest chunk start virtual offset, or None


def parse_csi(path):
    """Parse a (BGZF-compressed) CSI index, including tabix sequence names from the aux field."""
    with gzip.open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"CSI\x01":
        raise ValueError("invalid CSI magic")
    offset = 4
    _min_shift, depth, l_aux = struct.unpack_from("<iii", data, offset)
    offset += 12
    aux = data[offset:offset + l_aux]
    offset += l_aux
    (n_ref,) = struct.unpack_from("<i", data, offset)
    offset += 4
    pseudo_bin = (((1 << ((depth + 1) * 3)) - 1) // 7) + 1
    first_offsets = []
    for _ in range(n_ref):
        (n_bin,) = struct.unpack_from("<i", data, offset)
        offset += 4
        starts = []
        for _ in range(n_bin):
            bin_id, _loffset, n_chunk = struct.unpack_from("<IQi", data, offset)
            offset += 16
            chunks = struct.unpack_from(f"<{2 * n_chunk}Q", data, offset)
            offset += 16 * n_chunk
            if bin_id != pseudo_bin:
                starts.extend(chunks[0::2])
        first_offsets.append(min(starts) if starts else None)
    names = []
    if l_aux >= 28:
        l_nm = struct.unpack_from("<7i", aux, 0)[6]
        names = [name.decode() for name in aux[28:28 + l_nm].split(b"\0") if name]
    return CsiIndex(names, first_offsets)


def _pipe_decompressed(path, command, **kwargs):
    """Run command with the decompressed file on stdin; returns CompletedProcess-like (rc, output)."""
    if _file_magic(path) == GZIP_MAGIC:
        source = subprocess.Popen(["gzip", "-dc", str(path)], stdout=subprocess.PIPE)
        stdin = source.stdout
    else:
        source = None
        stdin = open(path, "rb")
    try:
        process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        stdin.close()
        output, _ = process.communicate()
    finally:
        if source is not None:
            source.wait()
    return process.returncode, output.decode("utf-8", "replace")


def _tail(text, lines=10):
    return [line for line in text.strip().splitlines() if line.strip()][-lines:]


def run_gff3validator(path):
    """Run GenomeTools gt gff3validator. Returns Outcome (skip when gt is not installed)."""
    gt = shutil.which("gt")
    if not gt:
        return Outcome(skip="gt not found on PATH; GenomeTools gff3validator not run")
    returncode, output = _pipe_decompressed(path, [gt, "gff3validator"])
    if returncode != 0:
        return Outcome(errors=["gt gff3validator failed"] + _tail(output))
    return Outcome()


def run_genepred_check(path):
    """Run gtfToGenePred then genePredCheck; requires zero failed records."""
    gtf_to_genepred = shutil.which("gtfToGenePred")
    genepred_check = shutil.which("genePredCheck")
    if not gtf_to_genepred or not genepred_check:
        return Outcome(skip="gtfToGenePred or genePredCheck not found on PATH; GTF conversion check not run")
    with tempfile.TemporaryDirectory() as tmp_dir:
        genepred = Path(tmp_dir) / "genes.gp"
        returncode, output = _pipe_decompressed(
            path, [gtf_to_genepred, "-genePredExt", "-ignoreGroupsWithoutExons", "stdin", str(genepred)]
        )
        if returncode != 0:
            return Outcome(errors=["gtfToGenePred failed"] + _tail(output))
        result = subprocess.run([genepred_check, str(genepred)], capture_output=True, text=True)
    output = result.stdout + result.stderr
    match = re.search(r"checked:\s*(\d+)\s+failed:\s*(\d+)", output)
    if result.returncode != 0 or not match or int(match.group(2)) != 0:
        return Outcome(errors=["genePredCheck reported failed records"] + _tail(output))
    return Outcome()


class GenesetValidation(OutputValidationBase):
    """GFF3, GTF and chromosome TSV validation."""

    @staticmethod
    def raw_sibling(path):
        """Raw dumper output paired with a processed file, including custom filenames."""
        return Path(path).with_suffix(".gz")

    def check_compression(self, path, require_bgzf=True, require_gzip=False):
        stage, info = super().check_compression(path, require_bgzf, require_gzip)
        if require_bgzf:
            sibling = self.raw_sibling(path)
            if sibling == Path(path) or not sibling.is_file():
                message = f"Raw gzip sibling not found: {sibling.name}"
                details = (stage.details or [stage.reason]) if stage.status == FAIL else []
                stage = StageResult("compression", FAIL, (details + [message])[0], details + [message])
        return stage, info

    def compare_raw_sibling(self, path):
        """Compare feature-line multisets in bounded memory, allowing sorting and changed headers."""
        sibling = self.raw_sibling(path)
        if sibling == Path(path) or not sibling.is_file():
            return Outcome(errors=[f"Raw gzip sibling not found: {sibling.name}"])
        try:
            compression, info = super().check_compression(sibling, require_bgzf=False, require_gzip=True)
            if compression.status == FAIL:
                return Outcome(errors=[f"Raw gzip sibling {sibling.name}: {compression.reason}"])

            def signature(file_path):
                count, total, squared = 0, 0, 0
                with open_binary_lines(file_path) as fh:
                    for line in fh:
                        if not line.strip() or line.startswith(b"#"):
                            continue
                        value = xxhash.xxh128_intdigest(line.rstrip(b"\r\n"))
                        count += 1
                        total = (total + value) % (1 << 128)
                        squared = (squared + value * value) % (1 << 128)
                return count, total, squared

            processed, raw = signature(path), signature(sibling)
            if processed != raw:
                return Outcome(errors=[f"Feature records differ from raw gzip sibling {sibling.name} "
                                       f"(processed {processed[0]} vs raw {raw[0]} records)"])
        except (OSError, ValueError, zlib.error, EOFError) as exc:
            return Outcome(errors=[f"Raw gzip sibling {sibling.name} could not be compared: {exc}"])
        return Outcome()

    def _seqid_outcome(self, seqids):
        outcome = Outcome()
        lookup = self.metadata.sequence_lookup()
        if not lookup:
            outcome.warnings.append(NO_METADATA if not self.metadata.available
                                    else "No seq_regions in metadata; seqids not compared")
            return outcome
        unknown = [seqid for seqid in seqids if seqid not in lookup]
        if unknown:
            outcome.errors.append(summarise_items("Seqids not in metadata seq_regions", unknown))
        return outcome

    def validate_gff3(self, path):
        def completeness(scan):
            raw = self.compare_raw_sibling(path)
            if not self.metadata.available:
                raw.skip = NO_METADATA
                return raw
            outcome = self._seqid_outcome(scan.seqids)
            outcome.errors.extend(raw.errors)
            # Every metadata seq_region is mandatory, independently of CDS counts.
            lookup = self.metadata.sequence_lookup()
            present = scan.seqids | set(scan.sequence_regions)
            missing = [seq[0] or seq[1] for seq in set(lookup.values())
                       if not any(alias in present for alias in (seq[0], seq[1]) if alias)]
            if missing:
                outcome.errors.append(summarise_items("Missing seq_regions", missing))
            if scan.sequence_regions:
                all_sequences = self.metadata.sequence_lookup()
                mismatched = [f"{name} {end - start + 1} vs {all_sequences[name][2]}"
                              for name, (start, end) in scan.sequence_regions.items()
                              if name in all_sequences and end - start + 1 != all_sequences[name][2]]
                if mismatched:
                    outcome.warnings.append(summarise_items(
                        "Length mismatch with metadata (##sequence-region file vs metadata)", mismatched))
            else:
                outcome.warnings.append("No ##sequence-region pragmas; seq_region presence checked from feature seqids")
            expected = self.metadata.total_coding_exons
            label = "CDS features vs genebuild.stats.total_coding_exons"
            if expected is None:
                outcome.warnings.append(f"{label} not available in metadata; count {scan.cds_count} not compared")
            elif scan.cds_count != expected:
                outcome.warnings.append(f"{label} mismatch: file {scan.cds_count} vs metadata {expected}")
            return outcome

        return self.run(path, Path(path).name, cached_gff3_scan, self.csi_index_checker, completeness,
                        format_checker=run_gff3validator)

    def validate_gtf(self, path, gff3_path):
        def completeness(scan):
            # Check the unsorted dumper tail before comparing records or opening GFF3.
            raw_path = self.raw_sibling(path)
            raw_validator = GenesetValidation(self.metadata, {**self.settings, "validation_stage": "all"})
            raw_report = raw_validator.validate_raw_geneset(raw_path, "gtf")
            raw_errors = [f"Raw gzip sibling {raw_path.name}: {detail}"
                          for stage in raw_report.failures
                          for detail in (stage.details or [stage.reason])]
            reference_missing = gff3_path is None or not Path(gff3_path).is_file()
            if reference_missing:
                raw_errors.append(f"GFF3 cross-reference missing: no GFF3 file found in {Path(path).parent}")
            if raw_errors:
                return Outcome(errors=raw_errors)
            outcome = self._seqid_outcome(scan.seqids)
            outcome.errors.extend(self.compare_raw_sibling(path).errors)
            gff3, reason = self._gff3_or_skip(gff3_path)
            if gff3 is None:
                outcome.skip = reason
                return outcome
            missing = set(gff3.transcripts) - set(scan.transcripts)
            extra = set(scan.transcripts) - set(gff3.transcripts)
            different = [tid for tid, exons in scan.transcripts.items()
                         if tid in gff3.transcripts and exons != gff3.transcripts[tid]]
            if missing:
                outcome.errors.append(summarise_items("GFF3 transcripts missing from GTF", missing))
            if extra:
                outcome.errors.append(summarise_items("GTF transcripts not in GFF3", extra))
            if different:
                outcome.errors.append(summarise_items("Transcripts with exon regions differing from GFF3", different))
            return outcome

        return self.run(path, Path(path).name, scan_gtf, self.csi_index_checker, completeness,
                        format_checker=run_genepred_check)

    def validate_raw_geneset(self, path, file_format):
        """Truncation check on the unsorted dumper output (genes.gff3.gz / genes.gtf.gz).

        Sorting reorders lines, so truncation is only visible in the raw file: it must decompress fully,
        end with a newline and finish with a complete feature line. For GTF the last line must also
        carry every attribute in raw_gtf_required_attributes with a nonempty value.
        """
        required_attributes = self.settings["raw_gtf_required_attributes"]
        if isinstance(required_attributes, str):
            required_attributes = [item.strip() for item in required_attributes.split(",") if item.strip()]

        def scanner(raw_path):
            scan = RawGenesetScan()
            last_raw, last_line, last_line_no = b"", None, 0
            with open_binary_lines(raw_path) as fh:
                for line_no, raw in enumerate(fh, 1):
                    last_raw = raw
                    if raw.strip():
                        last_line, last_line_no = raw, line_no
            if last_line is None:
                scan.errors.add("File has no content")
                return scan
            if not last_raw.endswith(b"\n"):
                scan.errors.add("File does not end with a newline (truncated)")
            line = last_line.decode("utf-8", "replace").rstrip("\r\n")
            scan.last_line = line
            if file_format == "gff3" and line.strip() == "###":
                return scan
            if line.startswith("#"):
                scan.errors.add(f"Line {last_line_no}: last line is a comment or directive, not a feature")
                return scan
            fields = line.split("\t")
            if _check_feature_columns(fields, last_line_no, scan.errors) is None:
                scan.errors.add(f"Line {last_line_no}: last feature line is incomplete (truncated)")
                return scan
            if file_format == "gtf":
                attrs = _parse_gtf_attributes(fields[8]) or {}
                missing = [name for name in required_attributes if not attrs.get(name)]
                if missing:
                    scan.errors.add(summarise_items(
                        f"Line {last_line_no}: last line missing required attributes (truncated)", missing))
            return scan

        return self.run(path, Path(path).name, scanner, None, None, require_bgzf=False, require_gzip=True,
                        not_applicable_reason="Raw file: index and completeness are validated on the sorted .bgz file")

    def validate_chromosome_tsv(self, path):
        def scanner(tsv_path):
            scan = ChromosomeScan()
            with open_binary_lines(tsv_path) as fh:
                for line_no, raw in enumerate(fh, 1):
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if not line:
                        scan.errors.add(f"Line {line_no}: blank line")
                        continue
                    fields = line.split("\t")
                    if len(fields) != 2:
                        scan.errors.add(f"Line {line_no}: expected 2 columns, found {len(fields)}")
                        continue
                    if not fields[1].isdigit():
                        scan.errors.add(f"Line {line_no}: header or non-integer length ({fields[1]})"
                                        if line_no == 1 else f"Line {line_no}: non-integer length")
                        continue
                    if int(fields[1]) <= 0:
                        scan.errors.add(f"Line {line_no}: length must be positive")
                    if fields[0] in scan.records:
                        scan.errors.add(f"Line {line_no}: duplicate chromosome {fields[0]}")
                    scan.records[fields[0]] = int(fields[1])
            if not scan.records and not scan.errors:
                scan.errors.add("No chromosomes found")
            return scan

        def completeness(scan):
            outcome = Outcome()
            if not self.metadata.available:
                return Outcome(skip=NO_METADATA)
            chromosomes = self.metadata.sequence_lookup(chromosomal_only=True)
            if not chromosomes:
                return Outcome(skip="No chromosomal assembly sequences in metadata")
            all_seqs = self.metadata.sequence_lookup()
            seen = set()
            unknown, not_chromosomal, mismatched = [], [], []
            for name, length in scan.records.items():
                seq = all_seqs.get(name)
                if seq is None:
                    unknown.append(name)
                    continue
                if not seq[3]:
                    not_chromosomal.append(name)
                seen.add(seq)
                if length != seq[2]:
                    mismatched.append(f"{name} {length} vs {seq[2]}")
            missing = [seq[0] or seq[1] for seq in set(chromosomes.values()) if seq not in seen]
            if missing:
                outcome.errors.append(summarise_items("Missing chromosomes", missing))
            if unknown:
                outcome.errors.append(summarise_items("Entries not in metadata seq_regions", unknown))
            if mismatched:
                outcome.errors.append(summarise_items("Length mismatch with metadata (file vs metadata)", mismatched))
            if not_chromosomal:
                outcome.warnings.append(summarise_items("Entries not flagged chromosomal in metadata", not_chromosomal))
            return outcome

        return self.run(path, Path(path).name, scanner, None, completeness, require_bgzf=False)

    # --- CSI --------------------------------------------------------------

    def csi_index_checker(self, path, info, scan):
        outcome = Outcome()
        csi_path = Path(f"{path}.csi")
        if not csi_path.is_file():
            outcome.errors.append(f"CSI index not found: {csi_path.name}")
            return outcome
        index = parse_csi(csi_path)
        if not index.first_offsets:
            outcome.errors.append("CSI index has no references")
            return outcome
        if index.names and len(index.names) != len(index.first_offsets):
            outcome.errors.append(
                f"CSI name count {len(index.names)} does not match reference count {len(index.first_offsets)}")
            return outcome
        if not index.names:
            outcome.warnings.append("CSI index has no sequence names; name checks not run")

        if info.kind != "bgzf":
            outcome.errors.append("Data file is not BGZF; indexed retrieval is not possible")
            return outcome
        reader = BgzfReader(path, info.blocks)
        names = index.names or [None] * len(index.first_offsets)
        refs = [(name, voffset) for name, voffset in zip(names, index.first_offsets) if voffset is not None]
        failed = []
        for name, voffset in _sample(refs, self.settings["index_sample_size"]):
            line = reader.read_virtual_line(voffset).decode("utf-8", "replace")
            seqid = line.split("\t", 1)[0]
            if (name is not None and seqid != name) or (name is None and line.count("\t") != 8):
                failed.append(name or f"offset {voffset}")
        if failed:
            outcome.errors.append(summarise_items("Indexed retrieval failed for", failed))
        return outcome

    def index_content_checker(self, path, scan):
        """Compare the parsed seqids with the CSI sequence names during format validation."""
        outcome = Outcome()
        index = parse_csi(Path(f"{path}.csi"))
        if scan is not None and index.names:
            missing = scan.seqids - set(index.names)
            extra = set(index.names) - scan.seqids
            if missing:
                outcome.errors.append(summarise_items("Seqids missing from CSI", missing))
            if extra:
                outcome.errors.append(summarise_items("CSI references not in file", extra))
        return outcome


@dataclass
class RawGenesetScan:
    last_line: str = None
    errors: ErrorCollector = field(default_factory=ErrorCollector)
    warnings: list = field(default_factory=list)


@dataclass
class ChromosomeScan:
    records: dict = field(default_factory=dict)
    errors: ErrorCollector = field(default_factory=ErrorCollector)
    warnings: list = field(default_factory=list)
