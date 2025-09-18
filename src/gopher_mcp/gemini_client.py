"""Gemini protocol client implementation."""

import time
from typing import Dict, List, Optional, Tuple

import structlog

from .gemini_tls import GeminiTLSClient, TLSConfig, TLSConnectionError
from .tofu import TOFUManager, TOFUValidationError
from .client_certs import ClientCertificateManager
from .models import (
    GeminiFetchResponse,
    GeminiURL,
    GeminiErrorResult,
    GeminiCacheEntry,
    TOFUEntry,
    GeminiCertificateInfo,
)
from .utils import (
    parse_gemini_url,
    parse_gemini_response,
    process_gemini_response,
)

logger = structlog.get_logger(__name__)


class GeminiClient:
    """Async Gemini protocol client with TLS, caching and safety features."""

    def __init__(
        self,
        *,
        max_response_size: int = 1024 * 1024,  # 1MB
        timeout_seconds: float = 30.0,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = 300,  # 5 minutes
        max_cache_entries: int = 1000,
        allowed_hosts: Optional[List[str]] = None,
        tls_config: Optional[TLSConfig] = None,
        tofu_enabled: bool = True,
        tofu_storage_path: Optional[str] = None,
        client_certs_enabled: bool = True,
        client_certs_storage_path: Optional[str] = None,
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
            client_certs_enabled: Whether to enable client certificate management
            client_certs_storage_path: Path to client certificate storage directory
        """
        self.max_response_size = max_response_size
        self.timeout_seconds = timeout_seconds
        self.cache_enabled = cache_enabled
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_entries = max_cache_entries
        self.allowed_hosts = set(allowed_hosts) if allowed_hosts else None
        self.tofu_enabled = tofu_enabled
        self.client_certs_enabled = client_certs_enabled

        # Initialize TLS client
        if tls_config is None:
            tls_config = TLSConfig(timeout_seconds=timeout_seconds)
        self.tls_client = GeminiTLSClient(tls_config)

        # Initialize TOFU manager
        self.tofu_manager: Optional[TOFUManager] = None
        if self.tofu_enabled:
            self.tofu_manager = TOFUManager(tofu_storage_path)

        # Initialize client certificate manager
        self.client_cert_manager: Optional[ClientCertificateManager] = None
        if self.client_certs_enabled:
            self.client_cert_manager = ClientCertificateManager(
                client_certs_storage_path
            )

        self._cache: Dict[str, GeminiCacheEntry] = {}

    def _validate_security(self, parsed_url: GeminiURL) -> None:
        """Validate security constraints for a Gemini request.

        Args:
            parsed_url: Parsed Gemini URL

        Raises:
            ValueError: If security constraints are violated
        """
        # Check allowed hosts
        if self.allowed_hosts and parsed_url.host not in self.allowed_hosts:
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
                    logger.info(
                        "Cache hit",
                        url=url,
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

            # Fetch the content
            response = await self._fetch_content(parsed_url)

            # Add request info to response
            if hasattr(response, "request_info"):
                response.request_info.update(request_info)

            # Cache the response
            if self.cache_enabled:
                self._cache_response(url, response)

            logger.info(
                "Gemini fetch successful",
                url=url,
                host=parsed_url.host,
                port=parsed_url.port,
                path=parsed_url.path,
                query=parsed_url.query,
                response_type=getattr(response, "kind", "unknown"),
                response_size=getattr(response, "size", 0),
                cached=False,
            )

            return response

        except Exception as e:
            logger.error(
                "Gemini fetch failed",
                url=url,
                error=str(e),
                error_type=type(e).__name__,
            )
            return GeminiErrorResult(
                error={
                    "code": "FETCH_ERROR",
                    "message": str(e),
                },
                requestInfo={"url": url, "timestamp": time.time()},
            )

    async def _fetch_content(self, parsed_url: GeminiURL) -> GeminiFetchResponse:
        """Fetch content from parsed Gemini URL using TLS.

        Args:
            parsed_url: Parsed Gemini URL

        Returns:
            Appropriate response based on status code

        """
        ssl_sock = None
        try:
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
                    parsed_url.host, parsed_url.port, timeout=self.timeout_seconds
                )
            else:
                # Use default TLS client
                ssl_sock, connection_info = await self.tls_client.connect(
                    parsed_url.host, parsed_url.port, timeout=self.timeout_seconds
                )

            # Validate certificate using TOFU if enabled
            tofu_warning = None
            if self.tofu_manager and connection_info.get("cert_fingerprint"):
                try:
                    is_valid, warning = self.tofu_manager.validate_certificate(
                        parsed_url.host,
                        parsed_url.port,
                        connection_info["cert_fingerprint"],
                        connection_info.get("peer_cert_info"),
                    )
                    if warning:
                        tofu_warning = warning
                        logger.warning(
                            "TOFU validation warning",
                            host=parsed_url.host,
                            port=parsed_url.port,
                            warning=warning,
                        )
                except TOFUValidationError as e:
                    logger.error(
                        "TOFU validation failed",
                        host=parsed_url.host,
                        port=parsed_url.port,
                        error=str(e),
                    )
                    raise ValueError(f"Certificate validation failed: {e}")

            # Format Gemini request: URL + CRLF
            request_url = f"gemini://{parsed_url.host}"
            if parsed_url.port != 1965:
                request_url += f":{parsed_url.port}"
            request_url += parsed_url.path
            if parsed_url.query:
                request_url += f"?{parsed_url.query}"

            request_data = f"{request_url}\r\n".encode("utf-8")

            # Send request
            await self.tls_client.send_data(ssl_sock, request_data)

            # Receive response
            raw_response = await self.tls_client.receive_data(
                ssl_sock, self.max_response_size
            )

            # Parse response
            parsed_response = parse_gemini_response(raw_response)

            # Process response based on status code
            result = process_gemini_response(parsed_response, request_url, time.time())

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

        except TLSConnectionError as e:
            logger.error("TLS connection failed", url=parsed_url, error=str(e))
            raise ValueError(f"TLS connection failed: {e}")
        except Exception as e:
            logger.error("Gemini fetch failed", url=parsed_url, error=str(e))
            raise
        finally:
            # Always close the connection
            if ssl_sock:
                await self.tls_client.close(ssl_sock)

    def _get_cached_response(self, url: str) -> Optional[GeminiFetchResponse]:
        """Get cached response if available and not expired.

        Args:
            url: Gemini URL

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

    def _cache_response(self, url: str, response: GeminiFetchResponse) -> None:
        """Cache a response.

        Args:
            url: Gemini URL
            response: Response to cache

        """
        if not self.cache_enabled:
            return

        # Evict oldest entries if cache is full
        if len(self._cache) >= self.max_cache_entries:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]

        entry = GeminiCacheEntry(
            key=url,
            value=response,
            timestamp=time.time(),
            ttl=self.cache_ttl_seconds,
        )

        self._cache[url] = entry

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

    def list_tofu_certificates(self) -> List[TOFUEntry]:
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
        common_name: Optional[str] = None,
        validity_days: int = 365,
    ) -> Tuple[str, str]:
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
    ) -> Optional[Tuple[str, str]]:
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

    def list_client_certificates(self) -> List[GeminiCertificateInfo]:
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
