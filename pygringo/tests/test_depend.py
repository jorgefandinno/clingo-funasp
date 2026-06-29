"""Unit tests for :mod:`pygringo._depend`."""

from __future__ import annotations

from pygringo._depend import order_components


def _flatten(components: list[list[str]]) -> list[set[str]]:
    return [set(comp) for comp in components]


def test_chain_orders_dependencies_first() -> None:
    comps = order_components(["a", "b", "c"], [("a", "b"), ("b", "c")])
    assert _flatten(comps) == [{"a"}, {"b"}, {"c"}]


def test_cycle_grouped_into_one_component() -> None:
    comps = order_components(
        ["a", "b", "c"],
        [("a", "b"), ("b", "a"), ("b", "c")],
    )
    assert _flatten(comps) == [{"a", "b"}, {"c"}]


def test_isolated_nodes() -> None:
    comps = order_components(["x", "y"], [])
    assert _flatten(comps) in ([{"x"}, {"y"}], [{"y"}, {"x"}])


def test_negative_cycle_forms_one_component() -> None:
    # A negative cycle (recursion through negation) is not special-cased: the two
    # predicates simply form one component, grounded together by a fixpoint.
    comps = order_components(["a", "b"], [("a", "b"), ("b", "a")])
    assert _flatten(comps) == [{"a", "b"}]


def test_edge_across_components() -> None:
    comps = order_components(["a", "b"], [("a", "b")])
    assert _flatten(comps) == [{"a"}, {"b"}]


def test_self_loop() -> None:
    comps = order_components(["a"], [("a", "a")])
    assert _flatten(comps) == [{"a"}]


def test_diamond_topological_order() -> None:
    # a -> b, a -> c, b -> d, c -> d : a first, d last
    comps = order_components(
        ["a", "b", "c", "d"],
        [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
    )
    flat = _flatten(comps)
    assert flat[0] == {"a"}
    assert flat[-1] == {"d"}
    assert flat[1] | flat[2] == {"b", "c"}
