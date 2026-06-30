# How gringo reorders matchers (body-literal join ordering)

This note explains the algorithm the C++ grounder uses to decide the *order* in
which a rule body's literals (matchers) are evaluated. Reordering matters for the
same reason join ordering matters in a database: a rule body is a join over
relations, and the order in which you join determines how large the intermediate
result sets get. Gringo picks the order with a greedy, cost-based heuristic.

All code references are to `lib/ground`.

## Where it lives

- `Ground::Linearizer::prepare` and `Ground::Linearizer::order_` —
  `lib/ground/src/statement.cc:108` and `:169`. `order_` is the actual ordering
  algorithm.
- Per-matcher cost model: `Lit::score` (`lib/ground/include/clingo/ground/literal.hh:57`)
  with implementations in `lib/ground/src/literal.cc` and, for the size estimate
  of symbolic atoms, `Term::score` in `lib/ground/src/term.cc`.
- `AssignmentAnalyzer` helper — `lib/ground/src/statement.cc:13`.

## Two layers: linearization, then ordering

`prepare` (`statement.cc:108`) is called once per rule. It does two things.

1. **Semi-naive delta programs.** A recursive literal (one that is not
   `single_pass`, i.e. ranges over a predicate still growing in the current
   component) is marked. For *n* recursive literals it produces *n* "todo"
   vectors — one per literal designated as the *delta*. In a given todo the delta
   literal is `MatcherType::new_atoms`, recursive literals before it are
   `old_atoms`, and the rest are `all_atoms` (the standard *first-new* split, so
   every tuple containing at least one freshly derived atom is enumerated exactly
   once). `MatcherType` is `{new_atoms, old_atoms, all_atoms}` in that order
   (`instantiator.hh:54`).

2. **Dependency model** (`build_`, `statement.cc:140`). For every literal it
   collects two variable sets:
   - **depend**: variables that must already be bound for the literal to run
     (`VarSelectMode::depend`);
   - **provide**: variables the literal can bind (`VarSelectMode::provide`).
   It also builds the inverse map `var -> literals that depend on it`.

Then for each todo it calls `order_` to greedily order *that* delta program, and
registers the resulting `Instantiator` in the queue under the index of the
predicate it watches (`statement.cc:134`).

## The cost model: `score`

Each matcher exposes `score(bound)` returning a `double`, where `bound` is the
current "is this variable bound?" bitmap. Lower is better. The sign encodes a
class:

- **Negative = "fast", non-generating** matchers (filters and assignments that
  do not enumerate a relation). Constants in `literal.cc:10`:
  - `score_fast = -1.0`: comparisons `X<Y` (`LitComparison`, `:163`), fully-bound
    or numeric intervals (`LitInterval`, `:59`), simple aggregates, fact checks.
  - `score_maybe_fast = -0.1`: externals (`:300`).
- **0**: a matcher that provides no *new* variable — e.g. a negative atom
  (`LitSymbolic` with `Sign::once` returns 0, `:417`), a projection or tuple
  check that only filters.
- **Positive = generating** matchers: the estimated number of atoms the matcher
  yields. For a symbolic atom this is `atom->score(relation_size, bound)`
  (`LitSymbolic::do_score`, `:409`), which walks the term structure:
  - `TermVariable` / `TermLinear`: `bound[v] ? 0 : size` — an unbound argument
    variable contributes the full relation size; a bound one contributes nothing
    (it filters) (`term.cc:551`, `:607`).
  - `TermSymbol`, `TermProjection`: `0` — a constant argument is fully selective
    (`term.cc:118`, `:56`).
  - `TermFunction` with arity *k*: `root = max(1, (size/2)^(1/k))`, then average
    the children's scores evaluated at `root` (`term.cc:1037`). `TermTuple` is the
    same with `root = size^(1/k)` (`:948`). This models a predicate's tuples as
    spread across its argument positions, so binding more arguments shrinks the
    estimate super-linearly.

  So an atom all of whose argument variables are already bound scores ~0 (a
  lookup), while one with all-free arguments scores ~`size` (a full scan).

## The greedy ordering loop (`order_`)

`order_` maintains a worklist (`queue_`) of literals that are *ready* — every
variable in their `depend` set is bound. Initialization queues all literals with
no dependencies (`statement.cc:176`). A per-literal counter `cur` starts at
`depend.size()` and is decremented as its dependencies get provided; it joins the
queue when `cur` hits 0 (`:261`).

Each iteration:

1. **Re-score every ready literal** against the current `bound` set
   (`:214`–`:228`). Scores are recomputed each round because binding a variable
   can turn an expensive full scan into a cheap lookup. A literal that provides
   nothing new is left "free"; a generating literal (`score > 0`) gets an extra
   factor (see below).

2. **Pick the minimum-score ready literal**, ties broken by insertion order
   (`std::get<1>` is a monotonically increasing generation counter) (`:230`–
   `:242`). The effect: apply cheap filters and assignments first, then among
   generating matchers choose the most selective, deferring full scans.

   There is one override for semi-naive correctness: when comparing a
   `new_atoms` matcher against a non-`new` one and *both* are generating
   (`score >= 0`), the order is forced by `MatcherType` rather than by score
   (`new_atoms` sorts first) (`:236`). This pins the delta literal's relative
   position so the first-new enumeration stays correct regardless of the cost
   estimates.

3. **Commit the chosen matcher**: build it (`lits[i]->matcher(...)`), record the
   watched predicate index if any, append it to the `Instantiator` with the list
   of binding "slots" it depends on (`make_depend`, `:184`), then mark its newly
   provided variables bound and enqueue any literal that thereby becomes ready
   (`:255`–`:267`). An equivalent already-emitted matcher (e.g. `X=Y` vs `Y=X`)
   is skipped (`:246`).

Finally `inst.finalize` records the rule's *important* variables (those needed by
the head / enclosing scope) so the instantiator knows which bindings to keep
(`:270`).

### The assignment-propagation factor

Before scoring, an `AssignmentAnalyzer` is built over the body's assignment
literals with **depend/provide deliberately swapped** (`:209`): a literal that
depends on vars *D* and provides *P* is entered as a node depending on *P* and
providing *D*. This models *back-substitution* through equalities — if you learn
the output of `Z = f(X)`, you may be able to solve for its input `X`.

When scoring a generating literal, `analyzer.propagate(prv)` reports how many
*extra* variables would become determined this way once the literal's provides
are bound, and the size estimate is scaled `score *= 1 + extra.size()`
(`:221`–`:225`). Because the loop minimizes, a generating matcher whose bindings
merely also unlock equality-determined variables is charged more and scheduled
later, so genuinely size-reducing matchers and pure filters run first; the
equality-induced bindings are then harvested cheaply once the candidate set has
shrunk. `backtrack()` undoes the temporary propagation before the next candidate
is scored.

## Summary

For each rule (and each semi-naive delta of it), gringo greedily linearizes the
body: repeatedly score every literal whose variables are bindable, then take the
cheapest — fast filters/assignments (negative score) first, then the most
selective generating atom (smallest estimated output, with bound arguments
modeled as shrinking the estimate), with a fixed slot for the semi-naive delta
literal and a correction for variables fixed transitively through equalities. The
result is an `Instantiator`: an ordered chain of matchers that keeps intermediate
join results as small as the heuristic can manage.

### Relation to pygringo

pygringo ports this algorithm in `pygringo/_order.py` (`linearize`), wired into
the fixpoint via `_build_instantiators` / `_join` in `pygringo/_ground.py`. The
`safety` pilot supplies the readiness half — it orders the body for
*groundability* and exposes per-literal `(provide, depend)` via
`safety.literal_dependencies` — and `_order.py` adds the cost model: the ported
`Term::score`/`Lit::score` (`_term_score`/`_literal_score`), the greedy min-cost
selection with the semi-naive new-atoms tie rule, and the `AssignmentAnalyzer`
back-substitution factor (the `AssignmentAnalyzer` class; its `extra` per literal
is constant, so it is precomputed once per body). Note the factor is largely
*inert* on pygringo's input: `rewrite_statement` inlines equalities and seeds
interval variables with bound-check comparisons, so few back-substitution edges
survive. Reordering changes only the join's evaluation, never its result, so
ground output is unchanged. See [[pygringo-lean-on-rewrite-and-safety]].
