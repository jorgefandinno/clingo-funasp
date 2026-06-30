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
# p(1).
# p(2).
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
3. group predicates into dependency **components** in evaluation order
   (`_depend`, strongly-connected components via Tarjan; negative cycles are just
   one component);
4. per component, run a **domain** fixpoint (possible atoms, ignoring negation)
   then a **fact** fixpoint (atoms derived by a trivially-true body), over an
   `AtomBase` (`_literal`, `_term`);
5. **emit** the ground program, simplifying each body literal from the atom
   states, then ground the integrity **constraints**.

The two fixpoints use **semi-naive evaluation** (the C++ `GenerationCounts`):
each relation tracks old/new/all *generations*, and a recursive rule is matched
as delta rules so that, in each generation, one recursive literal ranges over the
freshly-derived *new* atoms while the others range over *old*/*all* — every new
combination is generated exactly once instead of re-scanning the whole relation
each pass.

### Negation

Following `lib/ground`'s `NonFactMatcher` / `StateAtom`, a negative literal never
binds variables and never restricts the domain. The atom base distinguishes
*facts* (definitely true) from merely *possible* atoms, and at emit time a
negative literal `not c` is:

- **dropped** if `c` is impossible (trivially true),
- used to **delete** the rule if `c` is a fact (body false),
- **kept** for the solver if `c` is possibly true.

This makes both **stratified and non-stratified negation** (recursion through
negation, e.g. `p :- not q. q :- not p.`) correct.

Modules: `_term` (term evaluation / matching), `_literal` (body-literal
matchers), `_atombase` (atom states by signature), `_depend` (components),
`_ground` (pipeline).

## Scope and assumptions

Supported: facts, normal rules, integrity constraints, choice rules (including
bounds and conditional elements, e.g. `1 { p(X) : q(X) } 2`), **body
aggregates** (`#count`/`#sum`/`#sump`/`#min`/`#max` with guards and conditional
elements, positive or negated), positive recursion, stratified **and
non-stratified** negation, comparisons, arithmetic and intervals.

Aggregates are emitted *ground* for the solver to evaluate: their elements and
conditions are instantiated over the domain, mirroring how choice rules are
handled. `clingo.ast.rewrite_statement` (run by `ground`) normalises every
aggregate first — choice rules become `#count` head aggregates and double bounds
become `lo <= … <= hi` — and the `safety` pilot orders the body and each
element's condition, so the grounder works against a single normalised shape.

Out of scope for this milestone (each raises `GroundError`): **assignment
aggregates** whose variable escapes (`N = #count{…}`, `… = S`), **recursion
through an aggregate** (an element-condition predicate in the rule's own
component), head `#sum`/`#min`/`#max` aggregates, disjunctions, conditional
literals, theory atoms, `#minimize`/`#maximize` and weak constraints, externals,
classical negation in heads, and `#show`/`#project`/`#edge`/`#heuristic`
statements and scripts. These are the subject of later phases.

Other notes:

- Input is assumed normalised, exactly like the `safety` pilot. `ground` runs
  `rewrite_statement` for you; a rewrite failure (e.g. an unsafe rule) is
  reported as `GroundError`.
- The output is simplified from the atom states: positive facts and impossible
  negative literals are dropped, dead rules are removed, and a rule whose body
  becomes trivially true is emitted as a fact. The set of answer sets matches
  clingo's, which is what the tests check.
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
input (`tests/util.py`), including non-stratified negation. Unit tests cover term
evaluation/matching (`test_term.py`), the atom base / states (`test_atombase.py`),
component ordering (`test_depend.py`), and exact ground output plus the
`GroundError` boundary (`test_ground.py`).
