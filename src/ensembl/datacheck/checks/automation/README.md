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

Optional resource config overrides:

```bash
export ENSEMBL_DATACHECK_BLAST_DATABASE_FILES_BASE_PATH="/path/to/blast_db"
```

The bundled configuration expands `${VARIABLE}` values using the process
environment. Its portable resource locations are:

- `BASE_DUMPS` for generated dumps (`blast`, `blastdbs`, `refget`, `tracks`, and
  FTP dumps)
- `BASE_BLAST_DB` for the live BLAST database release and synchronisation checks

When the generic variables are unset, they default to the Production TEAM
module variables `HPS_DUMPS` and `BLAST_DB_LIVE`, respectively. Export the
generic variables to select another backend at runtime:

```bash
# Optional on Production TEAM hosts: these are the built-in fallbacks.
export HPS_DUMPS="/path/to/production/dumps"
export BLAST_DB_LIVE="/path/to/production/blast-db"

# Local or CI override: these take precedence over the fallbacks.
export BASE_DUMPS="/path/to/local/dumps"
export BASE_BLAST_DB="/path/to/local/blast-db"
```

Any other `${VARIABLE}` in a resource configuration is expanded directly from
the process environment. An unset variable is deliberately left visible in the
resolved configuration so it can be overridden with `ENSEMBL_DATACHECK_*` or
`--params`.

Runtime `--params` overrides use dotted config paths:

```bash
--params blast_database_files.base_path=/path/to/blast_db
```

Use alternate paths from `alt_base_path` values:

```bash
--use_alt
```

For `blast_database_files`, `--use_alt` expects genome directories directly
under `blast_database_files.alt_base_path`.

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
ensembl-datacheck --test=automation/automation_blast_database_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_blast_database_release ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_blast_database_release_sync ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_compara_mongo_load ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_ftp_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_genesearch_solr ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_track_api_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_refget_expected_files ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_thoas_mongo_load ${COMMON_ARGS}
ensembl-datacheck --test=automation/automation_thoas_genome_mapping ${COMMON_ARGS}
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
  from the `blast_database_release` config. It does not use `--release_name`;
  `base_path` is the BLAST database release directory to check.
- `automation_blast_database_release_sync` reads `base_path`,
  `manifest_path`, and `expected_files` from `blast_database_release_sync`.
  It uses `--database` and `--release_name` to obtain the release's
  genebuild genomes from metadata, checks every genome directory and required
  file at the release target, and verifies MD5 checksums for the files in the
  just-generated source manifest. It does not reject pre-existing entries;
  stale-data cleanup remains a separate step.
- Automation resource config precedence is:
  `--params` > `--use_alt` > `ENSEMBL_DATACHECK_*` environment variables >
  `--automation_resource_config` JSON > bundled repo JSON.
- `automation_blast_database_release` failures start with a one-line count and
  release path. Native output includes the full discrepancy list inline. JSON
  reports store the same full list under the failure's `details.items` field.
- Mongo-related checks use URIs from `resource_config.json` (`compara_mongo_uri`, `thoas_mongo_*`).
- `automation_thoas_genome_mapping` checks that each genome has a document with
  its `genome_uuid` and `release_name` in the Thoas `metadata.genome_mapping`
  collection, with a `release_version` matching the metadata database.

## Refget index checksum coverage

`automation/automation_refget_expected_index_db` checks metadata
`assembly_sequence.md5` and MongoDB region/protein/transcript MD5 keys separately.
It requires `--genome_uuid UUID1,UUID2`; it never selects genomes by release.
All requested UUIDs share one checksum query and one index lookup pass.

The `refget_index` resource describes the shared index; `refget` continues to
configure the per-genome files check. Its bundled `index_file` is the generic
placeholder `${REFGET_INDEX_FILE}`; map that variable to the index in each
environment without changing the JSON. For example, map a generic dumps root
at runtime and derive the index path for that environment:

```bash
export BASE_DUMPS="${HPS_DUMPS}"  # or "${NFS_DUMPS}", according to the environment
export REFGET_INDEX_FILE="${BASE_DUMPS}/refget/indexdb.tkh"
```

For a local file, set `REFGET_INDEX_FILE=/path/to/indexdb.tkh` directly.
The shared automation loader expands `${NAME}` in JSON configuration before
applying resource-specific environment and CLI overrides. Precedence remains
config-file < `ENSEMBL_DATACHECK_*` environment < dotted `--params`. A literal
`refget_index.index_file` override takes precedence over `REFGET_INDEX_FILE`.
An unset index placeholder fails with a configuration message when this check
runs; it does not require configuring the index for unrelated automation checks.

Mongo authentication comes from the existing resource named by
`refget_index.mongo_resource` (default: `thoas_mongo_internal_resource_uri`).
The check uses the existing session-scoped `mongo_client` fixture, indirectly
parametrized with `refget_index`. The fixture resolves its `mongo_resource` from
`automation_resource_config`, including the standard cleanup and skip behavior.
Configuration is resolved once during fixture setup; no collection-time config
loading is needed for the Mongo selection.
No refget-specific Mongo client is created. No credentials are stored in the
bundled config.

For example, using the existing config-file, environment and CLI precedence:

```bash
export REFGET_INDEX_FILE=/path/to/indexdb.tkh
export ENSEMBL_DATACHECK_THOAS_MONGO_INTERNAL_RESOURCE_URI_URI="$THOAS_MONGO_URI"
ensembl-datacheck --test automation/automation_refget_expected_index_db \
  --database "$METADATA_DB_URL" --genome_uuid UUID1,UUID2 \
  --params refget_index.mongo_database=release_116_5,refget_index.index_backend=python,refget_index.report=checksums.json \
  --no-cache-results
```

If `mongo_database` is unset, the standard automation metadata helper obtains
records only for the supplied UUIDs with `release_name=None`; their
`release_version` identifies `release_<version>` exactly as in the Thoas load
check. Set `mongo_database` explicitly if a UUID has multiple release versions.
The shared assembly checksum query then validates all supplied UUIDs. With an
explicit Mongo database, the additional genome-version lookup is unnecessary.
`refget_index.ignore` and the selected Mongo resource's `ignore` flag follow
standard automation skip behavior. Missing MD5s produce separate assembly and
Mongo failures; query/configuration errors are reported during fixture setup.
