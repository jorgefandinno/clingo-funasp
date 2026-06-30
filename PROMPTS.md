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

## Request

Implement semi-naive generations.

## Answer

What I built

The two grounding fixpoints (domain and facts) now use semi-naive evaluation with generation tracking, mirroring lib/ground's GenerationCounts.

_atombase.py — each predicate relation (_GenRelation) keeps atoms in insertion order with two offsets defining OLD / NEW / ALL windows:
- enter_generation() promotes last gen's new atoms to old and snapshots the current length;
- atoms added during a generation sit beyond all_offset and are only seen as NEW next generation.
- Tracked separately for the possible (domain) and fact relations.

_ground.py — a windowed delta-rule join (_join) replaces the naive full re-scan:
- recursive positive literals (predicate in the current SCC) range over a generation window; non-recursive/lower-component literals range over the full relation;
- each generation runs delta rules using the first-new split (_window_for: literals before the delta → OLD, the delta → NEW, after → ALL), so every new combination is generated exactly once;
- seed rules (no recursive literal, including negation-recursive rules) fire only in generation 0;
- both _domain_fixpoint and _fact_fixpoint iterate generations until a pass adds nothing.

The emit phase stays a single full enumeration over the final domain (semi-naive doesn't apply there), and negation handling is unchanged.

Verified

- It's genuinely semi-naive: on a length-12 transitive-closure chain, the recursive literal's NEW windows were 12, 11, …, 1 summing to exactly 78 = the total t-atoms — each atom consumed as "new" once, not re-scanned every pass (naive would be ~12×78).
- Correctness preserved: 58 pygringo tests pass (random hash seed), including all differential cases (stratified/non-stratified negation, recursion, choice); cyclic transitive closure also checked.
- mypy --strict clean, isort/black clean, 33 safety tests still pass.

I also updated the README and module docstrings — semi-naive is no longer described as a "future optimization."

One honest caveat on fidelity: this is the textbook delta-rule formulation of semi-naive, which matches lib/ground's generation semantics, but not its exact machinery — clingo uses per-literal semi-naive indices with an instantiator queue that re-activates rules per newly-derived atom, whereas pygringo re-evaluates each component's rules once per generation. Same asymptotic benefit (joins touch only the delta), simpler control flow.

## Request

Implement per-literal semi-naive indices with an instantiator queue that re-activates rules per newly-derived atom as clingo does.


## Answer

- _Instantiator (new, @dataclass(eq=False)) — one delta rule per recursive literal, exactly clingo's statement.cc todos_ decomposition. A seed instantiator (delta=None) has no recursive literal and runs only in generation 0; a delta instantiator designates one recursive literal as NEW (earlier→OLD, later→ALL, via the existing _window_for) and watches that literal's predicate. _Rule is now eq=False too, so both can key the worklist.
- _build_instantiators expands each rule into its delta rules and records each delta instantiator's watched signature.
- _instantiate — a single queue-driven engine replacing the two for rule in rules generation loops:
  - all instantiators enqueued for generation 0 (clingo's "enqueue all initially");
  - each generation runs only the queued instantiators, then propagates: a predicate that gained atoms re-enqueues exactly the instantiators watching it (clingo's Queue::propagate(index) keyed on the per-literal semi-naive index = the delta predicate);
  - drives both the domain phase and the fact phase via the facts flag.

_atombase.py, _literal.py, _depend.py, _term.py are untouched — the generation windows and negation/fact handling are reused unchanged.

Why it's correct

This is a sound optimization of the already-tested generation version: a delta instantiator that isn't queued in a generation has an empty NEW window, so it would derive nothing — skipping it changes nothing. The differential tests are the guard.

Verified

- 59 tests pass (random hash seed), including all differential cases (stratified/non-stratified negation, recursion, transitive closure, cycles, choice); mypy --strict clean; isort/black clean; 33 safety tests still pass.
- Delta property preserved: on a length-12 transitive-closure chain the NEW(t) windows are 12,11,…,1, summing to 78 — each atom consumed as new once.
- Selective re-activation locked in by a new test (test_queue_reactivates_selectively): for reach(a). edge(a,b). edge(b,c). reach(Y):-reach(X),edge(X,Y). the three seed rules are each instantiated exactly once while the recursive rule re-activates across generations — under the old per-generation scheme the seed counts would have been higher.

This is now faithful to clingo's scheduling: per-literal indices + a queue that re-activates a rule only when a predicate it reads gains atoms, with a single priority queue (sufficient for the supported normal/constraint/choice rules).


## Answer

What changed

pygringo/_ground.py — the bulk of the work:
- _classify now accepts bounded and conditional choice (HeadAggregate with guards + element conditions) and body BodyAggregates; new agg_sigs on _Rule collects aggregate-element condition predicates.
- _join treats a body aggregate as transparent in the domain phase and blocking in the fact phase, and rejects unbound assignment aggregates (N = #count{…}).
- _head_atoms enumerates conditional choice elements over the domain.
- ground() feeds aggregate condition predicates into the dependency graph and rejects recursion through an aggregate (stratified-only).
- Emit (_build_body / _build_ground + _ground_condition/_ground_tuple/_ground_*_guard helpers) instantiates each aggregate's elements/conditions over the domain and emits a ground BodyAggregate/HeadAggregate with its guards, simplifying fact/impossible condition literals.

pygringo/_literal.py — added match_condition (folds match_literal over an element's bare-literal condition) and made match_body transparent for body aggregates.

Docs/tests — README + module-docstring scope updated; test_ground.py gains ~16 differential programs, 3 new exact tests, the deferred-case rejections, and the updated #count { 0,a: a } choice output.

Approach & boundaries (as agreed)

Altitude is instantiate + emit — consistent with the existing choice handling; lib/ground's accumulate/propagate is an optimization, not needed for answer-set correctness. The heavy normalization is done for free by ast.rewrite_statement and the safety pilot (both already in the pipeline). Deferred with clear GroundErrors: escaping assignment aggregates, recursion through aggregates, head #sum/#min/#max, #minimize/#maximize.

Verification

- pytest pygringo/tests → 81 passed (was 59).
- mypy --strict … → clean.
- Extra differential checks against real clingo across ~25 aggregate programs (count/sum/min/max, bounded & conditional choice, negated aggregates, aggregates in constraints, shared global vars, two aggregates per body) all match.
- black/isort applied.

One unrelated pre-existing gap surfaced: anonymous-variable projection (w(I,_)) isn't supported in pygringo even in plain rules — out of scope here.

Note: the memory directory the system prompt referenced didn't exist; I created it with one entry capturing the rewrite-statement/safety-pilot insight for future pygringo work.

---

visiting permutation of body indices by greedy min-cost selection, then have _join follow that permutation (windows stay keyed on each literal's original index, and a "new-atoms-first" tie rule preserves semi-naive correctness — exactly what the C++ order_ comparator does). Emit (match_body) is independent and order-insensitive, so answer sets/output are unchanged — only fixpoint efficiency improves.
2. The cost model needs per-literal depend/provide variable sets, which pygringo doesn't currently compute (it just trusts safety's order). The safety pilot does compute them (_make_nodes, handling linear inversion, equality flips, aggregate deps), and already exports select_variables/check_linear/is_provided. The C++ Term::score I need to port is small (TermBinary/TermSymbol/projection → 0; variable → bound?0:size; function/tuple → nth-root spread).

Two genuine forks before I finalize:

● User answered Claude's questions:
· How faithful should the ported cost model be? The C++ `order_` has a core size-based greedy plus a secondary `AssignmentAnalyzer` refinement that scales a generating matcher's estimate by variables transitively fixed through equalities (back-substitution). → Core greedy (recommended)
· Where should the per-literal depend/provide variable sets come from? The greedy needs them to know which literals are 'ready', and the safety pilot already computes them internally (`_make_nodes`). → Reuse via safety API (recommended)

Decisions noted: core greedy, reuse safety. Let me confirm the exact _make_nodes/_DepNode shape so the safety helper is specified precisely.

---

Done. Cost-based matcher reordering is implemented, verified, and documented.

What changed

safety/ — exposed literal_dependencies(lit, global_set, bound), a thin public wrapper over the existing _make_nodes, so pygringo can reuse the per-literal (provide, depend) analysis (linear inversion, equality flips, aggregate deps) instead of re-deriving it. Exported from safety/__init__.py.

pygringo/_atombase.py — added an O(1) size(...) accessor for the cost model.

pygringo/_order.py (new) — the ported cost analysis:
- _term_score — clingo's Term::score (unbound variable spreads relation size; bound var/constant → 0; function/tuple of arity k → ~k-th-root spread).
- _literal_score — Lit::score (fast filters/assignments = −1, intervals = range length, positive atoms = size-based).
- linearize — greedy min-cost selection over ready literals (rescored each step), with the semi-naive new-atoms-first tie rule. Core greedy only; no AssignmentAnalyzer factor, per your choice.

pygringo/_ground.py — wired it in: _Rule.deps (computed once via the safety helper), _Instantiator.order, _build_instantiators computes the visiting permutation per delta from an AtomBase size snapshot, and _join now follows that permutation (windows still keyed on each literal's original index).

Docs/tests — updated matcher-ordering.md's "Relation to pygringo"; new test_order.py (cost model + linearize behavior, including the delta-slot rule); two join-heavy differential programs; updated the queue-spy test to the new _join signature.

Verification

- pytest pygringo/tests safety/tests → 120 passed. Crucially, every pre-existing test passes unchanged — reordering alters neither answer sets nor emitted text.
- mypy --strict → clean (20 files).
- Perf: on a join-heavy program, reordering grounds 2.8× faster with byte-identical output vs. a forced identity order.
- isort/black applied.

The key correctness property: the reorder only changes how a body join is evaluated, never the set of solutions, so output is provably unchanged — only the fixpoint gets cheaper.

---

Incorporate support for aggregtes in `pygringo` using the code in `lib/ground` as guide.
