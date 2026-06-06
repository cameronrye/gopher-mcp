"""Gopher protocol client implementation."""

import re
import time
from collections import OrderedDict
from typing import List, Optional, Set

import structlog

from .gopher_transport import GopherProtocolError, decode_gopher_text, fetch_gopher
from .ssrf import SSRFError, normalize_host, validate_target
from .models import (
    BinaryResult,
    CacheEntry,
    ErrorResult,
    GopherFetchResponse,
    GopherURL,
    MenuResult,
    TextResult,
)
from .utils import detect_binary_mime_type, parse_gopher_menu, parse_gopher_url

logger = structlog.get_logger(__name__)

# Default configuration constants
DEFAULT_MAX_RESPONSE_SIZE = 1024 * 1024  # 1MB
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_CACHE_ENTRIES = 1000
DEFAULT_MAX_SELECTOR_LENGTH = 1024
DEFAULT_MAX_SEARCH_LENGTH = 256


class GopherClient:
    """Async Gopher protocol client with caching and safety features."""

    def __init__(
        self,
        *,
        max_response_size: int = DEFAULT_MAX_RESPONSE_SIZE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_cache_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        allowed_hosts: Optional[List[str]] = None,
        allow_local_hosts: bool = False,
        max_selector_length: int = DEFAULT_MAX_SELECTOR_LENGTH,
        max_search_length: int = DEFAULT_MAX_SEARCH_LENGTH,
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

        self.allow_local_hosts = allow_local_hosts

        # Convert allowed hosts to a set for faster lookup
        self.allowed_hosts: Optional[Set[str]] = (
            set(allowed_hosts) if allowed_hosts else None
        )

        # Use OrderedDict for LRU cache implementation
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()

    def _validate_security(self, parsed_url: GopherURL) -> None:
        """Validate security constraints for a Gopher request.

        Args:
            parsed_url: Parsed Gopher URL

        Raises:
            ValueError: If security validation fails

        """
        # Check allowed hosts (normalized to close trailing-dot/case bypasses)
        if self.allowed_hosts:
            allowed = {normalize_host(h) for h in self.allowed_hosts}
            if normalize_host(parsed_url.host) not in allowed:
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

        except SSRFError as e:
            return self._error_result(url, "BLOCKED", str(e), e)
        except GopherProtocolError as e:
            # Network-level failure (timeout / connection / oversize). The
            # transport keeps these messages free of internal detail.
            return self._error_result(url, "FETCH_ERROR", str(e), e)
        except ValueError as e:
            # Validation errors (allowlist, selector, port) are safe to surface.
            return self._error_result(url, "INVALID_REQUEST", str(e), e)
        except Exception as e:
            return self._error_result(
                url, "FETCH_ERROR", "Failed to fetch the requested resource", e
            )

    def _error_result(
        self, url: str, code: str, message: str, exc: Exception
    ) -> ErrorResult:
        """Build a sanitized error result, logging full detail server-side."""
        logger.error(
            "Gopher fetch failed",
            url=url,
            code=code,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return ErrorResult(
            error={"code": code, "message": message},
            requestInfo={"url": url, "timestamp": time.time()},
        )

    async def _fetch_content(self, parsed_url: GopherURL) -> GopherFetchResponse:
        """Fetch content from a parsed Gopher URL over the native transport.

        The configured ``max_response_size`` and ``timeout_seconds`` are
        enforced by :func:`fetch_gopher` (bounded read + overall deadline),
        unlike the previous pituophis path which ignored both.

        Args:
            parsed_url: Parsed Gopher URL

        Returns:
            Appropriate response based on content type
        """
        # SSRF guard: reject internal/loopback/link-local targets before connecting.
        await validate_target(
            parsed_url.host,
            parsed_url.port,
            allow_local=self.allow_local_hosts,
        )

        raw = await fetch_gopher(
            parsed_url.host,
            parsed_url.port,
            parsed_url.selector,
            parsed_url.search,
            max_bytes=self.max_response_size,
            timeout=self.timeout_seconds,
        )

        gopher_type = parsed_url.gopher_type
        if gopher_type in ("1", "7"):
            # Menu/directory or search results (which are menus)
            return self._process_menu_response(raw)
        elif gopher_type in ("4", "5", "6", "9", "g", "I"):
            # Binary content - return metadata only
            return self._process_binary_response(raw)
        else:
            # Text (type 0) and unknown types - try as text
            return self._process_text_response(raw)

    def _process_menu_response(self, raw: bytes) -> MenuResult:
        """Parse a Gopher menu (RFC 1436) into a structured result.

        Uses the project's own ``parse_gopher_menu``, which honours the
        ``.`` terminator and skips malformed lines. An empty result means
        an empty directory, not a swallowed parse failure (unexpected
        errors propagate to the caller and surface as an ErrorResult).

        Args:
            raw: Raw response bytes from the server

        Returns:
            Parsed menu result
        """
        content, _ = decode_gopher_text(raw)
        items = parse_gopher_menu(content)
        return MenuResult(items=items)

    def _process_text_response(self, raw: bytes) -> TextResult:
        """Process a Gopher text response.

        Args:
            raw: Raw response bytes from the server

        Returns:
            Text result
        """
        text_content, charset = decode_gopher_text(raw)

        # Strip control characters except newlines, carriage returns and tabs.
        sanitized_text = "".join(
            char
            for char in text_content
            if char.isprintable() or char in ("\n", "\t", "\r")
        )

        return TextResult(
            text=sanitized_text,
            bytes=len(raw),
            charset=charset,
        )

    # Note: Search is handled by _process_menu_response since search results are menus

    def _process_binary_response(self, raw: bytes) -> BinaryResult:
        """Process a Gopher binary response (metadata only; no bytes to the LLM).

        Args:
            raw: Raw response bytes from the server

        Returns:
            Binary result with size and sniffed MIME type
        """
        return BinaryResult(
            bytes=len(raw),
            mimeType=detect_binary_mime_type(raw),
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

        # Move to end to mark as recently used (LRU)
        self._cache.move_to_end(url)
        return entry.value

    def _cache_response(self, url: str, response: GopherFetchResponse) -> None:
        """Cache a response using LRU eviction strategy.

        Args:
            url: Gopher URL
            response: Response to cache

        """
        if not self.cache_enabled:
            return

        # Evict least recently used entry if cache is full
        if (
            self._cache
            and len(self._cache) >= self.max_cache_entries
            and url not in self._cache
        ):
            # Remove first item (least recently used)
            self._cache.popitem(last=False)

        entry = CacheEntry(
            key=url,
            value=response,
            timestamp=time.time(),
            ttl=self.cache_ttl_seconds,
        )

        # Add or update entry and move to end (most recently used)
        self._cache[url] = entry
        self._cache.move_to_end(url)

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        self._cache.clear()
        logger.info("Gopher client closed")
