# FTP file validation (internal use)

Validate one file per run with `--test=ftp_file_validation`.

## Setup

```bash
python -m pip install -e .

# Optional GFF3/GTF format tools; missing tools cause those checks to SKIP:
conda install -c bioconda genometools-genometools ucsc-gtftogenepred ucsc-genepredcheck

DB='mysql+pymysql://USER:PASSWORD@HOST/ensembl_genome_metadata'
GENOME_UUID='your-genome-uuid'
```

## Run

```bash
# File path: detect the type from its name
ensembl-datacheck --test=ftp_file_validation \
  -f /data/softmasked.fa.bgz \
  --genome_uuid "$GENOME_UUID" --database "$DB" --no-cache-results

# File path and explicit type
ensembl-datacheck --test=ftp_file_validation \
  -f /data/custom.bgz --file-type softmask \
  --genome_uuid "$GENOME_UUID" --database "$DB" --no-cache-results

# Genome UUID and type: find the file under the FTP root
ensembl-datacheck --test=ftp_file_validation \
  --file-type gff3 --genome_uuid "$GENOME_UUID" \
  --database "$DB" --no-cache-results
```

FTP lookup defaults to `/nfs/ftp/public/ensemblorganisms`.
Use `--base-path /custom/ftp/root` to change it; do not combine this with `-f`.
For local runs, database and UUID can be omitted, but metadata comparisons SKIP.

**File types:** `unmask`, `softmask`, `hardmask`, `cdna`, `pep`, `chrom`,
`gff3`, `gtf`, `raw_gff3`, `raw_gtf`.

## Run one stage

Add one of these options to a command above:

```bash
--validation-stage bgzip
--validation-stage index
--validation-stage format
--validation-stage completeness
```

The default runs **compression → index → format → completeness**.
Failures stop later stages; warnings do not. A selected stage still reads any
supporting records or references it needs.

## Required related files

- BGZF FASTA: `<file>.fai`; `.gzi` is optional by default.
- `genes.gff3.bgz`: `.csi` index and raw `genes.gff3.gz`.
- `genes.gtf.bgz`: `.csi` index, raw `genes.gtf.gz`, and matching
  `genes.gff3`, `genes.gff3.bgz`, or `genes.gff3.gz` in the same directory.
- cDNA/peptide completeness: a GFF3 reference in the same directory.
- Raw gzip and chromosome TSV: no index required.

## Results

Results, warnings, and the selected GFF3 reference appear in the terminal.
Add `--output-dir results/my-file` to save `ftp_file_validation_report.json`
and `report.json`. Use a separate directory per run to keep previous reports.

Exit codes: `0` = no failures (skips allowed), `1` = validation failed,
`2` = usage/collection error. Add `--tb=short` for tracebacks or `-rs` for skip reasons.

Settings: [resource_config.json](../automation/resource_config.json).
Override with `--params ftp_file_validation.KEY=VALUE`.

## Unit tests

```bash
python -m pytest -c tests/pytest.ini tests/test_ftp_file_validation.py -q
```
