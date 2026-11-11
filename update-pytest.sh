#!/usr/bin/env bash
# Rename the `clingo` Python package to $PACKAGE in the stubs, the tests, and
# the module names hard-coded in the Python bindings.
#
# This must be idempotent: rebase.sh runs it after every rebase.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
shopt -s nullglob

PACKAGE=clingo_funasp

FILES=(lib/python-api/tests/*.py lib/python-api/stubs/*.pyi)
sed -i \
    -e "s/from clingo import/from ${PACKAGE} import/g" \
    -e "s/\bclingo\./${PACKAGE}./g" \
    "${FILES[@]}"

# Bindings: the extension module name, module paths in strings such as
# "clingo.base" (submodule names, type names, imports) and docstrings.
# `#include "clingo.hh"` lines are C++ headers and must stay untouched.
SOURCES=(lib/python-api/src/*.cc lib/python-api/src/*.hh lib/python-api/src/*.h)
sed -i \
    -e "s/PYBIND11_MODULE(clingo,/PYBIND11_MODULE(${PACKAGE},/" \
    -e "s/import(\"clingo\")/import(\"${PACKAGE}\")/g" \
    -e "/^[[:space:]]*#[[:space:]]*include/!s/\bclingo\./${PACKAGE}./g" \
    "${SOURCES[@]}"
