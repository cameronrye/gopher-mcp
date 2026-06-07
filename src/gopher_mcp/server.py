"""Main MCP server implementation for Gopher and Gemini protocols."""

import asyncio
from typing import Any, Dict, List, Optional

import structlog
from mcp.server.fastmcp import FastMCP

from .config import get_config
from .gopher_client import GopherClient
from .gemini_client import GeminiClient
from .models import GopherFetchRequest, GeminiFetchRequest

logger = structlog.get_logger(__name__)

# Initialize FastMCP server
mcp = FastMCP("gopher-mcp")

# Bounds for the batch tools: cap the list length and the number of in-flight
# connections so a caller (or attacker-steered model) cannot fan out an
# unbounded number of concurrent requests.
MAX_BATCH_URLS = 50
BATCH_CONCURRENCY = 5


class ClientManager:
    """Singleton manager for Gopher and Gemini client instances."""

    _instance: Optional["ClientManager"] = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize the client manager."""
        self._gopher_client: Optional[GopherClient] = None
        self._gemini_client: Optional[GeminiClient] = None
        self._gopher_lock = asyncio.Lock()
        self._gemini_lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls) -> "ClientManager":
        """Get or create the singleton instance."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def get_gopher_client(self) -> GopherClient:
        """Get or create the Gopher client instance."""
        async with self._gopher_lock:
            if self._gopher_client is None:
                config = get_config()
                gopher_config = config.gopher

                self._gopher_client = GopherClient(
                    max_response_size=gopher_config.max_response_size,
                    timeout_seconds=gopher_config.timeout_seconds,
                    cache_enabled=gopher_config.cache_enabled,
                    cache_ttl_seconds=gopher_config.cache_ttl_seconds,
                    max_cache_entries=gopher_config.max_cache_entries,
                    allowed_hosts=gopher_config.allowed_hosts,
                    allow_local_hosts=gopher_config.allow_local_hosts,
                    max_selector_length=gopher_config.max_selector_length,
                    max_search_length=gopher_config.max_search_length,
                )
                logger.info(
                    "Gopher client initialized",
                    allowed_hosts=gopher_config.allowed_hosts,
                    cache_enabled=self._gopher_client.cache_enabled,
                    timeout_seconds=self._gopher_client.timeout_seconds,
                )
            return self._gopher_client

    async def get_gemini_client(self) -> GeminiClient:
        """Get or create the Gemini client instance."""
        async with self._gemini_lock:
            if self._gemini_client is None:
                config = get_config()
                gemini_config = config.gemini

                # Convert Path to str if needed
                tofu_path = (
                    str(gemini_config.tofu_storage_path)
                    if gemini_config.tofu_storage_path
                    else None
                )
                client_certs_path = (
                    str(gemini_config.client_certs_storage_path)
                    if gemini_config.client_certs_storage_path
                    else None
                )

                self._gemini_client = GeminiClient(
                    max_response_size=gemini_config.max_response_size,
                    timeout_seconds=gemini_config.timeout_seconds,
                    cache_enabled=gemini_config.cache_enabled,
                    cache_ttl_seconds=gemini_config.cache_ttl_seconds,
                    max_cache_entries=gemini_config.max_cache_entries,
                    allowed_hosts=gemini_config.allowed_hosts,
                    allow_local_hosts=gemini_config.allow_local_hosts,
                    tofu_enabled=gemini_config.tofu_enabled,
                    tofu_storage_path=tofu_path,
                    client_certs_enabled=gemini_config.client_certs_enabled,
                    client_certs_storage_path=client_certs_path,
                )
                logger.info(
                    "Gemini client initialized",
                    allowed_hosts=gemini_config.allowed_hosts,
                    cache_enabled=self._gemini_client.cache_enabled,
                    timeout_seconds=self._gemini_client.timeout_seconds,
                    tofu_enabled=self._gemini_client.tofu_enabled,
                    client_certs_enabled=self._gemini_client.client_certs_enabled,
                )
            return self._gemini_client

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._gopher_client:
            await self._gopher_client.close()
            self._gopher_client = None
        if self._gemini_client:
            await self._gemini_client.close()
            self._gemini_client = None


# Global client manager instance
_client_manager: Optional[ClientManager] = None


async def get_client_manager() -> ClientManager:
    """Get or create the global client manager instance."""
    global _client_manager
    if _client_manager is None:
        _client_manager = await ClientManager.get_instance()
    return _client_manager


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
        manager = await get_client_manager()
        client = await manager.get_gopher_client()
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
        manager = await get_client_manager()
        client = await manager.get_gemini_client()
        response = await client.fetch(request.url)
        return response.model_dump()
    except Exception as e:
        logger.error("Gemini fetch failed", url=url, error=str(e))
        raise


@mcp.tool()
async def gopher_batch_fetch(urls: List[str]) -> List[Dict[str, Any]]:
    """Fetch multiple Gopher URLs in parallel for improved performance.

    Uses asyncio.gather() to fetch all URLs concurrently, which is much
    faster than fetching them sequentially. Useful for fetching multiple
    menu items or related resources at once.

    Args:
        urls: List of Gopher URLs to fetch

    Returns:
        List of responses in the same order as the input URLs

    """
    try:
        if len(urls) > MAX_BATCH_URLS:
            raise ValueError(
                f"Too many URLs in batch request: {len(urls)} (max {MAX_BATCH_URLS})"
            )

        manager = await get_client_manager()
        client = await manager.get_gopher_client()
        semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

        from .models import ErrorResult

        async def fetch_one(url: str) -> Dict[str, Any]:
            async with semaphore:
                try:
                    request = GopherFetchRequest(url=url)
                except Exception as e:
                    return ErrorResult(
                        error={"code": "INVALID_REQUEST", "message": str(e)},
                        requestInfo={"url": url},
                    ).model_dump()
                try:
                    response = await client.fetch(request.url)
                    return response.model_dump()
                except Exception as e:  # defensive: client.fetch normally never raises
                    return ErrorResult(
                        error={"code": "FETCH_ERROR", "message": str(e)},
                        requestInfo={"url": url},
                    ).model_dump()

        # Bounded concurrency: at most BATCH_CONCURRENCY in-flight at once.
        results = await asyncio.gather(*[fetch_one(url) for url in urls])
        return list(results)
    except Exception as e:
        logger.error("Gopher batch fetch failed", error=str(e))
        raise


@mcp.tool()
async def gemini_batch_fetch(urls: List[str]) -> List[Dict[str, Any]]:
    """Fetch multiple Gemini URLs in parallel for improved performance.

    Uses asyncio.gather() to fetch all URLs concurrently, which is much
    faster than fetching them sequentially. Useful for fetching multiple
    pages or related resources at once.

    Args:
        urls: List of Gemini URLs to fetch

    Returns:
        List of responses in the same order as the input URLs

    """
    try:
        if len(urls) > MAX_BATCH_URLS:
            raise ValueError(
                f"Too many URLs in batch request: {len(urls)} (max {MAX_BATCH_URLS})"
            )

        manager = await get_client_manager()
        client = await manager.get_gemini_client()
        semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

        from .models import GeminiErrorResult

        async def fetch_one(url: str) -> Dict[str, Any]:
            async with semaphore:
                try:
                    request = GeminiFetchRequest(url=url)
                except Exception as e:
                    return GeminiErrorResult(
                        error={"code": "INVALID_REQUEST", "message": str(e)},
                        requestInfo={"url": url},
                    ).model_dump()
                try:
                    response = await client.fetch(request.url)
                    return response.model_dump()
                except Exception as e:  # defensive: client.fetch normally never raises
                    return GeminiErrorResult(
                        error={"code": "FETCH_ERROR", "message": str(e)},
                        requestInfo={"url": url},
                    ).model_dump()

        # Bounded concurrency: at most BATCH_CONCURRENCY in-flight at once.
        results = await asyncio.gather(*[fetch_one(url) for url in urls])
        return list(results)
    except Exception as e:
        logger.error("Gemini batch fetch failed", error=str(e))
        raise


async def cleanup() -> None:
    """Cleanup resources."""
    global _client_manager
    if _client_manager:
        await _client_manager.cleanup()
        _client_manager = None


def main() -> None:
    """Main entry point for the server."""
    from . import __main__

    __main__.main()
