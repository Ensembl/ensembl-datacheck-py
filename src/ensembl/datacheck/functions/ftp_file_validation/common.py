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

"""Shared pieces: stage results, gzip/BGZF reading, index sampling and genome metadata."""

import bisect
import gzip
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from ensembl.production.metadata.api.models import AssemblySequence, Genome
from ensembl.datacheck.functions.utils import get_genome_dataset_attribute

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
STAGES = ("compression", "index", "format", "completeness")

MAX_DETAILS = 20
GZIP_MAGIC = b"\x1f\x8b"
BGZF_EOF = bytes.fromhex("1f8b08040000000000ff0600424302001b0003000000000000000000")

GENOME_MASKS = ("unmasked", "softmasked", "hardmasked")


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


def _sample(items, size):
    """Evenly sample up to size items, always including first and last."""
    items = list(items)
    if len(items) <= size:
        return items
    step = (len(items) - 1) / (size - 1) if size > 1 else 0
    return [items[round(i * step)] for i in range(size)]


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
