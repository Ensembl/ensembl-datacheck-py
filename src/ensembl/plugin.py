import pytest
import os
import sys

def pytest_addoption(parser):
    parser.addoption(
        "--file", action="store", default=None, help="Path to the file to be tested"
    )
    parser.addoption(
        "--test", action="store", default=None, help="Name of the test to run"
    )

@pytest.fixture
def file_path(request):
    file_path = request.config.getoption("--file")
    file_path = os.path.expanduser(file_path)
    return file_path

def pytest_cmdline_main(config):
    test_name = config.getoption("--test")
    if test_name:
        test_file = f"src/tests/{test_name}.py"
        if not os.path.isfile(test_file):
            raise pytest.UsageError(f"Test file {test_file} does not exist.")
        config.args.insert(0, test_file)