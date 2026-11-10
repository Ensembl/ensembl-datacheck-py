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
import os
import sys
import pytest

# Short flag only for --test=ftp_file_validation; elsewhere -f keeps its pytest-xdist meaning.
OUTPUT_VALIDATION_SHORT_FLAGS = {"-f": "--target-file"}
# Folder (-d) and release (-rn ... -release-check) runs were removed; ftp_file_validation checks one file.
# Without this, -rn / -release-check would be read silently as pytest's -r (report characters).
OUTPUT_VALIDATION_REMOVED_FLAGS = ("-d", "--target-dir", "-rn", "--release_name", "-release-check", "--release-check")

# Checks that were removed, mapped to the message pointing at their replacement.
REMOVED_TESTS = {
    "fasta": "--test=fasta has been removed; FASTA validation is now in ftp_file_validation. "
             "Use: ensembl-datacheck --test=ftp_file_validation -f FILE",
}


def check_removed_test(args):
    """Exit with a pointer to the replacement when a removed check is requested."""
    message = REMOVED_TESTS.get(_selected_test(args))
    if message:
        raise SystemExit(message)


def _selected_test(args):
    """Return the --test value from the argument list, if any."""
    for index, arg in enumerate(args):
        if arg.startswith("--test="):
            return arg.split("=", 1)[1]
        if arg == "--test" and index + 1 < len(args):
            return args[index + 1]
    return None


def _is_ftp_file_validation(args):
    """True for --test=ftp_file_validation and its parts (ftp_file_validation/fasta, ftp_file_validation/geneset)."""
    test = _selected_test(args) or ""
    return test.rstrip("/") == "ftp_file_validation" or test.startswith("ftp_file_validation/")


def translate_short_flags(args):
    """Map ftp_file_validation's -f FILE to --target-file and reject the removed folder/release flags."""
    if not _is_ftp_file_validation(args):
        return args
    translated = []
    iterator = iter(args)
    for arg in iterator:
        flag, sep, value = arg.partition("=")
        if flag in OUTPUT_VALIDATION_REMOVED_FLAGS:
            raise SystemExit(f"{flag} is no longer supported: ftp_file_validation checks one file, use -f FILE")
        if flag in OUTPUT_VALIDATION_SHORT_FLAGS:
            if not sep:
                value = next(iterator, None)
                if value is None:
                    raise SystemExit(f"{flag} requires a value")
            translated.extend([OUTPUT_VALIDATION_SHORT_FLAGS[flag], value])
        else:
            translated.append(arg)
    return translated


DATABASE_OPTIONS = ("--database", "--other_database", "--taxonomy_database")
OUTPUT_DIR_JSON_REPORT = "report.json"


def _option_value(args, name):
    """Return the last value given for --name VALUE or --name=VALUE."""
    value = None
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            value = args[index + 1]
        elif arg.startswith(f"{name}="):
            value = arg.split("=", 1)[1]
    return value


def mysql_url_for_pymysql(url):
    """`prod1 details url` prints mysql://user@host:port/; use the installed pymysql driver for it."""
    return "mysql+pymysql://" + url[len("mysql://"):] if url.startswith("mysql://") else url


def apply_ftp_file_validation_defaults(args):
    """For ftp_file_validation: accept plain mysql:// URLs and send the JSON report to --output-dir."""
    if not _is_ftp_file_validation(args):
        return args
    updated = []
    iterator = iter(args)
    for arg in iterator:
        flag, sep, value = arg.partition("=")
        if flag in DATABASE_OPTIONS:
            if not sep:
                value = next(iterator, "")
            updated.extend([flag, mysql_url_for_pymysql(value)])
        else:
            updated.append(arg)
    if "--output-dir" in updated or any(arg.startswith("--output-dir=") for arg in updated):
        output_dir = _option_value(updated, "--output-dir")
        # An unset shell variable (--output-dir $output_dir) would otherwise take the next option as the folder.
        if not output_dir or output_dir.startswith("-"):
            raise SystemExit("--output-dir requires a folder name (is the shell variable set?)")
    output_dir = _option_value(updated, "--output-dir")
    if output_dir and _option_value(updated, "--json-report-file") is None:
        updated.extend(["--json-report", f"--json-report-file={os.path.join(output_dir, OUTPUT_DIR_JSON_REPORT)}"])
        os.makedirs(output_dir, exist_ok=True)
    return updated


def main():
    """
    Main entry point for the script when using ensembl-datacheck.

    This function processes command-line arguments to configure and run pytest with
    the datacheck functionality.

    The script removes the script name from `sys.argv`, adds a custom plugin to the
    arguments, ensures traceback and output options are set correctly, and then
    executes pytest.

    Raises:
        SystemExit: Exits the script with the exit code from pytest.
    """
    # Remove the script name from sys.argv
    check_removed_test(sys.argv[1:])
    args = apply_ftp_file_validation_defaults(translate_short_flags(sys.argv[1:]))

    # Custom plugin name
    plugin_name = 'ensembl.datacheck.plugin'

    # Always add the plugin
    args.extend(['-p', plugin_name])

    # Check if traceback option is present
    tb_option_present = any(arg.startswith('--tb') for arg in args)

    # Check if native output option is present
    native_output_present = '--native-output' in args

    if tb_option_present and not native_output_present:
        # Add native output if traceback is present but native output is not
        args.append('--native-output')
    elif not native_output_present:
        # Disable traceback if native output is not present
        args.append('--tb=no')

    # Run pytest with the modified arguments
    sys.exit(pytest.main(args))

if __name__ == "__main__":
    main()
