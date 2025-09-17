"""MCP tool definitions for Gopher operations.

This module provides manual tool creation functions for users who want to
create MCP tool definitions programmatically. The main server implementation
in server.py uses FastMCP's decorator approach instead.
"""

from mcp.types import Tool


def create_gopher_fetch_tool() -> Tool:
    """Create the gopher.fetch tool definition.

    Returns:
        Tool definition for gopher.fetch

    """
    return Tool(
        name="gopher.fetch",
        description=(
            "Fetch Gopher menus or text by URL. Supports all standard Gopher "
            "item types including menus (type 1), text files (type 0), search "
            "servers (type 7), and binary files. Returns structured JSON "
            "responses optimized for LLM consumption."
        ),
        inputSchema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^gopher://",
                    "description": (
                        "Full Gopher URL to fetch. Examples: "
                        "gopher://gopher.floodgap.com/1/ (menu), "
                        "gopher://gopher.floodgap.com/0/about.txt (text), "
                        "gopher://veronica.example.com/7/search%09python (search)"
                    ),
                    "examples": [
                        "gopher://gopher.floodgap.com/1/",
                        "gopher://gopher.floodgap.com/0/about.txt",
                        "gopher://veronica.example.com/7/search%09python",
                    ],
                }
            },
            "additionalProperties": False,
        },
    )
