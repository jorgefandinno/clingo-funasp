# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This is **clingo 6**, a from-scratch reimplementation of the clingo 5 Answer Set
Programming (ASP) solver, part of the [Potassco](https://potassco.org/) project.
It builds a CLI application, a C/C++ library, and a Python module. The reference
solver engine (clasp) and other dependencies live in `third_party/` as git
submodules — run `git submodule update --init --recursive` after cloning.

## Build & Test

Two build conventions coexist:

- **README style** (single `build/` dir, what packagers use):
  ```sh
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
  cmake --build build --config Release
  ```
- **Makefile style** (preferred for development; uses clang + libc++, creates a
  `.venv`, and puts builds under `build/debug`, `build/release`, etc.):
  ```sh
  make debug        # configure + build debug into build/debug
  make test         # build debug, then run the full ctest suite
  make release      # release build + tests
  make web          # emscripten/WASM build (needs emsdk_env.sh)
  ```

Running tests:
- C++ tests use **Catch2** and are registered with ctest via
  `catch_discover_tests`. Run all: `make test`, or directly
  `ctest --test-dir build/debug`.
- Run a single C++ test binary: `./build/debug/bin/test_clingo-util` (one
  `test_clingo-<lib>` binary per library). Filter cases by Catch2 tag/name,
  e.g. `./build/debug/bin/test_clingo-util "[base]"`.
- Python tests use **pytest** (`testpaths = ["lib"]`); the bindings must be
  built first. `make stubs` regenerates `.pyi` stubs.

Python module only (no full app):
```sh
pipx run build .          # produces a wheel in dist/
pip install dist/clingo*.whl
```

Key CMake options (default ON unless noted): `CLINGO_BUILD_TESTS`,
`CLINGO_BUILD_APP`, `CLINGO_BUILD_PYTHON`, `CLINGO_BUILD_EXAMPLES`,
`CLINGO_BUILD_WEB` (OFF), `CLINGO_PROFILE` (OFF).

## Architecture

The C++ code lives under the `CppClingo` namespace. `lib/` is layered, roughly
following the ASP processing pipeline; each layer is its own CMake target
(`clingo-<name>`) with `include/`, `src/`, and `tests/` subdirs:

- **util** — generic data structures and helpers (no clingo-specific logic).
- **core** — fundamental types: symbols, numbers, strings.
- **input** — parser/AST for logic programs (uses `re2c` for lexing).
- **ground** — the grounder: instantiates rules over the Herbrand base.
- **output** — emits ground output (e.g. aspif) to the solver backend.
- **control** — orchestration layer tying grounding and solving together
  (`grounder.cc`, `solver.cc`, aggregates, theory, config); wraps clasp.

On top of the pipeline sit three API layers:

- **c-api** (`CppClingo::CAPI`) — the public, ABI-stable C API. `core.h` here
  holds `CLINGO_VERSION`, which drives the project version in CMake.
- **cxx-api** — idiomatic C++ wrapper over the C API (header-rich:
  `control.hh`, `ast.hh`, `solve.hh`, etc.).
- **python-api** (`PyClingo`) — pybind11 bindings; `stubs/` holds generated
  type stubs.

`app/main.cc` is the CLI entry point and is built purely against the C API
(`clingo/app.h`). `scripts/` contains code-generation and tooling (e.g.
`make gen` regenerates `lib/python-api/src/ast.cc` from `scripts/generate.py`;
`make compdb` builds `compile_commands.json`).

## Conventions

- See `STYLE.md` for the full C++ style guide. Highlights: C++20; CamelCase
  types (except STL-like), snake_case functions/vars, trailing `_` on private
  members; `const` placed after the type; prefer `auto var = expr` and brace
  initialization; explicit null/optional checks (`ptr != nullptr`,
  `opt.has_value()`); range algorithms (`std::ranges::sort`); Doxygen `//!`
  comments; `std::format` is not used.
- Formatting/linting is enforced by **pre-commit** (`make` does not run it):
  `clang-format` + `clang-tidy` (version 21, warnings-as-errors) for C/C++, and
  `isort` + `black` for Python. Run `pre-commit run --all-files` before
  committing.
- `DEVELOP.md` documents how to build a custom clang/libc++ toolchain, which the
  development `make` targets expect (they default to `clang-20`/`clang++-20`
  with `-stdlib=libc++` when available).
