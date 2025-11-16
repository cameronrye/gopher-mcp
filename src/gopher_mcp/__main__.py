"""Main entry point for the Gopher MCP server."""

import argparse

from .server import mcp


def main() -> None:
    """Run the main entry point."""
    parser = argparse.ArgumentParser(description="Gopher MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--mount-path",
        type=str,
        default=None,
        help="Mount path for HTTP transport (optional)",
    )

    args = parser.parse_args()

    try:
        # FastMCP handles its own event loop
        mcp.run(transport=args.transport, mount_path=args.mount_path)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
