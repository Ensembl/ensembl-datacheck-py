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
import sys
import pytest

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
    args = sys.argv[1:]

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
