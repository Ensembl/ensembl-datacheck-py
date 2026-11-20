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

"""Fixtures shared by regulation datachecks."""

from pathlib import Path

import pytest

SUPPORTED_FEATURE_TYPES = frozenset(
    {
        "CTCF_binding_site",
        "EMAR",
        "enhancer",
        "open_chromatin_region",
        "promoter",
    }
)


def _is_regulation_gff_check(request: pytest.FixtureRequest) -> bool:
    """Return whether the requesting check is in the regulation GFF module."""
    return Path(request.module.__file__).name == "gff.py"


@pytest.fixture
def target_file(request: pytest.FixtureRequest) -> Path | None:
    """Map a combined regulation run's source GFF to the GFF check target.

    A ``--test=regulation`` run has one primary target file: the regulatory
    BigBed. Its ``--source-file`` is the corresponding GFF, which is the
    target required by the GFF checks. Direct ``regulation/gff`` runs retain
    the normal ``--target-file`` behaviour.
    """
    option_name = "target_file"
    if (
        _is_regulation_gff_check(request)
        and request.config.getoption("test") == "regulation"
    ):
        option_name = "source_file"

    file_path = request.config.getoption(option_name)
    return Path(file_path).expanduser() if file_path else None


@pytest.fixture
def source_file(request: pytest.FixtureRequest) -> Path | None:
    """Keep the BigBed out of generic GFF checks during a combined run."""
    if (
        _is_regulation_gff_check(request)
        and request.config.getoption("test") == "regulation"
    ):
        return None

    file_path = request.config.getoption("source_file")
    return Path(file_path).expanduser() if file_path else None
