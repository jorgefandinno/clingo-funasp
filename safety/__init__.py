"""Standalone Python re-implementation of clingo's rule-safety check.

This package ports ``lib/input/src/rewrite/safety.cc`` to the clingo Python AST
API. The entry point is :func:`check_safety`, which decides whether a statement
is safe and returns it with body/condition literals reordered into a groundable
order (equalities flipped so the binding side is on the left).

The input statement is assumed to be normalised (unpooled), as produced by
``clingo.ast.rewrite_statement``. Non-normalised constructs raise
:class:`SafetyError`.

Example::

    from clingo import ast
    from clingo.core import Library
    from safety import check_safety

    lib = Library()
    ctx = ast.RewriteContext(lib)
    (stm,) = ast.rewrite_statement(ctx, ast.parse_statement(lib, "p(X) :- q(Y)."))
    result = check_safety(lib, stm)
    assert not result.safe
    assert result.unsafe_variables == ["X"]
"""

from ._analyze import VariableContext, check_linear, is_provided, select_variables
from ._safety import (
    SafetyError,
    SafetyResult,
    check_safety,
    literal_dependencies,
)

__all__ = [
    "check_safety",
    "SafetyResult",
    "SafetyError",
    "literal_dependencies",
    "select_variables",
    "check_linear",
    "is_provided",
    "VariableContext",
]
