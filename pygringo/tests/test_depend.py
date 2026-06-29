"""Unit tests for :mod:`pygringo._depend`."""

from __future__ import annotations

import pytest

from pygringo._depend import order_components
from pygringo._error import GroundError


def _flatten(components: list[list[str]]) -> list[set[str]]:
    return [set(comp) for comp in components]


def test_chain_orders_dependencies_first() -> None:
    comps = order_components(["a", "b", "c"], [("a", "b", False), ("b", "c", False)])
    assert _flatten(comps) == [{"a"}, {"b"}, {"c"}]


def test_cycle_grouped_into_one_component() -> None:
    comps = order_components(
        ["a", "b", "c"],
        [("a", "b", False), ("b", "a", False), ("b", "c", False)],
    )
    assert _flatten(comps) == [{"a", "b"}, {"c"}]


def test_isolated_nodes() -> None:
    comps = order_components(["x", "y"], [])
    assert _flatten(comps) in ([{"x"}, {"y"}], [{"y"}, {"x"}])


def test_negative_recursion_rejected() -> None:
    with pytest.raises(GroundError):
        order_components(["a", "b"], [("a", "b", False), ("b", "a", True)])


def test_negative_edge_across_components_allowed() -> None:
    comps = order_components(["a", "b"], [("a", "b", True)])
    assert _flatten(comps) == [{"a"}, {"b"}]


def test_self_loop() -> None:
    comps = order_components(["a"], [("a", "a", False)])
    assert _flatten(comps) == [{"a"}]
    with pytest.raises(GroundError):
        order_components(["a"], [("a", "a", True)])


def test_diamond_topological_order() -> None:
    # a -> b, a -> c, b -> d, c -> d : a first, d last
    comps = order_components(
        ["a", "b", "c", "d"],
        [("a", "b", False), ("a", "c", False), ("b", "d", False), ("c", "d", False)],
    )
    flat = _flatten(comps)
    assert flat[0] == {"a"}
    assert flat[-1] == {"d"}
    assert flat[1] | flat[2] == {"b", "c"}
