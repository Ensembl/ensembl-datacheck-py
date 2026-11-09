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
output_validation.py

Validate one FTPdump output file (FASTA or geneset). See checks/readme.md for the full specification.

Input: exactly one file per run. Supported forms:
    --genome_uuid UUID --file-type TYPE [--base-path FTP_ROOT] --database URL
    --genome_uuid UUID -f FILE
    --genome_uuid UUID -f FILE --file-type TYPE

Without -f, resolve the genome's public FTP path from metadata under FTP_ROOT
(default /nfs/ftp/public/ensemblorganisms). With -f, infer the type from the
filename unless --file-type explicitly selects the validator.

    ensembl-datacheck --test=output_validation -f genes.gff3.bgz --database <metadata_url> \
        --genome_uuid <uuid> --no-cache-results --tb=short

--database and --genome_uuid enable the metadata checks. The runner maps -f to --target-file for
this test only.

Each file is checked in the order Compression -> Index -> Format -> Completeness:
    - Compression: gzip/BGZF block integrity (CRC, size), BGZF EOF marker, nonempty content.
    - Index: FAI/GZI (FASTA) or CSI (GFF3/GTF) parse, consistency with the data and
      random-access retrieval of sampled records.
    - Format: FASTA structure / GFF3 / GTF / chromosome TSV structure, plus the external
      validators (gt gff3validator, gtfToGenePred + genePredCheck) when they are on PATH.
    - Completeness: comparison with the metadata database and with the GFF3 file.

For processed GFF3/GTF, compression also requires a same-stem .gz sibling
(e.g. genes.gff3.bgz -> genes.gff3.gz). Completeness verifies the sibling's gzip
integrity and compares feature records independent of sorting, ignoring comments
and directives. Missing or different records fail even without metadata.

Raw geneset files (genes.gff3.gz / genes.gtf.gz, unsorted dumper output) get a truncation check:
gzip integrity, final newline and a complete last feature line; for GTF the last line must also
carry gene_id, gene_version, gene_biotype and gene_source.

Stop rules:
    - Missing or ambiguous input file: usage error before any check runs.
    - Compression failure: skip index, format and completeness.
    - Index failure: skip format and completeness.
    - Format failure: completeness SKIP.

Nothing is written next to the FTPdump outputs; external tools use a temporary directory.
"""

import os, re, shutil, struct, subprocess, tempfile, warnings, zlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
import bisect, fnmatch
import gzip
import fcntl, json, uuid
from datetime import datetime, timezone

import pytest
import xxhash
from sqlalchemy import select

from ensembl.production.metadata.api.models import AssemblySequence, Genome
from ensembl.datacheck.checks.automation.conftest import _build_automation_resource_config
from ensembl.datacheck.functions.utils import (
    EnsemblDatacheckWarning,
    get_genome_dataset_attribute,
    get_genomes_from_metadata_db,
)

logger = logging.getLogger(__name__)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
STAGES = ("compression", "index", "format", "completeness")

MAX_DETAILS = 20
GZIP_MAGIC = b"\x1f\x8b"
BGZF_EOF = bytes.fromhex("1f8b08040000000000ff0600424302001b0003000000000000000000")

NUCLEOTIDE_UPPER = b"ACGTNRYKMSWBDHV"
NUCLEOTIDE_ANY_CASE = NUCLEOTIDE_UPPER + NUCLEOTIDE_UPPER.lower()
PROTEIN = b"ACDEFGHIKLMNPQRSTVWYXBZJUO*"
GENOME_MASKS = ("unmasked", "softmasked", "hardmasked")

_ID_PREFIXES = ("transcript:", "gene:", "cds:", "exon:", "protein:")
_ID_VERSION = re.compile(r"\.\d+$")
_FINGERPRINT_MASK = (1 << 64) - 1

DEFAULT_SETTINGS = {
    "genome_fasta": ["unmasked.fa.bgz", "softmasked.fa.bgz", "hardmasked.fa.bgz"],
    "cdna_fasta": "cdna.fa.bgz",
    "peptide_fasta": "pep.fa.bgz",
    "gff3": "genes.gff3.bgz",
    "gtf": "genes.gtf.bgz",
    "raw_gff3": "genes.gff3.gz",
    "raw_gtf": "genes.gtf.gz",
    "raw_gtf_required_attributes": ["gene_id", "gene_version", "gene_biotype", "gene_source"],
    "chromosome_tsv": "chromosomes.tsv*",
    "chromosome_tsv_required": False,
    "require_gzi": False,
    "strict_metadata_counts": False,
    "check_genome_headers": True,
    "compare_genome_masks": True,
    "index_sample_size": 5,
    "max_line_width": 80,
}


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    """Outcome of one validation stage for one file."""
    stage: str
    status: str
    reason: str = ""
    details: list = field(default_factory=list)
    expected_skip: bool = False  # SKIP because the stage does not apply (e.g. plain TSV index)


@dataclass
class Outcome:
    """Errors, warnings and an optional skip reason collected by a check function."""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    skip: str = None
    note: str = ""  # reason shown when the stage passes


@dataclass
class FileReport:
    """All stage results for one output file."""
    label: str
    path: Path
    stages: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def add(self, result):
        self.stages.append(result)
        return result

    def skip_remaining(self, reason):
        done = {stage.stage for stage in self.stages}
        for stage in STAGES:
            if stage not in done:
                self.add(StageResult(stage, SKIP, reason))

    @property
    def failures(self):
        return [stage for stage in self.stages if stage.status == FAIL]

    @property
    def unexpected_skips(self):
        return [stage for stage in self.stages if stage.status == SKIP and not stage.expected_skip]

    @property
    def overall(self):
        if self.failures:
            return FAIL
        if self.unexpected_skips:
            return SKIP
        return PASS


class ErrorCollector(list):
    """List of error messages capped at MAX_DETAILS, counting the total."""

    def __init__(self, limit=MAX_DETAILS):
        super().__init__()
        self.limit = limit
        self.total = 0

    def add(self, message):
        self.total += 1
        if len(self) < self.limit:
            self.append(message)

    def summary(self):
        messages = list(self)
        if self.total > len(messages):
            messages.append(f"... {self.total - len(messages)} more errors not shown")
        return messages


def summarise_items(label, items, limit=MAX_DETAILS):
    """Return a single quote-free line: '<label> (<n>): a, b, c ... (+N more)'."""
    items = sorted(str(item) for item in items)
    shown = ", ".join(items[:limit])
    more = f" ... (+{len(items) - limit} more)" if len(items) > limit else ""
    return f"{label} ({len(items)}): {shown}{more}"


def stage_from_outcome(stage, outcome, pass_reason=""):
    """Convert an Outcome into a StageResult."""
    if outcome.errors:
        errors = outcome.errors.summary() if isinstance(outcome.errors, ErrorCollector) else list(outcome.errors)
        return StageResult(stage, FAIL, errors[0], errors)
    if outcome.skip:
        return StageResult(stage, SKIP, outcome.skip)
    return StageResult(stage, PASS, pass_reason)


# ---------------------------------------------------------------------------
# Compression / BGZF
# ---------------------------------------------------------------------------

@dataclass
class CompressionInfo:
    """What the compression stage learned about a file."""
    kind: str  # bgzf, gzip, plain, missing
    readable: bool = True
    uncompressed_size: int = 0
    blocks: list = field(default_factory=list)  # (compressed offset, uncompressed offset) of nonempty blocks
    has_eof: bool = False
    error: str = None


def _read_bgzf_block(fh):
    """Read one BGZF block at the current position. Returns (data, block_size) or None at EOF."""
    header = fh.read(12)
    if not header:
        return None
    if len(header) < 12:
        raise ValueError("truncated gzip header")
    id1, id2, cm, flg, _mtime, _xfl, _os, xlen = struct.unpack("<BBBBIBBH", header)
    if (id1, id2, cm) != (31, 139, 8):
        raise ValueError("invalid gzip magic")
    if not flg & 4:
        raise NotBgzfError("gzip member has no extra field")
    extra = fh.read(xlen)
    if len(extra) != xlen:
        raise ValueError("truncated gzip extra field")
    bsize = None
    pos = 0
    while pos + 4 <= len(extra):
        si1, si2, slen = extra[pos], extra[pos + 1], struct.unpack_from("<H", extra, pos + 2)[0]
        if pos + 4 + slen > len(extra):
            raise ValueError("truncated gzip extra subfield")
        if si1 == 66 and si2 == 67 and slen == 2:
            bsize = struct.unpack_from("<H", extra, pos + 4)[0]
        pos += 4 + slen
    if bsize is None:
        raise NotBgzfError("gzip member has no BGZF BC subfield")
    cdata_size = bsize - xlen - 19
    if cdata_size < 2:
        raise ValueError("invalid BGZF block size")
    cdata = fh.read(cdata_size)
    trailer = fh.read(8)
    if len(cdata) != cdata_size or len(trailer) != 8:
        raise ValueError("truncated BGZF block")
    crc, isize = struct.unpack("<II", trailer)
    data = zlib.decompress(cdata, -15)
    if len(data) != isize:
        raise ValueError("BGZF block size mismatch")
    if zlib.crc32(data) != crc:
        raise ValueError("BGZF block CRC mismatch")
    return data, bsize + 1


class NotBgzfError(ValueError):
    """The file is gzip compressed but not BGZF."""


def _file_magic(path):
    with open(path, "rb") as fh:
        return fh.read(2)


def inspect_compression(path):
    """Walk all BGZF blocks (or the gzip stream) and verify their integrity."""
    path = Path(path)
    if not path.is_file():
        return CompressionInfo("missing", readable=False, error=f"File not found: {path}")
    if path.stat().st_size == 0:
        return CompressionInfo("plain", readable=False, error="File is empty")
    if _file_magic(path) != GZIP_MAGIC:
        return CompressionInfo("plain", readable=True)

    info = CompressionInfo("bgzf")
    coffset = 0
    last_block_empty = False
    try:
        with open(path, "rb") as fh:
            while True:
                block = _read_bgzf_block(fh)
                if block is None:
                    break
                data, block_size = block
                if data:
                    info.blocks.append((coffset, info.uncompressed_size))
                info.uncompressed_size += len(data)
                last_block_empty = not data
                coffset += block_size
    except NotBgzfError:
        return _inspect_plain_gzip(path)
    except (ValueError, zlib.error, struct.error, OSError) as exc:
        info.readable = False
        info.error = f"Corrupt BGZF data at compressed offset {coffset}: {exc}"
        return info

    info.has_eof = last_block_empty
    if info.uncompressed_size == 0:
        info.readable = False
        info.error = "File has no uncompressed content"
    return info


def _inspect_plain_gzip(path):
    info = CompressionInfo("gzip")
    try:
        with gzip.open(path, "rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                info.uncompressed_size += len(chunk)
    except (OSError, EOFError, zlib.error) as exc:
        info.readable = False
        info.error = f"Corrupt gzip data: {exc}"
        return info
    if info.uncompressed_size == 0:
        info.readable = False
        info.error = "File has no uncompressed content"
    return info


class BgzfReader:
    """Minimal random-access BGZF reader using the block table from inspect_compression."""

    def __init__(self, path, blocks):
        self.path = Path(path)
        self.blocks = blocks
        self._ustarts = [uoffset for _, uoffset in blocks]

    def _read_from(self, coffset, within, size=None, until_newline=False):
        out = bytearray()
        with open(self.path, "rb") as fh:
            fh.seek(coffset)
            while True:
                block = _read_bgzf_block(fh)
                if block is None:
                    break
                data = block[0][within:]
                within = 0
                if until_newline and b"\n" in data:
                    out += data[:data.index(b"\n") + 1]
                    break
                out += data
                if size is not None and len(out) >= size:
                    break
        return bytes(out[:size]) if size is not None else bytes(out)

    def read_virtual_line(self, voffset):
        return self._read_from(voffset >> 16, voffset & 0xFFFF, until_newline=True)

    def read_uncompressed(self, uoffset, size):
        idx = bisect.bisect_right(self._ustarts, uoffset) - 1
        if idx < 0:
            raise ValueError(f"Offset {uoffset} is before the first block")
        coffset, ustart = self.blocks[idx]
        return self._read_from(coffset, uoffset - ustart, size=size)


def open_binary_lines(path):
    """Open a plain, gzip or BGZF file for binary line iteration."""
    if _file_magic(path) == GZIP_MAGIC:
        return gzip.open(path, "rb")
    return open(path, "rb")


# ---------------------------------------------------------------------------
# FASTA
# ---------------------------------------------------------------------------

@dataclass
class FastaRecord:
    name: str
    length: int = 0
    offset: int = 0
    linebases: int = 0
    linewidth: int = 0
    header: str = ""  # header text after '>', trailing whitespace kept


@dataclass
class FastaScan:
    records: dict = field(default_factory=dict)
    errors: ErrorCollector = field(default_factory=ErrorCollector)
    warnings: list = field(default_factory=list)
    lowercase_bases: int = 0

    @property
    def has_lowercase(self):
        return self.lowercase_bases > 0


def scan_fasta(path, alphabet, max_line_width=80):
    """Stream a FASTA file and validate its structure; collects FAI-equivalent records."""
    scan = FastaScan()
    lower = bytes(range(97, 123))
    current = None
    short_line_seen = False
    position = 0
    last_line = b""
    wide_lines = 0
    wide_headers = 0
    crlf_reported = False

    def finish(record):
        if record is not None and record.length == 0:
            scan.errors.add(f"Empty sequence for {record.name}")

    with open_binary_lines(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            last_line = raw
            width = len(raw)
            if raw.startswith(b">"):
                finish(current)
                header_text = raw[1:].rstrip(b"\r\n")
                try:
                    header_text.decode("utf-8")
                except UnicodeDecodeError:
                    scan.errors.add(f"Line {line_no}: header is not valid UTF-8 text")
                # Tab is ordinary header text; other control bytes are not.
                if any((char < 32 and char != 9) or char == 127 for char in header_text):
                    scan.errors.add(f"Line {line_no}: header contains control characters")
                if len(raw.rstrip(b"\r\n")) > max_line_width:
                    wide_headers += 1
                header = header_text.strip()
                name = header.split(None, 1)[0].decode("utf-8", "replace") if header else ""
                if not name:
                    scan.errors.add(f"Line {line_no}: empty FASTA header")
                elif name in scan.records:
                    scan.errors.add(f"Line {line_no}: duplicate sequence ID {name}")
                current = FastaRecord(name, offset=position + width,
                                      header=header_text.decode("utf-8", "replace"))
                if name and name not in scan.records:
                    scan.records[name] = current
                short_line_seen = False
            else:
                seq = raw.rstrip(b"\n")
                if seq.endswith(b"\r"):
                    if not crlf_reported:
                        scan.errors.add(f"Line {line_no}: Windows line ending")
                        crlf_reported = True
                    seq = seq[:-1]
                if current is None:
                    scan.errors.add(f"Line {line_no}: sequence or blank line before the first header")
                elif not seq:
                    scan.errors.add(f"Line {line_no}: blank line inside {current.name}")
                else:
                    invalid = seq.translate(None, alphabet)
                    if invalid:
                        chars = "".join(sorted(set(invalid.decode("latin-1"))))
                        scan.errors.add(f"Line {line_no}: invalid sequence characters {chars} in {current.name}")
                    scan.lowercase_bases += len(seq) - len(seq.translate(None, lower))
                    if current.linebases == 0:
                        current.linebases = len(seq)
                        current.linewidth = width
                        if len(seq) > max_line_width:
                            wide_lines += 1
                    elif short_line_seen or len(seq) > current.linebases:
                        scan.errors.add(f"Line {line_no}: inconsistent line length in {current.name}")
                    elif len(seq) < current.linebases:
                        short_line_seen = True
                    current.length += len(seq)
            position += width
    finish(current)

    if position == 0:
        scan.errors.add("File has no content")
    elif not last_line.endswith(b"\n"):
        scan.errors.add("File does not end with a newline")
    if not scan.records and position:
        scan.errors.add("No FASTA records found")
    if wide_headers:
        scan.warnings.append(f"{wide_headers} header lines are longer than {max_line_width} characters")
    if wide_lines:
        scan.warnings.append(f"{wide_lines} records use sequence lines longer than {max_line_width} characters")
    return scan


GENOME_MASK_TAGS = {"unmasked": ("unmasked", "dna"), "softmasked": ("softmasked", "dna_sm"),
                    "hardmasked": ("hardmasked", "dna_rm")}
GENOME_HEADER_FORMAT = "NAME MASK:COORD_SYSTEM ASSEMBLY:NAME:START:END:STRAND"


def genome_header_errors(scan, mask):
    """Check genome FASTA headers: '>NAME MASK:COORD_SYSTEM ASSEMBLY:NAME:START:END:STRAND'.

    MASK must name the file's mask (unmasked/softmasked/hardmasked, or Ensembl's dna/dna_sm/dna_rm), the
    location must name the record and START..END must span the sequence. Returns (errors, warnings).
    """
    tags = GENOME_MASK_TAGS[mask]
    wrong_tag, malformed, wrong_name, bad_location, wrong_length = {}, [], [], [], []
    trailing = 0
    for name, record in scan.records.items():
        if record.header != record.header.rstrip():
            trailing += 1
        tokens = record.header.split()
        tag, _, coord_system = tokens[1].partition(":") if len(tokens) >= 3 else ("", "", "")
        location = tokens[2].split(":") if len(tokens) >= 3 else []
        if not tag or not coord_system or len(location) < 5:
            malformed.append(name)
            continue
        if tag not in tags:
            wrong_tag.setdefault(tag, []).append(name)
        seq_name, start, end, strand = location[-4:]
        if seq_name != name:
            wrong_name.append(name)
        if not (start.isdigit() and end.isdigit()) or strand not in ("1", "-1") or not 1 <= int(start) <= int(end):
            bad_location.append(name)
        elif int(end) - int(start) + 1 != record.length:
            wrong_length.append(f"{name} (header {int(end) - int(start) + 1}, sequence {record.length})")
    errors = [summarise_items(f"Headers say {tag}, expected {tags[0]} for a {mask} file", names)
              for tag, names in sorted(wrong_tag.items())]
    if malformed:
        errors.append(summarise_items(f"Headers not in the format {GENOME_HEADER_FORMAT}", malformed))
    if wrong_name:
        errors.append(summarise_items("Header location names a different sequence than the ID", wrong_name))
    if bad_location:
        errors.append(summarise_items("Header location has an invalid START, END or STRAND", bad_location))
    if wrong_length:
        errors.append(summarise_items("Header location length differs from the sequence length", wrong_length))
    warnings = [f"{trailing} headers end with whitespace"] if trailing else []
    return errors, warnings


def mask_letter_errors(scan, mask):
    """Softmasked FASTA must contain lowercase (soft-masked) bases; unmasked and hardmasked must not."""
    if mask == "softmasked" and scan.records and not scan.lowercase_bases:
        return ["Softmasked FASTA has no lowercase (soft-masked) bases; it looks like an unmasked or hardmasked file"]
    if mask != "softmasked" and scan.lowercase_bases:
        return [f"{mask.capitalize()} FASTA has {scan.lowercase_bases} lowercase (soft-masked) bases; "
                "lowercase is only allowed in softmasked FASTA"]
    return []


class FastaSequenceReader:
    """Read FASTA records in order, returning each record's sequence in chunks without line breaks."""

    def __init__(self, fh):
        self.lines = iter(fh)
        self.pending = None  # header line read past the end of the previous record
        self.parts, self.size = [], 0
        self.in_record = False

    def next_record(self):
        """Skip the rest of the current record; return the next record's ID, or None at the end."""
        while self.read(1 << 20):
            pass
        line = self.pending if self.pending is not None else next(self.lines, None)
        self.pending = None
        while line is not None and not line.startswith(b">"):
            line = next(self.lines, None)
        if line is None:
            return None
        self.in_record = True
        header = line[1:].split(None, 1)
        return header[0].decode("utf-8", "replace") if header else ""

    def read(self, size):
        """Return up to size bases of the current record (fewer only at its end)."""
        while self.in_record and self.size < size:
            line = next(self.lines, None)
            if line is None or line.startswith(b">"):
                self.pending, self.in_record = line, False
                break
            line = line.rstrip(b"\r\n")
            self.parts.append(line)
            self.size += len(line)
        data = b"".join(self.parts)
        chunk, rest = data[:size], data[size:]
        self.parts, self.size = ([rest], len(rest)) if rest else ([], 0)
        return chunk


_TO_UPPER = bytes.maketrans(bytes(range(97, 123)), bytes(range(65, 91)))
_LOWER_TO_N = bytes.maketrans(bytes(range(97, 123)), b"N" * 26)
_NOT_N = re.compile(rb"[^N]+")


def _hard_matches_unmasked(hard, unmasked):
    if hard == unmasked:
        return True
    return all(unmasked[m.start():m.end()] == m.group() for m in _NOT_N.finditer(hard))


# (file mask, reference mask) -> (rule(file chunk, reference chunk), description)
MASK_RULES = {
    ("softmasked", "unmasked"): (lambda soft, unmasked: soft.translate(_TO_UPPER) == unmasked,
                                 "softmasked must equal unmasked apart from lowercase"),
    ("unmasked", "softmasked"): (lambda unmasked, soft: soft.translate(_TO_UPPER) == unmasked,
                                 "unmasked must equal softmasked in uppercase"),
    ("hardmasked", "softmasked"): (lambda hard, soft: soft.translate(_LOWER_TO_N) == hard,
                                   "hardmasked must equal softmasked with lowercase bases replaced by N"),
    ("hardmasked", "unmasked"): (_hard_matches_unmasked, "hardmasked must equal unmasked except where it has N"),
    ("softmasked", "hardmasked"): (lambda soft, hard: soft.translate(_LOWER_TO_N) == hard,
                                   "softmasked with lowercase bases replaced by N must equal hardmasked"),
    ("unmasked", "hardmasked"): (lambda unmasked, hard: _hard_matches_unmasked(hard, unmasked),
                                 "unmasked must equal hardmasked except where hardmasked has N"),
}
# Reference to compare with, in order of preference, when it is in the same folder.
MASK_REFERENCES = {"unmasked": ("softmasked", "hardmasked"), "softmasked": ("unmasked", "hardmasked"),
                   "hardmasked": ("softmasked", "unmasked")}


def compare_masked_fasta(path, mask, reference, reference_mask, chunk_size=1 << 20):
    """Compare a genome FASTA base by base with another mask of the same genome; returns error lines."""
    rule, description = MASK_RULES[(mask, reference_mask)]
    reference = Path(reference)
    differs, wrong_length, errors = [], [], []
    with open_binary_lines(path) as fh, open_binary_lines(reference) as ref_fh:
        ours, theirs = FastaSequenceReader(fh), FastaSequenceReader(ref_fh)
        while True:
            name, ref_name = ours.next_record(), theirs.next_record()
            if name is None or ref_name is None:
                if name != ref_name:
                    errors.append(f"Record count differs from {reference.name}: "
                                  f"{'this file' if ref_name is None else reference.name} has more records")
                break
            if name != ref_name:
                errors.append(f"Record order differs from {reference.name}: {name} here, {ref_name} there")
                break
            position = 0
            while True:
                data, ref_data = ours.read(chunk_size), theirs.read(chunk_size)
                if not data and not ref_data:
                    break
                common = min(len(data), len(ref_data))
                if not rule(data[:common], ref_data[:common]):
                    i = next(i for i in range(common) if not rule(data[i:i + 1], ref_data[i:i + 1]))
                    differs.append(f"{name} at {position + i + 1} ({chr(data[i])} here, {chr(ref_data[i])} there)")
                    break
                if len(data) != len(ref_data):
                    wrong_length.append(name)
                    break
                position += common
    if differs:
        errors.insert(0, summarise_items(f"Masking differs from {reference.name} ({description})", differs))
    if wrong_length:
        errors.append(summarise_items(f"Sequence length differs from {reference.name}", wrong_length))
    return errors


def parse_fai(path):
    """Parse a .fai file into {name: (length, offset, linebases, linewidth)}."""
    entries = {}
    errors = ErrorCollector()
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) not in (5, 6):
                errors.add(f"FAI line {line_no}: expected 5 columns, found {len(fields)}")
                continue
            try:
                values = tuple(int(value) for value in fields[1:5])
            except ValueError:
                errors.add(f"FAI line {line_no}: non-integer field")
                continue
            if fields[0] in entries:
                errors.add(f"FAI line {line_no}: duplicate name {fields[0]}")
            entries[fields[0]] = values
    if not entries and not errors.total:
        errors.add("FAI index is empty")
    return entries, errors


def parse_gzi(path):
    """Parse a .gzi file into a list of (compressed offset, uncompressed offset)."""
    data = Path(path).read_bytes()
    if len(data) < 8:
        raise ValueError("GZI index is truncated")
    (count,) = struct.unpack_from("<Q", data, 0)
    if len(data) != 8 + 16 * count:
        raise ValueError(f"GZI index size does not match its entry count {count}")
    values = struct.unpack_from(f"<{2 * count}Q", data, 8)
    return list(zip(values[0::2], values[1::2]))


def _sample(items, size):
    """Evenly sample up to size items, always including first and last."""
    items = list(items)
    if len(items) <= size:
        return items
    step = (len(items) - 1) / (size - 1) if size > 1 else 0
    return [items[round(i * step)] for i in range(size)]


# ---------------------------------------------------------------------------
# GFF3 / GTF
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


@dataclass
class GenomeMetadata:
    """Expected values from the metadata database for one genome."""
    sequences: list  # (name, accession, length, chromosomal)
    total_genome_length: int = None
    coding_transcripts: int = None
    total_coding_exons: int = None
    available: bool = True

    def sequence_lookup(self, chromosomal_only=False):
        lookup = {}
        for seq in self.sequences:
            if chromosomal_only and not seq[3]:
                continue
            for key in (seq[0], seq[1]):
                if key:
                    lookup[key] = seq
        return lookup


def load_genome_metadata(db_session, genome_uuid):
    """Load assembly sequences and genome statistics for genome_uuid."""
    rows = db_session.execute(
        select(AssemblySequence.name, AssemblySequence.accession, AssemblySequence.length,
               AssemblySequence.chromosomal)
        .join(Genome, Genome.assembly_id == AssemblySequence.assembly_id)
        .where(Genome.genome_uuid == genome_uuid)
    ).all()
    return GenomeMetadata(
        sequences=[(row[0], row[1], row[2], bool(row[3])) for row in rows],
        total_genome_length=_to_int(get_genome_dataset_attribute(
            db_session, genome_uuid, "assembly.stats.total_genome_length", dataset_type="assembly")),
        coding_transcripts=_to_int(get_genome_dataset_attribute(
            db_session, genome_uuid, "genebuild.stats.coding_transcripts")),
        total_coding_exons=_to_int(get_genome_dataset_attribute(
            db_session, genome_uuid, "genebuild.stats.total_coding_exons")),
    )


NO_METADATA = "Metadata not available; pass --database and --genome_uuid to compare with metadata"


def compare_sequences(observed, metadata, chromosomal_only=False, label="seq_regions",
                      length_warning=False):
    """Compare {id: length} from an output file with metadata sequences. Returns Outcome."""
    outcome = Outcome()
    if not metadata.available:
        outcome.skip = NO_METADATA
        return outcome
    lookup = metadata.sequence_lookup(chromosomal_only)
    if not lookup:
        outcome.skip = f"No expected {label} found in metadata"
        return outcome
    seen = set()
    extra, mismatched = [], []
    for name, length in observed.items():
        seq = lookup.get(name)
        if seq is None:
            extra.append(name)
            continue
        seen.add(seq)
        if length != seq[2]:
            mismatched.append(f"{name} {length} vs {seq[2]}")
    missing = [seq[0] or seq[1] for seq in set(lookup.values()) if seq not in seen]
    if missing:
        outcome.errors.append(summarise_items(f"Missing {label}", missing))
    if extra:
        outcome.errors.append(summarise_items(f"Unexpected {label} not in metadata", extra))
    if mismatched:
        (outcome.warnings if length_warning else outcome.errors).append(
            summarise_items(f"Length mismatch with metadata ({label} file vs metadata)", mismatched))
    return outcome


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

_GFF3_CACHE = {}


def cached_gff3_scan(path):
    """Scan a GFF3 file once per process and reuse it for cross-reference checks."""
    path = Path(path)
    key = (str(path.resolve()), path.stat().st_mtime_ns)
    if key not in _GFF3_CACHE:
        _GFF3_CACHE.clear()
        _GFF3_CACHE[key] = scan_gff3(path)
    return _GFF3_CACHE[key]


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

    def run(self, path, label, scanner, index_checker, completeness_checker, require_bgzf=True,
            require_gzip=False, not_applicable_reason="Not applicable for this file", format_checker=None):
        """Run all stages in order applying the stop rules from readme.md.

        Index structure and retrieval run first; parsed-content consistency belongs to format.

        index_checker / completeness_checker may be None when the stage does not apply; the stage is
        then reported as SKIP with not_applicable_reason and does not affect the overall result.
        """
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

    # --- FAI/GZI ----------------------------------------------------------

    def fasta_index_checker(self, path, info, scan):
        outcome = Outcome()
        fai_path = Path(f"{path}.fai")
        gzi_path = Path(f"{path}.gzi")
        if not fai_path.is_file():
            outcome.errors.append(f"FAI index not found: {fai_path.name}")
            return outcome
        fai, fai_errors = parse_fai(fai_path)
        outcome.errors.extend(fai_errors.summary())

        if info.kind != "bgzf":
            outcome.errors.append("Data file is not BGZF; indexed retrieval is not possible")
        if gzi_path.is_file():
            if info.kind == "bgzf":
                block_map = dict(info.blocks)
                bad = [c for c, u in parse_gzi(gzi_path) if block_map.get(c) != u]
                if bad:
                    outcome.errors.append(summarise_items("GZI entries not matching BGZF blocks", bad))
        elif self.settings["require_gzi"]:
            outcome.errors.append(f"GZI index not found: {gzi_path.name}")
        else:
            outcome.warnings.append(f"GZI index not delivered: {gzi_path.name}")


        if info.kind == "bgzf" and fai:
            reader = BgzfReader(path, info.blocks)
            failed = []
            for name in _sample(fai, self.settings["index_sample_size"]):
                length, offset, linebases, _linewidth = fai[name]
                size = min(length, linebases)
                data = reader.read_uncompressed(offset, size)
                if len(data) != size or b"\n" in data or b">" in data:
                    failed.append(name)
            if failed:
                outcome.errors.append(summarise_items("Indexed retrieval failed for", failed))
        return outcome

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
        """Compare parsed data with the index during format validation."""
        outcome = Outcome()
        if isinstance(scan, FastaScan):
            fai, _ = parse_fai(Path(f"{path}.fai"))
            if scan is not None and fai:
                missing = [name for name in scan.records if name not in fai]
                extra = [name for name in fai if name not in scan.records]
                wrong = [
                    name for name, rec in scan.records.items()
                    if name in fai and fai[name] != (rec.length, rec.offset, rec.linebases, rec.linewidth)
                ]
                if missing:
                    outcome.errors.append(summarise_items("Sequences missing from FAI", missing))
                if extra:
                    outcome.errors.append(summarise_items("FAI entries not in FASTA", extra))
                if wrong:
                    outcome.errors.append(summarise_items("FAI entries with wrong length/offset/line layout", wrong))
        else:
            index = parse_csi(Path(f"{path}.csi"))
            if scan is not None and index.names:
                missing = scan.seqids - set(index.names)
                extra = set(index.names) - scan.seqids
                if missing:
                    outcome.errors.append(summarise_items("Seqids missing from CSI", missing))
                if extra:
                    outcome.errors.append(summarise_items("CSI references not in file", extra))
        return outcome


class FastaValidation(OutputValidationBase):
    """Genome (unmasked/softmasked/hardmasked), cDNA and peptide FASTA validation."""

    def _scanner(self, alphabet):
        return lambda path: scan_fasta(path, alphabet, self.settings["max_line_width"])

    def _total_length_mismatch(self, outcome, total, expected):
        """Report FASTA total vs assembly.stats.total_genome_length, saying whether seq_regions explain it."""
        difference = total - expected
        message = (f"Total length {total} does not match assembly.stats.total_genome_length {expected} "
                   f"(FASTA is {abs(difference)} bp {'longer' if difference > 0 else 'shorter'})")
        sequences = {(name, accession): length for name, accession, length, _ in self.metadata.sequences}
        metadata_total = sum(sequences.values())
        explanation = ""
        if not outcome.errors and metadata_total == total:
            explanation = (f"; all {len(sequences)} assembly_sequence seq_regions are present "
                           f"and sum to {metadata_total}, so no seq_region is missing. total_genome_length "
                           f"disagrees with assembly_sequence in the metadata")
        outcome.warnings.append(f"{message}; assembly_sequence lengths sum to {metadata_total}{explanation}")

    def _genome_scanner(self, alphabet, mask):
        """FASTA structure plus the genome header and masking-letter checks."""
        def scanner(path):
            scan = scan_fasta(path, alphabet, self.settings["max_line_width"])
            errors = mask_letter_errors(scan, mask)
            if self.settings["check_genome_headers"]:
                header_errors, header_warnings = genome_header_errors(scan, mask)
                errors += header_errors
                scan.warnings.extend(header_warnings)
            if errors:  # put these summaries before the per-line errors, which are capped
                merged = ErrorCollector()
                for message in errors + list(scan.errors):
                    merged.add(message)
                merged.total += scan.errors.total - len(scan.errors)
                scan.errors = merged
            return scan
        return scanner

    def _mask_comparison(self, mask):
        """Compare with the other mask of the same genome in the same folder (format stage, after the scan)."""
        def checker(path):
            path = Path(path)
            siblings = {classify_file(p, self.settings): p for p in sorted(path.parent.iterdir())
                        if p.is_file() and p != path}
            for reference_mask in MASK_REFERENCES[mask]:
                reference = siblings.get(f"genome_{reference_mask}")
                if reference is None:
                    continue
                try:
                    errors = compare_masked_fasta(path, mask, reference, reference_mask)
                except (OSError, ValueError, zlib.error, EOFError) as exc:
                    return Outcome(warnings=[f"Masking not compared with {reference.name}: {exc}"])
                return Outcome(errors=errors, note=f"masking consistent with {reference.name}")
            wanted = " or ".join(f"{m}.fa.bgz" for m in MASK_REFERENCES[mask])
            return Outcome(note=f"masking checked by letters only; no {wanted} in the same folder to compare with")
        return checker

    def validate_genome_fasta(self, path, mask):
        alphabet = NUCLEOTIDE_ANY_CASE if mask == "softmasked" else NUCLEOTIDE_UPPER

        def completeness(scan):
            outcome = compare_sequences({n: r.length for n, r in scan.records.items()}, self.metadata,
                                        length_warning=True)
            if outcome.skip:  # no metadata: nothing to compare the total with either
                return outcome
            total = sum(record.length for record in scan.records.values())
            expected = self.metadata.total_genome_length
            if expected is None:
                outcome.warnings.append("assembly.stats.total_genome_length not available in metadata")
            elif total != expected:
                self._total_length_mismatch(outcome, total, expected)
            return outcome

        format_checker = self._mask_comparison(mask) if self.settings["compare_genome_masks"] else None
        return self.run(path, Path(path).name, self._genome_scanner(alphabet, mask), self.fasta_index_checker,
                        completeness, format_checker=format_checker)

    def validate_cdna_fasta(self, path, gff3_path):
        def completeness(scan):
            gff3, reason = self._gff3_or_skip(gff3_path)
            if gff3 is None:
                return Outcome(skip=reason)
            outcome = Outcome()
            seen, extra, mismatched = set(), [], []
            for name, record in scan.records.items():
                tid = normalise_id(name)
                exons = gff3.transcripts.get(tid)
                if exons is None:
                    extra.append(name)
                    continue
                seen.add(tid)
                if exons[1] != record.length:
                    mismatched.append(f"{name} {record.length} vs {exons[1]}")
            if extra:
                outcome.errors.append(summarise_items("cDNA sequences without GFF3 exons", extra))
            if mismatched:
                outcome.errors.append(summarise_items("cDNA length differs from GFF3 exon length", mismatched))
            not_exported = set(gff3.transcripts) - seen
            if not_exported:
                outcome.warnings.append(summarise_items("GFF3 transcripts not in cDNA FASTA", not_exported))
            return outcome

        return self.run(path, Path(path).name, self._scanner(NUCLEOTIDE_ANY_CASE),
                        self.fasta_index_checker, completeness)

    def validate_peptide_fasta(self, path, gff3_path):
        def completeness(scan):
            outcome = Outcome()
            self.count_check(outcome, "Coding transcripts (peptide sequences)", len(scan.records),
                             self.metadata.coding_transcripts)
            gff3, reason = self._gff3_or_skip(gff3_path)
            if gff3 is None:
                outcome.skip = reason
                return outcome
            protein_to_tid = {protein: tid for tid, protein in gff3.coding.items()}
            seen, extra, length_diff = set(), [], 0
            for name, record in scan.records.items():
                key = normalise_id(name)
                tid = protein_to_tid.get(key) or (key if key in gff3.coding else None)
                if tid is None:
                    extra.append(name)
                    continue
                seen.add(tid)
                if abs(record.length - gff3.cds_length.get(tid, 0) // 3) > 1:
                    length_diff += 1
            if extra:
                outcome.errors.append(summarise_items("Peptides without a GFF3 CDS", extra))
            missing = [gff3.coding[tid] for tid in gff3.coding if tid not in seen]
            if missing:
                outcome.errors.append(summarise_items("GFF3 coding transcripts missing from peptide FASTA", missing))
            if length_diff:
                outcome.warnings.append(f"{length_diff} peptides differ from GFF3 CDS length / 3 by more than 1")
            return outcome

        return self.run(path, Path(path).name, self._scanner(PROTEIN), self.fasta_index_checker, completeness)


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
            if scan.sequence_regions:
                regions = compare_sequences(
                    {name: end - start + 1 for name, (start, end) in scan.sequence_regions.items()},
                    self.metadata, label="seq_regions in ##sequence-region pragmas")
                outcome.errors.extend(regions.errors)
                if regions.skip:
                    outcome.warnings.append(regions.skip)
            else:
                outcome.warnings.append("No ##sequence-region pragmas; seq_region coverage not checked")
            self.count_check(outcome, "CDS features vs genebuild.stats.total_coding_exons",
                             scan.cds_count, self.metadata.total_coding_exons)
            return outcome

        return self.run(path, Path(path).name, cached_gff3_scan, self.csi_index_checker, completeness,
                        format_checker=run_gff3validator)

    def validate_gtf(self, path, gff3_path):
        def completeness(scan):
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


# ---------------------------------------------------------------------------
# Coordination and reporting
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutputFile:
    """The output file to validate."""
    key: str  # genome_unmasked, cdna, peptide, gff3, gtf, chromosome_tsv
    group: str  # fasta or geneset
    filename: str
    path: str  # file given with -f
    gff3_path: str = None  # GFF3 in the same folder, used for cDNA/peptide/GTF cross-reference

    def __str__(self):
        return f"{self.key}:{self.path or self.filename}"


def output_settings(resource_config):
    settings = dict(DEFAULT_SETTINGS)
    settings.update(resource_config.get("output_validation") or {})
    for flag in ("chromosome_tsv_required", "require_gzi", "strict_metadata_counts", "check_genome_headers",
                 "compare_genome_masks"):
        settings[flag] = str(settings[flag]).lower() in ("1", "true", "yes")
    for number in ("index_sample_size", "max_line_width"):
        settings[number] = int(settings[number])
    return settings


INDEX_SUFFIXES = (".fai", ".gzi", ".csi", ".tbi")
GROUP_BY_KEY = {"cdna": "fasta", "peptide": "fasta", "gff3": "geneset", "gtf": "geneset",
                "raw_gff3": "geneset", "raw_gtf": "geneset", "chromosome_tsv": "geneset"}
_FASTA_NAME = re.compile(r"\.(fa|fasta|fna|faa)(\.b?gz)?$")


def classify_file(path, settings):
    """Return the output key (genome_<mask>, cdna, peptide, gff3, gtf, chromosome_tsv) for a file, or None."""
    name = Path(path).name
    lower = name.lower()
    if lower.endswith(INDEX_SUFFIXES) or lower in ("md5sum.txt",):
        return None
    configured = {settings["cdna_fasta"]: "cdna", settings["peptide_fasta"]: "peptide",
                  settings["gff3"]: "gff3", settings["gtf"]: "gtf", settings["raw_gff3"]: "raw_gff3",
                  settings["raw_gtf"]: "raw_gtf", settings["chromosome_tsv"]: "chromosome_tsv"}
    genome_fasta = settings["genome_fasta"]
    if isinstance(genome_fasta, str):
        genome_fasta = [item.strip() for item in genome_fasta.split(",")]
    for filename in genome_fasta:
        configured[filename] = f"genome_{next((m for m in GENOME_MASKS if m in filename), 'unmasked')}"
    for pattern, key in configured.items():
        if fnmatch.fnmatch(name, pattern):
            return key
    if lower.endswith(".gff3.gz"):
        return "raw_gff3"
    if lower.endswith(".gtf.gz"):
        return "raw_gtf"
    if ".gff3" in lower:
        return "gff3"
    if ".gtf" in lower:
        return "gtf"
    if ".tsv" in lower and "chrom" in lower:
        return "chromosome_tsv"
    if _FASTA_NAME.search(lower):
        for mask in GENOME_MASKS:
            if mask in lower:
                return f"genome_{mask}"
        if ".dna_sm." in lower:
            return "genome_softmasked"
        if ".dna_rm." in lower:
            return "genome_hardmasked"
        if ".dna." in lower:
            return "genome_unmasked"
        if "cdna" in lower:
            return "cdna"
        if "pep" in lower or lower.endswith((".faa", ".faa.gz", ".faa.bgz")):
            return "peptide"
    return None


CLI_FILE_TYPES = ("unmask", "softmask", "hardmask", "chrom", "cdna", "pep",
                  "gff3", "gtf", "raw_gff3", "raw_gtf")
FILE_TYPES = tuple(f"genome_{mask}" for mask in GENOME_MASKS) + tuple(GROUP_BY_KEY)


def normalise_file_type(file_type):
    """Resolve an explicit validator type independently of the input filename."""
    aliases = {"unmask": "genome_unmasked", "softmask": "genome_softmasked",
               "hardmask": "genome_hardmasked", "chrom": "chromosome_tsv",
               "cdna_fasta": "cdna", "peptide_fasta": "peptide", "pep": "peptide",
               **{mask: f"genome_{mask}" for mask in GENOME_MASKS}}
    key = aliases.get(file_type, file_type)
    if key not in FILE_TYPES:
        raise pytest.UsageError(f"Unknown --file-type {file_type!r}; choose from {', '.join(CLI_FILE_TYPES)}")
    return key


def resolve_output_input(config, settings):
    """Resolve one explicit file or one typed output under the public FTP base."""
    target = required_target_file(config)
    file_type = config.getoption("file_type", None)
    if file_type:
        file_type = normalise_file_type(file_type)
    base = config.getoption("base_path", None)
    if target:
        if base:
            raise pytest.UsageError("Use --base-path with --file-type, without -f/--target-file")
        return local_output_files(settings, target, file_type)
    genome_uuid = config.getoption("genome_uuid")
    database = config.getoption("database")
    if not genome_uuid or not database:
        raise pytest.UsageError("FTP lookup requires --genome_uuid and --database")
    rows = list(get_genomes_from_metadata_db(db_url=database, genome_uuids=[genome_uuid]))
    if not rows:
        raise pytest.UsageError(f"Genome not found in metadata: {genome_uuid}")
    from ensembl.datacheck.checks.automation.utils import get_ftp_paths
    paths = set()
    dataset = "assembly" if file_type.startswith("genome_") else "genebuild"
    for genome in rows:
        ftp_paths = get_ftp_paths(
            metadata_uri=database, taxonomy_uri=config.getoption("taxonomy_database", None),
            genome_uuid=genome_uuid, genebuild_date=genome.get("genebuild_date"),
            annotation_source=genome.get("annotation_source"),
            assembly_accession=genome.get("assembly_accession"))
        paths.update(item["path"] for item in ftp_paths if item["dataset_type"] == dataset)
    if len(paths) != 1:
        raise pytest.UsageError(f"Expected one FTP {dataset} path for {genome_uuid}, found {sorted(paths)}")
    directory = Path(base or settings.get("base_path") or "/nfs/ftp/public/ensemblorganisms").expanduser() / paths.pop()
    if not directory.is_dir():
        raise pytest.UsageError(f"FTP output directory not found: {directory}")
    candidates = [p for p in sorted(directory.iterdir())
                  if p.is_file() and classify_file(p, settings) == file_type]
    if len(candidates) != 1:
        raise pytest.UsageError(
            f"Expected one {file_type} file in {directory}, found {len(candidates)}; use -f FILE to select one")
    return local_output_files(settings, candidates[0], file_type)


def local_output_files(settings, target_file, file_type=None):
    """Build the OutputFile for -f FILE; a GFF3 in the same folder is paired for cross-reference."""
    path = Path(target_file).expanduser()
    if not path.is_file():
        raise pytest.UsageError(f"-f/--target-file not found: {path}")
    key = normalise_file_type(file_type) if file_type else classify_file(path, settings)
    if key is None:
        raise pytest.UsageError(
            f"Cannot determine output type of {path.name}; expected a genome/cDNA/peptide FASTA, GFF3, GTF "
            "or chromosome TSV name")
    gff3 = None
    if key in ("cdna", "peptide", "gtf"):
        gff3_files = [p for p in sorted(path.parent.iterdir()) if p.is_file() and classify_file(p, settings) == "gff3"]
        gff3 = str(gff3_files[0]) if gff3_files else None
    group = GROUP_BY_KEY.get(key, "fasta")
    return [OutputFile(key, group, path.name, path=str(path), gff3_path=gff3)]


_METADATA_CACHE = {}


class OutputValidation:
    """Run the right validator for the -f file and report results."""

    def __init__(self, db_session, resource_config, genome):
        self.resource_config = resource_config
        self.settings = output_settings(resource_config)
        self.genome = genome
        uuid = genome.get("genome_uuid")
        if db_session is None or not uuid:
            self.metadata = GenomeMetadata(sequences=[], available=False)
            return
        if uuid not in _METADATA_CACHE:
            _METADATA_CACHE.clear()
            _METADATA_CACHE[uuid] = load_genome_metadata(db_session, uuid)
        self.metadata = _METADATA_CACHE[uuid]

    def validate(self, output_file):
        path = Path(output_file.path)
        gff3_path = output_file.gff3_path
        fasta = FastaValidation(self.metadata, self.settings)
        geneset = GenesetValidation(self.metadata, self.settings)
        if output_file.key.startswith("genome_"):
            return fasta.validate_genome_fasta(path, output_file.key.removeprefix("genome_"))
        if output_file.key == "cdna":
            return fasta.validate_cdna_fasta(path, gff3_path)
        if output_file.key == "peptide":
            return fasta.validate_peptide_fasta(path, gff3_path)
        if output_file.key == "gff3":
            return geneset.validate_gff3(path)
        if output_file.key == "gtf":
            return geneset.validate_gtf(path, gff3_path)
        if output_file.key in ("raw_gff3", "raw_gtf"):
            return geneset.validate_raw_geneset(path, output_file.key.removeprefix("raw_"))
        if output_file.key == "chromosome_tsv":
            return geneset.validate_chromosome_tsv(path)
        raise ValueError(f"Unknown output file key {output_file.key}")

    @staticmethod
    def report(file_report):
        """Log stage results, emit warnings, and fail/skip the pytest item as needed."""
        label = file_report.label
        for stage in file_report.stages:
            log = logger.error if stage.status == FAIL else logger.warning if stage.status == SKIP else logger.info
            log("[%s] %s: %s%s", label, stage.stage, stage.status, f" - {stage.reason}" if stage.reason else "")
            for detail in stage.details[1:]:
                log("      %s", detail)
        overall = file_report.overall
        (logger.error if overall == FAIL else logger.info)("[%s] overall: %s", label, overall)
        for message in file_report.warnings:
            warnings.warn(EnsemblDatacheckWarning(f"[{label}] {message}", "output_validation", "report"))

        failures = file_report.failures
        if failures:
            items = [f"{stage.stage}: {detail}" for stage in failures for detail in (stage.details or [stage.reason])]
            items += [f"{stage.stage}: SKIP - {stage.reason}" for stage in file_report.unexpected_skips]
            raise AssertionError("\n".join(
                [f"Output validation failures in {label}: {len(failures)}. Release path: {file_report.path}",
                 "Full list:"] + [item.replace('"', "") for item in items]
            ))
        if file_report.unexpected_skips:
            pytest.skip("; ".join(f"[{label}] {s.stage}: {s.reason}" for s in file_report.unexpected_skips))


# ---------------------------------------------------------------------------
# pytest wiring
# ---------------------------------------------------------------------------

def _resource_config_from_pytest(config):
    return _build_automation_resource_config(
        config_path=config.getoption("--automation_resource_config"),
        environ=os.environ,
        raw_params=config.getoption("--params"),
        use_alt=config.getoption("use_alt"),
    )


def required_target_file(config):
    """Require a file or validator type; release-wide runs remain unsupported."""
    if config.getoption("release_name", None):
        raise pytest.UsageError("output_validation no longer supports --release_name; it checks one file: -f FILE")
    target_file = config.getoption("target_file")
    if not target_file and not config.getoption("file_type", None):
        raise pytest.UsageError("output_validation needs one input: -f FILE or --file-type TYPE")
    return target_file


def pytest_generate_tests(metafunc):
    """Parametrize each check by (genome, output file) for the -f file."""
    if not {"genomes", "output_file"} <= set(metafunc.fixturenames):
        return
    plugins = metafunc.config.pluginmanager
    if not plugins.has_plugin(TerminalSummary.name):
        plugins.register(TerminalSummary(), TerminalSummary.name)
    try:
        _generate_tests(metafunc)
    except pytest.UsageError as error:
        # pytest cuts a collection error to the terminal width in its summary, and the runner's
        # default --tb=no hides the traceback, so print the full message before re-raising.
        reporter = metafunc.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"output_validation usage error: {error}", red=True, bold=True)
        raise


def _generate_tests(metafunc):
    """Parametrize one resolved file; metadata uses a single --genome_uuid."""
    group = "fasta" if metafunc.function.__name__ == "check_fasta_output" else "geneset"
    settings = output_settings(_resource_config_from_pytest(metafunc.config))
    genome_uuid = metafunc.config.getoption("genome_uuid")
    if genome_uuid and "," in genome_uuid:
        raise pytest.UsageError("-f accepts a single --genome_uuid for metadata checks")
    genome = {"genome_uuid": genome_uuid}
    files = [f for f in resolve_output_input(metafunc.config, settings) if f.group == group]
    if not files:
        # An empty parameter set leaves `genomes` as NOTSET, which the JSON report hook cannot read.
        metafunc.parametrize(("genomes", "output_file"), [pytest.param(
            genome, None, marks=pytest.mark.skip(reason=f"-f file is not a {group} file"),
            id=f"no-{group}-files")])
        return
    metafunc.parametrize(("genomes", "output_file"), [(genome, f) for f in files],
                         ids=[f"{f.filename}-{f.key}" for f in files])


# ---------------------------------------------------------------------------
# --output-dir summary report
# ---------------------------------------------------------------------------

OUTPUT_REPORT_NAME = "output_validation_report.json"


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
    """Collect file records; with --output-dir, write them to <output_dir>/output_validation_report.json.

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
    return {"test": "output_validation", "run_id": run_id,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input": config.getoption("target_file"), "genome_uuid": config.getoption("genome_uuid"),
            "file_type": config.getoption("file_type", None), "base_path": config.getoption("base_path", None)}


REPORT_KEY = pytest.StashKey()


@pytest.fixture(scope="session")
def output_report(request):
    """Collects every file result for the terminal summary; with --output-dir also writes the JSON file."""
    writer = OutputReportWriter(request.config.getoption("output_dir", None), _run_info(request.config))
    request.config.stash[REPORT_KEY] = writer
    yield writer
    if writer.output_dir is not None:
        logger.info("output_validation report written to %s", writer.write())


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

    name = "output_validation_terminal_summary"

    @pytest.hookimpl(trylast=True)
    def pytest_terminal_summary(self, terminalreporter, config):
        writer = config.stash.get(REPORT_KEY, None)
        if writer is None or not writer.records:
            return
        terminalreporter.write_sep("=", "Output validation", bold=True)
        for text, markup in format_terminal_report(writer.document(), writer.written):
            terminalreporter.write_line(text, **markup)


def _validate_and_report(genomes, output_file, db_session, resource_config, output_report):
    file_report = OutputValidation(db_session, resource_config, genomes).validate(output_file)
    output_report.add(file_report, output_file, genomes)
    OutputValidation.report(file_report)


@pytest.fixture(scope="session")
def output_resource_config(request):
    return _resource_config_from_pytest(request.config)


def check_fasta_output(genomes, output_file, db_session, output_resource_config, output_report):
    """Validate genome, cDNA and peptide FASTA outputs (select with -k fasta or -k all)."""
    _validate_and_report(genomes, output_file, db_session, output_resource_config, output_report)


def check_geneset_output(genomes, output_file, db_session, output_resource_config, output_report):
    """Validate GFF3, GTF, raw GFF3/GTF and chromosome TSV outputs (select with -k geneset or -k all)."""
    _validate_and_report(genomes, output_file, db_session, output_resource_config, output_report)


# -k matches names in a check function's __dict__, so this attribute makes "-k all" select both
# checks without registering a custom marker (which warns when run outside this repository).
check_fasta_output.all = True
check_geneset_output.all = True
