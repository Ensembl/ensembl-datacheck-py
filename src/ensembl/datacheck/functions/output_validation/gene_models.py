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

"""GFF3 / GTF parsing shared by the geneset checks and the cDNA/peptide cross-reference."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import xxhash

from .common import ErrorCollector, open_binary_lines

_ID_PREFIXES = ("transcript:", "gene:", "cds:", "exon:", "protein:")
_ID_VERSION = re.compile(r"\.\d+$")
_FINGERPRINT_MASK = (1 << 64) - 1


def normalise_id(value):
    """Strip Ensembl type prefixes (transcript:, CDS:, ...) and a trailing .version."""
    value = value.strip()
    lowered = value.lower()
    for prefix in _ID_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix):]
            break
    return _ID_VERSION.sub("", value)


def _exon_hash(seqid, start, end, strand):
    return xxhash.xxh64_intdigest(f"{seqid}\t{start}\t{end}\t{strand}".encode())


@dataclass
class GeneModelScan:
    """Structure and gene-model summary of a GFF3 or GTF file."""
    seqids: set = field(default_factory=set)
    sequence_regions: dict = field(default_factory=dict)
    transcripts: dict = field(default_factory=dict)  # tid -> [exon count, exon length, fingerprint]
    coding: dict = field(default_factory=dict)  # tid -> protein id
    cds_length: dict = field(default_factory=dict)  # tid -> CDS length
    cds_count: int = 0
    feature_count: int = 0
    errors: ErrorCollector = field(default_factory=ErrorCollector)
    warnings: list = field(default_factory=list)
    skip: str = None

    def add_exon(self, tid, seqid, start, end, strand):
        entry = self.transcripts.setdefault(tid, [0, 0, 0])
        entry[0] += 1
        entry[1] += end - start + 1
        entry[2] = (entry[2] + _exon_hash(seqid, start, end, strand)) & _FINGERPRINT_MASK


def _check_feature_columns(fields, line_no, errors):
    """Validate the 8 fixed GFF/GTF columns. Returns (start, end) or None."""
    if len(fields) != 9:
        errors.add(f"Line {line_no}: expected 9 tab-separated columns, found {len(fields)}")
        return None
    seqid, _source, feature_type, start, end, score, strand, phase, _attrs = fields
    if not seqid or not feature_type:
        errors.add(f"Line {line_no}: empty seqid or feature type")
        return None
    try:
        start, end = int(start), int(end)
    except ValueError:
        errors.add(f"Line {line_no}: non-integer start or end")
        return None
    if start < 1 or start > end:
        errors.add(f"Line {line_no}: invalid coordinates {start}-{end}")
        return None
    if score != ".":
        try:
            float(score)
        except ValueError:
            errors.add(f"Line {line_no}: invalid score {score}")
    if strand not in ("+", "-", ".", "?"):
        errors.add(f"Line {line_no}: invalid strand {strand}")
    if feature_type == "CDS" and phase not in ("0", "1", "2"):
        errors.add(f"Line {line_no}: CDS without a valid phase")
    elif phase not in (".", "0", "1", "2"):
        errors.add(f"Line {line_no}: invalid phase {phase}")
    return start, end


def scan_gff3(path):
    """Stream a GFF3 file, validate its structure and summarise its gene models."""
    scan = GeneModelScan()
    first_line = True
    with open_binary_lines(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if first_line:
                first_line = False
                if not re.match(r"^##gff-version\s+3(\.\d+)*\s*$", line):
                    scan.errors.add("Line 1: missing ##gff-version 3 header")
            if not line:
                continue
            if line.startswith("#"):
                if line.startswith("##sequence-region"):
                    parts = line.split()
                    if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
                        scan.sequence_regions[parts[1]] = (int(parts[2]), int(parts[3]))
                    else:
                        scan.errors.add(f"Line {line_no}: malformed ##sequence-region pragma")
                elif line.startswith("##FASTA"):
                    break
                continue
            fields = line.split("\t")
            coords = _check_feature_columns(fields, line_no, scan.errors)
            if coords is None:
                continue
            scan.feature_count += 1
            seqid, feature_type, strand = fields[0], fields[2], fields[6]
            scan.seqids.add(seqid)
            attrs = {}
            for item in fields[8].split(";"):
                item = item.strip()
                if not item:
                    continue
                if "=" not in item:
                    scan.errors.add(f"Line {line_no}: attribute without = ({item})")
                    continue
                key, value = item.split("=", 1)
                attrs[key] = value
            parents = [normalise_id(p) for p in attrs.get("Parent", "").split(",") if p]
            if feature_type == "exon":
                for tid in parents:
                    scan.add_exon(tid, seqid, coords[0], coords[1], strand)
            elif feature_type == "CDS":
                scan.cds_count += 1
                protein = attrs.get("protein_id") or attrs.get("ID", "")
                for tid in parents:
                    scan.coding[tid] = normalise_id(protein) if protein else tid
                    scan.cds_length[tid] = scan.cds_length.get(tid, 0) + coords[1] - coords[0] + 1
    if first_line:
        scan.errors.add("File has no content")
    elif scan.feature_count == 0:
        scan.errors.add("No GFF3 features found")
    return scan


def _parse_gtf_attributes(text):
    attrs = {}
    for item in text.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = item.split(None, 1)
        if len(parts) != 2:
            return None
        attrs.setdefault(parts[0], parts[1].strip().strip('"'))
    return attrs


def scan_gtf(path):
    """Stream a GTF file, validate its structure and required attributes, and summarise exons."""
    scan = GeneModelScan()
    with open_binary_lines(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            coords = _check_feature_columns(fields, line_no, scan.errors)
            if coords is None:
                continue
            scan.feature_count += 1
            seqid, feature_type, strand = fields[0], fields[2], fields[6]
            scan.seqids.add(seqid)
            attrs = _parse_gtf_attributes(fields[8])
            if attrs is None:
                scan.errors.add(f"Line {line_no}: malformed attribute column")
                continue
            if not attrs.get("gene_id"):
                scan.errors.add(f"Line {line_no}: missing required attribute gene_id")
            if feature_type != "gene" and not attrs.get("transcript_id"):
                scan.errors.add(f"Line {line_no}: missing required attribute transcript_id on {feature_type}")
                continue
            if feature_type == "exon":
                scan.add_exon(normalise_id(attrs["transcript_id"]), seqid, coords[0], coords[1], strand)
            elif feature_type == "CDS":
                scan.cds_count += 1
    if scan.feature_count == 0:
        scan.errors.add("No GTF features found")
    return scan


_GFF3_CACHE = {}


def cached_gff3_scan(path):
    """Scan a GFF3 file once per process and reuse it for cross-reference checks."""
    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    if key not in _GFF3_CACHE:
        _GFF3_CACHE.clear()
        _GFF3_CACHE[key] = scan_gff3(path)
    return _GFF3_CACHE[key]
