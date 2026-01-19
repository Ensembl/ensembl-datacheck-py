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
from pathlib import Path
import re
from typing import Any, Callable

import pytest
import sqlalchemy
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker
import xxhash


# Global variables to collect information at diverse stages of the datachecks
cache_report: dict[str, Any] = {}
failed_tests: dict[str, bool] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    Registers argparse-style options for Ensembl Datachecks.

    Args:
        parser: Parser for command line arguments and ini-file values.
    """
    parser.addoption("--test", required=True, help="Name of the test to run")
    parser.addoption(
        "--file", type=lambda x: Path(x) if x else x, default=None, help="Path to the file to be tested"
    )
    parser.addoption("--database", help="Database URL for SQLAlchemy")


@pytest.fixture
def file_path(request: pytest.FixtureRequest) -> Path | None:
    """
    Pytest fixture to get the file path from the command-line options.

    Args:
        request: The fixture request object.

    Returns:
        The file path, or None if not provided.
    """
    file_path = request.config.getoption("--file")
    if file_path:
        file_path = Path(file_path).expanduser()
    return file_path


@pytest.fixture(scope="session")
def db_session(request: pytest.FixtureRequest) -> sqlalchemy.orm.Session | None:
    """
    Pytest fixture to create a SQLAlchemy database session.

    Args:
        request: The fixture request object.

    Yields:
        The database session, or None if not provided.
    """
    database_url = request.config.getoption("--database")
    if database_url:
        engine = create_engine(database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
    else:
        yield None


def pytest_cmdline_main(config: pytest.Config) -> None:
    """
    Ensures only the specified test file is run.

    Args:
        config: The pytest configuration object.

    Raises:
        pytest.UsageError: If the specified test file does not exist.
    """
    test_name = config.getoption("--test")
    if test_name:
        test_file = Path(__file__).parent / "checks" / f"{test_name}.py"
        if not os.path.isfile(test_file):
            raise pytest.UsageError(f"Test file {test_file} does not exist.")
        config.args[:] = [str(test_file)]  # Ensure only the specified test file is run


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """
    Allows plugins and conftest files to perform initial configuration.

    More information: https://docs.pytest.org/en/latest/reference/reference.html#std-hook-pytest_configure

    Args:
        config: The pytest config object.
    """
    # Update the `cache_dir` path based on the data to validate
    if config.getoption("--file"):
        # Generate cache directory based on file hash
        file_hash = xxhash.xxh64_hexdigest(config.getoption("--file").read_bytes())
        cache_dir = Path(config.getini("cache_dir")) / file_hash
        config._inicache["cache_dir"] = cache_dir
    elif config.getoption("--database"):
        # Generate cache directory based on database update time
        db_url = make_url(config.getoption("--database"))
        engine = create_engine(db_url)
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    """
                    SELECT MAX(UPDATE_TIME) as last_update
                    FROM information_schema.tables
                    WHERE TABLE_SCHEMA = :database
                    """
                ),
                {"database": connection.engine.url.database},
            )
            last_update = result.scalar()
        cache_dir = Path("/hps/nobackup/flicek/ensembl/production/datachecks/python_dc/") / \
            db_url.host / db_url.database / last_update.strftime("%Y%m%d%H%M%S")
    else:
        raise ValueError("Either '--file' or '--database' must be provided.")
    # Prevent pytest from automatically running tests here
    config.option.runpytest = False


def pytest_pycollect_makeitem(
    collector: pytest.Collector, name: str, obj: Callable
) -> pytest.Function | None:
    """
    Custom item collection to support test naming convention.

    Args:
        collector: The collector object.
        name: Name of the test item.
        obj: The test function.

    Returns:
        The pytest Function item if the naming convention matches, else None.
    """
    if name.startswith("check_") and callable(obj):
        return pytest.Function.from_parent(collector, name=name)
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """
    Actions to perform at the start of the pytest session.

    Args:
        session: The pytest session object.
    """
    print("Ensembl Datacheck")
    print("https://github.com/Ensembl/ensembl-datacheck-py")
    print("Documentation available at TODO")
    print("Contributions are always welcome")


def pytest_collection_modifyitems(session: pytest.Session) -> None:
    """
    Actions to perform after test collection is finished.

    Args:
        session: The pytest session object.
    """
    # Report cached passed tests from previous run
    tests_collected = set(session.config.cache.get("cache/nodeids", []))
    lastfailed = set(session.config.cache.get("cache/lastfailed", {}).keys())
    for test in tests_collected.difference(lastfailed):
        test_file, test_func = test.split("::")
        test_name = Path(test_file).stem
        cache_report.setdefault("PASSED (CACHED)", [])
        cache_report["PASSED (CACHED)"].append(f"{test_name}::{test_func}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> pytest.TestReport:
    """
    Called to create a :class:`~pytest.TestReport` for each of the setup, call and teardown runtest
    phases of a test item.

    Args:
        item: The item.
        call: The :class:`~pytest.CallInfo` for the phase.
    """
    # Execute all other hooks to obtain the report object
    report = yield
    test_report = report.get_result()
    if test_report.when == "call":
        test_file, _, test_func = test_report.location
        test_name = Path(test_file).stem
        test_outcome = test_report.outcome.upper()
        test_id = f"{test_name}::{test_func}"
        # Format error message for better readability, if applicable
        if test_report.passed:
            cache_report.setdefault(test_outcome, [])
            cache_report[test_outcome].append(test_id)
        else:
            failed_tests[f"{test_file}::{test_func}"] = True
            if isinstance(test_report.longrepr, tuple):
                error_msg = "\n".join(map(str, test_report.longrepr)).splitlines()
            else:
                error_msg = str(test_report.longrepr).splitlines()
            # If "AssertionError", remove the last line that contains the assertion code
            if "AssertionError" in error_msg[0]:
                error_msg = [line[2:] for line in error_msg[:-1]]
            cache_report.setdefault(test_outcome, {})
            cache_report[test_outcome][test_id] = re.sub(r'^[^:]+: ', "", "\n".join(error_msg))
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    """
    Called after whole test run finished, right before returning the exit status to the system.

    Args:
        session: The pytest session object.
        exitstatus: The status which pytest will return to the system.
    """
    session.config.cache.set("cache/lastfailed", failed_tests)
    session.config.cache.set("cache/report", cache_report)
