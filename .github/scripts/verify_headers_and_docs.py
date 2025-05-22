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
import sys
import re

LICENSE_HEADER = [
    "# See the NOTICE file distributed with this work for additional information",
    "# regarding copyright ownership.",
    "#",
    "# Licensed under the Apache License, Version 2.0 (the \"License\");",
    "# you may not use this file except in compliance with the License.",
    "# You may obtain a copy of the License at",
    "#",
    "#     http://www.apache.org/licenses/LICENSE-2.0",
    "#",
    "# Unless required by applicable law or agreed to in writing, software",
    "# distributed under the License is distributed on an \"AS IS\" BASIS,",
    "# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "# See the License for the specific language governing permissions and",
    "# limitations under the License."
]

def check_license_header(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        header = [line.strip() for line in lines[:len(LICENSE_HEADER)]]
        return header == LICENSE_HEADER

def check_module_docstring(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        return bool(re.match(r'^\s*"""[\s\S]+?"""\s*', content))

def check_function_docstrings(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        functions = re.findall(r'\ndef\s+(\w+)\s*\(.*?\):', content)
        for fn in functions:
            pattern = rf'def\s+{fn}\s*\(.*?\):\s*\n\s*"""[\s\S]+?"""'
            if not re.search(pattern, content):
                return False
        return True

def main():
    failed = False

    for root, _, files in os.walk("."):
        for file in files:
            if not file.endswith(".py"):
                continue

            full_path = os.path.join(root, file)

            # 1. Check license header
            if not check_license_header(full_path):
                print(f"❌ Missing or incorrect license header: {full_path}")
                failed = True

            # 2. Checks for files in `checks/`
            if "/checks/" in full_path.replace("\\", "/"):
                if not check_module_docstring(full_path):
                    print(f"❌ Missing comprehensive module-level docstring: {full_path}")
                    failed = True
                if not check_function_docstrings(full_path):
                    print(f"❌ Missing function-level docstrings: {full_path}")
                    failed = True

            # 3. Checks for files in `functions/`
            if "/functions/" in full_path.replace("\\", "/"):
                if not check_function_docstrings(full_path):
                    print(f"❌ Missing function-level docstrings: {full_path}")
                    failed = True

    if failed:
        sys.exit(1)
    else:
        print("✅ All checks passed.")

if __name__ == "__main__":
    main()
