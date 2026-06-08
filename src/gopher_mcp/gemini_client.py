"""Gemini protocol client implementation."""

import asyncio
import time
from collections import OrderedDict

import structlog

from .cache import TTLCacheMixin
from .client_certs import ClientCertificateManager
from .gemini_tls import GeminiTLSClient, TLSConfig, TLSConnectionError
from .models import (
    GeminiCacheEntry,
    GeminiCertificateInfo,
    GeminiErrorResult,
    GeminiFetchResponse,
    GeminiURL,
    TOFUEntry,
)
from .ratelimit import RateLimiter
from .ssrf import SSRFError, normalize_host, validate_target
from .tofu import (
    TOFUExpiredError,
    TOFUManager,
    TOFUUnavailableError,
    TOFUValidationError,
)
from .utils import (
    parse_gemini_response,
    parse_gemini_url,
    process_gemini_response,
)

logger = structlog.get_logger(__name__)

# Default configuration constants
DEFAULT_MAX_RESPONSE_SIZE = 1024 * 1024  # 1MB
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_CACHE_ENTRIES = 1000
DEFAULT_MAX_RENDERED_CHARS = 50000  # LLM-facing text cap; 0 = unlimited


class GeminiClient(TTLCacheMixin[GeminiFetchResponse]):
    """Async Gemini protocol client with TLS, caching and safety features."""

    def __init__(
        self,
        *,
        max_response_size: int = DEFAULT_MAX_RESPONSE_SIZE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_cache_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        allowed_hosts: list[str] | None = None,
        allow_local_hosts: bool = False,
        tls_config: TLSConfig | None = None,
        tofu_enabled: bool = True,
        tofu_storage_path: str | None = None,
        tofu_reject_expired: bool = False,
        client_certs_enabled: bool = True,
        client_certs_storage_path: str | None = None,
        max_rendered_chars: int = DEFAULT_MAX_RENDERED_CHARS,
        requests_per_minute: float = 0.0,
        max_concurrent_requests: int = 0,
        denied_mime_types: list[str] | None = None,
    ) -> None:
        """Initialize the Gemini client.

        Args:
            max_response_size: Maximum response size in bytes
            timeout_seconds: Request timeout in seconds
            cache_enabled: Whether to enable response caching
            cache_ttl_seconds: Cache TTL in seconds
            max_cache_entries: Maximum number of cache entries
            allowed_hosts: List of allowed hostnames (None = allow all)
            tls_config: TLS configuration (uses defaults if None)
            tofu_enabled: Whether to enable TOFU certificate validation
            tofu_storage_path: Path to TOFU storage file
            tofu_reject_expired: Fail closed on a certificate outside its
                validity window instead of accepting it with a warning
            client_certs_enabled: Whether to enable client certificate management
            client_certs_storage_path: Path to client certificate storage directory
        """
        self.max_response_size = max_response_size
        self.timeout_seconds = timeout_seconds
        self.cache_enabled = cache_enabled
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_entries = max_cache_entries
        self.max_rendered_chars = max_rendered_chars
        self._rate_limiter = RateLimiter(requests_per_minute)
        self.max_concurrent_requests = max_concurrent_requests
        # Opt-in coarse cap on simultaneous fetches (None = unlimited).
        self._fetch_semaphore = (
            asyncio.Semaphore(max_concurrent_requests)
            if max_concurrent_requests > 0
            else None
        )
        self.denied_mime_types = frozenset(denied_mime_types or ())
        self.allowed_hosts = set(allowed_hosts) if allowed_hosts else None
        self.allow_local_hosts = allow_local_hosts
        self.tofu_enabled = tofu_enabled
        self.client_certs_enabled = client_certs_enabled

        # Initialize TLS client
        if tls_config is None:
            tls_config = TLSConfig(timeout_seconds=timeout_seconds)
        self.tls_client = GeminiTLSClient(tls_config)

        # Initialize TOFU manager
        self.tofu_manager: TOFUManager | None = None
        if self.tofu_enabled:
            self.tofu_manager = TOFUManager(
                tofu_storage_path, reject_expired=tofu_reject_expired
            )
        else:
            # Gemini TLS runs with CERT_NONE, so TOFU is the ONLY peer
            # authentication. Disabling it leaves every connection unauthenticated
            # and trivially MITM-able -- make that loud rather than a silent toggle.
            logger.warning(
                "TOFU is DISABLED: Gemini connections are unauthenticated "
                "(CERT_NONE TLS with no certificate pinning) and vulnerable to "
                "active MITM. Re-enable TOFU unless you fully trust the network."
            )

        # Initialize client certificate manager
        self.client_cert_manager: ClientCertificateManager | None = None
        if self.client_certs_enabled:
            self.client_cert_manager = ClientCertificateManager(
                client_certs_storage_path
            )

        # LRU cache (get/put behaviour lives in TTLCacheMixin). The element type
        # is inherited from the mixin annotation; only the entry class differs.
        self._cache = OrderedDict()
        self._cache_entry_cls = GeminiCacheEntry

    def _validate_security(self, parsed_url: GeminiURL) -> None:
        """Validate security constraints for a Gemini request.

        Args:
            parsed_url: Parsed Gemini URL

        Raises:
            ValueError: If security constraints are violated
        """
        # Check allowed hosts (normalized to close trailing-dot/case bypasses)
        if self.allowed_hosts:
            allowed = {normalize_host(h) for h in self.allowed_hosts}
            if normalize_host(parsed_url.host) not in allowed:
                raise ValueError(f"Host not allowed: {parsed_url.host}")

        # Validate port range
        if not 1 <= parsed_url.port <= 65535:
            raise ValueError(f"Invalid port number: {parsed_url.port}")

    async def fetch(self, url: str) -> GeminiFetchResponse:
        """Fetch content from a Gemini URL.

        Args:
            url: Gemini URL to fetch

        Returns:
            Structured response based on status code

        """
        try:
            # Parse the URL
            parsed_url = parse_gemini_url(url)

            # Validate security constraints
            self._validate_security(parsed_url)

            # Check cache first
            if self.cache_enabled:
                cached_response = self._get_cached_response(url)
                if cached_response:
                    # Log without the query string: a status-10/11 answer (which
                    # the caller percent-encodes into the query) may be a secret.
                    logger.debug(
                        "Cache hit",
                        url=f"gemini://{parsed_url.host}:{parsed_url.port}{parsed_url.path}",
                        cached=True,
                        response_type=getattr(cached_response, "kind", "unknown"),
                        response_size=getattr(cached_response, "size", 0),
                    )
                    return cached_response

            # Create request info for provenance
            request_info = {
                "url": url,
                "host": parsed_url.host,
                "port": parsed_url.port,
                "path": parsed_url.path,
                "query": parsed_url.query,
                "timestamp": time.time(),
            }

            # Fetch the content (optionally bounded by the concurrency cap)
            response = await self._bounded_fetch(parsed_url)

            # Honour a server SLOW_DOWN (status 44): back off this host for the
            # advertised number of seconds (meta) regardless of the configured
            # rate limit, so we don't keep hammering a server asking us to wait.
            self._maybe_honor_slow_down(parsed_url.host, response)

            # Add request info to response
            if hasattr(response, "request_info"):
                response.request_info.update(request_info)

            # Cache the response. Skip transient/non-content results: error
            # and redirect targets can change moment to moment, and
            # input/certificate prompts are per-interaction, so caching them
            # would serve a stale failure or redirect for the full TTL.
            if self.cache_enabled and getattr(response, "kind", None) not in (
                "error",
                "redirect",
                "input",
                "certificate",
            ):
                self._cache_response(url, response)

            # Host/port/path are request metadata; keep them at DEBUG so default
            # INFO logs don't record every browsed resource. The query is NOT
            # logged: a status-10/11 input answer is carried there and may be a
            # secret (status 11). Record only whether a query was present.
            logger.debug(
                "Gemini fetch successful",
                host=parsed_url.host,
                port=parsed_url.port,
                path=parsed_url.path,
                has_query=bool(parsed_url.query),
                response_type=getattr(response, "kind", "unknown"),
                response_size=getattr(response, "size", 0),
                cached=False,
            )

            return response

        except SSRFError as e:
            # Policy messages name a host/category only (no internal detail).
            return self._error_result(url, "BLOCKED", str(e), e)
        except TOFUExpiredError as e:
            # Distinct from a fingerprint change: the cert MATCHES the pin but is
            # outside its validity window. Report it accurately (must precede the
            # TOFUValidationError handler since it is a subclass). The message
            # names host:port and a category only -- safe to surface.
            return self._error_result(url, "CERTIFICATE_EXPIRED", str(e), e)
        except TOFUUnavailableError as e:
            # No certificate to compare against (not a mismatch). Also a subclass,
            # so it must precede the TOFUValidationError handler.
            return self._error_result(url, "CERTIFICATE_UNVERIFIED", str(e), e)
        except TOFUValidationError as e:
            return self._error_result(
                url,
                "CERTIFICATE_CHANGED",
                "Server certificate failed TOFU verification (it does not match "
                "the previously trusted certificate)",
                e,
            )
        except TLSConnectionError as e:
            return self._error_result(url, "TLS_ERROR", "TLS connection failed", e)
        except TimeoutError as e:
            # DNS resolution, connect, or read exceeded the request deadline.
            return self._error_result(url, "FETCH_ERROR", "The request timed out", e)
        except ValueError as e:
            # URL/host validation errors are safe to surface verbatim.
            return self._error_result(url, "INVALID_REQUEST", str(e), e)
        except Exception as e:
            return self._error_result(
                url, "FETCH_ERROR", "Failed to fetch the requested resource", e
            )

    def _error_result(
        self, url: str, code: str, message: str, exc: Exception
    ) -> GeminiErrorResult:
        """Build a sanitized error result, logging full detail server-side."""
        logger.error(
            "Gemini fetch failed",
            url=url,
            code=code,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return GeminiErrorResult(
            error={"code": code, "message": message},
            requestInfo={"url": url, "timestamp": time.time()},
        )

    def _maybe_honor_slow_down(self, host: str, response: GeminiFetchResponse) -> None:
        """If ``response`` is a status-44 SLOW_DOWN, back off this host.

        The Gemini spec says the meta of a 44 is the number of seconds to wait;
        fall back to a conservative default if it isn't a plain number.
        """
        if not isinstance(response, GeminiErrorResult):
            return
        if response.error.get("status") != 44:
            return
        message = response.error.get("message", "")
        try:
            seconds = float(str(message).strip())
        except (TypeError, ValueError):
            seconds = 60.0
        self._rate_limiter.penalize(host, seconds)

    async def _bounded_fetch(self, parsed_url: GeminiURL) -> GeminiFetchResponse:
        """Run :meth:`_fetch_content`, bounded by the concurrency cap if set."""
        if self._fetch_semaphore is None:
            return await self._fetch_content(parsed_url)
        async with self._fetch_semaphore:
            return await self._fetch_content(parsed_url)

    async def _fetch_content(self, parsed_url: GeminiURL) -> GeminiFetchResponse:
        """Fetch content from parsed Gemini URL using TLS.

        Args:
            parsed_url: Parsed Gemini URL

        Returns:
            Appropriate response based on status code

        """
        ssl_sock = None
        try:
            # SSRF guard: reject internal/loopback/link-local targets before
            # opening the TLS connection, and pin the connection to a validated
            # IP so the TLS layer can't re-resolve to a rebinding answer.
            #
            # Bound DNS resolution by the request deadline: getaddrinfo is
            # otherwise unbounded (a tarpit nameserver could stall a worker -- and
            # tie up an event-loop executor thread -- far past timeout_seconds).
            connect_addresses = await asyncio.wait_for(
                validate_target(
                    parsed_url.host,
                    parsed_url.port,
                    allow_local=self.allow_local_hosts,
                ),
                timeout=self.timeout_seconds,
            )
            # Prefer an IPv4 address (the historical behavior was AF_INET-only),
            # but fall back to the first address so IPv6-only hosts still work.
            connect_ip = next(
                (a for a in connect_addresses if ":" not in a), connect_addresses[0]
            )

            # Politeness: space out requests to the same host (and honour any
            # outstanding status-44 backoff for it).
            await self._rate_limiter.acquire(parsed_url.host)

            # Check for client certificate
            client_cert_path = None
            client_key_path = None
            if self.client_cert_manager:
                cert_paths = self.client_cert_manager.get_certificate_for_scope(
                    parsed_url.host, parsed_url.port, parsed_url.path
                )
                if cert_paths:
                    client_cert_path, client_key_path = cert_paths
                    logger.debug(
                        "Using client certificate",
                        host=parsed_url.host,
                        port=parsed_url.port,
                        path=parsed_url.path,
                        cert_path=client_cert_path,
                    )

            # Update TLS config with client certificate if available
            tls_config = self.tls_client.config
            if client_cert_path and client_key_path:
                # Create a new TLS config with client certificate
                from .gemini_tls import TLSConfig

                tls_config = TLSConfig(
                    min_version=tls_config.min_version,
                    verify_mode=tls_config.verify_mode,
                    client_cert_path=client_cert_path,
                    client_key_path=client_key_path,
                    timeout_seconds=tls_config.timeout_seconds,
                )
                # Create temporary TLS client with client certificate
                temp_tls_client = GeminiTLSClient(tls_config)
                ssl_sock, connection_info = await temp_tls_client.connect(
                    parsed_url.host,
                    parsed_url.port,
                    timeout=self.timeout_seconds,
                    connect_ip=connect_ip,
                )
            else:
                # Use default TLS client
                ssl_sock, connection_info = await self.tls_client.connect(
                    parsed_url.host,
                    parsed_url.port,
                    timeout=self.timeout_seconds,
                    connect_ip=connect_ip,
                )

            # Validate certificate using TOFU if enabled (fail CLOSED).
            tofu_warning = None
            if self.tofu_manager:
                cert_fingerprint = connection_info.get("cert_fingerprint")
                if not cert_fingerprint:
                    # The TLS layer runs with CERT_NONE, so TOFU is the only
                    # thing authenticating the peer. Without a fingerprint we
                    # cannot apply the pin -- refuse rather than send the
                    # request to an unverified server. This is a distinct failure
                    # from a fingerprint mismatch (there is nothing to compare).
                    raise TOFUUnavailableError(
                        "No certificate fingerprint available; cannot verify "
                        "the server identity via TOFU"
                    )
                # A fingerprint mismatch raises TOFUValidationError, which
                # propagates to fetch() and becomes a CERTIFICATE_CHANGED error.
                is_valid, warning = self.tofu_manager.validate_certificate(
                    parsed_url.host,
                    parsed_url.port,
                    cert_fingerprint,
                    connection_info.get("peer_cert_info"),
                )
                if not is_valid:
                    # Defense-in-depth: a non-raising False result must still
                    # reject (fail CLOSED), not merely warn -- so this gate is
                    # robust regardless of how the validator signals failure.
                    raise TOFUValidationError(
                        warning
                        or f"TOFU validation failed for "
                        f"{parsed_url.host}:{parsed_url.port}"
                    )
                if warning:
                    tofu_warning = warning
                    logger.warning(
                        "TOFU validation warning",
                        host=parsed_url.host,
                        port=parsed_url.port,
                        warning=warning,
                    )

            # Format Gemini request: URL + CRLF
            request_url = f"gemini://{parsed_url.host}"
            if parsed_url.port != 1965:
                request_url += f":{parsed_url.port}"
            request_url += parsed_url.path
            if parsed_url.query:
                request_url += f"?{parsed_url.query}"

            request_data = f"{request_url}\r\n".encode()

            # Send request
            await self.tls_client.send_data(ssl_sock, request_data)

            # Receive response under an overall deadline. The per-recv socket
            # timeout alone gives no total bound, so a server dripping one byte
            # at a time could hold the connection open indefinitely (slow loris).
            raw_response = await asyncio.wait_for(
                self.tls_client.receive_data(ssl_sock, self.max_response_size),
                timeout=self.timeout_seconds,
            )

            # Parse response
            parsed_response = parse_gemini_response(raw_response)

            # Process response based on status code
            result = process_gemini_response(
                parsed_response,
                request_url,
                time.time(),
                max_rendered_chars=self.max_rendered_chars,
                denied_mime_types=self.denied_mime_types,
            )

            # Add connection info to request info
            if hasattr(result, "request_info"):
                result.request_info.update(
                    {
                        "tls_version": connection_info.get("tls_version"),
                        "cipher": connection_info.get("cipher"),
                        "cert_fingerprint": connection_info.get("cert_fingerprint"),
                        "tofu_warning": tofu_warning,
                    }
                )

            return result

        except Exception as e:
            # Preserve the exception type (TLSConnectionError, TOFUValidationError,
            # SSRFError, ...) so fetch() can map it to a distinct error code.
            logger.error("Gemini fetch failed", url=str(parsed_url), error=str(e))
            raise
        finally:
            # Always close the connection
            if ssl_sock:
                await self.tls_client.close(ssl_sock)

    # _get_cached_response / _cache_response are provided by TTLCacheMixin.

    def update_tofu_certificate(
        self, host: str, port: int, cert_fingerprint: str, force: bool = False
    ) -> None:
        """Update TOFU certificate for a host.

        Args:
            host: Hostname
            port: Port number
            cert_fingerprint: Certificate fingerprint
            force: Force update even if certificate exists

        Raises:
            ValueError: If TOFU is not enabled
        """
        if not self.tofu_manager:
            raise ValueError("TOFU is not enabled")

        self.tofu_manager.update_certificate(host, port, cert_fingerprint, force=force)

    def remove_tofu_certificate(self, host: str, port: int) -> bool:
        """Remove TOFU certificate for a host.

        Args:
            host: Hostname
            port: Port number

        Returns:
            True if certificate was removed, False if not found

        Raises:
            ValueError: If TOFU is not enabled
        """
        if not self.tofu_manager:
            raise ValueError("TOFU is not enabled")

        return self.tofu_manager.remove_certificate(host, port)

    def list_tofu_certificates(self) -> list[TOFUEntry]:
        """List all TOFU certificates.

        Returns:
            List of TOFU entries

        Raises:
            ValueError: If TOFU is not enabled
        """
        if not self.tofu_manager:
            raise ValueError("TOFU is not enabled")

        return self.tofu_manager.list_certificates()

    def generate_client_certificate(
        self,
        host: str,
        port: int = 1965,
        path: str = "/",
        common_name: str | None = None,
        validity_days: int = 365,
    ) -> tuple[str, str]:
        """Generate a new client certificate for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope
            common_name: Certificate common name
            validity_days: Certificate validity in days

        Returns:
            Tuple of (cert_path, key_path)

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.generate_certificate(
            host, port, path, common_name, validity_days
        )

    def get_client_certificate_for_scope(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> tuple[str, str] | None:
        """Get client certificate paths for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            Tuple of (cert_path, key_path) or None if not found

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.get_certificate_for_scope(host, port, path)

    def list_client_certificates(self) -> list[GeminiCertificateInfo]:
        """List all client certificates.

        Returns:
            List of client certificate information

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.list_certificates()

    def remove_client_certificate(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> bool:
        """Remove client certificate for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            True if certificate was removed, False if not found

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.remove_certificate(host, port, path)

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        self._cache.clear()
        logger.info("Gemini client closed")
