"""TLS client implementation for Gemini protocol with SNI support."""

import asyncio
import socket
import ssl
import time
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TLSConfig:
    """Configuration for TLS connections."""

    min_version: str = "TLSv1.2"
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
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

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


class GeminiTLSClient:
    """Async TLS client for Gemini protocol with mandatory SNI support."""

    def __init__(self, config: Optional[TLSConfig] = None):
        """Initialize TLS client with configuration.

        Args:
            config: TLS configuration (uses defaults if None)
        """
        self.config = config or TLSConfig()
        self._ssl_context: Optional[ssl.SSLContext] = None

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
            raise TLSConnectionError(f"Failed to create SSL context: {e}", e)

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

        # Set preferred cipher suites for security
        # TLS 1.3 ciphers are handled automatically
        if hasattr(context, "set_ciphers"):
            # Prefer ECDHE for forward secrecy, AES-GCM for AEAD
            preferred_ciphers = [
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-CHACHA20-POLY1305",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
            ]
            context.set_ciphers(":".join(preferred_ciphers))

        return context

    @property
    def ssl_context(self) -> ssl.SSLContext:
        """Get SSL context, creating it if necessary."""
        if self._ssl_context is None:
            self._ssl_context = self._create_ssl_context()
        return self._ssl_context

    async def connect(
        self, host: str, port: int = 1965, timeout: Optional[float] = None
    ) -> Tuple[ssl.SSLSocket, Dict[str, Any]]:
        """Establish TLS connection with SNI support.

        Args:
            host: Hostname to connect to
            port: Port number (default: 1965)
            timeout: Connection timeout (uses config default if None)

        Returns:
            Tuple of (SSL socket, connection info)

        Raises:
            TLSConnectionError: If connection fails
        """
        # Host-level SSRF/allowlist validation is performed by the caller
        # (GeminiClient) before reaching the transport.
        timeout = timeout or self.config.timeout_seconds

        logger.info(
            "Establishing TLS connection",
            host=host,
            port=port,
            timeout=timeout,
            tls_version=self.config.min_version,
        )

        start_time = time.time()

        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)

            # Connect to host
            await asyncio.get_event_loop().run_in_executor(
                None, sock.connect, (host, port)
            )

            # Wrap socket with TLS, including SNI (mandatory for Gemini)
            server_hostname = host
            ssl_sock = self.ssl_context.wrap_socket(
                sock,
                server_hostname=server_hostname,  # This enables SNI
                do_handshake_on_connect=False,
            )

            # Perform TLS handshake
            await asyncio.get_event_loop().run_in_executor(None, ssl_sock.do_handshake)

            # Get connection information
            connection_time = time.time() - start_time
            connection_info = self._get_connection_info(ssl_sock, connection_time)

            logger.info(
                "TLS connection established",
                host=host,
                port=port,
                connection_time=connection_time,
                tls_version=connection_info.get("tls_version"),
                cipher=connection_info.get("cipher"),
            )

            return ssl_sock, connection_info

        except socket.timeout:
            raise TLSConnectionError(f"Connection timeout after {timeout} seconds")
        except socket.gaierror as e:
            raise TLSConnectionError(f"DNS resolution failed for {host}: {e}", e)
        except ConnectionRefusedError:
            raise TLSConnectionError(f"Connection refused by {host}:{port}")
        except ssl.SSLError as e:
            raise TLSConnectionError(f"TLS handshake failed: {e}", e)
        except Exception as e:
            raise TLSConnectionError(f"Connection failed: {e}", e)

    def _get_connection_info(
        self, ssl_sock: ssl.SSLSocket, connection_time: float
    ) -> Dict[str, Any]:
        """Extract connection information from SSL socket.

        Args:
            ssl_sock: Connected SSL socket
            connection_time: Time taken to establish connection

        Returns:
            Dictionary with connection information
        """
        try:
            peer_cert = ssl_sock.getpeercert(binary_form=True)
            # Under CERT_NONE getpeercert() returns {}, so derive cert details
            # from the DER instead (this is where the expiry actually lives).
            peer_cert_info = self._parse_peer_cert(peer_cert)
            cipher = ssl_sock.cipher()

            info: Dict[str, Any] = {
                "connection_time": connection_time,
                "tls_version": ssl_sock.version(),
                "cipher": cipher[0] if cipher else None,
                "cipher_strength": cipher[2] if cipher else None,
                "peer_cert_der": peer_cert,
                "peer_cert_info": peer_cert_info,
                "sni_hostname": ssl_sock.server_hostname,
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
    def _parse_peer_cert(peer_cert_der: Optional[bytes]) -> Dict[str, Any]:
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

    async def close(self, ssl_sock: ssl.SSLSocket) -> None:
        """Close TLS connection gracefully with close_notify.

        Args:
            ssl_sock: SSL socket to close
        """
        try:
            # Send TLS close_notify alert
            await asyncio.get_event_loop().run_in_executor(None, ssl_sock.unwrap)
        except Exception as e:
            logger.warning("Error during TLS close_notify", error=str(e))
        finally:
            # Close the underlying socket
            try:
                ssl_sock.close()
            except Exception as e:
                logger.warning("Error closing socket", error=str(e))

    async def send_data(self, ssl_sock: ssl.SSLSocket, data: bytes) -> None:
        """Send data over TLS connection.

        Args:
            ssl_sock: Connected SSL socket
            data: Data to send

        Raises:
            TLSConnectionError: If send fails
        """
        try:
            await asyncio.get_event_loop().run_in_executor(None, ssl_sock.sendall, data)
        except Exception as e:
            raise TLSConnectionError(f"Failed to send data: {e}", e)

    async def receive_data(
        self,
        ssl_sock: ssl.SSLSocket,
        max_size: int = 1024 * 1024,  # 1MB default
    ) -> bytes:
        """Receive data from TLS connection.

        Args:
            ssl_sock: Connected SSL socket
            max_size: Maximum data size to receive

        Returns:
            Received data

        Raises:
            TLSConnectionError: If receive fails or the response exceeds max_size.
        """
        loop = asyncio.get_running_loop()
        try:
            chunks: list[bytes] = []
            total = 0
            while total < max_size:
                chunk = await loop.run_in_executor(
                    None, ssl_sock.recv, min(4096, max_size - total)
                )
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)

            # Hit the cap without EOF: probe one more byte so an over-limit
            # response is REJECTED rather than silently truncated (which would
            # hand the model a corrupted, incomplete document as if complete).
            extra = await loop.run_in_executor(None, ssl_sock.recv, 1)
            if extra:
                raise TLSConnectionError(
                    f"Response exceeds maximum size of {max_size} bytes"
                )
            return b"".join(chunks)

        except TLSConnectionError:
            raise
        except Exception as e:
            raise TLSConnectionError(f"Failed to receive data: {e}", e)


def create_tls_client(
    min_version: str = "TLSv1.2",
    timeout_seconds: float = 30.0,
    client_cert_path: Optional[str] = None,
    client_key_path: Optional[str] = None,
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE,
) -> GeminiTLSClient:
    """Create a configured TLS client for Gemini connections.

    Args:
        min_version: Minimum TLS version ("TLSv1.2" or "TLSv1.3")
        timeout_seconds: Connection timeout
        client_cert_path: Path to client certificate file
        client_key_path: Path to client private key file
        verify_mode: Certificate verification mode

    Returns:
        Configured TLS client
    """
    config = TLSConfig(
        min_version=min_version,
        timeout_seconds=timeout_seconds,
        client_cert_path=client_cert_path,
        client_key_path=client_key_path,
        verify_mode=verify_mode,
    )

    return GeminiTLSClient(config)
