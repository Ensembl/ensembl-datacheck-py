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

* TODO


Creating a new plugin
------------

Define the tests in a file within the directory tests (ex tests/fasta.py). Use comment strings. ex::

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
Then a pytest must be written for each test::

    def test_check_line_length(file_path, max_length=80):
        """Check for lines longer than max_length and return warnings."""
        line_warnings = check_line_length(file_path, max_length)
        if line_warnings:
            for warning in line_warnings:
                warnings.warn(warning, UserWarning)


The functions are to be written independently and stored in src/ensembl/datacheck_functions. These methods are to be as
generic as reasonable and used by as many tests as possible. The methods are stored in files based on function:

content_checks.py : Data checks within a text file

db_checks.py : Checking mysql databases (not implemented yet)

file_checks.py : System level checks of files

utils.py : Other checks or special commands.

Your test will be called, by calling the file name, without extensions, after --test=. ex::

    ensembl-datacheck --test=fasta --file=~/TEST/2pass.fasta

Installation
------------

Download the repo and install it (virtual enviroment recomended)::

    git clone (insert repo here)
    pip install ensembl-datacheck-py


Usage
-----

To run a program you can call it like::

    ensembl-datacheck --test=fasta --file=~/TEST/2pass.fasta


To Do
------------
- More tests!
- Confluence Page
- Publish it
- Introduce tests for tests


Contributing
------------
Contributions are very welcome.

License
-------

Distributed under the terms of the `Apache Software License 2.0`_ license, "ensembl-datacheck-py" is free and open source software


Issues
------

If you encounter any problems, please `file an issue`_ along with a detailed description.

.. _`Cookiecutter`: https://github.com/audreyr/cookiecutter
.. _`@hackebrot`: https://github.com/hackebrot
.. _`MIT`: https://opensource.org/licenses/MIT
.. _`BSD-3`: https://opensource.org/licenses/BSD-3-Clause
.. _`GNU GPL v3.0`: https://www.gnu.org/licenses/gpl-3.0.txt
.. _`Apache Software License 2.0`: https://www.apache.org/licenses/LICENSE-2.0
.. _`cookiecutter-pytest-plugin`: https://github.com/pytest-dev/cookiecutter-pytest-plugin
.. _`file an issue`: https://github.com/Ensembl/ensembl-datacheck-py/issues
.. _`pytest`: https://github.com/pytest-dev/pytest
.. _`tox`: https://tox.readthedocs.io/en/latest/
.. _`pip`: https://pypi.org/project/pip/
.. _`PyPI`: https://pypi.org/project
