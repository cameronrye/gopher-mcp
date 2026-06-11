"""Tests for Gemini client implementation."""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gopher_mcp.gemini_client import GeminiClient, _safe_display_url
from gopher_mcp.gemini_tls import TLSConfig, TLSConnectionError
from gopher_mcp.models import (
    GeminiErrorResult,
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

    def test_status_44_slow_down_penalizes_host(self):
        """A status-44 SLOW_DOWN backs the host off for the advertised seconds."""
        client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        client._rate_limiter.penalize = Mock()  # type: ignore[method-assign]
        result = GeminiErrorResult(
            error={"code": "TEMPORARY_ERROR", "message": "10", "status": 44},
            requestInfo={},
        )
        client._maybe_honor_slow_down("slow.example", result)
        client._rate_limiter.penalize.assert_called_once_with("slow.example", 10.0)

    def test_non_44_response_does_not_penalize(self):
        client = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        client._rate_limiter.penalize = Mock()  # type: ignore[method-assign]
        result = GeminiErrorResult(
            error={"code": "TEMPORARY_ERROR", "message": "x", "status": 41},
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
        client = GeminiClient()

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
            max_concurrent_requests=2,
            cache_enabled=False,
            tofu_enabled=False,
            client_certs_enabled=False,
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
        client = GeminiClient(client_certs_enabled=False)  # TOFU on by default
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
        client = GeminiClient(cache_enabled=True)

        # Mock cached response
        cached_response = GeminiSuccessResult(
            content="Cached content",
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            size=14,
            requestInfo={},
        )

        with patch.object(client, "_get_cached_response") as mock_get_cache:
            mock_get_cache.return_value = cached_response

            result = await client.fetch("gemini://example.com/")

            assert result == cached_response
            mock_get_cache.assert_called_once_with("gemini://example.com/")

    @pytest.mark.asyncio
    async def test_fetch_error_handling(self):
        """Test fetch error handling."""
        client = GeminiClient()

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

        client = GeminiClient()
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
        client = GeminiClient(allowed_hosts=["allowed.com"])

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
        client = GeminiClient(cache_enabled=True)

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
        client = GeminiClient(cache_enabled=True)

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
        client = GeminiClient(cache_enabled=True)

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

            # Verify TLS operations
            mock_connect.assert_called_once_with(
                "example.com", 1965, timeout=30.0, connect_ip="93.184.216.34"
            )
            mock_send.assert_called_once()
            mock_receive.assert_called_once_with(mock_ssl_sock, 1024 * 1024)
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
            assert sent_data == b"gemini://[2606:4700:4700::1111]:1966/p\r\n"

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
        client = GeminiClient()

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
        """Test fetching with client certificate."""
        client = GeminiClient(client_certs_enabled=True)

        with patch.object(
            client.client_cert_manager, "get_certificate_for_scope"
        ) as mock_get_cert:
            mock_get_cert.return_value = ("/path/to/cert.pem", "/path/to/key.pem")

            with patch.object(client.tls_client, "connect") as mock_connect:
                mock_connect.return_value = (Mock(), {"cert_fingerprint": "test_fp"})

                with patch.object(client.tls_client, "send_data") as _mock_send:
                    with patch.object(
                        client.tls_client, "receive_data"
                    ) as mock_receive:
                        mock_receive.return_value = b"20 text/plain\r\ntest content"

                        with patch.object(client.tls_client, "close") as _mock_close:
                            _result = await client.fetch("gemini://example.com/test")

                            # Verify client certificate was used
                            mock_get_cert.assert_called_once_with(
                                "example.com", 1965, "/test"
                            )

    @pytest.mark.asyncio
    async def test_fetch_with_tofu_warning(self):
        """Test fetching with TOFU warning."""
        client = GeminiClient(tofu_enabled=True)

        with patch.object(client.tofu_manager, "validate_certificate") as mock_validate:
            mock_validate.return_value = (True, "Certificate changed")

            with patch.object(client.tls_client, "connect") as mock_connect:
                mock_connect.return_value = (Mock(), {"cert_fingerprint": "test_fp"})

                with patch.object(client.tls_client, "send_data") as _mock_send:
                    with patch.object(
                        client.tls_client, "receive_data"
                    ) as mock_receive:
                        mock_receive.return_value = b"20 text/plain\r\ntest content"

                        with patch.object(client.tls_client, "close") as _mock_close:
                            _result = await client.fetch("gemini://example.com/test")

                            # Verify TOFU warning was handled
                            mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_with_tofu_validation_error(self):
        """Test fetching with TOFU validation error."""
        client = GeminiClient(tofu_enabled=True)

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
        defaults = {"tofu_enabled": False, "client_certs_enabled": False}
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
