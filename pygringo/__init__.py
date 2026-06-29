"""Standalone Python re-implementation of clingo's grounder (``lib/ground``).

This package ports the core of clingo's grounder to the clingo Python AST API,
representing logic-program objects with :mod:`clingo.ast` (e.g. ``StmRule`` maps
to :class:`clingo.ast.StatementRule`).  The entry point is :func:`ground`, which
turns a non-ground program into a list of variable-free ``clingo.ast``
statements.  It reuses the :mod:`safety` pilot for safety checking and for
ordering body literals into a groundable order.

Example::

    from clingo import ast
    from clingo.core import Library
    from pygringo import ground

    lib = Library()
    stms = []
    ast.parse_string(lib, "q(1). q(2). p(X) :- q(X).", stms.append)
    for stm in ground(lib, stms):
        print(stm)
    # q(1).
    # q(2).
    # p(1) :- q(1).
    # p(2) :- q(2).

Scope: normal rules, integrity constraints and plain choice rules.  Aggregates
with bounds/conditions, disjunctions, conditional literals, theory atoms,
optimize/weak constraints, externals and other statement kinds raise
:class:`GroundError` -- they are the subject of later phases.
"""

from __future__ import annotations

from ._error import GroundError
from ._ground import ground

__all__ = ["ground", "GroundError"]
