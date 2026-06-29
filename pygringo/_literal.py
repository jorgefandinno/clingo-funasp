"""Body-literal matchers.

Port of the matching half of ``literal.hh`` / ``matcher.hh`` for the literal
kinds in scope: symbolic atoms (positive and negative), comparisons, intervals
and the boolean constants.  Each matcher is a generator that, given a partial
:data:`~pygringo._term.Assignment`, yields every extension of it under which the
literal holds.  Comparisons may *provide* bindings (the equality ``X = expr``)
or merely *check* (e.g. ``X < Y``); the input is assumed to be in groundable
order, as produced by :func:`safety.check_safety`.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import singledispatch
from typing import Any

from clingo import ast
from clingo.core import Library
from clingo.symbol import Number, Symbol

from ._atombase import AtomBase
from ._error import GroundError, _Undefined
from ._term import Assignment, atom_signature, eval_term, interval_bounds, match_term


def _relation_holds(rel: ast.Relation, left: Symbol, right: Symbol) -> bool:
    if rel == ast.Relation.Equal:
        return bool(left == right)
    if rel == ast.Relation.NotEqual:
        return bool(left != right)
    if rel == ast.Relation.Less:
        return bool(left < right)
    if rel == ast.Relation.LessEqual:
        return bool(left <= right)
    if rel == ast.Relation.Greater:
        return bool(left > right)
    return bool(left >= right)  # GreaterEqual


@singledispatch
def match_literal(
    lit: Any, asgn: Assignment, base: AtomBase, lib: Library
) -> Iterator[Assignment]:
    raise GroundError(f"unsupported literal: {type(lit).__name__} ({lit})")


@match_literal.register
def _(
    lit: ast.LiteralSymbolic, asgn: Assignment, base: AtomBase, lib: Library
) -> Iterator[Assignment]:
    atom = lit.atom
    name, arity, positive = atom_signature(atom)
    if lit.sign == ast.Sign.NoSign:
        # Positive: join against every domain atom with a matching signature.
        for sym in base.by_signature(name, arity, positive):
            candidate = dict(asgn)
            if match_term(atom, sym, candidate, lib):
                yield candidate
        return
    # Negative literals never bind variables (safety guarantees they are bound by
    # earlier positive literals); here we only enumerate, confirming the atom is
    # ground and yielding once.  Whether the literal is kept, dropped or kills the
    # rule is decided later from the atom's fact/domain state (see ``_ground``).
    sym = eval_term(atom, asgn, lib)
    if sym is None:
        raise GroundError(f"unbound variable in negative literal: {lit}")
    yield asgn


@match_literal.register
def _(
    lit: ast.LiteralComparison, asgn: Assignment, base: AtomBase, lib: Library
) -> Iterator[Assignment]:
    if len(lit.right) != 1:
        raise GroundError(f"non-normalised multi-guard comparison: {lit}")
    guard = lit.right[0]
    left, right, rel = lit.left, guard.term, guard.relation
    negated = lit.sign != ast.Sign.NoSign

    # Interval ``X = lo..hi``: enumerate the range and bind the other side.
    if rel == ast.Relation.Equal and not negated:
        bounds = interval_bounds(right, asgn, lib)
        target = left
        if bounds is None:
            bounds = interval_bounds(left, asgn, lib)
            target = right
        if bounds is not None:
            lo, hi = bounds
            for value in range(lo, hi + 1):
                candidate = dict(asgn)
                if match_term(target, Number(lib, value), candidate, lib):
                    yield candidate
            return

    left_value = eval_term(left, asgn, lib)
    right_value = eval_term(right, asgn, lib)

    # Equality that provides a binding for the unevaluated side.
    if rel == ast.Relation.Equal and not negated:
        if left_value is None and right_value is not None:
            candidate = dict(asgn)
            if match_term(left, right_value, candidate, lib):
                yield candidate
            return
        if right_value is None and left_value is not None:
            candidate = dict(asgn)
            if match_term(right, left_value, candidate, lib):
                yield candidate
            return

    # Otherwise both sides must be evaluable and we simply check the relation.
    if left_value is None or right_value is None:
        raise GroundError(f"comparison not in groundable order: {lit}")
    holds = _relation_holds(rel, left_value, right_value)
    if negated:
        holds = not holds
    if holds:
        yield asgn


@match_literal.register
def _(
    lit: ast.LiteralBoolean, asgn: Assignment, base: AtomBase, lib: Library
) -> Iterator[Assignment]:
    holds = lit.value if lit.sign == ast.Sign.NoSign else not lit.value
    if holds:
        yield asgn


def match_body(
    body: list[ast.BodyLiteral], asgn: Assignment, base: AtomBase, lib: Library
) -> Iterator[Assignment]:
    """Yield every assignment extending ``asgn`` under which the whole body holds.

    The body literals are matched left to right (the groundable order); arithmetic
    that is undefined for a particular binding prunes that branch, mirroring
    clingo's *operation undefined* behaviour.
    """
    if not body:
        yield asgn
        return
    first, rest = body[0], body[1:]
    if not isinstance(first, ast.BodySimpleLiteral):
        raise GroundError(f"unsupported body literal: {first}")
    try:
        extensions = list(match_literal(first.literal, asgn, base, lib))
    except _Undefined:
        return
    for extended in extensions:
        yield from match_body(rest, extended, base, lib)
