# Regulation Checks: How To Run

This directory contains regulation datachecks under:

- `src/ensembl/datacheck/checks/regulation`

## 1) Prerequisites

From the repository root:

```bash
python -m pip install -e .
```

The regulation checks require either:

- a target regulatory BigBed file;
- a target regulatory GFF file with a `.gff.gz` suffix, BGZF compression, and
  a readable `.csi` or `.tbi` index; or
- both files when comparing a BigBed with its source GFF.

## 2) Run all regulation checks for a BigBed/GFF pair

Use `--test=regulation` to validate a regulatory BigBed and the GFF from which
it was created in one command. In this mode, `--file`/`--target-file` is the
BigBed and `--source-file` is passed to the regulation GFF checks as their
target GFF.

```bash
ensembl-datacheck \
  --test=regulation \
  --file /path/to/regulatory_features.bb \
  --source-file /path/to/regulatory_features.gff.gz
```

## 3) Run only the regulation BigBed checks

```bash
ensembl-datacheck \
  --test=regulation/bigbed \
  --target-file /path/to/regulatory_features.bb \
  --source-file /path/to/regulatory_features.gff.gz
```

`--file` is an alias for `--target-file`.

`--source-file` is required for this module. It is the GFF used to create the
BigBed and is used to compare the number of records for every feature type.

## 4) Run only the regulation GFF checks

```bash
ensembl-datacheck \
  --test=regulation/gff \
  --target-file /path/to/regulatory_features.gff.gz
```

Place the matching `.csi` or `.tbi` index beside the GFF (for example,
`regulatory_features.gff.gz.csi`). This module validates one regulatory GFF;
it does not compare a target and source file.

## 5) Write a JSON report

```bash
ensembl-datacheck \
  --test=regulation/bigbed \
  --target-file /path/to/regulatory_features.bb \
  --source-file /path/to/regulatory_features.gff.gz \
  --json-report \
  --json-report-file regulation_bigbed.json
```

JSON reports are written with two-space indentation by default. Override with
`--json-report-indent <n>` if needed.

## Checks

`regulation/bigbed` runs these checks:

- `check_exist`: the target BigBed file exists.
- `check_validity`: the target file can be read as a BigBed file.
- `check_feature_types_match`: the feature-type names and counts in the target
  BigBed match those in the source GFF.

`regulation/gff` runs the generic GFF checks and regulation-specific checks.
It verifies that the target GFF:

- exists and has a `.gff.gz` extension;
- is BGZF-compressed, has a readable `.csi` or `.tbi` index, and contains
  GFF content that `gffutils` can parse;
- includes Ensembl Regulation version and gene-annotation headers; and
- contains one or more of these supported feature types, with each observed
  type having at least one record:
  `CTCF_binding_site`, `EMAR`, `enhancer`, `open_chromatin_region`, and
  `promoter`.

The BigBed feature-type comparison reports the complete per-type count mappings
for both files when they differ. BigBed feature types with spaces are
normalised to underscores before comparison.

## Notes

- `regulation/bigbed` and `regulation/gff` remain available when only one
  format needs checking. Unlike the combined `regulation` run, a direct
  `regulation/gff` run takes its GFF from `--target-file`/`--file`.
- Feature-type counting loads a GFF with `gffutils` into a temporary SQLite
  database; it does not leave a database beside the input data.
- If `pyBigWig` cannot validate the target, the generic BigBed validity check
  tries the UCSC `bigBedInfo` command when it is available on `PATH`.
- Add `--no-cache-results` to force a fresh run instead of using cached results.
