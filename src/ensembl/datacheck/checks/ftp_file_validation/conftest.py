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

"""pytest wiring shared by fasta.py and geneset.py: parametrization, the report fixture and the summary."""

import logging

import pytest

from ensembl.datacheck.functions.ftp_file_validation.dispatch import (_resource_config_from_pytest,
                                                                    resolve_output_input)
from ensembl.datacheck.functions.ftp_file_validation.file_types import output_settings
from ensembl.datacheck.functions.ftp_file_validation.report import (REPORT_KEY, OutputReportWriter, TerminalSummary,
                                                                  _run_info)

logger = logging.getLogger("ftp_file_validation")


def pytest_generate_tests(metafunc):
    """Parametrize each check by (genome, output file) for the -f file."""
    if not {"genomes", "output_file"} <= set(metafunc.fixturenames):
        return
    plugins = metafunc.config.pluginmanager
    if not plugins.has_plugin(TerminalSummary.name):
        plugins.register(TerminalSummary(), TerminalSummary.name)
    try:
        _generate_tests(metafunc)
    except pytest.UsageError as error:
        # pytest cuts a collection error to the terminal width in its summary, and the runner's
        # default --tb=no hides the traceback, so print the full message before re-raising.
        reporter = metafunc.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"ftp_file_validation usage error: {error}", red=True, bold=True)
        raise


def _generate_tests(metafunc):
    """Parametrize one resolved file; metadata uses a single --genome_uuid."""
    group = "fasta" if metafunc.function.__name__ == "check_fasta_output" else "geneset"
    settings = output_settings(_resource_config_from_pytest(metafunc.config))
    genome_uuid = metafunc.config.getoption("genome_uuid")
    if genome_uuid and "," in genome_uuid:
        raise pytest.UsageError("-f accepts a single --genome_uuid for metadata checks")
    genome = {"genome_uuid": genome_uuid}
    files = [f for f in resolve_output_input(metafunc.config, settings) if f.group == group]
    if not files:
        # An empty parameter set leaves `genomes` as NOTSET, which the JSON report hook cannot read.
        metafunc.parametrize(("genomes", "output_file"), [pytest.param(
            genome, None, marks=pytest.mark.skip(reason=f"-f file is not a {group} file"),
            id=f"no-{group}-files")])
        return
    metafunc.parametrize(("genomes", "output_file"), [(genome, f) for f in files],
                         ids=[f"{f.filename}-{f.key}" for f in files])


@pytest.fixture(scope="session")
def output_report(request):
    """Collects every file result for the terminal summary; with --output-dir also writes the JSON file."""
    writer = OutputReportWriter(request.config.getoption("output_dir", None), _run_info(request.config))
    request.config.stash[REPORT_KEY] = writer
    yield writer
    if writer.output_dir is not None:
        logger.info("ftp_file_validation report written to %s", writer.write())


@pytest.fixture(scope="session")
def output_resource_config(request):
    return _resource_config_from_pytest(request.config)
