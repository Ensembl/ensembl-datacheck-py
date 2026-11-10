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

"""FASTA output checks; run with --test=output_validation (both modules) or --test=output_validation/fasta."""

from ensembl.datacheck.functions.output_validation.dispatch import validate_and_report


def check_fasta_output(genomes, output_file, db_session, output_resource_config, output_report):
    """Validate genome, cDNA and peptide FASTA outputs (select with -k fasta or -k all)."""
    validate_and_report(genomes, output_file, db_session, output_resource_config, output_report)


# -k matches names in a check function's __dict__, so this attribute makes "-k all" select both
# checks without registering a custom marker (which warns when run outside this repository).
check_fasta_output.all = True
