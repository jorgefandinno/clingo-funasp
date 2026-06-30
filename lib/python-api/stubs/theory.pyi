"""
This module allows for using theories implemented in C from Python.
"""

from __future__ import annotations

import collections.abc
import typing

import clingo_funasp.app
import clingo_funasp.control
import clingo_funasp.core
import clingo_funasp.solve
import clingo_funasp.stats
import clingo_funasp.symbol

__all__: list[str] = ["Theory", "TheoryAssignment"]

class Theory:
    """
    Object to call functions from a C-library implementing a custom theory.
    """

    def __init__(self, library: clingo_funasp.core.Library, create: typing.Any) -> None:
        """
        Construct a theory object.

        Args:
            library: Library object to store symbols in.
            create:
                A capsule object holding a function pointer to initialize the theory.
        """

    def assignment(self, thread_id: int) -> TheoryAssignment:
        """
        Get the symbols and values currently assigned by the theory

        It depends on the theory when this function can be called. Generally, it can be
        called after `on_model` while the solver is still holding its current model.

        Args:
            thread_id: The id of the thread to query.

        Returns:
            An interable over symbol value pairs.
        """

    def on_model(self, model: clingo_funasp.solve.Model) -> None:
        """
        Notify the theory about the given model.

        Some theories extend the model here are set their internal assignments. This
        function should be called in the on_model callback of a control's solve
        function.

        Args:
            model: The current model.
        """

    def on_stats(self, step: clingo_funasp.stats.Stats, accu: clingo_funasp.stats.Stats) -> None:
        """
        Let the theory update statistics.

        Some theories extend the statistics here.

        Args:
            step: The per step statistics.
            accu: The accumulated statistics.
        """

    def prepare(self, control: clingo_funasp.control.Control) -> None:
        """
        Prepare the theory for solving.

        Args:
            control: The control object using for solving.
        """

    def register(self, control: clingo_funasp.control.Control) -> None:
        """
        Register the theory with the given control object.

        This function should be called once on the control object before grounding and
        solving starts.

        Args:
            control: The control object to register the theory with.
        """

    def register_options(self, options: clingo_funasp.app.AppOptions) -> None:
        """
        Register theory related options.

        Args:
            options: The application options.

        See also: `clingo_funasp.app.App.register_options`
        """

    def rewrite(
        self,
        statement: (
            clingo_funasp.ast.StatementRule
            | clingo_funasp.ast.StatementTheory
            | clingo_funasp.ast.StatementOptimize
            | clingo_funasp.ast.StatementWeakConstraint
            | clingo_funasp.ast.StatementShow
            | clingo_funasp.ast.StatementShowNothing
            | clingo_funasp.ast.StatementShowSignature
            | clingo_funasp.ast.StatementProject
            | clingo_funasp.ast.StatementProjectSignature
            | clingo_funasp.ast.StatementDefined
            | clingo_funasp.ast.StatementExternal
            | clingo_funasp.ast.StatementEdge
            | clingo_funasp.ast.StatementHeuristic
            | clingo_funasp.ast.StatementScript
            | clingo_funasp.ast.StatementInclude
            | clingo_funasp.ast.StatementProgram
            | clingo_funasp.ast.StatementConst
            | clingo_funasp.ast.StatementComment
        ),
        callback: collections.abc.Callable[
            [
                clingo_funasp.ast.StatementRule
                | clingo_funasp.ast.StatementTheory
                | clingo_funasp.ast.StatementOptimize
                | clingo_funasp.ast.StatementWeakConstraint
                | clingo_funasp.ast.StatementShow
                | clingo_funasp.ast.StatementShowNothing
                | clingo_funasp.ast.StatementShowSignature
                | clingo_funasp.ast.StatementProject
                | clingo_funasp.ast.StatementProjectSignature
                | clingo_funasp.ast.StatementDefined
                | clingo_funasp.ast.StatementExternal
                | clingo_funasp.ast.StatementEdge
                | clingo_funasp.ast.StatementHeuristic
                | clingo_funasp.ast.StatementScript
                | clingo_funasp.ast.StatementInclude
                | clingo_funasp.ast.StatementProgram
                | clingo_funasp.ast.StatementConst
                | clingo_funasp.ast.StatementComment
            ],
            None,
        ],
    ) -> None:
        """
        Rewrite the given statement and pass the result to the callback.

        Some theories require rewriting prior to adding a non-ground program to a
        control object.

        Args:
            statement: The statement to rewrite.
            callback: The callback receiving rewritten statements.
        """

    def rewrite_files(
        self,
        lib: clingo_funasp.core.Library,
        control: clingo_funasp.control.Control,
        files: typing.Sequence[str],
    ) -> None:
        """
        Rewrite the program in the given files and add it to the control.

        Args:
            lib: The library to store symbols.
            control: The target control..
            files: The files to parse.
        """

    def rewrite_string(
        self, lib: clingo_funasp.core.Library, control: clingo_funasp.control.Control, program: str
    ) -> None:
        """
        Rewrite the given program adding it to the control object.

        Args:
            lib: The library to store symbols.
            control: The target control..
            program: The program to parse.
        """

    def validate_options(self) -> None:
        """
        Check the registered options.

        See also: `clingo_funasp.app.App.validate_options`
        """

    def value(
        self, thread_id: int, symbol: clingo_funasp.symbol.Symbol
    ) -> clingo_funasp.symbol.Symbol | int | float | None:
        """
        Get the value of the symbol in the assignment of the given thread.

        It depends on the theory when this function can be called. Generally, it can be
        called after `on_model` while the solver is still holding its current model.

        Args:
            thread_id: The id of the thread to query.
            symbol: The symbol to lookup.

        Returns:
            The value or None if unnassigned.
        """

    @property
    def has_assignment(self) -> bool:
        """
        Check whether the theory supports symbol value assigments.
        """

    @property
    def name(self) -> str:
        """
        Get the name of the theory.
        """

    @property
    def version(self) -> tuple[int, int, int]:
        """
        Get the version of the theory (major, minor, revision).
        """

class TheoryAssignment:
    """
    Assignment of theory values.
    """

    def __iter__(self) -> TheoryAssignment:
        """
        Return self.
        """

    def __next__(
        self,
    ) -> tuple[clingo_funasp.symbol.Symbol, clingo_funasp.symbol.Symbol | int | float]:
        """
        Get the next symbol value pair.
        """

    def at(
        self, index: int
    ) -> tuple[clingo_funasp.symbol.Symbol, clingo_funasp.symbol.Symbol | int | float]:
        """
        Get the value at the given index in the assignment.

        Args:
            index: The index of the value
        Returns:
            The value.
        """

    def lookup(self, symbol: clingo_funasp.symbol.Symbol) -> int | None:
        """
        Get the value index of the symbol in the assignment.

        Args:
            symbol: The symbol to lookup.
        Returns:
            The value or None if unnassigned.
        """
