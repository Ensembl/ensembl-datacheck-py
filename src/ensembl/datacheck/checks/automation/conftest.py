import pytest
import pathlib
import json
from pymongo import MongoClient

@pytest.fixture(scope="session")
def automation_resource_config(request):
    """
    Pytest fixture to load automation resource configuration from the database.
    Args:
        request (pytest.FixtureRequest): The fixture request object.

    """
    config = request.config.getoption("--automation_resource_config")
    if not config:
        raise ValueError("Please provide the path to the automation resource config file using --automation_resource_config")

    config_path = pathlib.Path(config)

    if not config_path.is_file():
        raise ValueError(f"Config file not found at {config_path}")
    # read the json file and return the content as a dictionary
    return json.loads(config_path.read_text())


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
    client = MongoClient(mongo_uri)
    yield client

    # Cleanup
    client.close()

