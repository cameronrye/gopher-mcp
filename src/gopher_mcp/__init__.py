"""Gopher MCP - A Model Context Protocol server for Gopher and Gemini protocols.

This package provides a cross-platform MCP server that allows LLMs to browse
Gopher and Gemini resources safely and efficiently.
"""

from importlib.metadata import PackageNotFoundError, version

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

from .server import (
    gemini_batch_fetch,
    gemini_fetch,
    gopher_batch_fetch,
    gopher_fetch,
    mcp,
)

__all__ = [
    "gemini_batch_fetch",
    "gemini_fetch",
    "gopher_batch_fetch",
    "gopher_fetch",
    "mcp",
]
