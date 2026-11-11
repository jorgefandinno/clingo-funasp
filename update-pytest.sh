#!/usr/bin/env bash
# Rename the `clingo` Python package to $PACKAGE in the stubs and tests.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
shopt -s nullglob

PACKAGE=clingo_funasp
FILES=(lib/python-api/tests/*.py lib/python-api/stubs/*.pyi)
sed -i \
    -e "s/from clingo import/from ${PACKAGE} import/g" \
    -e "s/\bclingo\./${PACKAGE}./g" \
    "${FILES[@]}"
