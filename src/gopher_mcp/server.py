"""Main MCP server implementation for Gopher protocol."""

import os
from typing import Any, Dict, List, Optional

import structlog
from mcp.server.fastmcp import FastMCP

from .gopher_client import GopherClient
from .models import GopherFetchRequest

logger = structlog.get_logger(__name__)

# Initialize FastMCP server
mcp = FastMCP("gopher-mcp")

# Global gopher client instance
_gopher_client: GopherClient | None = None


def get_gopher_client() -> GopherClient:
    """Get or create the global Gopher client instance."""
    global _gopher_client
    if _gopher_client is None:
        # Parse allowed hosts from environment
        allowed_hosts_env = os.getenv("GOPHER_ALLOWED_HOSTS")
        allowed_hosts: Optional[List[str]] = None
        if allowed_hosts_env:
            allowed_hosts = [host.strip() for host in allowed_hosts_env.split(",")]

        _gopher_client = GopherClient(
            max_response_size=int(
                os.getenv("GOPHER_MAX_RESPONSE_SIZE", "1048576")
            ),  # 1MB
            timeout_seconds=float(os.getenv("GOPHER_TIMEOUT_SECONDS", "30.0")),
            cache_enabled=os.getenv("GOPHER_CACHE_ENABLED", "true").lower() == "true",
            cache_ttl_seconds=int(os.getenv("GOPHER_CACHE_TTL_SECONDS", "300")),
            max_cache_entries=int(os.getenv("GOPHER_MAX_CACHE_ENTRIES", "1000")),
            allowed_hosts=allowed_hosts,
            max_selector_length=int(os.getenv("GOPHER_MAX_SELECTOR_LENGTH", "1024")),
            max_search_length=int(os.getenv("GOPHER_MAX_SEARCH_LENGTH", "256")),
        )
        logger.info(
            "Gopher client initialized",
            allowed_hosts=allowed_hosts,
            cache_enabled=_gopher_client.cache_enabled,
            timeout_seconds=_gopher_client.timeout_seconds,
        )
    return _gopher_client


@mcp.tool()
async def gopher_fetch(url: str) -> Dict[str, Any]:
    """Fetch Gopher menus or text by URL.

    Supports all standard Gopher item types including menus (type 1),
    text files (type 0), search servers (type 7), and binary files.
    Returns structured JSON responses optimized for LLM consumption.

    Args:
        url: Full Gopher URL to fetch (e.g., gopher://gopher.floodgap.com/1/)
    """
    try:
        request = GopherFetchRequest(url=url)
        client = get_gopher_client()
        response = await client.fetch(request.url)
        return response.model_dump()
    except Exception as e:
        logger.error("Gopher fetch failed", url=url, error=str(e))
        raise


async def cleanup() -> None:
    """Cleanup resources."""
    global _gopher_client
    if _gopher_client:
        await _gopher_client.close()
        _gopher_client = None
