"""Predicate dependency analysis: strongly-connected components in evaluation order.

A small, self-contained analogue of the component computation the C++ grounder
performs before instantiation (``program.hh``'s ``Component``).  Predicates that
depend on one another cyclically form a component that must be grounded together
by a fixpoint; components are returned in an order where every dependency is
grounded before the predicates that use it.  Recursion through negation is
rejected (the program is not stratified), which is out of scope for the core
milestone.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from typing import TypeVar

from ._error import GroundError

T = TypeVar("T", bound=Hashable)


def order_components(
    nodes: Iterable[T],
    edges: Iterable[tuple[T, T, bool]],
) -> list[list[T]]:
    """Group ``nodes`` into strongly-connected components in evaluation order.

    Each edge ``(src, dst, negative)`` means *dst depends on src*, so ``src``
    must be grounded before ``dst``; ``negative`` marks dependency through
    negation.  Returns the components as lists, ordered so that dependencies come
    first.  Raises :class:`GroundError` if any component contains a negative edge
    (recursion through negation).
    """
    adj: dict[T, list[T]] = {n: [] for n in nodes}
    edge_list = list(edges)
    for src, dst, _ in edge_list:
        adj.setdefault(src, [])
        adj.setdefault(dst, [])
    for src, dst, _ in edge_list:
        adj[src].append(dst)

    index: dict[T, int] = {}
    low: dict[T, int] = {}
    comp_of: dict[T, int] = {}
    on_stack: set[T] = set()
    stack: list[T] = []
    comps: list[list[T]] = []
    counter = 0

    # Iterative Tarjan to avoid recursion limits on large dependency graphs.
    for root in adj:
        if root in index:
            continue
        work: list[tuple[T, int]] = [(root, 0)]
        while work:
            node, child = work[-1]
            if child == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            if child < len(adj[node]):
                work[-1] = (node, child + 1)
                succ = adj[node][child]
                if succ not in index:
                    work.append((succ, 0))
                elif succ in on_stack:
                    low[node] = min(low[node], index[succ])
            else:
                if low[node] == index[node]:
                    comp: list[T] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp_of[w] = len(comps)
                        comp.append(w)
                        if w == node:
                            break
                    comps.append(comp)
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])

    for src, dst, negative in edge_list:
        if negative and comp_of[src] == comp_of[dst]:
            raise GroundError("recursion through negation is not supported")

    # Tarjan closes components in reverse topological order (sinks first); we
    # want dependencies (sources) first.
    return list(reversed(comps))
