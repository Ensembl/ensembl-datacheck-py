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
blast_db.py

This module performs generic BLAST database checks.

A BLAST database is a *set* of files sharing a common prefix
(softmasked.ndb, softmasked.nhr, ...), so ``target_file`` is the database
prefix handed to the BLAST+ tools, not a single file on disk. A volume
suffix, if present, is stripped automatically.

The NCBI BLAST+ command-line tools (`blastdbcmd`, `blastdbcheck`) are the
source of truth for the binary format and are required on PATH; there is no
native Python reader equivalent to pyBigWig for BLAST databases.

Checks performed:
1. check_exist:    Asserts BLAST database files exist for the target prefix.
2. check_validity: Asserts the database is readable (`blastdbcmd -info`) and
                   passes `blastdbcheck`, ignoring the benign taxid-lookup
                   exception raised when taxdb.* is not on the BLASTDB path.
"""
import glob
import os
import re
import shutil
import subprocess

# blastdbcheck's MetaData sub-test resolves the taxid embedded in the volume
# via GetTaxInfo(), which needs taxdb.* on the BLASTDB path. When those files
# aren't present it throws — a lookup failure, NOT corruption — so we ignore it.
_TAXID_LOOKUP_NOISE = re.compile(r"GetTaxInfo\(\)\s*-\s*Taxid\s+\d+\s+not found")

_BLAST_DB_SUFFIXES = (
    ".ndb", ".nhr", ".nin", ".nog", ".nos", ".not", ".nsq", ".ntf", ".nto",
    ".nsi", ".nsd", ".nal", ".pdb", ".phr", ".pin", ".pog", ".pos", ".pot",
    ".psq", ".ptf", ".pto", ".psi", ".psd", ".pal",
)


def _blast_db_prefix(path):
    """Strip a BLAST volume suffix so we hold the DB prefix the tools expect."""
    p = str(path)
    for suffix in _BLAST_DB_SUFFIXES:
        if p.endswith(suffix):
            return p[: -len(suffix)]
    return p


def _blast_db_files(prefix):
    """All files belonging to a BLAST database prefix."""
    return sorted(glob.glob(_blast_db_prefix(prefix) + ".*"))


def _blast_env(taxdb_dir=None):
    """Environment for BLAST+ tools, optionally adding taxdb to BLASTDB."""
    env = os.environ.copy()
    if taxdb_dir:
        existing = env.get("BLASTDB", "")
        env["BLASTDB"] = f"{taxdb_dir}:{existing}" if existing else str(taxdb_dir)
    return env


def _run_blastdbcmd_info(db_prefix, taxdb_dir=None):
    """`blastdbcmd -info`: cheapest read that actually opens the index."""
    exe = shutil.which("blastdbcmd")
    if exe is None:
        raise FileNotFoundError("blastdbcmd not on PATH; is BLAST+ installed?")
    return subprocess.run(
        [exe, "-db", _blast_db_prefix(db_prefix), "-info"],
        capture_output=True, text=True, env=_blast_env(taxdb_dir),
    )


def _collect_real_errors(output):
    """
    Parse blastdbcheck output into a list of genuine errors.

    blastdbcheck prints one line per (volume / test), e.g. '<path> / MetaData:'
    or '<path> / Sample: Status for OID 0: PASS', with NCBI C++ exception
    detail spilling onto following unprefixed lines. A multi-line exception
    must be judged as a whole: the cause ('Taxid 9606 not found') sits a couple
    of lines below the 'NCBI C++ Exception:' header, so a line-by-line filter
    flags the header even when the cause is the benign taxid lookup. We group
    consecutive lines of the same test back together and classify each block.
    """
    test_re = re.compile(r" / (\w+):\s?(.*)$")
    oid_re = re.compile(r"Status for OID \d+:\s*(\S+)")

    blocks = []  # [test_name, merged_text]
    for raw in output.splitlines():
        match = test_re.search(raw)
        if match:
            test, message = match.group(1), match.group(2)
            if blocks and blocks[-1][0] == test:
                blocks[-1][1] += " " + message
            else:
                blocks.append([test, message])
        elif raw.strip() and blocks:
            blocks[-1][1] += " " + raw.strip()  # exception traceback continuation

    real_errors = []
    for test, text in blocks:
        text = text.strip()
        low = text.lower()

        bad_oids = [s for s in oid_re.findall(text) if s.upper() != "PASS"]
        if bad_oids:
            real_errors.append(f"{test}: {len(bad_oids)} sampled OID(s) did not PASS")

        if ("[error]" in low or "exception" in low) and not _TAXID_LOOKUP_NOISE.search(text):
            real_errors.append(f"{test}: {text}")

    return real_errors


def _run_blastdbcheck(db_prefix, taxdb_dir=None, full=False, sample=200):
    """
    Run blastdbcheck and return (passed, real_errors).

    stderr is merged into stdout so an exception header and its cause stay
    adjacent and can be grouped. The benign taxid-lookup exception (raised
    when taxdb.* isn't on the BLASTDB path) is filtered out; a non-PASS OID
    or any other exception is a real error.
    """
    exe = shutil.which("blastdbcheck")
    if exe is None:
        raise FileNotFoundError("blastdbcheck not on PATH; is BLAST+ installed?")

    cmd = [exe, "-db", _blast_db_prefix(db_prefix), "-verbosity", "3"]
    cmd += ["-full"] if full else ["-random", str(sample)]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=_blast_env(taxdb_dir),
    )

    errors = _collect_real_errors(proc.stdout)
    return (not errors), errors


def check_exist(target_file):
    """Check that BLAST database files exist for the target prefix.

    Args:
        target_file (pathlib.Path or None): BLAST database prefix.

    Raises:
        AssertionError: If no database files are found.
    """
    assert _blast_db_files(target_file), (
        f"No BLAST database files found for '{target_file}'."
    )


def check_validity(target_file, taxdb_dir=None, full=False):
    """Check that the target is a valid, readable BLAST database.

    Args:
        target_file (pathlib.Path or None): BLAST database prefix.
        taxdb_dir (str or None): Directory holding taxdb.* / taxonomy4blast.*.
            If given, it is prepended to BLASTDB so the MetaData test resolves
            embedded taxids cleanly. Optional — noise is filtered either way.
        full (bool): If True, blastdbcheck validates every sequence (slow);
            otherwise it samples (default).

    Raises:
        AssertionError: If the database is missing, unreadable, or fails check.
    """
    assert _blast_db_files(target_file), (
        f"No BLAST database files found for '{target_file}'."
    )

    info = _run_blastdbcmd_info(target_file, taxdb_dir=taxdb_dir)
    assert info.returncode == 0 and info.stdout.strip(), (
        f"BLAST database '{target_file}' could not be opened: "
        f"{(info.stderr or info.stdout).strip()}"
    )

    passed, errors = _run_blastdbcheck(target_file, taxdb_dir=taxdb_dir, full=full)
    assert passed, (
        f"blastdbcheck reported errors for '{target_file}':\n  "
        + "\n  ".join(errors)
    )