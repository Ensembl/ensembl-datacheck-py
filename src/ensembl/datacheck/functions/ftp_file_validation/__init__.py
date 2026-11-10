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
FTPdump output validation library (FASTA and geneset).

The pytest checks live in checks/ftp_file_validation/ (fasta.py, geneset.py, conftest.py) and are run
together with --test=ftp_file_validation. See checks/ftp_file_validation/README.md for the full specification.

Modules:
    common       stage results, gzip/BGZF reading, genome metadata
    gene_models  GFF3/GTF parsing (used by geneset and by cDNA/peptide cross-reference)
    file_types   settings, output types, filename classification
    base         OutputValidationBase stage runner
    fasta        FastaValidation and FASTA/FAI/GZI helpers
    geneset      GenesetValidation, CSI, external validators
    dispatch     input resolution, validator selection, pytest reporting
    report       --output-dir JSON and terminal summary

Input: exactly one file per run. Supported forms:
    --genome_uuid UUID --file-type TYPE [--base-path FTP_ROOT] --database URL
    --genome_uuid UUID -f FILE
    --genome_uuid UUID -f FILE --file-type TYPE

Without -f, resolve the genome's public FTP path from metadata under FTP_ROOT
(default /nfs/ftp/public/ensemblorganisms). With -f, infer the type from the
filename unless --file-type explicitly selects the validator.

    ensembl-datacheck --test=ftp_file_validation -f genes.gff3.bgz --database <metadata_url> \
        --genome_uuid <uuid> --no-cache-results --tb=short

--database and --genome_uuid enable the metadata checks. The runner maps -f to --target-file for
this test only.

Each file is checked in the order Compression -> Index -> Format -> Completeness:
    - Compression: gzip/BGZF block integrity (CRC, size), BGZF EOF marker, nonempty content.
    - Index: FAI/GZI (FASTA) or CSI (GFF3/GTF) parse, consistency with the data and
      random-access retrieval of sampled records.
    - Format: FASTA structure / GFF3 / GTF / chromosome TSV structure, plus the external
      validators (gt gff3validator, gtfToGenePred + genePredCheck) when they are on PATH.
    - Completeness: comparison with the metadata database and with the GFF3 file.

For processed GFF3/GTF, compression also requires a same-stem .gz sibling
(e.g. genes.gff3.bgz -> genes.gff3.gz). Completeness verifies the sibling's gzip
integrity and compares feature records independent of sorting, ignoring comments
and directives. Missing or different records fail even without metadata.

Raw geneset files (genes.gff3.gz / genes.gtf.gz, unsorted dumper output) get a truncation check:
gzip integrity, final newline and a complete last feature line; for GTF the last line must also
carry gene_id, gene_version, gene_biotype and gene_source.

Stop rules:
    - Missing or ambiguous input file: usage error before any check runs.
    - Compression failure: skip index, format and completeness.
    - Index failure: skip format and completeness.
    - Format failure: completeness SKIP.

Nothing is written next to the FTPdump outputs; external tools use a temporary directory.
"""

# Re-export the public names so callers can keep using one namespace (ov.FastaValidation, ov.PASS, ...).
# Patch a function where it is looked up: e.g. geneset.run_gff3validator, not this package.
from .common import *  # noqa: F401,F403
from .gene_models import *  # noqa: F401,F403
from .file_types import *  # noqa: F401,F403
from .base import *  # noqa: F401,F403
from .fasta import *  # noqa: F401,F403
from .geneset import *  # noqa: F401,F403
from .dispatch import *  # noqa: F401,F403
from .report import *  # noqa: F401,F403
from .common import _sample  # noqa: F401
from .gene_models import _GFF3_CACHE, _check_feature_columns, _parse_gtf_attributes  # noqa: F401
from .dispatch import _resource_config_from_pytest  # noqa: F401
from .report import _run_info  # noqa: F401
