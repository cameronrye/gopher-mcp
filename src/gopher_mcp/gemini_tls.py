"""TLS client implementation for Gemini protocol with SNI support."""

import asyncio
import socket
import ssl
import time
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

import structlog

from .security import TLSSecurityManager, TLSSecurityConfig

logger = structlog.get_logger(__name__)


@dataclass
class TLSConfig:
    """Configuration for TLS connections."""

    min_version: str = "TLSv1.2"
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
    timeout_seconds: float = 30.0
    security_config: Optional[TLSSecurityConfig] = None

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

        # Initialize security manager
        self.security_manager = TLSSecurityManager(self.config.security_config)

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context with secure defaults.

        Returns:
            Configured SSL context

        Raises:
            TLSConnectionError: If SSL context creation fails
        """
        try:
            # Use security manager to create context if available
            if self.config.security_config:
                context = self.security_manager.create_ssl_context()
            else:
                # Fallback to legacy configuration
                context = self._create_legacy_ssl_context()

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

    def _create_legacy_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context using legacy configuration for backward compatibility."""
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
        # Validate host against security policy
        if not self.security_manager.validate_host(host):
            raise TLSConnectionError(f"Host {host} blocked by security policy")

        # Use security manager timeout if available
        timeout = timeout or self.security_manager.get_connection_timeout()

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

            # Wrap socket with TLS, including SNI
            server_hostname = host if self.security_manager.requires_sni() else None
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
            peer_cert_info = ssl_sock.getpeercert()
            cipher = ssl_sock.cipher()

            info = {
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
            TLSConnectionError: If receive fails
        """
        try:
            data = b""
            while len(data) < max_size:
                chunk = await asyncio.get_event_loop().run_in_executor(
                    None, ssl_sock.recv, min(4096, max_size - len(data))
                )
                if not chunk:
                    break
                data += chunk

            return data

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
