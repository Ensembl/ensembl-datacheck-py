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

"""Pydantic models for transcriptomic-selection JSON payloads."""

from pydantic import BaseModel, ConfigDict, Field


class _SchemaModel(BaseModel):
    """Base model that makes the JSON schema strict."""

    model_config = ConfigDict(extra="forbid", strict=True)


class AttributeProvenance(_SchemaModel):
    """Source details for a value in the selection metadata."""

    source: str
    source_field: str
    source_id: str
    source_value: str
    normalization: str | None = None


class MetadataAttribute(_SchemaModel):
    """A selected metadata value and its provenance."""

    value: str
    provenance: AttributeProvenance


class SelectionProvenance(_SchemaModel):
    """Accessions from which a transcriptomic selection was derived."""

    biosample_accession: str
    run_accessions: list[str] = Field(min_length=1)
    study_accession: str


class TargetGenome(_SchemaModel):
    """Genome assembly targeted by a transcriptomic selection."""

    assembly: str
    assembly_uuid: str
    species: str


class TranscriptomicSelection(_SchemaModel):
    """Schema for one transcriptomic-selection record."""

    data_type: str
    display_label: str
    metadata: dict[str, MetadataAttribute] = Field(min_length=1)
    provenance: SelectionProvenance
    schema_version: str
    selection_id: str
    selection_hierarchy: list[str] = Field(min_length=1)
    selection_level: str
    target_genome: TargetGenome
