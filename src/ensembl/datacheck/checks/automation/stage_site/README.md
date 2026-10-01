# Stage Site Checks

Checks that a staging site (default `https://staging-2020.ensembl.org`) serves the
genomes in the metadata database correctly, through the same APIs and pages the
website uses.

Most checks run once per genome (`genome_uuid`), selected from the metadata DB
with `--release_name` / `--genome_uuid`, like the other automation checks.
`current_release.py` runs once per run.

## Configuration

The site URL comes from the `stage_site` entry in
`../resource_config.json`:

```json
"stage_site": {
  "ignore": "False",
  "uri": "https://staging-2020.ensembl.org"
}
```

Point the checks at another site, or switch them off:

```bash
--params stage_site.uri=https://other-site.ensembl.org
--params stage_site.ignore=True
```

When the entry is missing, ignored or has no `uri`, the checks are skipped.

## Running

```bash
# All stage site checks
ensembl-datacheck --test=automation/stage_site ${COMMON_ARGS}

# One file
ensembl-datacheck --test=automation/stage_site/genome_search ${COMMON_ARGS}
```

`COMMON_ARGS` is described in `../README.md`. `--database` (metadata DB) is
required. `--test=automation` does not run this directory; run it by path.

## Endpoints tested

`<site>` is the configured `stage_site.uri`.

### `genome_search.py`: genome selector search

| Check | Endpoint | Passes when | Purpose |
|---|---|---|---|
| `check_genome_search_by_genome_uuid` | `GET <site>/api/search/genomes?query=<genome_uuid>` | 200, a match has `genome_id` = genome_uuid, and its `assembly.url` responds with 200 | Genome can be found by its UUID in the genome selector |
| `check_genome_search_by_assembly_accession` | `GET <site>/api/search/genomes?query=<assembly_accession>` | Same as above | Genome can be found by its assembly accession in the genome selector |

The genome selector page (`<site>/genome-selector/search?query=...`) is rendered
in the browser from this API, so the API is queried directly.

### `gene_search.py`: gene search

| Check | Endpoint | Passes when | Purpose |
|---|---|---|---|
| `check_gene_search_by_sample_gene` | `POST <site>/api/search/genes` with `{"query": <sample_gene>, "genome_ids": [<genome_uuid>]}` | 200, `meta.total_hits` >= 1, and a match has `genome_id` = genome_uuid | The genome's genes are indexed and searchable |

`<sample_gene>` is the genome's `genebuild.sample_gene` dataset attribute in the
metadata DB, fetched with `get_genome_dataset_attribute()` in
`functions/utils.py`.

### `genome_page.py`: genome page

| Check | Endpoint | Passes when | Purpose |
|---|---|---|---|
| `check_genome_page_by_assembly_accession` | `GET <site>/genome/<assembly_accession>` | 200, and the page's `window.__PRELOADED_STATE__` contains a genome with the assembly accession | The genome's species page loads |

This page is rendered on the server. An unknown accession responds with 404.

### `meta_api.py`: metadata API genome endpoints

| Check | Endpoint | Passes when | Purpose |
|---|---|---|---|
| `check_meta_api_example_objects` | `GET <site>/api/metadata/genome/<genome_uuid>/example_objects` | 200, and a non-empty list where every object has `type` and `id` | The example gene/location/variant links on the site work |
| `check_meta_api_genome_id[explain]` | `GET <site>/api/metadata/genome/<genome_uuid>/explain` | 200, and `genome_id` = genome_uuid | Genome summary is served |
| `check_meta_api_genome_id[details]` | `GET <site>/api/metadata/genome/<genome_uuid>/details` | 200, and `genome_id` = genome_uuid | Genome details (species page) are served |
| `check_meta_api_stats` | `GET <site>/api/metadata/genome/<genome_uuid>/stats` | 200, and `genome_stats.assembly_stats` has at least one non-null value | Genome statistics are loaded |

### `genome_browser_and_trackapi.py`: genome browser and track API

These checks use the genome's example gene and location from
`<site>/api/metadata/genome/<genome_uuid>/example_objects`, fetched once per genome.

| Check | Endpoint | Passes when | Purpose |
|---|---|---|---|
| `check_validate_location` | `GET <site>/api/metadata/validate_location?genome_id=<genome_uuid>&location=<location>` | 200, and `region`, `start` and `end` are all `is_valid` | The example location is a valid region of the genome |
| `check_genome_browser_focus_gene` | `GET <site>/genome-browser/<assembly_accession>?focus=gene:<gene>&location=<location>`, then `POST <site>/api/graphql/core` (`gene(by_id: {genome_id, stable_id})`) | Page responds with 200, and the gene is found in GraphQL | The genome browser opens on the example gene |
| `check_track_categories` | `GET <site>/api/tracks/track_categories/<genome_uuid>` | 200, and the track categories include `Assembly` and `Genes & transcripts` | The genome browser has its core tracks |

### `current_release.py`: current release

| Check | Endpoint | Passes when | Purpose |
|---|---|---|---|
| `check_current_partial_release` | `GET <site>/api/metadata/releases?current_only=true` | 200, and the `name` of releases with `type` = `partial` equals the `label` of the current partial releases (`release_type = 'partial'`, `is_current = 1`) in `ensembl_release` | The site serves the current partial release from the metadata DB |

This check runs once per run, not once per genome. It uses
`get_current_release_labels()` in `functions/utils.py`.

## Notes

Several endpoints respond with 200 even when the data is missing. For these the
checks look at the response content, not only the status code:

- `stats` for an unknown genome responds with 200 and every stat null.
- `validate_location` responds with 200 for an invalid location; validity is in
  the `is_valid` flags.
- `genome-browser` is rendered in the browser and responds with the same 200
  page for any genome or focus. The focus gene is therefore checked through
  the Core GraphQL API the browser loads it from.
- An `assembly.url` (identifiers.org) responds with 200 even for an accession
  that does not exist, because it redirects to the ENA browser page.

## Unit tests

Unit tests for these checks are in `tests/test_automation_stage_site_*.py`.
They mock the HTTP calls. Database helpers are tested against the SQLite
metadata DB in `tests/database/`.

```bash
PYTHONPATH=src pytest --rootdir=./tests ./tests -k stage_site
```
