"""Main entry point for the Gopher MCP server."""

import sys

from .server import mcp


def main() -> None:
    """Main entry point."""
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--http":
            # HTTP transport not yet implemented in FastMCP
            print("HTTP transport not yet supported", file=sys.stderr)
            sys.exit(1)
        else:
            # FastMCP handles its own event loop
            mcp.run(transport="stdio")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
