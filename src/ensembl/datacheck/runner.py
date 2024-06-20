import sys
import pytest

def main():
    # Remove the script name from sys.argv
    args = sys.argv[1:]

    # Custom plugin name
    plugin_name = 'ensembl.datacheck.plugin'

    # Always add the plugin
    args.extend(['-p', plugin_name])
    tb_option_present = any(arg.startswith('--tb') for arg in args)
    native_output_present = '--native-output' in args
    if tb_option_present and not native_output_present:
        args.append('--native-output')
    elif not native_output_present:
        args.append('--tb=no')

    sys.exit(pytest.main(args))

if __name__ == "__main__":
    main()
