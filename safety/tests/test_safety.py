"""Tests for the standalone safety checker.

Inputs are built with ``ast.parse_statement`` (not ``ast.rewrite_statement``):
clingo's rewrite pass performs the safety check itself -- it rejects unsafe
statements and eliminates/pre-orders equalities -- which would make the
reordering, equality-flip and unsafe-detection logic untestable. Hand-written
programs here are already in the normalised form the checker assumes
(single-guard comparisons, ``m*X+n`` linear terms, no pools).
"""

import pytest
from clingo import ast
from clingo.core import Library

from safety import SafetyError, check_safety, select_variables
from safety._analyze import VariableContext, check_linear, is_provided


class TestSafety:
    _lib: Library

    def setup_method(self, method: object) -> None:
        self._lib = Library()

    def check(self, program: str) -> tuple[bool, str, list[str]]:
        """Parse one statement and return ``(safe, rendered, unsafe_variables)``."""
        result = check_safety(self._lib, ast.parse_statement(self._lib, program))
        return result.safe, str(result.statement), result.unsafe_variables

    # --- safe rules, with groundable reordering ---------------------------

    def test_simple_safe(self) -> None:
        safe, rendered, unsafe = self.check("p(X) :- q(X).")
        assert safe
        assert unsafe == []
        assert rendered == "p(X) :- q(X)."

    def test_reorder_binds_before_use(self) -> None:
        # q(X) binds X, X=Y then binds Y, r(Y) uses it; the equality is ordered
        # after its provider and the comparison X<... style tests come last.
        safe, rendered, _ = self.check("p(X) :- r(Y), X = Y, q(X).")
        assert safe
        # providers q(X)/r(Y) precede the equality test
        assert rendered == "p(X) :- r(Y); q(X); X=Y."

    def test_comparison_ordered_last(self) -> None:
        safe, rendered, _ = self.check("p(X) :- q(X), X < Y, r(Y).")
        assert safe
        assert rendered == "p(X) :- q(X); r(Y); X<Y."

    def test_equality_no_flip_when_left_binds(self) -> None:
        # Y bound by q(Y); X = Y binds X from the left, so it is NOT flipped.
        safe, rendered, _ = self.check("p(X) :- X = Y, q(Y).")
        assert safe
        assert rendered == "p(X) :- q(Y); X=Y."

    def test_equality_flip_when_right_binds(self) -> None:
        # Y bound by q(Y); 'Y = X' must bind X via the right-hand side, so it is
        # flipped to 'X=Y'.
        safe, rendered, _ = self.check("p(X) :- q(Y), Y = X.")
        assert safe
        assert rendered == "p(X) :- q(Y); X=Y."

    # --- unsafe rules ------------------------------------------------------

    def test_unsafe_unbound_head_variable(self) -> None:
        safe, _, unsafe = self.check("p(X) :- q(Y).")
        assert not safe
        assert unsafe == ["X"]

    def test_unsafe_negative_literal_does_not_bind(self) -> None:
        safe, _, unsafe = self.check("p(X) :- not q(X).")
        assert not safe
        assert unsafe == ["X"]

    def test_unsafe_comparison_does_not_bind(self) -> None:
        # X < Y cannot bind X; only Y is provided by q(Y).
        safe, _, unsafe = self.check("p(X) :- X < Y, q(Y).")
        assert not safe
        assert unsafe == ["X"]

    def test_unsafe_reports_all_unbound(self) -> None:
        safe, _, unsafe = self.check("p(X, Y) :- q(Z).")
        assert not safe
        assert unsafe == ["X", "Y"]

    # --- arithmetic / linear terms ----------------------------------------

    def test_linear_term_binds(self) -> None:
        # 1*X+1 is the canonical linear form; matching it binds X.
        safe, _, unsafe = self.check("p(X) :- q(1*X+1).")
        assert safe
        assert unsafe == []

    def test_nonlinear_arithmetic_does_not_bind(self) -> None:
        # X*X is not linear, so X is not provided by the match.
        safe, _, unsafe = self.check("p(X) :- q(X*X).")
        assert not safe
        assert unsafe == ["X"]

    def test_unary_minus_preserves_binding(self) -> None:
        safe, _, unsafe = self.check("p(X) :- q(-X).")
        assert safe

    def test_absolute_value_does_not_bind(self) -> None:
        safe, _, unsafe = self.check("p(X) :- q(|X|).")
        assert not safe
        assert unsafe == ["X"]

    def test_function_argument_binds(self) -> None:
        safe, _, _ = self.check("p(X) :- q(f(X)).")
        assert safe

    # --- aggregates --------------------------------------------------------

    def test_body_aggregate_left_guard_binds(self) -> None:
        safe, _, unsafe = self.check("p(N) :- N = #count{ X : q(X) }.")
        assert safe
        assert unsafe == []

    def test_body_aggregate_non_equal_guard_does_not_bind(self) -> None:
        # N < #count{...} cannot bind N.
        safe, _, unsafe = self.check("p(N) :- N < #count{ X : q(X) }.")
        assert not safe
        assert unsafe == ["N"]

    def test_local_unsafe_in_aggregate_element(self) -> None:
        # Z appears in the element tuple but is never bound by the condition.
        safe, _, unsafe = self.check("p :- 1 = #count{ Z : q(Y) }.")
        assert not safe
        assert unsafe == ["Z"]

    def test_local_unsafe_when_guard_var_only_in_condition(self) -> None:
        # Y appears both in the element condition and on the guard, but nothing
        # in the global scope binds it, so Y is unsafe.
        safe, _, unsafe = self.check(":- #sum{ X : p(X,Y) } = Y.")
        assert not safe
        assert unsafe == ["Y"]

    # --- conditional literals / disjunction / head -------------------------

    def test_body_conditional_literal_safe(self) -> None:
        safe, _, unsafe = self.check("p :- q(X) : r(X).")
        assert safe
        assert unsafe == []

    def test_head_disjunction_safe(self) -> None:
        safe, _, unsafe = self.check("a(X) ; b(X) :- c(X).")
        assert safe
        assert unsafe == []

    def test_constraint_no_variables(self) -> None:
        safe, rendered, unsafe = self.check(":- a, b.")
        assert safe
        assert unsafe == []

    # --- other statement kinds --------------------------------------------

    def test_show_term_must_be_bound(self) -> None:
        safe, _, _ = self.check("#show p(X) : q(X).")
        assert safe

    def test_show_term_unbound_is_unsafe(self) -> None:
        safe, _, unsafe = self.check("#show p(X) : q(Y).")
        assert not safe
        assert unsafe == ["X"]

    def test_external_body_checked(self) -> None:
        assert self.check("#external p(X) : q(X).")[0]
        safe, _, unsafe = self.check("#external p(X) : q(Y).")
        assert not safe
        assert unsafe == ["X"]

    def test_program_statement_trivially_safe(self) -> None:
        safe, _, unsafe = self.check("#program base.")
        assert safe
        assert unsafe == []

    # --- normalisation preconditions raise --------------------------------

    def test_multi_guard_comparison_raises(self) -> None:
        with pytest.raises(SafetyError):
            self.check("p(X) :- X = Y = Z.")

    def test_set_aggregate_raises(self) -> None:
        with pytest.raises(SafetyError):
            self.check("p :- a { q(X) } b.")

    def test_optimize_raises(self) -> None:
        with pytest.raises(SafetyError):
            self.check("#minimize{ X : q(X) }.")


class TestAnalyzeHelpers:
    _lib: Library

    def setup_method(self, method: object) -> None:
        self._lib = Library()

    def test_is_provided(self) -> None:
        assert is_provided({"X", "Y"}, ["X", "Y"])
        assert not is_provided({"X"}, ["X", "Y"])
        # auxiliary "$"-prefixed variables count as always provided
        assert is_provided(set(), ["$aux"])

    def test_check_linear_recognises_canonical_form(self) -> None:
        term = ast.parse_term(self._lib, "1*X+1")
        assert check_linear(term) == "X"

    def test_check_linear_rejects_nonlinear(self) -> None:
        assert check_linear(ast.parse_term(self._lib, "X+1")) is None
        assert check_linear(ast.parse_term(self._lib, "X*X")) is None
        assert check_linear(ast.parse_term(self._lib, "0*X+1")) is None

    def test_select_variables_global_excludes_element_locals(self) -> None:
        stm = ast.parse_statement(self._lib, "p(N) :- N = #count{ X : q(X, Y) }.")
        # N is global; X and Y are local to the aggregate element.
        assert select_variables(stm, VariableContext.GLOBAL) == {"N"}
        assert select_variables(stm, VariableContext.ALL) == {"N", "X", "Y"}

    def test_select_variables_global_includes_guards(self) -> None:
        stm = ast.parse_statement(self._lib, "p(N) :- N = #count{ X : q(X) }.")
        # the guard variable N is global even though the element body is local
        assert "N" in select_variables(stm, VariableContext.GLOBAL)
