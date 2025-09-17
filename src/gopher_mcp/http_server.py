"""HTTP transport server for Gopher MCP."""

import asyncio
import os
from typing import Any, Optional

import structlog

from .server import cleanup

logger = structlog.get_logger(__name__)


class HTTPServer:
    """HTTP transport server for MCP."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        """Initialize HTTP server.

        Args:
            host: Host to bind to
            port: Port to bind to

        """
        self.host = host
        self.port = port
        self.server: Optional[Any] = None

    async def start(self) -> None:
        """Start the HTTP server."""
        try:
            from aiohttp import web, web_runner

            app = web.Application()
            app.router.add_post("/mcp", self._handle_mcp_request)
            app.router.add_get("/health", self._handle_health)
            app.router.add_options("/mcp", self._handle_options)

            # Add CORS headers
            app.middlewares.append(HTTPServer._cors_middleware)

            runner = web_runner.AppRunner(app)
            await runner.setup()

            site = web_runner.TCPSite(runner, self.host, self.port)
            await site.start()

            self.server = runner
            logger.info(f"HTTP server started on {self.host}:{self.port}")

        except ImportError:
            logger.error("aiohttp not installed. Install with: uv add aiohttp")
            raise

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self.server:
            await self.server.cleanup()
            self.server = None
            logger.info("HTTP server stopped")

    @staticmethod
    async def _cors_middleware(request: Any, handler: Any) -> Any:
        """Add CORS headers to responses."""
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    async def _handle_health(self, request: Any) -> Any:
        """Handle health check requests."""
        from aiohttp import web

        return web.json_response({"status": "healthy", "service": "gopher-mcp"})

    async def _handle_options(self, request: Any) -> Any:
        """Handle CORS preflight requests."""
        from aiohttp import web

        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )

    async def _handle_mcp_request(self, request: Any) -> Any:
        """Handle MCP JSON-RPC requests."""
        from aiohttp import web

        try:
            data = await request.json()

            # For now, return a simple error indicating this is not implemented
            # The proper way would be to use FastMCP's built-in HTTP transport
            logger.warning("Manual MCP request handling not fully implemented")
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": "Method not implemented - use FastMCP's built-in HTTP transport",
                        "data": "Call mcp.run(transport='http') instead",
                    },
                    "id": data.get("id") if isinstance(data, dict) else None,
                },
                status=501,
            )

        except Exception as e:
            logger.error("Error handling MCP request", error=str(e))
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": str(e),
                    },
                    "id": None,
                },
                status=500,
            )


async def run_http_server(host: str = "localhost", port: int = 8000) -> None:
    """Run the HTTP server."""
    server = HTTPServer(host, port)

    try:
        await server.start()
        logger.info(f"Gopher MCP HTTP server running on http://{host}:{port}")

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down HTTP server...")
    finally:
        await server.stop()
        await cleanup()


if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("GOPHER_HTTP_HOST", "localhost")
    port = int(os.getenv("GOPHER_HTTP_PORT", "8000"))

    # Run the server
    asyncio.run(run_http_server(host, port))
