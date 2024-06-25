import pathlib
import pytest
import pickle
import xxhash

class CacheManager:
    def __init__(self, config):
        self.config = config
        self.file_path = pathlib.Path(config.getoption("--file")).expanduser()
        self.test_name = config.getoption("--test")
        self.cache_dir = self.get_cache_dir()

    def get_cache_dir(self):
        file_hash = xxhash.xxh64_hexdigest(self.file_path.read_bytes())
        cache_dir = pathlib.Path(f"/hps/nobackup/flicek/ensembl/production/datachecks/python_dc/{file_hash}")
        return cache_dir

    def setup_cache(self):
        if self.cache_dir.exists():
            results_file = self.cache_dir / "results.txt"
            cache_file = self.cache_dir / "cache.pkl"

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
        results_file = self.cache_dir / "results.txt"
        if results_file.exists():
            print("Loading previous test results:")
            print(results_file.read_text())
            pytest.exit("Previous test results loaded, exiting.")
        else:
            raise FileNotFoundError(f"No previous test results found for {self.file_path}")

    def handle_cache_post_run(self, terminalreporter):
        results_file = self.cache_dir / "results.txt"
        self.write_summary_to_file(results_file)
        self.save_cache(terminalreporter)
        self.cleanup_cache_if_all_passed(terminalreporter)

    def write_summary_to_file(self, results_file):
        custom_summary_plugin = self.config.pluginmanager.getplugin('custom_summary_plugin')
        if custom_summary_plugin:
            custom_summary_plugin.write_summary_to_file(results_file)

    def save_cache(self, terminalreporter):
        cache_file = self.cache_dir / "cache.pkl"
        last_failed = terminalreporter.stats.get('failed', {})
        last_failed_ids = {item.nodeid: True for item in last_failed}
        with cache_file.open("wb") as f:
            pickle.dump(last_failed_ids, f)

    def cleanup_cache_if_all_passed(self, terminalreporter):
        cache_file = self.cache_dir / "cache.pkl"
        if not terminalreporter.stats.get('failed', {}):
            if cache_file.exists():
                print(f"All tests passed. Deleting cache file: {cache_file}")
                cache_file.unlink()
