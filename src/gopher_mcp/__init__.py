"""Gopher MCP - A Model Context Protocol server for Gopher and Gemini protocols.

This package provides a cross-platform MCP server that allows LLMs to browse
Gopher and Gemini resources safely and efficiently.
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Any

# Annotated because server.py imports this name back out of the package while
# __init__ is still executing; without the annotation mypy cannot infer a type
# through that partially-initialized module and reports has-type.
__version__: str
try:
    # Single source of truth: the version declared in pyproject.toml. Deriving
    # it here removes the hardcoded copy that could silently drift from the tag.
    __version__ = version("gopher-mcp")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"

__author__ = "Cameron Rye"
__email__ = "c@meron.io"
__license__ = "MIT"

__all__ = [
    "gemini_batch_fetch",
    "gemini_fetch",
    "gopher_batch_fetch",
    "gopher_fetch",
    "mcp",
]


def __getattr__(name: str) -> Any:
    """Resolve the server's exports on first access (PEP 562).

    Importing them here eagerly pulled FastMCP and cryptography -- 734 modules,
    0.3 s -- into every ``import gopher_mcp.gemtext``, coupling the pure parsing
    modules (whose own docstrings claim to sit at the bottom of the import
    graph) to the MCP SDK for no benefit. The names stay importable from the
    package; only the cost moves to whoever actually asks for them.

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The named server export.

    Raises:
        AttributeError: If the package has no such attribute.
    """
    if name in __all__:
        # Lazy on purpose (see the docstring above): hoisting this would pull
        # FastMCP and cryptography into every ``import gopher_mcp.*``, which is
        # the entire cost this PEP 562 hook exists to avoid.
        from . import server  # noqa: PLC0415

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
