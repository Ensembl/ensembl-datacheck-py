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

"""Resolve the input file, pick the FASTA or geneset validator and report the result to pytest."""

import logging
import os
import warnings
from pathlib import Path

import pytest

from ensembl.datacheck.checks.automation.conftest import _build_automation_resource_config
from ensembl.datacheck.functions.utils import EnsemblDatacheckWarning, get_genomes_from_metadata_db

from .common import FAIL, SKIP, GenomeMetadata, load_genome_metadata
from .fasta import FastaValidation
from .file_types import GROUP_BY_KEY, OutputFile, classify_file, normalise_file_type, output_settings
from .geneset import GenesetValidation

# Same logger name as when this was one module, so log lines read as before.
logger = logging.getLogger("output_validation")


def _resource_config_from_pytest(config):
    resource = _build_automation_resource_config(
        config_path=config.getoption("--automation_resource_config"),
        environ=os.environ,
        raw_params=config.getoption("--params"),
        use_alt=config.getoption("use_alt"),
    )
    stage = config.getoption("validation_stage", None)
    if stage:
        resource.setdefault("output_validation", {})["validation_stage"] = stage
    return resource


def required_target_file(config):
    """Require a file or validator type; release-wide runs remain unsupported."""
    if config.getoption("release_name", None):
        raise pytest.UsageError("output_validation no longer supports --release_name; it checks one file: -f FILE")
    target_file = config.getoption("target_file")
    if not target_file and not config.getoption("file_type", None):
        raise pytest.UsageError("output_validation needs one input: -f FILE or --file-type TYPE")
    return target_file


def resolve_output_input(config, settings):
    """Resolve one explicit file or one typed output under the public FTP base."""
    target = required_target_file(config)
    file_type = config.getoption("file_type", None)
    if file_type:
        file_type = normalise_file_type(file_type)
    base = config.getoption("base_path", None)
    if target:
        if base:
            raise pytest.UsageError("Use --base-path with --file-type, without -f/--target-file")
        return local_output_files(settings, target, file_type)
    genome_uuid = config.getoption("genome_uuid")
    database = config.getoption("database")
    if not genome_uuid or not database:
        raise pytest.UsageError("FTP lookup requires --genome_uuid and --database")
    rows = list(get_genomes_from_metadata_db(db_url=database, genome_uuids=[genome_uuid]))
    if not rows:
        raise pytest.UsageError(f"Genome not found in metadata: {genome_uuid}")
    from ensembl.datacheck.checks.automation.utils import get_ftp_paths
    paths = set()
    dataset = "assembly" if file_type.startswith("genome_") else "genebuild"
    for genome in rows:
        ftp_paths = get_ftp_paths(
            metadata_uri=database, taxonomy_uri=config.getoption("taxonomy_database", None),
            genome_uuid=genome_uuid, genebuild_date=genome.get("genebuild_date"),
            annotation_source=genome.get("annotation_source"),
            assembly_accession=genome.get("assembly_accession"))
        paths.update(item["path"] for item in ftp_paths if item["dataset_type"] == dataset)
    if len(paths) != 1:
        raise pytest.UsageError(f"Expected one FTP {dataset} path for {genome_uuid}, found {sorted(paths)}")
    directory = Path(base or settings.get("base_path") or "/nfs/ftp/public/ensemblorganisms").expanduser() / paths.pop()
    if not directory.is_dir():
        raise pytest.UsageError(f"FTP output directory not found: {directory}")
    candidates = [p for p in sorted(directory.iterdir())
                  if p.is_file() and classify_file(p, settings) == file_type]
    if len(candidates) != 1:
        raise pytest.UsageError(
            f"Expected one {file_type} file in {directory}, found {len(candidates)}; use -f FILE to select one")
    return local_output_files(settings, candidates[0], file_type)


def local_output_files(settings, target_file, file_type=None):
    """Build the OutputFile for -f FILE; a GFF3 in the same folder is paired for cross-reference."""
    path = Path(target_file).expanduser()
    if not path.is_file():
        raise pytest.UsageError(f"-f/--target-file not found: {path}")
    key = normalise_file_type(file_type) if file_type else classify_file(path, settings)
    if key is None:
        raise pytest.UsageError(
            f"Cannot determine output type of {path.name}; expected a genome/cDNA/peptide FASTA, GFF3, GTF "
            "or chromosome TSV name")
    gff3 = None
    if key in ("cdna", "peptide", "gtf"):
        gff3_files = [p for p in path.parent.iterdir()
                      if p != path and p.is_file() and classify_file(p, settings) in ("gff3", "raw_gff3")]
        # GTF references must share the filename stem; never use another geneset.
        stem = path.name.split(".gtf", 1)[0] if key == "gtf" else None
        if stem is not None:
            gff3_files = [p for p in gff3_files if p.name.split(".gff3", 1)[0] == stem]
        gff3_files.sort(key=lambda p: (
            0 if stem is not None and p.name.split(".gff3", 1)[0] == stem else 1,
            0 if classify_file(p, settings) == "gff3" else 1, p.name))
        gff3 = str(gff3_files[0]) if gff3_files else None
    group = GROUP_BY_KEY.get(key, "fasta")
    return [OutputFile(key, group, path.name, path=str(path), gff3_path=gff3)]


_METADATA_CACHE = {}


class OutputValidation:
    """Run the right validator for the -f file and report results."""

    def __init__(self, db_session, resource_config, genome):
        self.resource_config = resource_config
        self.settings = output_settings(resource_config)
        self.genome = genome
        uuid = genome.get("genome_uuid")
        if db_session is None or not uuid:
            self.metadata = GenomeMetadata(sequences=[], available=False)
            return
        if uuid not in _METADATA_CACHE:
            _METADATA_CACHE.clear()
            _METADATA_CACHE[uuid] = load_genome_metadata(db_session, uuid)
        self.metadata = _METADATA_CACHE[uuid]

    def validate(self, output_file):
        path = Path(output_file.path)
        gff3_path = output_file.gff3_path
        fasta = FastaValidation(self.metadata, self.settings)
        geneset = GenesetValidation(self.metadata, self.settings)
        if output_file.key.startswith("genome_"):
            return fasta.validate_genome_fasta(path, output_file.key.removeprefix("genome_"))
        if output_file.key == "cdna":
            return fasta.validate_cdna_fasta(path, gff3_path)
        if output_file.key == "peptide":
            return fasta.validate_peptide_fasta(path, gff3_path)
        if output_file.key == "gff3":
            return geneset.validate_gff3(path)
        if output_file.key == "gtf":
            return geneset.validate_gtf(path, gff3_path)
        if output_file.key in ("raw_gff3", "raw_gtf"):
            return geneset.validate_raw_geneset(path, output_file.key.removeprefix("raw_"))
        if output_file.key == "chromosome_tsv":
            return geneset.validate_chromosome_tsv(path)
        raise ValueError(f"Unknown output file key {output_file.key}")

    @staticmethod
    def report(file_report):
        """Log stage results, emit warnings, and fail/skip the pytest item as needed."""
        label = file_report.label
        for stage in file_report.stages:
            log = logger.error if stage.status == FAIL else logger.warning if stage.status == SKIP else logger.info
            log("[%s] %s: %s%s", label, stage.stage, stage.status, f" - {stage.reason}" if stage.reason else "")
            for detail in stage.details[1:]:
                log("      %s", detail)
        overall = file_report.overall
        (logger.error if overall == FAIL else logger.info)("[%s] overall: %s", label, overall)
        for message in file_report.warnings:
            warnings.warn(EnsemblDatacheckWarning(f"[{label}] {message}", "output_validation", "report"))

        failures = file_report.failures
        if failures:
            items = [f"{stage.stage}: {detail}" for stage in failures for detail in (stage.details or [stage.reason])]
            items += [f"{stage.stage}: SKIP - {stage.reason}" for stage in file_report.unexpected_skips]
            raise AssertionError("\n".join(
                [f"Output validation failures in {label}: {len(failures)}. Release path: {file_report.path}",
                 "Full list:"] + [item.replace('"', "") for item in items]
            ))
        if file_report.unexpected_skips:
            pytest.skip("; ".join(f"[{label}] {s.stage}: {s.reason}" for s in file_report.unexpected_skips))


def validate_and_report(genomes, output_file, db_session, resource_config, output_report):
    if output_file.key in ("gtf", "cdna", "peptide"):
        reference = str(Path(output_file.gff3_path).resolve()) if output_file.gff3_path else "not found"
        logger.info("[%s] GFF3 reference: %s", output_file.filename, reference)
    file_report = OutputValidation(db_session, resource_config, genomes).validate(output_file)
    output_report.add(file_report, output_file, genomes)
    OutputValidation.report(file_report)
