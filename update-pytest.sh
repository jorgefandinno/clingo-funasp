#!/usr/bin/env bash
# Rename the `clingo` Python package to $PACKAGE in the stubs, the tests, and
# the module names hard-coded in the Python bindings.
#
# This must be idempotent: rebase.sh runs it after every rebase.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
shopt -s nullglob globstar

PACKAGE=clingo_funasp

FILES=(lib/python-api/tests/**/*.py lib/python-api/stubs/**/*.pyi)
sed -i \
    -e "s/from clingo import/from ${PACKAGE} import/g" \
    -e "s/\bclingo\./${PACKAGE}./g" \
    "${FILES[@]}"

# Bindings: the extension module name, module paths in strings such as
# "clingo.base" (submodule names, type names, imports) and docstrings.
# - `#include "clingo.hh"` lines are C++ headers and must stay untouched.
# - Both the pybind11 (PYBIND11_MODULE, py::module::import) and the Python C
#   API (PyInit_clingo, "clingo" literals) spellings are handled.
# - `clingo.name(` is a method call on a C++ variable named `clingo`
#   (e.g. `clingo.get()` in script.cc), not a module path.
SOURCES=(lib/python-api/src/*.cc lib/python-api/src/*.hh lib/python-api/src/*.h)
perl -pi -e "
    s/PYBIND11_MODULE\(clingo,/PYBIND11_MODULE(${PACKAGE},/;
    s/import\(\"clingo\"\)/import(\"${PACKAGE}\")/g;
    s/\bPyInit_clingo\(\)/PyInit_${PACKAGE}()/;
    s/\"clingo\"/\"${PACKAGE}\"/g;
    s/(?<![\w.])clingo\.(?!\w+\()/${PACKAGE}./g unless /^\s*#\s*include/;
" "${SOURCES[@]}"
