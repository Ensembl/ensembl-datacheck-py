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
Check that all required metakeys from the metadata database are present in the core database
and have non-empty values.
Checks performed:
    - Fixture For Automation Resource Config: Loads automation resource configuration from
      a JSON file specified via command-line option, or from the bundled
      resource_config.json by default.
"""

import pytest
import pathlib
import json
import os
from copy import deepcopy
from ensembl.datacheck.functions.utils import get_genomes_from_metadata_db

from ensembl.production.metadata.api.adaptors.genome import GenomeAdaptor

AUTOMATION_ENV_PREFIX = "ENSEMBL_DATACHECK_"
AUTOMATION_CONFIG_FIELDS = (
    "expected_files",
    "base_path",
    "subfolder",
    "ignore",
    "type",
    "uri",
)
PARAM_ALIASES = {
    "base_dir": "blast_database_release.base_path",
    "blast_database_release_base_dir": "blast_database_release.base_path",
}


def _resolve_automation_resource_config_path(config):
    """Resolve optional automation resource config override path."""
    bundled_config_path = pathlib.Path(__file__).with_name("resource_config.json")
    if not config:
        return None

    config_path = pathlib.Path(config).expanduser()
    if config_path.is_file():
        return config_path

    # Support historical docs that passed src/.../resource_config.json from any cwd.
    if config_path.name == "resource_config.json":
        return bundled_config_path

    return config_path


def _bundled_automation_resource_config_path():
    """Return the packaged automation resource config path."""
    return pathlib.Path(__file__).with_name("resource_config.json")


def _load_json_config(config_path):
    """Load a JSON config file into a dictionary."""
    if not config_path.is_file():
        raise ValueError(f"Config file not found at {config_path}")
    return json.loads(config_path.read_text())


def _deep_merge_config(base_config, override_config):
    """Merge override_config onto base_config recursively."""
    merged_config = deepcopy(base_config)
    for key, value in override_config.items():
        if (
            isinstance(value, dict)
            and isinstance(merged_config.get(key), dict)
        ):
            merged_config[key] = _deep_merge_config(merged_config[key], value)
        else:
            merged_config[key] = deepcopy(value)
    return merged_config


def _parse_key_value_params(raw_params):
    """Parse --params values into key-value pairs."""
    parsed_params = {}
    for raw_param in raw_params or []:
        for param in raw_param.split(","):
            param = param.strip()
            if not param or "=" not in param:
                continue
            key, value = param.split("=", 1)
            parsed_params[key.strip()] = _parse_config_value(value.strip())
    return parsed_params


def _parse_config_value(value):
    """Parse structured config values where unambiguous."""
    if value.startswith(("[", "{")):
        return json.loads(value)
    return value


def _normalise_cli_override_key(key):
    """Map CLI override aliases to dotted config paths."""
    return PARAM_ALIASES.get(key, key)


def _normalise_env_override_key(env_name):
    """Convert an automation environment variable name to a dotted config path."""
    if not env_name.startswith(AUTOMATION_ENV_PREFIX):
        return None

    raw_name = env_name.removeprefix(AUTOMATION_ENV_PREFIX)
    if "__" in raw_name:
        return raw_name.lower().replace("__", ".")

    for field_name in AUTOMATION_CONFIG_FIELDS:
        env_field_name = field_name.upper()
        suffix = f"_{env_field_name}"
        if raw_name.endswith(suffix):
            resource_name = raw_name[:-len(suffix)].lower()
            return f"{resource_name}.{field_name}"

    return None


def _set_config_path(config, dotted_path, value):
    """Set a dotted config path on config, creating nested dictionaries."""
    path_parts = dotted_path.split(".")
    assert len(path_parts) >= 2, (
        f"Automation config override '{dotted_path}' must use dotted syntax, "
        "for example blast_database_files.base_path=/path"
    )

    target = config
    for path_part in path_parts[:-1]:
        target = target.setdefault(path_part, {})
        assert isinstance(target, dict), (
            f"Automation config override '{dotted_path}' conflicts with "
            f"non-object config value at '{path_part}'"
        )
    config_field = path_parts[-1]
    target[config_field] = value


def _apply_config_overrides(config, overrides):
    """Apply dotted-path overrides to config."""
    resolved_config = deepcopy(config)
    for key, value in overrides.items():
        _set_config_path(
            config=resolved_config,
            dotted_path=_normalise_cli_override_key(key),
            value=value,
        )
    return resolved_config


def _automation_environment_overrides(environ):
    """Return automation config overrides from environment variables."""
    overrides = {}
    for env_name, env_value in environ.items():
        override_key = _normalise_env_override_key(env_name)
        if override_key:
            overrides[override_key] = _parse_config_value(env_value)
    return overrides


def _apply_alt_base_paths(config):
    """Mark resources with a subfolder as using alt path ordering (release before subfolder)."""
    resolved_config = deepcopy(config)
    for resource_config in resolved_config.values():
        if not isinstance(resource_config, dict):
            continue
        if resource_config.get("subfolder"):
            resource_config["use_alt_base_path"] = True
    return resolved_config


def _build_automation_resource_config(
    config_path,
    environ,
    raw_params,
    use_alt=False,
):
    """Build automation config with repo < JSON < env < CLI precedence."""
    bundled_config = _load_json_config(_bundled_automation_resource_config_path())
    specified_config = {}

    if config_path:
        resolved_config_path = _resolve_automation_resource_config_path(config_path)
        specified_config = _load_json_config(resolved_config_path)

    resource_config = _deep_merge_config(bundled_config, specified_config)
    resource_config = _apply_config_overrides(
        resource_config,
        _automation_environment_overrides(environ),
    )
    if use_alt:
        resource_config = _apply_alt_base_paths(resource_config)
    return _apply_config_overrides(
        resource_config,
        _parse_key_value_params(raw_params),
    )


@pytest.fixture(scope="session")
def user_cli(request):
    """
    Fixture for user CLI configuration.
    """
    return request.config


def pytest_generate_tests(metafunc):
    """
    Pytest hook to generate test parameters based on command-line options.

    Args:
        metafunc: The Metafunc object for the test function being collected.

    Returns: None. This function modifies the test parameters in place.

    """
    test = metafunc.config.getoption("test")
    # Only generate parameters per genome uuid for tests name that start with "automation"
    if test.startswith("automation") and "genomes" in metafunc.fixturenames:
        db_url = metafunc.config.getoption("database")
        taxonomy_url = metafunc.config.getoption("taxonomy_database")
        release_name = metafunc.config.getoption("release_name")
        genome_uuids = metafunc.config.getoption("genome_uuid")

        genomes_iter = get_genomes_from_metadata_db(
            db_url=db_url,
            release_name=release_name,
            genome_uuids=genome_uuids)  # Fetch all at once since we need to group them in memory

        metafunc.parametrize("genomes", list(genomes_iter), scope="session")


@pytest.fixture(scope="session")
def automation_resource_config(request):
    """
    Pytest fixture to load automation resource configuration.
    Args:
        request (pytest.FixtureRequest): The fixture request object.

    """
    return _build_automation_resource_config(
        config_path=request.config.getoption("--automation_resource_config"),
        environ=os.environ,
        raw_params=request.config.getoption("--params"),
        use_alt=request.config.getoption("use_alt"),
    )


@pytest.fixture(scope="session")
def track_api_resource(request, automation_resource_config):
    """
    Return a Track API base URI for the parametrized resource type.
    """
    resource_type = getattr(request, "param", None)
    if not resource_type:
        raise ValueError("Please parametrize the track_api_resource fixture with a resource type")

    resource = automation_resource_config.get(resource_type)
    if not resource:
        pytest.skip(f"Resource '{resource_type}' not found in config file")

    if resource.get("ignore") == "True":
        pytest.skip(f"Skipped '{resource_type}' check as ignore=True in config")

    uri = resource.get("uri")
    if not uri:
        pytest.skip(f"Track API URI missing for '{resource_type}'")

    return uri


@pytest.fixture(scope="session")
def mongo_client(request, automation_resource_config):
    """
    Returns a MongoClient for a specific resource type.
    The resource type is passed dynamically via request.param from the test.
    """
    resource_type = getattr(request, "param", None)
    if not resource_type:
        raise ValueError("Please parametrize the mongo_client fixture with a resource type")

    # Get resource config
    resource = automation_resource_config.get(resource_type)
    if not resource:
        pytest.skip(f"Resource '{resource_type}' not found in config file")

    if resource.get("ignore") == "True":
        pytest.skip(f"Skipped '{resource_type}' check as ignore=True in config")

    mongo_uri = resource.get("uri")
    if not mongo_uri:
        pytest.skip(f"Mongo URI missing for '{resource_type}'")

    # Create client and yield to test
    from pymongo import MongoClient

    client = MongoClient(mongo_uri)
    yield client

    # Cleanup
    client.close()
