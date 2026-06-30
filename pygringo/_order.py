"""Cost-based matcher reordering.

Port of the core of clingo's body linearizer (``Ground::Linearizer::order_`` in
``lib/ground/src/statement.cc``; see ``pygringo/matcher-ordering.md``).  A rule
body is a join over relations, and the order in which its literals are matched
decides how large the intermediate result sets get.  :func:`linearize` greedily
orders a body by estimated cost: cheap filters first, then the most selective
generating matcher, keeping the semi-naive *delta* literal in a valid slot.

This reorders only the *evaluation* of a join, never its result set, so grounding
output is unchanged -- only the fixpoint's efficiency.  The ``AssignmentAnalyzer``
back-substitution refinement of the C++ code is intentionally not ported.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cmp_to_key

from clingo import ast
from clingo.symbol import SymbolType

from safety import check_linear

from ._atombase import AtomBase
from ._term import _arguments, _is_interval, atom_signature

#: Score of a non-generating matcher (a filter or assignment): scheduled first.
_SCORE_FAST = -1.0

#: ``(provide, depend)`` variable-name sets of one body literal.
Dep = tuple[frozenset[str], frozenset[str]]


def _term_score(term: ast.Term, size: float, bound: frozenset[str] | set[str]) -> float:
    """Estimate how many atoms an argument term contributes (clingo ``Term::score``).

    An unbound variable spreads the relation ``size``; a bound variable or a
    constant is fully selective (``0``); a function/tuple of arity ``k`` spreads
    the size as roughly its ``k``-th root across the arguments.
    """
    if isinstance(term, ast.TermVariable):
        return 0.0 if term.name in bound else size
    if isinstance(term, ast.TermSymbolic):
        return 0.0
    if isinstance(term, ast.TermBinaryOperation):
        if _is_interval(term):
            return 0.0
        name = check_linear(term)  # canonical m*X+n binds X
        if name is not None:
            return 0.0 if name in bound else size
        return 0.0
    if isinstance(term, ast.TermUnaryOperation):
        if term.operator_type == ast.UnaryOperator.Minus:
            return _term_score(term.right, size, bound)
        return 0.0
    if isinstance(term, ast.TermFunction):
        args = _arguments(term)
        if not args:
            return 0.0
        root = max(1.0, (size / 2.0) ** (1.0 / len(args)))
        return sum(_term_score(a, root, bound) for a in args) / len(args)
    if isinstance(term, ast.TermTuple):
        args = _arguments(term)
        if not args:
            return 0.0
        root = size ** (1.0 / len(args)) if size > 0 else 0.0
        return sum(_term_score(a, root, bound) for a in args) / len(args)
    return 0.0


def _const_number(term: ast.Term) -> int | None:
    if isinstance(term, ast.TermSymbolic) and term.symbol.type == SymbolType.Number:
        return term.symbol.number
    return None


def _interval_node(lit: ast.Literal) -> ast.TermBinaryOperation | None:
    """Return the interval term of an ``X = lo..hi`` comparison, else ``None``."""
    if not isinstance(lit, ast.LiteralComparison) or lit.sign != ast.Sign.NoSign:
        return None
    if len(lit.right) != 1 or lit.right[0].relation != ast.Relation.Equal:
        return None
    for node in (lit.right[0].term, lit.left):
        if isinstance(node, ast.TermBinaryOperation) and _is_interval(node):
            return node
    return None


def _interval_range(node: ast.TermBinaryOperation) -> float:
    """Estimate an interval's size (clingo ``LitInterval::do_score``)."""
    lo = _const_number(node.left)
    hi = _const_number(node.right)
    if lo is not None and hi is not None:
        return float(max(0, hi - lo))
    return 100.0  # non-constant bounds: a fixed, deliberately large estimate


def _literal_score(
    blit: ast.BodyLiteral,
    provide: frozenset[str],
    bound: frozenset[str] | set[str],
    base: AtomBase,
) -> float:
    """Estimate the cost of matching ``blit`` given the currently bound variables.

    Negative is a fast, non-generating matcher (filter/assignment) to run first;
    a positive number estimates how many atoms a generating matcher yields.
    """
    if provide <= bound:
        return _SCORE_FAST  # binds nothing new: a lookup/filter
    if isinstance(blit, ast.BodyAggregate):
        return _SCORE_FAST  # transparent / pure filter (assignments are rejected)
    if isinstance(blit, ast.BodySimpleLiteral):
        lit = blit.literal
        if isinstance(lit, ast.LiteralSymbolic):
            if lit.sign != ast.Sign.NoSign:
                return _SCORE_FAST  # negative literal: a filter
            name, arity, positive = atom_signature(lit.atom)
            return _term_score(lit.atom, float(base.size(name, arity, positive)), bound)
        if isinstance(lit, ast.LiteralComparison):
            node = _interval_node(lit)
            return _interval_range(node) if node is not None else _SCORE_FAST
    return _SCORE_FAST


def linearize(
    body: Sequence[ast.BodyLiteral],
    deps: Sequence[Dep],
    delta: int | None,
    base: AtomBase,
) -> list[int]:
    """Return a visiting permutation of ``body`` indices ordered by estimated cost.

    A literal is *ready* once every variable in its ``depend`` set is bound.  Each
    step re-scores the ready literals (binding a variable can turn a scan into a
    lookup) and takes the cheapest, breaking ties by original position.  The
    semi-naive ``delta`` literal sorts first among generating matchers so the
    first-new enumeration stays correct (cf. the C++ ``order_`` comparator).
    """
    n = len(body)
    placed = [False] * n
    bound: set[str] = set()
    order: list[int] = []

    def is_new(i: int) -> bool:
        return delta is not None and i == delta

    while len(order) < n:
        ready = [i for i in range(n) if not placed[i] and deps[i][1] <= bound]
        if not ready:  # safety guarantees a groundable order; stay robust anyway
            ready = [i for i in range(n) if not placed[i]]
        scores = {i: _literal_score(body[i], deps[i][0], bound, base) for i in ready}

        def cmp(i: int, j: int) -> int:
            si, sj = scores[i], scores[j]
            if (is_new(i) or is_new(j)) and si >= 0 and sj >= 0:
                return -1 if is_new(i) else 1
            if si != sj:
                return -1 if si < sj else 1
            return -1 if i < j else 1

        best = min(ready, key=cmp_to_key(cmp))
        order.append(best)
        placed[best] = True
        bound |= deps[best][0]
    return order
