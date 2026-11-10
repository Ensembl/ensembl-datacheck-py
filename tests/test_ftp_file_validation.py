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

"""Unit tests for FTPdump output validation using synthetic BGZF files and indexes."""

import gzip
import json
import struct
import zlib
from pathlib import Path

import pytest

from ensembl.datacheck.functions import ftp_file_validation as ov
from ensembl.datacheck.functions.ftp_file_validation import dispatch as ov_dispatch
from ensembl.datacheck.functions.ftp_file_validation import geneset as ov_geneset

BLOCK = 64  # tiny blocks so random access crosses BGZF block boundaries


def _bgzf_block(data):
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    cdata = compressor.compress(data) + compressor.flush()
    bsize = len(cdata) + 25
    header = struct.pack("<BBBBIBBHBBHH", 31, 139, 8, 4, 0, 0, 255, 6, 66, 67, 2, bsize)
    return header + cdata + struct.pack("<II", zlib.crc32(data), len(data))


def write_bgzf(path, text, eof=True):
    """Write text as BGZF; returns [(compressed offset, uncompressed offset)] of each block."""
    data = text.encode()
    blocks, out, uoffset = [], bytearray(), 0
    for start in range(0, len(data), BLOCK):
        blocks.append((len(out), uoffset))
        chunk = data[start:start + BLOCK]
        out += _bgzf_block(chunk)
        uoffset += len(chunk)
    if eof:
        out += ov.BGZF_EOF
    path.write_bytes(bytes(out))
    return blocks


def write_fai(fasta_path, text, line_width=60):
    lines, offset, name = [], 0, None
    records = {}
    for line in text.splitlines(keepends=True):
        if line.startswith(">"):
            name = line[1:].split()[0]
            records[name] = [0, offset + len(line), 0, 0]
        else:
            rec = records[name]
            if rec[2] == 0:
                rec[2], rec[3] = len(line.rstrip("\n")), len(line)
            rec[0] += len(line.rstrip("\n"))
        offset += len(line)
    for name, (length, off, bases, width) in records.items():
        lines.append(f"{name}\t{length}\t{off}\t{bases}\t{width}\n")
    (fasta_path.parent / f"{fasta_path.name}.fai").write_text("".join(lines))


def voffset_for(blocks, uoffset):
    coffset, ustart = [b for b in blocks if b[1] <= uoffset][-1]
    return (coffset << 16) | (uoffset - ustart)


def write_csi(data_path, text, blocks):
    """Write a minimal tabix-style CSI with one bin per reference pointing at its first record."""
    names, first = [], {}
    offset = 0
    for line in text.splitlines(keepends=True):
        if not line.startswith("#"):
            seqid = line.split("\t", 1)[0]
            if seqid not in first:
                names.append(seqid)
                first[seqid] = voffset_for(blocks, offset)
        offset += len(line)
    name_blob = b"".join(name.encode() + b"\0" for name in names)
    aux = struct.pack("<7i", 0, 1, 4, 5, ord("#"), 0, len(name_blob)) + name_blob
    body = b"CSI\x01" + struct.pack("<iii", 14, 5, len(aux)) + aux + struct.pack("<i", len(names))
    for name in names:
        body += struct.pack("<i", 1) + struct.pack("<IQi", 0, 0, 1) + struct.pack("<QQ", first[name], first[name] + 1)
    with gzip.open(data_path.parent / f"{data_path.name}.csi", "wb") as fh:
        fh.write(body)


METADATA = ov.GenomeMetadata(
    sequences=[("1", "CM000001.1", 120, True), ("2", "CM000002.1", 70, True), ("MT", "CM000003.1", 10, False)],
    total_genome_length=200,
    coding_transcripts=1,
    total_coding_exons=2,
)
SETTINGS = ov.output_settings({})


GENOME_SEQUENCES = {"1": ("chromosome", "ACGT" * 30), "2": ("chromosome", "acgtN" * 14), "MT": ("scaffold", "A" * 10)}


def genome_fasta(mask="softmasked"):
    """Softmasked test genome, or the unmasked / hardmasked version of it, with Ensembl-style headers."""
    def wrap(seq):
        return "".join(seq[i:i + 60] + "\n" for i in range(0, len(seq), 60))
    def masked(seq):
        if mask == "unmasked":
            return seq.upper()
        if mask == "hardmasked":
            return "".join("N" if base.islower() else base for base in seq)
        return seq
    return "".join(f">{name} {mask}:{coord} GRCh38:{name}:1:{len(seq)}:1\n{wrap(masked(seq))}"
                   for name, (coord, seq) in GENOME_SEQUENCES.items())


GFF3 = (
    "##gff-version 3\n"
    "##sequence-region 1 1 120\n"
    "##sequence-region 2 1 70\n"
    "##sequence-region MT 1 10\n"
    "1\tens\tgene\t1\t60\t.\t+\t.\tID=gene:G1\n"
    "1\tens\tmRNA\t1\t60\t.\t+\t.\tID=transcript:T1;Parent=gene:G1;version=2\n"
    "1\tens\texon\t1\t20\t.\t+\t.\tParent=transcript:T1\n"
    "1\tens\tCDS\t1\t20\t.\t+\t0\tID=CDS:P1;Parent=transcript:T1;protein_id=P1\n"
    "1\tens\texon\t41\t50\t.\t+\t.\tParent=transcript:T1\n"
    "1\tens\tCDS\t41\t50\t.\t+\t1\tID=CDS:P1;Parent=transcript:T1;protein_id=P1\n"
    "2\tens\tgene\t5\t30\t.\t-\t.\tID=gene:G2\n"
    "2\tens\tncRNA\t5\t30\t.\t-\t.\tID=transcript:T2;Parent=gene:G2\n"
    "2\tens\texon\t5\t30\t.\t-\t.\tParent=transcript:T2\n"
)

GTF = (
    '1\tens\tgene\t1\t60\t.\t+\t.\tgene_id "G1";\n'
    '1\tens\ttranscript\t1\t60\t.\t+\t.\tgene_id "G1"; transcript_id "T1";\n'
    '1\tens\texon\t1\t20\t.\t+\t.\tgene_id "G1"; transcript_id "T1";\n'
    '1\tens\texon\t41\t50\t.\t+\t.\tgene_id "G1"; transcript_id "T1";\n'
    '2\tens\tgene\t5\t30\t.\t-\t.\tgene_id "G2";\n'
    '2\tens\texon\t5\t30\t.\t-\t.\tgene_id "G2"; transcript_id "T2";\n'
)


GTF = "".join(line.rstrip("\n") +
              ' gene_version "1"; gene_biotype "protein_coding"; gene_source "ensembl";\n'
              for line in GTF.splitlines(keepends=True))


@pytest.fixture(autouse=True)
def no_external_tools(monkeypatch):
    monkeypatch.setattr(ov_geneset, "run_gff3validator", lambda path: ov.Outcome())
    monkeypatch.setattr(ov_geneset, "run_genepred_check", lambda path: ov.Outcome())
    ov._GFF3_CACHE.clear()


def statuses(report):
    return {stage.stage: stage.status for stage in report.stages}


def make_gff3(tmp_path, text=GFF3):
    path = tmp_path / "genes.gff3.bgz"
    write_csi(path, text, write_bgzf(path, text))
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(text)
    return path


def test_genome_fasta_passes(tmp_path):
    path = tmp_path / "softmasked.fa.bgz"
    text = genome_fasta()
    write_bgzf(path, text)
    write_fai(path, text)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    assert statuses(report) == {s: ov.PASS for s in ov.STAGES}, report
    assert report.overall == ov.PASS


def test_unmasked_rejects_lowercase_and_skips_completeness(tmp_path):
    path = tmp_path / "unmasked.fa.bgz"
    text = genome_fasta()
    write_bgzf(path, text)
    write_fai(path, text)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "unmasked")
    result = statuses(report)
    assert result["format"] == ov.FAIL
    assert result["completeness"] == ov.SKIP
    assert report.overall == ov.FAIL


def test_missing_seq_region_and_length(tmp_path):
    path = tmp_path / "softmasked.fa.bgz"
    text = genome_fasta().split(">MT")[0]
    write_bgzf(path, text)
    write_fai(path, text)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    completeness = report.stages[-1]
    assert completeness.status == ov.FAIL
    assert any("Missing seq_regions (1): MT" in d for d in completeness.details)
    assert any("total_genome_length" in w for w in report.warnings)


def test_wrong_fai_and_missing_eof(tmp_path):
    path = tmp_path / "softmasked.fa.bgz"
    text = genome_fasta()
    write_bgzf(path, text, eof=False)
    (tmp_path / "softmasked.fa.bgz.fai").write_text("1\t120\t999\t60\t61\n")
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    result = statuses(report)
    assert result["compression"] == ov.FAIL
    assert result == {"compression": ov.FAIL, "index": ov.SKIP,
                      "format": ov.SKIP, "completeness": ov.SKIP}


def test_missing_file_skips_remaining(tmp_path):
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(tmp_path / "x.fa.bgz", "unmasked")
    assert statuses(report) == {"compression": ov.FAIL, "index": ov.SKIP, "format": ov.SKIP, "completeness": ov.SKIP}


def test_scan_fasta_format_errors(tmp_path):
    path = tmp_path / "bad.fa"
    path.write_text("ACGT\n>a\nACGT\nAC\nACGT\n>a\n\n>b\nAXZ")
    scan = ov.scan_fasta(path, ov.NUCLEOTIDE_UPPER)
    text = "\n".join(scan.errors)
    for expected in ("before the first header", "inconsistent line length", "duplicate sequence ID",
                     "blank line", "invalid sequence characters", "does not end with a newline"):
        assert expected in text


def test_gff3_cdna_peptide_gtf(tmp_path):
    gff3 = make_gff3(tmp_path)
    geneset = ov.GenesetValidation(METADATA, SETTINGS)
    assert geneset.validate_gff3(gff3).overall == ov.PASS

    cdna = tmp_path / "cdna.fa.bgz"
    cdna_text = ">T1.2 cdna\n" + "A" * 30 + "\n>T2\n" + "C" * 26 + "\n"
    write_bgzf(cdna, cdna_text)
    write_fai(cdna, cdna_text)
    fasta = ov.FastaValidation(METADATA, SETTINGS)
    assert fasta.validate_cdna_fasta(cdna, gff3).overall == ov.PASS

    pep = tmp_path / "pep.fa.bgz"
    pep_text = ">P1.1 pep\nMKLMKLMKL*\n"
    write_bgzf(pep, pep_text)
    write_fai(pep, pep_text)
    assert fasta.validate_peptide_fasta(pep, gff3).overall == ov.PASS

    gtf = tmp_path / "genes.gtf.bgz"
    write_csi(gtf, GTF, write_bgzf(gtf, GTF))
    with gzip.open(gtf.with_suffix(".gz"), "wt") as fh:
        fh.write(GTF)
    assert geneset.validate_gtf(gtf, gff3).overall == ov.PASS

    bad_gtf_text = GTF.replace("41\t50", "41\t51")
    bad_gtf = tmp_path / "bad.gtf.bgz"
    write_csi(bad_gtf, bad_gtf_text, write_bgzf(bad_gtf, bad_gtf_text))
    with gzip.open(bad_gtf.with_suffix(".gz"), "wt") as fh:
        fh.write(bad_gtf_text)
    completeness = geneset.validate_gtf(bad_gtf, gff3).stages[-1]
    assert completeness.status == ov.FAIL
    assert "exon regions differing from GFF3 (1): T1" in completeness.reason


def test_cdna_length_mismatch(tmp_path):
    gff3 = make_gff3(tmp_path)
    cdna = tmp_path / "cdna.fa.bgz"
    cdna_text = ">T1\n" + "A" * 31 + "\n>T9\nAC\n"
    write_bgzf(cdna, cdna_text)
    write_fai(cdna, cdna_text)
    completeness = ov.FastaValidation(METADATA, SETTINGS).validate_cdna_fasta(cdna, gff3).stages[-1]
    assert completeness.status == ov.FAIL
    assert any("without GFF3 exons (1): T9" in d for d in completeness.details)
    assert any("T1 31 vs 30" in d for d in completeness.details)


def test_csi_name_mismatch_fails_index(tmp_path):
    path = tmp_path / "genes.gff3.bgz"
    blocks = write_bgzf(path, GFF3)
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(GFF3)
    write_csi(path, GFF3.replace("\n2\t", "\nX\t"), blocks)
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_gff3(path)
    assert statuses(report)["index"] == ov.FAIL


def test_gff3_format_errors():
    errors = ov.ErrorCollector()
    assert ov._check_feature_columns(["1", "s", "CDS", "10", "5", ".", "+", ".", ""], 1, errors) is None
    assert ov._check_feature_columns(["1", "s", "CDS", "1", "5", ".", "x", ".", ""], 2, errors) == (1, 5)
    assert len(errors) == 3


def test_external_tool_missing_is_skip_not_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(ov_geneset, "run_gff3validator", lambda path: ov.Outcome(skip="gt not found"))
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_gff3(make_gff3(tmp_path))
    assert statuses(report)["format"] == ov.SKIP
    assert report.overall == ov.SKIP
    with pytest.raises(pytest.skip.Exception):
        ov.OutputValidation.report(report)


def test_chromosome_tsv(tmp_path):
    path = tmp_path / "chromosomes.tsv"
    path.write_text("1\t120\n2\t70\n")
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_chromosome_tsv(path)
    assert report.overall == ov.PASS
    assert statuses(report)["compression"] == ov.SKIP

    path.write_text("name\tlength\n1\t120\n")
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_chromosome_tsv(path)
    assert statuses(report)["format"] == ov.FAIL


def test_report_failure_message_matches_hook_format(tmp_path):
    report = ov.FileReport("x.fa.bgz", tmp_path / "x.fa.bgz")
    report.add(ov.StageResult("compression", ov.PASS))
    report.add(ov.StageResult("completeness", ov.FAIL, "Missing seq_regions (2): a, b",
                              ["Missing seq_regions (2): a, b"]))
    with pytest.raises(AssertionError) as excinfo:
        ov.OutputValidation.report(report)
    lines = str(excinfo.value).splitlines()
    assert lines[0] == f"FTP file validation failures in x.fa.bgz: 1. Release path: {tmp_path / 'x.fa.bgz'}"
    assert lines[1] == "Full list:"
    assert lines[2] == "completeness: Missing seq_regions (2): a, b"


def test_load_genome_metadata_from_sqlite():
    from pathlib import Path
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    db = Path(__file__).parent / "database" / "ensembl_genome_metadata.db"
    with Session(create_engine(f"sqlite:///{db}")) as session:
        metadata = ov.load_genome_metadata(session, "a73351f7-93e7-11ec-a39d-005056b38ce3")
    assert metadata.sequences
    assert metadata.total_genome_length


def test_classify_file():
    assert ov.classify_file("softmasked.fa.bgz", SETTINGS) == "genome_softmasked"
    assert ov.classify_file("Homo_sapiens.GRCh38.dna_rm.toplevel.fa.gz", SETTINGS) == "genome_hardmasked"
    assert ov.classify_file("Homo_sapiens.GRCh38.dna.toplevel.fa.gz", SETTINGS) == "genome_unmasked"
    assert ov.classify_file("cdna.fa.bgz", SETTINGS) == "cdna"
    assert ov.classify_file("pep.fa.bgz", SETTINGS) == "peptide"
    assert ov.classify_file("genes.gff3.bgz", SETTINGS) == "gff3"
    assert ov.classify_file("genes.gtf.bgz", SETTINGS) == "gtf"
    assert ov.classify_file("chromosomes.tsv", SETTINGS) == "chromosome_tsv"
    assert ov.classify_file("pep.fa.bgz.fai", SETTINGS) is None
    assert ov.classify_file("genes.embl.gz", SETTINGS) is None


def test_local_output_files_pairs_sibling_gff3(tmp_path):
    (tmp_path / "geneset").mkdir()
    for rel in ("softmasked.fa.bgz", "geneset/cdna.fa.bgz", "geneset/genes.gff3.bgz",
                "geneset/genes.gff3.bgz.csi", "readme.txt"):
        (tmp_path / rel).write_text("x")
    single = ov.local_output_files(SETTINGS, tmp_path / "geneset" / "cdna.fa.bgz")
    assert [(f.key, f.gff3_path) for f in single] == [("cdna", str(tmp_path / "geneset" / "genes.gff3.bgz"))]
    genome = ov.local_output_files(SETTINGS, tmp_path / "softmasked.fa.bgz")
    assert [(f.key, f.gff3_path) for f in genome] == [("genome_softmasked", None)]
    with pytest.raises(pytest.UsageError):
        ov.local_output_files(SETTINGS, tmp_path / "readme.txt")
    with pytest.raises(pytest.UsageError, match="not found"):
        ov.local_output_files(SETTINGS, tmp_path / "missing.fa.bgz")


def test_local_validation_without_metadata_skips_completeness(tmp_path):
    path = tmp_path / "softmasked.fa.bgz"
    text = genome_fasta()
    write_bgzf(path, text)
    write_fai(path, text)
    output_file = ov.local_output_files(SETTINGS, path)[0]
    report = ov.OutputValidation(None, {}, {"genome_uuid": None}).validate(output_file)
    assert statuses(report) == {"compression": ov.PASS, "index": ov.PASS, "format": ov.PASS,
                                "completeness": ov.SKIP}
    assert ov.NO_METADATA in report.stages[-1].reason


def test_runner_translates_short_flags_only_for_ftp_file_validation():
    from ensembl.datacheck.runner import translate_short_flags
    assert translate_short_flags(["--test=ftp_file_validation", "-f", "a.fa"]) == [
        "--test=ftp_file_validation", "--target-file", "a.fa"]
    assert translate_short_flags(["--test=ftp_file_validation", "-f=a.fa"]) == [
        "--test=ftp_file_validation", "--target-file", "a.fa"]
    assert translate_short_flags(["--test", "fasta", "-f"]) == ["--test", "fasta", "-f"]


@pytest.mark.parametrize("test", ["ftp_file_validation/fasta", "ftp_file_validation/geneset", "ftp_file_validation/"])
def test_runner_translates_short_flags_for_ftp_file_validation_parts(test):
    from ensembl.datacheck.runner import apply_ftp_file_validation_defaults, translate_short_flags
    assert translate_short_flags([f"--test={test}", "-f", "a.fa"]) == [f"--test={test}", "--target-file", "a.fa"]
    assert apply_ftp_file_validation_defaults([f"--test={test}", "--database", "mysql://u@h:1/db"]) == [
        f"--test={test}", "--database", "mysql+pymysql://u@h:1/db"]
    assert translate_short_flags(["--test=ftp_file_validation_other", "-f", "a"]) == [
        "--test=ftp_file_validation_other", "-f", "a"]


RAW_GTF_LAST = '2\tens\tgene\t5\t30\t.\t-\t.\tgene_id "G2"; gene_version "1"; gene_biotype "lncRNA"; gene_source "ensembl";\n'


def write_gzip(path, text):
    with gzip.open(path, "wt") as fh:
        fh.write(text)
    return path


@pytest.mark.parametrize("file_format,text", [
    ("gtf", GTF + RAW_GTF_LAST),
    ("gff3", GFF3),
    ("gff3", GFF3 + "###\n"),
])
def test_raw_geneset_complete_passes(tmp_path, file_format, text):
    path = write_gzip(tmp_path / f"genes.{file_format}.gz", text)
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_raw_geneset(path, file_format)
    assert statuses(report) == {"compression": ov.PASS, "index": ov.SKIP, "format": ov.PASS,
                                "completeness": ov.SKIP}
    assert report.overall == ov.PASS  # index/completeness are not-applicable skips


@pytest.mark.parametrize("file_format,text,expected", [
    ("gtf", GTF + RAW_GTF_LAST.replace(' gene_source "ensembl";', ""), "missing required attributes (truncated) (1): gene_source"),
    ("gtf", GTF + RAW_GTF_LAST.replace('gene_version "1"', 'gene_version ""'), "gene_version"),
    ("gtf", GTF + RAW_GTF_LAST[:40], "does not end with a newline"),
    ("gff3", GFF3 + "2\tens\texon\t5", "incomplete (truncated)"),
])
def test_raw_geneset_truncation_fails(tmp_path, file_format, text, expected):
    path = write_gzip(tmp_path / f"genes.{file_format}.gz", text)
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_raw_geneset(path, file_format)
    fmt = next(stage for stage in report.stages if stage.stage == "format")
    assert fmt.status == ov.FAIL
    assert any(expected in detail for detail in fmt.details), fmt.details


def test_raw_geneset_corrupt_gzip_and_plain(tmp_path):
    path = write_gzip(tmp_path / "genes.gtf.gz", GTF + RAW_GTF_LAST)
    path.write_bytes(path.read_bytes()[:-12])  # chop the gzip trailer
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_raw_geneset(path, "gtf")
    assert statuses(report)["compression"] == ov.FAIL

    plain = tmp_path / "plain.gtf.gz"
    plain.write_text(GTF + RAW_GTF_LAST)
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_raw_geneset(plain, "gtf")
    assert statuses(report)["compression"] == ov.FAIL


def test_classify_raw_geneset():
    assert ov.classify_file("genes.gff3.gz", SETTINGS) == "raw_gff3"
    assert ov.classify_file("genes.gtf.gz", SETTINGS) == "raw_gtf"
    assert ov.classify_file("genes.gtf.bgz", SETTINGS) == "gtf"


def test_external_format_validation_runs_after_index_without_mutating_cache(tmp_path, monkeypatch):
    path = make_gff3(tmp_path)
    cached = ov.cached_gff3_scan(path)
    events = []
    validator = ov.GenesetValidation(METADATA, SETTINGS)
    original = validator.csi_index_checker

    def check_index(*args):
        events.append("index")
        assert args[2] is None
        return original(*args)

    def check_format(path):
        events.append("format")
        return ov.Outcome(errors=["External validator rejected the file"], warnings=["Tool warning"])

    monkeypatch.setattr(validator, "csi_index_checker", check_index)
    monkeypatch.setattr(ov_geneset, "run_gff3validator", check_format)
    report = validator.validate_gff3(path)
    assert events == ["index", "format"]
    assert statuses(report) == dict(zip(ov.STAGES, [ov.PASS, ov.PASS, ov.FAIL, ov.SKIP]))
    assert report.warnings == ["format: Tool warning"]
    assert not cached.errors
    assert cached.skip is None
    assert cached.transcripts


@pytest.mark.parametrize("size", [0, 10, 25])
def test_invalid_bgzf_block_size_is_reported(tmp_path, size):
    path = tmp_path / "genes.gff3.bgz"
    block = bytearray(_bgzf_block(b"feature\n"))
    struct.pack_into("<H", block, 16, size)
    path.write_bytes(block)
    info = ov.inspect_compression(path)
    assert not info.readable
    assert "invalid BGZF block size" in info.error


def test_scan_fasta_checks_ported_from_fasta_py(tmp_path):
    path = tmp_path / "headers.fa"
    long_header = ">long " + "x" * 90 + "\n"
    path.write_bytes(b">ok\nACGT\n>bin\xff\xfe\nACGT\n>ctl\x00x\nACGT\n" + long_header.encode() + b"ACGT\n")
    scan = ov.scan_fasta(path, ov.NUCLEOTIDE_UPPER)
    text = "\n".join(scan.errors)
    assert "Line 3: header is not valid UTF-8 text" in text
    assert "Line 5: header contains control characters" in text
    assert scan.warnings == ["1 header lines are longer than 80 characters"]


def test_scan_fasta_header_tab_is_text(tmp_path):
    path = tmp_path / "tab.fa"
    path.write_bytes(b">a\tdescription\nACGT\n")
    assert not ov.scan_fasta(path, ov.NUCLEOTIDE_UPPER).errors


@pytest.mark.parametrize("kind", ["cdna", "peptide", "gtf"])
def test_invalid_gff3_cross_reference_skips_completeness(tmp_path, kind):
    gff3 = make_gff3(tmp_path, GFF3 + "truncated feature\n")
    if kind == "gtf":
        path = tmp_path / "genes.gtf.bgz"
        write_csi(path, GTF, write_bgzf(path, GTF))
        with gzip.open(path.with_suffix(".gz"), "wt") as fh:
            fh.write(GTF)
        report = ov.GenesetValidation(METADATA, SETTINGS).validate_gtf(path, gff3)
    else:
        path = tmp_path / f"{kind}.fa.bgz"
        text = ">T1\nACGT\n"
        write_bgzf(path, text)
        write_fai(path, text)
        validator = ov.FastaValidation(METADATA, SETTINGS)
        validate = validator.validate_cdna_fasta if kind == "cdna" else validator.validate_peptide_fasta
        report = validate(path, gff3)
    assert statuses(report)["completeness"] == ov.SKIP
    assert "invalid GFF3" in report.stages[-1].reason
    assert report.overall == ov.SKIP


def test_peptide_missing_cross_reference_is_not_pass(tmp_path):
    path = tmp_path / "pep.fa.bgz"
    text = ">P1\nACGT\n"
    write_bgzf(path, text)
    write_fai(path, text)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_peptide_fasta(path, None)
    assert statuses(report)["completeness"] == ov.SKIP
    assert report.overall == ov.SKIP


class _Config:
    def __init__(self, **options):
        self.options = options

    def getoption(self, name, default=None):
        return self.options.get(name, default)


def test_required_target_file():
    assert ov.required_target_file(_Config(target_file="a.fa")) == "a.fa"
    with pytest.raises(pytest.UsageError, match="needs one input: -f FILE"):
        ov.required_target_file(_Config())
    with pytest.raises(pytest.UsageError, match="no longer supports --release_name"):
        ov.required_target_file(_Config(target_file="a.fa", release_name="115"))


@pytest.mark.parametrize("flags", [["-d", "dir"], ["--target-dir=dir"], ["-rn", "115", "-release-check"],
                                   ["-rn=115"], ["--release_name", "115"], ["--release-check"]])
def test_runner_rejects_folder_and_release_flags(flags):
    from ensembl.datacheck.runner import translate_short_flags
    with pytest.raises(SystemExit, match="no longer supported: ftp_file_validation checks one file"):
        translate_short_flags(["--test=ftp_file_validation"] + flags)
    assert translate_short_flags(["--test=other"] + flags) == ["--test=other"] + flags


def test_removed_fasta_check_points_to_ftp_file_validation():
    from pathlib import Path
    import ensembl.datacheck.runner as runner
    from ensembl.datacheck.runner import check_removed_test
    checks = Path(runner.__file__).parent / "checks"
    assert not (checks / "fasta.py").exists()
    assert (checks / "ftp_file_validation" / "fasta.py").is_file()  # only inside ftp_file_validation/
    for args in (["--test=fasta"], ["--test", "fasta", "--file=x.fa"]):
        with pytest.raises(SystemExit, match="ftp_file_validation"):
            check_removed_test(args)
    check_removed_test(["--test=ftp_file_validation", "-f", "x.fa"])  # no exit


def test_mysql_url_uses_pymysql():
    from ensembl.datacheck.runner import mysql_url_for_pymysql
    assert mysql_url_for_pymysql("mysql://ensro@mysql-ens-production-1:4721/ensembl_genome_metadata") == \
        "mysql+pymysql://ensro@mysql-ens-production-1:4721/ensembl_genome_metadata"
    assert mysql_url_for_pymysql("mysql+pymysql://u@h/db") == "mysql+pymysql://u@h/db"
    assert mysql_url_for_pymysql("sqlite:///x.db") == "sqlite:///x.db"


def test_runner_ftp_file_validation_defaults(tmp_path):
    from ensembl.datacheck.runner import apply_ftp_file_validation_defaults
    out = tmp_path / "out"
    args = apply_ftp_file_validation_defaults(
        ["--test=ftp_file_validation", "--database", "mysql://ensro@h:1/ensembl_genome_metadata",
         "--output-dir", str(out)])
    assert args[:3] == ["--test=ftp_file_validation", "--database", "mysql+pymysql://ensro@h:1/ensembl_genome_metadata"]
    assert args[-2:] == ["--json-report", f"--json-report-file={out / 'report.json'}"]
    assert out.is_dir()
    args = apply_ftp_file_validation_defaults(
        ["--test=ftp_file_validation", "--database=mysql://h/db", "--output-dir", str(out), "--json-report-file=x.json"])
    assert args == ["--test=ftp_file_validation", "--database", "mysql+pymysql://h/db", "--output-dir", str(out),
                    "--json-report-file=x.json"]
    other = ["--test=other", "--database", "mysql://h/db"]
    assert apply_ftp_file_validation_defaults(list(other)) == other


def _file_report(name, failed=False):
    report = ov.FileReport(name, Path("/dumps") / name)
    report.add(ov.StageResult("compression", ov.PASS, "bgzf"))
    report.add(ov.StageResult("index", ov.SKIP, "Not applicable", expected_skip=True))
    report.add(ov.StageResult("format", ov.FAIL if failed else ov.PASS, "bad" if failed else "",
                              ["Line 2: invalid"] if failed else []))
    report.add(ov.StageResult("completeness", ov.SKIP, "Metadata not available"))
    report.warnings.append("long lines")
    return report


def test_output_report_record_and_merge(tmp_path):
    output_file = ov.OutputFile("cdna", "fasta", "cdna.fa.bgz", path="/dumps/cdna.fa.bgz")
    genome = {"genome_uuid": "g1"}
    info = {"test": "ftp_file_validation", "run_id": "run1"}

    first = ov.OutputReportWriter(tmp_path, info)
    first.add(_file_report("cdna.fa.bgz"), output_file, genome)
    second = ov.OutputReportWriter(tmp_path, info)  # another xdist worker in the same run
    second.add(_file_report("pep.fa.bgz", failed=True), output_file, genome)
    first.write()
    document = json.loads(second.write().read_text())

    assert document["conclusion"] == ov.FAIL
    assert document["summary"] == {"files": 2, "PASS": 0, "FAIL": 1, "SKIP": 1}
    record = {r["file"]: r for r in document["files"]}["/dumps/pep.fa.bgz"]
    assert record["conclusion"] == ov.FAIL and record["genome_uuid"] == "g1" and record["file_type"] == "cdna"
    assert record["result"]["format"] == {"status": "FAIL", "reason": "bad", "details": ["Line 2: invalid"]}
    assert record["result"]["index"]["not_applicable"] is True
    assert record["warnings"] == ["long lines"]

    rerun = ov.OutputReportWriter(tmp_path, {**info, "run_id": "run2"})  # a new run replaces the file
    rerun.add(_file_report("cdna.fa.bgz"), output_file, genome)
    assert json.loads(rerun.write().read_text())["summary"]["files"] == 1


@pytest.mark.parametrize("args", [["--output-dir"], ["--output-dir", "--tb=short"], ["--output-dir="]])
def test_runner_rejects_missing_output_dir(args):
    from ensembl.datacheck.runner import apply_ftp_file_validation_defaults
    with pytest.raises(SystemExit, match="--output-dir requires a folder"):
        apply_ftp_file_validation_defaults(["--test=ftp_file_validation", "-f", "x.fa"] + args)


def test_gff3_completeness_skips_without_metadata(tmp_path):
    gff3 = make_gff3(tmp_path)
    no_metadata = ov.GenomeMetadata(sequences=[], available=False)
    report = ov.GenesetValidation(no_metadata, SETTINGS).validate_gff3(gff3)
    completeness = {stage.stage: stage for stage in report.stages}["completeness"]
    assert completeness.status == ov.SKIP and not completeness.expected_skip
    assert completeness.reason == ov.NO_METADATA
    assert report.overall == ov.SKIP


def _genome_fasta_report(tmp_path, metadata, settings=SETTINGS, text=None):
    path = tmp_path / "softmasked.fa.bgz"
    text = text if text is not None else genome_fasta()
    write_bgzf(path, text)
    write_fai(path, text)
    report = ov.FastaValidation(metadata, settings).validate_genome_fasta(path, "softmasked")
    return report, {stage.stage: stage for stage in report.stages}["completeness"]


def test_total_genome_length_disagrees_with_assembly_sequence(tmp_path):
    # Every seq_region matches; only the assembly.stats.total_genome_length statistic differs (seen in prod).
    metadata = ov.GenomeMetadata(sequences=METADATA.sequences, total_genome_length=216)
    report, completeness = _genome_fasta_report(tmp_path, metadata)
    assert completeness.status == ov.PASS and report.overall == ov.PASS
    warning = next(w for w in report.warnings if "total_genome_length" in w)
    assert "FASTA is 16 bp shorter" in warning
    assert "all 3 assembly_sequence seq_regions are present and sum to 200" in warning

    strict = ov.output_settings({"ftp_file_validation": {"strict_metadata_counts": True}})
    _, completeness = _genome_fasta_report(tmp_path, metadata, strict)
    assert completeness.status == ov.PASS


def test_total_length_mismatch_names_missing_seq_region(tmp_path):
    report, completeness = _genome_fasta_report(tmp_path, METADATA, text=genome_fasta().split(">MT")[0])
    assert completeness.status == ov.FAIL
    assert completeness.details[0] == "Missing seq_regions (1): MT"
    assert any("FASTA is 10 bp shorter" in w for w in report.warnings)


def test_terminal_report_lists_stages_details_and_json_location(tmp_path):
    report = ov.FileReport("pep.fa.bgz", Path("/dumps/pep.fa.bgz"))
    report.add(ov.StageResult("compression", ov.PASS, "bgzf"))
    report.add(ov.StageResult("format", ov.FAIL, "Invalid FASTA (2)", ["Line 2: bad", "Line 9: bad"]))
    report.warnings.append("long lines")
    writer = ov.OutputReportWriter(None, {"test": "ftp_file_validation", "run_id": "r"})
    writer.add(report, ov.OutputFile("peptide", "fasta", "pep.fa.bgz", path="/dumps/pep.fa.bgz"), {"genome_uuid": None})

    lines = [text for text, _ in ov.format_terminal_report(writer.document())]
    assert lines[:3] == ["File:    /dumps/pep.fa.bgz", "Type:    peptide",
                         "Genome:  not given (completeness needs --database and --genome_uuid)"]
    assert "  format       FAIL  Invalid FASTA (2)" in lines
    assert sum("- Line" in line for line in lines) == 2
    assert "  - long lines" in lines and "Result:  FAIL" in lines
    assert lines[-1] == "JSON:    not written (add --output-dir DIR to save it)"
    markup = dict(ov.format_terminal_report(writer.document(), "/out/ftp_file_validation_report.json"))
    assert markup["  format       FAIL  Invalid FASTA (2)"] == {"red": True}
    assert "JSON:    /out/ftp_file_validation_report.json" in markup


def _write_genome(folder, mask, text=None):
    path = folder / f"{mask}.fa.bgz"
    text = genome_fasta(mask) if text is None else text
    write_bgzf(path, text)
    write_fai(path, text)
    return path


def _format_stage(report):
    return {stage.stage: stage for stage in report.stages}["format"]


@pytest.mark.parametrize("mask", ["unmasked", "softmasked", "hardmasked"])
def test_each_genome_mask_passes_alone(tmp_path, mask):
    path = _write_genome(tmp_path, mask)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, mask)
    assert report.overall == ov.PASS, report
    assert "letters only" in _format_stage(report).reason


def test_hardmasked_copied_to_softmasked_fails(tmp_path):
    # The reported case: a hardmasked file copied over softmasked.fa.bgz.
    path = _write_genome(tmp_path, "softmasked", genome_fasta("hardmasked"))
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    details = _format_stage(report).details
    assert report.overall == ov.FAIL
    assert details[0].startswith("Softmasked FASTA has no lowercase (soft-masked) bases")
    assert "Headers say hardmasked, expected softmasked for a softmasked file (3): 1, 2, MT" in details


def test_softmasked_copied_to_hardmasked_fails(tmp_path):
    path = _write_genome(tmp_path, "hardmasked", genome_fasta("softmasked"))
    details = _format_stage(ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "hardmasked")).details
    assert details[0] == ("Hardmasked FASTA has 56 lowercase (soft-masked) bases; "
                          "lowercase is only allowed in softmasked FASTA")
    assert any(d.startswith("Headers say softmasked, expected hardmasked") for d in details)


def test_genome_header_location_checks(tmp_path):
    text = (">1 softmasked:chromosome GRCh38:1:1:119:1\n" + "ACGTa" * 24 + "\n"
            ">2 softmasked:chromosome GRCh38:X:1:5:1 \nACGTa\n"
            ">3 softmasked GRCh38:3:1:5:1\nACGTa\n"
            ">4 softmasked:chromosome GRCh38:4:5:1:1\nACGTa\n")
    scan = ov.scan_fasta(_write_genome(tmp_path, "softmasked", text), ov.NUCLEOTIDE_ANY_CASE)
    errors, warnings = ov.genome_header_errors(scan, "softmasked")
    assert errors == [
        "Headers not in the format NAME MASK:COORD_SYSTEM ASSEMBLY:NAME:START:END:STRAND (1): 3",
        "Header location names a different sequence than the ID (1): 2",
        "Header location has an invalid START, END or STRAND (1): 4",
    ]
    assert warnings == ["1 headers end with whitespace",
                        "Header location length differs from the sequence length (1): 1 (header 119, sequence 120)"]
    legacy = ov.scan_fasta(_write_genome(tmp_path, "unmasked", ">1 dna:chromosome chromosome:GRCh38:1:1:4:1 REF\nACGT\n"),
                           ov.NUCLEOTIDE_UPPER)
    assert ov.genome_header_errors(legacy, "unmasked") == ([], [])


def test_masks_compared_with_sibling_files(tmp_path):
    for mask in ("unmasked", "softmasked", "hardmasked"):
        _write_genome(tmp_path, mask)
    validation = ov.FastaValidation(METADATA, SETTINGS)
    for mask, reference in (("unmasked", "softmasked"), ("softmasked", "unmasked"), ("hardmasked", "softmasked")):
        report = validation.validate_genome_fasta(tmp_path / f"{mask}.fa.bgz", mask)
        assert report.overall == ov.PASS, report
        assert _format_stage(report).reason == f"masking consistent with {reference}.fa.bgz"

    # Hardmasked with a base that softmasked does not mask, and without softmasked: compared with unmasked.
    bad = genome_fasta("hardmasked").replace("NNNN", "NNNA", 1)
    _write_genome(tmp_path, "hardmasked", bad)
    details = _format_stage(validation.validate_genome_fasta(tmp_path / "hardmasked.fa.bgz", "hardmasked")).details
    assert details == ["Masking differs from softmasked.fa.bgz (hardmasked must equal softmasked with lowercase bases "
                       "replaced by N) (1): 2 at 4 (A here, t there)"]
    (tmp_path / "softmasked.fa.bgz").unlink()
    details = _format_stage(validation.validate_genome_fasta(tmp_path / "hardmasked.fa.bgz", "hardmasked")).details
    assert details == ["Masking differs from unmasked.fa.bgz (hardmasked must equal unmasked except where it has N) "
                       "(1): 2 at 4 (A here, T there)"]


def test_mask_comparison_reports_length_and_record_differences(tmp_path):
    soft = _write_genome(tmp_path, "softmasked")
    unmasked = tmp_path / "other.fa"
    unmasked.write_text(genome_fasta("unmasked").replace("A" * 10, "A" * 9))
    assert ov.compare_masked_fasta(soft, "softmasked", unmasked, "unmasked") == [
        "Sequence length differs from other.fa (1): MT"]
    unmasked.write_text(genome_fasta("unmasked").split(">MT")[0])
    assert ov.compare_masked_fasta(soft, "softmasked", unmasked, "unmasked") == [
        "Record count differs from other.fa: this file has more records"]


def test_fasta_sequence_reader_chunks_across_lines(tmp_path):
    path = tmp_path / "x.fa"
    path.write_text(">a one\nACG\nTA\n>b\nGG\n>c\n")
    with open(path, "rb") as fh:
        reader = ov.FastaSequenceReader(fh)
        assert reader.next_record() == "a"
        assert [reader.read(2), reader.read(2), reader.read(2), reader.read(2)] == [b"AC", b"GT", b"A", b""]
        assert reader.next_record() == "b"  # unread bases are skipped
        assert reader.next_record() == "c" and reader.read(5) == b""
        assert reader.next_record() is None


def test_soft_and_unmasked_fall_back_to_hardmasked(tmp_path):
    validation = ov.FastaValidation(METADATA, SETTINGS)
    _write_genome(tmp_path, "hardmasked")
    for mask in ("softmasked", "unmasked"):
        path = _write_genome(tmp_path, mask)
        assert _format_stage(validation.validate_genome_fasta(path, mask)).reason == "masking consistent with hardmasked.fa.bgz"
        path.unlink()
    soft = _write_genome(tmp_path, "softmasked", genome_fasta().replace("ACGT", "ACGG", 1))
    details = _format_stage(validation.validate_genome_fasta(soft, "softmasked")).details
    assert details == ["Masking differs from hardmasked.fa.bgz (softmasked with lowercase bases replaced by N must "
                       "equal hardmasked) (1): 1 at 4 (G here, T there)"]


@pytest.mark.parametrize("key", ov.FILE_TYPES)
def test_explicit_type_accepts_arbitrary_filename(tmp_path, key):
    path = tmp_path / "custom.data"
    path.touch()
    files = ov.resolve_output_input(_Config(target_file=str(path), file_type=key), SETTINGS)
    assert files[0].key == key
    assert files[0].path == str(path)


def test_explicit_type_overrides_recognised_name(tmp_path):
    path = tmp_path / "cdna.fa.bgz"
    path.touch()
    assert ov.local_output_files(SETTINGS, path, "peptide")[0].key == "peptide"


@pytest.mark.parametrize("override", [True, False])
def test_ftp_type_lookup(tmp_path, monkeypatch, override):
    from ensembl.datacheck.checks.automation import utils
    genome = {"genome_uuid": "uuid", "genebuild_date": "2026-01", "annotation_source": "Ensembl",
              "assembly_accession": "GCA_000001405.29"}
    monkeypatch.setattr(ov_dispatch, "get_genomes_from_metadata_db", lambda **kwargs: iter([genome]))
    monkeypatch.setattr(utils, "get_ftp_paths", lambda **kwargs: [
        {"dataset_type": "assembly", "path": "species/genome"},
        {"dataset_type": "genebuild", "path": "species/geneset"}])
    directory = tmp_path / "species" / "geneset"
    directory.mkdir(parents=True)
    path = directory / "cdna.fa.bgz"
    path.touch()
    settings = dict(SETTINGS)
    if not override:
        settings["base_path"] = str(tmp_path)
    config = _Config(genome_uuid="uuid", database="metadata", file_type="cdna",
                     base_path=str(tmp_path) if override else None)
    assert ov.resolve_output_input(config, settings)[0].path == str(path)
    (directory / "other.cdna.fa.bgz").touch()
    with pytest.raises(pytest.UsageError, match="found 2"):
        ov.resolve_output_input(config, settings)


@pytest.mark.parametrize("options, message", [
    ({"file_type": "unknown"}, "Unknown --file-type"),
    ({"file_type": "gff3"}, "requires --genome_uuid and --database"),
    ({"target_file": "file", "base_path": "root"}, "without -f"),
])
def test_invalid_output_input(options, message):
    with pytest.raises(pytest.UsageError, match=message):
        ov.resolve_output_input(_Config(**options), SETTINGS)


@pytest.mark.parametrize("file_format,text", [("gff3", GFF3), ("gtf", GTF)])
@pytest.mark.parametrize("raw_state", ["missing", "matching", "reordered", "changed", "duplicate", "corrupt"])
def test_processed_geneset_requires_and_compares_raw_sibling(tmp_path, file_format, text, raw_state):
    path = tmp_path / f"custom.{file_format}.bgz"
    write_csi(path, text, write_bgzf(path, text))
    raw = path.with_suffix(".gz")
    if raw_state != "missing":
        content = text
        if raw_state == "reordered":
            content = "# different header\n" + "".join(reversed([
                line for line in text.splitlines(keepends=True) if not line.startswith("#")]))
        elif raw_state == "changed":
            content = text.replace("41\t50", "41\t51")
        elif raw_state == "duplicate":
            content += text.splitlines(keepends=True)[-1]
        with gzip.open(raw, "wt") as fh:
            fh.write(content)
        if raw_state == "corrupt":
            raw.write_bytes(raw.read_bytes()[:-5])
    validator = ov.GenesetValidation(METADATA, SETTINGS)
    gff3 = make_gff3(tmp_path)
    report = (validator.validate_gff3(path) if file_format == "gff3"
              else validator.validate_gtf(path, gff3))
    assert statuses(report)["compression"] == (ov.FAIL if raw_state == "missing" else ov.PASS)
    expected = (ov.SKIP if raw_state == "missing" else
                ov.PASS if raw_state in ("matching", "reordered") else ov.FAIL)
    assert statuses(report)["completeness"] == expected


def test_raw_sibling_mismatch_fails_without_metadata(tmp_path):
    path = make_gff3(tmp_path)
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(GFF3.replace("41\t50", "41\t51"))
    validator = ov.GenesetValidation(ov.GenomeMetadata(sequences=[], available=False), SETTINGS)
    assert statuses(validator.validate_gff3(path))["completeness"] == ov.FAIL


@pytest.mark.parametrize("compression_kind", ["plain", "gzip", "bgzf"])
def test_compression_failure_never_invokes_later_checks(tmp_path, compression_kind):
    path = tmp_path / "input.fa.bgz"
    if compression_kind == "plain":
        path.write_text(">seq\nACGT\n")
    elif compression_kind == "gzip":
        with gzip.open(path, "wt") as fh:
            fh.write(">seq\nACGT\n")
    else:
        write_bgzf(path, ">seq\nACGT\n", eof=False)

    def unexpected(*args):
        pytest.fail("A later check ran after compression failed")

    validator = ov.OutputValidationBase(METADATA, SETTINGS)
    report = validator.run(path, path.name, unexpected, unexpected, unexpected,
                           format_checker=unexpected)
    assert statuses(report) == {"compression": ov.FAIL, "index": ov.SKIP,
                                "format": ov.SKIP, "completeness": ov.SKIP}
    assert all("Compression validation failed" in stage.reason for stage in report.stages[1:])
    assert report.overall == ov.FAIL


@pytest.mark.parametrize("index_fails", [False, True])
def test_stages_execute_sequentially(tmp_path, monkeypatch, index_fails):
    validator = ov.OutputValidationBase(METADATA, SETTINGS)
    events = []

    def compression(*args):
        events.append("compression")
        return ov.StageResult("compression", ov.PASS), ov.CompressionInfo("bgzf")

    def index(*args):
        events.append("index")
        assert args[2] is None
        return ov.Outcome(errors=["Bad index"] if index_fails else [])

    def scanner(*args):
        events.append("format")
        return ov.FastaScan()

    def completeness(*args):
        events.append("completeness")
        return ov.Outcome()

    monkeypatch.setattr(validator, "check_compression", compression)
    monkeypatch.setattr(validator, "index_content_checker", lambda *args: ov.Outcome())
    path = tmp_path / "file.bgz"
    path.touch()
    report = validator.run(path, "file", scanner, index, completeness)
    assert events == (["compression", "index"] if index_fails else list(ov.STAGES))
    if index_fails:
        assert statuses(report) == {"compression": ov.PASS, "index": ov.FAIL,
                                    "format": ov.SKIP, "completeness": ov.SKIP}


@pytest.mark.parametrize("suffix", ov.INDEX_SUFFIXES)
@pytest.mark.parametrize("index_offset", [-1, 0, 1])
def test_index_timestamp_warning(tmp_path, suffix, index_offset):
    import os

    path = tmp_path / "data.bgz"
    index = Path(f"{path}{suffix}")
    path.touch()
    index.touch()
    timestamp = 1_700_000_000_000_000_000
    os.utime(path, ns=(timestamp, timestamp))
    index_timestamp = timestamp + index_offset * 1_000_000_000
    os.utime(index, ns=(index_timestamp, index_timestamp))
    validator = ov.OutputValidationBase(METADATA, SETTINGS)
    stage, warnings = validator.check_index(path, None, None, lambda *args: ov.Outcome())
    assert stage.status == ov.PASS
    assert len(warnings) == (1 if index_offset < 0 else 0)
    if warnings:
        assert path.name in warnings[0] and index.name in warnings[0]
        assert "newer than index" in warnings[0]


def test_old_index_warning_does_not_block_validation(tmp_path):
    import os

    path = tmp_path / "softmasked.fa.bgz"
    text = genome_fasta()
    write_bgzf(path, text)
    write_fai(path, text)
    os.utime(Path(f"{path}.fai"), (1_600_000_000, 1_600_000_000))
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    assert report.overall == ov.PASS
    assert any("index: Data file" in warning and "newer than index" in warning
               for warning in report.warnings)


@pytest.mark.parametrize("short,key", [
    ("hardmask", "genome_hardmasked"), ("unmask", "genome_unmasked"),
    ("softmask", "genome_softmasked"), ("chrom", "chromosome_tsv"),
    ("cdna", "cdna"), ("pep", "peptide"),
])
def test_short_file_types(tmp_path, short, key):
    path = tmp_path / "custom.data"
    path.touch()
    assert ov.normalise_file_type(short) == key
    assert ov.resolve_output_input(_Config(target_file=str(path), file_type=short), SETTINGS)[0].key == key


def test_file_type_error_shows_short_names():
    with pytest.raises(pytest.UsageError) as error:
        ov.normalise_file_type("invalid")
    assert ", ".join(ov.CLI_FILE_TYPES) in str(error.value)
    assert "genome_" not in str(error.value)


def test_softmasked_accepts_uppercase_n(tmp_path):
    text = genome_fasta().replace("acgtn", "acgtN", 1)
    path = _write_genome(tmp_path, "softmasked", text)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    assert statuses(report)["format"] == ov.PASS
    assert report.overall == ov.PASS


def test_softmasked_accepts_lowercase_n(tmp_path):
    path = _write_genome(tmp_path, "softmasked", genome_fasta().replace("acgtN", "acgtn"))
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, "softmasked")
    assert statuses(report)["format"] == ov.PASS


@pytest.mark.parametrize("mask", ["unmasked", "hardmasked"])
def test_uppercase_n_still_allowed_in_other_genome_masks(tmp_path, mask):
    path = _write_genome(tmp_path, mask)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, mask)
    assert statuses(report)["format"] == ov.PASS


@pytest.mark.parametrize("mask", ov.GENOME_MASKS)
@pytest.mark.parametrize("missing", [False, True])
def test_genome_completeness_missing_regions_fail_lengths_warn(tmp_path, mask, missing):
    sequences = [(name, accession, length + 1, chromosomal)
                 for name, accession, length, chromosomal in METADATA.sequences]
    metadata = ov.GenomeMetadata(sequences=sequences, total_genome_length=203)
    settings = ov.output_settings({"ftp_file_validation": {"strict_metadata_counts": True}})
    text = genome_fasta(mask)
    if missing:
        text = text.split(">MT")[0]
    path = _write_genome(tmp_path, mask, text)
    report = ov.FastaValidation(metadata, settings).validate_genome_fasta(path, mask)
    assert statuses(report)["completeness"] == (ov.FAIL if missing else ov.PASS)
    assert any("Length mismatch with metadata" in warning for warning in report.warnings)
    assert any("total_genome_length" in warning for warning in report.warnings)
    if missing:
        assert report.stages[-1].details == ["Missing seq_regions (1): MT"]


@pytest.mark.parametrize("mask", ov.GENOME_MASKS)
@pytest.mark.parametrize("missing", [False, True])
def test_header_length_difference_warns_and_reaches_completeness(tmp_path, mask, missing):
    text = genome_fasta(mask).replace("GRCh38:1:1:120:1", "GRCh38:1:1:128:1")
    if missing:
        text = text.split(">MT")[0]
    path = _write_genome(tmp_path, mask, text)
    report = ov.FastaValidation(METADATA, SETTINGS).validate_genome_fasta(path, mask)
    assert statuses(report)["format"] == ov.PASS
    assert any("Header location length differs" in warning and "header 128, sequence 120" in warning
               for warning in report.warnings)
    assert statuses(report)["completeness"] == (ov.FAIL if missing else ov.PASS)
    assert report.overall == (ov.FAIL if missing else ov.PASS)
    if missing:
        assert "Missing seq_regions (1): MT" in report.stages[-1].details


def test_gtf_raw_tail_attributes_fail_before_gff3_lookup(tmp_path, monkeypatch):
    path = tmp_path / "genes.gtf.bgz"
    text = GTF.rsplit(' gene_version "1";', 1)[0] + "\n"
    write_csi(path, text, write_bgzf(path, text))
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(text)
    validator = ov.GenesetValidation(METADATA, SETTINGS)

    def unexpected(*args):
        pytest.fail("GFF3 lookup must not run after a truncated raw GTF tail")

    monkeypatch.setattr(validator, "_gff3_or_skip", unexpected)
    report = validator.validate_gtf(path, None)
    assert statuses(report)["format"] == ov.PASS
    assert statuses(report)["completeness"] == ov.FAIL
    assert "last line missing required attributes" in report.stages[-1].reason
    assert "gene_version" in report.stages[-1].reason
    assert any("GFF3 cross-reference missing" in detail for detail in report.stages[-1].details)


@pytest.mark.parametrize("name", ["genes.gff3", "genes.gff3.gz", "genes.gff3.bgz"])
def test_gtf_discovers_gff3_sibling_variants(tmp_path, name):
    path = tmp_path / "genes.gtf.bgz"
    write_csi(path, GTF, write_bgzf(path, GTF))
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(GTF)
    reference = tmp_path / name
    if name.endswith((".gz", ".bgz")):
        with gzip.open(reference, "wt") as fh:
            fh.write(GFF3)
    else:
        reference.write_text(GFF3)
    output = ov.local_output_files(SETTINGS, path)[0]
    assert output.gff3_path == str(reference)
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_gtf(path, output.gff3_path)
    assert report.overall == ov.PASS


def test_gtf_prefers_same_stem_gff3(tmp_path):
    path = tmp_path / "genes.gtf.bgz"
    path.touch()
    (tmp_path / "aaa.gff3.bgz").touch()
    reference = tmp_path / "genes.gff3.gz"
    reference.touch()
    (tmp_path / "genes.gff3.gz.csi").touch()
    assert ov.local_output_files(SETTINGS, path)[0].gff3_path == str(reference)


def test_gtf_missing_gff3_fails_completeness(tmp_path):
    path = tmp_path / "genes.gtf.bgz"
    write_csi(path, GTF, write_bgzf(path, GTF))
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(GTF)
    output = ov.local_output_files(SETTINGS, path)[0]
    assert output.gff3_path is None
    report = ov.GenesetValidation(METADATA, SETTINGS).validate_gtf(path, output.gff3_path)
    assert statuses(report)["completeness"] == ov.FAIL
    assert "GFF3 cross-reference missing" in report.stages[-1].reason


def test_report_identifies_selected_gff3(tmp_path):
    path = tmp_path / "genes.gtf.bgz"
    path.touch()
    reference = tmp_path / "genes.gff3.gz"
    reference.touch()
    output = ov.local_output_files(SETTINGS, path)[0]
    record = ov.file_report_record(ov.FileReport(path.name, path), output, {})
    assert record["gff3_reference"] == str(reference.resolve())
    lines = [line for line, _ in ov.format_terminal_report({"files": [record]})]
    assert f"GFF3:    {reference.resolve()}" in lines


def test_gtf_does_not_fall_back_to_different_stem_gff3(tmp_path):
    path = tmp_path / "genes.gtf.bgz"
    path.touch()
    for name in ("test_genes.gff3", "other.gff3.bgz", "different.gff3.gz"):
        (tmp_path / name).touch()
    assert ov.local_output_files(SETTINGS, path)[0].gff3_path is None


@pytest.mark.parametrize("with_pragmas", [True, False])
@pytest.mark.parametrize("missing", [True, False])
def test_gff3_missing_seq_regions_fail_counts_warn(tmp_path, with_pragmas, missing):
    lines = GFF3.splitlines(keepends=True)
    if not with_pragmas:
        lines = [line for line in lines if not line.startswith("##sequence-region")]
        lines.append("MT\tens\tgene\t1\t10\t.\t+\t.\tID=gene:MT1\n")
    if missing:
        lines = [line for line in lines if not line.startswith(("2\t", "##sequence-region 2 "))]
    path = make_gff3(tmp_path, "".join(lines))
    metadata = ov.GenomeMetadata(sequences=METADATA.sequences, total_coding_exons=100)
    settings = ov.output_settings({"ftp_file_validation": {"strict_metadata_counts": True}})
    report = ov.GenesetValidation(metadata, settings).validate_gff3(path)
    assert statuses(report)["completeness"] == (ov.FAIL if missing else ov.PASS)
    assert any("CDS features" in warning and "mismatch" in warning for warning in report.warnings)
    if missing:
        assert "Missing seq_regions (1): 2" in report.stages[-1].details


def test_gff3_missing_nonchromosomal_seq_region_fails(tmp_path):
    text = GFF3.replace("##sequence-region MT 1 10\n", "")
    path = make_gff3(tmp_path, text)
    metadata = ov.GenomeMetadata(sequences=METADATA.sequences, total_coding_exons=100)
    report = ov.GenesetValidation(metadata, SETTINGS).validate_gff3(path)
    assert statuses(report)["completeness"] == ov.FAIL
    assert "Missing seq_regions (1): MT" in report.stages[-1].details
    assert any("CDS features" in warning and "mismatch" in warning for warning in report.warnings)


@pytest.mark.parametrize("stage", ["bgzip", "index", "format", "completeness"])
def test_select_one_validation_stage(tmp_path, stage):
    path = _write_genome(tmp_path, "softmasked")
    settings = {**SETTINGS, "validation_stage": stage}
    if stage in ("format", "completeness"):
        Path(f"{path}.fai").unlink()  # Neither stage requires an index-only check.
    report = ov.FastaValidation(METADATA, settings).validate_genome_fasta(path, "softmasked")
    selected = "compression" if stage == "bgzip" else stage
    assert statuses(report)[selected] == ov.PASS
    assert all(result.expected_skip and result.reason == "Not selected"
               for result in report.stages if result.stage != selected)
    assert report.overall == ov.PASS


def test_completeness_only_still_checks_raw_gtf_tail(tmp_path):
    path = tmp_path / "genes.gtf.bgz"
    text = GTF.rsplit(' gene_version "1";', 1)[0] + "\n"
    write_bgzf(path, text)
    with gzip.open(path.with_suffix(".gz"), "wt") as fh:
        fh.write(text)
    validator = ov.GenesetValidation(METADATA, {**SETTINGS, "validation_stage": "completeness"})
    report = validator.validate_gtf(path, None)
    assert statuses(report)["completeness"] == ov.FAIL
    assert "last line missing required attributes" in report.stages[-1].reason
