"""Tests for Gemini client implementation."""

from unittest.mock import Mock, patch

import pytest

from src.gopher_mcp.gemini_client import GeminiClient
from src.gopher_mcp.gemini_tls import TLSConfig, TLSConnectionError
from src.gopher_mcp.models import (
    GeminiResponse,
    GeminiStatusCode,
    GeminiSuccessResult,
    GeminiErrorResult,
    GeminiMimeType,
)


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
            patch("src.gopher_mcp.gemini_client.parse_gemini_url") as mock_parse,
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

        with patch("src.gopher_mcp.gemini_client.parse_gemini_url") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid URL")

            result = await client.fetch("invalid://url")

            assert isinstance(result, GeminiErrorResult)
            assert result.error["code"] == "FETCH_ERROR"
            assert "Invalid URL" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_security_violation(self):
        """Test fetch with security violation."""
        client = GeminiClient(allowed_hosts=["allowed.com"])

        mock_parsed_url = Mock()
        mock_parsed_url.host = "forbidden.com"
        mock_parsed_url.port = 1965

        with patch("src.gopher_mcp.gemini_client.parse_gemini_url") as mock_parse:
            mock_parse.return_value = mock_parsed_url

            result = await client.fetch("gemini://forbidden.com/")

            assert isinstance(result, GeminiErrorResult)
            assert "Host not allowed" in result.error["message"]


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
            patch(
                "src.gopher_mcp.gemini_client.parse_gemini_response"
            ) as mock_parse_resp,
            patch(
                "src.gopher_mcp.gemini_client.process_gemini_response"
            ) as mock_process,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = mock_raw_response
            mock_parse_resp.return_value = mock_parsed_response
            mock_process.return_value = mock_result

            result = await client._fetch_content(mock_parsed_url)

            assert result == mock_result

            # Verify TLS operations
            mock_connect.assert_called_once_with("example.com", 1965, timeout=30.0)
            mock_send.assert_called_once()
            mock_receive.assert_called_once_with(mock_ssl_sock, 1024 * 1024)
            mock_close.assert_called_once_with(mock_ssl_sock)

            # Verify request format
            sent_data = mock_send.call_args[0][1]
            expected_request = b"gemini://example.com/test?search\r\n"
            assert sent_data == expected_request

    @pytest.mark.asyncio
    async def test_fetch_content_tls_error(self):
        """Test content fetch with TLS error."""
        client = GeminiClient()

        mock_parsed_url = Mock()
        mock_parsed_url.host = "example.com"
        mock_parsed_url.port = 1965

        with patch.object(client.tls_client, "connect") as mock_connect:
            mock_connect.side_effect = TLSConnectionError("Connection failed")

            with pytest.raises(ValueError, match="TLS connection failed"):
                await client._fetch_content(mock_parsed_url)

    @pytest.mark.asyncio
    async def test_fetch_content_cleanup_on_error(self):
        """Test that TLS connection is cleaned up on error."""
        client = GeminiClient()

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
