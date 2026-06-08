"""Tests for package-level metadata."""

from importlib.metadata import version


def test_version_is_derived_from_package_metadata():
    """__version__ is single-sourced from the installed package metadata
    (pyproject.toml), so it can never drift from a hardcoded copy."""
    import gopher_mcp

    assert gopher_mcp.__version__ == version("gopher-mcp")


def test_version_is_a_non_empty_string():
    import gopher_mcp

    assert isinstance(gopher_mcp.__version__, str)
    assert gopher_mcp.__version__
