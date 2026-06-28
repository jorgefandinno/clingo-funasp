"""Variable analysis helpers.

Python port of the parts of ``lib/input/src/rewrite/analyze.cc`` and
``lib/input/src/rewrite/visit_variables.cc`` that the safety check relies on:

* :func:`select_variables` -- collect variable names, distinguishing *global*
  occurrences from occurrences that are *local* to an aggregate / theory /
  optimize element body or a conditional literal.
* :func:`check_linear` -- recognise the canonical ``m*X+n`` linear term and
  return the bound variable ``X``.
* :func:`is_provided` -- the "all variables are provided" predicate.
"""

from __future__ import annotations

import enum
from functools import singledispatch

from clingo import ast
from clingo.symbol import SymbolType


class VariableContext(enum.Enum):
    """Scope filter for :func:`select_variables`.

    Mirrors ``CppClingo::Input::VariableContext`` (``visit_variables.hh``).
    """

    #: Visit every variable occurrence, including nested element bodies.
    ALL = "all"
    #: Visit only variables occurring in the global scope of the statement.
    GLOBAL = "global"


# --- variable collection ---------------------------------------------------


def select_variables(node, ctx: VariableContext = VariableContext.ALL) -> set[str]:
    """Return the set of variable names occurring in ``node``.

    With :data:`VariableContext.GLOBAL`, occurrences inside aggregate / theory
    / optimize *element bodies* and inside conditional literals are skipped
    (guards and names still count as global). With :data:`VariableContext.ALL`
    every occurrence is collected.
    """
    out: set[str] = set()
    _collect(node, ctx, out)
    return out


@singledispatch
def _collect(node, ctx: VariableContext, out: set[str]) -> None:
    # Generic case: descend into all direct AST children. ``visit`` forwards the
    # extra ``ctx``/``out`` arguments to the callback (see clingo.ast docs).
    node.visit(_collect, ctx, out)


@_collect.register
def _(node: ast.TermVariable, ctx: VariableContext, out: set[str]) -> None:
    out.add(node.name)


@_collect.register
def _(node: ast.TheoryTermVariable, ctx: VariableContext, out: set[str]) -> None:
    out.add(node.name)


# Scope-introducing nodes: their guards/names are global, their element bodies
# (and conditional-literal contents) are local.


def _collect_guarded(node, ctx: VariableContext, out: set[str]) -> None:
    left = getattr(node, "left", None)
    if left is not None:
        _collect(left, ctx, out)
    right = getattr(node, "right", None)
    if right is not None:
        _collect(right, ctx, out)
    if ctx is VariableContext.ALL:
        for elem in node.elements:
            _collect(elem, ctx, out)


@_collect.register
def _(node: ast.BodyAggregate, ctx: VariableContext, out: set[str]) -> None:
    _collect_guarded(node, ctx, out)


@_collect.register
def _(node: ast.HeadAggregate, ctx: VariableContext, out: set[str]) -> None:
    _collect_guarded(node, ctx, out)


@_collect.register
def _(node: ast.BodySetAggregate, ctx: VariableContext, out: set[str]) -> None:
    _collect_guarded(node, ctx, out)


@_collect.register
def _(node: ast.HeadSetAggregate, ctx: VariableContext, out: set[str]) -> None:
    _collect_guarded(node, ctx, out)


def _collect_theory(node, ctx: VariableContext, out: set[str]) -> None:
    _collect(node.name, ctx, out)
    right = getattr(node, "right", None)
    if right is not None:
        _collect(right, ctx, out)
    if ctx is VariableContext.ALL:
        for elem in node.elements:
            _collect(elem, ctx, out)


@_collect.register
def _(node: ast.BodyTheoryAtom, ctx: VariableContext, out: set[str]) -> None:
    _collect_theory(node, ctx, out)


@_collect.register
def _(node: ast.HeadTheoryAtom, ctx: VariableContext, out: set[str]) -> None:
    _collect_theory(node, ctx, out)


@_collect.register
def _(node: ast.BodyConditionalLiteral, ctx: VariableContext, out: set[str]) -> None:
    if ctx is VariableContext.ALL:
        node.visit(_collect, ctx, out)


@_collect.register
def _(node: ast.HeadConditionalLiteral, ctx: VariableContext, out: set[str]) -> None:
    if ctx is VariableContext.ALL:
        node.visit(_collect, ctx, out)


@_collect.register
def _(node: ast.StatementOptimize, ctx: VariableContext, out: set[str]) -> None:
    if ctx is VariableContext.ALL:
        node.visit(_collect, ctx, out)


@_collect.register
def _(node: ast.StatementConst, ctx: VariableContext, out: set[str]) -> None:
    # Constant definitions contribute no variables.
    return None


# --- linear terms ----------------------------------------------------------


def _is_number(term) -> bool:
    return isinstance(term, ast.TermSymbolic) and term.symbol.type == SymbolType.Number


def check_linear(term) -> str | None:
    """Return the variable ``X`` if ``term`` is the canonical linear ``m*X+n``.

    Mirrors ``is_linear`` / ``check_linear`` in ``analyze.cc``: the term must be
    ``(m * X) + n`` with ``m`` and ``n`` numbers, ``m != 0`` and ``X`` a
    variable. After ``rewrite_statement`` arithmetic is normalised into this
    shape (e.g. ``X+1`` becomes ``1*X+1``). Returns ``None`` otherwise.
    """
    if not isinstance(term, ast.TermBinaryOperation):
        return None
    if term.operator_type != ast.BinaryOperator.Plus:
        return None
    mul = term.left
    if (
        not isinstance(mul, ast.TermBinaryOperation)
        or mul.operator_type != ast.BinaryOperator.Multiplication
    ):
        return None
    if not _is_number(term.right):
        return None
    if not _is_number(mul.left) or mul.left.symbol.number == 0:
        return None
    if not isinstance(mul.right, ast.TermVariable):
        return None
    return mul.right.name


# --- safety predicate ------------------------------------------------------


def is_provided(provided, names) -> bool:
    """True iff every name in ``names`` is provided.

    A name counts as provided if it is in ``provided`` or starts with ``$``
    (auxiliary variables introduced by rewriting, treated as always safe).
    """
    return all(name.startswith("$") or name in provided for name in names)
