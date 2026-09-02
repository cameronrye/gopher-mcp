"""Tests for package-level metadata and the package's import surface."""

import subprocess
import sys
from importlib.metadata import version
from unittest.mock import patch

import pytest


def test_version_is_derived_from_package_metadata():
    """__version__ is single-sourced from the installed package metadata
    (pyproject.toml), so it can never drift from a hardcoded copy."""
    import gopher_mcp

    assert gopher_mcp.__version__ == version("gopher-mcp")


def test_version_is_a_non_empty_string():
    import gopher_mcp

    assert isinstance(gopher_mcp.__version__, str)
    assert gopher_mcp.__version__


def test_version_flag_reports_it_from_the_cli(capsys):
    """ "Which version are you running?" has to be answerable for the uvx and
    Docker installs the docs recommend, where `python -c "import gopher_mcp"`
    is not available."""
    from gopher_mcp import __main__ as entry

    with patch("sys.argv", ["gopher-mcp", "--version"]), pytest.raises(SystemExit) as e:
        entry.main()

    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"gopher-mcp {version('gopher-mcp')}"


class TestLazyServerExports:
    """The package re-exports the server's tools without importing it eagerly."""

    def test_importing_a_leaf_module_does_not_pull_in_the_mcp_sdk(self):
        """A subprocess because the suite has long since imported the SDK.

        The eager re-export made ``import gopher_mcp.gemtext`` load FastMCP,
        cryptography and 734 modules, which coupled the pure parsers to an SDK
        they never call -- and this project is deliberately holding back from
        the mcp 2.x that would break that import.
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, gopher_mcp.gemtext;"
                " print(sorted({'mcp', 'cryptography'} & sys.modules.keys()))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        assert result.stdout.strip() == "[]"

    def test_the_exports_still_resolve_from_the_package(self):
        import gopher_mcp
        from gopher_mcp import server

        for name in gopher_mcp.__all__:
            assert getattr(gopher_mcp, name) is getattr(server, name)

    def test_an_unknown_attribute_still_raises_attribute_error(self):
        import gopher_mcp

        with pytest.raises(AttributeError, match="no attribute 'not_a_tool'"):
            getattr(gopher_mcp, "not_a_tool")  # noqa: B009 - the lookup is the test
