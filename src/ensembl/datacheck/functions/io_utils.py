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

import errno
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


def bb_bw_reader(target_file):
    """
    Provide a pyBigWig reader opened on a bigBed/bigWig file path.

    Args:
        target_file (str or pathlib.Path): The path to the bigBed/bigWig file.

    Returns:
        pyBigWig.pyBigWig: Open reader on success.

    Raises:
        Exception: Propagates import/open failures from pyBigWig.
    """
    import pyBigWig
    return pyBigWig.open(str(target_file))


def load_bigbed_info(target_file: Path | str) -> dict[str, Any]:
    """
    Load bigBed info from target file.

    This function requires the bigBedInfo executable.

    Args:
        target_file: Path to the target bigBed file.

    Returns:
        bigBed info dictionary.

    Raises:
        FileNotFoundError: If target file is not found.
        RuntimeError: If bigBedInfo executable not found,
            or if bigBedInfo fails with an unexpected error.
        ValueError: If a Boolean string value cannot be converted to a bool object,
            or if the target file is not in bigBed format.
    """

    def digit_grouped_integer(value):
        return int(value.replace(",", ""))

    def str_to_bool(value):
        str_bool_map = {"yes": True, "no": False}
        try:
            return str_bool_map[value]
        except KeyError as exc:
            raise ValueError(f"failed to convert value {value!r} to bool") from exc

    field_converters = {
        "version": int,
        "fieldCount": int,
        "hasHeaderExtension": str_to_bool,
        "isCompressed": str_to_bool,
        "isSwapped": bool,
        "extraIndexCount": int,
        "itemCount": digit_grouped_integer,
        "primaryDataSize": digit_grouped_integer,
        "primaryIndexSize": digit_grouped_integer,
        "zoomLevels": int,
        "chromCount": int,
        "basesCovered": digit_grouped_integer,
        "meanDepth (of bases covered)": float,
        "minDepth": float,
        "maxDepth": float,
        "std of depth": float,
    }

    bigbed_info_exe = shutil.which("bigBedInfo")

    if not bigbed_info_exe:
        raise RuntimeError("bigBedInfo executable not found")

    cmd_args = [bigbed_info_exe, str(target_file)]
    process = subprocess.run(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)

    if process.returncode != 0:
        err_msg = process.stderr.strip()
        if err_msg == f"Couldn't open {target_file}":
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), target_file)
        if err_msg == f"{target_file} is not a big bed file":
            raise ValueError(err_msg)
        raise RuntimeError(err_msg)

    lines = process.stdout.splitlines()

    bigbed_info = {}
    for line in lines:
        field_name, field_value = line.split(":", maxsplit=1)
        field_converter = field_converters[field_name]
        bigbed_info[field_name] = field_converter(field_value.strip())

    return bigbed_info


def vcf_reader(target_file):
    """
    Provide a cyvcf2 VCF reader opened on a VCF file path.

    Args:
        target_file (str or pathlib.Path): The path to the VCF file.

    Returns:
        cyvcf2.cyvcf2.VCF: Open reader on success.

    Raises:
        Exception: Propagates import/open failures from cyvcf2.
    """
    from cyvcf2 import VCF
    return VCF(str(target_file))
