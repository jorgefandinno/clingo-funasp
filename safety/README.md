# safety

A standalone Python re-implementation of clingo's rule-safety check, ported from
the C++ `lib/input/src/rewrite/safety.cc` to the clingo Python AST API
(`clingo.ast`).

A variable is *unsafe* if grounding cannot bind it to a value. `check_safety`
decides whether a statement is safe and, when it is, returns the statement with
body/condition literals reordered into a **groundable order** (equalities
flipped so the binding side is on the left).

## Usage

```python
from clingo import ast
from clingo.core import Library
from safety import check_safety

lib = Library()
stm = ast.parse_statement(lib, "p(X) :- r(Y), X = Y, q(X).")
result = check_safety(lib, stm)

result.safe              # True
str(result.statement)    # "p(X) :- r(Y); q(X); X=Y."  (reordered)
result.unsafe_variables  # []  (names of unsafe variables when not safe)
```

`check_safety(lib, stm) -> SafetyResult` where `SafetyResult` has `.safe`,
`.statement` (reordered when safe, original otherwise), and `.unsafe_variables`
(sorted, de-duplicated).

## Input assumptions

The input statement is assumed **normalised** (unpooled), matching the
precondition of the C++ code. Non-normalised constructs raise `SafetyError`:
multi-guard comparisons (`X = Y = Z`), set aggregates (`a { ... } b`), and
`#minimize`/`#maximize` statements. Arithmetic that should bind a variable must
be in the canonical linear form `m*X+n` (e.g. write `q(1*X+1)`, not `q(X+1)`).

> **Note on `ast.rewrite_statement`.** clingo's own `rewrite_statement` produces
> normalised statements, but it *also performs the safety check itself*: it
> raises on unsafe input and eliminates/pre-orders equalities. It therefore
> cannot be used to feed unsafe or out-of-order statements to this checker — use
> `ast.parse_statement` with already-normalised program text instead.

## Layout

- `_analyze.py` — variable collection with global/local scope gating
  (`select_variables`), linear-term recognition (`check_linear`), and the
  `is_provided` predicate. Ports `analyze.cc` / `visit_variables.cc`.
- `_safety.py` — the algorithm: provide/depend analysis (`GetDep`), per-literal
  dependency nodes (`MakeNode`), the groundable-ordering fixpoint
  (`prepare_lits`), equality `flip`, and the global/local checks. Ports
  `safety.cc`.

## Running the tests

The compiled `clingo` module lives in the build tree, so put it (and this repo
root) on `PYTHONPATH`:

```sh
make debug   # if not already built; module also exists under build/bin/python/Release
PYTHONPATH=build/bin/python/Release:. python -m pytest safety/tests/test_safety.py -v
```
