Plan how to create a python module that checks the safety of a Statement replicating the code `safety.cc`. The module should use the python API for clingo (
https://docs.potassco.org/clingo-preview/python-api/clingo.html). For example, `StmRule` is should be mapped to `clingo.ast.StatementRule` (https://docs.potassco.org/clingo-preview/python-api/clingo/ast.html#StatementRule).

---

## Request

Plan how to create a python module that replicates the functionality in `lib/ground`. The module should use the python API for clingo (https://docs.potassco.org/clingo-preview/python-api/clingo.html) to represent objects. For example, `StmRule` is should be mapped to `clingo.ast.StatementRule` (https://docs.potassco.org/clingo-preview/python-api/clingo/ast.html#StatementRule).
- Create a folder named `pygringo` and put all the code you create there.
- We already ported `safety.cc` as a pilot and you put the code in `safety`. Reuse this code.
- Add tests that check the code is correct.
- Type all functions arguments. Check with `mypy --strict --local-partial-types --allow-redefinition-new`.


## Answer

Done. Here's what I built.

pygringo — a Python port of the core grounder

A standalone package under pygringo/ that grounds non-ground programs using the clingo Python AST API, reusing the safety pilot. ground(lib, statements) -> list[ast.Statement] returns variable-free clingo.ast rules/facts.

Modules:
- _term.py — term eval_term / match_term (arithmetic, intervals, functions, tuples, linear inversion) + atom_signature.
- _atombase.py — derived atoms indexed by signature, insertion-ordered for deterministic output.
- _depend.py — predicate dependency SCCs via iterative Tarjan, in evaluation order; rejects recursion through negation.
- _literal.py — body-literal match generators (symbolic ±, comparisons, intervals, booleans) + the backtracking match_body join.
- _ground.py — the pipeline: normalise (rewrite_statement) → safety + groundable ordering (safety.check_safety) → stratify → component-wise bottom-up fixpoint → emit; constraints grounded last.
- __init__.py, README.md, _error.py.

Reuse of safety: check_safety (safety + body reordering = the matcher's join order), plus select_variables/check_linear/is_provided.

Scope (this milestone): facts, normal rules, constraints, plain choice ({...}), positive recursion, stratified negation, comparisons, arithmetic, intervals. Aggregates with bounds/conditions, disjunction, conditional literals, theory, optimize/weak, externals → GroundError.

Tests (pygringo/tests/): a differential harness comparing pygringo's grounding against real clingo's ground()+solve() answer sets over a 20-program corpus, plus exact-output, term, dependency, and GroundError-boundary unit tests.

Verification — all green:

pytest pygringo/tests                                           45 passed
mypy --strict --local-partial-types --allow-redefinition-new pygringo   clean
pytest safety/tests        33 passed   (mypy strict: clean)

One change outside pygringo

safety/_analyze.py: check_linear crashed on the interval operator (raw value 9, outside the BinaryOperator enum) because it read operator_type unguarded — this blocked every program with an interval. I added a small _binary_operator helper that returns None for intervals. It's the only net change in safety/ (the 33 safety tests still pass).

Two things worth flagging for the next phase:
- Output is correct but unsimplified — matched comparisons/intervals are dropped, but true facts aren't propagated out of bodies the way clingo's grounder does (answer sets are identical, which is what the tests assert).
- Choice rules round-trip through clingo's #count-as-choice representation; bounded/conditional aggregates were deliberately deferred as they need the full aggregate machinery.


---

## Request

Incorporate support for non-stratified negation in `pygringo` using the code in `lib/ground` as guide.

## Answer

What changed

Following lib/ground's NonFactMatcher / StateAtom design, negation is now gated on fact-vs-derived state rather than mere presence, which both adds recursion-through-negation support and fixes a latent bug.

- _atombase.py — atoms now carry state: a possible (domain) set plus a facts subset (add, add_fact, is_possible, is_fact), mirroring StateAtom { fact, derived, unknown }.
- _depend.py — no longer rejects negative cycles; they simply form one component (the negative edge flag is gone).
- _literal.py — the negative-literal matcher is now pure enumeration (bind-check + yield); semantic decisions moved to the emitter.
- _ground.py — restructured into three phases per component, in dependency order, which avoids the fact-ordering hazard:
  a. domain fixpoint — possible atoms, ignoring negation (negatives don't bind or restrict the domain);
  b. fact fixpoint — atoms derived by a trivially-true normal-rule body become facts;
  c. emit — simplify each body literal from final atom states: positive fact → drop; negated fact → delete rule; negated impossible → drop (trivially true); otherwise keep for the solver. Node ordering is now first-seen (deterministic output regardless of hash seed).
- README updated; new tests/test_atombase.py; differential corpus extended with non-stratified cases.

Behaviour

The previously-confirmed bug is fixed — {a}. b :- not a. now yields {a},{b} — and genuine non-stratified programs work: p :- not q. q :- not p. → {p},{q}; p :- not p. → no answer set. Output is also now properly simplified (facts propagate, dead rules removed): q(1). q(2). p(X):-q(X). grounds to q(1). q(2). p(1). p(2)..

Verification — all green

pytest pygringo/tests            58 passed  (PYTHONHASHSEED=random)
mypy --strict --local-partial-types --allow-redefinition-new pygringo   clean
pytest safety/tests              33 passed  (no regression; mypy clean)
isort --profile black / black    clean

Primary correctness is still the differential oracle: every program — stratified and non-stratified — grounds to a program whose clingo answer sets exactly match clingo's own ground()+solve().

One follow-up worth noting: double negation (not not a) is handled conservatively (kept, never proved fact-true), which is sound but less simplified — a natural next refinement alongside semi-naive generations.

---

Incorporate support for aggregtes in `pygringo` using the code in `lib/ground` as guide.
