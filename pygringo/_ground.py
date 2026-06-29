"""The grounding pipeline.

Ties the pieces together into :func:`ground`, which turns a non-ground program
into a list of variable-free :class:`clingo.ast` statements.  The pipeline
mirrors the C++ grounder at a high level:

1. **normalise** every statement with :func:`clingo.ast.rewrite_statement`
   (unpooling, canonicalising arithmetic into ``m*X+n``, turning intervals into
   ``X = lo..hi`` comparisons) -- the precondition the ``safety`` pilot assumes;
2. **check safety** and obtain the body in *groundable order* via
   :func:`safety.check_safety`;
3. **stratify** the predicates into dependency components (:mod:`._depend`);
4. **instantiate** each component with a bottom-up fixpoint, joining body
   literals over the :class:`AtomBase` (:mod:`._literal`) and emitting the ground
   rules;
5. ground the integrity **constraints** over the completed atom base.

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
    body_sigs: list[tuple[Signature, bool]]
    component: int = -1


# --- classification --------------------------------------------------------


def _simple_literal(blit: ast.BodyLiteral) -> ast.Literal:
    """Return the literal of a simple body literal, rejecting other body kinds."""
    if not isinstance(blit, ast.BodySimpleLiteral):
        raise GroundError(f"unsupported body literal: {blit}")
    return blit.literal


def _body_signatures(body: Sequence[ast.BodyLiteral]) -> list[tuple[Signature, bool]]:
    sigs: list[tuple[Signature, bool]] = []
    for blit in body:
        lit = _simple_literal(blit)
        if isinstance(lit, ast.LiteralSymbolic):
            sigs.append((atom_signature(lit.atom), lit.sign != ast.Sign.NoSign))
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


# --- output construction ---------------------------------------------------


def _symbol_literal(
    lib: Library, loc: Location, sym: Symbol, sign: ast.Sign
) -> ast.LiteralSymbolic:
    return ast.LiteralSymbolic(lib, loc, sign, ast.TermSymbolic(lib, loc, sym))


def _ground_body(rule: _Rule, asgn: Assignment, lib: Library) -> list[ast.BodyLiteral]:
    """Render the matched body as ground symbolic literals.

    Comparisons and boolean literals are dropped: they were verified during
    matching, so the surviving rule instance only carries its (ground) atoms.
    """
    out: list[ast.BodyLiteral] = []
    for blit in rule.body:
        lit = _simple_literal(blit)
        if isinstance(lit, ast.LiteralSymbolic):
            sym = eval_term(lit.atom, asgn, lib)
            assert sym is not None  # body variables are bound after a full match
            out.append(
                ast.BodySimpleLiteral(
                    lib, _symbol_literal(lib, rule.location, sym, lit.sign)
                )
            )
    return out


def _emit_normal(
    rule: _Rule,
    asgn: Assignment,
    base: AtomBase,
    lib: Library,
    out: list[ast.Statement],
    seen: set[str],
) -> bool:
    assert isinstance(rule.head, ast.HeadSimpleLiteral)
    assert isinstance(rule.head.literal, ast.LiteralSymbolic)
    sym = eval_term(rule.head.literal.atom, asgn, lib)
    assert sym is not None
    is_new = base.add(sym)
    head = ast.HeadSimpleLiteral(
        lib, _symbol_literal(lib, rule.location, sym, ast.Sign.NoSign)
    )
    stm = ast.StatementRule(lib, rule.location, head, _ground_body(rule, asgn, lib))
    _record(stm, out, seen)
    return is_new


def _emit_choice(
    rule: _Rule,
    asgn: Assignment,
    base: AtomBase,
    lib: Library,
    out: list[ast.Statement],
    seen: set[str],
) -> bool:
    assert isinstance(rule.head, ast.HeadAggregate)
    loc = rule.location
    elements: list[ast.HeadAggregateElement] = []
    is_new = False
    for elem in rule.head.elements:
        assert isinstance(elem.literal, ast.LiteralSymbolic)
        sym = eval_term(elem.literal.atom, asgn, lib)
        assert sym is not None
        is_new = base.add(sym) or is_new
        term = ast.TermSymbolic(lib, loc, sym)
        literal = ast.LiteralSymbolic(lib, loc, ast.Sign.NoSign, term)
        elements.append(ast.HeadAggregateElement(lib, loc, [term], literal, []))
    head = ast.HeadAggregate(
        lib, loc, None, ast.AggregateFunction.Count, elements, None
    )
    stm = ast.StatementRule(lib, loc, head, _ground_body(rule, asgn, lib))
    _record(stm, out, seen)
    return is_new


def _emit_constraint(
    rule: _Rule,
    asgn: Assignment,
    lib: Library,
    out: list[ast.Statement],
    seen: set[str],
) -> None:
    stm = ast.StatementRule(
        lib, rule.location, rule.head, _ground_body(rule, asgn, lib)
    )
    _record(stm, out, seen)


def _record(stm: ast.Statement, out: list[ast.Statement], seen: set[str]) -> None:
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

    # Dependency components over predicate signatures.
    nodes: set[Signature] = set()
    edges: list[tuple[Signature, Signature, bool]] = []
    for rule in rules:
        nodes.update(rule.head_sigs)
        for sig, _ in rule.body_sigs:
            nodes.add(sig)
        for head_sig in rule.head_sigs:
            for sig, negative in rule.body_sigs:
                edges.append((sig, head_sig, negative))

    components = order_components(nodes, edges)
    comp_index = {sig: i for i, comp in enumerate(components) for sig in comp}
    for rule in rules:
        rule.component = max((comp_index[s] for s in rule.head_sigs), default=0)

    # Bottom-up fixpoint, component by component.
    base = AtomBase()
    out: list[ast.Statement] = []
    seen: set[str] = set()
    for ci in range(len(components)):
        comp_rules = [r for r in rules if r.component == ci]
        changed = True
        while changed:
            changed = False
            for rule in comp_rules:
                for asgn in match_body(rule.body, {}, base, lib):
                    try:
                        if rule.kind == _Kind.NORMAL:
                            new = _emit_normal(rule, asgn, base, lib, out, seen)
                        else:
                            new = _emit_choice(rule, asgn, base, lib, out, seen)
                    except _Undefined:
                        continue
                    changed = changed or new

    # Constraints derive nothing; ground them once over the completed base.
    for rule in constraints:
        for asgn in match_body(rule.body, {}, base, lib):
            try:
                _emit_constraint(rule, asgn, lib, out, seen)
            except _Undefined:
                continue

    return out
