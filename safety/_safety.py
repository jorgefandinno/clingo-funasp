"""Safety check for normalised statements.

Python port of ``lib/input/src/rewrite/safety.cc``. The entry point is
:func:`check_safety`. The input statement is assumed to be already normalised
(unpooled): single-guard comparisons, ``m*X+n`` linear terms, no pools or set
aggregates. Non-normalised constructs that the C++ code rejects with "unpool
must be called before safety checking" raise :class:`SafetyError` here.

Note that ``clingo.ast.rewrite_statement`` does normalise statements but also
performs the safety check itself (rejecting unsafe input and eliminating
equalities), so it cannot be used to feed inputs to this checker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import singledispatch

from clingo import ast

from ._analyze import VariableContext, check_linear, is_provided, select_variables


class SafetyError(Exception):
    """Raised when the input is not normalised (pools/set aggregates/optimize)."""


@dataclass
class SafetyResult:
    """Outcome of :func:`check_safety`.

    Attributes:
        safe: Whether the statement is safe.
        statement: The statement with body/condition literals reordered into a
            groundable order (equalities flipped so the binding side is on the
            left) when ``safe``; the original statement otherwise.
        unsafe_variables: Sorted names of the unsafe variables (empty iff safe).
    """

    safe: bool
    statement: object
    unsafe_variables: list[str] = field(default_factory=list)


# --- provide / depend analysis of terms (GetDep) ---------------------------


@singledispatch
def _get_dep(term, can_provide: bool, ignore, provide, depend) -> None:
    # Conservative fallback for any term kind not special-cased: it can only
    # depend on its variables, never provide them.
    for name in select_variables(term, VariableContext.ALL):
        if name not in ignore:
            depend.append(name)


@_get_dep.register
def _(term: ast.TermVariable, can_provide, ignore, provide, depend) -> None:
    if term.name not in ignore:
        (provide if can_provide else depend).append(term.name)


@_get_dep.register
def _(term: ast.TermSymbolic, can_provide, ignore, provide, depend) -> None:
    return None


@_get_dep.register
def _(term: ast.TermAbsolute, can_provide, ignore, provide, depend) -> None:
    for arg in term.pool:
        _get_dep(arg, False, ignore, provide, depend)


@_get_dep.register
def _(term: ast.TermUnaryOperation, can_provide, ignore, provide, depend) -> None:
    provides = can_provide and term.operator_type == ast.UnaryOperator.Minus
    _get_dep(term.right, provides, ignore, provide, depend)


@_get_dep.register
def _(term: ast.TermBinaryOperation, can_provide, ignore, provide, depend) -> None:
    var = check_linear(term)
    if can_provide and var is not None and var not in ignore:
        provide.append(var)
    else:
        _get_dep(term.left, False, ignore, provide, depend)
        _get_dep(term.right, False, ignore, provide, depend)


@_get_dep.register
def _(term: ast.TermTuple, can_provide, ignore, provide, depend) -> None:
    for elem in term.pool:
        _get_dep(elem, can_provide, ignore, provide, depend)


@_get_dep.register
def _(term: ast.ArgumentTuple, can_provide, ignore, provide, depend) -> None:
    for arg in term.arguments:
        _get_dep(arg, can_provide, ignore, provide, depend)


@_get_dep.register
def _(term: ast.TermFunction, can_provide, ignore, provide, depend) -> None:
    for argtuple in term.pool:
        _get_dep(argtuple, can_provide, ignore, provide, depend)


@_get_dep.register
def _(term: ast.TermFormatString, can_provide, ignore, provide, depend) -> None:
    for fld in term.elements:
        if isinstance(fld, ast.FormatFieldExpression):
            _get_dep(fld.left, False, ignore, provide, depend)
        # FormatFieldLiteral contributes nothing.


# --- per-literal dependency nodes (MakeNode) -------------------------------


def _globals_in(node, global_set) -> list[str]:
    return [v for v in select_variables(node, VariableContext.ALL) if v in global_set]


@singledispatch
def _make_nodes(lit, can_provide: bool, global_set, bound):
    """Return a list of ``(provide, depend, swap)`` nodes for ``lit``."""
    raise SafetyError(f"unexpected literal: {type(lit).__name__}")


@_make_nodes.register
def _(lit: ast.BodySimpleLiteral, can_provide, global_set, bound):
    return _make_nodes(lit.literal, can_provide, global_set, bound)


@_make_nodes.register
def _(lit: ast.LiteralBoolean, can_provide, global_set, bound):
    return [([], [], False)]


@_make_nodes.register
def _(lit: ast.LiteralSymbolic, can_provide, global_set, bound):
    provide: list[str] = []
    depend: list[str] = []
    _get_dep(
        lit.atom, can_provide and lit.sign == ast.Sign.NoSign, bound, provide, depend
    )
    return [(provide, depend, False)]


@_make_nodes.register
def _(lit: ast.LiteralComparison, can_provide, global_set, bound):
    if len(lit.right) != 1:
        raise SafetyError("comparison must have a single guard (unpool first)")
    relation = lit.right[0].relation
    rhs_term = lit.right[0].term
    nodes = []

    def add(lhs_provides: bool, rhs_provides: bool) -> None:
        provide: list[str] = []
        depend: list[str] = []
        _get_dep(lit.left, lhs_provides, bound, provide, depend)
        _get_dep(rhs_term, rhs_provides, bound, provide, depend)
        # suppress the right-binding candidate when it provides nothing
        if not rhs_provides or provide:
            nodes.append((provide, depend, rhs_provides))

    if relation == ast.Relation.Equal and can_provide:
        add(True, False)
        add(False, True)
    else:
        add(False, False)
    return nodes


@_make_nodes.register
def _(lit: ast.BodyConditionalLiteral, can_provide, global_set, bound):
    return [([], _globals_in(lit, global_set), False)]


@_make_nodes.register
def _(lit: ast.BodyTheoryAtom, can_provide, global_set, bound):
    return [([], _globals_in(lit, global_set), False)]


@_make_nodes.register
def _(lit: ast.BodyAggregate, can_provide, global_set, bound):
    left = lit.left
    right = lit.right
    provides = (
        can_provide
        and lit.sign == ast.Sign.NoSign
        and right is None
        and left is not None
        and left.relation == ast.Relation.Equal
    )
    provide: list[str] = []
    depend: list[str] = []
    if left is not None:
        _get_dep(left.term, provides, bound, provide, depend)
    if right is not None:
        _get_dep(right.term, False, bound, provide, depend)
    for elem in lit.elements:
        depend.extend(_globals_in(elem, global_set))
    return [(provide, depend, False)]


@_make_nodes.register
def _(lit: ast.BodySetAggregate, can_provide, global_set, bound):
    raise SafetyError("set aggregate: unpool must be called before safety checking")


# --- equality flip ---------------------------------------------------------


def _flip_comparison(lib, comp):
    guard = comp.right[0]
    new_right = [ast.RightGuard(lib, guard.relation, comp.left)]
    return ast.LiteralComparison(lib, comp.location, comp.sign, guard.term, new_right)


def _flip(lib, item):
    """Flip an equality literal so the binding side is on the left."""
    if isinstance(item, ast.BodySimpleLiteral):
        return ast.BodySimpleLiteral(lib, _flip_comparison(lib, item.literal))
    return _flip_comparison(lib, item)


# --- groundable ordering (prepare_lits) ------------------------------------


def _prepare_lits(lib, lits, global_set, bound, extra=()):
    """Order ``lits`` into a groundable sequence.

    Returns ``(order, provided, complete)`` where ``order`` is a list of
    ``(index, swap)`` pairs into ``lits`` and ``complete`` is true iff every
    literal could be ordered. Mirrors ``prepare_lits`` in ``safety.cc``.
    """
    lits = list(lits)
    provided: set[str] = set(extra)
    bound = set(bound)

    # build candidate nodes: [src_index, provide, depend, swap]
    nodes = []
    for index, lit in enumerate(lits):
        for provide, depend, swap in _make_nodes(lit, True, global_set, bound):
            nodes.append([index, provide, depend, swap])

    done = [False] * len(lits)
    order: list[tuple[int, bool]] = []

    # fixpoint: repeatedly stable-partition the not-yet-fixed nodes whose whole
    # depend set is provided to the front, emit the new ones, grow ``provided``.
    start = 0
    while start < len(nodes):
        rest = nodes[start:]
        front = [nd for nd in rest if is_provided(provided, nd[2])]
        back = [nd for nd in rest if not is_provided(provided, nd[2])]
        if not front:
            break  # no progress
        nodes[start:] = front + back
        stop = start + len(front)
        for index, provide, depend, swap in nodes[start:stop]:
            if not done[index]:
                done[index] = True
                provided.update(provide)
                order.append((index, swap))
        start = stop

    return order, provided, all(done)


def _reorder(lib, lits, order):
    lits = list(lits)
    return [_flip(lib, lits[index]) if swap else lits[index] for index, swap in order]


# --- nested local checks (CheckLocal) --------------------------------------


def _attr_vars(node, out: set[str]) -> None:
    if hasattr(node, "visit"):  # an AST node
        out |= select_variables(node, VariableContext.ALL)
    else:  # a sequence of AST nodes (e.g. an element tuple)
        for elem in node:
            _attr_vars(elem, out)


def _handle_element(lib, bound, elem, attr_values, unsafe):
    """Check and reorder a single element condition.

    ``attr_values`` are the element's non-condition parts (tuple/literal) which
    must only use provided variables. Returns ``(state, new_element)``.
    """
    order, provided, complete = _prepare_lits(lib, elem.condition, set(), bound)

    depend: set[str] = set()
    for attr in attr_values:
        _attr_vars(attr, depend)
    depend = {v for v in depend if v not in bound}

    if not complete or not is_provided(provided, depend):
        local = select_variables(elem, VariableContext.ALL) - set(bound)
        unsafe.extend(v for v in local if v not in provided)
        return False, None

    new_cond = _reorder(lib, elem.condition, order)
    return True, elem.update(lib, condition=new_cond)


def _handle_agg_elements(lib, bound, lit, with_literal, unsafe):
    new_elems = []
    for elem in lit.elements:
        attrs = [elem.tuple]
        if with_literal:
            attrs.append(elem.literal)
        state, new_elem = _handle_element(lib, bound, elem, attrs, unsafe)
        if not state:
            return False, None
        new_elems.append(new_elem if new_elem is not None else elem)
    return True, lit.update(lib, elements=new_elems)


def _check_local(lib, bound, item, unsafe):
    """Check nested element conditions of a body/head literal.

    ``bound`` is the set of already-provided (global) variables. Returns
    ``(state, new_item)``; ``new_item`` is ``None`` when unchanged or unsafe.
    """
    if isinstance(item, (ast.BodySimpleLiteral, ast.HeadSimpleLiteral)):
        return True, None

    if isinstance(item, ast.BodyConditionalLiteral):
        return _handle_element(lib, bound, item, [item.literal], unsafe)

    if isinstance(item, ast.HeadDisjunction):
        new_elems = []
        for elem in item.elements:
            if isinstance(elem, ast.HeadConditionalLiteral):
                state, new_elem = _handle_element(
                    lib, bound, elem, [elem.literal], unsafe
                )
                if not state:
                    return False, None
                new_elems.append(new_elem if new_elem is not None else elem)
            else:
                new_elems.append(elem)
        return True, item.update(lib, elements=new_elems)

    if isinstance(item, ast.HeadAggregate):
        return _handle_agg_elements(lib, bound, item, with_literal=True, unsafe=unsafe)

    if isinstance(item, ast.BodyAggregate):
        return _handle_agg_elements(lib, bound, item, with_literal=False, unsafe=unsafe)

    if isinstance(item, (ast.BodyTheoryAtom, ast.HeadTheoryAtom)):
        return _handle_agg_elements(lib, bound, item, with_literal=False, unsafe=unsafe)

    if isinstance(item, (ast.BodySetAggregate, ast.HeadSetAggregate)):
        raise SafetyError("set aggregate: unpool must be called before checking safety")

    # any other literal kind is trivially safe and unchanged
    return True, None


# --- top-level statement checks (CheckGlobal) ------------------------------

_TRIVIALLY_SAFE = (
    ast.StatementTheory,
    ast.StatementShowNothing,
    ast.StatementShowSignature,
    ast.StatementProjectSignature,
    ast.StatementDefined,
    ast.StatementScript,
    ast.StatementInclude,
    ast.StatementProgram,
    ast.StatementConst,
    ast.StatementComment,
)


def _handle_body(lib, global_set, stm, unsafe, atom=None):
    """Order/check the body and recurse into nested scopes.

    Returns ``(state, new_body, provided)`` so callers can also check a head.
    """
    extra = select_variables(atom, VariableContext.ALL) if atom is not None else set()
    order, provided, complete = _prepare_lits(lib, stm.body, global_set, set(), extra)

    if not complete or not is_provided(provided, global_set):
        unsafe.extend(v for v in global_set if v not in provided)
        return False, None, provided

    new_body = []
    for item in _reorder(lib, stm.body, order):
        state, new_item = _check_local(lib, provided, item, unsafe)
        if not state:
            return False, None, provided
        new_body.append(new_item if new_item is not None else item)

    return True, new_body, provided


def _check_global(lib, global_set, stm, unsafe):
    if isinstance(stm, ast.StatementRule):
        state, new_body, provided = _handle_body(lib, global_set, stm, unsafe)
        if not state:
            return False, None
        state, new_head = _check_local(lib, provided, stm.head, unsafe)
        if not state:
            return False, None
        head = new_head if new_head is not None else stm.head
        return True, stm.update(lib, head=head, body=new_body)

    if isinstance(stm, ast.StatementOptimize):
        raise SafetyError("optimize: unpool must be called before safety checking")

    if isinstance(
        stm,
        (
            ast.StatementWeakConstraint,
            ast.StatementShow,
            ast.StatementExternal,
            ast.StatementEdge,
        ),
    ):
        state, new_body, _ = _handle_body(lib, global_set, stm, unsafe)
        if not state:
            return False, None
        return True, stm.update(lib, body=new_body)

    if isinstance(stm, (ast.StatementProject, ast.StatementHeuristic)):
        state, new_body, _ = _handle_body(lib, global_set, stm, unsafe, atom=stm.atom)
        if not state:
            return False, None
        return True, stm.update(lib, body=new_body)

    if isinstance(stm, _TRIVIALLY_SAFE):
        return True, None

    raise SafetyError(f"unexpected statement: {type(stm).__name__}")


def check_safety(lib, stm) -> SafetyResult:
    """Check whether ``stm`` is safe, replicating ``safety.cc``.

    Args:
        lib: A ``clingo.core.Library`` (needed to build rewritten literals).
        stm: A normalised ``clingo.ast`` statement (run it through
            ``ast.rewrite_statement`` first).

    Returns:
        A :class:`SafetyResult`. When safe, ``statement`` is the statement with
        body/condition literals reordered into a groundable order.
    """
    global_set = select_variables(stm, VariableContext.GLOBAL)
    unsafe: list[str] = []
    state, new_stm = _check_global(lib, global_set, stm, unsafe)
    if state:
        return SafetyResult(True, new_stm if new_stm is not None else stm, [])
    return SafetyResult(False, stm, sorted(set(unsafe)))
