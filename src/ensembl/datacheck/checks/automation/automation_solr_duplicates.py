# See the NOTICE file distributed with this work for additional information
# regarding copyright ownership.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Check selected genomes for identical documents in a Solr collection.

The selected genome UUIDs come from automation's existing ``genomes`` fixture,
so callers can restrict the check with the standard comma-separated
``--genome_uuid`` option. Solr URL and collection are supplied through the
``solr_duplicates`` automation resource configuration.

Example::

    ensembl-datacheck --test automation \
      --automation_resource solr_duplicates \
      --database '<metadata database URL>' \
      --genome_uuid '<uuid-1>,<uuid-2>' \
      --params 'solr_duplicates.ignore=False' \
      --params 'solr_duplicates.uri=http://host:port/solr' \
      --params 'solr_duplicates.collection=beta_even'
"""

import hashlib
import json
from urllib.parse import quote

import pytest
import requests


RESOURCE_KEY = "solr_duplicates"
QUERY_FIELD = "genome_id"
DEFAULT_PAGE_SIZE = 5_000
DEFAULT_TIMEOUT = 120
DEFAULT_IGNORED_FIELDS = ("id", "_version_")


def _is_true(value):
    """Return whether a config value represents true."""
    return value is True or str(value).lower() == "true"


def _normalise_ignored_fields(value):
    """Return configured ignored fields as a tuple of field names."""
    if value is None:
        return DEFAULT_IGNORED_FIELDS
    if isinstance(value, str):
        return tuple(field.strip() for field in value.split(",") if field.strip())
    return tuple(value)


def _get_solr_duplicate_config(automation_resource_config):
    """Validate and return the Solr duplicate-check configuration."""
    config = automation_resource_config.get(RESOURCE_KEY)
    assert config, f"Missing '{RESOURCE_KEY}' section in automation resource config."

    if _is_true(config.get("ignore", False)):
        pytest.skip(f"Skipped '{RESOURCE_KEY}' check as ignore=True in config")

    solr_url = config.get("uri")
    collection = config.get("collection")
    assert solr_url, f"Missing {RESOURCE_KEY}.uri in automation resource config."
    assert collection, f"Missing {RESOURCE_KEY}.collection in automation resource config."

    page_size = int(config.get("page_size", DEFAULT_PAGE_SIZE))
    timeout = float(config.get("timeout", DEFAULT_TIMEOUT))
    assert page_size > 0, f"{RESOURCE_KEY}.page_size must be greater than zero."
    assert timeout > 0, f"{RESOURCE_KEY}.timeout must be greater than zero."

    return {
        "solr_url": solr_url,
        "collection": collection,
        "page_size": page_size,
        "timeout": timeout,
        "ignored_fields": _normalise_ignored_fields(config.get("ignored_fields")),
    }


def _build_solr_select_url(solr_url, collection):
    """Build a collection select URL from either a host URL or a /solr URL."""
    base_url = solr_url.rstrip("/")
    if not base_url.endswith("/solr"):
        base_url = f"{base_url}/solr"
    return f"{base_url}/{quote(collection, safe='')}/select"


def _canonical_digest(document, ignored_fields=DEFAULT_IGNORED_FIELDS):
    """Hash stored document content after removing non-content identity fields."""
    ignored = set(ignored_fields)
    comparable = {
        field: value
        for field, value in document.items()
        if field not in ignored
    }
    canonical = json.dumps(
        comparable,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _request_page(select_url, params, timeout):
    """Request and validate one Solr cursor page."""
    response = requests.post(select_url, data=params, timeout=timeout)
    assert response.status_code == 200, (
        f"Solr select endpoint failed for URL {response.url!r} "
        f"with status code {response.status_code}."
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"Solr select endpoint did not return valid JSON for URL {response.url!r}."
        ) from exc

    response_section = payload.get("response")
    assert isinstance(response_section, dict), "Solr response field 'response' is not an object."
    documents = response_section.get("docs")
    assert isinstance(documents, list), "Solr response field 'response.docs' is not a list."
    assert "numFound" in response_section, "Solr response is missing 'response.numFound'."
    assert "nextCursorMark" in payload, "Solr cursor response is missing 'nextCursorMark'."
    return payload


def _check_genome_documents(genome_uuid, config):
    """Scan one genome and fail as soon as an identical document pair is found."""
    select_url = _build_solr_select_url(config["solr_url"], config["collection"])
    cursor_mark = "*"
    seen = {}
    documents_checked = 0
    total_documents = None

    while True:
        requested_cursor = cursor_mark
        payload = _request_page(
            select_url=select_url,
            params={
                "q": "*:*",
                "fq": f'{QUERY_FIELD}:"{genome_uuid}"',
                "rows": config["page_size"],
                "fl": "*",
                "sort": "id asc",
                "cursorMark": requested_cursor,
                "wt": "json",
                "omitHeader": "true",
            },
            timeout=config["timeout"],
        )
        response_section = payload["response"]
        if total_documents is None:
            total_documents = int(response_section["numFound"])
            assert total_documents > 0, (
                f"{genome_uuid}: no documents found in Solr collection "
                f"'{config['collection']}'."
            )

        documents = response_section["docs"]
        for document in documents:
            digest = _canonical_digest(document, config["ignored_fields"])
            document_id = str(document.get("id", ""))
            first_id = seen.get(digest)
            documents_checked += 1
            assert first_id is None, (
                f"{genome_uuid}: identical documents found in Solr collection "
                f"'{config['collection']}': {first_id!r} and {document_id!r}. "
                f"Ignored fields: {list(config['ignored_fields'])}."
            )
            seen[digest] = document_id

        cursor_mark = payload["nextCursorMark"]
        if not documents or cursor_mark == requested_cursor:
            break

    assert documents_checked == total_documents, (
        f"{genome_uuid}: Solr document count changed during the duplicate scan "
        f"for collection '{config['collection']}': expected {total_documents}, "
        f"checked {documents_checked}."
    )


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("solr")
@pytest.mark.automation_resource("solr_duplicates")
def check_solr_genome_documents_are_unique(genomes, automation_resource_config):
    """Check that the selected genome has no identical documents in Solr."""
    config = _get_solr_duplicate_config(automation_resource_config)
    genome_uuid = genomes.get("genome_uuid")
    assert genome_uuid, "Missing genome_uuid in selected genome metadata."
    _check_genome_documents(genome_uuid, config)
