"""Tests for Gemini TLS client implementation (native asyncio transport)."""

import asyncio
import hashlib
import socket
import ssl
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gopher_mcp.gemini_tls import (
    GeminiTLSClient,
    TLSConfig,
    TLSConnection,
    TLSConnectionError,
)


def _conn(reader=None, writer=None) -> TLSConnection:
    """Build a TLSConnection from a reader/writer (real or mock)."""
    return TLSConnection(reader=reader or Mock(), writer=writer or Mock())


class TestTLSConfig:
    """Test TLS configuration."""

    def test_default_config(self):
        config = TLSConfig()
        assert config.min_version == "TLSv1.2"
        assert config.verify_mode == ssl.CERT_NONE
        assert config.client_cert_path is None
        assert config.client_key_path is None
        assert config.timeout_seconds == 30.0

    def test_custom_config(self):
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
        with pytest.raises(ValueError, match="Unsupported TLS version"):
            TLSConfig(min_version="TLSv1.1")

    def test_invalid_timeout(self):
        with pytest.raises(ValueError, match="Timeout must be positive"):
            TLSConfig(timeout_seconds=0)
        with pytest.raises(ValueError, match="Timeout must be positive"):
            TLSConfig(timeout_seconds=-1)

    def test_cert_without_key(self):
        with pytest.raises(ValueError, match="Client key path required"):
            TLSConfig(client_cert_path="/path/to/cert.pem")

    def test_key_without_cert(self):
        with pytest.raises(ValueError, match="Client cert path required"):
            TLSConfig(client_key_path="/path/to/key.pem")

    def test_tls_config_edge_cases(self):
        assert TLSConfig(timeout_seconds=0.1).timeout_seconds == 0.1
        assert TLSConfig(timeout_seconds=3600.0).timeout_seconds == 3600.0


class TestTLSConnectionError:
    """Test TLS connection error."""

    def test_basic_error(self):
        error = TLSConnectionError("Connection failed")
        assert str(error) == "Connection failed"
        assert error.original_error is None

    def test_error_with_original(self):
        original = ConnectionRefusedError("Connection refused")
        error = TLSConnectionError("TLS failed", original)
        assert str(error) == "TLS failed"
        assert error.original_error == original


class TestSSLContext:
    """Test SSL context construction."""

    def test_client_initialization(self):
        client = GeminiTLSClient()
        assert client.config.min_version == "TLSv1.2"
        assert client._ssl_context is None

    def test_client_with_custom_config(self):
        config = TLSConfig(min_version="TLSv1.3", timeout_seconds=60.0)
        client = GeminiTLSClient(config)
        assert client.config == config

    def test_ssl_context_creation(self):
        context = GeminiTLSClient().ssl_context
        assert isinstance(context, ssl.SSLContext)
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2
        assert context.check_hostname is False
        assert context.verify_mode == ssl.CERT_NONE

    def test_ssl_context_tls13(self):
        context = GeminiTLSClient(TLSConfig(min_version="TLSv1.3")).ssl_context
        assert context.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_ssl_context_does_not_narrow_cipher_suites(self):
        """The TLS 1.2 cipher list must not be narrowed to a few AEAD-only ECDHE
        suites: that drops ECDHE-CBC and DHE suites and risks handshake failures
        with conforming Gemini servers. Peer auth is via TOFU pinning, so keep
        Python's secure defaults. A narrowed list yields ~9 ciphers; default ~17."""
        assert len(GeminiTLSClient().ssl_context.get_ciphers()) > 12

    def test_ssl_context_caching(self):
        client = GeminiTLSClient()
        assert client.ssl_context is client.ssl_context

    @patch("ssl.SSLContext.load_cert_chain")
    def test_ssl_context_with_client_cert(self, mock_load_cert):
        config = TLSConfig(
            client_cert_path="/path/to/cert.pem", client_key_path="/path/to/key.pem"
        )
        _ = GeminiTLSClient(config).ssl_context
        mock_load_cert.assert_called_once_with("/path/to/cert.pem", "/path/to/key.pem")

    @patch("ssl.create_default_context")
    def test_ssl_context_creation_error(self, mock_create_context):
        mock_create_context.side_effect = Exception("SSL error")
        with pytest.raises(TLSConnectionError, match="Failed to create SSL context"):
            _ = GeminiTLSClient().ssl_context

    def test_ssl_context_creation_with_invalid_cert_path(self):
        config = TLSConfig(
            client_cert_path="/nonexistent/cert.pem",
            client_key_path="/nonexistent/key.pem",
        )
        with pytest.raises(TLSConnectionError):
            GeminiTLSClient(config)._create_ssl_context()


class TestConnectErrorMapping:
    """connect() maps transport errors to TLSConnectionError without hitting the
    network (asyncio.open_connection is patched)."""

    @pytest.mark.asyncio
    async def test_timeout(self):
        with patch("asyncio.open_connection", AsyncMock(side_effect=TimeoutError())):
            with pytest.raises(TLSConnectionError, match="Connection timeout"):
                await GeminiTLSClient().connect("example.org", 1965, timeout=1.0)

    @pytest.mark.asyncio
    async def test_dns_error(self):
        with patch(
            "asyncio.open_connection",
            AsyncMock(side_effect=socket.gaierror("name resolution failed")),
        ):
            with pytest.raises(TLSConnectionError, match="DNS resolution failed"):
                await GeminiTLSClient().connect("nonexistent.invalid", 1965)

    @pytest.mark.asyncio
    async def test_refused(self):
        with patch(
            "asyncio.open_connection", AsyncMock(side_effect=ConnectionRefusedError())
        ):
            with pytest.raises(TLSConnectionError, match="Connection refused"):
                await GeminiTLSClient().connect("example.org", 1965)

    @pytest.mark.asyncio
    async def test_ssl_error(self):
        with patch(
            "asyncio.open_connection",
            AsyncMock(side_effect=ssl.SSLError("handshake failed")),
        ):
            with pytest.raises(TLSConnectionError, match="TLS handshake failed"):
                await GeminiTLSClient().connect("example.org", 1965)

    @pytest.mark.asyncio
    async def test_generic_oserror(self):
        with patch("asyncio.open_connection", AsyncMock(side_effect=OSError("boom"))):
            with pytest.raises(TLSConnectionError, match="Connection failed"):
                await GeminiTLSClient().connect("example.org", 1965)


class TestSendReceiveClose:
    """send_data/receive_data/close operate on the native asyncio streams."""

    @pytest.mark.asyncio
    async def test_send_data(self):
        writer = Mock()
        writer.write = Mock()
        writer.drain = AsyncMock()
        await GeminiTLSClient().send_data(_conn(writer=writer), b"gemini://x/\r\n")
        writer.write.assert_called_once_with(b"gemini://x/\r\n")
        writer.drain.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_data_error(self):
        writer = Mock()
        writer.write = Mock(side_effect=RuntimeError("boom"))
        with pytest.raises(TLSConnectionError, match="Failed to send data"):
            await GeminiTLSClient().send_data(_conn(writer=writer), b"data")

    @pytest.mark.asyncio
    async def test_close_connection(self):
        writer = Mock()
        writer.close = Mock()
        writer.wait_closed = AsyncMock()
        await GeminiTLSClient().close(_conn(writer=writer))
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_suppresses_errors(self):
        writer = Mock()
        writer.close = Mock()
        writer.wait_closed = AsyncMock(side_effect=RuntimeError("boom"))
        # Must not raise even if wait_closed errors.
        await GeminiTLSClient().close(_conn(writer=writer))

    @pytest.mark.asyncio
    async def test_close_is_time_bounded_when_peer_withholds_close_notify(self):
        """A peer that never sends close_notify must not hang close() past the
        grace period (which would add the OS TCP timeout to every request)."""

        async def _never_returns() -> None:
            await asyncio.Event().wait()  # blocks forever

        writer = Mock()
        writer.close = Mock()
        writer.wait_closed = Mock(side_effect=_never_returns)
        with patch("gopher_mcp.gemini_tls.CLOSE_TIMEOUT_SECONDS", 0.01):
            # Must return promptly (well under any real TCP timeout) and not raise.
            await asyncio.wait_for(
                GeminiTLSClient().close(_conn(writer=writer)), timeout=1.0
            )
        writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_reads_until_eof(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"20 text/gemini\r\nHello")
        reader.feed_eof()
        data = await GeminiTLSClient().receive_data(_conn(reader=reader))
        assert data == b"20 text/gemini\r\nHello"

    @pytest.mark.asyncio
    async def test_receive_rejects_oversize(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * 2048)
        reader.feed_eof()
        with pytest.raises(TLSConnectionError, match="exceeds maximum size"):
            await GeminiTLSClient().receive_data(_conn(reader=reader), max_size=1024)

    @pytest.mark.asyncio
    async def test_receive_accepts_exactly_max_size_on_eof(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * 1024)
        reader.feed_eof()
        result = await GeminiTLSClient().receive_data(
            _conn(reader=reader), max_size=1024
        )
        assert result == b"x" * 1024

    @pytest.mark.asyncio
    async def test_receive_accepts_exactly_max_size_when_held_open(self, monkeypatch):
        """A complete, exactly-max_size response whose server holds the
        connection open (no EOF) is accepted once the short probe times out,
        rather than spuriously erroring."""
        monkeypatch.setattr("gopher_mcp.gemini_tls.PROBE_TIMEOUT_SECONDS", 0.05)
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * 1024)  # no feed_eof: connection stays open
        result = await GeminiTLSClient().receive_data(
            _conn(reader=reader), max_size=1024
        )
        assert result == b"x" * 1024

    @pytest.mark.asyncio
    async def test_receive_error_wrapped(self):
        reader = Mock()
        reader.read = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(TLSConnectionError, match="Failed to receive data"):
            await GeminiTLSClient().receive_data(_conn(reader=reader))


class TestConnectionInfo:
    """_get_connection_info derives details (incl. fingerprint) from the SSL
    object, working under CERT_NONE where getpeercert() (dict form) is empty."""

    def test_get_connection_info(self):
        ssl_obj = Mock()
        ssl_obj.getpeercert.return_value = b"fake_cert_data"
        ssl_obj.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
        ssl_obj.version.return_value = "TLSv1.3"
        ssl_obj.server_hostname = "example.org"

        info = GeminiTLSClient()._get_connection_info(ssl_obj, 1.5)

        assert info["connection_time"] == 1.5
        assert info["tls_version"] == "TLSv1.3"
        assert info["cipher"] == "TLS_AES_256_GCM_SHA384"
        assert info["cipher_strength"] == 256
        assert info["sni_hostname"] == "example.org"
        expected = "sha256:" + hashlib.sha256(b"fake_cert_data").hexdigest()
        assert info["cert_fingerprint"] == expected

    def test_get_connection_info_error(self):
        ssl_obj = Mock()
        ssl_obj.getpeercert.side_effect = Exception("boom")
        info = GeminiTLSClient()._get_connection_info(ssl_obj, 1.0)
        assert info["connection_time"] == 1.0
        assert "error" in info

    def test_get_connection_info_no_ssl_object(self):
        info = GeminiTLSClient()._get_connection_info(None, 1.0)
        assert info["connection_time"] == 1.0
        assert "error" in info


def _make_self_signed_cert(tmp_path):
    """Write a self-signed cert+key to ``tmp_path`` and return (cert_pem_path,
    key_pem_path, der_sha256_hex)."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    der_sha256 = hashlib.sha256(cert_der).hexdigest()

    cert_path = tmp_path / "server.crt"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path), der_sha256


class TestRealTLSHandshake:
    """Drive connect()/send/receive/close against a REAL loopback TLS server,
    behaviorally exercising SNI delivery, the handshake, and fingerprint
    extraction from the real peer DER (the foundation TOFU depends on)."""

    @pytest.mark.asyncio
    async def test_real_handshake_extracts_matching_fingerprint(self, tmp_path):
        cert_path, key_path, expected_sha256 = _make_self_signed_cert(tmp_path)

        seen_sni: list[str | None] = []
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert_path, key_path)
        server_ctx.sni_callback = lambda sslobj, name, ctx: seen_sni.append(name)

        async def handle(reader, writer):
            await reader.readline()
            writer.write(b"20 text/gemini\r\nhello\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
        port = server.sockets[0].getsockname()[1]

        client = GeminiTLSClient(TLSConfig())
        try:
            conn, info = await client.connect(
                "localhost", port, connect_ip="127.0.0.1", timeout=5.0
            )
            try:
                assert info["cert_fingerprint"] == f"sha256:{expected_sha256}"
                assert info["tls_version"] in ("TLSv1.2", "TLSv1.3")
                assert seen_sni and seen_sni[0] == "localhost"

                await client.send_data(conn, b"gemini://localhost/\r\n")
                body = await client.receive_data(conn, max_size=1024)
                assert body == b"20 text/gemini\r\nhello\r\n"
            finally:
                await client.close(conn)
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_real_stream_rejects_oversize_body(self, tmp_path):
        cert_path, key_path, _ = _make_self_signed_cert(tmp_path)
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert_path, key_path)

        async def handle(reader, writer):
            await reader.readline()
            writer.write(b"x" * 4096)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
        port = server.sockets[0].getsockname()[1]

        client = GeminiTLSClient(TLSConfig())
        try:
            conn, _ = await client.connect(
                "localhost", port, connect_ip="127.0.0.1", timeout=5.0
            )
            try:
                await client.send_data(conn, b"gemini://localhost/\r\n")
                with pytest.raises(TLSConnectionError, match="exceeds maximum size"):
                    await client.receive_data(conn, max_size=1024)
            finally:
                await client.close(conn)
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_slow_loris_read_is_cancellable(self, tmp_path):
        """A peer that completes the handshake then dribbles bytes forever is cut
        off at the wait_for deadline -- native asyncio makes the read genuinely
        cancellable (the old run_in_executor design could not be)."""
        cert_path, key_path, _ = _make_self_signed_cert(tmp_path)
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert_path, key_path)

        stop = asyncio.Event()

        async def handle(reader, writer):
            await reader.readline()
            try:
                while not stop.is_set():
                    writer.write(b"x")
                    await writer.drain()
                    await asyncio.sleep(0.05)
            except (ConnectionError, OSError):
                pass

        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
        port = server.sockets[0].getsockname()[1]

        client = GeminiTLSClient(TLSConfig())
        try:
            conn, _ = await client.connect(
                "localhost", port, connect_ip="127.0.0.1", timeout=5.0
            )
            try:
                await client.send_data(conn, b"gemini://localhost/\r\n")
                with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                    await asyncio.wait_for(
                        client.receive_data(conn, max_size=10_000_000), timeout=0.3
                    )
            finally:
                await client.close(conn)
        finally:
            stop.set()
            server.close()
            await server.wait_closed()


class TestConnectPinnedIp:
    """connect() must use the pinned IP, never re-resolve the hostname."""

    @pytest.mark.asyncio
    async def test_connect_uses_pinned_ip_not_hostname(self):
        client = GeminiTLSClient(TLSConfig())
        # Unresolvable hostname, but pinned to loopback:closed-port. A refusal
        # (not a DNS error) proves the pinned IP was used without re-resolving.
        with pytest.raises(TLSConnectionError) as exc_info:
            await client.connect(
                "host.that.never.resolves.invalid",
                1,
                connect_ip="127.0.0.1",
                timeout=2,
            )
        assert "DNS" not in str(exc_info.value)
