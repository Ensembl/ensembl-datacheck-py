import sys
import pytest
import os


def main():
    # Remove the script name from sys.argv
    args = sys.argv[1:]
    sys.exit(pytest.main(args))


if __name__ == "__main__":
    main()