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

"""Validate JSON files against the datacheck's Pydantic schemas.

Run the transcriptomic-selection check with::

    ensembl-datacheck --test=json_validator --file=selection.json \\
        --params=schema=transcriptomic_selection
"""

from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ensembl.datacheck.json_schemas import TranscriptomicSelection


FILE_HANDOVER_SCHEMA_NAMES = frozenset({
    "short_variants",
    "structural_variant",
    "regulation_tracks",
    "expression_tracks",
    "segmental_duplication",
})


def _load_file_handover_schemas() -> dict[str, type[BaseModel]]:
    """Load schemas supplied by file-handover when that package is installed.

    file-handover is intentionally not a dependency of this package: its source
    repository is private, and only JSON checks that explicitly select one of
    its schemas need it. Its schema package imports only Pydantic models.
    """
    module_name = "ensembl.production.file_handover.routes.schema"
    try:
        schema_module = import_module(module_name)
    except ModuleNotFoundError as exc:
        # The optional package, or one of its namespace-package parents, is
        # absent. Do not prevent unrelated datachecks from being installed or
        # run. Missing dependencies inside an installed package still surface.
        if exc.name and module_name.startswith(exc.name):
            return {}
        raise

    return dict(schema_module.TRACK_DATASET_SCHEMA_CLASSES)


FILE_HANDOVER_SCHEMAS = _load_file_handover_schemas()

SCHEMAS: dict[str, type[BaseModel]] = {
    "transcriptomic_selection": TranscriptomicSelection,
    **FILE_HANDOVER_SCHEMAS,
}


def check_validity(target_file: Path | None, params: dict[str, str]) -> None:
    """Check that ``target_file`` is valid JSON for the selected schema.

    Select a schema with ``--params schema=<name>``. Available names are
    ``transcriptomic_selection``.
    """
    assert target_file is not None and target_file.is_file(), (
        "A JSON file is required (--file or --target-file)."
    )

    schema_name = params.get("schema")
    assert schema_name, "A schema is required (--params schema=<name>)."
    schema = SCHEMAS.get(schema_name)
    if schema is None:
        if schema_name in FILE_HANDOVER_SCHEMA_NAMES and not FILE_HANDOVER_SCHEMAS:
            raise AssertionError(
                f"JSON schema '{schema_name}' requires the optional "
                "file-handover package to be installed."
            )
        raise AssertionError(
            f"Unknown JSON schema '{schema_name}'. Available schemas: "
            f"{', '.join(sorted(SCHEMAS))}."
        )

    try:
        schema.model_validate_json(target_file.read_bytes())
    except ValidationError as exc:
        raise AssertionError(
            f"JSON file '{target_file}' does not match schema '{schema_name}': {exc}"
        ) from exc
