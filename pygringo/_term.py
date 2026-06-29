"""Term evaluation and matching.

Python port of the term layer of ``lib/ground`` (``term.hh`` / ``term.cc``)
restricted to the core milestone.  Two operations are provided over
:class:`clingo.ast` terms and a variable *assignment* (a mapping from variable
name to :class:`clingo.symbol.Symbol`):

* :func:`eval_term` -- evaluate a term to a ground :class:`Symbol` (the C++
  ``Term::eval``).  Returns ``None`` if the term contains an unbound variable
  and raises :class:`_Undefined` if an arithmetic operation is undefined.
* :func:`match_term` -- unify a (possibly non-ground) term against a ground
  symbol, extending the assignment in place (the C++ ``Term::match``).

The input is assumed normalised (unpooled), matching the precondition of the
``safety`` pilot: every function/tuple carries exactly one argument tuple.
"""

from __future__ import annotations

from functools import singledispatch
from typing import Any

from clingo import ast
from clingo.core import Library
from clingo.symbol import Function, Number, Symbol, SymbolType, Tuple_

from ._error import GroundError, _Undefined

#: A partial binding of variable names to ground symbols.
Assignment = dict[str, Symbol]


# --- helpers ---------------------------------------------------------------


def _arguments(node: ast.TermFunction | ast.TermTuple) -> list[Any]:
    """Return the single argument tuple's terms, asserting the input is unpooled."""
    pool = node.pool
    if len(pool) != 1:
        raise GroundError(f"non-normalised pooled term: {node}")
    elem = pool[0]
    if not isinstance(elem, ast.ArgumentTuple):
        raise GroundError(f"non-normalised pooled term: {node}")
    return list(elem.arguments)


def atom_signature(atom: ast.Term) -> tuple[str, int, bool]:
    """Return the ``(name, arity, is_positive)`` signature of a predicate atom.

    Handles both a non-ground ``TermFunction`` (``p(X)``) and a ground
    ``TermSymbolic`` whose symbol is a function (``q(1)``).
    """
    if isinstance(atom, ast.TermFunction):
        if atom.external:
            raise GroundError(f"external functions are not supported: {atom}")
        return atom.name, len(_arguments(atom)), True
    if isinstance(atom, ast.TermSymbolic) and atom.symbol.type == SymbolType.Function:
        sym = atom.symbol
        return sym.name, len(sym.arguments), sym.is_positive
    raise GroundError(f"unsupported atom (classical negation?): {atom}")


def _is_interval(node: ast.TermBinaryOperation) -> bool:
    """True if ``node`` is an interval ``a..b``.

    The interval operator is not part of the public ``BinaryOperator`` enum, so
    reading ``operator_type`` raises ``ValueError`` -- we use that as the test.
    """
    try:
        node.operator_type
    except ValueError:
        return True
    return False


def interval_bounds(
    node: ast.Term, asgn: Assignment, lib: Library
) -> tuple[int, int] | None:
    """Return ``(lo, hi)`` if ``node`` is an interval with evaluable integer bounds.

    Returns ``None`` if ``node`` is not an interval.  Raises :class:`_Undefined`
    if the bounds do not evaluate to numbers.
    """
    if not isinstance(node, ast.TermBinaryOperation) or not _is_interval(node):
        return None
    lo = eval_term(node.left, asgn, lib)
    hi = eval_term(node.right, asgn, lib)
    if lo is None or hi is None:
        raise _Undefined("interval bound is unbound")
    if lo.type != SymbolType.Number or hi.type != SymbolType.Number:
        raise _Undefined("interval bound is not a number")
    return lo.number, hi.number


# --- arithmetic ------------------------------------------------------------


def _trunc_div(a: int, b: int) -> int:
    if b == 0:
        raise _Undefined("division by zero")
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _binary(op: ast.BinaryOperator, a: int, b: int) -> int:
    if op == ast.BinaryOperator.Plus:
        return a + b
    if op == ast.BinaryOperator.Minus:
        return a - b
    if op == ast.BinaryOperator.Multiplication:
        return a * b
    if op == ast.BinaryOperator.Division:
        return _trunc_div(a, b)
    if op == ast.BinaryOperator.Modulo:
        return a - _trunc_div(a, b) * b
    if op == ast.BinaryOperator.Power:
        if b < 0:
            raise _Undefined("negative exponent")
        return int(a**b)
    if op == ast.BinaryOperator.And:
        return a & b
    if op == ast.BinaryOperator.Or:
        return a | b
    if op == ast.BinaryOperator.Xor:
        return a ^ b
    raise GroundError(f"unsupported binary operator: {op}")  # pragma: no cover


# --- evaluation ------------------------------------------------------------


@singledispatch
def eval_term(term: Any, asgn: Assignment, lib: Library) -> Symbol | None:
    raise GroundError(f"cannot evaluate term: {type(term).__name__} ({term})")


@eval_term.register
def _(term: ast.TermSymbolic, asgn: Assignment, lib: Library) -> Symbol | None:
    return term.symbol


@eval_term.register
def _(term: ast.TermVariable, asgn: Assignment, lib: Library) -> Symbol | None:
    return asgn.get(term.name)


@eval_term.register
def _(term: ast.TermFunction, asgn: Assignment, lib: Library) -> Symbol | None:
    if term.external:
        raise GroundError(f"external functions are not supported: {term}")
    args: list[Symbol] = []
    for arg in _arguments(term):
        value = eval_term(arg, asgn, lib)
        if value is None:
            return None
        args.append(value)
    return Function(lib, term.name, args)


@eval_term.register
def _(term: ast.TermTuple, asgn: Assignment, lib: Library) -> Symbol | None:
    args: list[Symbol] = []
    for arg in _arguments(term):
        value = eval_term(arg, asgn, lib)
        if value is None:
            return None
        args.append(value)
    return Tuple_(lib, args)


@eval_term.register
def _(term: ast.TermBinaryOperation, asgn: Assignment, lib: Library) -> Symbol | None:
    if _is_interval(term):
        raise _Undefined("an interval has no single value")
    left = eval_term(term.left, asgn, lib)
    right = eval_term(term.right, asgn, lib)
    if left is None or right is None:
        return None
    if left.type != SymbolType.Number or right.type != SymbolType.Number:
        raise _Undefined("arithmetic on non-numbers")
    return Number(lib, _binary(term.operator_type, left.number, right.number))


@eval_term.register
def _(term: ast.TermUnaryOperation, asgn: Assignment, lib: Library) -> Symbol | None:
    value = eval_term(term.right, asgn, lib)
    if value is None:
        return None
    if term.operator_type == ast.UnaryOperator.Minus:
        if value.type == SymbolType.Number:
            return Number(lib, -value.number)
        if value.type == SymbolType.Function:
            # Classical negation flips the sign of a function symbol.
            return Function(
                lib, value.name, list(value.arguments), not value.is_positive
            )
        raise _Undefined("unary minus on non-number/function")
    # Bitwise negation.
    if value.type != SymbolType.Number:
        raise _Undefined("bitwise negation on non-number")
    return Number(lib, ~value.number)


@eval_term.register
def _(term: ast.TermAbsolute, asgn: Assignment, lib: Library) -> Symbol | None:
    pool = term.pool
    if len(pool) != 1:
        raise GroundError(f"non-normalised absolute term: {term}")
    value = eval_term(pool[0], asgn, lib)
    if value is None:
        return None
    if value.type != SymbolType.Number:
        raise _Undefined("absolute value of non-number")
    return Number(lib, abs(value.number))


# --- matching --------------------------------------------------------------


@singledispatch
def match_term(term: Any, sym: Symbol, asgn: Assignment, lib: Library) -> bool:
    # Value terms (arithmetic, absolute, ...): match by evaluation, with a
    # linear-inversion fallback when a single variable is still unbound.
    return _match_value(term, sym, asgn, lib)


@match_term.register
def _(term: ast.TermVariable, sym: Symbol, asgn: Assignment, lib: Library) -> bool:
    if term.anonymous:
        return True
    bound = asgn.get(term.name)
    if bound is None:
        asgn[term.name] = sym
        return True
    return bool(bound == sym)


@match_term.register
def _(term: ast.TermSymbolic, sym: Symbol, asgn: Assignment, lib: Library) -> bool:
    return bool(term.symbol == sym)


@match_term.register
def _(term: ast.TermFunction, sym: Symbol, asgn: Assignment, lib: Library) -> bool:
    if term.external:
        raise GroundError(f"external functions are not supported: {term}")
    args = _arguments(term)
    if (
        sym.type != SymbolType.Function
        or sym.name != term.name
        or not sym.is_positive
        or len(sym.arguments) != len(args)
    ):
        return False
    return all(match_term(a, s, asgn, lib) for a, s in zip(args, sym.arguments))


@match_term.register
def _(term: ast.TermTuple, sym: Symbol, asgn: Assignment, lib: Library) -> bool:
    args = _arguments(term)
    if sym.type != SymbolType.Tuple or len(sym.arguments) != len(args):
        return False
    return all(match_term(a, s, asgn, lib) for a, s in zip(args, sym.arguments))


def _match_value(term: ast.Term, sym: Symbol, asgn: Assignment, lib: Library) -> bool:
    """Match an arithmetic/value term against a ground symbol.

    If the term is fully bound it is evaluated and compared.  Otherwise we try
    the canonical linear form ``m*X+n`` (``safety.check_linear``) and invert it
    to bind ``X`` -- this is how the grounder matches e.g. ``q(X+1)``.
    """
    value = eval_term(term, asgn, lib)
    if value is not None:
        return bool(value == sym)

    from safety import (
        check_linear,
    )  # noqa: PLC0415  (avoid import cycle at module load)

    name = check_linear(term)
    if name is None or name in asgn:
        raise GroundError(f"cannot match non-linear term with unbound variable: {term}")
    if sym.type != SymbolType.Number:
        return False
    coeff, const = _linear_coeffs(term, asgn, lib)
    numerator = sym.number - const
    if coeff == 0 or numerator % coeff != 0:
        return False
    asgn[name] = Number(lib, numerator // coeff)
    return True


def _linear_coeffs(term: ast.Term, asgn: Assignment, lib: Library) -> tuple[int, int]:
    """Return ``(m, n)`` for a canonical linear term ``m*X+n``."""
    assert isinstance(term, ast.TermBinaryOperation)
    mul = term.left
    assert isinstance(mul, ast.TermBinaryOperation)
    coeff = eval_term(mul.left, asgn, lib)
    const = eval_term(term.right, asgn, lib)
    assert coeff is not None and const is not None
    return coeff.number, const.number
