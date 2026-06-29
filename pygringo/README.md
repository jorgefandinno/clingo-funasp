# pygringo

A standalone Python re-implementation of the core of clingo's grounder, ported
from the C++ `lib/ground` to the clingo Python AST API (`clingo.ast`). It reuses
the [`safety`](../safety) pilot for the safety check and for ordering body
literals into a groundable order.

`pygringo.ground` turns a non-ground program into a list of **variable-free**
`clingo.ast` statements, mirroring how `StmRule` maps to
`clingo.ast.StatementRule`.

## Usage

```python
from clingo import ast
from clingo.core import Library
from pygringo import ground

lib = Library()
stms = []
ast.parse_string(lib, "q(1). q(2). p(X) :- q(X).", stms.append)

for stm in ground(lib, stms):
    print(stm)
# q(1).
# q(2).
# p(1) :- q(1).
# p(2) :- q(2).
```

`ground(lib, statements) -> list[ast.Statement]`. The input statements are the
non-ground statements produced by `clingo.ast.parse_statement` /
`clingo.ast.parse_string`. Each statement is first normalised with
`clingo.ast.rewrite_statement` (unpooling, canonicalising arithmetic into
`m*X+n`, turning intervals into `X = lo..hi` comparisons) — the same precondition
the `safety` pilot assumes.

## How it works

The pipeline follows the C++ grounder at a high level:

1. **normalise** every statement (`rewrite_statement`);
2. **check safety** and obtain the body in groundable order
   (`safety.check_safety`);
3. **stratify** predicates into dependency components in evaluation order
   (`_depend`, strongly-connected components via Tarjan);
4. **instantiate** each component with a bottom-up fixpoint, joining body
   literals over an `AtomBase` (`_literal`, `_term`) and emitting ground rules;
5. ground the integrity **constraints** over the completed atom base.

Modules: `_term` (term evaluation / matching), `_literal` (body-literal
matchers), `_atombase` (derived atoms by signature), `_depend` (components),
`_ground` (pipeline).

## Scope and assumptions

Supported: facts, normal rules, integrity constraints, plain choice rules
(`{ ... }` without bounds or conditional elements), positive recursion,
stratified negation, comparisons, arithmetic and intervals.

Out of scope for this milestone (each raises `GroundError`): aggregates with
bounds or conditions, disjunctions, conditional literals, theory atoms,
`#minimize`/`#maximize` and weak constraints, externals, classical negation in
heads, and `#show`/`#project`/`#edge`/`#heuristic` statements and scripts. These
are the subject of later phases.

Other notes:

- Input is assumed normalised, exactly like the `safety` pilot. `ground` runs
  `rewrite_statement` for you; a rewrite failure (e.g. an unsafe rule) is
  reported as `GroundError`.
- The output is a correct but **unsimplified** ground program: matched
  comparisons/intervals are dropped, but true facts are *not* propagated out of
  rule bodies (clingo's grounder additionally simplifies). The set of answer sets
  is unchanged, which is what the tests check.
- Output is deterministic for a given input order (the atom base preserves
  insertion order).

## Tests

```sh
pytest pygringo/tests
mypy --strict --local-partial-types --allow-redefinition-new pygringo
```

Correctness is checked by **differential testing** against real clingo: for a
corpus of programs, pygringo's grounding is solved and its answer sets are
compared to those of `clingo.control.Control.ground()` + `solve()` on the same
input (`tests/util.py`). Unit tests cover term evaluation/matching
(`test_term.py`), component ordering (`test_depend.py`), and exact ground output
plus the `GroundError` boundary (`test_ground.py`).
