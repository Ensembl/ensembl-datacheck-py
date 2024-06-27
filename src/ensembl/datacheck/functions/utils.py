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


class EnsemblDatacheckWarning(UserWarning):
    """
    Custom warning class for Ensembl data checks.

    Attributes:
        message (str): The warning message.
        file_name (str): The name of the file where the warning originated.
        function_name (str): The name of the function where the warning originated.
    """

    def __init__(self, message, file_name, function_name):
        """
        Initializes the EnsemblDatacheckWarning with the given message, file name, and function name.

        Args:
            message (str): The warning message.
            file_name (str): The name of the file where the warning originated.
            function_name (str): The name of the function where the warning originated.
        """
        self.message = message
        self.file_name = file_name
        self.function_name = function_name

    def __str__(self):
        """
        Returns a formatted string representation of the warning.

        Returns:
            str: Formatted warning message.
        """
        return f"Warning::{self.file_name}::{self.function_name}: {self.message}"
