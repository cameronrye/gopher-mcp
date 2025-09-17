"""Gopher protocol client implementation."""

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Set

import pituophis
import structlog

from .models import (
    BinaryResult,
    CacheEntry,
    ErrorResult,
    GopherFetchResponse,
    GopherMenuItem,
    GopherURL,
    MenuResult,
    TextResult,
)
from .utils import parse_gopher_url

logger = structlog.get_logger(__name__)


class GopherClient:
    """Async Gopher protocol client with caching and safety features."""

    def __init__(
        self,
        *,
        max_response_size: int = 1024 * 1024,  # 1MB
        timeout_seconds: float = 30.0,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = 300,  # 5 minutes
        max_cache_entries: int = 1000,
        allowed_hosts: Optional[List[str]] = None,
        max_selector_length: int = 1024,
        max_search_length: int = 256,
    ) -> None:
        """Initialize the Gopher client.

        Args:
            max_response_size: Maximum response size in bytes
            timeout_seconds: Request timeout in seconds
            cache_enabled: Whether to enable response caching
            cache_ttl_seconds: Cache TTL in seconds
            max_cache_entries: Maximum number of cache entries
            allowed_hosts: List of allowed hostnames (None = allow all)
            max_selector_length: Maximum selector string length
            max_search_length: Maximum search query length

        """
        self.max_response_size = max_response_size
        self.timeout_seconds = timeout_seconds
        self.cache_enabled = cache_enabled
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_entries = max_cache_entries
        self.max_selector_length = max_selector_length
        self.max_search_length = max_search_length

        # Convert allowed hosts to a set for faster lookup
        self.allowed_hosts: Optional[Set[str]] = (
            set(allowed_hosts) if allowed_hosts else None
        )

        self._cache: Dict[str, CacheEntry] = {}

    def _validate_security(self, parsed_url: GopherURL) -> None:
        """Validate security constraints for a Gopher request.

        Args:
            parsed_url: Parsed Gopher URL

        Raises:
            ValueError: If security validation fails

        """
        # Check allowed hosts
        if self.allowed_hosts and parsed_url.host not in self.allowed_hosts:
            raise ValueError(f"Host '{parsed_url.host}' not in allowed hosts list")

        # Validate selector length
        if len(parsed_url.selector) > self.max_selector_length:
            raise ValueError(
                f"Selector too long: {len(parsed_url.selector)} > {self.max_selector_length}"
            )

        # Validate search query length
        if parsed_url.search and len(parsed_url.search) > self.max_search_length:
            raise ValueError(
                f"Search query too long: {len(parsed_url.search)} > {self.max_search_length}"
            )

        # Validate selector doesn't contain dangerous characters
        if re.search(r"[\r\n\t]", parsed_url.selector):
            raise ValueError("Selector contains invalid control characters")

        # Validate search query doesn't contain dangerous characters
        if parsed_url.search and re.search(r"[\r\n]", parsed_url.search):
            raise ValueError("Search query contains invalid control characters")

        # Validate port range
        if not 1 <= parsed_url.port <= 65535:
            raise ValueError(f"Invalid port number: {parsed_url.port}")

    async def fetch(self, url: str) -> GopherFetchResponse:
        """Fetch content from a Gopher URL.

        Args:
            url: Gopher URL to fetch

        Returns:
            Structured response based on content type

        """
        try:
            # Parse the URL
            parsed_url = parse_gopher_url(url)

            # Validate security constraints
            self._validate_security(parsed_url)

            # Check cache first
            if self.cache_enabled:
                cached_response = self._get_cached_response(url)
                if cached_response:
                    logger.info(
                        "Cache hit",
                        url=url,
                        cached=True,
                        response_type=getattr(cached_response, "kind", "unknown"),
                        response_size=getattr(cached_response, "bytes", 0),
                    )
                    return cached_response

            # Create request info for provenance
            request_info = {
                "url": url,
                "host": parsed_url.host,
                "port": parsed_url.port,
                "type": parsed_url.gopher_type,
                "selector": parsed_url.selector,
                "timestamp": time.time(),
            }

            # Fetch the content
            response = await self._fetch_content(parsed_url)
            if hasattr(response, "request_info"):
                response.request_info = request_info

            # Cache the response
            if self.cache_enabled:
                self._cache_response(url, response)

            logger.info(
                "Gopher fetch successful",
                url=url,
                host=parsed_url.host,
                port=parsed_url.port,
                gopher_type=parsed_url.gopher_type,
                selector=parsed_url.selector,
                search=parsed_url.search,
                response_type=getattr(response, "kind", "unknown"),
                response_size=getattr(response, "bytes", 0),
                cached=False,
            )

            return response

        except Exception as e:
            logger.error(
                "Gopher fetch failed",
                url=url,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ErrorResult(
                error={
                    "code": "FETCH_ERROR",
                    "message": str(e),
                },
                requestInfo={"url": url, "timestamp": time.time()},
            )

    async def _fetch_content(self, parsed_url: GopherURL) -> GopherFetchResponse:
        """Fetch content from parsed Gopher URL using Pituophis.

        Args:
            parsed_url: Parsed Gopher URL

        Returns:
            Appropriate response based on content type

        """
        try:
            # Create Pituophis request
            request = pituophis.Request(
                host=parsed_url.host,
                port=parsed_url.port,
                path=parsed_url.selector,
                query=parsed_url.search or "",
                itype=parsed_url.gopher_type,
                tls=False,  # Standard Gopher doesn't use TLS
                tls_verify=True,
            )

            # Fetch content in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, request.get)

            # Process based on content type
            if parsed_url.gopher_type == "1":
                # Menu/directory
                return await self._process_menu_response(response, parsed_url)
            elif parsed_url.gopher_type == "0":
                # Text file
                return await self._process_text_response(response)
            elif parsed_url.gopher_type == "7":
                # Search - treat as menu
                return await self._process_menu_response(response, parsed_url)
            elif parsed_url.gopher_type in ["4", "5", "6", "9", "g", "I"]:
                # Binary content
                return await self._process_binary_response(response)
            else:
                # Unknown type - try as text
                return await self._process_text_response(response)

        except Exception as e:
            logger.error("Gopher fetch failed", url=parsed_url, error=str(e))
            raise

    async def _process_menu_response(
        self, response: Any, parsed_url: GopherURL
    ) -> MenuResult:
        """Process a Gopher menu response.

        Args:
            response: Pituophis response object
            parsed_url: Original parsed URL for context

        Returns:
            Parsed menu result

        """
        try:
            # Parse the menu using Pituophis
            menu_items = response.menu()
            items = []

            for item in menu_items:
                # Convert Pituophis Item to our GopherMenuItem
                next_url = f"gopher://{item.host}:{item.port}/{item.itype}{item.path}"
                if item.itype == "7" and parsed_url.search:
                    # Add search for search items
                    next_url += f"?{parsed_url.search}"

                gopher_item = GopherMenuItem(
                    type=item.itype,
                    title=item.text,
                    selector=item.path,
                    host=item.host,
                    port=item.port,
                    nextUrl=next_url,
                )
                items.append(gopher_item)

            return MenuResult(items=items)

        except Exception as e:
            logger.error("Failed to parse menu", error=str(e))
            # Return empty menu on parse error
            return MenuResult(items=[])

    async def _process_text_response(self, response: Any) -> TextResult:
        """Process a Gopher text response.

        Args:
            response: Pituophis response object

        Returns:
            Text result

        """
        try:
            # Get text content from response
            text_content = response.text()

            # Sanitize the text content
            # Remove any control characters except newlines, carriage returns, and tabs
            sanitized_text = "".join(
                char
                for char in text_content
                if char.isprintable() or char in ["\n", "\t", "\r"]
            )

            return TextResult(
                text=sanitized_text,
                bytes=len(response.binary),
                charset="utf-8",
            )

        except Exception as e:
            logger.error("Failed to process text response", error=str(e))
            # Return error message as text
            error_text = f"Error processing text: {str(e)}"
            return TextResult(
                text=error_text,
                bytes=len(error_text.encode("utf-8")),
                charset="utf-8",
            )

    # Note: Search is handled by _process_menu_response since search results are menus

    async def _process_binary_response(self, response: Any) -> BinaryResult:
        """Process a Gopher binary response.

        Args:
            response: Pituophis response object

        Returns:
            Binary result with metadata only (no binary data for LLM)

        """
        try:
            # Get the binary size
            binary_size = len(response.binary)

            # Try to determine MIME type from content
            mime_type = "application/octet-stream"  # Default

            # Simple MIME type detection based on first few bytes
            if binary_size > 0:
                header = response.binary[:16]
                if header.startswith(b"\x89PNG"):
                    mime_type = "image/png"
                elif header.startswith(b"\xff\xd8\xff"):
                    mime_type = "image/jpeg"
                elif header.startswith(b"GIF8"):
                    mime_type = "image/gif"
                elif header.startswith(b"%PDF"):
                    mime_type = "application/pdf"
                elif header.startswith(b"PK"):
                    mime_type = "application/zip"

            return BinaryResult(
                bytes=binary_size,
                mimeType=mime_type,
            )

        except Exception as e:
            logger.error("Failed to process binary response", error=str(e))
            return BinaryResult(
                bytes=0,
                mimeType="application/octet-stream",
            )

    def _get_cached_response(self, url: str) -> Optional[GopherFetchResponse]:
        """Get cached response if available and not expired.

        Args:
            url: Gopher URL

        Returns:
            Cached response or None

        """
        if not self.cache_enabled or url not in self._cache:
            return None

        entry = self._cache[url]
        current_time = time.time()

        if entry.is_expired(current_time):
            del self._cache[url]
            return None

        return entry.value

    def _cache_response(self, url: str, response: GopherFetchResponse) -> None:
        """Cache a response.

        Args:
            url: Gopher URL
            response: Response to cache

        """
        if not self.cache_enabled:
            return

        # Evict oldest entries if cache is full
        if len(self._cache) >= self.max_cache_entries:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]

        entry = CacheEntry(
            key=url,
            value=response,
            timestamp=time.time(),
            ttl=self.cache_ttl_seconds,
        )

        self._cache[url] = entry

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        self._cache.clear()
        logger.info("Gopher client closed")
