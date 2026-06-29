"""Unit tests for :mod:`pygringo._term`."""

from __future__ import annotations

import pytest
from clingo import ast
from clingo.core import Library
from clingo.symbol import Number, Symbol

from pygringo._error import GroundError, _Undefined
from pygringo._term import (
    Assignment,
    atom_signature,
    eval_term,
    interval_bounds,
    match_term,
)


def _term(lib: Library, text: str) -> ast.Term:
    return ast.parse_term(lib, text)


def _num(lib: Library, value: int) -> Symbol:
    return Number(lib, value)


def test_eval_arithmetic() -> None:
    lib = Library()
    asgn: Assignment = {"X": _num(lib, 4)}
    assert eval_term(_term(lib, "1*X+1"), asgn, lib) == _num(lib, 5)
    assert eval_term(_term(lib, "X*X"), asgn, lib) == _num(lib, 16)
    assert eval_term(_term(lib, "7/2"), {}, lib) == _num(lib, 3)
    assert eval_term(_term(lib, "-7/2"), {}, lib) == _num(lib, -3)  # truncates to zero
    assert eval_term(_term(lib, "7\\2"), {}, lib) == _num(lib, 1)
    assert eval_term(_term(lib, "|3-10|"), {}, lib) == _num(lib, 7)
    assert eval_term(_term(lib, "2**5"), {}, lib) == _num(lib, 32)


def test_eval_unbound_returns_none() -> None:
    lib = Library()
    assert eval_term(_term(lib, "X"), {}, lib) is None
    assert eval_term(_term(lib, "f(X,1)"), {}, lib) is None


def test_eval_compound() -> None:
    lib = Library()
    asgn: Assignment = {"X": _num(lib, 2), "Y": _num(lib, 3)}
    assert str(eval_term(_term(lib, "f(X,Y)"), asgn, lib)) == "f(2,3)"
    assert str(eval_term(_term(lib, "(X,Y)"), asgn, lib)) == "(2,3)"


def test_eval_undefined() -> None:
    lib = Library()
    with pytest.raises(_Undefined):
        eval_term(_term(lib, "1/0"), {}, lib)
    with pytest.raises(_Undefined):
        eval_term(_term(lib, '"x"+1'), {}, lib)


def _sym(lib: Library, text: str) -> Symbol:
    """Build a ground symbol by evaluating its parsed term."""
    value = eval_term(ast.parse_term(lib, text), {}, lib)
    assert value is not None
    return value


def test_match_function() -> None:
    lib = Library()
    asgn: Assignment = {}
    assert match_term(_term(lib, "f(X,Y)"), _sym(lib, "f(1,2)"), asgn, lib)
    assert asgn == {"X": _num(lib, 1), "Y": _num(lib, 2)}


def test_match_consistency() -> None:
    lib = Library()
    assert match_term(_term(lib, "f(X,X)"), _sym(lib, "f(1,1)"), {}, lib)
    assert not match_term(_term(lib, "f(X,X)"), _sym(lib, "f(1,2)"), {}, lib)


def test_match_linear_inversion() -> None:
    lib = Library()
    asgn: Assignment = {}
    # q(1*X+1) against q(7) binds X = 6
    assert match_term(_term(lib, "1*X+1"), _num(lib, 7), asgn, lib)
    assert asgn == {"X": _num(lib, 6)}
    # non-divisible => no match
    assert not match_term(_term(lib, "2*Y+0"), _num(lib, 5), {}, lib)


def test_interval_bounds() -> None:
    lib = Library()
    ctx = ast.RewriteContext(lib)
    stm = ast.rewrite_statement(ctx, ast.parse_statement(lib, "p(1..3)."))[0]
    assert isinstance(stm, ast.StatementRule)
    blit = stm.body[0]
    assert isinstance(blit, ast.BodySimpleLiteral)
    comp = blit.literal
    assert isinstance(comp, ast.LiteralComparison)
    assert interval_bounds(comp.right[0].term, {}, lib) == (1, 3)
    assert interval_bounds(_term(lib, "5"), {}, lib) is None


def test_atom_signature() -> None:
    lib = Library()
    assert atom_signature(_term(lib, "p(X,Y)")) == ("p", 2, True)
    ground = ast.parse_term(lib, "q(1)")
    assert atom_signature(ground) == ("q", 1, True)
    with pytest.raises(GroundError):
        atom_signature(_term(lib, "X"))
