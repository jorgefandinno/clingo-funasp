"""Unit tests for :mod:`pygringo._atombase`."""

from __future__ import annotations

from clingo.core import Library
from clingo.symbol import Function, Number, Symbol

from pygringo._atombase import AtomBase, signature_of


def _atom(lib: Library, name: str, *args: int) -> Symbol:
    return Function(lib, name, [Number(lib, a) for a in args])


def test_signature_of() -> None:
    lib = Library()
    assert signature_of(_atom(lib, "p", 1, 2)) == ("p", 2, True)
    assert signature_of(Function(lib, "a", [])) == ("a", 0, True)


def test_add_is_monotone_and_deduplicates() -> None:
    lib = Library()
    base = AtomBase()
    p1 = _atom(lib, "p", 1)
    assert base.add(p1) is True
    assert base.add(p1) is False
    assert base.is_possible(p1)
    assert not base.is_possible(_atom(lib, "p", 2))


def test_facts_are_a_subset_of_possible() -> None:
    lib = Library()
    base = AtomBase()
    p1 = _atom(lib, "p", 1)
    assert base.add_fact(p1) is True
    assert base.add_fact(p1) is False  # already a fact
    assert base.is_fact(p1)
    assert base.is_possible(p1)  # a fact is always possible
    # a merely-possible atom is not a fact
    p2 = _atom(lib, "p", 2)
    base.add(p2)
    assert base.is_possible(p2)
    assert not base.is_fact(p2)


def test_by_signature_preserves_insertion_order() -> None:
    lib = Library()
    base = AtomBase()
    for i in (3, 1, 2):
        base.add(_atom(lib, "q", i))
    base.add(_atom(lib, "r", 9))
    got = [s.arguments[0].number for s in base.by_signature("q", 1)]
    assert got == [3, 1, 2]
    assert list(base.by_signature("missing", 1)) == []
