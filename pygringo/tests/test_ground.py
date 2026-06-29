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
    # negation against a possibly-true (choice) atom -- the regression case
    "{a}. b :- not a.",
    "{ q(X) } :- dom(X). dom(1..2). p(X) :- dom(X), not q(X).",
    # non-stratified negation (recursion through negation)
    "p :- not q. q :- not p.",
    "a. p :- not q. q :- not p.",
    "p :- not q. q :- not p. r :- p. r :- q.",
    "p :- not p.",  # no answer set
    # even/odd loop through negation
    "n(1..4). even(X) :- n(X), not odd(X). odd(X) :- n(X), not even(X).",
    # non-stratified negation combined with a constraint
    "{a;b}. p :- not q. q :- not p. :- p, a. :- q, b.",
]


@pytest.mark.parametrize("program", DIFFERENTIAL_PROGRAMS)
def test_differential(program: str) -> None:
    assert_equivalent(program)


def test_exact_projection() -> None:
    # Positive body atoms that are facts are dropped, so derived atoms whose body
    # is trivially true become facts themselves.
    grounded = ground_program("q(1). q(2). p(X) :- q(X).")
    assert grounded.splitlines() == ["q(1).", "q(2).", "p(1).", "p(2)."]


def test_exact_interval() -> None:
    grounded = ground_program("p(1..3).")
    assert grounded.splitlines() == ["p(1).", "p(2).", "p(3)."]


def test_exact_arithmetic() -> None:
    grounded = ground_program("num(2). twice(X+X) :- num(X).")
    assert grounded.splitlines() == ["num(2).", "twice(4)."]


def test_exact_negation_kept_for_possible_atom() -> None:
    # `a` is only possibly true (a choice atom), so `not a` is kept for the solver.
    grounded = ground_program("{a}. b :- not a.")
    assert grounded.splitlines() == ["#count { a: a }.", "b :- not a."]


def test_exact_negation_simplified() -> None:
    # `not even(2)` kills odd(2) (even(2) is a fact); `not even(1)` is dropped as
    # trivially true (even(1) is not in the domain), so odd(1) becomes a fact.
    grounded = ground_program("q(1..2). even(2). odd(X) :- q(X), not even(X).")
    assert grounded.splitlines() == ["even(2).", "q(1).", "q(2).", "odd(1)."]


def test_queue_reactivates_selectively(monkeypatch: pytest.MonkeyPatch) -> None:
    """The instantiator queue re-runs a rule only when a watched predicate grows.

    Seed rules (empty/static body) are instantiated once, in generation 0; the
    recursive rule is re-activated across generations as ``reach`` grows.  Under a
    per-generation scheme every rule would run once per generation instead.
    """
    import pygringo._ground as engine

    domain_body_lengths: list[int] = []
    original = engine._join

    def spy(
        body: object,
        index: int,
        *args: object,
        **kwargs: object,
    ) -> object:
        facts = args[-1] if args else kwargs.get("facts")
        if index == 0 and facts is False:
            domain_body_lengths.append(len(body))  # type: ignore[arg-type]
        return original(body, index, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "_join", spy)
    ground_program("reach(a). edge(a,b). edge(b,c). reach(Y) :- reach(X), edge(X,Y).")

    # Three seed rules (reach(a)., edge(a,b)., edge(b,c).) each instantiated once.
    assert domain_body_lengths.count(0) == 3
    # The recursive rule (body length 2) is re-activated across several generations.
    assert domain_body_lengths.count(2) >= 2


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
    ],
)
def test_unsupported_raises(program: str) -> None:
    lib = Library()
    with pytest.raises(GroundError):
        ground(lib, _statements(lib, program))
