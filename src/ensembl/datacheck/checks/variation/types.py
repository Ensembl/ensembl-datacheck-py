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
variation/types.py

Type definitions for variation-specific datachecks.
"""

import sys

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

if sys.version_info >= (3, 13):
    from typing import ReadOnly
else:
    from typing_extensions import ReadOnly

from typing import TypedDict


# Type definitions
class Csq_subfield_spec(TypedDict):
    """
    Dict defining a CSQ subfield specification.
        * canbe_empty: Whether the subfield is allowed to have no data for (some) records.
        * species: Species for which the subfield is expected to exist. 'all' if it is expected to exist for all species.
    """
    canbe_empty: NotRequired[ReadOnly[bool]]
    """Whether the subfield is allowed to have no data for (some) records."""
    species: ReadOnly[str]
    """Species for which the subfield is expected to exist. 'all' if it is expected to exist for all species."""
