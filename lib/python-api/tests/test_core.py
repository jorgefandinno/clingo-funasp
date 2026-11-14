"""
Unit tests for clingo_funasp.core module.
"""

from clingo_funasp.core import Library, version


class TestCore:
    """
    Unit tests for clingo_funasp.core module.
    """

    def test_version(self):
        """
        Test the version function.
        """
        assert version() >= (6, 0, 0)

    def test_library(self):
        """
        Test library creation.
        """
        with Library() as lib:
            assert lib is not None
