"""The grounding pipeline.

Ties the pieces together into :func:`ground`, which turns a non-ground program
into a list of variable-free :class:`clingo.ast` statements.  The pipeline
mirrors the C++ grounder at a high level:

1. **normalise** every statement with :func:`clingo.ast.rewrite_statement`
   (unpooling, canonicalising arithmetic into ``m*X+n``, turning intervals into
   ``X = lo..hi`` comparisons) -- the precondition the ``safety`` pilot assumes;
2. **check safety** and obtain the body in *groundable order* via
   :func:`safety.check_safety`;
3. group the predicates into dependency **components** (:mod:`._depend`);
4. per component, run a **domain** fixpoint (possible atoms, ignoring negation)
   then a **fact** fixpoint (atoms derived by a trivially-true body);
5. **emit** the ground program, simplifying body literals from the atom states.

Negation -- including recursion through negation -- is supported: following
``lib/ground``'s ``NonFactMatcher`` / ``StateAtom``, a negative literal does not
bind variables or restrict the domain; at emit time a negated atom that is a fact
kills the rule, one that is not in the domain is dropped (trivially true), and an
otherwise possible one is kept for the solver.

Scope: normal rules, integrity constraints, choice rules (with bounds and
conditional elements) and body aggregates (``#count``/``#sum``/``#sump``/
``#min``/``#max`` with guards and conditions, positive or negated).  Aggregates
are instantiated over the domain and emitted *ground* for the solver to evaluate
(like choice rules); their truth value is not decided here.  Assignment
aggregates whose variable escapes (``N = #count{...}``), recursion through an
aggregate, head ``#sum``/``#min``/``#max`` aggregates, disjunctions, conditional
literals, theory atoms, optimize / weak constraints, externals, and
show/project/edge/heuristic statements and scripts raise :class:`GroundError`.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from clingo import ast
from clingo.core import Library, Location
from clingo.symbol import Symbol

from safety import VariableContext, check_safety, literal_dependencies, select_variables

from ._atombase import AtomBase, Signature, Window, signature_of
from ._depend import order_components
from ._error import GroundError, _Undefined
from ._literal import match_body, match_condition, match_literal
from ._order import Dep, linearize
from ._term import Assignment, atom_signature, eval_term, match_term


class _Kind(enum.Enum):
    NORMAL = "normal"
    CONSTRAINT = "constraint"
    CHOICE = "choice"


@dataclass(eq=False)
class _Rule:
    """A safety-checked, reordered rule together with its dependency signatures.

    ``eq=False`` gives identity equality/hashing so rules can key the worklist.
    """

    kind: _Kind
    location: Location
    head: ast.HeadLiteral
    body: list[ast.BodyLiteral]
    head_sigs: list[Signature]
    body_sigs: list[Signature]
    #: Positive predicate signatures in aggregate element conditions (head or
    #: body).  They are dependency edges and gate the stratification check.
    agg_sigs: list[Signature]
    #: Per-body-literal ``(provide, depend)`` variable sets, for cost-based
    #: matcher reordering (one entry per ``body`` literal, same order).
    deps: list[Dep] = field(default_factory=list)
    component: int = -1


@dataclass(eq=False)
class _Instantiator:
    """One delta rule of a rule, in clingo's sense (``statement.cc`` ``todos_``).

    A *seed* instantiator (``delta is None``) has no recursive literal and runs
    only in generation 0.  A *delta* instantiator designates ``delta`` as its
    *new* recursive literal (earlier recursive literals range over old atoms,
    later over all); it ``watch``es that literal's predicate and is re-queued
    whenever that predicate gains atoms.
    """

    rule: _Rule
    recursive: frozenset[int]
    delta: int | None
    watch: Signature | None
    #: Visiting permutation of ``rule.body`` indices, ordered by estimated cost.
    order: list[int]


# --- classification --------------------------------------------------------


def _simple_literal(blit: ast.BodyLiteral) -> ast.Literal:
    """Return the literal of a simple body literal, rejecting other body kinds."""
    if not isinstance(blit, ast.BodySimpleLiteral):
        raise GroundError(f"unsupported body literal: {blit}")
    return blit.literal


def _condition_sigs(condition: Sequence[ast.Literal]) -> list[Signature]:
    """Positive symbolic predicate signatures in an aggregate element condition."""
    sigs: list[Signature] = []
    for lit in condition:
        if isinstance(lit, ast.LiteralSymbolic) and lit.sign == ast.Sign.NoSign:
            sigs.append(atom_signature(lit.atom))
    return sigs


def _element_sigs(elements: Sequence[Any]) -> list[Signature]:
    """Condition signatures across all elements of an aggregate."""
    sigs: list[Signature] = []
    for elem in elements:
        sigs.extend(_condition_sigs(elem.condition))
    return sigs


def _body_signatures(
    body: Sequence[ast.BodyLiteral],
) -> tuple[list[Signature], list[Signature]]:
    """Return ``(body_sigs, agg_sigs)``: simple positive deps and aggregate deps."""
    body_sigs: list[Signature] = []
    agg_sigs: list[Signature] = []
    for blit in body:
        if isinstance(blit, ast.BodyAggregate):
            agg_sigs.extend(_element_sigs(blit.elements))
            continue
        lit = _simple_literal(blit)
        if isinstance(lit, ast.LiteralSymbolic):
            # Both signs edge into the dependency graph so negative cycles land in
            # one component (positive recursion is selected separately).
            body_sigs.append(atom_signature(lit.atom))
    return body_sigs, agg_sigs


def _rule_deps(head: ast.HeadLiteral, body: Sequence[ast.BodyLiteral]) -> list[Dep]:
    """Per-body-literal ``(provide, depend)`` variable sets (via the ``safety`` pilot).

    ``global_set`` is the rule's global variables, needed so the dependency
    analysis classifies aggregate-element variables correctly.
    """
    global_set: set[str] = set(select_variables(head, VariableContext.GLOBAL))
    for blit in body:
        global_set |= select_variables(blit, VariableContext.GLOBAL)
    deps: list[Dep] = []
    for blit in body:
        nodes = literal_dependencies(blit, global_set)
        provide = frozenset(v for node in nodes for v in node.provide)
        depend = frozenset(v for node in nodes for v in node.depend)
        deps.append((provide, depend))
    return deps


def _classify(stm: ast.StatementRule) -> _Rule:
    head = stm.head
    body = list(stm.body)
    body_sigs, agg_sigs = _body_signatures(body)
    deps = _rule_deps(head, body)

    if isinstance(head, ast.HeadSimpleLiteral):
        hlit = head.literal
        if isinstance(hlit, ast.LiteralBoolean):
            if hlit.value:
                raise GroundError("rule head '#true' is not supported")
            return _Rule(
                _Kind.CONSTRAINT,
                stm.location,
                head,
                body,
                [],
                body_sigs,
                agg_sigs,
                deps,
            )
        if isinstance(hlit, ast.LiteralSymbolic):
            sig = atom_signature(hlit.atom)
            return _Rule(
                _Kind.NORMAL, stm.location, head, body, [sig], body_sigs, agg_sigs, deps
            )
        raise GroundError(f"unsupported head literal: {hlit}")

    if isinstance(head, ast.HeadAggregate):
        if head.function != ast.AggregateFunction.Count:
            raise GroundError("only choice (#count) head aggregates are supported")
        head_sigs: list[Signature] = []
        for elem in head.elements:
            if not isinstance(elem.literal, ast.LiteralSymbolic):
                raise GroundError(f"unsupported choice element: {elem.literal}")
            head_sigs.append(atom_signature(elem.literal.atom))
        agg_sigs = agg_sigs + _element_sigs(head.elements)
        return _Rule(
            _Kind.CHOICE, stm.location, head, body, head_sigs, body_sigs, agg_sigs, deps
        )

    raise GroundError(f"unsupported rule head: {type(head).__name__}")


# --- head atoms ------------------------------------------------------------


def _head_atoms(
    rule: _Rule, asgn: Assignment, base: AtomBase, lib: Library
) -> list[Symbol]:
    """Evaluate the ground atoms a rule derives under ``asgn`` (empty for constraints).

    May raise :class:`_Undefined` if head arithmetic is undefined.
    """
    if rule.kind == _Kind.NORMAL:
        assert isinstance(rule.head, ast.HeadSimpleLiteral)
        assert isinstance(rule.head.literal, ast.LiteralSymbolic)
        sym = eval_term(rule.head.literal.atom, asgn, lib)
        assert sym is not None
        return [sym]
    if rule.kind == _Kind.CHOICE:
        assert isinstance(rule.head, ast.HeadAggregate)
        atoms: list[Symbol] = []
        for elem in rule.head.elements:
            assert isinstance(elem.literal, ast.LiteralSymbolic)
            for cond_asgn in match_condition(elem.condition, asgn, base, lib):
                sym = eval_term(elem.literal.atom, cond_asgn, lib)
                assert sym is not None
                atoms.append(sym)
        return atoms
    return []


# --- semi-naive matching ---------------------------------------------------


def _recursive_positions(
    body: list[ast.BodyLiteral], component: frozenset[Signature]
) -> list[int]:
    """Positions of positive symbolic literals whose predicate is in ``component``."""
    positions: list[int] = []
    for index, blit in enumerate(body):
        if isinstance(blit, ast.BodySimpleLiteral):
            lit = blit.literal
            if isinstance(lit, ast.LiteralSymbolic) and lit.sign == ast.Sign.NoSign:
                if atom_signature(lit.atom) in component:
                    positions.append(index)
    return positions


def _window_for(index: int, delta: int) -> Window:
    """Window of a recursive literal when ``delta`` is the designated delta position.

    Uses the *first-new* split (each tuple with >=1 new atom is generated once):
    literals before the delta range over old atoms, the delta over new, the rest
    over all.
    """
    if index < delta:
        return Window.OLD
    if index == delta:
        return Window.NEW
    return Window.ALL


def _is_unbound_assignment(agg: ast.BodyAggregate, asgn: Assignment) -> bool:
    """True for an assignment aggregate ``Var = #agg{...}`` whose ``Var`` is unbound.

    Such an aggregate would have to *bind* ``Var`` to each possible aggregate value
    (``lib/ground``'s ``StateAssignAggr``), which is out of scope; an equality guard
    against an already-bound value or a constant is a plain check and is allowed.
    """
    left = agg.left
    return (
        agg.sign == ast.Sign.NoSign
        and agg.right is None
        and left is not None
        and left.relation == ast.Relation.Equal
        and isinstance(left.term, ast.TermVariable)
        and left.term.name not in asgn
    )


def _join(
    body: list[ast.BodyLiteral],
    order: list[int],
    pos: int,
    asgn: Assignment,
    base: AtomBase,
    lib: Library,
    recursive: frozenset[int],
    delta: int | None,
    facts: bool,
) -> Iterator[Assignment]:
    """Backtracking join of ``body`` in ``order`` with semi-naive windows.

    ``order`` is the cost-based visiting permutation of body indices
    (:func:`pygringo._order.linearize`); ``pos`` is the position within it.  The
    semi-naive window of a recursive literal is keyed on its *original* body index
    (``order[pos]``), so reordering never affects which generation it ranges over.
    Positive symbolic literals over the current component (``recursive``) range
    over a generation window (relative to ``delta``); other positive literals
    range over the whole relation.  When ``facts`` is set, positive literals match
    the *fact* relation and a negative literal prunes unless its atom is impossible
    (the body must be trivially true for the head to be a fact); otherwise negation
    is ignored (domain phase).
    """
    if pos == len(order):
        yield asgn
        return
    index = order[pos]
    blit = body[index]

    if isinstance(blit, ast.BodyAggregate):
        if _is_unbound_assignment(blit, asgn):
            raise GroundError(f"assignment aggregates are not supported: {blit}")
        # The domain ignores the aggregate (it binds nothing, like negation); the
        # fact phase blocks, so an aggregate-bodied rule never derives a fact.
        if facts:
            return
        yield from _join(body, order, pos + 1, asgn, base, lib, recursive, delta, facts)
        return

    lit = _simple_literal(blit)

    if isinstance(lit, ast.LiteralSymbolic):
        atom = lit.atom
        if lit.sign == ast.Sign.NoSign:
            name, arity, positive = atom_signature(atom)
            if index in recursive:
                assert delta is not None
                candidates = base.window(
                    name, arity, positive, _window_for(index, delta), facts
                )
            else:
                candidates = base.relation(name, arity, positive, facts)
            for sym in candidates:
                extended = dict(asgn)
                try:
                    matched = match_term(atom, sym, extended, lib)
                except _Undefined:
                    continue
                if matched:
                    yield from _join(
                        body,
                        order,
                        pos + 1,
                        extended,
                        base,
                        lib,
                        recursive,
                        delta,
                        facts,
                    )
            return

        # Negative literal: ground (variables bound by earlier positives).
        try:
            sym = eval_term(atom, asgn, lib)
        except _Undefined:
            return
        if sym is None:
            raise GroundError(f"unbound variable in negative literal: {lit}")
        if facts and (lit.sign != ast.Sign.Single or base.is_possible(sym)):
            return  # not trivially true (possible atom, or conservative double negation)
        yield from _join(body, order, pos + 1, asgn, base, lib, recursive, delta, facts)
        return

    # Comparisons / intervals / booleans are window-independent.
    try:
        extensions = list(match_literal(lit, asgn, base, lib))
    except _Undefined:
        return
    for extension in extensions:
        yield from _join(
            body, order, pos + 1, extension, base, lib, recursive, delta, facts
        )


def _build_instantiators(
    rules: list[_Rule], component: frozenset[Signature], base: AtomBase
) -> list[_Instantiator]:
    """Expand each rule into its delta rules (one instantiator per delta position).

    Each instantiator carries a cost-based visiting ``order`` for its body,
    computed from a snapshot of the current relation sizes in ``base``.
    """
    instantiators: list[_Instantiator] = []
    for rule in rules:
        recursive = _recursive_positions(rule.body, component)
        if not recursive:
            order = linearize(rule.body, rule.deps, None, base)
            instantiators.append(_Instantiator(rule, frozenset(), None, None, order))
            continue
        rec_set = frozenset(recursive)
        for delta in recursive:
            lit = rule.body[delta]
            assert isinstance(lit, ast.BodySimpleLiteral)
            assert isinstance(lit.literal, ast.LiteralSymbolic)
            watch = atom_signature(lit.literal.atom)
            order = linearize(rule.body, rule.deps, delta, base)
            instantiators.append(_Instantiator(rule, rec_set, delta, watch, order))
    return instantiators


def _instantiate(
    rules: list[_Rule],
    component: frozenset[Signature],
    base: AtomBase,
    lib: Library,
    facts: bool,
) -> None:
    """Run the queue-driven semi-naive fixpoint over ``rules``.

    With ``facts`` set this derives *facts* from normal rules (a body trivially
    true under the current states); otherwise it derives the *domain* (possible
    atoms, ignoring negation).  An instantiator is re-queued only when a predicate
    it watches gains atoms -- clingo's ``Queue::propagate`` keyed on the
    per-literal semi-naive index.
    """
    eligible = [r for r in rules if not facts or r.kind == _Kind.NORMAL]
    instantiators = _build_instantiators(eligible, component, base)
    watchers: dict[Signature, list[_Instantiator]] = {}
    for inst in instantiators:
        if inst.watch is not None:
            watchers.setdefault(inst.watch, []).append(inst)

    queue: dict[_Instantiator, None] = dict.fromkeys(instantiators)
    while queue:
        base.enter_generation(component, facts=facts)
        current = list(queue)
        queue = {}
        grew: dict[Signature, None] = {}
        for inst in current:
            for asgn in _join(
                inst.rule.body,
                inst.order,
                0,
                {},
                base,
                lib,
                inst.recursive,
                inst.delta,
                facts,
            ):
                try:
                    atoms = _head_atoms(inst.rule, asgn, base, lib)
                except _Undefined:
                    continue
                for sym in atoms:
                    added = base.add_fact(sym) if facts else base.add(sym)
                    if added:
                        grew[signature_of(sym)] = None
        for sig in grew:
            for inst in watchers.get(sig, ()):
                queue[inst] = None


# --- output construction ---------------------------------------------------


def _symbol_literal(
    lib: Library, loc: Location, sym: Symbol, sign: ast.Sign
) -> ast.LiteralSymbolic:
    return ast.LiteralSymbolic(lib, loc, sign, ast.TermSymbolic(lib, loc, sym))


def _ground_tuple(
    terms: Sequence[ast.Term], asgn: Assignment, lib: Library, loc: Location
) -> list[ast.Term]:
    """Evaluate an element tuple to ground symbolic terms."""
    out: list[ast.Term] = []
    for term in terms:
        sym = eval_term(term, asgn, lib)
        assert sym is not None
        out.append(ast.TermSymbolic(lib, loc, sym))
    return out


def _ground_condition(
    condition: Sequence[ast.Literal],
    asgn: Assignment,
    base: AtomBase,
    lib: Library,
    loc: Location,
) -> list[ast.Literal] | None:
    """Ground and simplify an aggregate element condition (a list of literals).

    Mirrors :func:`_build_body`: positive facts and impossible negatives are
    dropped, comparisons/booleans are dropped (verified while matching), and a
    negative fact returns ``None`` -- the condition is false, so the element is
    dropped from the aggregate.
    """
    out: list[ast.Literal] = []
    for lit in condition:
        if not isinstance(lit, ast.LiteralSymbolic):
            continue
        sym = eval_term(lit.atom, asgn, lib)
        assert sym is not None
        if lit.sign == ast.Sign.NoSign:
            if base.is_fact(sym):
                continue
        elif lit.sign == ast.Sign.Single:
            if base.is_fact(sym):
                return None
            if not base.is_possible(sym):
                continue
        out.append(_symbol_literal(lib, loc, sym, lit.sign))
    return out


def _ground_left_guard(
    guard: ast.LeftGuard | None, asgn: Assignment, lib: Library, loc: Location
) -> ast.LeftGuard | None:
    if guard is None:
        return None
    sym = eval_term(guard.term, asgn, lib)
    assert sym is not None
    return ast.LeftGuard(lib, ast.TermSymbolic(lib, loc, sym), guard.relation)


def _ground_right_guard(
    guard: ast.RightGuard | None, asgn: Assignment, lib: Library, loc: Location
) -> ast.RightGuard | None:
    if guard is None:
        return None
    sym = eval_term(guard.term, asgn, lib)
    assert sym is not None
    return ast.RightGuard(lib, guard.relation, ast.TermSymbolic(lib, loc, sym))


def _ground_body_aggregate(
    agg: ast.BodyAggregate,
    asgn: Assignment,
    base: AtomBase,
    lib: Library,
    loc: Location,
) -> ast.BodyAggregate:
    """Instantiate a body aggregate's elements over the domain, keeping its guards.

    The aggregate is emitted ground for clingo to evaluate; we do not attempt to
    decide its truth value here (cf. ``lib/ground``'s accumulate/propagate).
    """
    elements: list[ast.BodyAggregateElement] = []
    for elem in agg.elements:
        for cond_asgn in match_condition(elem.condition, asgn, base, lib):
            cond = _ground_condition(elem.condition, cond_asgn, base, lib, loc)
            if cond is None:
                continue
            tup = _ground_tuple(elem.tuple, cond_asgn, lib, loc)
            elements.append(ast.BodyAggregateElement(lib, loc, tup, cond))
    left = _ground_left_guard(agg.left, asgn, lib, loc)
    right = _ground_right_guard(agg.right, asgn, lib, loc)
    return ast.BodyAggregate(lib, loc, agg.sign, left, agg.function, elements, right)


def _build_body(
    rule: _Rule, asgn: Assignment, base: AtomBase, lib: Library
) -> list[ast.BodyLiteral] | None:
    """Render the matched body as ground literals, simplifying from atom states.

    Returns ``None`` if the rule is killed (a negated atom is a fact).  Positive
    facts and impossible negative literals are dropped (trivially true);
    comparisons/booleans are dropped (verified during matching).  Body aggregates
    are instantiated into a ground aggregate for the solver to evaluate.
    """
    loc = rule.location
    out: list[ast.BodyLiteral] = []
    for blit in rule.body:
        if isinstance(blit, ast.BodyAggregate):
            out.append(_ground_body_aggregate(blit, asgn, base, lib, loc))
            continue
        lit = _simple_literal(blit)
        if not isinstance(lit, ast.LiteralSymbolic):
            continue
        sym = eval_term(lit.atom, asgn, lib)
        assert sym is not None
        if lit.sign == ast.Sign.NoSign:
            if base.is_fact(sym):
                continue  # trivially true
        elif lit.sign == ast.Sign.Single:
            if base.is_fact(sym):
                return None  # body is false; the rule is deleted
            if not base.is_possible(sym):
                continue  # trivially true
        out.append(ast.BodySimpleLiteral(lib, _symbol_literal(lib, loc, sym, lit.sign)))
    return out


def _build_ground(
    rule: _Rule, asgn: Assignment, base: AtomBase, lib: Library
) -> ast.Statement | None:
    """Build the ground statement for one matched instance, or ``None`` if killed."""
    body = _build_body(rule, asgn, base, lib)
    if body is None:
        return None
    loc = rule.location

    if rule.kind == _Kind.CONSTRAINT:
        return ast.StatementRule(lib, loc, rule.head, body)

    if rule.kind == _Kind.NORMAL:
        (sym,) = _head_atoms(rule, asgn, base, lib)
        head = ast.HeadSimpleLiteral(
            lib, _symbol_literal(lib, loc, sym, ast.Sign.NoSign)
        )
        return ast.StatementRule(lib, loc, head, body)

    # choice / bounded / conditional head aggregate (#count)
    head_agg = rule.head
    assert isinstance(head_agg, ast.HeadAggregate)
    elements: list[ast.HeadAggregateElement] = []
    for elem in head_agg.elements:
        assert isinstance(elem.literal, ast.LiteralSymbolic)
        for cond_asgn in match_condition(elem.condition, asgn, base, lib):
            sym = eval_term(elem.literal.atom, cond_asgn, lib)
            assert sym is not None
            cond = _ground_condition(elem.condition, cond_asgn, base, lib, loc)
            if cond is None:
                continue
            tup = _ground_tuple(elem.tuple, cond_asgn, lib, loc)
            literal = _symbol_literal(lib, loc, sym, elem.literal.sign)
            elements.append(ast.HeadAggregateElement(lib, loc, tup, literal, cond))
    left = _ground_left_guard(head_agg.left, asgn, lib, loc)
    right = _ground_right_guard(head_agg.right, asgn, lib, loc)
    head = ast.HeadAggregate(lib, loc, left, head_agg.function, elements, right)
    return ast.StatementRule(lib, loc, head, body)


def _emit(
    rule: _Rule, base: AtomBase, lib: Library, out: list[ast.Statement], seen: set[str]
) -> None:
    for asgn in match_body(rule.body, {}, base, lib):
        try:
            stm = _build_ground(rule, asgn, base, lib)
        except _Undefined:
            continue
        if stm is None:
            continue
        key = str(stm)
        if key not in seen:
            seen.add(key)
            out.append(stm)


# --- driver ----------------------------------------------------------------


def ground(lib: Library, statements: Sequence[ast.Statement]) -> list[ast.Statement]:
    """Ground ``statements`` into a list of variable-free ``clingo.ast`` statements.

    ``statements`` are non-ground statements as produced by
    :func:`clingo.ast.parse_statement` / :func:`clingo.ast.parse_string`.  The
    returned program contains only ground rules, facts, integrity constraints and
    choice rules.  Raises :class:`GroundError` for unsafe rules and for constructs
    outside the core milestone.
    """
    ctx = ast.RewriteContext(lib)
    rules: list[_Rule] = []
    constraints: list[_Rule] = []

    for stm in statements:
        # Structural directives carry no rules to ground.
        if isinstance(stm, (ast.StatementProgram, ast.StatementComment)):
            continue
        if not isinstance(stm, ast.StatementRule):
            raise GroundError(f"unsupported statement: {type(stm).__name__}")
        try:
            normalised_statements = ast.rewrite_statement(ctx, stm)
        except RuntimeError as exc:  # clingo rejects e.g. unsafe rules while rewriting
            raise GroundError(f"could not rewrite statement: {stm}") from exc
        for normalised in normalised_statements:
            if not isinstance(normalised, ast.StatementRule):
                raise GroundError(f"unsupported statement: {type(normalised).__name__}")
            result = check_safety(lib, normalised)
            if not result.safe:
                raise GroundError(f"unsafe variables: {result.unsafe_variables}")
            assert isinstance(result.statement, ast.StatementRule)
            rule = _classify(result.statement)
            (constraints if rule.kind == _Kind.CONSTRAINT else rules).append(rule)

    # Dependency components over predicate signatures (negative cycles allowed).
    # Nodes are kept in first-seen order so component order -- and hence the output
    # order -- is deterministic for a given input, independent of hash seeding.
    # Aggregate element conditions (``agg_sigs``) are dependencies of the head just
    # like positive body literals, so they edge into the head and place the head in
    # a later component -- which lets us forbid recursion *through* an aggregate.
    nodes: dict[Signature, None] = {}
    edges: list[tuple[Signature, Signature]] = []
    for rule in rules:
        for sig in (*rule.head_sigs, *rule.body_sigs, *rule.agg_sigs):
            nodes.setdefault(sig, None)
        for head_sig in rule.head_sigs:
            for sig in (*rule.body_sigs, *rule.agg_sigs):
                edges.append((sig, head_sig))

    components = order_components(nodes, edges)
    comp_index = {sig: i for i, comp in enumerate(components) for sig in comp}
    for rule in rules:
        rule.component = max((comp_index[s] for s in rule.head_sigs), default=0)

    # Stratified aggregates only: an element-condition predicate may not share the
    # rule's own component (that would be recursion through the aggregate).
    for rule in rules:
        if any(comp_index[s] == rule.component for s in rule.agg_sigs):
            raise GroundError("recursion through aggregates is not supported")

    # Per component (dependency order): domain fixpoint, then fact fixpoint.
    base = AtomBase()
    by_component = [
        [r for r in rules if r.component == ci] for ci in range(len(components))
    ]
    comp_sigs = [frozenset(comp) for comp in components]
    for ci, comp_rules in enumerate(by_component):
        _instantiate(comp_rules, comp_sigs[ci], base, lib, facts=False)
        _instantiate(comp_rules, comp_sigs[ci], base, lib, facts=True)

    # Emit once all atom states are final: rules (dependency order), then constraints.
    out: list[ast.Statement] = []
    seen: set[str] = set()
    for comp_rules in by_component:
        for rule in comp_rules:
            _emit(rule, base, lib, out, seen)
    for rule in constraints:
        _emit(rule, base, lib, out, seen)

    return out
