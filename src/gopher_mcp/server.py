"""Main MCP server implementation for Gopher and Gemini protocols."""

import os
from typing import Any, Dict, List, Optional

import structlog
from mcp.server.fastmcp import FastMCP

from .gopher_client import GopherClient
from .gemini_client import GeminiClient
from .models import GopherFetchRequest, GeminiFetchRequest

logger = structlog.get_logger(__name__)

# Initialize FastMCP server
mcp = FastMCP("gopher-mcp")

# Global client instances
_gopher_client: GopherClient | None = None
_gemini_client: GeminiClient | None = None


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


def get_gemini_client() -> GeminiClient:
    """Get or create the global Gemini client instance."""
    global _gemini_client
    if _gemini_client is None:
        # Parse allowed hosts from environment
        allowed_hosts_env = os.getenv("GEMINI_ALLOWED_HOSTS")
        allowed_hosts: Optional[List[str]] = None
        if allowed_hosts_env:
            allowed_hosts = [host.strip() for host in allowed_hosts_env.split(",")]

        _gemini_client = GeminiClient(
            max_response_size=int(
                os.getenv("GEMINI_MAX_RESPONSE_SIZE", "1048576")
            ),  # 1MB
            timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30.0")),
            cache_enabled=os.getenv("GEMINI_CACHE_ENABLED", "true").lower() == "true",
            cache_ttl_seconds=int(os.getenv("GEMINI_CACHE_TTL_SECONDS", "300")),
            max_cache_entries=int(os.getenv("GEMINI_MAX_CACHE_ENTRIES", "1000")),
            allowed_hosts=allowed_hosts,
            tofu_enabled=os.getenv("GEMINI_TOFU_ENABLED", "true").lower() == "true",
            tofu_storage_path=os.getenv("GEMINI_TOFU_STORAGE_PATH"),
            client_certs_enabled=os.getenv(
                "GEMINI_CLIENT_CERTS_ENABLED", "true"
            ).lower()
            == "true",
            client_certs_storage_path=os.getenv("GEMINI_CLIENT_CERTS_STORAGE_PATH"),
        )
        logger.info(
            "Gemini client initialized",
            allowed_hosts=allowed_hosts,
            cache_enabled=_gemini_client.cache_enabled,
            timeout_seconds=_gemini_client.timeout_seconds,
            tofu_enabled=_gemini_client.tofu_enabled,
            client_certs_enabled=_gemini_client.client_certs_enabled,
        )
    return _gemini_client


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


@mcp.tool()
async def gemini_fetch(url: str) -> Dict[str, Any]:
    """Fetch Gemini content by URL.

    Supports the Gemini protocol with TLS, TOFU certificate validation,
    client certificates, and gemtext parsing. Returns structured JSON
    responses optimized for LLM consumption.

    Args:
        url: Full Gemini URL to fetch (e.g., gemini://gemini.circumlunar.space/)

    """
    try:
        request = GeminiFetchRequest(url=url)
        client = get_gemini_client()
        response = await client.fetch(request.url)
        return response.model_dump()
    except Exception as e:
        logger.error("Gemini fetch failed", url=url, error=str(e))
        raise


async def cleanup() -> None:
    """Cleanup resources."""
    global _gopher_client, _gemini_client
    if _gopher_client:
        await _gopher_client.close()
        _gopher_client = None
    if _gemini_client:
        await _gemini_client.close()
        _gemini_client = None
