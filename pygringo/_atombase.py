"""The atom base: derived ground atoms with their state, indexed by signature.

A trimmed Python analogue of ``base.hh``'s ``AtomBase``.  Each ground atom is
either *possible* (in the domain) or, more strongly, a *fact* (definitely true);
this mirrors the C++ ``StateAtom { fact, derived, unknown }`` distinction that
drives negation handling and output simplification.  Facts form a subset of the
possible atoms.  The core milestone uses a naive bottom-up fixpoint, so this only
needs to store atoms, answer ``is_possible`` / ``is_fact`` queries, and index the
possible atoms by signature for the join.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from clingo.symbol import Symbol, SymbolType

#: ``(name, arity, is_positive)`` -- the key under which an atom is indexed.
Signature = tuple[str, int, bool]


def signature_of(sym: Symbol) -> Signature:
    """Return the predicate signature of a function symbol."""
    assert sym.type == SymbolType.Function
    return sym.name, len(sym.arguments), sym.is_positive


class AtomBase:
    """Derived ground atoms and their state.

    The *possible* atoms (the domain) are kept in insertion order (a ``dict`` used
    as an ordered set) so that grounding is deterministic for a given input order.
    The *facts* are a subset, tracked separately.
    """

    _possible: dict[Signature, dict[Symbol, None]]
    _facts: set[Symbol]

    def __init__(self) -> None:
        self._possible = {}
        self._facts = set()

    def add(self, sym: Symbol) -> bool:
        """Add ``sym`` to the domain; return ``True`` iff it was newly added."""
        bucket = self._possible.setdefault(signature_of(sym), {})
        if sym in bucket:
            return False
        bucket[sym] = None
        return True

    def add_fact(self, sym: Symbol) -> bool:
        """Mark ``sym`` a fact (and add it to the domain); return ``True`` iff new."""
        self.add(sym)
        if sym in self._facts:
            return False
        self._facts.add(sym)
        return True

    def is_possible(self, sym: Symbol) -> bool:
        """True iff ``sym`` is in the domain (derivable)."""
        return sym in self._possible.get(signature_of(sym), {})

    def is_fact(self, sym: Symbol) -> bool:
        """True iff ``sym`` is known to be a fact (definitely true)."""
        return sym in self._facts

    def by_signature(
        self, name: str, arity: int, positive: bool = True
    ) -> Iterable[Symbol]:
        """Return all domain atoms with the given signature."""
        return self._possible.get((name, arity, positive), ())

    def __iter__(self) -> Iterator[Symbol]:
        for bucket in self._possible.values():
            yield from bucket
