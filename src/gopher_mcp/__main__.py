"""Main entry point for the Gopher MCP server."""

import argparse
import asyncio
import contextlib

from .config import configure_logging, get_config
from .server import cleanup, mcp


def main() -> None:
    """Run the main entry point."""
    # Configure logging (to stderr) from ServerConfig before anything logs.
    configure_logging(get_config().server)

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
        help="Mount path for the SSE transport (only used with --transport sse)",
    )

    args = parser.parse_args()

    # FastMCP's run() only honors mount_path for the SSE transport; accepting it
    # elsewhere would silently do nothing. Reject it explicitly instead.
    if args.mount_path is not None and args.transport != "sse":
        parser.error("--mount-path is only supported with --transport sse")

    try:
        # FastMCP handles its own event loop.
        if args.transport == "sse":
            mcp.run(transport=args.transport, mount_path=args.mount_path)
        else:
            mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        pass
    finally:
        # Release client/transport resources on shutdown.
        with contextlib.suppress(Exception):
            asyncio.run(cleanup())


if __name__ == "__main__":
    main()
