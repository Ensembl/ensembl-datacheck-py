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

def bb_bw_reader(file_path):
    """
    Provide a pyBigWig reader opened on a bigBed/bigWig file path.

    Args:
        file_path (str): The path to the bigBed/bigWig file.

    Returns:
        pyBigWig.pyBigWig: Open reader on success.

    Raises:
        Exception: Propagates import/open failures from pyBigWig.
    """
    import pyBigWig
    return pyBigWig.open(str(file_path))
