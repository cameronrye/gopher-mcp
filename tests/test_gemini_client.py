"""Tests for Gemini client implementation."""

import asyncio
import errno
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gopher_mcp.gemini_client import GeminiClient, _safe_display_url
from gopher_mcp.gemini_tls import (
    GeminiConnectionError,
    GeminiTLSClient,
    TLSConfig,
    TLSConnectionError,
)
from gopher_mcp.models import (
    GeminiCacheEntry,
    GeminiErrorResult,
    GeminiGemtextResult,
    GeminiMimeType,
    GeminiRedirectResult,
    GeminiResponse,
    GeminiStatusCode,
    GeminiSuccessResult,
)
from gopher_mcp.tofu import TOFUValidationError


class TestGeminiClientInit:
    """Test GeminiClient initialization."""

    def test_default_initialization(self):
        """Test client initialization with defaults."""
        client = GeminiClient()

        assert client.max_response_size == 1024 * 1024
        assert client.timeout_seconds == 30.0
        assert client.cache_enabled is True
        assert client.cache_ttl_seconds == 300
        assert client.max_cache_entries == 1000
        assert client.allowed_hosts is None
        assert client.tls_client is not None
        assert isinstance(client._cache, dict)

    def test_disabling_tofu_logs_a_warning(self):
        """tofu_enabled=False removes ALL peer authentication (CERT_NONE TLS),
        so it must be loud rather than a silent footgun."""
        with patch("gopher_mcp.gemini_client.logger") as mock_logger:
            client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        assert client.tofu_manager is None
        assert mock_logger.warning.called
        logged = str(mock_logger.warning.call_args).lower()
        assert "tofu" in logged or "unauthenticated" in logged

    def test_tls_client_for_cert_is_cached_per_pair(self):
        """The client-cert TLS client (and its SSL context) is built once per
        (cert, key) pair, not rebuilt on every request."""
        client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        a = client._tls_client_for_cert("/a.crt", "/a.key")
        b = client._tls_client_for_cert("/a.crt", "/a.key")
        assert a is b
        assert a.config.client_cert_path == "/a.crt"
        other = client._tls_client_for_cert("/b.crt", "/b.key")
        assert other is not a

    def test_status_44_slow_down_penalizes_host(self):
        """A status-44 SLOW_DOWN backs the host off for the advertised seconds.

        The seconds come from ``error["meta"]`` -- the capsule's own text --
        never from ``error["message"]``, which is this server's explanation.
        """
        client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        client._rate_limiter.penalize = Mock()  # type: ignore[method-assign]
        result = GeminiErrorResult(
            error={
                "code": "TEMPORARY_ERROR",
                "message": "The capsule answered status 44 (SLOW DOWN).",
                "meta": "10",
                "status": 44,
            },
            requestInfo={},
        )
        client._maybe_honor_slow_down("slow.example", result)
        client._rate_limiter.penalize.assert_called_once_with("slow.example", 10.0)

    def test_slow_down_ignores_a_number_in_the_server_authored_message(self):
        """Reading the seconds out of `message` would break the moment that
        field became server-authored prose (it now contains the status number),
        so the fallback must apply when `meta` names nothing usable."""
        client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        client._rate_limiter.penalize = Mock()  # type: ignore[method-assign]
        result = GeminiErrorResult(
            error={
                "code": "TEMPORARY_ERROR",
                "message": "The capsule answered status 44 (SLOW DOWN).",
                "meta": "in a while",
                "status": 44,
            },
            requestInfo={},
        )
        client._maybe_honor_slow_down("slow.example", result)
        client._rate_limiter.penalize.assert_called_once_with("slow.example", 60.0)

    def test_non_44_response_does_not_penalize(self):
        client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        client._rate_limiter.penalize = Mock()  # type: ignore[method-assign]
        result = GeminiErrorResult(
            error={"code": "TEMPORARY_ERROR", "meta": "x", "status": 41},
            requestInfo={},
        )
        client._maybe_honor_slow_down("h", result)
        client._rate_limiter.penalize.assert_not_called()

    def test_custom_initialization(self):
        """Test client initialization with custom parameters."""
        tls_config = TLSConfig(timeout_seconds=60.0)
        client = GeminiClient(
            max_response_size=2048,
            timeout_seconds=60.0,
            cache_enabled=False,
            cache_ttl_seconds=600,
            max_cache_entries=500,
            allowed_hosts=["example.com", "test.org"],
            tls_config=tls_config,
        )

        assert client.max_response_size == 2048
        assert client.timeout_seconds == 60.0
        assert client.cache_enabled is False
        assert client.cache_ttl_seconds == 600
        assert client.max_cache_entries == 500
        assert client.allowed_hosts == {"example.com", "test.org"}


class TestGeminiClientSecurity:
    """Test GeminiClient security validation."""

    def test_validate_security_allowed_host(self):
        """Test security validation with allowed hosts."""
        client = GeminiClient(allowed_hosts=["example.com"])

        # Mock parsed URL
        parsed_url = Mock()
        parsed_url.host = "example.com"
        parsed_url.port = 1965

        # Should not raise
        client._validate_security(parsed_url)

    def test_validate_security_disallowed_host(self):
        """Test security validation with disallowed host."""
        client = GeminiClient(allowed_hosts=["example.com"])

        # Mock parsed URL
        parsed_url = Mock()
        parsed_url.host = "malicious.com"
        parsed_url.port = 1965

        with pytest.raises(ValueError, match="Host not allowed"):
            client._validate_security(parsed_url)

    def test_validate_security_invalid_port_low(self):
        """Test security validation with invalid low port."""
        client = GeminiClient()

        # Mock parsed URL
        parsed_url = Mock()
        parsed_url.host = "example.com"
        parsed_url.port = 0

        with pytest.raises(ValueError, match="Invalid port number"):
            client._validate_security(parsed_url)

    def test_validate_security_invalid_port_high(self):
        """Test security validation with invalid high port."""
        client = GeminiClient()

        # Mock parsed URL
        parsed_url = Mock()
        parsed_url.host = "example.com"
        parsed_url.port = 65536

        with pytest.raises(ValueError, match="Invalid port number"):
            client._validate_security(parsed_url)


class TestGeminiClientFetch:
    """Test GeminiClient fetch method."""

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Test successful fetch operation."""
        client = GeminiClient(respect_robots_txt=False)

        # Mock dependencies
        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"
        mock_parsed_url.query = None

        mock_response = GeminiSuccessResult(
            content="Hello, world!",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=13,
            requestInfo={},
        )

        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = mock_parsed_url
            mock_fetch.return_value = mock_response

            result = await client.fetch("gemini://example.com/")

            assert result == mock_response
            assert "url" in result.request_info
            assert "timestamp" in result.request_info
            mock_parse.assert_called_once_with("gemini://example.com/")

    @pytest.mark.asyncio
    async def test_max_concurrent_requests_bounds_inflight(self):
        """An opt-in concurrency cap limits simultaneous in-flight fetches."""
        import asyncio

        from gopher_mcp.models import GeminiMimeType, GeminiSuccessResult

        client = GeminiClient(
            respect_robots_txt=False,
            max_concurrent_requests=2,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
            # Rate limiting is on by default and would serialize same-host
            # requests to one per second, hiding the concurrency behaviour.
            requests_per_minute=0,
        )
        inflight = 0
        peak = 0

        async def fake(_parsed_url):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            return GeminiSuccessResult(
                content="hi",
                mimeType=GeminiMimeType(type="text", subtype="plain"),
                size=2,
                requestInfo={},
            )

        client._fetch_content = fake  # type: ignore[method-assign]
        await asyncio.gather(
            *[client.fetch(f"gemini://example.org/{i}") for i in range(6)]
        )
        assert peak == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_dns_resolution_is_bounded_by_request_timeout(self):
        """A hanging resolver must not exceed the request deadline. DNS was
        previously outside the timeout envelope, so a tarpit nameserver could
        stall a worker far past timeout_seconds."""
        import asyncio

        client = GeminiClient(
            respect_robots_txt=False,
            timeout_seconds=0.05,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
        )

        async def slow_validate(*args, **kwargs):
            await asyncio.sleep(5)
            return ["93.184.216.34"]

        with patch(
            "gopher_mcp.gemini_client.validate_target", side_effect=slow_validate
        ):
            result = await asyncio.wait_for(
                client.fetch("gemini://example.org/"), timeout=1.0
            )

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        await client.close()

    @pytest.mark.asyncio
    async def test_missing_fingerprint_fails_closed_without_sending(self):
        """The most security-critical TOFU branch: when TLS yields no certificate
        fingerprint, the request must NOT be sent to the unverified peer."""
        client = GeminiClient(
            client_certs_enabled=False,  # TOFU on by default
            respect_robots_txt=False,
        )
        assert client.tofu_manager is not None

        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(Mock(), {})  # no 'cert_fingerprint' key
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.receive_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        # Distinct from a fingerprint mismatch: there is no cert to compare, so
        # reporting CERTIFICATE_CHANGED ("does not match") would be misleading.
        assert result.error["code"] == "CERTIFICATE_UNVERIFIED"
        assert "does not match" not in result.error["message"].lower()
        client.tls_client.send_data.assert_not_awaited()  # never reached the wire

    @pytest.mark.asyncio
    async def test_expired_pin_reports_certificate_expired_not_changed(self):
        """With reject_expired, an expired-but-MATCHING pin must report
        CERTIFICATE_EXPIRED -- not CERTIFICATE_CHANGED, which would falsely imply
        the cert no longer matches and send an operator chasing a phantom MITM."""
        import tempfile
        from pathlib import Path as _Path

        from gopher_mcp.models import TOFUEntry

        with tempfile.TemporaryDirectory() as d:
            client = GeminiClient(
                respect_robots_txt=False,
                client_certs_enabled=False,
                tofu_reject_expired=True,
                tofu_storage_path=str(_Path(d) / "tofu.json"),
            )
            assert client.tofu_manager is not None
            # Pre-pin an already-expired cert with a known fingerprint.
            client.tofu_manager._entries["example.com:1965"] = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc",
                first_seen=1.0,
                last_seen=1.0,
                expires=100.0,
            )

            client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
                return_value=(Mock(), {"cert_fingerprint": "abc", "peer_cert_info": {}})
            )
            client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
            client.tls_client.receive_data = AsyncMock()  # type: ignore[method-assign]
            client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

            result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "CERTIFICATE_EXPIRED"
        # The accurate message must not claim the cert "changed"/"does not match".
        assert "does not match" not in result.error["message"].lower()
        client.tls_client.send_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_with_cache_hit(self):
        """Test fetch with cache hit."""
        client = GeminiClient(cache_enabled=True, respect_robots_txt=False)

        # Mock cached response
        cached_response = GeminiSuccessResult(
            content="Cached content",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=14,
            requestInfo={},
        )

        entry = GeminiCacheEntry(
            key="gemini://example.com/",
            value=cached_response,
            timestamp=time.time() - 30,
            ttl=300,
        )

        with patch.object(client, "_get_cached_entry") as mock_get_cache:
            mock_get_cache.return_value = entry

            result = await client.fetch("gemini://example.com/")

            # The content is the cached one, but the copy handed back is marked
            # as a replay so the model can tell it is not the current state.
            assert isinstance(result, GeminiSuccessResult)
            assert result.content == cached_response.content
            assert result.cached is True
            mock_get_cache.assert_called_once_with("gemini://example.com/")

    @pytest.mark.asyncio
    async def test_fetch_error_handling(self):
        """Test fetch error handling."""
        client = GeminiClient(respect_robots_txt=False)

        with patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid URL")

            result = await client.fetch("invalid://url")

            assert isinstance(result, GeminiErrorResult)
            assert result.error["code"] == "INVALID_REQUEST"
            assert "Invalid URL" in result.error["message"]

    async def test_malformed_server_response_is_protocol_error_not_invalid_request(
        self,
    ):
        """A server-side protocol fault (e.g. missing CRLF, empty response) must
        surface as PROTOCOL_ERROR, not INVALID_REQUEST -- the latter wrongly
        tells the model its own URL was malformed."""
        from gopher_mcp.gemini_parse import GeminiProtocolError

        client = GeminiClient(respect_robots_txt=False)
        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"
        mock_parsed_url.query = None

        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = mock_parsed_url
            mock_fetch.side_effect = GeminiProtocolError(
                "Invalid response format: missing CRLF"
            )

            result = await client.fetch("gemini://example.com/")

            assert isinstance(result, GeminiErrorResult)
            assert result.error["code"] == "PROTOCOL_ERROR"
            assert "missing CRLF" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_security_violation(self):
        """Test fetch with security violation."""
        client = GeminiClient(allowed_hosts=["allowed.com"], respect_robots_txt=False)

        mock_parsed_url = Mock()
        mock_parsed_url.host = "forbidden.com"
        mock_parsed_url.port = 1965

        with patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse:
            mock_parse.return_value = mock_parsed_url

            result = await client.fetch("gemini://forbidden.com/")

            assert isinstance(result, GeminiErrorResult)
            assert "Host not allowed" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_does_not_cache_error_result(self):
        """A transient error result must not be cached, or a momentary server
        failure would be served stale for the full cache TTL."""
        client = GeminiClient(cache_enabled=True, respect_robots_txt=False)

        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"
        mock_parsed_url.query = None

        error_response = GeminiErrorResult(
            error={"code": "TEMPORARY_FAILURE", "message": "Server unavailable"},
            requestInfo={},
        )

        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = mock_parsed_url
            mock_fetch.return_value = error_response

            result = await client.fetch("gemini://example.com/")

            assert result == error_response
            assert client._get_cached_response("gemini://example.com/") is None

    @pytest.mark.asyncio
    async def test_fetch_does_not_cache_redirect_result(self):
        """A redirect result must not be cached: the target can change and a
        stale redirect would keep sending the client to the old location."""
        client = GeminiClient(cache_enabled=True, respect_robots_txt=False)

        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"
        mock_parsed_url.query = None

        redirect_response = GeminiRedirectResult(
            newUrl="gemini://example.com/new", requestInfo={}
        )

        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = mock_parsed_url
            mock_fetch.return_value = redirect_response

            result = await client.fetch("gemini://example.com/")

            assert result == redirect_response
            assert client._get_cached_response("gemini://example.com/") is None

    @pytest.mark.asyncio
    async def test_fetch_caches_success_result(self):
        """A successful response is still cached."""
        client = GeminiClient(cache_enabled=True, respect_robots_txt=False)

        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"
        mock_parsed_url.query = None

        success_response = GeminiSuccessResult(
            content="Hello",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=5,
            requestInfo={},
        )

        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = mock_parsed_url
            mock_fetch.return_value = success_response

            result = await client.fetch("gemini://example.com/")

            assert result == success_response
            assert (
                client._get_cached_response("gemini://example.com/") == success_response
            )


class TestGeminiClientFetchContent:
    """Test GeminiClient _fetch_content method."""

    @pytest.mark.asyncio
    async def test_fetch_content_success(self):
        """Test successful content fetch."""
        client = GeminiClient()

        # Mock parsed URL
        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/test"
        mock_parsed_url.query = "search"

        # Mock TLS connection
        mock_ssl_sock = Mock()
        mock_connection_info = {
            "tls_version": "TLSv1.3",
            "cipher": "TLS_AES_256_GCM_SHA384",
            "cert_fingerprint": "abc123",
        }

        # Mock response
        mock_raw_response = b"20 text/plain\r\nHello, world!"
        mock_parsed_response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="text/plain", body=b"Hello, world!"
        )
        mock_result = GeminiSuccessResult(
            content="Hello, world!",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=13,
            requestInfo={},
        )

        with (
            patch.object(client.tls_client, "connect") as mock_connect,
            patch.object(client.tls_client, "send_data") as mock_send,
            patch.object(client.tls_client, "receive_data") as mock_receive,
            patch.object(client.tls_client, "close") as mock_close,
            patch("gopher_mcp.gemini_client.parse_gemini_response") as mock_parse_resp,
            patch("gopher_mcp.gemini_client.process_gemini_response") as mock_process,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = mock_raw_response
            mock_parse_resp.return_value = mock_parsed_response
            mock_process.return_value = mock_result

            result = await client._fetch_content(mock_parsed_url)

            assert result == mock_result

            # Verify TLS operations. Each address gets its own share of what is
            # LEFT of the deadline, so the timeout is "the whole budget minus
            # the DNS lookup" rather than the configured 30 exactly.
            assert mock_connect.await_count == 1
            args, kwargs = mock_connect.call_args
            assert args == ("example.com", 1965)
            assert kwargs["connect_ip"] == "93.184.216.34"
            assert kwargs["timeout"] == pytest.approx(30.0, abs=1.0)
            mock_send.assert_called_once()
            mock_receive.assert_called_once_with(
                mock_ssl_sock, 1024 * 1024, truncate_at_max=False
            )
            mock_close.assert_called_once_with(mock_ssl_sock)

            # Verify request format
            sent_data = mock_send.call_args[0][1]
            expected_request = b"gemini://example.com/test?search\r\n"
            assert sent_data == expected_request

    @pytest.mark.asyncio
    async def test_fetch_content_brackets_ipv6_host_on_the_wire(self):
        """An IPv6 literal host must be bracketed in the request line sent.

        Per RFC 3986 the address must be ``[..]`` so a server (and any URL
        re-parse) can tell the address colons from a port separator.
        """
        client = GeminiClient()

        mock_parsed_url = Mock()
        mock_parsed_url.host = "2606:4700:4700::1111"  # globally routable IPv6
        mock_parsed_url.port = 1966
        mock_parsed_url.path = "/p"
        mock_parsed_url.query = ""

        mock_connection_info = {"cert_fingerprint": "abc123"}
        mock_result = GeminiSuccessResult(
            content="ok",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=2,
            requestInfo={},
        )
        with (
            patch.object(client.tls_client, "connect") as mock_connect,
            patch.object(client.tls_client, "send_data") as mock_send,
            patch.object(client.tls_client, "receive_data") as mock_receive,
            patch.object(client.tls_client, "close"),
            patch("gopher_mcp.gemini_client.parse_gemini_response"),
            patch("gopher_mcp.gemini_client.process_gemini_response") as mock_process,
        ):
            mock_connect.return_value = (Mock(), mock_connection_info)
            mock_receive.return_value = b"20 text/plain\r\nok"
            mock_process.return_value = mock_result

            await client._fetch_content(mock_parsed_url)

            sent_data = mock_send.call_args[0][1]
            # The trailing "?" is the empty-but-present query: an empty answer
            # to a status-10/11 prompt must reach the capsule as a query, not as
            # the bare URL it already answered with a 10.
            assert sent_data == b"gemini://[2606:4700:4700::1111]:1966/p?\r\n"

    def test_safe_display_url_brackets_ipv6_host(self):
        """The display/log helper must also bracket IPv6 hosts."""
        parsed = Mock()
        parsed.host = "2001:db8::1"
        parsed.port = 1965
        parsed.path = "/x"
        assert _safe_display_url(parsed) == "gemini://[2001:db8::1]/x"

    @pytest.mark.asyncio
    async def test_send_is_bounded_by_request_deadline(self):
        """A peer that completes the handshake then stops reading must not pin
        the request forever: the send must run under the request deadline, the
        same as the receive does (and as the Gopher transport already does)."""
        client = GeminiClient()
        client.timeout_seconds = 0.05
        client.tofu_manager = None  # isolate from the on-disk trust store

        parsed = Mock()
        parsed.host = "example.com"
        parsed.port = 1965
        parsed.path = "/"
        parsed.query = ""

        async def hanging_send(*args, **kwargs):
            await asyncio.sleep(0.5)  # far longer than the 0.05s deadline

        with (
            patch.object(client.tls_client, "connect") as mock_connect,
            patch.object(client.tls_client, "send_data", side_effect=hanging_send),
            patch.object(client.tls_client, "receive_data"),
            patch.object(client.tls_client, "close"),
            patch("gopher_mcp.gemini_client.parse_gemini_response"),
            patch("gopher_mcp.gemini_client.process_gemini_response"),
        ):
            mock_connect.return_value = (Mock(), {"cert_fingerprint": "abc"})
            with pytest.raises(TimeoutError):
                await client._fetch_content(parsed)

    @pytest.mark.asyncio
    async def test_fetch_content_tls_error(self):
        """Test content fetch with TLS error."""
        client = GeminiClient()

        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"

        with patch.object(client.tls_client, "connect") as mock_connect:
            mock_connect.side_effect = TLSConnectionError("Connection failed")

            # The typed error now propagates (fetch() maps it to TLS_ERROR).
            with pytest.raises(TLSConnectionError, match="Connection failed"):
                await client._fetch_content(mock_parsed_url)

    @pytest.mark.asyncio
    async def test_fetch_content_cleanup_on_error(self):
        """Test that TLS connection is cleaned up on error."""
        client = GeminiClient(tofu_enabled=False)

        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965
        mock_parsed_url.path = "/"
        mock_parsed_url.query = None

        mock_ssl_sock = Mock()

        with (
            patch.object(client.tls_client, "connect") as mock_connect,
            patch.object(client.tls_client, "send_data") as mock_send,
            patch.object(client.tls_client, "close") as mock_close,
        ):
            mock_connect.return_value = (mock_ssl_sock, {})
            mock_send.side_effect = Exception("Send failed")

            with pytest.raises(Exception, match="Send failed"):
                await client._fetch_content(mock_parsed_url)

            # Verify cleanup was called
            mock_close.assert_called_once_with(mock_ssl_sock)


class TestGeminiClientCaching:
    """Test GeminiClient caching functionality."""

    def test_get_cached_response_hit(self):
        """Test cache hit."""
        client = GeminiClient(cache_enabled=True)

        # Add entry to cache
        response = GeminiSuccessResult(
            content="Cached",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=6,
            requestInfo={},
        )
        client._cache_response("gemini://example.com/", response)

        result = client._get_cached_response("gemini://example.com/")
        assert result == response

    def test_get_cached_response_miss(self):
        """Test cache miss."""
        client = GeminiClient(cache_enabled=True)

        result = client._get_cached_response("gemini://example.com/")
        assert result is None

    def test_get_cached_response_disabled(self):
        """Test cache disabled."""
        client = GeminiClient(cache_enabled=False)

        result = client._get_cached_response("gemini://example.com/")
        assert result is None

    def test_zero_ttl_disables_the_cache(self):
        """A zero TTL means every entry is expired the instant it is written, so
        the client must treat it as caching off rather than keep the bookkeeping
        for a cache that can never hit -- the same rule the config layer applies.
        """
        client = GeminiClient(cache_ttl_seconds=0)
        assert client.cache_enabled is False

        response = GeminiSuccessResult(
            content="Cached",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=6,
            requestInfo={},
        )
        client._cache_response("gemini://example.com/", response)
        assert len(client._cache) == 0

    def test_cache_response_eviction(self):
        """Test cache eviction when full."""
        client = GeminiClient(cache_enabled=True, max_cache_entries=2)

        # Fill cache
        response1 = GeminiSuccessResult(
            content="1",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=1,
            requestInfo={},
        )
        response2 = GeminiSuccessResult(
            content="2",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=1,
            requestInfo={},
        )
        response3 = GeminiSuccessResult(
            content="3",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=1,
            requestInfo={},
        )

        client._cache_response("url1", response1)
        client._cache_response("url2", response2)
        client._cache_response("url3", response3)  # Should evict oldest

        assert len(client._cache) == 2
        assert client._get_cached_response("url1") is None  # Evicted
        assert client._get_cached_response("url2") == response2
        assert client._get_cached_response("url3") == response3

    @pytest.mark.asyncio
    async def test_close(self):
        """Test client cleanup."""
        client = GeminiClient()

        # Add some cache entries
        response = GeminiSuccessResult(
            content="test",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=4,
            requestInfo={},
        )
        client._cache_response("url", response)

        await client.close()

        assert len(client._cache) == 0


class TestGeminiClientCacheExpiry:
    """Test cache expiry functionality."""

    def test_cache_expiry_and_cleanup(self):
        """Test that expired cache entries are cleaned up."""
        client = GeminiClient(cache_ttl_seconds=1)

        response = GeminiSuccessResult(
            content="test",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=4,
            requestInfo={},
        )

        # Cache a response
        client._cache_response("test_url", response)
        assert len(client._cache) == 1

        # Mock time to simulate expiry
        with patch("time.time", return_value=time.time() + 2):
            # This should trigger cache cleanup
            cached = client._get_cached_response("test_url")
            assert cached is None
            assert len(client._cache) == 0

    def test_disabled_caching_early_return(self):
        """Test that disabled caching returns early."""
        client = GeminiClient(cache_enabled=False)

        response = GeminiSuccessResult(
            content="test",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=4,
            requestInfo={},
        )

        # This should return early and not cache anything
        client._cache_response("test_url", response)
        assert len(client._cache) == 0


class TestGeminiClientManagerErrors:
    """Test error cases when managers are not enabled."""

    def test_tofu_methods_when_disabled(self):
        """Test TOFU methods raise errors when TOFU is disabled."""
        client = GeminiClient(tofu_enabled=False)

        with pytest.raises(ValueError, match="TOFU is not enabled"):
            client.update_tofu_certificate("example.com", 1965, "fingerprint")

        with pytest.raises(ValueError, match="TOFU is not enabled"):
            client.remove_tofu_certificate("example.com", 1965)

        with pytest.raises(ValueError, match="TOFU is not enabled"):
            client.list_tofu_certificates()

    def test_client_cert_methods_when_disabled(self):
        """Test client certificate methods raise errors when disabled."""
        client = GeminiClient(client_certs_enabled=False)

        with pytest.raises(ValueError, match="Client certificates are not enabled"):
            client.generate_client_certificate("example.com")

        with pytest.raises(ValueError, match="Client certificates are not enabled"):
            client.get_client_certificate_for_scope("example.com")

        with pytest.raises(ValueError, match="Client certificates are not enabled"):
            client.list_client_certificates()

        with pytest.raises(ValueError, match="Client certificates are not enabled"):
            client.remove_client_certificate("example.com")


class TestGeminiClientAdvancedFeatures:
    """Test advanced client features."""

    @pytest.mark.asyncio
    async def test_fetch_with_non_standard_port(self):
        """Test fetching with non-standard port in URL."""
        client = GeminiClient(respect_robots_txt=False)

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_response = GeminiSuccessResult(
                content="test",
                mimeType=GeminiMimeType(type="text", subtype="plain"),
                size=4,
                requestInfo={},
            )
            mock_fetch.return_value = mock_response

            # This should trigger the non-standard port handling (line 269)
            result = await client.fetch("gemini://example.com:7070/test")
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_fetch_with_client_certificate(self):
        """A scoped client certificate is used for the fetch, and the fetch
        succeeds.

        The cert/key are REAL files and the cert-bound TLS client's SSL context
        is really built, so swapping the cert and key arguments (or falling back
        to the shared default client) fails here. Patching the default client's
        connect proved nothing: with cert paths present _fetch_content switches
        to a cert-bound client whose connect was never mocked, so the fetch
        actually failed and the assertion only checked a mock.
        """
        client = GeminiClient(
            tofu_enabled=False,
            client_certs_enabled=True,
            cache_enabled=False,
            respect_robots_txt=False,
        )
        cert_path, key_path = client.generate_client_certificate(
            "example.com", 1965, "/test"
        )

        cert_bound = client._tls_client_for_cert(cert_path, key_path)
        assert cert_bound is not client.tls_client
        assert cert_bound.config.client_cert_path == cert_path
        # Builds a real context from the real PEMs (load_cert_chain).
        assert cert_bound.ssl_context is not None

        cert_bound.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(_reader_conn(b"20 text/plain\r\nmembers only"), {})
        )
        cert_bound.send_data = AsyncMock()  # type: ignore[method-assign]
        cert_bound.close = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.connect = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.com/test")

        assert isinstance(result, GeminiSuccessResult)
        assert result.content == "members only"
        cert_bound.connect.assert_awaited_once()
        client.tls_client.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_with_tofu_warning(self):
        """A TOFU warning reaches the caller via request_info['tofu_warning'].

        Asserting only that the validator was called left the propagation itself
        unpinned: deleting it passed the whole suite.
        """
        client = GeminiClient(
            tofu_enabled=True,
            cache_enabled=False,
            respect_robots_txt=False,
        )

        with patch.object(client.tofu_manager, "validate_certificate") as mock_validate:
            mock_validate.return_value = (True, "Certificate changed")

            client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
                return_value=(
                    _reader_conn(b"20 text/plain\r\ntest content"),
                    {"cert_fingerprint": "test_fp", "tls_version": "TLSv1.3"},
                )
            )
            client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
            client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

            result = await client.fetch("gemini://example.com/test")

        mock_validate.assert_called_once()
        assert isinstance(result, GeminiSuccessResult)
        assert result.request_info["tofu_warning"] == "Certificate changed"
        assert result.request_info["tls_version"] == "TLSv1.3"

    @pytest.mark.asyncio
    async def test_fetch_with_tofu_validation_error(self):
        """Test fetching with TOFU validation error."""
        client = GeminiClient(tofu_enabled=True, respect_robots_txt=False)

        with patch.object(client.tofu_manager, "validate_certificate") as mock_validate:
            mock_validate.side_effect = TOFUValidationError(
                "Certificate validation failed"
            )

            with patch.object(client.tls_client, "connect") as mock_connect:
                mock_connect.return_value = (Mock(), {"cert_fingerprint": "test_fp"})

                with patch.object(client.tls_client, "close") as _mock_close:
                    result = await client.fetch("gemini://example.com/test")

                    # Should return a distinct, sanitized certificate error
                    assert isinstance(result, GeminiErrorResult)
                    assert result.error["code"] == "CERTIFICATE_CHANGED"
                    assert "TOFU" in result.error["message"]


class TestSensitiveInputRedaction:
    """A status-10/11 input answer is percent-encoded into the query string and
    may be a secret (status 11 = SENSITIVE_INPUT). The client must not reflect
    that query back to the caller (requestInfo) or write it to logs, matching
    the deliberate sanitization already applied to INFO/DEBUG log sites.
    """

    SECRET = "hunter2-secret-answer"

    def _client(self, **kw):
        defaults = {
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "respect_robots_txt": False,
        }
        defaults.update(kw)
        return GeminiClient(**defaults)

    @pytest.mark.asyncio
    async def test_fetch_request_info_omits_query(self):
        from gopher_mcp.models import GeminiMimeType, GeminiSuccessResult, GeminiURL

        client = self._client(cache_enabled=False)
        parsed = GeminiURL(
            host="example.org", port=1965, path="/login", query=self.SECRET
        )
        success = GeminiSuccessResult(
            content="ok",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=2,
            requestInfo={},
        )
        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url", return_value=parsed),
            patch.object(client, "_fetch_content", AsyncMock(return_value=success)),
        ):
            result = await client.fetch(f"gemini://example.org/login?{self.SECRET}")

        ri = result.request_info
        assert self.SECRET not in str(ri)
        assert ri.get("query") is None
        assert "?" not in ri["url"]
        assert ri.get("has_query") is True

    @pytest.mark.asyncio
    async def test_error_result_redacts_query_in_result_and_log(self):
        from structlog.testing import capture_logs

        client = self._client(cache_enabled=False)
        url = f"gemini://example.org/login?{self.SECRET}"
        with capture_logs() as logs:
            result = client._error_result(url, "TLS_ERROR", "failed", Exception("boom"))

        assert self.SECRET not in str(result.request_info)
        assert all(self.SECRET not in str(entry) for entry in logs)

    @pytest.mark.asyncio
    async def test_query_bearing_response_is_not_cached(self):
        from gopher_mcp.models import GeminiMimeType, GeminiSuccessResult, GeminiURL

        client = self._client(cache_enabled=True)
        parsed = GeminiURL(host="example.org", port=1965, path="/s", query=self.SECRET)
        success = GeminiSuccessResult(
            content="ok",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=2,
            requestInfo={},
        )
        with (
            patch("gopher_mcp.gemini_client.parse_gemini_url", return_value=parsed),
            patch.object(client, "_fetch_content", AsyncMock(return_value=success)),
        ):
            await client.fetch(f"gemini://example.org/s?{self.SECRET}")

        # The answer-bearing query must not be retained in any cache key.
        assert all(self.SECRET not in key for key in client._cache)


class TestEmptyAllowlistDenies:
    """An explicitly empty allowlist admits nothing.

    ``set(allowed_hosts) if allowed_hosts else None`` collapsed ``[]`` to "no
    allowlist configured", so a caller who deliberately locked the client down
    got NO host restriction at all. ``allowed_ports`` in ssrf.validate_target
    already behaves this way.
    """

    def _url(self, host: str):
        from gopher_mcp.models import GeminiURL

        return GeminiURL(host=host, port=1965, path="/", query=None)

    def test_empty_list_blocks_every_host(self):
        client = GeminiClient(
            tofu_enabled=False, client_certs_enabled=False, allowed_hosts=[]
        )
        assert client.allowed_hosts == set()
        with pytest.raises(ValueError, match="Host not allowed"):
            client._validate_security(self._url("example.com"))

    def test_none_still_allows_every_host(self):
        client = GeminiClient(
            tofu_enabled=False, client_certs_enabled=False, allowed_hosts=None
        )
        assert client.allowed_hosts is None
        client._validate_security(self._url("example.com"))

    def test_allowlist_is_normalized_once_at_construction(self):
        """Normalizing per request rebuilt the set on every fetch even though
        the allowlist is fixed at construction."""
        client = GeminiClient(
            tofu_enabled=False,
            client_certs_enabled=False,
            allowed_hosts=["Example.COM."],
        )
        assert client.allowed_hosts == {"example.com"}
        client._validate_security(self._url("EXAMPLE.com"))


def _reader_conn(payload: bytes):
    """A TLSConnection over a real StreamReader preloaded with ``payload``."""
    from gopher_mcp.gemini_tls import TLSConnection

    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    reader.feed_eof()
    return TLSConnection(reader=reader, writer=Mock())


class TestOverallRequestDeadline:
    """``timeout_seconds`` is a budget for the whole exchange, not per phase."""

    @pytest.mark.asyncio
    async def test_multi_phase_stall_is_bounded_by_one_deadline(self):
        """DNS, connect, send and receive each used to get their own full-length
        wait_for, so a tarpit answering every phase just under the limit held a
        tool call for several multiples of the configured timeout."""
        client = GeminiClient(
            respect_robots_txt=False,
            timeout_seconds=0.3,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
        )

        async def stalling_connect(*args, **kwargs):
            await asyncio.sleep(0.25)
            return Mock(), {"cert_fingerprint": "x"}

        async def stalling_send(*args, **kwargs):
            await asyncio.sleep(0.25)

        async def stalling_receive(*args, **kwargs):
            await asyncio.sleep(0.25)
            return b"20 text/plain\r\nhi"

        client.tls_client.connect = stalling_connect  # type: ignore[method-assign]
        client.tls_client.send_data = stalling_send  # type: ignore[method-assign]
        client.tls_client.receive_data = stalling_receive  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await client.fetch("gemini://example.org/")
        elapsed = loop.time() - started

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        assert "timed out" in result.error["message"].lower()
        # Three 0.25s phases used to complete happily inside three 0.3s budgets.
        assert elapsed < 0.3 * 2

    @pytest.mark.asyncio
    async def test_robots_probe_shares_the_request_budget(self):
        """The robots gate runs the same multi-phase exchange as the fetch it
        guards, so a tarpit host could otherwise spend the whole configured
        timeout twice in one call."""
        client = GeminiClient(
            timeout_seconds=0.5,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
            requests_per_minute=0,
            respect_robots_txt=True,
        )

        bodies = [
            b"20 text/plain\r\nUser-agent: *\nDisallow:\n",
            b"20 text/plain\r\nhi",
        ]

        # Comfortably inside one budget, so the robots probe itself succeeds and
        # the fetch it guards is left with only the remainder.
        async def stalling_connect(*args, **kwargs):
            await asyncio.sleep(0.3)
            return _reader_conn(bodies.pop(0)), {"cert_fingerprint": "x"}

        client.tls_client.connect = stalling_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await client.fetch("gemini://example.org/page")
        elapsed = loop.time() - started

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        assert "timed out" in result.error["message"].lower()
        # Two independent budgets used to allow 0.3s of robots plus 0.3s of
        # fetch and return a success.
        assert elapsed < 0.5 * 2

    @pytest.mark.asyncio
    async def test_queue_waits_are_not_charged_to_the_deadline(self):
        """Only wire time is charged: a request that waited its turn behind the
        rate limiter must still get the full deadline for the exchange itself."""
        client = GeminiClient(
            respect_robots_txt=False,
            timeout_seconds=0.5,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
            requests_per_minute=240,  # 0.25s spacing between same-host requests
        )
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *a, **k: (_reader_conn(b"20 text/plain\r\nhi"), {})
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        first = await client.fetch("gemini://example.org/a")
        second = await client.fetch("gemini://example.org/b")

        assert not isinstance(first, GeminiErrorResult)
        assert not isinstance(second, GeminiErrorResult)


class TestConnectFailureReporting:
    """Connect-level failures must be reported as what they are."""

    @pytest.mark.asyncio
    async def test_connect_timeout_reports_a_timeout_not_a_tls_error(self):
        """A firewalled host that drops SYNs used to be reported as
        "TLS connection failed", steering the model toward certificate
        diagnostics instead of "host unreachable"."""
        client = GeminiClient(
            respect_robots_txt=False,
            timeout_seconds=0.1,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
        )

        async def never_connects(*args, **kwargs):
            await asyncio.Event().wait()

        with patch("asyncio.open_connection", never_connects):
            result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        assert "timed out" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_connect_fails_over_to_the_next_vetted_address(self):
        """A dual-homed capsule whose first A record is down was unreachable
        over Gemini while the Gopher transport, which iterates, still reached
        it. Every address stays SSRF-vetted."""
        client = GeminiClient(
            respect_robots_txt=False,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
        )
        attempted: list[str] = []

        async def flaky_connect(host, port, timeout=None, *, connect_ip=None):
            attempted.append(connect_ip)
            if connect_ip == "93.184.216.34":
                raise TLSConnectionError("Connection refused by example.org:1965")
            return _reader_conn(b"20 text/plain\r\nhi"), {}

        client.tls_client.connect = flaky_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gemini_client.validate_target",
            AsyncMock(
                return_value=["2606:2800:220::1", "93.184.216.34", "93.184.216.35"]
            ),
        ):
            result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiSuccessResult)
        # IPv4 first (the historical behaviour was AF_INET-only), but every
        # vetted address is tried before giving up.
        assert attempted == ["93.184.216.34", "93.184.216.35"]

    @pytest.mark.asyncio
    async def test_all_addresses_failing_surfaces_the_last_error(self):
        client = GeminiClient(
            respect_robots_txt=False,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
        )
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=TLSConnectionError("Connection refused by example.org:1965")
        )
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gemini_client.validate_target",
            AsyncMock(return_value=["93.184.216.34", "93.184.216.35"]),
        ):
            result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "TLS_ERROR"
        assert client.tls_client.connect.await_count == 2


class TestTofuOffTheEventLoop:
    """TOFU persistence (flock + full store re-read + two fsyncs) must not run
    on the event loop: a batch of previously-unseen hosts would otherwise stall
    every other in-flight request, and a wedged lock holder would freeze the
    whole process."""

    @pytest.mark.asyncio
    async def test_blocking_validation_does_not_stall_the_loop(self):
        client = GeminiClient(
            cache_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
        )
        assert client.tofu_manager is not None

        def blocking_validate(*args, **kwargs):
            time.sleep(0.2)  # stands in for the lock + re-read + fsync cycle
            return True, None

        client.tofu_manager.validate_certificate = blocking_validate  # type: ignore[method-assign]
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(
                _reader_conn(b"20 text/plain\r\nhi"),
                {"cert_fingerprint": "x"},
            )
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.005)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            result = await client.fetch("gemini://example.org/")
        finally:
            task.cancel()

        assert not isinstance(result, GeminiErrorResult)
        # On the loop the ticker got no chance to run at all during the stall.
        assert ticks > 5

    @pytest.mark.asyncio
    async def test_unlockable_store_reports_its_own_error_code(self):
        """Distinct from a fingerprint mismatch: the certificate was never in
        question, the pin just could not be recorded."""
        from gopher_mcp.tofu import TOFUStorageError

        client = GeminiClient(
            cache_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
        )
        assert client.tofu_manager is not None
        client.tofu_manager.validate_certificate = Mock(  # type: ignore[method-assign]
            side_effect=TOFUStorageError("Could not lock the TOFU trust store at /x")
        )
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(Mock(), {"cert_fingerprint": "x"})
        )
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "CERTIFICATE_STORE_UNAVAILABLE"
        # The store path stays in the log, not in the reply.
        assert "/x" not in result.error["message"]
        # A store that is merely unwritable reaches the same code, so the message
        # must not assert the lock-contention cause; and since the caller cannot
        # see the path, it names the setting that chooses it.
        message = result.error["message"]
        assert "not writable" in message
        assert "GEMINI_TOFU_STORAGE_PATH" in message

    @pytest.mark.asyncio
    async def test_not_yet_valid_cert_is_not_reported_as_expired(self):
        """TOFUNotYetValidError subclasses TOFUExpiredError, so its handler must
        come first -- otherwise a certificate presented before its notBefore is
        reported as CERTIFICATE_EXPIRED, the opposite of what happened, and the
        message ("not yet valid") contradicts its own code."""
        with tempfile.TemporaryDirectory() as d:
            client = GeminiClient(
                cache_enabled=False,
                client_certs_enabled=False,
                respect_robots_txt=False,
                tofu_storage_path=str(Path(d) / "tofu.json"),
            )
            assert client.tofu_manager is not None

            # Well beyond NOT_BEFORE_SKEW_SECONDS, so this is a real refusal
            # rather than the clock-skew grace the store deliberately allows.
            client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
                return_value=(
                    Mock(),
                    {
                        "cert_fingerprint": "sha256:beef",
                        "peer_cert_info": {
                            "not_before_timestamp": time.time() + 86400,
                        },
                    },
                )
            )
            client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
            client.tls_client.receive_data = AsyncMock()  # type: ignore[method-assign]
            client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

            result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "CERTIFICATE_NOT_YET_VALID"
        assert "not yet valid" in result.error["message"]
        client.tls_client.send_data.assert_not_awaited()


class TestGeminiRobotsGate:
    """The Gemini robots gate fails closed, so every way it can decline matters."""

    def _client(self, **kw):
        defaults = {
            "cache_enabled": False,
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "requests_per_minute": 0,
            "respect_robots_txt": True,
        }
        defaults.update(kw)
        return GeminiClient(**defaults)

    @pytest.mark.asyncio
    async def test_ssrf_block_is_not_reported_as_a_robots_failure(self):
        """An SSRFError is a client-side policy refusal, not the "server or
        network error" RFC 9309 s2.3.1.4 contemplates -- folding it into
        RobotsUnavailable told the model to disable robots checking for a host
        the SSRF guard blocks either way."""
        client = self._client()

        # blocked.example resolves to 169.254.169.254 (cloud metadata).
        result = await client.fetch("gemini://blocked.example/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "BLOCKED"

    @pytest.mark.asyncio
    async def test_transport_failure_still_fails_closed(self):
        """The deliberate fail-closed behaviour for a real transport failure
        must survive letting SSRFError through."""
        client = self._client()
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=TLSConnectionError("TLS handshake failed")
        )
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiErrorResult)
        # Fails closed, but as ROBOTS_UNAVAILABLE: the capsule never answered,
        # so it cannot have disallowed anything.
        assert result.error["code"] == "ROBOTS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_oversize_robots_is_truncated_and_parsed_not_denied(self):
        """Past the cap the read used to RAISE, which the fail-closed gate turned
        into a permanent denial -- and since an unavailable policy is never
        cached, every later request re-downloaded and re-denied forever."""
        client = self._client(max_response_size=1024)
        oversize = b"20 text/plain\r\n" + b"# padding comment\n" * 500

        bodies = [oversize, b"20 text/plain\r\nhello"]

        async def fake_connect(*args, **kwargs):
            return _reader_conn(bodies.pop(0)), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiSuccessResult)
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_truncated_robots_drops_the_incomplete_final_line(self):
        """Half a Disallow must not be applied as if it were a whole one."""
        header = b"20 text/plain\r\n"
        body = b"User-agent: *\nDisallow: /private/\nDisallow: /secr"
        cap = len(header) + len(body)
        client = self._client(max_response_size=cap)

        async def fake_connect(*args, **kwargs):
            return _reader_conn(header + body + b"et/\nDisallow: /more\n"), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        text = await client._fetch_robots("example.org", 1965)

        assert text == "User-agent: *\nDisallow: /private/\n"

    @pytest.mark.asyncio
    async def test_non_policy_statuses_report_no_policy(self):
        """A redirect, an input prompt or a certificate request is not a policy
        we can apply, so nothing is disallowed -- and the gate caches that
        "no policy" answer for the full 24h TTL."""
        from gopher_mcp.models import GeminiInputResult

        client = self._client()
        redirect = GeminiRedirectResult(
            newUrl="gemini://example.org/robots.txt/",
            isPermanent=False,
            requestInfo={},
        )
        prompt = GeminiInputResult(
            prompt="who are you?", sensitive=False, requestInfo={}
        )

        for response in (redirect, prompt):
            with patch.object(
                client, "_fetch_content", AsyncMock(return_value=response)
            ):
                assert await client._fetch_robots("example.org", 1965) is None

    @pytest.mark.asyncio
    async def test_disallow_message_does_not_tell_the_model_to_turn_robots_off(self):
        """The tool result is read by the model, not the operator. Its single
        actionable sentence used to be an unconditional "set
        GEMINI_RESPECT_ROBOTS_TXT=false", which contradicts the shipped
        AI-assistant guide ("do not suggest disabling robots checking unless the
        user has said they operate the host")."""
        client = self._client()

        async def fake_connect(*args, **kwargs):
            return _reader_conn(b"20 text/plain\r\nUser-agent: *\nDisallow: /\n"), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        message = result.error["message"]
        # The operator's decision and the correct next step come first...
        assert "operator's decision" in message
        assert "do not retry" in message
        assert "Tell the user the resource is excluded" in message
        # ...and the override is still named, but only under its condition.
        assert "GEMINI_RESPECT_ROBOTS_TXT=false" in message
        assert "a host the user has said they operate" in message

    @pytest.mark.asyncio
    async def test_probe_and_fetch_pay_one_rate_limit_token(self):
        """The probe and the fetch it guards are one user request to one
        capsule. Charging both made every first fetch to a host sleep a full
        interval -- a second, with the shipped defaults -- before anything could
        be sent."""
        client = self._client(requests_per_minute=60)
        waits: list[float] = []

        async def record(seconds):
            waits.append(seconds)

        client._rate_limiter._sleep = record  # type: ignore[assignment]

        bodies = [b"20 text/plain\r\n", b"20 text/plain\r\nhello"]

        async def fake_connect(*args, **kwargs):
            return _reader_conn(bodies.pop(0)), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiSuccessResult)
        assert waits == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("respect_robots_txt", [True, False])
    async def test_every_fetch_pays_exactly_one_rate_limit_token(
        self, respect_robots_txt
    ):
        """One acquire per fetch, on both robots paths.

        With robots checking on -- the default -- the probe's acquire in
        ``_fetch_robots`` is the *only* throttle: ``_bounded_fetch`` sees the
        probe's credit and returns before the base class's own acquire. Zero
        awaits means per-host throttling is silently gone; two means the
        double-charge the probe credit exists to prevent. The sibling assertion
        for Gopher lives in tests/test_gopher_client.py.
        """
        client = self._client(respect_robots_txt=respect_robots_txt)
        client._rate_limiter.acquire = AsyncMock()  # type: ignore[method-assign]

        bodies = [b"20 text/plain\r\n", b"20 text/plain\r\nhello"]
        if not respect_robots_txt:
            bodies.pop(0)

        async def fake_connect(*args, **kwargs):
            return _reader_conn(bodies.pop(0)), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiSuccessResult)
        client._rate_limiter.acquire.assert_awaited_once_with("example.org")

    @pytest.mark.asyncio
    async def test_probe_and_fetch_resolve_the_host_once(self):
        """``ssrf.resolve_host`` caches nothing, so the probe's vetted addresses
        are handed to the fetch rather than looked up a second time."""
        client = self._client(requests_per_minute=0)
        resolver = AsyncMock(return_value=["93.184.216.34"])

        bodies = [b"20 text/plain\r\n", b"20 text/plain\r\nhello"]

        async def fake_connect(*args, **kwargs):
            return _reader_conn(bodies.pop(0)), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch("gopher_mcp.gemini_client.validate_target", resolver):
            result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiSuccessResult)
        assert resolver.await_count == 1

    @pytest.mark.asyncio
    async def test_a_later_fetch_does_not_inherit_the_first_probe_credit(self):
        """The credit is a ContextVar, so it outlives the fetch that set it
        unless it is reset -- a second fetch must resolve for itself."""
        client = self._client(requests_per_minute=0)
        resolver = AsyncMock(return_value=["93.184.216.34"])

        async def fake_connect(*args, **kwargs):
            return _reader_conn(b"20 text/plain\r\nhello"), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch("gopher_mcp.gemini_client.validate_target", resolver):
            await client.fetch("gemini://example.org/page")
            before = resolver.await_count
            await client.fetch("gemini://example.org/other")

        # The robots policy is cached after the first call, so the second call
        # runs no probe and must pay for exactly one lookup of its own.
        assert resolver.await_count == before + 1


class TestClientCertificateExposure:
    """A client certificate is an identity; the payload must say when it leaked."""

    def _client(self, **kw):
        defaults = {
            "cache_enabled": False,
            "tofu_enabled": False,
            "client_certs_enabled": True,
            "requests_per_minute": 0,
            "respect_robots_txt": False,
        }
        defaults.update(kw)
        return GeminiClient(**defaults)

    async def _fetch_over(self, client, tls_version):
        cert_path, key_path = client.generate_client_certificate(
            "example.com", 1965, "/test"
        )
        cert_bound = client._tls_client_for_cert(cert_path, key_path)
        cert_bound.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(
                _reader_conn(b"20 text/plain\r\nmembers only"),
                {"tls_version": tls_version},
            )
        )
        cert_bound.send_data = AsyncMock()  # type: ignore[method-assign]
        cert_bound.close = AsyncMock()  # type: ignore[method-assign]
        return await client.fetch("gemini://example.com/test")

    @pytest.mark.asyncio
    async def test_tls_12_flags_the_certificate_as_sent_in_the_clear(self):
        """TLS 1.2 sends client certificates unencrypted, so any passive
        observer learns the user's persistent identity for that scope. The
        Gemini specification makes warning about that a client SHOULD."""
        client = self._client()

        result = await self._fetch_over(client, "TLSv1.2")

        assert isinstance(result, GeminiSuccessResult)
        warning = result.request_info["client_cert_warning"]
        assert "in the clear" in warning
        assert "TLS 1.2" in warning

    @pytest.mark.asyncio
    async def test_tls_13_carries_no_such_warning(self):
        client = self._client()

        result = await self._fetch_over(client, "TLSv1.3")

        assert isinstance(result, GeminiSuccessResult)
        assert "client_cert_warning" not in result.request_info

    @pytest.mark.asyncio
    async def test_a_certless_tls_12_fetch_carries_no_warning(self):
        """The warning is about the identity, not about the TLS version."""
        client = self._client(client_certs_enabled=False)
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(
                _reader_conn(b"20 text/plain\r\nhi"),
                {"tls_version": "TLSv1.2"},
            )
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.com/test")

        assert isinstance(result, GeminiSuccessResult)
        assert "client_cert_warning" not in result.request_info

    def test_the_pin_ordering_exposure_is_documented(self):
        """The certificate is presented during the handshake, which completes
        before the TOFU pin can be checked -- so a rogue server collects the
        identity even though the request is then withheld. Closing that window
        costs an extra round trip; the exposure is documented instead, and this
        pins that the note is actually there for a reader of the code."""
        doc = GeminiClient._fetch_content.__doc__ or ""

        assert "before" in doc
        assert "validate_certificate" in doc
        assert "identity disclosure has happened" in doc


class TestBlackHoledAddressFailover:
    """Hosts that are down overwhelmingly DROP SYNs rather than refusing them."""

    def _client(self, **kw):
        defaults = {
            "cache_enabled": False,
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "requests_per_minute": 0,
            "respect_robots_txt": False,
            "timeout_seconds": 0.4,
        }
        defaults.update(kw)
        return GeminiClient(**defaults)

    @pytest.mark.asyncio
    async def test_a_dropped_syn_advances_to_the_next_address(self):
        """The connect loop caught only TLSConnectionError while a dropped SYN
        raises a bare TimeoutError, and every attempt shared one deadline -- so
        the first black hole burned the whole budget and the remaining vetted
        addresses were never tried, which is the only case the fail-over exists
        for."""
        client = self._client()
        attempted: list[str] = []

        async def flaky_connect(host, port, timeout=None, *, connect_ip=None):
            attempted.append(connect_ip)
            if connect_ip == "203.0.113.1":
                await asyncio.sleep(timeout)
                raise TimeoutError(f"Connection to {host}:{port} timed out")
            return _reader_conn(b"20 text/plain\r\nhi"), {}

        client.tls_client.connect = flaky_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gemini_client.validate_target",
            AsyncMock(return_value=["203.0.113.1", "93.184.216.34"]),
        ):
            result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiSuccessResult)
        assert attempted == ["203.0.113.1", "93.184.216.34"]

    @pytest.mark.asyncio
    async def test_each_attempt_gets_a_share_of_what_is_left(self):
        """A single address still gets the whole remaining budget; two split it,
        so one black hole cannot consume the other's chance."""
        client = self._client()
        timeouts: list[float] = []

        async def refusing_connect(host, port, timeout=None, *, connect_ip=None):
            timeouts.append(timeout)
            raise TLSConnectionError("Connection refused")

        client.tls_client.connect = refusing_connect  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gemini_client.validate_target",
            AsyncMock(return_value=["203.0.113.1", "93.184.216.34"]),
        ):
            await client.fetch("gemini://example.org/")

        assert len(timeouts) == 2
        assert timeouts[0] == pytest.approx(0.2, abs=0.05)

    @pytest.mark.asyncio
    async def test_every_address_black_holed_is_still_a_timeout(self):
        """The deliberate "a timeout is reported AS a timeout" decision in the
        transport must survive the fail-over."""
        client = self._client()

        async def never_connects(host, port, timeout=None, *, connect_ip=None):
            await asyncio.sleep(timeout)
            raise TimeoutError("timed out")

        client.tls_client.connect = never_connects  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gemini_client.validate_target",
            AsyncMock(return_value=["203.0.113.1", "203.0.113.2"]),
        ):
            result = await client.fetch("gemini://example.org/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        assert "timed out" in result.error["message"].lower()


class TestSlowDownIsAnswerNotASleep:
    """After a status-44, later fetches must not sit in the backoff."""

    def _client(self, **kw):
        defaults = {
            "cache_enabled": False,
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "respect_robots_txt": False,
            "requests_per_minute": 0,
            "timeout_seconds": 5.0,
        }
        defaults.update(kw)
        return GeminiClient(**defaults)

    @pytest.mark.asyncio
    async def test_a_long_backoff_returns_a_structured_error(self):
        """A capsule naming 3600 seconds parked every later fetch for the
        300-second clamp inside the tool call -- the MCP client's own timeout
        fires long before that, and in a batch the sleeping call also ties up
        one of the five concurrency slots."""
        client = self._client()
        client._rate_limiter._sleep = AsyncMock()  # type: ignore[assignment]
        client._rate_limiter.penalize("example.org", 3600)

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "SLOW_DOWN"
        assert result.error["retry_after_seconds"] == pytest.approx(300.0, abs=1.0)
        assert "Nothing was sent" in result.error["message"]
        client._rate_limiter._sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_short_backoff_is_still_slept_through(self):
        """Ordinary sub-timeout spacing keeps sleeping: the point is the
        ceiling, not the throttle."""
        client = self._client()
        slept: list[float] = []

        async def record(seconds):
            slept.append(seconds)

        client._rate_limiter._sleep = record  # type: ignore[assignment]
        client._rate_limiter.penalize("example.org", 1.0)
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(_reader_conn(b"20 text/plain\r\nhi"), {})
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.org/page")

        assert isinstance(result, GeminiSuccessResult)
        assert slept and slept[0] == pytest.approx(1.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_the_refused_request_does_not_extend_the_backoff(self):
        """A request that never went out must not push the next caller back."""
        client = self._client()
        client._rate_limiter._sleep = AsyncMock()  # type: ignore[assignment]
        client._rate_limiter.penalize("example.org", 3600)
        before = client._rate_limiter._next_allowed["example.org"]

        await client.fetch("gemini://example.org/page")

        assert client._rate_limiter._next_allowed["example.org"] == before


class TestGeminiCacheKeyIsTheWireRequest:
    """Spellings that produce an identical request line share one entry."""

    def _client(self, **kw):
        defaults = {
            "cache_enabled": True,
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "respect_robots_txt": False,
            "requests_per_minute": 0,
        }
        defaults.update(kw)
        return GeminiClient(**defaults)

    @pytest.mark.asyncio
    async def test_equivalent_spellings_share_one_entry(self):
        """The cache exists to spare small capsules repeat traffic; keying on
        the raw string gave "gemini://h", "gemini://h/", an explicit ":1965"
        and a "%2e" segment five entries and five network fetches."""
        client = self._client()
        connects = 0

        async def fake_connect(*args, **kwargs):
            nonlocal connects
            connects += 1
            return _reader_conn(b"20 text/plain\r\nhi"), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        for url in (
            "gemini://example.org",
            "gemini://example.org/",
            "gemini://EXAMPLE.org/a/../",
            "gemini://example.org:1965/",
            "gemini://example.org/%2e/",
        ):
            result = await client.fetch(url)
            assert isinstance(result, GeminiSuccessResult)

        assert connects == 1
        assert len(client._cache) == 1

    @pytest.mark.asyncio
    async def test_different_paths_still_get_their_own_entry(self):
        client = self._client()
        connects = 0

        async def fake_connect(*args, **kwargs):
            nonlocal connects
            connects += 1
            return _reader_conn(b"20 text/plain\r\nhi"), {}

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        await client.fetch("gemini://example.org/a")
        await client.fetch("gemini://example.org/b")

        assert connects == 2
        assert len(client._cache) == 2


class TestFragmentBearingLinksAreFetchable:
    """A gemtext link this server emitted must be one the tool accepts back."""

    @pytest.mark.asyncio
    async def test_a_link_with_an_anchor_round_trips_through_a_fetch(self):
        client = GeminiClient(
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
            requests_per_minute=0,
        )
        sent: list[bytes] = []

        async def fake_connect(*args, **kwargs):
            return _reader_conn(b"20 text/gemini\r\n=> /page#section Anchored"), {}

        async def record_send(conn, data):
            sent.append(data)

        client.tls_client.connect = fake_connect  # type: ignore[method-assign]
        client.tls_client.send_data = record_send  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        first = await client.fetch("gemini://example.org/")
        assert isinstance(first, GeminiGemtextResult)
        link_url = first.document.links[0].url
        assert link_url == "gemini://example.org/page#section"

        # The tool used to refuse the URL it had just handed back, without
        # touching the network, as "URL must not contain fragment".
        second = await client.fetch(link_url)
        assert not isinstance(second, GeminiErrorResult)
        assert sent[-1] == b"gemini://example.org/page\r\n"


class TestTLSConnectFailureDoesNotEchoTheAddress:
    """A failed connect must not report which IP was actually tried."""

    @pytest.mark.asyncio
    async def test_generic_oserror_omits_the_connect_address(self):
        """The refused-connection branch shields the common case, but the
        generic ``except OSError`` used to interpolate the exception itself --
        and asyncio builds every deferred connect failure as
        ``OSError(err, f"Connect call failed {address}")``, so the SSRF-vetted
        resolved IP travelled inside ``strerror`` straight into the message.
        """
        client = GeminiTLSClient(TLSConfig())
        failure = OSError(errno.EHOSTUNREACH, "Connect call failed ('10.1.2.3', 1965)")

        with (
            patch("asyncio.open_connection", side_effect=failure),
            pytest.raises(GeminiConnectionError) as exc_info,
        ):
            await client.connect("example.com", 1965, connect_ip="10.1.2.3")

        message = str(exc_info.value)
        assert "10.1.2.3" not in message
        assert os.strerror(errno.EHOSTUNREACH) in message


class TestGeminiResponseSizeAccessor:
    """Gemini spells the same field ``size``; the accessor hides the split."""

    def test_gemini_reads_the_size_field(self):
        client = GeminiClient()
        response = GeminiSuccessResult(
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            content="hello",
            size=5,
        )
        assert client._response_size(response) == 5

    def test_bodiless_results_report_zero(self):
        client = GeminiClient()
        response = GeminiRedirectResult(status=30, newUrl="gemini://example.org/b")
        assert client._response_size(response) == 0


class TestGeminiOffsetContinuation:
    """A page cut at the render limit must be continuable, not a dead end."""

    BODY = "".join(f"line {i}\n" for i in range(40))

    def _client(self, **kw):
        defaults = {
            "respect_robots_txt": False,
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "requests_per_minute": 0,
            "cache_enabled": False,
            "max_rendered_chars": 45,
        }
        client = GeminiClient(**{**defaults, **kw})
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(Mock(), {"cert_fingerprint": "x"})
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.receive_data = AsyncMock(  # type: ignore[method-assign]
            return_value=b"20 text/gemini\r\n" + self.BODY.encode()
        )
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]
        return client

    @pytest.mark.asyncio
    async def test_gemtext_windows_reassemble_into_the_whole_page(self):
        client = self._client()

        first = await client.fetch("gemini://example.org/")
        assert first.truncated is True
        assert first.total_chars == len(self.BODY)
        # The window is cut back to the last complete line, and next_offset
        # points at that cut -- not at the character budget -- so the windows
        # abut exactly instead of overlapping or dropping a line.
        assert first.raw_content.endswith("\n")
        assert first.next_offset == len(first.raw_content)

        seen = first.raw_content
        offset = first.next_offset
        # Bounded, not `while offset is not None`: a next_offset that stops
        # advancing must fail this one test, not spin until the suite-wide
        # timeout kills the process without a pytest summary.
        for _ in range(20):
            if offset is None:
                break
            window = await client.fetch("gemini://example.org/", offset=offset)
            seen += window.raw_content
            offset = window.next_offset
        else:
            pytest.fail(f"windows never terminated: next_offset stuck at {offset}")

        assert seen == self.BODY

    @pytest.mark.asyncio
    async def test_a_line_longer_than_the_window_is_still_returned_whole(self):
        """A line longer than the whole budget must not vanish.

        There is no complete line to parse, so the document is empty -- but the
        characters are real and ``next_offset`` advances past them, so if the
        window also blanked ``raw_content`` no later offset could ever ask for
        them again. A caller running the documented continuation loop would
        assemble a fragment and have no signal it was not the whole page.
        """
        body = "# short\n" + "X" * 3000 + "\ntail line\n"
        client = self._client(max_rendered_chars=1000)
        client.tls_client.receive_data = AsyncMock(  # type: ignore[method-assign]
            return_value=b"20 text/gemini\r\n" + body.encode()
        )

        seen = ""
        from_payload = ""
        offset: int | None = 0
        for _ in range(20):
            if offset is None:
                break
            window = await client.fetch("gemini://example.org/", offset=offset)
            assert window.total_chars == len(body)
            # What the MODEL receives, not what the object holds: raw_content is
            # exclude=True, so a window can look complete here and still deliver
            # nothing over the wire. That is exactly how the first version of
            # this fix passed its own test while changing nothing for a caller.
            payload = window.model_dump()
            in_payload = "".join(
                line["content"] for line in payload["document"]["lines"]
            )
            if window.next_offset is not None:
                assert in_payload != "", (
                    f"window at offset {offset} delivered no content to the "
                    f"caller but still advanced to {window.next_offset}"
                )
            seen += window.raw_content
            from_payload += in_payload
            offset = window.next_offset
        else:
            pytest.fail(f"windows never terminated: next_offset stuck at {offset}")

        assert seen == body
        # The payload view is the one that matters. A gemtext line does not
        # carry its own terminator, so the comparison is against the body with
        # newlines removed: what must not happen is a character going missing,
        # and before this fix 3000 of them did.
        assert from_payload.replace("\n", "") == body.replace("\n", ""), (
            f"a caller following the documented loop reassembled "
            f"{len(from_payload)} of {len(body.replace(chr(10), ''))} characters"
        )
        assert from_payload.count("X") == 3000

    @pytest.mark.asyncio
    async def test_half_an_over_long_link_line_is_never_parsed_as_a_link(self):
        """Withholding the PARSE is the other half of the fix.

        The span still has to reach the model -- ``next_offset`` advances past
        it, so anything withheld is unreachable forever -- but a truncated
        ``=> url text`` must never arrive as a COMPLETE link pointing at the
        surviving prefix, which is a URL the server never sent.

        So it comes back as a plain text line: the characters are all there and
        nothing carries a target. Asserting an empty document here would pin the
        first, wrong version of this fix, which returned the span only in
        ``raw_content`` -- a field excluded from the payload, so the model
        received nothing at all.
        """
        body = "=> gemini://example.org/" + "a" * 3000 + " real link\n"
        client = self._client(max_rendered_chars=1000)
        client.tls_client.receive_data = AsyncMock(  # type: ignore[method-assign]
            return_value=b"20 text/gemini\r\n" + body.encode()
        )

        result = await client.fetch("gemini://example.org/")

        assert result.raw_content == body[:1000]
        assert result.partial_line is True

        # The characters reach the model, in the payload and not just alongside
        # it: raw_content is exclude=True and never serialized.
        payload = result.model_dump()
        assert "raw_content" not in payload
        assert [line["content"] for line in payload["document"]["lines"]] == [
            body[:1000]
        ]

        # ... and not one of them is presented as a link.
        from gopher_mcp.models import GemtextLineType

        assert result.document.lines[0].type is GemtextLineType.TEXT
        assert result.document.lines[0].link is None
        assert result.document.links == []

    @pytest.mark.asyncio
    async def test_a_plain_text_body_windows_too(self):
        client = self._client()
        client.tls_client.receive_data = AsyncMock(  # type: ignore[method-assign]
            return_value=b"20 text/plain\r\n" + self.BODY.encode()
        )

        result = await client.fetch("gemini://example.org/", offset=45)

        assert isinstance(result, GeminiSuccessResult)
        assert result.content == self.BODY[45:90]
        assert result.total_chars == len(self.BODY)
        assert result.next_offset == 90
        # `size` counts bytes and is NOT an offset: an offset is in characters.
        assert result.size == len(self.BODY.encode())

    @pytest.mark.asyncio
    async def test_a_negative_offset_is_rejected(self):
        client = self._client()

        result = await client.fetch("gemini://example.org/", offset=-1)

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_the_cache_does_not_serve_one_window_for_another(self):
        """The cache stores the rendered window, not the body, so the offset is
        part of the key -- otherwise the second window would be answered with
        the first, silently."""
        client = self._client(cache_enabled=True)

        first = await client.fetch("gemini://example.org/")
        second = await client.fetch("gemini://example.org/", offset=first.next_offset)
        replay = await client.fetch("gemini://example.org/")

        assert second.raw_content != first.raw_content
        assert replay.cached is True
        assert replay.raw_content == first.raw_content
        assert client.tls_client.receive_data.await_count == 2


class TestContinuationCarriesParseState:
    """A continuation window resumes mid-document, so it must resume mid-parse.

    ``parse_gemtext`` classifies from the top of whatever string it is handed.
    A window that starts inside a ``` block, or inside a line, is not the top of
    a document, and parsing it as one inverts the meaning of every line after
    the resume point -- silently, with ``partial_line`` false.
    """

    def _client(self, **kw):
        defaults = {
            "respect_robots_txt": False,
            "tofu_enabled": False,
            "client_certs_enabled": False,
            "requests_per_minute": 0,
            "cache_enabled": False,
            "max_rendered_chars": 1000,
        }
        client = GeminiClient(**{**defaults, **kw})
        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(Mock(), {"cert_fingerprint": "x"})
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]
        return client

    async def _walk(self, client, url="gemini://example.org/"):
        """Return every window of a body, following the documented loop."""
        windows = []
        offset: int | None = 0
        for _ in range(20):
            if offset is None:
                break
            window = await client.fetch(url, offset=offset)
            windows.append(window)
            offset = window.next_offset
        else:
            pytest.fail(f"windows never terminated: next_offset stuck at {offset}")
        return windows

    @pytest.mark.asyncio
    async def test_a_fenced_link_line_is_never_a_link_in_a_later_window(self):
        """The sharper half: no over-long line, no hostile capsule, no flag.

        A ``=>`` inside a ``` block is sample text, not a link. When the block
        straddles the render cap the second window starts inside it, and a
        parser that resets to normal mode reads that sample as a real link,
        resolves it, and puts it in ``document.links`` -- the exact thing the
        continuation protocol promises cannot happen.
        """
        from gopher_mcp.models import GemtextLineType

        fenced_link = "=> gemini://attacker.example/drain-wallet Official portal"
        body = "\n".join(
            ["```"]
            + [f"code line {i}" for i in range(150)]
            + [fenced_link, "```", "real text"]
        )
        client = self._client()
        client.tls_client.receive_data = AsyncMock(  # type: ignore[method-assign]
            return_value=b"20 text/gemini\r\n" + body.encode()
        )

        windows = await self._walk(client)
        assert len(windows) > 1, "test needs a body that actually straddles the cap"

        for i, window in enumerate(windows):
            assert window.document.links == [], (
                f"window {i} fabricated {window.document.links} from a line the "
                f"capsule sent inside a preformat block"
            )

        lines = [line for w in windows for line in w.document.lines]
        fenced = [ln for ln in lines if ln.content == fenced_link]
        assert fenced, "the fenced link line never came back at all"
        assert all(ln.type is GemtextLineType.PREFORMAT for ln in fenced), (
            f"fenced sample text came back typed {[ln.type for ln in fenced]}"
        )

        # ... and the closing fence must still close: a line genuinely outside
        # the block must not be swallowed by an inverted toggle.
        tail = [ln for ln in lines if ln.content == "real text"]
        assert tail and all(ln.type is GemtextLineType.TEXT for ln in tail), (
            f"the line after the closing fence came back typed "
            f"{[ln.type for ln in tail]}"
        )

    @pytest.mark.asyncio
    async def test_the_tail_of_an_over_long_line_is_not_parsed_as_a_line(self):
        """The resume side of the ``partial_line`` fix.

        0.9.0 refuses to parse the window that ends mid-line. The window that
        *starts* mid-line is the other half of the same cut, and it was still
        parsed from the top -- so a ``=>`` sitting just past the cap boundary
        arrives as a complete link whose target the capsule never offered as one.
        """
        from gopher_mcp.models import GemtextLineType

        tail = "=> gemini://attacker.example/drain-wallet Official portal"
        body = "A" * 1000 + tail + "\n"
        client = self._client()
        client.tls_client.receive_data = AsyncMock(  # type: ignore[method-assign]
            return_value=b"20 text/gemini\r\n" + body.encode()
        )

        windows = await self._walk(client)
        assert windows[0].partial_line is True, "test needs the mid-line cut"
        assert len(windows) > 1

        for i, window in enumerate(windows):
            assert window.document.links == [], (
                f"window {i} presented the tail of a text line as link "
                f"{window.document.links}"
            )
        resumed = windows[1].document.lines[0]
        assert resumed.type is GemtextLineType.TEXT
        assert resumed.link is None
