"""Exceptions used across :mod:`pygringo`."""

from __future__ import annotations


class GroundError(Exception):
    """Raised for inputs the grounder cannot handle.

    This covers constructs that are out of scope for the current milestone
    (aggregates other than plain choice, disjunction, theory atoms, optimize,
    externals, scripts), non-normalised input (pooled terms), unsafe rules, and
    recursion through negation.
    """


class _Undefined(Exception):
    """Internal signal that an arithmetic operation is undefined.

    Mirrors clingo's *operation undefined* behaviour (e.g. division by zero or
    arithmetic on non-numbers): the offending rule instance derives nothing and
    is silently dropped during instantiation.
    """
