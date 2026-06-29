"""Test helpers: a differential harness comparing pygringo against real clingo."""

from __future__ import annotations

from clingo import ast
from clingo.control import Control
from clingo.core import Library
from clingo.solve import Model

from pygringo import ground


def all_models(program: str) -> list[list[str]]:
    """Ground and solve ``program`` with clingo, returning every answer set.

    Each answer set is the sorted list of its true atoms; the list of answer sets
    is itself sorted so results are order-independent.
    """
    ctl = Control(Library(), ["0"])  # "0" => enumerate all models
    ctl.parse_string(program)
    ctl.ground()
    models: list[list[str]] = []

    def collect(model: Model) -> None:
        models.append(sorted(str(sym) for sym in model.symbols(atoms=True)))

    ctl.solve(on_model=collect)
    return sorted(models)


def ground_program(program: str) -> str:
    """Return the pygringo grounding of ``program`` rendered as text."""
    lib = Library()
    statements: list[ast.Statement] = []
    ast.parse_string(lib, program, statements.append)
    return "\n".join(str(stm) for stm in ground(lib, statements))


def assert_equivalent(program: str) -> None:
    """Assert pygringo's grounding has the same answer sets as clingo's."""
    expected = all_models(program)
    grounded = ground_program(program)
    actual = all_models(grounded)
    assert actual == expected, (
        f"answer sets differ for:\n{program}\n"
        f"--- pygringo grounding ---\n{grounded}\n"
        f"expected={expected}\nactual={actual}"
    )
