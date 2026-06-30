"""Tests for the cost-based matcher reordering (:mod:`pygringo._order`)."""

from __future__ import annotations

from clingo import ast
from clingo.core import Library
from clingo.symbol import Function, Number

import pygringo._ground as engine
from pygringo._atombase import AtomBase
from pygringo._order import _term_score, linearize
from safety import check_safety


def _one_rule(program: str) -> tuple[Library, engine._Rule]:
    """Parse, normalise and safety-check ``program``, returning its single rule."""
    lib = Library()
    statements: list[ast.Statement] = []
    ast.parse_string(lib, program, statements.append)
    ctx = ast.RewriteContext(lib)
    rules: list[engine._Rule] = []
    for stm in statements:
        if not isinstance(stm, ast.StatementRule):
            continue
        for normalised in ast.rewrite_statement(ctx, stm):
            result = check_safety(lib, normalised)
            assert result.safe
            assert isinstance(result.statement, ast.StatementRule)
            rules.append(engine._classify(result.statement))
    (rule,) = [r for r in rules if r.kind != engine._Kind.CONSTRAINT or r.body]
    return lib, rule


def _atom(lib: Library, atom: str) -> ast.Term:
    statements: list[ast.Statement] = []
    ast.parse_string(lib, f"p :- {atom}.", statements.append)
    rule = next(s for s in statements if isinstance(s, ast.StatementRule))
    blit = rule.body[0]
    assert isinstance(blit, ast.BodySimpleLiteral)
    assert isinstance(blit.literal, ast.LiteralSymbolic)
    return blit.literal.atom


def test_term_score_bound_vs_free() -> None:
    lib = Library()
    atom = _atom(lib, "q(X)")  # arity 1: root = (size/2)**1 = size/2
    assert _term_score(atom, 100.0, frozenset()) == 50.0
    assert _term_score(atom, 100.0, frozenset({"X"})) == 0.0


def test_linearize_prefers_selective_relation() -> None:
    # `sel` has one atom, `big` has a hundred; both bind X, so the selective one
    # should be matched first (after which `big(X)` and `X < 5` are mere checks).
    lib, rule = _one_rule("r(X) :- big(X), sel(X), X < 5.")
    base = AtomBase()
    for i in range(100):
        base.add(Function(lib, "big", [Number(lib, i)]))
    base.add(Function(lib, "sel", [Number(lib, 1)]))

    order = linearize(rule.body, rule.deps, None, base)
    assert "sel" in str(rule.body[order[0]])


def test_linearize_delta_first_for_semi_naive() -> None:
    # `edge` is tiny and `reach` large, so by size alone `edge` would go first;
    # but the semi-naive delta literal (`reach`) must sort first among generating
    # matchers so the first-new enumeration stays correct.
    lib, rule = _one_rule("reach(Y) :- reach(X), edge(X,Y).")
    base = AtomBase()
    for i in range(50):
        base.add(Function(lib, "reach", [Number(lib, i)]))
    base.add(Function(lib, "edge", [Number(lib, 0), Number(lib, 1)]))

    delta = next(i for i, b in enumerate(rule.body) if "reach" in str(b))
    order = linearize(rule.body, rule.deps, delta, base)
    assert order[0] == delta


def test_order_is_a_permutation() -> None:
    lib, rule = _one_rule("r(X,Z) :- a(X), b(X,Y), c(Y,Z), X < Z.")
    base = AtomBase()
    order = linearize(rule.body, rule.deps, None, base)
    assert sorted(order) == list(range(len(rule.body)))
