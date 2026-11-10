# Run FTPdump output validation (Internal usage only)

Validate one file per run with `ensembl-datacheck --test=output_validation`.
The default order is **compression → index → format → completeness**.
A failed stage skips later stages; warnings do not stop validation.

## Setup

From the repository root:

```bash
python -m pip install -e .

# Optional external GFF3/GTF format validators:
conda install -c bioconda genometools-genometools ucsc-gtftogenepred ucsc-genepredcheck
```

Missing external validators cause their format checks to SKIP.
For metadata comparisons, set a read-only SQLAlchemy database URL and one genome UUID:

```bash
DB='mysql+pymysql://USER:PASSWORD@HOST/ensembl_genome_metadata'
GENOME_UUID='your-genome-uuid'
```

On EBI hosts, the database URL can also be set with
`DB="$(prod1 details url)ensembl_genome_metadata"`.
The runner accepts `mysql://` and converts it to `mysql+pymysql://`.

## Choose an input

### File path: recognize the type from its name

```bash
ensembl-datacheck --test=output_validation \
  -f /data/genome/softmasked.fa.bgz \
  --genome_uuid "$GENOME_UUID" --database "$DB" --no-cache-results
```

For local checks without metadata, omit `--genome_uuid` and `--database`.
Comparisons that require metadata will SKIP; comparisons against related files
can still run.

### File path and explicit type

Use this for custom filenames or to override filename recognition:

```bash
ensembl-datacheck --test=output_validation \
  -f /data/custom.bgz --file-type softmask \
  --genome_uuid "$GENOME_UUID" --database "$DB" --no-cache-results
```

### Genome UUID and type: resolve the FTP file

```bash
ensembl-datacheck --test=output_validation \
  --genome_uuid "$GENOME_UUID" --file-type gff3 \
  --database "$DB" --no-cache-results
```

The default FTP root is `/nfs/ftp/public/ensemblorganisms`. Override it with
`--base-path /custom/ftp/root`, preserving the accession/source/date directory
layout. FTP lookup requires metadata and exactly one matching file.
Do not combine `--base-path` with `-f`.

### File types

| `--file-type` | Output |
|---|---|
| `unmask`, `softmask`, `hardmask` | Genome FASTA |
| `cdna` | cDNA FASTA |
| `pep` | Peptide FASTA |
| `chrom` | Chromosome TSV |
| `gff3`, `gtf` | Processed BGZF geneset |
| `raw_gff3`, `raw_gtf` | Raw gzip dumper output |

## Run one stage

Add `--validation-stage bgzip`, `index`, `format`, or `completeness`:

```bash
ensembl-datacheck --test=output_validation \
  -f /data/geneset/genes.gtf.bgz --file-type gtf \
  --validation-stage completeness \
  --genome_uuid "$GENOME_UUID" --database "$DB" --no-cache-results
```

The default is `all`. `compression` and `bgzf` are aliases for `bgzip`.
Unselected stages show SKIP without affecting the result.
Format-only runs do not require an index. Completeness-only runs still parse
records and check required raw files and references, but skip index validation
and external format tools.

## Files needed alongside the input

| Input | Related files |
|---|---|
| BGZF FASTA | `<file>.fai`; `<file>.gzi` is optional unless `require_gzi=true` |
| `genes.gff3.bgz` | `genes.gff3.bgz.csi` and raw `genes.gff3.gz` |
| `genes.gtf.bgz` | `genes.gtf.bgz.csi`, raw `genes.gtf.gz`, and matching `genes.gff3.*` |
| cDNA or peptide FASTA | GFF3 in the same directory for completeness comparisons |
| Raw `.gff3.gz` / `.gtf.gz`, chromosome TSV | No index required |

GTF requires the same GFF3 stem: `genes.gtf.bgz` accepts `genes.gff3`,
`genes.gff3.bgz`, or `genes.gff3.gz`, but not `test_genes.gff3`.
The selected reference path is shown in the logs and reports.
GTF completeness checks the raw last line for nonempty `gene_id`, `gene_version`,
`gene_biotype`, and `gene_source` attributes before comparing with GFF3.

Missing metadata seq_regions fail genome FASTA and GFF3 completeness.
Genome length differences and GFF3 CDS count differences produce warnings.
An index older than its data file also produces a warning.

## Results and reports

Results and warnings appear in the terminal. To save JSON, add
`--output-dir results/my-file` to any command:

- `output_validation_report.json`: per-file and per-stage results, warnings, and GFF3 reference.
- `report.json`: the standard pytest JSON report.

A later run replaces reports in the same output directory. Use a separate
directory for each file when running several commands.

Exit codes: `0` means no failures (SKIP is allowed), `1` means validation failed,
and `2` means a usage or collection error. A SKIP is not evidence of a pass.
Add `--tb=short` for pytest tracebacks or `-rs` for skip reasons.

## Useful options

| Option | Purpose |
|---|---|
| `--test=output_validation/fasta` | Collect only FASTA checks |
| `--test=output_validation/geneset` | Collect only geneset checks |
| `--no-cache-results` | Avoid writing the result cache; recommended in examples |
| `--automation_resource_config /path/config.json` | Load a resource configuration override |
| `--params output_validation.require_gzi=true` | Require the FASTA GZI index |
| `--params output_validation.check_genome_headers=false` | Accept alternative genome header conventions |
| `--params output_validation.compare_genome_masks=false` | Disable comparisons with sibling genome masks |

Default settings are in [resource_config.json](../automation/resource_config.json).
The command entry points are [fasta.py](fasta.py) and [geneset.py](geneset.py);
validation logic lives in [functions/output_validation](../../functions/output_validation/).

For an unrecognized filename, supply `--file-type`. For missing metadata, supply
both database and UUID. Folder and release-wide flags are unsupported; run one
command per file.

## Unit tests

From the repository root; no database or FTP access is needed:

```bash
python -m pytest -c tests/pytest.ini tests/test_output_validation.py -q
```
