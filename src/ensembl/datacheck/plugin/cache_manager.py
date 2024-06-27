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

import pathlib
import pytest
import pickle
import xxhash
from sqlalchemy import create_engine, text
from datetime import datetime

class CacheManager:
    """
    Manages caching for pytest runs to optimize performance by reusing results.

    Attributes:
        config (pytest.Config): Pytest configuration object.
        file_path (str): Path to the file specified in the command line arguments.
        test_name (str): Name of the test specified in the command line arguments.
        database_url (str): Database URL specified in the command line arguments.
        cache_dir (pathlib.Path): Directory path where the cache is stored.
    """

    def __init__(self, config):
        """
        Initializes CacheManager with the given configuration.

        Args:
            config (pytest.Config): Pytest configuration object.
        """
        self.config = config
        self.file_path = config.getoption("--file")
        self.test_name = config.getoption("--test")
        self.database_url = config.getoption("--database")
        self.cache_dir = self.get_cache_dir()

    def get_cache_dir(self):
        """
        Determines the cache directory based on the input file or database URL.

        Returns:
            pathlib.Path: Path to the cache directory.

        Raises:
            ValueError: If neither --file nor --database is provided.
        """
        if self.file_path:
            # Generate cache directory based on file hash
            file_hash = xxhash.xxh64_hexdigest(pathlib.Path(self.file_path).read_bytes())
            cache_dir = pathlib.Path(f"/hps/nobackup/flicek/ensembl/production/datachecks/python_dc/{file_hash}")
        elif self.database_url:
            # Generate cache directory based on database update time
            engine = create_engine(self.database_url)
            with engine.connect() as connection:
                result = connection.execute(text("""
                    SELECT MAX(UPDATE_TIME) as last_update
                    FROM information_schema.tables
                    WHERE TABLE_SCHEMA = :database
                """), {"database": connection.engine.url.database})
                last_update = result.scalar()
                last_update_str = last_update.strftime('%Y%m%d%H%M%S')
            server = self.database_url.split('@')[1].split('/')[0]
            db_name = self.database_url.split('/')[-1]
            cache_dir = pathlib.Path(f"/hps/nobackup/flicek/ensembl/production/datachecks/python_dc/{server}/{db_name}/{last_update_str}")
        else:
            raise ValueError("Either --file or --database must be provided.")
        return cache_dir

    def get_results_file(self):
        """
        Determines the path to the results file based on the input file or database URL.

        Returns:
            pathlib.Path: Path to the results file.
        """
        if self.file_path:
            filename = pathlib.Path(self.file_path).stem
            results_file = self.cache_dir / f"{filename}_results.txt"
        else:
            results_file = self.cache_dir / "results.txt"
        return results_file

    def setup_cache(self):
        """
        Sets up the cache directory and loads previous test results if available.

        If cached results are found, pytest exits early with the cached results.
        """
        results_file = self.get_results_file()
        cache_file = self.cache_dir / "cache.pkl"

        if self.cache_dir.exists():
            if results_file.exists() and not cache_file.exists():
                print("Using cached results:")
                print(results_file.read_text())
                pytest.exit("Using cached results, exiting.")

            if cache_file.exists():
                with cache_file.open("rb") as f:
                    last_failed = pickle.load(f)
                self.config.cache.set("cache/lastfailed", last_failed)
                self.config.option.last_failed = True
                self.config.option.continue_on_collection_errors = True
                print(f"Loading last failed tests from cache: {last_failed}")
        else:
            self.cache_dir.mkdir(parents=True)
            print(f"Created cache directory at: {self.cache_dir}")

    def load_test_results(self):
        """
        Loads previous test results from the results file if available.

        If the results file is found, pytest exits early with the loaded results.

        Raises:
            FileNotFoundError: If no previous test results are found.
        """
        results_file = self.get_results_file()
        if results_file.exists():
            print("Loading previous test results:")
            print(results_file.read_text())
            pytest.exit("Previous test results loaded, exiting.")
        else:
            raise FileNotFoundError(f"No previous test results found for {self.file_path or self.database_url}")

    def handle_cache_post_run(self, terminalreporter):
        """
        Handles cache operations after the pytest run.

        This includes writing the summary to the results file, saving the cache, and cleaning up if all tests passed.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
        results_file = self.get_results_file()
        self.write_summary_to_file(results_file)
        self.save_cache(terminalreporter)
        self.cleanup_cache_if_all_passed(terminalreporter)

    def write_summary_to_file(self, results_file):
        """
        Writes the test summary to the results file using the custom summary plugin.

        Args:
            results_file (pathlib.Path): Path to the results file.
        """
        custom_summary_plugin = self.config.pluginmanager.getplugin('custom_summary_plugin')
        if custom_summary_plugin:
            custom_summary_plugin.write_summary_to_file(results_file)

    def save_cache(self, terminalreporter):
        """
        Saves the IDs of the failed tests to the cache file.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
        cache_file = self.cache_dir / "cache.pkl"
        last_failed = terminalreporter.stats.get('failed', {})
        last_failed_ids = {item.nodeid: True for item in last_failed}
        with cache_file.open("wb") as f:
            pickle.dump(last_failed_ids, f)

    def cleanup_cache_if_all_passed(self, terminalreporter):
        """
        Cleans up the cache if all tests passed by deleting the cache file.

        Args:
            terminalreporter (pytest.TerminalReporter): Pytest terminal reporter plugin.
        """
        cache_file = self.cache_dir / "cache.pkl"
        if not terminalreporter.stats.get('failed', {}):
            if cache_file.exists():
                print(f"All tests passed. Deleting cache file: {cache_file}")
                cache_file.unlink()
