# CloudShell package repo template

[![Build status](https://github.com/QualiSystems/cloudshell-package-repo-template/workflows/CI/badge.svg?branch=master)](https://github.com/QualiSystems/cloudshell-package-repo-template/actions?query=branch%3Amaster)
[![codecov](https://codecov.io/gh/QualiSystems/cloudshell-package-repo-template/branch/master/graph/badge.svg)](https://codecov.io/gh/QualiSystems/cloudshell-package-repo-template)
[![PyPI version](https://badge.fury.io/py/cloudshell-template.svg)](https://badge.fury.io/py/cloudshell-template)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/python/black)

Use this template to create new shell packages.

## Description of services
### tox
[tox](https://pypi.org/project/tox/) is an open source tool we use to run tests in multiple virtual environments.  
* To run all tests described in tox.ini, just run `tox`.
* To run a particular env use `tox -e env_name`.

### pre-commit
[pre-commit](https://pypi.org/project/pre-commit/) is an open source library we use to manage pre-commit hooks.
* Run all code linters with a command `pre-commit run --all-files`. 
* Add git hook with command `pre-commit install`.
* To update versions of pre-commit hooks in config file run `pre-commit autoupdate`

We use these hooks:
* **isort** sorts imports (config in tox.ini)
* **black** reformats code to one style (config in pyproject.toml)
* **flake8** checks code style (config in tox.ini). We use these plugins: 
  * `flake8-docstring` to check docstrings
  * `flake8-builtins` to avoid using builtins as variable names
  * `flake8-comprehensions` to check list/dict comprehensions
  * `flake8-print` to ensure we don't leave prints in the code 
  * `flake8-eradicate` to ensure we don't leave commented lines in the code

## Installation

### tox.ini
* Set the `package-name` var regarding your package.
* Set the python version in envlist.

### .travis.yml
* Set the python version regarding tox.ini.

### pyproject.toml
* Set the python version for black.

### setup.py
* Set a name and description for the package.
* Set the python version of the shell.

### README.md
* Update links for build, coverage etc.
* Add the line to README  
   We use tox and pre-commit for testing. [Services description](https://github.com/QualiSystems/cloudshell-package-repo-template#description-of-services)
