===========================
ensembl-datacheck-py
===========================

.. image:: https://img.shields.io/pypi/v/ensembl-datacheck-py.svg
    :target: https://pypi.org/project/ensembl-datacheck-py
    :alt: PyPI version

.. image:: https://img.shields.io/pypi/pyversions/ensembl-datacheck-py.svg
    :target: https://pypi.org/project/ensembl-datacheck-py
    :alt: Python versions

.. image:: https://github.com/Ensembl/ensembl-datacheck-py/actions/workflows/main.yml/badge.svg
    :target: https://github.com/Ensembl/ensembl-datacheck-py/actions/workflows/main.yml
    :alt: See Build Status on GitHub Actions

A genomics data checking plugin

----


Features
--------

* File-based and database-based datachecks
* Generic and domain-specific checks under ``src/ensembl/datacheck/checks/``
* Optional secondary input files for comparison checks
* Optional JSON reporting and result caching


Creating checks
---------------

Define checks in a file within ``src/ensembl/datacheck/checks/`` (for example ``src/ensembl/datacheck/checks/fasta.py`` or ``src/ensembl/datacheck/checks/variation/bigbed.py``). Use module docstrings. For example::

    """
    fasta.py

    This tests for proper formatting of a fasta file. See: https://zhanggroup.org/FASTA/
    The tests are:
    File is a text file
    Line length is under 80 char (warning only)
    Only has allowed characters
    Print allowed type
    Ensure the file ends properly
    """
Then write a ``check_*`` function for each datacheck::

    def check_line_length(target_file, max_length=80):
        """Check for lines longer than max_length and return warnings."""
        line_warnings = check_line_length(target_file, max_length)
        if line_warnings:
            for warning in line_warnings:
                warnings.warn(warning, UserWarning)


Shared helper functions should be written independently and stored in ``src/ensembl/datacheck/functions``. These methods are to be as
generic as reasonable and used by as many tests as possible. The methods are stored in files based on function:

content_checks.py : Data checks within a text file

db_checks.py : Checking mysql databases (not implemented yet)

file_checks.py : System level checks of files

io_utils.py : File readers and related IO helpers

utils.py : Other checks or special commands.

Checks are called by module name, without extensions, after ``--test=``. For example::

    ensembl-datacheck --test=fasta --file=~/TEST/2pass.fasta

Nested modules can also be targeted directly. For example::

    ensembl-datacheck --test=variation/bigbed --target-file=~/TEST/example.bb --source-file=~/TEST/example.vcf.gz

Installation
------------

Download the repo and install it (virtual environment recommended)::

    git clone https://github.com/Ensembl/ensembl-datacheck-py.git
    cd ensembl-datacheck-py
    python -m pip install -e .


Usage
-----

To run a program you can call it like::

    ensembl-datacheck --test=fasta --file=~/TEST/2pass.fasta

To run a variation-specific check with a secondary source file::

    ensembl-datacheck --test=variation/bigbed --target-file=~/TEST/example.bb --source-file=~/TEST/example.vcf.gz

``--file`` and ``--target-file`` are CLI aliases for the primary file under test.


Contributing
------------
Contributions are very welcome.

License
-------

Distributed under the terms of the `Apache Software License 2.0`_ license, "ensembl-datacheck-py" is free and open source software


Issues
------

If you encounter any problems, please `file an issue`_ along with a detailed description.

.. _`Apache Software License 2.0`: https://www.apache.org/licenses/LICENSE-2.0
.. _`file an issue`: https://github.com/Ensembl/ensembl-datacheck-py/issues
