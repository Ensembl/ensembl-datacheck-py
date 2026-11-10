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

"""FASTA scanning, genome header and masking rules, FAI/GZI indexes and FastaValidation."""

import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .base import OutputValidationBase
from .common import (BgzfReader, ErrorCollector, Outcome, _sample, compare_sequences, open_binary_lines,
                     summarise_items)
from .file_types import classify_file
from .gene_models import normalise_id

NUCLEOTIDE_UPPER = b"ACGTNRYKMSWBDHV"
NUCLEOTIDE_ANY_CASE = NUCLEOTIDE_UPPER + NUCLEOTIDE_UPPER.lower()
PROTEIN = b"ACDEFGHIKLMNPQRSTVWYXBZJUO*"


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
    location must name the record; a START..END span differing from the sequence length warns.
    Returns (errors, warnings).
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
    warnings = [f"{trailing} headers end with whitespace"] if trailing else []
    if wrong_length:
        warnings.append(summarise_items("Header location length differs from the sequence length", wrong_length))
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

    def index_content_checker(self, path, scan):
        """Compare the parsed FASTA records with the FAI during format validation."""
        outcome = Outcome()
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
        return outcome
