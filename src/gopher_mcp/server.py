"""Main MCP server implementation for Gopher and Gemini protocols."""

import asyncio
from typing import Annotated, Any, Optional
from urllib.parse import quote

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .config import get_config
from .gemini_client import GeminiClient
from .gopher_client import GopherClient
from .models import GeminiFetchRequest, GopherFetchRequest

logger = structlog.get_logger(__name__)

# High-level guidance surfaced to the model by MCP clients.
SERVER_INSTRUCTIONS = (
    "Browse Gopher and Gemini resources. Use gopher_fetch for gopher:// URLs and "
    "gemini_fetch for gemini:// URLs; the *_batch_fetch variants take several "
    "URLs at once. Navigate by following the `nextUrl` field of Gopher menu "
    "items and the `links` of Gemini gemtext documents. Binary and oversize "
    "bodies are returned as metadata only (no raw bytes). On a Gemini status-10 "
    "or status-11 (input) response, call gemini_fetch again with the `input` "
    "argument set to the user's answer rather than building a query string by "
    "hand. All fetches are read-only and may reach arbitrary external hosts."
)

# Read-only network fetchers reaching arbitrary external hosts -- exactly what
# readOnlyHint/openWorldHint signal to clients for consent and safe invocation.
_FETCH_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Rich, LLM-facing parameter schemas. Description + examples reach the model via
# FastMCP's generated inputSchema; we deliberately do NOT add a `pattern`
# constraint so an invalid URL still returns a structured error (the no-raise
# contract) instead of a FastMCP ToolError.
_GopherUrl = Annotated[
    str,
    Field(
        description=(
            "A full gopher:// URL. The first path character is the item type "
            "(1=menu, 0=text file, 7=search). Follow `nextUrl` from menu items "
            "to navigate. Example: gopher://gopher.floodgap.com/1/"
        ),
        examples=[
            "gopher://gopher.floodgap.com/1/",
            "gopher://gopher.floodgap.com/0/gopher/proxy",
            "gopher://gopher.floodgap.com/7/v2/vs",
        ],
    ),
]
_GeminiUrl = Annotated[
    str,
    Field(
        description=(
            "A full gemini:// URL, e.g. gemini://geminiprotocol.net/ . On a "
            "status-10/11 input response, call again with the `input` argument "
            "set to the user's answer instead of hand-building a query string."
        ),
        examples=[
            "gemini://geminiprotocol.net/",
            "gemini://kennedy.gemi.dev/",
        ],
    ),
]
_GeminiInput = Annotated[
    str | None,
    Field(
        description=(
            "Optional answer to a Gemini status-10/11 input prompt. It is "
            "percent-encoded and sent as the query string, so pass the raw "
            "answer (spaces, &, = and unicode are handled for you). Replaces any "
            "query already present in `url`."
        ),
    ),
]

# Initialize FastMCP server
mcp = FastMCP("gopher-mcp", instructions=SERVER_INSTRUCTIONS)

# Bounds for the batch tools: cap the list length and the number of in-flight
# connections so a caller (or attacker-steered model) cannot fan out an
# unbounded number of concurrent requests.
MAX_BATCH_URLS = 50
BATCH_CONCURRENCY = 5

# LLM-facing messages for the *defensive* catch-all paths. ``client.fetch``
# normally returns a sanitized ErrorResult rather than raising, so reaching these
# means an unexpected internal exception -- whose ``str(e)`` can carry local
# paths or library internals. Log the detail server-side, return a generic
# message to the model. (Validation errors keep their specific message: those are
# safe Pydantic messages the model needs to correct its input.)
_GENERIC_FETCH_ERROR = "An unexpected error occurred while fetching the resource."
_GENERIC_SETUP_ERROR = "Failed to initialize the fetch client."


class ClientManager:
    """Singleton manager for Gopher and Gemini client instances."""

    _instance: Optional["ClientManager"] = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize the client manager."""
        self._gopher_client: GopherClient | None = None
        self._gemini_client: GeminiClient | None = None
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
                    max_rendered_chars=gopher_config.max_rendered_chars,
                    max_menu_items=gopher_config.max_menu_items,
                    requests_per_minute=gopher_config.requests_per_minute,
                    max_concurrent_requests=gopher_config.max_concurrent_requests,
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
                    tofu_reject_expired=gemini_config.tofu_reject_expired,
                    client_certs_enabled=gemini_config.client_certs_enabled,
                    client_certs_storage_path=client_certs_path,
                    max_rendered_chars=gemini_config.max_rendered_chars,
                    requests_per_minute=gemini_config.requests_per_minute,
                    max_concurrent_requests=gemini_config.max_concurrent_requests,
                    denied_mime_types=gemini_config.denied_mime_types,
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


async def get_client_manager() -> ClientManager:
    """Get or create the singleton client manager instance.

    ``ClientManager`` already provides a properly locked singleton, so this is a
    thin wrapper kept for call-site readability (and as a patch point in tests).
    """
    return await ClientManager.get_instance()


@mcp.tool(annotations=_FETCH_ANNOTATIONS, title="Fetch Gopher resource")
async def gopher_fetch(url: _GopherUrl) -> dict[str, Any]:
    """Fetch Gopher menus or text by URL.

    Supports all standard Gopher item types including menus (type 1),
    text files (type 0), search servers (type 7), and binary files.
    Returns structured JSON responses optimized for LLM consumption.

    Args:
        url: Full Gopher URL to fetch (e.g., gopher://gopher.floodgap.com/1/)

    """
    from .models import ErrorResult

    # Validate the request separately so a bad URL becomes a sanitized,
    # structured error instead of a raised ValidationError that FastMCP would
    # surface to the model as a raw ToolError (matching the batch tools and the
    # client layer's no-raise contract).
    try:
        request = GopherFetchRequest(url=url)
    except Exception as e:
        logger.info("Rejected invalid Gopher URL", url=url, error=str(e))
        return ErrorResult(
            error={"code": "INVALID_REQUEST", "message": str(e)},
            requestInfo={"url": url},
        ).model_dump()

    try:
        manager = await get_client_manager()
        client = await manager.get_gopher_client()
        response = await client.fetch(request.url)
        return response.model_dump()
    except Exception as e:  # defensive: client.fetch normally returns ErrorResult
        logger.error("Gopher fetch failed", url=url, error=str(e))
        return ErrorResult(
            error={"code": "FETCH_ERROR", "message": _GENERIC_FETCH_ERROR},
            requestInfo={"url": url},
        ).model_dump()


@mcp.tool(annotations=_FETCH_ANNOTATIONS, title="Fetch Gemini resource")
async def gemini_fetch(url: _GeminiUrl, input: _GeminiInput = None) -> dict[str, Any]:
    """Fetch Gemini content by URL.

    Supports the Gemini protocol with TLS, TOFU certificate validation,
    client certificates, and gemtext parsing. Returns structured JSON
    responses optimized for LLM consumption.

    Args:
        url: Full Gemini URL to fetch (e.g., gemini://gemini.circumlunar.space/)
        input: Optional answer to a status-10/11 input prompt; it is
            percent-encoded and sent as the query string.

    """
    from .models import GeminiErrorResult

    # When answering a status-10/11 prompt, percent-encode the raw input and set
    # it as the query string so the model never hand-builds query strings (and
    # spaces/&/=/unicode survive). Replaces any query/fragment already present.
    effective_url = url
    if input is not None:
        base = url.split("#", 1)[0].split("?", 1)[0]
        effective_url = f"{base}?{quote(input, safe='')}"

    # Validate separately so a bad URL becomes a sanitized, structured error
    # instead of a raised ValidationError surfaced to the model as a ToolError.
    # Log only the base `url`, never the (possibly sensitive) input answer.
    try:
        request = GeminiFetchRequest(url=effective_url)
    except Exception as e:
        logger.info("Rejected invalid Gemini URL", url=url, error=str(e))
        return GeminiErrorResult(
            error={"code": "INVALID_REQUEST", "message": str(e)},
            requestInfo={"url": url},
        ).model_dump()

    try:
        manager = await get_client_manager()
        client = await manager.get_gemini_client()
        response = await client.fetch(request.url)
        return response.model_dump()
    except Exception as e:  # defensive: client.fetch normally returns ErrorResult
        logger.error("Gemini fetch failed", url=url, error=str(e))
        return GeminiErrorResult(
            error={"code": "FETCH_ERROR", "message": _GENERIC_FETCH_ERROR},
            requestInfo={"url": url},
        ).model_dump()


@mcp.tool(annotations=_FETCH_ANNOTATIONS, title="Fetch multiple Gopher resources")
async def gopher_batch_fetch(urls: list[str]) -> list[dict[str, Any]]:
    """Fetch multiple Gopher URLs in parallel for improved performance.

    Uses asyncio.gather() to fetch all URLs concurrently, which is much
    faster than fetching them sequentially. Useful for fetching multiple
    menu items or related resources at once.

    Args:
        urls: List of Gopher URLs to fetch (at most 50 per call)

    Returns:
        List of responses in the same order and of the same length as the input
        URLs, so callers can zip responses to requests by index.

    """
    from .models import ErrorResult

    # Over-limit is a sanitized, structured error -- not a raised exception that
    # FastMCP would surface to the model as a raw ToolError. Return ONE error per
    # input URL so the response stays index-aligned with the request (a single
    # element would silently break a caller zipping responses to URLs).
    if len(urls) > MAX_BATCH_URLS:
        message = f"Too many URLs in batch request: {len(urls)} (max {MAX_BATCH_URLS})"
        return [
            ErrorResult(
                error={"code": "INVALID_REQUEST", "message": message},
                requestInfo={"url": url},
            ).model_dump()
            for url in urls
        ]

    # Client setup can raise (e.g. a fail-closed corrupt TOFU/cert store);
    # return a sanitized error rather than letting it escape as a ToolError.
    try:
        manager = await get_client_manager()
        client = await manager.get_gopher_client()
    except Exception as e:
        logger.error("Gopher batch fetch setup failed", error=str(e))
        return [
            ErrorResult(
                error={"code": "FETCH_ERROR", "message": _GENERIC_SETUP_ERROR},
                requestInfo={"url": url},
            ).model_dump()
            for url in urls
        ]
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def fetch_one(url: str) -> dict[str, Any]:
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
                logger.error("Gopher batch item failed", url=url, error=str(e))
                return ErrorResult(
                    error={"code": "FETCH_ERROR", "message": _GENERIC_FETCH_ERROR},
                    requestInfo={"url": url},
                ).model_dump()

    # Bounded concurrency: at most BATCH_CONCURRENCY in-flight at once.
    results = await asyncio.gather(*[fetch_one(url) for url in urls])
    return list(results)


@mcp.tool(annotations=_FETCH_ANNOTATIONS, title="Fetch multiple Gemini resources")
async def gemini_batch_fetch(urls: list[str]) -> list[dict[str, Any]]:
    """Fetch multiple Gemini URLs in parallel for improved performance.

    Uses asyncio.gather() to fetch all URLs concurrently, which is much
    faster than fetching them sequentially. Useful for fetching multiple
    pages or related resources at once.

    Args:
        urls: List of Gemini URLs to fetch (at most 50 per call)

    Returns:
        List of responses in the same order and of the same length as the input
        URLs, so callers can zip responses to requests by index.

    """
    from .models import GeminiErrorResult

    # Over-limit is a sanitized, structured error -- not a raised exception that
    # FastMCP would surface to the model as a raw ToolError. Return ONE error per
    # input URL so the response stays index-aligned with the request.
    if len(urls) > MAX_BATCH_URLS:
        message = f"Too many URLs in batch request: {len(urls)} (max {MAX_BATCH_URLS})"
        return [
            GeminiErrorResult(
                error={"code": "INVALID_REQUEST", "message": message},
                requestInfo={"url": url},
            ).model_dump()
            for url in urls
        ]

    # Client setup can raise (e.g. a fail-closed corrupt TOFU/cert store);
    # return a sanitized error rather than letting it escape as a ToolError.
    try:
        manager = await get_client_manager()
        client = await manager.get_gemini_client()
    except Exception as e:
        logger.error("Gemini batch fetch setup failed", error=str(e))
        return [
            GeminiErrorResult(
                error={"code": "FETCH_ERROR", "message": _GENERIC_SETUP_ERROR},
                requestInfo={"url": url},
            ).model_dump()
            for url in urls
        ]
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def fetch_one(url: str) -> dict[str, Any]:
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
                logger.error("Gemini batch item failed", url=url, error=str(e))
                return GeminiErrorResult(
                    error={"code": "FETCH_ERROR", "message": _GENERIC_FETCH_ERROR},
                    requestInfo={"url": url},
                ).model_dump()

    # Bounded concurrency: at most BATCH_CONCURRENCY in-flight at once.
    results = await asyncio.gather(*[fetch_one(url) for url in urls])
    return list(results)


async def cleanup() -> None:
    """Cleanup resources and drop the singleton.

    Resetting ``ClientManager._instance`` (the single source of truth) ensures
    the next ``get_client_manager()`` builds a fresh manager instead of handing
    back one whose clients were just closed.
    """
    instance = ClientManager._instance
    if instance is not None:
        await instance.cleanup()
        ClientManager._instance = None


def main() -> None:
    """Main entry point for the server."""
    from . import __main__

    __main__.main()
