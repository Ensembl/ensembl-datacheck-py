# Compara Reference Checks

These checks compare the homology reference collection CSV files (from the
`collections/` folder of
[homology-reference-collections](https://gitlab.ebi.ac.uk/ensembl-data-teams/homology-reference-collections))
with the `compara_reference` genome groups in the metadata database. The CSV files are
read from a path you give; nothing is downloaded.

Each CSV file under `collections/` is one genome group:

| File | `genome_group.name` | `genome_group.label` |
|---|---|---|
| `2_bacteria.csv` | `2` | `Bacteria` |
| `40674_mammalia.csv` | `40674` | `Mammalia` |
| `protists.csv` (no taxonomy ID) | `protists` | `Protists` |

Each row is `<production_name>,<genome_uuid>` with no header. Labels are compared
case-insensitively.

A genome is a **current member** of a group when its `genome_group_member` row has
`is_current = 1` and its `release_id` belongs to a `partial` release. This is the
same query as:

```sql
SELECT genome_group.name, genome_group.label, genome.genome_uuid
FROM genome_group_member
JOIN genome_group USING (genome_group_id)
JOIN genome USING (genome_id)
JOIN ensembl_release USING (release_id)
WHERE ensembl_release.release_type = 'partial'
  AND genome_group_member.is_current = 1
  AND genome_group.type = 'compara_reference';
```

## Checks

All checks are in `homology_reference_collections.py`. The collections and database
rows are loaded once per run.

| Check | Fails when |
|---|---|
| `check_compara_reference_collection_files_are_valid` | A row is not `<production_name>,<genome_uuid>`, or a genome UUID appears twice in one file |
| `check_compara_reference_collections_have_genome_group` | A collection has no `compara_reference` group with its name, or the group's label differs |
| `check_compara_reference_genomes_exist` | A collection's genome UUID is not in the `genome` table |
| `check_compara_reference_genomes_not_suppressed` | A collection's genome is suppressed (`genome.suppressed = 1`); the failure shows `suppression_details` |
| `check_compara_reference_genomes_released` | A collection's genome is not in any `Released` or `Archived` release (only released genomes may be references) |
| `check_compara_reference_production_names` | **Warning only:** a collection's production name differs from `genome.production_name` for the same UUID. The SQL patches use UUIDs, so this does not fail the run |
| `check_compara_reference_missing_group_members` | A collection's genome UUID is not a current member of its group (for example, the patch adding it was not applied) |
| `check_compara_reference_extra_group_members` | A group has a current member that is not in its collection (for example, the patch dropping it was not applied) |
| `check_compara_reference_duplicate_group_members` | A genome is a current member of the same group more than once (`genome_group_member` has no unique key) |
| `check_compara_reference_groups_have_collection` | A `compara_reference` group has current members but no collection file (directory only) |

The missing and extra member checks skip collections that have no group, which are
already reported by the genome group check. The suppressed, released and production name
checks skip genome UUIDs that are not in the `genome` table, which are already reported by
`check_compara_reference_genomes_exist`. With a single CSV file, the duplicate member check
only looks at that collection's group.

## Configuration

The checks read the CSV files from `compara_reference.path`, which is either:

- **A directory**, such as the `collections/` folder: every `*.csv` in it is checked
  (other files, like the `.tsv` files, are ignored).
- **A single CSV file**, such as `40674_mammalia.csv`: only that collection and its
  genome group are checked. `check_compara_reference_groups_have_collection` is
  skipped, because the other collections were not read.

The `compara_reference` entry in `../resource_config.json` has no default path:

```json
"compara_reference": {
  "ignore": "False",
  "path": ""
}
```

Set it with `--params`, or with an environment variable (note the double underscore):

```bash
--params compara_reference.path=/path/to/collections
export ENSEMBL_DATACHECK_COMPARA_REFERENCE__PATH=/path/to/collections
```

If no path is set, every check errors with `Set compara_reference.path ...`.
Switch the checks off with `--params compara_reference.ignore=True`.

`--file`/`--target-file` is not used: the result cache keys on that file's contents,
so a cached result could hide a change in the metadata database, and the cache cannot
read a directory.

## Running

```bash
# Every collection in a directory
ensembl-datacheck --test=automation/compara_reference --database ${METADATA_DB_URL} \
  --params compara_reference.path=/path/to/collections

# One collection
ensembl-datacheck --test=automation/compara_reference --database ${METADATA_DB_URL} \
  --params compara_reference.path=/path/to/collections/40674_mammalia.csv
```

`--database` (metadata DB) is required. `--release_name` and `--genome_uuid` are not
used. `--test=automation` does not run this directory; run it by path.

Failures start with a one-line count and the collections source. Add
`--native-output` to print the full list, or `--json-report` to store it in the
report.
