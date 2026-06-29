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

Scope (core milestone): normal rules, integrity constraints and plain choice
rules (``{ ... }`` without bounds or conditional elements).  Aggregates with
bounds or conditions, disjunctions, conditional literals, theory atoms, optimize
/ weak constraints, externals, show/project/edge/heuristic statements and scripts
raise :class:`GroundError`.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from clingo import ast
from clingo.core import Library, Location
from clingo.symbol import Symbol

from safety import check_safety

from ._atombase import AtomBase, Signature
from ._depend import order_components
from ._error import GroundError, _Undefined
from ._literal import match_body
from ._term import Assignment, atom_signature, eval_term


class _Kind(enum.Enum):
    NORMAL = "normal"
    CONSTRAINT = "constraint"
    CHOICE = "choice"


@dataclass
class _Rule:
    """A safety-checked, reordered rule together with its dependency signatures."""

    kind: _Kind
    location: Location
    head: ast.HeadLiteral
    body: list[ast.BodyLiteral]
    head_sigs: list[Signature]
    body_sigs: list[Signature]
    component: int = -1


# --- classification --------------------------------------------------------


def _simple_literal(blit: ast.BodyLiteral) -> ast.Literal:
    """Return the literal of a simple body literal, rejecting other body kinds."""
    if not isinstance(blit, ast.BodySimpleLiteral):
        raise GroundError(f"unsupported body literal: {blit}")
    return blit.literal


def _body_signatures(body: Sequence[ast.BodyLiteral]) -> list[Signature]:
    sigs: list[Signature] = []
    for blit in body:
        lit = _simple_literal(blit)
        if isinstance(lit, ast.LiteralSymbolic):
            sigs.append(atom_signature(lit.atom))
    return sigs


def _classify(stm: ast.StatementRule) -> _Rule:
    head = stm.head
    body = list(stm.body)
    body_sigs = _body_signatures(body)

    if isinstance(head, ast.HeadSimpleLiteral):
        hlit = head.literal
        if isinstance(hlit, ast.LiteralBoolean):
            if hlit.value:
                raise GroundError("rule head '#true' is not supported")
            return _Rule(_Kind.CONSTRAINT, stm.location, head, body, [], body_sigs)
        if isinstance(hlit, ast.LiteralSymbolic):
            sig = atom_signature(hlit.atom)
            return _Rule(_Kind.NORMAL, stm.location, head, body, [sig], body_sigs)
        raise GroundError(f"unsupported head literal: {hlit}")

    if isinstance(head, ast.HeadAggregate):
        if head.left is not None or head.right is not None:
            raise GroundError("bounded head aggregates are not supported")
        if head.function != ast.AggregateFunction.Count:
            raise GroundError("only plain choice aggregates are supported")
        head_sigs: list[Signature] = []
        for elem in head.elements:
            if elem.condition:
                raise GroundError("conditional choice elements are not supported")
            if not isinstance(elem.literal, ast.LiteralSymbolic):
                raise GroundError(f"unsupported choice element: {elem.literal}")
            head_sigs.append(atom_signature(elem.literal.atom))
        return _Rule(_Kind.CHOICE, stm.location, head, body, head_sigs, body_sigs)

    raise GroundError(f"unsupported rule head: {type(head).__name__}")


# --- head atoms ------------------------------------------------------------


def _head_atoms(rule: _Rule, asgn: Assignment, lib: Library) -> list[Symbol]:
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
            sym = eval_term(elem.literal.atom, asgn, lib)
            assert sym is not None
            atoms.append(sym)
        return atoms
    return []


# --- domain and fact fixpoints ---------------------------------------------


def _domain_fixpoint(rules: list[_Rule], base: AtomBase, lib: Library) -> None:
    """Add every possibly-true atom of ``rules`` to ``base`` (ignoring negation)."""
    changed = True
    while changed:
        changed = False
        for rule in rules:
            for asgn in match_body(rule.body, {}, base, lib):
                try:
                    atoms = _head_atoms(rule, asgn, lib)
                except _Undefined:
                    continue
                for sym in atoms:
                    if base.add(sym):
                        changed = True


def _body_is_fact_true(
    rule: _Rule, asgn: Assignment, base: AtomBase, lib: Library
) -> bool:
    """True iff the matched body is trivially true (so a normal head is a fact).

    A positive atom must be a fact; a (single) negated atom must be impossible
    (not in the domain); comparisons/booleans already held during matching.
    Double negation is treated conservatively as non-trivial.
    """
    for blit in rule.body:
        lit = _simple_literal(blit)
        if not isinstance(lit, ast.LiteralSymbolic):
            continue
        sym = eval_term(lit.atom, asgn, lib)
        assert sym is not None
        if lit.sign == ast.Sign.NoSign:
            if not base.is_fact(sym):
                return False
        elif lit.sign == ast.Sign.Single:
            if base.is_possible(sym):
                return False
        else:  # Sign.Double: keep conservatively
            return False
    return True


def _fact_fixpoint(rules: list[_Rule], base: AtomBase, lib: Library) -> None:
    """Mark as facts the atoms derivable by a normal rule with a trivially-true body."""
    changed = True
    while changed:
        changed = False
        for rule in rules:
            if rule.kind != _Kind.NORMAL:
                continue
            for asgn in match_body(rule.body, {}, base, lib):
                if not _body_is_fact_true(rule, asgn, base, lib):
                    continue
                try:
                    (sym,) = _head_atoms(rule, asgn, lib)
                except _Undefined:
                    continue
                if base.add_fact(sym):
                    changed = True


# --- output construction ---------------------------------------------------


def _symbol_literal(
    lib: Library, loc: Location, sym: Symbol, sign: ast.Sign
) -> ast.LiteralSymbolic:
    return ast.LiteralSymbolic(lib, loc, sign, ast.TermSymbolic(lib, loc, sym))


def _build_body(
    rule: _Rule, asgn: Assignment, base: AtomBase, lib: Library
) -> list[ast.BodyLiteral] | None:
    """Render the matched body as ground literals, simplifying from atom states.

    Returns ``None`` if the rule is killed (a negated atom is a fact).  Positive
    facts and impossible negative literals are dropped (trivially true);
    comparisons/booleans are dropped (verified during matching).
    """
    loc = rule.location
    out: list[ast.BodyLiteral] = []
    for blit in rule.body:
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
        (sym,) = _head_atoms(rule, asgn, lib)
        head = ast.HeadSimpleLiteral(
            lib, _symbol_literal(lib, loc, sym, ast.Sign.NoSign)
        )
        return ast.StatementRule(lib, loc, head, body)

    # choice
    assert isinstance(rule.head, ast.HeadAggregate)
    elements: list[ast.HeadAggregateElement] = []
    for sym in _head_atoms(rule, asgn, lib):
        term = ast.TermSymbolic(lib, loc, sym)
        literal = ast.LiteralSymbolic(lib, loc, ast.Sign.NoSign, term)
        elements.append(ast.HeadAggregateElement(lib, loc, [term], literal, []))
    head = ast.HeadAggregate(
        lib, loc, None, ast.AggregateFunction.Count, elements, None
    )
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
    nodes: dict[Signature, None] = {}
    edges: list[tuple[Signature, Signature]] = []
    for rule in rules:
        for sig in (*rule.head_sigs, *rule.body_sigs):
            nodes.setdefault(sig, None)
        for head_sig in rule.head_sigs:
            for sig in rule.body_sigs:
                edges.append((sig, head_sig))

    components = order_components(nodes, edges)
    comp_index = {sig: i for i, comp in enumerate(components) for sig in comp}
    for rule in rules:
        rule.component = max((comp_index[s] for s in rule.head_sigs), default=0)

    # Per component (dependency order): domain fixpoint, then fact fixpoint.
    base = AtomBase()
    by_component = [
        [r for r in rules if r.component == ci] for ci in range(len(components))
    ]
    for comp_rules in by_component:
        _domain_fixpoint(comp_rules, base, lib)
        _fact_fixpoint(comp_rules, base, lib)

    # Emit once all atom states are final: rules (dependency order), then constraints.
    out: list[ast.Statement] = []
    seen: set[str] = set()
    for comp_rules in by_component:
        for rule in comp_rules:
            _emit(rule, base, lib, out, seen)
    for rule in constraints:
        _emit(rule, base, lib, out, seen)

    return out
