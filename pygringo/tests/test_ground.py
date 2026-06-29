"""End-to-end tests for :func:`pygringo.ground`.

The primary check is *differential*: pygringo's grounding must have exactly the
same answer sets as clingo's own grounding of the same program (``util``).  A few
small programs are also checked against an exact expected ground program.
"""

from __future__ import annotations

import pytest
from clingo import ast
from clingo.core import Library

from pygringo import GroundError, ground

from .util import assert_equivalent, ground_program

DIFFERENTIAL_PROGRAMS = [
    # facts only
    "a. b. c.",
    "q(1). q(2). q(3).",
    # projection / simple rule
    "q(1). q(2). p(X) :- q(X).",
    # joins over two predicates
    "edge(a,b). edge(b,c). edge(c,a). path(X,Y) :- edge(X,Y).",
    # positive recursion (reachability)
    "reach(a). edge(a,b). edge(b,c). edge(c,d). reach(Y) :- reach(X), edge(X,Y).",
    # transitive closure
    "e(1,2). e(2,3). e(3,4). t(X,Y) :- e(X,Y). t(X,Z) :- t(X,Y), e(Y,Z).",
    # arithmetic in the head
    "num(1). num(2). num(3). succ(X+1) :- num(X).",
    # intervals
    "p(1..5).",
    "grid(X,Y) :- X=1..3, Y=1..2.",
    # comparisons as guards
    "q(1..10). small(X) :- q(X), X<4.",
    "q(1..5). pair(X,Y) :- q(X), q(Y), X<Y.",
    # stratified negation
    "q(1..4). even(2). even(4). odd(X) :- q(X), not even(X).",
    # integrity constraint
    "q(1..3). :- q(X), q(Y), X<Y.",
    "{ a; b }. :- a, b.",
    # choice rules
    "{ p(X) } :- q(X). q(1). q(2).",
    "dom(1..3). { sel(X) } :- dom(X).",
    # choice + constraint interaction
    "dom(1..3). { sel(X) } :- dom(X). :- sel(X), sel(Y), X<Y.",
    # negation feeding a constraint
    "q(1..3). p(2). :- q(X), not p(X), X>1.",
    # multiple strata
    "a(1..3). b(X) :- a(X), not c(X). c(2). d(X) :- b(X), X>1.",
]


@pytest.mark.parametrize("program", DIFFERENTIAL_PROGRAMS)
def test_differential(program: str) -> None:
    assert_equivalent(program)


def test_exact_projection() -> None:
    grounded = ground_program("q(1). q(2). p(X) :- q(X).")
    assert grounded.splitlines() == [
        "q(1).",
        "q(2).",
        "p(1) :- q(1).",
        "p(2) :- q(2).",
    ]


def test_exact_interval() -> None:
    grounded = ground_program("p(1..3).")
    assert grounded.splitlines() == ["p(1).", "p(2).", "p(3)."]


def test_exact_arithmetic() -> None:
    grounded = ground_program("num(2). twice(X+X) :- num(X).")
    assert grounded.splitlines() == ["num(2).", "twice(4) :- num(2)."]


def _statements(lib: Library, program: str) -> list[ast.Statement]:
    out: list[ast.Statement] = []
    ast.parse_string(lib, program, out.append)
    return out


@pytest.mark.parametrize(
    "program",
    [
        "p(X) :- q(Y).",  # X unsafe
        "p(X).",  # X unsafe (fact with variable)
    ],
)
def test_unsafe_raises(program: str) -> None:
    lib = Library()
    with pytest.raises(GroundError):
        ground(lib, _statements(lib, program))


@pytest.mark.parametrize(
    "program",
    [
        "a; b.",  # disjunction
        "1 { a; b } 2.",  # bounded aggregate
        "#minimize { 1 : a }.",  # optimize
        "{ p(X) : q(X) } :- r(X).",  # conditional choice element
        "p :- not q. q :- not p.",  # recursion through negation
    ],
)
def test_unsupported_raises(program: str) -> None:
    lib = Library()
    with pytest.raises(GroundError):
        ground(lib, _statements(lib, program))
