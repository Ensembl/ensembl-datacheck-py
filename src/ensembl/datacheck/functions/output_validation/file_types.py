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

"""Settings, output file types and filename classification."""

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from .common import GENOME_MASKS

DEFAULT_SETTINGS = {
    "genome_fasta": ["unmasked.fa.bgz", "softmasked.fa.bgz", "hardmasked.fa.bgz"],
    "cdna_fasta": "cdna.fa.bgz",
    "peptide_fasta": "pep.fa.bgz",
    "gff3": "genes.gff3.bgz",
    "gtf": "genes.gtf.bgz",
    "raw_gff3": "genes.gff3.gz",
    "raw_gtf": "genes.gtf.gz",
    "raw_gtf_required_attributes": ["gene_id", "gene_version", "gene_biotype", "gene_source"],
    "chromosome_tsv": "chromosomes.tsv*",
    "chromosome_tsv_required": False,
    "require_gzi": False,
    "strict_metadata_counts": False,
    "check_genome_headers": True,
    "compare_genome_masks": True,
    "index_sample_size": 5,
    "max_line_width": 80,
}


@dataclass(frozen=True)
class OutputFile:
    """The output file to validate."""
    key: str  # genome_unmasked, cdna, peptide, gff3, gtf, chromosome_tsv
    group: str  # fasta or geneset
    filename: str
    path: str  # file given with -f
    gff3_path: str = None  # GFF3 in the same folder, used for cDNA/peptide/GTF cross-reference

    def __str__(self):
        return f"{self.key}:{self.path or self.filename}"


def output_settings(resource_config):
    settings = dict(DEFAULT_SETTINGS)
    settings.update(resource_config.get("output_validation") or {})
    for flag in ("chromosome_tsv_required", "require_gzi", "strict_metadata_counts", "check_genome_headers",
                 "compare_genome_masks"):
        settings[flag] = str(settings[flag]).lower() in ("1", "true", "yes")
    for number in ("index_sample_size", "max_line_width"):
        settings[number] = int(settings[number])
    return settings


INDEX_SUFFIXES = (".fai", ".gzi", ".csi", ".tbi")
GROUP_BY_KEY = {"cdna": "fasta", "peptide": "fasta", "gff3": "geneset", "gtf": "geneset",
                "raw_gff3": "geneset", "raw_gtf": "geneset", "chromosome_tsv": "geneset"}
_FASTA_NAME = re.compile(r"\.(fa|fasta|fna|faa)(\.b?gz)?$")


def classify_file(path, settings):
    """Return the output key (genome_<mask>, cdna, peptide, gff3, gtf, chromosome_tsv) for a file, or None."""
    name = Path(path).name
    lower = name.lower()
    if lower.endswith(INDEX_SUFFIXES) or lower in ("md5sum.txt",):
        return None
    configured = {settings["cdna_fasta"]: "cdna", settings["peptide_fasta"]: "peptide",
                  settings["gff3"]: "gff3", settings["gtf"]: "gtf", settings["raw_gff3"]: "raw_gff3",
                  settings["raw_gtf"]: "raw_gtf", settings["chromosome_tsv"]: "chromosome_tsv"}
    genome_fasta = settings["genome_fasta"]
    if isinstance(genome_fasta, str):
        genome_fasta = [item.strip() for item in genome_fasta.split(",")]
    for filename in genome_fasta:
        configured[filename] = f"genome_{next((m for m in GENOME_MASKS if m in filename), 'unmasked')}"
    for pattern, key in configured.items():
        if fnmatch.fnmatch(name, pattern):
            return key
    if lower.endswith(".gff3.gz"):
        return "raw_gff3"
    if lower.endswith(".gtf.gz"):
        return "raw_gtf"
    if ".gff3" in lower:
        return "gff3"
    if ".gtf" in lower:
        return "gtf"
    if ".tsv" in lower and "chrom" in lower:
        return "chromosome_tsv"
    if _FASTA_NAME.search(lower):
        for mask in GENOME_MASKS:
            if mask in lower:
                return f"genome_{mask}"
        if ".dna_sm." in lower:
            return "genome_softmasked"
        if ".dna_rm." in lower:
            return "genome_hardmasked"
        if ".dna." in lower:
            return "genome_unmasked"
        if "cdna" in lower:
            return "cdna"
        if "pep" in lower or lower.endswith((".faa", ".faa.gz", ".faa.bgz")):
            return "peptide"
    return None


CLI_FILE_TYPES = ("unmask", "softmask", "hardmask", "chrom", "cdna", "pep",
                  "gff3", "gtf", "raw_gff3", "raw_gtf")
FILE_TYPES = tuple(f"genome_{mask}" for mask in GENOME_MASKS) + tuple(GROUP_BY_KEY)


def normalise_file_type(file_type):
    """Resolve an explicit validator type independently of the input filename."""
    aliases = {"unmask": "genome_unmasked", "softmask": "genome_softmasked",
               "hardmask": "genome_hardmasked", "chrom": "chromosome_tsv",
               "cdna_fasta": "cdna", "peptide_fasta": "peptide", "pep": "peptide",
               **{mask: f"genome_{mask}" for mask in GENOME_MASKS}}
    key = aliases.get(file_type, file_type)
    if key not in FILE_TYPES:
        raise pytest.UsageError(f"Unknown --file-type {file_type!r}; choose from {', '.join(CLI_FILE_TYPES)}")
    return key
