# Automation Checks: How To Run

This directory contains automation datachecks under:

- `src/ensembl/datacheck/checks/automation`

## 1) Prerequisites

From the repository root:

```bash
python -m pip install -e ".[automation]"
```

Set required inputs:

```bash
export METADATA_DB_URL="mysql+pymysql://<user>:<pass>@<host>/<db>"
export TAXONOMY_DB_URL="mysql+pymysql://<user>:<pass>@<host>/<db>"
```

Optional config override:

```bash
export AUTOMATION_CONFIG="src/ensembl/datacheck/checks/automation/resource_config.json"
```

Optional filters (recommended to narrow scope):

```bash
export RELEASE_NAME="<release_name>"
export GENOME_UUID="<genome_uuid>"
```

Build shared CLI args:

```bash
COMMON_ARGS="--database ${METADATA_DB_URL} --taxonomy_database ${TAXONOMY_DB_URL}"
[ -n "${AUTOMATION_CONFIG}" ] && \
  COMMON_ARGS="${COMMON_ARGS} --automation_resource_config ${AUTOMATION_CONFIG}"
[ -n "${RELEASE_NAME}" ] && COMMON_ARGS="${COMMON_ARGS} --release_name ${RELEASE_NAME}"
[ -n "${GENOME_UUID}" ] && COMMON_ARGS="${COMMON_ARGS} --genome_uuid ${GENOME_UUID}"
```

## 2) Run each automation test module

```bash
ensembl-datacheck --test=automation/automation_blast_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_blast_database_files_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_blast_database_release ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_compara_mongo_load ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_ftp_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_genesearch_expected_file ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_genome_browser_files_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_refget_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_thoas_mongo_load ${COMMON_ARGS}
```

## 3) Run all automation tests

```bash
ensembl-datacheck --test=automation ${COMMON_ARGS}
```

## 4) Write a JSON report

```bash
ensembl-datacheck \
  --test=automation/automation_blast_database_release \
  ${COMMON_ARGS} \
  --json-report \
  --json-report-file db_files.json
```

JSON reports are written with two-space indentation by default. Override with
`--json-report-indent <n>` if needed.

## Notes

- `--test=automation` runs every `*.py` module in this directory (excluding `conftest.py`).
- `automation_blast_database_release` reads `base_path` and `expected_files`
  from the `blast_database_release` config.
  Override it with `--params base_dir=/path/to/blastdb`.
- `automation_blast_database_release` failures start with a one-line count and
  release path, followed by the full discrepancy list in native output and in
  the JSON report error field.
- Mongo-related checks use URIs from `resource_config.json` (`compara_mongo_uri`, `thoas_mongo_*`).
