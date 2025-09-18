"""Gopher MCP - A Model Context Protocol server for Gopher and Gemini protocols.

This package provides a cross-platform MCP server that allows LLMs to browse
Gopher and Gemini resources safely and efficiently.
"""

__version__ = "0.1.0"
__author__ = "Gopher MCP Team"
__email__ = "team@gopher-mcp.dev"
__license__ = "MIT"

from .server import gopher_fetch, gemini_fetch, mcp

__all__ = [
    "mcp",
    "gopher_fetch",
    "gemini_fetch",
]
