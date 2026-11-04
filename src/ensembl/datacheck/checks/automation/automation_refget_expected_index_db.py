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

"""Check assembly and MongoDB MD5 coverage using automation resources.

The shared engine lives in checks/refget_expected_index_db.py. UUIDs are
mandatory; the batch fixture applies no release filter. Settings follow the
standard bundled config < config file < environment < dotted --params order.
"""

import json
from pathlib import Path

import pytest

from ensembl.datacheck.checks import refget_expected_index_db as refget


@pytest.fixture(scope="module")
def refget_index_report(
    db_session, refget_index_genomes, refget_index_config, mongo_client,
):
    """Query all requested genomes once and share the source-specific report."""
    if db_session is None:
        raise ValueError("--database is required for assembly_sequence checksums.")
    config = refget_index_config
    report = refget.validate_genome_index(
        db_session, refget_index_genomes, config["index_file"],
        mongo_client=mongo_client,
        mongo_database=config.get("mongo_database"),
        index_backend=config.get("index_backend", "auto"),
    )
    if config.get("report"):
        Path(config["report"]).expanduser().write_text(json.dumps(report, indent=2) + "\n")
    return report


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("refget")
@pytest.mark.parametrize("mongo_client", ["refget_index"], indirect=True)
def check_refget_assembly_sequence_index_db(refget_index_report):
    """Check metadata assembly_sequence MD5 coverage in the shared index."""
    refget.check_refget_assembly_sequence_index_db(refget_index_report)


@pytest.mark.automation_resource("all")
@pytest.mark.automation_resource("refget")
@pytest.mark.parametrize("mongo_client", ["refget_index"], indirect=True)
def check_refget_mongo_index_db(refget_index_report):
    """Check MongoDB region, protein and transcript MD5 coverage in the index."""
    refget.check_refget_mongo_index_db(refget_index_report)
