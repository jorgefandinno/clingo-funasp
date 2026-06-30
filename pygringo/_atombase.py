"""The atom base: derived ground atoms with their state, indexed by signature.

A trimmed Python analogue of ``base.hh``'s ``AtomBase``.  Each ground atom is
either *possible* (in the domain) or, more strongly, a *fact* (definitely true);
this mirrors the C++ ``StateAtom { fact, derived, unknown }`` distinction that
drives negation handling and output simplification.  Facts form a subset of the
possible atoms.

Each relation tracks **generations** for semi-naive evaluation (the C++
``GenerationCounts``): atoms are kept in insertion order, and two offsets split
them into *old* / *new* / *all* windows so a recursive join can range a literal
over just the freshly-derived atoms.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Iterator

from clingo.symbol import Symbol, SymbolType

#: ``(name, arity, is_positive)`` -- the key under which an atom is indexed.
Signature = tuple[str, int, bool]


def signature_of(sym: Symbol) -> Signature:
    """Return the predicate signature of a function symbol."""
    assert sym.type == SymbolType.Function
    return sym.name, len(sym.arguments), sym.is_positive


class Window(enum.Enum):
    """A generation window over a relation, for semi-naive evaluation."""

    #: Atoms derived before the previous generation.
    OLD = "old"
    #: Atoms derived in the previous generation (the delta).
    NEW = "new"
    #: All atoms derived up to the start of the current generation.
    ALL = "all"


class _GenRelation:
    """Atoms of one signature in insertion order, with generation offsets.

    ``[0, old_offset)`` is *old*, ``[old_offset, all_offset)`` is *new* (the
    delta from the previous generation), and ``[0, all_offset)`` is *all*.  Atoms
    appended during the current generation lie beyond ``all_offset`` and are only
    visited once :meth:`enter_generation` promotes them.
    """

    __slots__ = ("atoms", "members", "old_offset", "all_offset")

    def __init__(self) -> None:
        self.atoms: list[Symbol] = []
        self.members: set[Symbol] = set()
        self.old_offset = 0
        self.all_offset = 0

    def add(self, sym: Symbol) -> bool:
        if sym in self.members:
            return False
        self.members.add(sym)
        self.atoms.append(sym)
        return True

    def enter_generation(self) -> None:
        self.old_offset = self.all_offset
        self.all_offset = len(self.atoms)

    def window(self, kind: Window) -> list[Symbol]:
        if kind is Window.OLD:
            return self.atoms[: self.old_offset]
        if kind is Window.NEW:
            return self.atoms[self.old_offset : self.all_offset]
        return self.atoms[: self.all_offset]


class AtomBase:
    """Derived ground atoms and their state, with semi-naive generations.

    Atoms are kept in insertion order so that grounding is deterministic for a
    given input order.  The *facts* are a generation-tracked subset of the
    *possible* atoms (the domain).
    """

    _possible: dict[Signature, _GenRelation]
    _facts: dict[Signature, _GenRelation]

    def __init__(self) -> None:
        self._possible = {}
        self._facts = {}

    def _store(self, facts: bool) -> dict[Signature, _GenRelation]:
        return self._facts if facts else self._possible

    def add(self, sym: Symbol) -> bool:
        """Add ``sym`` to the domain; return ``True`` iff it was newly added."""
        return self._possible.setdefault(signature_of(sym), _GenRelation()).add(sym)

    def add_fact(self, sym: Symbol) -> bool:
        """Mark ``sym`` a fact (and add it to the domain); return ``True`` iff new."""
        self.add(sym)
        return self._facts.setdefault(signature_of(sym), _GenRelation()).add(sym)

    def is_possible(self, sym: Symbol) -> bool:
        """True iff ``sym`` is in the domain (derivable)."""
        rel = self._possible.get(signature_of(sym))
        return rel is not None and sym in rel.members

    def is_fact(self, sym: Symbol) -> bool:
        """True iff ``sym`` is known to be a fact (definitely true)."""
        rel = self._facts.get(signature_of(sym))
        return rel is not None and sym in rel.members

    def enter_generation(
        self, signatures: Iterable[Signature], facts: bool = False
    ) -> None:
        """Advance the generation offsets of the given signatures' relations."""
        store = self._store(facts)
        for sig in signatures:
            store.setdefault(sig, _GenRelation()).enter_generation()

    def window(
        self, name: str, arity: int, positive: bool, kind: Window, facts: bool = False
    ) -> Iterable[Symbol]:
        """Return one generation window of a signature (empty if unknown)."""
        rel = self._store(facts).get((name, arity, positive))
        return rel.window(kind) if rel is not None else ()

    def relation(
        self, name: str, arity: int, positive: bool, facts: bool = False
    ) -> Iterable[Symbol]:
        """Return all atoms of a signature (empty if unknown)."""
        rel = self._store(facts).get((name, arity, positive))
        return rel.atoms if rel is not None else ()

    def size(
        self, name: str, arity: int, positive: bool = True, facts: bool = False
    ) -> int:
        """Return the number of atoms of a signature (0 if unknown).

        Used by the matcher cost model to estimate a relation's size.
        """
        rel = self._store(facts).get((name, arity, positive))
        return len(rel.atoms) if rel is not None else 0

    def by_signature(
        self, name: str, arity: int, positive: bool = True
    ) -> Iterable[Symbol]:
        """Return all domain atoms with the given signature."""
        return self.relation(name, arity, positive, facts=False)

    def __iter__(self) -> Iterator[Symbol]:
        for rel in self._possible.values():
            yield from rel.atoms
