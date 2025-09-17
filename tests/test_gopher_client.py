"""Tests for gopher_mcp.gopher_client module."""

import asyncio
import time
from unittest.mock import Mock, patch

import pytest

from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.models import (
    BinaryResult,
    CacheEntry,
    ErrorResult,
    GopherURL,
    MenuResult,
    TextResult,
)


class TestGopherClientInitialization:
    """Test GopherClient initialization and configuration."""

    def test_default_initialization(self):
        """Test GopherClient with default parameters."""
        client = GopherClient()

        assert client.max_response_size == 1024 * 1024  # 1MB
        assert client.timeout_seconds == 30.0
        assert client.cache_enabled is True
        assert client.cache_ttl_seconds == 300
        assert client.max_cache_entries == 1000
        assert client.max_selector_length == 1024
        assert client.max_search_length == 256
        assert client.allowed_hosts is None
        assert client._cache == {}

    def test_custom_initialization(self):
        """Test GopherClient with custom parameters."""
        client = GopherClient(
            max_response_size=2048,
            timeout_seconds=60.0,
            cache_enabled=False,
            cache_ttl_seconds=600,
            max_cache_entries=500,
            allowed_hosts=["example.com", "test.com"],
            max_selector_length=512,
            max_search_length=128,
        )

        assert client.max_response_size == 2048
        assert client.timeout_seconds == 60.0
        assert client.cache_enabled is False
        assert client.cache_ttl_seconds == 600
        assert client.max_cache_entries == 500
        assert client.max_selector_length == 512
        assert client.max_search_length == 128
        assert client.allowed_hosts == {"example.com", "test.com"}


class TestSecurityValidation:
    """Test security validation methods."""

    def test_validate_security_allowed_hosts_pass(self):
        """Test security validation passes for allowed hosts."""
        client = GopherClient(allowed_hosts=["example.com", "test.com"])
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/test", search=None
        )

        # Should not raise an exception
        client._validate_security(parsed_url)

    def test_validate_security_allowed_hosts_fail(self):
        """Test security validation fails for disallowed hosts."""
        client = GopherClient(allowed_hosts=["example.com"])
        parsed_url = GopherURL(
            host="forbidden.com",
            port=70,
            gopherType="1",
            selector="/test",
            search=None,
        )

        with pytest.raises(
            ValueError, match="Host 'forbidden.com' not in allowed hosts list"
        ):
            client._validate_security(parsed_url)

    def test_validate_security_selector_too_long(self):
        """Test security validation fails for overly long selectors."""
        client = GopherClient(max_selector_length=10)
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="1",
            selector="a" * 20,  # Too long
            search=None,
        )

        with pytest.raises(ValueError, match="Selector too long"):
            client._validate_security(parsed_url)

    def test_validate_security_search_too_long(self):
        """Test security validation fails for overly long search queries."""
        client = GopherClient(max_search_length=10)
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",
            selector="/search",
            search="a" * 20,  # Too long
        )

        with pytest.raises(ValueError, match="Search query too long"):
            client._validate_security(parsed_url)

    def test_validate_security_selector_invalid_chars(self):
        """Test security validation fails for selectors with invalid characters."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="1",
            selector="/test\r\nmalicious",
            search=None,
        )

        with pytest.raises(
            ValueError, match="Selector contains invalid control characters"
        ):
            client._validate_security(parsed_url)

    def test_validate_security_search_invalid_chars(self):
        """Test security validation fails for search queries with invalid characters."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",
            selector="/search",
            search="test\r\nmalicious",
        )

        with pytest.raises(
            ValueError, match="Search query contains invalid control characters"
        ):
            client._validate_security(parsed_url)

    def test_validate_security_invalid_port(self):
        """Test security validation fails for invalid port numbers."""
        client = GopherClient()

        # Test with port 0 (invalid)
        parsed_url_low = GopherURL(
            host="example.com",
            port=1,  # Valid port for creation
            gopherType="1",
            selector="/test",
            search=None,
        )
        # Manually set invalid port to test validation
        parsed_url_low.port = 0

        with pytest.raises(ValueError, match="Invalid port number"):
            client._validate_security(parsed_url_low)

        # Test with port > 65535 (invalid)
        parsed_url_high = GopherURL(
            host="example.com",
            port=65535,  # Valid port for creation
            gopherType="1",
            selector="/test",
            search=None,
        )
        # Manually set invalid port to test validation
        parsed_url_high.port = 70000

        with pytest.raises(ValueError, match="Invalid port number"):
            client._validate_security(parsed_url_high)


class TestCacheManagement:
    """Test cache management functionality."""

    def test_get_cached_response_cache_disabled(self):
        """Test getting cached response when cache is disabled."""
        client = GopherClient(cache_enabled=False)
        result = client._get_cached_response("gopher://example.com/1/")
        assert result is None

    def test_get_cached_response_not_found(self):
        """Test getting cached response when URL not in cache."""
        client = GopherClient()
        result = client._get_cached_response("gopher://example.com/1/")
        assert result is None

    def test_get_cached_response_expired(self):
        """Test getting cached response when entry is expired."""
        client = GopherClient()
        url = "gopher://example.com/1/"

        # Add expired entry
        expired_entry = CacheEntry(
            key=url,
            value=MenuResult(items=[]),
            timestamp=time.time() - 1000,  # Old timestamp
            ttl=300,
        )
        client._cache[url] = expired_entry

        result = client._get_cached_response(url)
        assert result is None
        assert url not in client._cache  # Should be removed

    def test_get_cached_response_valid(self):
        """Test getting valid cached response."""
        client = GopherClient()
        url = "gopher://example.com/1/"
        expected_result = MenuResult(items=[])

        # Add valid entry
        entry = CacheEntry(
            key=url, value=expected_result, timestamp=time.time(), ttl=300
        )
        client._cache[url] = entry

        result = client._get_cached_response(url)
        assert result == expected_result

    def test_cache_response_disabled(self):
        """Test caching response when cache is disabled."""
        client = GopherClient(cache_enabled=False)
        response = MenuResult(items=[])

        client._cache_response("gopher://example.com/1/", response)
        assert len(client._cache) == 0

    def test_cache_response_eviction(self):
        """Test cache eviction when max entries reached."""
        client = GopherClient(max_cache_entries=2)

        # Add first entry
        url1 = "gopher://example.com/1/"
        response1 = MenuResult(items=[])
        client._cache_response(url1, response1)

        # Add second entry
        url2 = "gopher://example.com/2/"
        response2 = MenuResult(items=[])
        client._cache_response(url2, response2)

        # Add third entry - should evict oldest
        url3 = "gopher://example.com/3/"
        response3 = MenuResult(items=[])
        client._cache_response(url3, response3)

        assert len(client._cache) == 2
        assert url1 not in client._cache  # Oldest should be evicted
        assert url2 in client._cache
        assert url3 in client._cache


class TestClientCleanup:
    """Test client cleanup functionality."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test client close method."""
        client = GopherClient()

        # Add some cache entries
        client._cache["test1"] = CacheEntry(
            key="test1", value=MenuResult(items=[]), timestamp=time.time(), ttl=300
        )
        client._cache["test2"] = CacheEntry(
            key="test2",
            value=TextResult(text="test", bytes=4, charset="utf-8"),
            timestamp=time.time(),
            ttl=300,
        )

        await client.close()

        assert len(client._cache) == 0


class TestFetchMethod:
    """Test the main fetch method."""

    @pytest.mark.asyncio
    async def test_fetch_with_cache_hit(self):
        """Test fetch method with cache hit."""
        client = GopherClient(cache_enabled=True)  # Explicitly enable cache
        url = "gopher://example.com/1/"
        expected_result = MenuResult(items=[])

        with patch("gopher_mcp.gopher_client.parse_gopher_url") as mock_parse:
            mock_parse.return_value = GopherURL(
                host="example.com", port=70, gopherType="1", selector="/", search=None
            )

            # Pre-populate cache with proper CacheEntry structure
            client._cache[url] = CacheEntry(
                key=url,
                value=expected_result,
                timestamp=time.time(),
                ttl=300,
            )

            result = await client.fetch(url)
            assert result == expected_result
            # parse_gopher_url should still be called for validation even with cache hit
            mock_parse.assert_called_once_with(url)

    @pytest.mark.asyncio
    async def test_fetch_security_validation_error(self):
        """Test fetch method with security validation error."""
        client = GopherClient(allowed_hosts=["allowed.com"])
        url = "gopher://forbidden.com/1/"

        with patch("gopher_mcp.utils.parse_gopher_url") as mock_parse:
            mock_parse.return_value = GopherURL(
                host="forbidden.com",
                port=70,
                gopherType="1",
                selector="/",
                search=None,
            )

            result = await client.fetch(url)
            assert isinstance(result, ErrorResult)
            assert result.error["code"] == "FETCH_ERROR"
            assert "not in allowed hosts list" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_parse_url_error(self):
        """Test fetch method with URL parsing error."""
        client = GopherClient()
        url = "invalid://url"

        with patch("gopher_mcp.utils.parse_gopher_url") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid URL")

            result = await client.fetch(url)
            assert isinstance(result, ErrorResult)
            assert result.error["code"] == "FETCH_ERROR"
            assert "URL must start with 'gopher://'" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_content_error(self):
        """Test fetch method with content fetching error."""
        client = GopherClient()
        url = "gopher://example.com/1/"

        with (
            patch("gopher_mcp.utils.parse_gopher_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = GopherURL(
                host="example.com", port=70, gopherType="1", selector="/", search=None
            )
            mock_fetch.side_effect = Exception("Network error")

            result = await client.fetch(url)
            assert isinstance(result, ErrorResult)
            assert result.error["code"] == "FETCH_ERROR"
            assert "Network error" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_successful_with_caching(self):
        """Test successful fetch with caching."""
        client = GopherClient()
        url = "gopher://example.com/1/"
        expected_result = MenuResult(items=[])

        with (
            patch("gopher_mcp.utils.parse_gopher_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = GopherURL(
                host="example.com", port=70, gopherType="1", selector="/", search=None
            )
            mock_fetch.return_value = expected_result

            result = await client.fetch(url)
            assert result == expected_result

            # Should be cached now
            assert url in client._cache
            cached_entry = client._cache[url]
            assert cached_entry.value == expected_result


class TestResponseProcessing:
    """Test response processing methods."""

    @pytest.mark.asyncio
    async def test_process_menu_response_success(self):
        """Test successful menu response processing."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/", search=None
        )

        # Mock pituophis response
        mock_response = Mock()
        mock_item1 = Mock()
        mock_item1.itype = "0"
        mock_item1.text = "Test File"
        mock_item1.path = "/test.txt"
        mock_item1.host = "example.com"
        mock_item1.port = 70

        mock_item2 = Mock()
        mock_item2.itype = "1"
        mock_item2.text = "Test Directory"
        mock_item2.path = "/testdir/"
        mock_item2.host = "example.com"
        mock_item2.port = 70

        mock_response.menu.return_value = [mock_item1, mock_item2]

        result = await client._process_menu_response(mock_response, parsed_url)

        assert isinstance(result, MenuResult)
        assert len(result.items) == 2

        # Check first item
        item1 = result.items[0]
        assert item1.type == "0"
        assert item1.title == "Test File"
        assert item1.selector == "/test.txt"
        assert item1.host == "example.com"
        assert item1.port == 70
        assert item1.next_url == "gopher://example.com:70/0/test.txt"

        # Check second item
        item2 = result.items[1]
        assert item2.type == "1"
        assert item2.title == "Test Directory"
        assert item2.selector == "/testdir/"
        assert item2.host == "example.com"
        assert item2.port == 70
        assert item2.next_url == "gopher://example.com:70/1/testdir/"

    @pytest.mark.asyncio
    async def test_process_menu_response_with_search(self):
        """Test menu response processing with search query."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",
            selector="/search",
            search="python",
        )

        # Mock pituophis response
        mock_response = Mock()
        mock_item = Mock()
        mock_item.itype = "7"
        mock_item.text = "Search"
        mock_item.path = "/search"
        mock_item.host = "example.com"
        mock_item.port = 70

        mock_response.menu.return_value = [mock_item]

        result = await client._process_menu_response(mock_response, parsed_url)

        assert isinstance(result, MenuResult)
        assert len(result.items) == 1

        item = result.items[0]
        assert item.next_url == "gopher://example.com:70/7/search?python"

    @pytest.mark.asyncio
    async def test_process_menu_response_error(self):
        """Test menu response processing with error."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/", search=None
        )

        # Mock pituophis response that raises exception
        mock_response = Mock()
        mock_response.menu.side_effect = Exception("Parse error")

        result = await client._process_menu_response(mock_response, parsed_url)

        assert isinstance(result, MenuResult)
        assert len(result.items) == 0  # Should return empty menu on error

    @pytest.mark.asyncio
    async def test_process_text_response_success(self):
        """Test successful text response processing."""
        client = GopherClient()

        # Mock pituophis response
        mock_response = Mock()
        mock_response.text.return_value = "Hello, World!\nThis is a test."
        mock_response.binary = b"Hello, World!\nThis is a test."

        result = await client._process_text_response(mock_response)

        assert isinstance(result, TextResult)
        assert result.text == "Hello, World!\nThis is a test."
        assert result.bytes == len(mock_response.binary)
        assert result.charset == "utf-8"

    @pytest.mark.asyncio
    async def test_process_text_response_with_control_chars(self):
        """Test text response processing with control characters."""
        client = GopherClient()

        # Mock pituophis response with control characters
        mock_response = Mock()
        text_with_controls = "Hello\x00\x01\x02World\r\nTest\t"
        mock_response.text.return_value = text_with_controls
        mock_response.binary = text_with_controls.encode("utf-8")

        result = await client._process_text_response(mock_response)

        assert isinstance(result, TextResult)
        # Control characters should be removed except \n and \t
        assert result.text == "HelloWorld\r\nTest\t"
        assert result.charset == "utf-8"

    @pytest.mark.asyncio
    async def test_process_text_response_error(self):
        """Test text response processing with error."""
        client = GopherClient()

        # Mock pituophis response that raises exception
        mock_response = Mock()
        mock_response.text.side_effect = Exception("Text processing error")

        result = await client._process_text_response(mock_response)

        assert isinstance(result, TextResult)
        assert "Error processing text" in result.text
        assert result.charset == "utf-8"

    @pytest.mark.asyncio
    async def test_process_binary_response_success(self):
        """Test successful binary response processing."""
        client = GopherClient()

        # Mock pituophis response with PNG data
        mock_response = Mock()
        png_header = b"\x89PNG\r\n\x1a\n" + b"test data"
        mock_response.binary = png_header

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == len(png_header)
        assert result.mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_process_binary_response_jpeg(self):
        """Test binary response processing for JPEG."""
        client = GopherClient()

        # Mock pituophis response with JPEG data
        mock_response = Mock()
        jpeg_header = b"\xff\xd8\xff" + b"test data"
        mock_response.binary = jpeg_header

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == len(jpeg_header)
        assert result.mime_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_process_binary_response_gif(self):
        """Test binary response processing for GIF."""
        client = GopherClient()

        # Mock pituophis response with GIF data
        mock_response = Mock()
        gif_header = b"GIF89a" + b"test data"
        mock_response.binary = gif_header

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == len(gif_header)
        assert result.mime_type == "image/gif"

    @pytest.mark.asyncio
    async def test_process_binary_response_pdf(self):
        """Test binary response processing for PDF."""
        client = GopherClient()

        # Mock pituophis response with PDF data
        mock_response = Mock()
        pdf_header = b"%PDF-1.4" + b"test data"
        mock_response.binary = pdf_header

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == len(pdf_header)
        assert result.mime_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_process_binary_response_zip(self):
        """Test binary response processing for ZIP."""
        client = GopherClient()

        # Mock pituophis response with ZIP data
        mock_response = Mock()
        zip_header = b"PK\x03\x04" + b"test data"
        mock_response.binary = zip_header

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == len(zip_header)
        assert result.mime_type == "application/zip"

    @pytest.mark.asyncio
    async def test_process_binary_response_unknown(self):
        """Test binary response processing for unknown type."""
        client = GopherClient()

        # Mock pituophis response with unknown data
        mock_response = Mock()
        unknown_data = b"unknown binary data"
        mock_response.binary = unknown_data

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == len(unknown_data)
        assert result.mime_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_process_binary_response_empty(self):
        """Test binary response processing for empty data."""
        client = GopherClient()

        # Mock pituophis response with empty data
        mock_response = Mock()
        mock_response.binary = b""

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == 0
        assert result.mime_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_process_binary_response_error(self):
        """Test binary response processing with error."""
        client = GopherClient()

        # Mock pituophis response that raises exception
        mock_response = Mock()
        mock_response.binary = property(
            lambda self: (_ for _ in ()).throw(Exception("Binary error"))
        )

        result = await client._process_binary_response(mock_response)

        assert isinstance(result, BinaryResult)
        assert result.bytes == 0
        assert result.mime_type == "application/octet-stream"


class TestFetchContentMethod:
    """Test the _fetch_content method for different content types."""

    @pytest.mark.asyncio
    async def test_fetch_content_menu_type(self):
        """Test fetching menu content (type 1)."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/", search=None
        )

        mock_response = Mock()
        expected_result = MenuResult(items=[])

        with (
            patch("pituophis.Request") as mock_request_class,
            patch.object(client, "_process_menu_response") as mock_process,
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_request = Mock()
            mock_request.get.return_value = mock_response
            mock_request_class.return_value = mock_request
            mock_process.return_value = expected_result

            # Mock asyncio.get_event_loop().run_in_executor
            mock_loop = Mock()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.run_in_executor.return_value = future
            mock_get_loop.return_value = mock_loop

            result = await client._fetch_content(parsed_url)

            assert result == expected_result
            mock_request_class.assert_called_once_with(
                host="example.com",
                port=70,
                path="/",
                query="",
                itype="1",
                tls=False,
                tls_verify=True,
            )
            mock_process.assert_called_once_with(mock_response, parsed_url)

    @pytest.mark.asyncio
    async def test_fetch_content_text_type(self):
        """Test fetching text content (type 0)."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="0",
            selector="/test.txt",
            search=None,
        )

        mock_response = Mock()
        expected_result = TextResult(text="test", bytes=4, charset="utf-8")

        with (
            patch("pituophis.Request") as mock_request_class,
            patch.object(client, "_process_text_response") as mock_process,
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_request = Mock()
            mock_request.get.return_value = mock_response
            mock_request_class.return_value = mock_request
            mock_process.return_value = expected_result

            # Mock asyncio.get_event_loop().run_in_executor
            mock_loop = Mock()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.run_in_executor.return_value = future
            mock_get_loop.return_value = mock_loop

            result = await client._fetch_content(parsed_url)

            assert result == expected_result
            mock_process.assert_called_once_with(mock_response)

    @pytest.mark.asyncio
    async def test_fetch_content_search_type(self):
        """Test fetching search content (type 7)."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",
            selector="/search",
            search="python",
        )

        mock_response = Mock()
        expected_result = MenuResult(items=[])

        with (
            patch("pituophis.Request") as mock_request_class,
            patch.object(client, "_process_menu_response") as mock_process,
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_request = Mock()
            mock_request.get.return_value = mock_response
            mock_request_class.return_value = mock_request
            mock_process.return_value = expected_result

            # Mock asyncio.get_event_loop().run_in_executor
            mock_loop = Mock()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.run_in_executor.return_value = future
            mock_get_loop.return_value = mock_loop

            result = await client._fetch_content(parsed_url)

            assert result == expected_result
            mock_request_class.assert_called_once_with(
                host="example.com",
                port=70,
                path="/search",
                query="python",
                itype="7",
                tls=False,
                tls_verify=True,
            )
            mock_process.assert_called_once_with(mock_response, parsed_url)

    @pytest.mark.asyncio
    async def test_fetch_content_binary_types(self):
        """Test fetching binary content (types 4, 5, 6, 9, g, I)."""
        client = GopherClient()

        binary_types = ["4", "5", "6", "9", "g", "I"]

        for gopher_type in binary_types:
            parsed_url = GopherURL(
                host="example.com",
                port=70,
                gopherType=gopher_type,
                selector="/file.bin",
                search=None,
            )

            mock_response = Mock()
            expected_result = BinaryResult(
                bytes=100, mime_type="application/octet-stream"
            )

            with (
                patch("pituophis.Request") as mock_request_class,
                patch.object(client, "_process_binary_response") as mock_process,
                patch("asyncio.get_event_loop") as mock_get_loop,
            ):
                mock_request = Mock()
                mock_request.get.return_value = mock_response
                mock_request_class.return_value = mock_request
                mock_process.return_value = expected_result

                # Mock asyncio.get_event_loop().run_in_executor
                mock_loop = Mock()
                future = asyncio.Future()
                future.set_result(mock_response)
                mock_loop.run_in_executor.return_value = future
                mock_get_loop.return_value = mock_loop

                result = await client._fetch_content(parsed_url)

                assert result == expected_result
                mock_process.assert_called_once_with(mock_response)

    @pytest.mark.asyncio
    async def test_fetch_content_unknown_type(self):
        """Test fetching unknown content type (defaults to text)."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="X",  # Unknown type
            selector="/unknown",
            search=None,
        )

        mock_response = Mock()
        expected_result = TextResult(text="unknown content", bytes=15, charset="utf-8")

        with (
            patch("pituophis.Request") as mock_request_class,
            patch.object(client, "_process_text_response") as mock_process,
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_request = Mock()
            mock_request.get.return_value = mock_response
            mock_request_class.return_value = mock_request
            mock_process.return_value = expected_result

            # Mock asyncio.get_event_loop().run_in_executor
            mock_loop = Mock()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.run_in_executor.return_value = future
            mock_get_loop.return_value = mock_loop

            result = await client._fetch_content(parsed_url)

            assert result == expected_result
            mock_process.assert_called_once_with(mock_response)

    @pytest.mark.asyncio
    async def test_fetch_content_pituophis_error(self):
        """Test _fetch_content with pituophis error."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/", search=None
        )

        with (
            patch("pituophis.Request") as mock_request_class,
            patch("asyncio.get_event_loop") as mock_get_loop,
        ):
            mock_request = Mock()
            mock_request.get.side_effect = Exception("Connection failed")
            mock_request_class.return_value = mock_request

            # Mock asyncio.get_event_loop().run_in_executor
            mock_loop = Mock()
            future = asyncio.Future()
            future.set_exception(Exception("Connection failed"))
            mock_loop.run_in_executor.return_value = future
            mock_get_loop.return_value = mock_loop

            with pytest.raises(Exception, match="Connection failed"):
                await client._fetch_content(parsed_url)
