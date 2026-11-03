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
Shared fixtures for the staging site checks.
"""

import pytest


@pytest.fixture(scope="session")
def stage_site_resource(automation_resource_config):
    """
    Return the staging site base URI from the automation config.
    """
    resource = automation_resource_config.get("stage_site")
    if not resource:
        pytest.skip("Resource 'stage_site' not found in config file")

    if resource.get("ignore") == "True":
        pytest.skip("Skipped 'stage_site' check as ignore=True in config")

    uri = resource.get("uri")
    if not uri:
        pytest.skip("Stage site URI missing for 'stage_site'")

    return uri
