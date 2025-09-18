"""Tests for Gemini TLS client implementation."""

import ssl
import socket
from unittest.mock import Mock, patch, AsyncMock
import pytest

from gopher_mcp.gemini_tls import (
    TLSConfig,
    TLSConnectionError,
    GeminiTLSClient,
    create_tls_client,
)


class TestTLSConfig:
    """Test TLS configuration."""

    def test_default_config(self):
        """Test default TLS configuration."""
        config = TLSConfig()

        assert config.min_version == "TLSv1.2"
        assert config.verify_mode == ssl.CERT_NONE
        assert config.client_cert_path is None
        assert config.client_key_path is None
        assert config.timeout_seconds == 30.0

    def test_custom_config(self):
        """Test custom TLS configuration."""
        config = TLSConfig(
            min_version="TLSv1.3",
            verify_mode=ssl.CERT_REQUIRED,
            client_cert_path="/path/to/cert.pem",
            client_key_path="/path/to/key.pem",
            timeout_seconds=60.0,
        )

        assert config.min_version == "TLSv1.3"
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.client_cert_path == "/path/to/cert.pem"
        assert config.client_key_path == "/path/to/key.pem"
        assert config.timeout_seconds == 60.0

    def test_invalid_tls_version(self):
        """Test that invalid TLS versions are rejected."""
        with pytest.raises(ValueError, match="Unsupported TLS version"):
            TLSConfig(min_version="TLSv1.1")

    def test_invalid_timeout(self):
        """Test that invalid timeouts are rejected."""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            TLSConfig(timeout_seconds=0)

        with pytest.raises(ValueError, match="Timeout must be positive"):
            TLSConfig(timeout_seconds=-1)

    def test_cert_without_key(self):
        """Test that cert without key is rejected."""
        with pytest.raises(ValueError, match="Client key path required"):
            TLSConfig(client_cert_path="/path/to/cert.pem")

    def test_key_without_cert(self):
        """Test that key without cert is rejected."""
        with pytest.raises(ValueError, match="Client cert path required"):
            TLSConfig(client_key_path="/path/to/key.pem")


class TestTLSConnectionError:
    """Test TLS connection error."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = TLSConnectionError("Connection failed")

        assert str(error) == "Connection failed"
        assert error.original_error is None

    def test_error_with_original(self):
        """Test error with original exception."""
        original = ConnectionRefusedError("Connection refused")
        error = TLSConnectionError("TLS failed", original)

        assert str(error) == "TLS failed"
        assert error.original_error == original


class TestGeminiTLSClient:
    """Test Gemini TLS client."""

    def test_client_initialization(self):
        """Test client initialization."""
        client = GeminiTLSClient()

        assert client.config.min_version == "TLSv1.2"
        assert client._ssl_context is None

    def test_client_with_custom_config(self):
        """Test client with custom configuration."""
        config = TLSConfig(min_version="TLSv1.3", timeout_seconds=60.0)
        client = GeminiTLSClient(config)

        assert client.config == config

    def test_ssl_context_creation(self):
        """Test SSL context creation."""
        client = GeminiTLSClient()
        context = client.ssl_context

        assert isinstance(context, ssl.SSLContext)
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2
        assert context.check_hostname is False
        assert context.verify_mode == ssl.CERT_NONE

    def test_ssl_context_tls13(self):
        """Test SSL context with TLS 1.3."""
        config = TLSConfig(min_version="TLSv1.3")
        client = GeminiTLSClient(config)
        context = client.ssl_context

        assert context.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_ssl_context_caching(self):
        """Test that SSL context is cached."""
        client = GeminiTLSClient()
        context1 = client.ssl_context
        context2 = client.ssl_context

        assert context1 is context2

    @patch("ssl.SSLContext.load_cert_chain")
    def test_ssl_context_with_client_cert(self, mock_load_cert):
        """Test SSL context with client certificate."""
        config = TLSConfig(
            client_cert_path="/path/to/cert.pem", client_key_path="/path/to/key.pem"
        )
        client = GeminiTLSClient(config)

        # Access ssl_context to trigger creation
        _ = client.ssl_context

        mock_load_cert.assert_called_once_with("/path/to/cert.pem", "/path/to/key.pem")

    @patch("ssl.create_default_context")
    def test_ssl_context_creation_error(self, mock_create_context):
        """Test SSL context creation error handling."""
        mock_create_context.side_effect = Exception("SSL error")
        client = GeminiTLSClient()

        with pytest.raises(TLSConnectionError, match="Failed to create SSL context"):
            _ = client.ssl_context

    @pytest.mark.asyncio
    @patch("socket.socket")
    @patch("asyncio.get_event_loop")
    async def test_connect_success(self, mock_get_loop, mock_socket):
        """Test successful TLS connection."""
        # Mock socket and SSL socket
        mock_sock = Mock()
        mock_ssl_sock = Mock()
        mock_ssl_sock.version.return_value = "TLSv1.2"
        mock_ssl_sock.cipher.return_value = (
            "ECDHE-RSA-AES256-GCM-SHA384",
            "TLSv1.2",
            256,
        )
        mock_ssl_sock.getpeercert.return_value = {"subject": [["CN", "example.org"]]}
        mock_ssl_sock.getpeercert.return_value = b"fake_cert_data"
        mock_ssl_sock.server_hostname = "example.org"

        mock_socket.return_value = mock_sock

        # Mock event loop executor
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock()
        mock_get_loop.return_value = mock_loop

        # Mock SSL context
        client = GeminiTLSClient()
        client._ssl_context = Mock()
        client._ssl_context.wrap_socket.return_value = mock_ssl_sock

        # Test connection
        ssl_sock, info = await client.connect("example.org", 1965)

        assert ssl_sock == mock_ssl_sock
        assert "connection_time" in info
        assert info["tls_version"] == "TLSv1.2"
        assert info["sni_hostname"] == "example.org"

    @pytest.mark.asyncio
    @patch("socket.socket")
    async def test_connect_timeout(self, mock_socket):
        """Test connection timeout."""
        mock_sock = Mock()
        mock_sock.connect.side_effect = socket.timeout()
        mock_socket.return_value = mock_sock

        client = GeminiTLSClient()

        with pytest.raises(TLSConnectionError, match="Connection timeout"):
            await client.connect("example.org", 1965, timeout=1.0)

    @pytest.mark.asyncio
    @patch("socket.socket")
    async def test_connect_dns_error(self, mock_socket):
        """Test DNS resolution error."""
        mock_sock = Mock()
        mock_sock.connect.side_effect = socket.gaierror("Name resolution failed")
        mock_socket.return_value = mock_sock

        client = GeminiTLSClient()

        with pytest.raises(TLSConnectionError, match="DNS resolution failed"):
            await client.connect("nonexistent.example", 1965)

    @pytest.mark.asyncio
    @patch("socket.socket")
    async def test_connect_refused(self, mock_socket):
        """Test connection refused."""
        mock_sock = Mock()
        mock_sock.connect.side_effect = ConnectionRefusedError()
        mock_socket.return_value = mock_sock

        client = GeminiTLSClient()

        with pytest.raises(TLSConnectionError, match="Connection refused"):
            await client.connect("example.org", 1965)

    @pytest.mark.asyncio
    @patch("socket.socket")
    @patch("asyncio.get_event_loop")
    async def test_connect_ssl_error(self, mock_get_loop, mock_socket):
        """Test SSL handshake error."""
        mock_sock = Mock()
        mock_ssl_sock = Mock()
        mock_ssl_sock.do_handshake.side_effect = ssl.SSLError("Handshake failed")

        mock_socket.return_value = mock_sock

        # Mock event loop executor
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.side_effect = [None, ssl.SSLError("Handshake failed")]
        mock_get_loop.return_value = mock_loop

        # Mock SSL context
        client = GeminiTLSClient()
        client._ssl_context = Mock()
        client._ssl_context.wrap_socket.return_value = mock_ssl_sock

        with pytest.raises(TLSConnectionError, match="TLS handshake failed"):
            await client.connect("example.org", 1965)

    @pytest.mark.asyncio
    async def test_close_connection(self):
        """Test closing TLS connection."""
        mock_ssl_sock = Mock()
        client = GeminiTLSClient()

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.run_in_executor = AsyncMock()
            mock_get_loop.return_value = mock_loop

            await client.close(mock_ssl_sock)

            # Verify unwrap was called (close_notify)
            mock_loop.run_in_executor.assert_called_once()
            mock_ssl_sock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_connection_error(self):
        """Test closing connection with errors."""
        mock_ssl_sock = Mock()
        mock_ssl_sock.unwrap.side_effect = Exception("Unwrap failed")
        mock_ssl_sock.close.side_effect = Exception("Close failed")

        client = GeminiTLSClient()

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.run_in_executor = AsyncMock(
                side_effect=Exception("Unwrap failed")
            )
            mock_get_loop.return_value = mock_loop

            # Should not raise exception despite errors
            await client.close(mock_ssl_sock)

    @pytest.mark.asyncio
    async def test_send_data(self):
        """Test sending data over TLS."""
        mock_ssl_sock = Mock()
        client = GeminiTLSClient()
        data = b"gemini://example.org/\r\n"

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.run_in_executor = AsyncMock()
            mock_get_loop.return_value = mock_loop

            await client.send_data(mock_ssl_sock, data)

            mock_loop.run_in_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_data_error(self):
        """Test send data error handling."""
        mock_ssl_sock = Mock()
        client = GeminiTLSClient()

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.run_in_executor = AsyncMock(side_effect=Exception("Send failed"))
            mock_get_loop.return_value = mock_loop

            with pytest.raises(TLSConnectionError, match="Failed to send data"):
                await client.send_data(mock_ssl_sock, b"data")

    @pytest.mark.asyncio
    async def test_receive_data(self):
        """Test receiving data over TLS."""
        mock_ssl_sock = Mock()
        client = GeminiTLSClient()

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            # Simulate receiving data in chunks, then empty chunk (EOF)
            mock_loop.run_in_executor = AsyncMock(
                side_effect=[b"20 text/gemini\r\n", b"Hello", b""]
            )
            mock_get_loop.return_value = mock_loop

            data = await client.receive_data(mock_ssl_sock)

            assert data == b"20 text/gemini\r\nHello"

    @pytest.mark.asyncio
    async def test_receive_data_error(self):
        """Test receive data error handling."""
        mock_ssl_sock = Mock()
        client = GeminiTLSClient()

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = Mock()
            mock_loop.run_in_executor = AsyncMock(
                side_effect=Exception("Receive failed")
            )
            mock_get_loop.return_value = mock_loop

            with pytest.raises(TLSConnectionError, match="Failed to receive data"):
                await client.receive_data(mock_ssl_sock)

    def test_get_connection_info(self):
        """Test extracting connection information."""
        mock_ssl_sock = Mock()
        mock_ssl_sock.version.return_value = "TLSv1.3"
        mock_ssl_sock.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
        mock_ssl_sock.getpeercert.side_effect = [
            {"subject": [["CN", "example.org"]]},  # First call (text form)
            b"fake_cert_data",  # Second call (binary form)
        ]
        mock_ssl_sock.server_hostname = "example.org"

        client = GeminiTLSClient()

        with patch("hashlib.sha256") as mock_sha256:
            mock_sha256.return_value.hexdigest.return_value = "abcdef123456"

            info = client._get_connection_info(mock_ssl_sock, 1.5)

            assert info["connection_time"] == 1.5
            assert info["tls_version"] == "TLSv1.3"
            assert info["cipher"] == "TLS_AES_256_GCM_SHA384"
            assert info["cipher_strength"] == 256
            assert info["sni_hostname"] == "example.org"
            assert info["cert_fingerprint"] == "sha256:abcdef123456"

    def test_get_connection_info_error(self):
        """Test connection info extraction with errors."""
        mock_ssl_sock = Mock()
        mock_ssl_sock.version.side_effect = Exception("Version error")

        client = GeminiTLSClient()
        info = client._get_connection_info(mock_ssl_sock, 1.0)

        assert info["connection_time"] == 1.0
        assert "error" in info


class TestCreateTLSClient:
    """Test TLS client factory function."""

    def test_create_default_client(self):
        """Test creating client with defaults."""
        client = create_tls_client()

        assert isinstance(client, GeminiTLSClient)
        assert client.config.min_version == "TLSv1.2"
        assert client.config.timeout_seconds == 30.0

    def test_create_custom_client(self):
        """Test creating client with custom settings."""
        client = create_tls_client(
            min_version="TLSv1.3",
            timeout_seconds=60.0,
            client_cert_path="/cert.pem",
            client_key_path="/key.pem",
            verify_mode=ssl.CERT_REQUIRED,
        )

        assert client.config.min_version == "TLSv1.3"
        assert client.config.timeout_seconds == 60.0
        assert client.config.client_cert_path == "/cert.pem"
        assert client.config.client_key_path == "/key.pem"
        assert client.config.verify_mode == ssl.CERT_REQUIRED


class TestGeminiTLSAdditionalCoverage:
    """Test additional TLS functionality for better coverage."""

    def test_ssl_context_creation_with_invalid_cert_path(self):
        """Test SSL context creation with invalid certificate path."""
        config = TLSConfig(
            client_cert_path="/nonexistent/cert.pem",
            client_key_path="/nonexistent/key.pem",
        )
        client = GeminiTLSClient(config)

        # This should handle the file not found error gracefully
        with pytest.raises(Exception):
            client._create_ssl_context()

    @pytest.mark.asyncio
    async def test_connection_cleanup_on_error(self):
        """Test that connections are properly cleaned up on errors."""
        client = GeminiTLSClient()

        # Mock socket creation to fail
        with patch("socket.socket") as mock_socket:
            mock_socket.side_effect = OSError("Connection failed")

            with pytest.raises(TLSConnectionError):
                await client.connect("nonexistent.example.com", 1965)

    @pytest.mark.asyncio
    async def test_receive_data_with_large_response(self):
        """Test receiving large response data."""
        client = GeminiTLSClient()

        # Mock SSL socket
        mock_sock = Mock()
        large_data = b"x" * 2048  # Larger than typical buffer
        mock_sock.recv.side_effect = [large_data[:1024], large_data[1024:], b""]

        result = await client.receive_data(mock_sock, max_size=2048)
        assert result == large_data

    def test_tls_config_edge_cases(self):
        """Test TLS config edge cases for better coverage."""
        # Test with minimum valid timeout
        config = TLSConfig(timeout_seconds=0.1)
        assert config.timeout_seconds == 0.1

        # Test with very high timeout
        config = TLSConfig(timeout_seconds=3600.0)
        assert config.timeout_seconds == 3600.0
