"""The atom base: derived ground atoms, indexed by predicate signature.

A trimmed Python analogue of ``base.hh``'s ``AtomBase`` / ``Bases``.  The core
milestone uses a naive bottom-up fixpoint (rather than the C++ generation-based
semi-naive evaluation), so this only needs to store the derived atoms, answer
membership queries, and index atoms by signature for the join.
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
    """A set of derived ground atoms indexed by signature.

    Atoms are kept in insertion order (a ``dict`` used as an ordered set) so that
    grounding is deterministic for a given input order.
    """

    _atoms: dict[Signature, dict[Symbol, None]]

    def __init__(self) -> None:
        self._atoms = {}

    def add(self, sym: Symbol) -> bool:
        """Add ``sym``; return ``True`` iff it was not already present."""
        bucket = self._atoms.setdefault(signature_of(sym), {})
        if sym in bucket:
            return False
        bucket[sym] = None
        return True

    def contains(self, sym: Symbol) -> bool:
        """True iff ``sym`` has been derived."""
        return sym in self._atoms.get(signature_of(sym), {})

    def by_signature(
        self, name: str, arity: int, positive: bool = True
    ) -> Iterable[Symbol]:
        """Return all derived atoms with the given signature."""
        return self._atoms.get((name, arity, positive), ())

    def __iter__(self) -> Iterator[Symbol]:
        for bucket in self._atoms.values():
            yield from bucket
