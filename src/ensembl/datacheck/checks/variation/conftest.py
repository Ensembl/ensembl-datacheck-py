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

import pytest


DEFAULT_MAX_RANDOM_REGIONS = "1000"


@pytest.fixture(scope="session")
def variation_params(params):
    """
    Variation-specific default parameters for source-file sampling checks.

    Args:
        params (dict): Parsed command-line params from the shared plugin.

    Returns:
        dict: User params merged over variation defaults.
    """
    resolved_params = {"max_random_regions": DEFAULT_MAX_RANDOM_REGIONS}
    resolved_params.update(params)
    return resolved_params
