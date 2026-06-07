"""Gopher MCP - A Model Context Protocol server for Gopher and Gemini protocols.

This package provides a cross-platform MCP server that allows LLMs to browse
Gopher and Gemini resources safely and efficiently.
"""

__version__ = "0.3.0"
__author__ = "Gopher MCP Team"
__email__ = "team@gopher-mcp.dev"
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
