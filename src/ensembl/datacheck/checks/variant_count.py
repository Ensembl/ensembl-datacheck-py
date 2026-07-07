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

"""
variant_count.py

Checks performed:
1. check_vcf_count: Asserts target VCF count, source VCF count, and
   metadatadb attribute value are the same.

Example:
    ensembl-datacheck \
        --test=variant_count \
        --target-file=/path/to/target.vcf.gz \
        --source-file=/path/to/source.vcf.gz \
        --database=mysql://user:pass@host:port/metadata_db \
        --params dataset_uuid=<dataset_uuid>

To override the metadata attribute name:
    ensembl-datacheck \
        --test=variant_count \
        --target-file=/path/to/target.vcf.gz \
        --source-file=/path/to/source.vcf.gz \
        --database=mysql://user:pass@host:port/metadata_db \
        --params dataset_uuid=<dataset_uuid>,attribute_name=variation.stats.short_variants
"""
import pytest
from ensembl.datacheck.plugins.pytest_hooks import PARSED_PARAMS_STASH_KEY
from ensembl.production.metadata.api.models import Dataset, DatasetAttribute, Attribute
from ensembl.datacheck.functions.file_checks import file_exists
from ensembl.datacheck.functions.vcf_sampling import (
    get_vcf_variant_count,
)


def get_variant_count_metadata(db_session, dataset_uuid, attribute_names='variation.stats.short_variants'):
    if isinstance(attribute_names, str):
        attribute_names = [attribute_names]

    rows = (
        db_session.query(DatasetAttribute.value)
        .select_from(Dataset)
        .join(DatasetAttribute, Dataset.dataset_id == DatasetAttribute.dataset_id)
        .join(Attribute, DatasetAttribute.attribute_id == Attribute.attribute_id)
        .filter(Dataset.dataset_uuid == dataset_uuid)
        .filter(Attribute.name.in_(attribute_names))
        .order_by(Attribute.name)
        .order_by(DatasetAttribute.value)
        .all()
    )
    return [value for (value,) in rows]


def _parse_variant_count(value, label):
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"{label} is not an integer: {value!r}") from exc


@pytest.mark.usefixtures("db_session")
def check_vcf_count(target_file, source_file, db_session, request):
    assert file_exists(target_file), "The target file does not exist."
    assert source_file is not None, "A source file is required (--source-file)."
    assert file_exists(source_file), "The source file does not exist."
    assert db_session is not None, "A metadata database is required (--database)."

    params = request.config.stash.get(PARSED_PARAMS_STASH_KEY, {})
    dataset_uuid = params.get("dataset_uuid")
    assert dataset_uuid, "A dataset UUID is required (--params dataset_uuid=<uuid>)."

    attribute_name = params.get("attribute_name", "variation.stats.short_variants")
    metadata_values = get_variant_count_metadata(db_session, dataset_uuid, attribute_name)
    assert metadata_values, (
        f"No metadata value found for dataset_uuid={dataset_uuid!r}, "
        f"attribute_name={attribute_name!r}."
    )
    assert len(metadata_values) == 1, (
        f"Expected one metadata value for dataset_uuid={dataset_uuid!r}, "
        f"attribute_name={attribute_name!r}; found {metadata_values!r}."
    )

    target_count = get_vcf_variant_count(target_file)
    source_count = get_vcf_variant_count(source_file)
    metadata_count = _parse_variant_count(metadata_values[0], "Metadata variant count")

    assert target_count == source_count == metadata_count, (
        "Variant counts do not match: "
        f"target_file={target_count}, "
        f"source_file={source_count}, "
        f"metadata[{attribute_name}]={metadata_count}."
    )
