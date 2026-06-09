"""TLS client implementation for Gemini protocol with SNI support.

Uses native asyncio TLS (``asyncio.open_connection(ssl=...)``) so connect,
handshake and every read are genuinely cancellable: a per-request
``asyncio.wait_for`` deadline actually unblocks a stalled/slow-loris peer
instead of leaving a thread parked on a blocking ``recv`` (the previous
``run_in_executor`` design could not be cancelled and shared a thread pool with
DNS resolution). No worker threads are held, so one slow Gemini server can no
longer degrade unrelated requests.
"""

import asyncio
import contextlib
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

READ_CHUNK = 65536
# Short probe deadline used once the size cap is reached: a server that sent
# exactly ``max_size`` bytes and then holds the connection open (delayed/absent
# close_notify) would otherwise block until the request deadline. A probe
# timeout means "no more data is forthcoming", so treat the response as complete.
PROBE_TIMEOUT_SECONDS = 1.0


@dataclass
class TLSConfig:
    """Configuration for TLS connections."""

    min_version: str = "TLSv1.2"
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE
    client_cert_path: str | None = None
    client_key_path: str | None = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.min_version not in ["TLSv1.2", "TLSv1.3"]:
            raise ValueError(f"Unsupported TLS version: {self.min_version}")

        if self.timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")

        # If client cert is provided, key must also be provided
        if self.client_cert_path and not self.client_key_path:
            raise ValueError("Client key path required when client cert is provided")
        if self.client_key_path and not self.client_cert_path:
            raise ValueError("Client cert path required when client key is provided")


class TLSConnectionError(Exception):
    """Exception raised for TLS connection errors."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


@dataclass
class TLSConnection:
    """An established Gemini TLS connection (native asyncio streams)."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


class GeminiTLSClient:
    """Async TLS client for Gemini protocol with mandatory SNI support."""

    def __init__(self, config: TLSConfig | None = None):
        """Initialize TLS client with configuration.

        Args:
            config: TLS configuration (uses defaults if None)
        """
        self.config = config or TLSConfig()
        self._ssl_context: ssl.SSLContext | None = None

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context with secure defaults.

        Returns:
            Configured SSL context

        Raises:
            TLSConnectionError: If SSL context creation fails
        """
        try:
            context = self._create_base_ssl_context()

            # Load client certificate if provided
            if self.config.client_cert_path and self.config.client_key_path:
                context.load_cert_chain(
                    self.config.client_cert_path, self.config.client_key_path
                )
                logger.info(
                    "Client certificate loaded", cert_path=self.config.client_cert_path
                )

            return context

        except Exception as e:
            raise TLSConnectionError(f"Failed to create SSL context: {e}", e) from e

    def _create_base_ssl_context(self) -> ssl.SSLContext:
        """Create the SSL context used for Gemini (TOFU, not CA validation)."""
        # Create default context with secure settings
        context = ssl.create_default_context()

        # Set minimum TLS version
        if self.config.min_version == "TLSv1.3":
            context.minimum_version = ssl.TLSVersion.TLSv1_3
        else:
            context.minimum_version = ssl.TLSVersion.TLSv1_2

        # Configure certificate verification
        # For Gemini, we typically use TOFU instead of CA validation
        context.check_hostname = False
        context.verify_mode = self.config.verify_mode

        # Keep Python's secure default cipher suites. We deliberately do NOT
        # narrow them: peer authentication is via TOFU fingerprint pinning (not
        # the negotiated cipher), so restricting to a handful of AEAD-only ECDHE
        # suites buys no security but drops ECDHE-CBC and DHE suites that some
        # conforming Gemini servers only offer, causing spurious 1.2 handshake
        # failures. create_default_context() already excludes weak ciphers.

        return context

    @property
    def ssl_context(self) -> ssl.SSLContext:
        """Get SSL context, creating it if necessary."""
        if self._ssl_context is None:
            self._ssl_context = self._create_ssl_context()
        return self._ssl_context

    async def connect(
        self,
        host: str,
        port: int = 1965,
        timeout: float | None = None,
        *,
        connect_ip: str | None = None,
    ) -> tuple[TLSConnection, dict[str, Any]]:
        """Establish a TLS connection with SNI support.

        Args:
            host: Hostname (used for SNI and TOFU; never re-resolved here).
            port: Port number (default: 1965)
            timeout: Overall deadline for connect + TLS handshake (uses config
                default if None). Native asyncio makes this genuinely
                cancellable.
            connect_ip: Pre-validated IP to connect to. When given, the socket
                targets this IP literal (which ``getaddrinfo`` returns verbatim,
                so there is no DNS re-resolution) instead of ``host`` -- this
                pins the connection to the address the SSRF guard vetted, closing
                the DNS-rebinding window, while ``host`` is still sent as SNI so
                virtual hosting/TOFU work.

        Returns:
            Tuple of (TLSConnection, connection info)

        Raises:
            TLSConnectionError: If connection fails
        """
        # Host-level SSRF/allowlist validation is performed by the caller
        # (GeminiClient) before reaching the transport.
        timeout = timeout or self.config.timeout_seconds
        target = connect_ip or host

        logger.info(
            "Establishing TLS connection",
            host=host,
            port=port,
            timeout=timeout,
            tls_version=self.config.min_version,
        )

        start_time = time.time()
        try:
            # ssl + server_hostname runs the TLS handshake during connection
            # setup and sends SNI. wait_for bounds connect AND handshake under a
            # single cancellable deadline.
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host=target,
                    port=port,
                    ssl=self.ssl_context,
                    server_hostname=host,
                ),
                timeout=timeout,
            )
        except TimeoutError as e:
            raise TLSConnectionError(
                f"Connection timeout after {timeout} seconds"
            ) from e
        except socket.gaierror as e:
            raise TLSConnectionError(f"DNS resolution failed for {host}: {e}", e) from e
        except ConnectionRefusedError as e:
            raise TLSConnectionError(f"Connection refused by {host}:{port}") from e
        except ssl.SSLError as e:
            raise TLSConnectionError(f"TLS handshake failed: {e}", e) from e
        except OSError as e:
            raise TLSConnectionError(f"Connection failed: {e}", e) from e

        ssl_object = writer.get_extra_info("ssl_object")
        connection_info = self._get_connection_info(
            ssl_object, time.time() - start_time
        )

        logger.info(
            "TLS connection established",
            host=host,
            port=port,
            connection_time=connection_info.get("connection_time"),
            tls_version=connection_info.get("tls_version"),
            cipher=connection_info.get("cipher"),
        )

        return TLSConnection(reader=reader, writer=writer), connection_info

    def _get_connection_info(
        self, ssl_object: ssl.SSLObject | None, connection_time: float
    ) -> dict[str, Any]:
        """Extract connection information from the TLS object.

        Args:
            ssl_object: The negotiated ``ssl.SSLObject`` (from the asyncio
                transport's ``ssl_object`` extra info), or None if unavailable.
            connection_time: Time taken to establish the connection.

        Returns:
            Dictionary with connection information
        """
        if ssl_object is None:  # pragma: no cover - defensive
            return {"connection_time": connection_time, "error": "no ssl object"}
        try:
            peer_cert = ssl_object.getpeercert(binary_form=True)
            # Under CERT_NONE getpeercert() (dict form) is empty, so derive cert
            # details from the DER instead (this is where the expiry lives).
            peer_cert_info = self._parse_peer_cert(peer_cert)
            cipher = ssl_object.cipher()

            info: dict[str, Any] = {
                "connection_time": connection_time,
                "tls_version": ssl_object.version(),
                "cipher": cipher[0] if cipher else None,
                "cipher_strength": cipher[2] if cipher else None,
                "peer_cert_der": peer_cert,
                "peer_cert_info": peer_cert_info,
                "sni_hostname": ssl_object.server_hostname,
            }

            # Add certificate fingerprint if available
            if peer_cert:
                import hashlib

                fingerprint = hashlib.sha256(peer_cert).hexdigest()
                info["cert_fingerprint"] = f"sha256:{fingerprint}"

            return info

        except Exception as e:
            logger.warning("Failed to extract connection info", error=str(e))
            return {"connection_time": connection_time, "error": str(e)}

    @staticmethod
    def _parse_peer_cert(peer_cert_der: bytes | None) -> dict[str, Any]:
        """Extract certificate details from DER bytes.

        Works under CERT_NONE (where ssl.getpeercert() returns an empty dict),
        so the certificate's validity window is actually available to TOFU.
        """
        if not peer_cert_der:
            return {}
        try:
            from cryptography import x509

            cert = x509.load_der_x509_certificate(peer_cert_der)
            return {
                "subject": cert.subject.rfc4514_string(),
                "issuer": cert.issuer.rfc4514_string(),
                "not_before_timestamp": cert.not_valid_before_utc.timestamp(),
                "not_after_timestamp": cert.not_valid_after_utc.timestamp(),
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Failed to parse peer certificate", error=str(e))
            return {}

    async def close(self, conn: TLSConnection) -> None:
        """Close a TLS connection gracefully.

        Args:
            conn: The connection to close
        """
        conn.writer.close()
        # Best-effort: ignore errors (incl. SSL close_notify hiccups) so they
        # don't mask the result the caller already obtained.
        with contextlib.suppress(Exception):
            await conn.writer.wait_closed()

    async def send_data(self, conn: TLSConnection, data: bytes) -> None:
        """Send data over the TLS connection.

        Args:
            conn: Connected TLS connection
            data: Data to send

        Raises:
            TLSConnectionError: If send fails
        """
        try:
            conn.writer.write(data)
            await conn.writer.drain()
        except Exception as e:
            raise TLSConnectionError(f"Failed to send data: {e}", e) from e

    async def receive_data(
        self,
        conn: TLSConnection,
        max_size: int = 1024 * 1024,  # 1MB default
    ) -> bytes:
        """Receive data from the TLS connection, bounded by ``max_size``.

        Args:
            conn: Connected TLS connection
            max_size: Maximum data size to receive

        Returns:
            Received data

        Raises:
            TLSConnectionError: If receive fails or the response exceeds max_size.
        """
        reader = conn.reader
        try:
            chunks: list[bytes] = []
            total = 0
            while total < max_size:
                chunk = await reader.read(min(READ_CHUNK, max_size - total))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)

            # Hit the cap without EOF: probe one more byte so an over-limit
            # response is REJECTED rather than silently truncated. Use a short
            # probe deadline so a complete, exactly-max_size response whose
            # server holds the connection open is still treated as complete.
            try:
                extra = await asyncio.wait_for(
                    reader.read(1), timeout=PROBE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                extra = b""
            if extra:
                raise TLSConnectionError(
                    f"Response exceeds maximum size of {max_size} bytes"
                )
            return b"".join(chunks)

        except TLSConnectionError:
            raise
        except Exception as e:
            raise TLSConnectionError(f"Failed to receive data: {e}", e) from e
