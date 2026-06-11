"""Tests for gopher_mcp.gopher_client module."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.gopher_transport import GopherProtocolError
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
            ValueError, match=r"Host 'forbidden.com' not in allowed hosts list"
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

    @pytest.mark.parametrize(
        "selector",
        ["/sel\x00null", "/sel\x07bell", "/sel\x1bescape", "/sel\x0bvtab"],
    )
    def test_validate_security_selector_rejects_all_c0_controls(self, selector):
        """All C0 control bytes (not just CR/LF/TAB) must be rejected in selectors.

        A percent-encoded NUL/ESC is decoded by parse_gopher_url and would
        otherwise be sent verbatim to the server inside the request line.
        """
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="1",
            selector=selector,
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

    def test_validate_security_search_tab_injection(self):
        """Reject TAB in the search query: the transport joins selector and
        search with a literal TAB, so an unescaped TAB would inject an extra
        field into the single Gopher request line."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",
            selector="/search",
            search="foo\textrafield",
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
            assert result.error["code"] == "INVALID_REQUEST"
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
            assert result.error["code"] == "INVALID_REQUEST"
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
            # Unexpected exceptions are sanitized -- the raw text must not leak.
            assert "Network error" not in result.error["message"]
            assert result.error["message"] == "Failed to fetch the requested resource"

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

    @pytest.mark.asyncio
    async def test_cache_is_case_insensitive_for_hostname(self):
        """Hostnames are case-insensitive (RFC 3986), so a request that differs
        only in host case must hit the same cache entry rather than creating a
        duplicate and re-fetching."""
        client = GopherClient()
        expected_result = MenuResult(items=[])

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = expected_result

            first = await client.fetch("gopher://Example.COM/1/")
            second = await client.fetch("gopher://example.com/1/")

            assert first == expected_result
            assert second == expected_result
            # The second request is served from cache -- no second fetch.
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_does_not_cache_error_result(self):
        """An ErrorResult must not be cached: a transient failure would
        otherwise be served stale for the whole TTL. Matches the Gemini client,
        which already excludes error/redirect/input/certificate results."""
        client = GopherClient()
        url = "gopher://example.com/1/"

        with (
            patch("gopher_mcp.utils.parse_gopher_url") as mock_parse,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_parse.return_value = GopherURL(
                host="example.com", port=70, gopherType="1", selector="/", search=None
            )
            mock_fetch.return_value = ErrorResult(
                error={"code": "UNSUPPORTED_TYPE", "message": "nope"},
                requestInfo={},
            )

            result = await client.fetch(url)
            assert isinstance(result, ErrorResult)
            assert url not in client._cache


class TestResponseProcessing:
    """Test response processing methods against real raw bytes."""

    def test_process_menu_response_success(self):
        """A real RFC 1436 menu is parsed into structured items."""
        client = GopherClient()
        raw = (
            b"0Test File\t/test.txt\texample.com\t70\r\n"
            b"1Test Directory\t/testdir/\texample.com\t70\r\n"
            b".\r\n"
        )

        result = client._process_menu_response(raw)

        assert isinstance(result, MenuResult)
        assert len(result.items) == 2

        item1 = result.items[0]
        assert item1.type == "0"
        assert item1.title == "Test File"
        assert item1.selector == "/test.txt"
        assert item1.host == "example.com"
        assert item1.port == 70
        assert item1.next_url == "gopher://example.com:70/0/test.txt"

        item2 = result.items[1]
        assert item2.type == "1"
        assert item2.title == "Test Directory"
        assert item2.next_url == "gopher://example.com:70/1/testdir/"

    def test_process_menu_response_caps_items_and_flags_truncation(self):
        """Over-cap menus are sliced to max_menu_items with truncated=True, and
        the parser stops early rather than building the whole directory."""
        client = GopherClient(max_menu_items=3)
        raw = (
            "".join(
                f"0File {i}\t/f{i}\texample.com\t70\r\n" for i in range(20)
            ).encode()
            + b".\r\n"
        )
        result = client._process_menu_response(raw)
        assert len(result.items) == 3
        assert result.truncated is True

    def test_process_menu_response_not_truncated_when_under_cap(self):
        client = GopherClient(max_menu_items=10)
        raw = b"0Only\t/only\texample.com\t70\r\n.\r\n"
        result = client._process_menu_response(raw)
        assert len(result.items) == 1
        assert result.truncated is False

    def test_process_menu_response_skips_terminator_and_blanks(self):
        """The '.' terminator and blank lines are not emitted as items."""
        client = GopherClient()
        raw = (
            b"0Doc\tsel\texample.com\t70\r\n"
            b"\r\n"  # blank line
            b".\r\n"  # RFC 1436 terminator
            b"0After terminator\tsel2\texample.com\t70\r\n"
        )

        result = client._process_menu_response(raw)

        # Only well-formed item lines are kept; '.' and blanks are skipped.
        titles = [i.title for i in result.items]
        assert "Doc" in titles
        assert "." not in titles

    def test_process_menu_response_empty(self):
        """An empty body yields an empty (not error) menu."""
        client = GopherClient()
        result = client._process_menu_response(b"")
        assert isinstance(result, MenuResult)
        assert result.items == []

    def test_process_text_response_success(self):
        """Text is decoded as UTF-8 and byte count reflects raw bytes."""
        client = GopherClient()
        raw = b"Hello, World!\nThis is a test."

        result = client._process_text_response(raw)

        assert isinstance(result, TextResult)
        assert result.text == "Hello, World!\nThis is a test."
        assert result.bytes == len(raw)
        assert result.charset == "utf-8"

    def test_process_text_response_with_control_chars(self):
        """Control characters are stripped except \\n, \\r and \\t."""
        client = GopherClient()
        raw = b"Hello\x00\x01\x02World\r\nTest\t"

        result = client._process_text_response(raw)

        assert result.text == "HelloWorld\r\nTest\t"
        assert result.charset == "utf-8"

    def test_process_text_response_strips_terminator_and_undot_stuffs(self):
        """RFC 1436 text framing is reversed: drop the lone '.' terminator and
        un-dot-stuff lines beginning with '..'."""
        client = GopherClient()
        raw = b"..dotted\r\nnormal line\r\n.\r\n"

        result = client._process_text_response(raw)

        assert result.text == ".dotted\r\nnormal line\r\n"
        assert result.bytes == len(raw)  # byte count still reflects raw input

    def test_process_text_response_without_terminator_unchanged(self):
        """Text that isn't dot-terminated is returned verbatim."""
        client = GopherClient()
        result = client._process_text_response(b"just text\nno terminator")
        assert result.text == "just text\nno terminator"

    def test_process_text_response_unframed_does_not_undot_stuff(self):
        """Un-dot-stuffing is part of the RFC 1436 period-termination framing.
        Without a trailing '.' terminator the document is unframed, so a leading
        '..' is literal content and must NOT be collapsed to '.'."""
        client = GopherClient()
        result = client._process_text_response(b"..literal dots\nplain text")
        assert result.text == "..literal dots\nplain text"

    def test_process_menu_response_handles_cr_only_line_endings(self):
        """Legacy CR-only line separators are split, not merged into one line."""
        client = GopherClient()
        raw = b"0A\tselA\texample.com\t70\r0B\tselB\texample.com\t70\r"
        result = client._process_menu_response(raw)
        assert [i.title for i in result.items] == ["A", "B"]

    def test_menu_next_url_percent_encodes_selector(self):
        """A selector with spaces/'?' is percent-encoded so nextUrl round-trips."""
        from gopher_mcp.utils import parse_gopher_url

        client = GopherClient()
        raw = b"0Spaced\t/path with space?q\texample.com\t70\r\n.\r\n"
        item = client._process_menu_response(raw).items[0]

        assert " " not in item.next_url
        assert item.next_url == "gopher://example.com:70/0/path%20with%20space%3Fq"
        # The generated URL must parse back to the original selector.
        assert parse_gopher_url(item.next_url).selector == "/path with space?q"

    def test_process_text_response_truncates_to_render_limit(self):
        """Text beyond the LLM-facing render cap is truncated and flagged, while
        `bytes` still reports the full original size."""
        client = GopherClient(max_rendered_chars=5)
        result = client._process_text_response(b"abcdefghij")
        assert result.text == "abcde"
        assert result.truncated is True
        assert result.bytes == 10

    def test_process_text_response_not_truncated_under_limit(self):
        client = GopherClient(max_rendered_chars=100)
        result = client._process_text_response(b"short")
        assert result.text == "short"
        assert result.truncated is False

    def test_process_text_response_latin1_fallback(self):
        """Non-UTF-8 (legacy latin-1) content decodes via fallback."""
        client = GopherClient()
        raw = "Café déjà vu".encode("latin-1")  # invalid as UTF-8

        result = client._process_text_response(raw)

        assert result.charset == "latin-1"
        assert "Caf" in result.text
        assert result.bytes == len(raw)

    @pytest.mark.parametrize(
        ("data", "expected_mime"),
        [
            (b"\x89PNG\r\n\x1a\n" + b"data", "image/png"),
            (b"\xff\xd8\xff" + b"data", "image/jpeg"),
            (b"GIF89a" + b"data", "image/gif"),
            (b"%PDF-1.4" + b"data", "application/pdf"),
            (b"PK\x03\x04" + b"data", "application/zip"),
            (b"unknown binary data", "application/octet-stream"),
            (b"", "application/octet-stream"),
        ],
    )
    def test_process_binary_response(self, data, expected_mime):
        """Binary responses return size + sniffed MIME, no bytes to the LLM."""
        client = GopherClient()
        result = client._process_binary_response(data)
        assert isinstance(result, BinaryResult)
        assert result.bytes == len(data)
        assert result.mime_type == expected_mime


class TestFetchContentMethod:
    """Test _fetch_content dispatch over the native transport."""

    @pytest.mark.asyncio
    async def test_fetch_content_menu_type(self):
        """Type 1 dispatches to the menu parser."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="", search=None
        )
        raw = b"0Doc\tsel\texample.com\t70\r\n.\r\n"

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=raw),
        ) as mock_fetch:
            result = await client._fetch_content(parsed_url)

        assert isinstance(result, MenuResult)
        assert len(result.items) == 1
        mock_fetch.assert_awaited_once_with(
            "example.com",
            70,
            "",
            None,
            max_bytes=client.max_response_size,
            timeout=client.timeout_seconds,
            connect_addresses=["93.184.216.34"],
        )

    @pytest.mark.asyncio
    async def test_fetch_content_text_type(self):
        """Type 0 dispatches to the text processor."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="0",
            selector="/test.txt",
            search=None,
        )

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hello"),
        ):
            result = await client._fetch_content(parsed_url)

        assert isinstance(result, TextResult)
        assert result.text == "hello"

    @pytest.mark.asyncio
    async def test_fetch_content_search_type(self):
        """Type 7 (search) is parsed as a menu and forwards the query."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",
            selector="/search",
            search="python",
        )
        raw = b"0Result\tsel\texample.com\t70\r\n.\r\n"

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=raw),
        ) as mock_fetch:
            result = await client._fetch_content(parsed_url)

        assert isinstance(result, MenuResult)
        mock_fetch.assert_awaited_once_with(
            "example.com",
            70,
            "/search",
            "python",
            max_bytes=client.max_response_size,
            timeout=client.timeout_seconds,
            connect_addresses=["93.184.216.34"],
        )

    @pytest.mark.asyncio
    async def test_fetch_content_binary_types(self):
        """Binary types return metadata-only BinaryResult."""
        client = GopherClient()
        for gopher_type in ["4", "5", "6", "9", "g", "I"]:
            parsed_url = GopherURL(
                host="example.com",
                port=70,
                gopherType=gopher_type,
                selector="/file.bin",
                search=None,
            )
            with patch(
                "gopher_mcp.gopher_client.fetch_gopher",
                new=AsyncMock(return_value=b"\x89PNG\r\n\x1a\nx"),
            ):
                result = await client._fetch_content(parsed_url)
            assert isinstance(result, BinaryResult)
            assert result.mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_fetch_content_unknown_type(self):
        """Unknown types default to text handling."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="X",
            selector="/unknown",
            search=None,
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"unknown content"),
        ):
            result = await client._fetch_content(parsed_url)
        assert isinstance(result, TextResult)
        assert result.text == "unknown content"

    @pytest.mark.asyncio
    async def test_fetch_content_does_not_forward_search_for_non_search_types(self):
        """A stray search on a non-type-7 URL must not be sent as a type-7 query
        (RFC 1436 only defines the <TAB>query field for Index-Search servers)."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType="0",
            selector="/file",
            search="stray",
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hi"),
        ) as mock_fetch:
            await client._fetch_content(parsed_url)
        assert mock_fetch.await_args.args[3] is None  # search positional arg

    @pytest.mark.asyncio
    async def test_fetch_content_interactive_type_not_fetched(self):
        """Telnet/tn3270/CSO types have no fetchable body; no connection opens."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="8", selector="/login", search=None
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher", new=AsyncMock()
        ) as mock_fetch:
            result = await client._fetch_content(parsed_url)
        mock_fetch.assert_not_awaited()
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "NOT_FETCHABLE"

    @pytest.mark.asyncio
    async def test_fetch_content_routes_sound_type_to_binary(self):
        """Known-binary types (e.g. 's'/sound) go to the binary processor, not
        the text path that would latin-1-mangle them."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="s", selector="/a.wav", search=None
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"RIFF\x00\x00\x00\x00WAVE"),
        ):
            result = await client._fetch_content(parsed_url)
        assert isinstance(result, BinaryResult)

    @pytest.mark.asyncio
    async def test_fetch_content_acquires_rate_limiter(self):
        """Each network fetch passes through the per-host rate limiter."""
        client = GopherClient()
        client._rate_limiter.acquire = AsyncMock()  # type: ignore[method-assign]
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="0", selector="/f", search=None
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hi"),
        ):
            await client._fetch_content(parsed_url)
        client._rate_limiter.acquire.assert_awaited_once_with("example.com")

    @pytest.mark.asyncio
    async def test_fetch_internal_host_is_blocked(self):
        """A URL resolving to an internal address yields a BLOCKED error (the
        SSRF guard is wired into the gopher client, not only end-to-end)."""
        client = GopherClient()
        result = await client.fetch("gopher://db.internal/1/")
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED"

    @pytest.mark.asyncio
    async def test_allow_local_hosts_permits_loopback(self):
        """With allow_local_hosts the guard is bypassed and the fetch proceeds to
        the (mocked) transport instead of being blocked."""
        client = GopherClient(allow_local_hosts=True)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hi"),
        ) as mock_fetch:
            result = await client.fetch("gopher://localhost/0/x")
        assert isinstance(result, TextResult)
        # Connection is pinned to the validated loopback IP (DNS-rebinding guard).
        assert mock_fetch.await_args.kwargs["connect_addresses"] == ["127.0.0.1"]

    @pytest.mark.asyncio
    async def test_fetch_content_transport_error_propagates(self):
        """Transport errors propagate to be mapped by fetch()."""
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="", search=None
        )
        with (
            patch(
                "gopher_mcp.gopher_client.fetch_gopher",
                new=AsyncMock(side_effect=GopherProtocolError("Connection failed")),
            ),
            pytest.raises(GopherProtocolError, match="Connection failed"),
        ):
            await client._fetch_content(parsed_url)

    @pytest.mark.asyncio
    async def test_max_concurrent_requests_bounds_inflight(self):
        """An opt-in concurrency cap limits simultaneous in-flight fetches."""
        import asyncio

        from gopher_mcp.models import TextResult

        client = GopherClient(max_concurrent_requests=2, cache_enabled=False)
        inflight = 0
        peak = 0

        async def fake(_parsed_url):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            return TextResult(bytes=2, text="hi")

        client._fetch_content = fake  # type: ignore[method-assign]
        await asyncio.gather(
            *[client.fetch(f"gopher://example.com/0/{i}") for i in range(6)]
        )
        assert peak == 2  # cap saturated but never exceeded
        await client.close()

    @pytest.mark.asyncio
    async def test_unlimited_concurrency_by_default(self):
        """The cap is opt-in: default (0) leaves concurrency unbounded."""
        import asyncio

        from gopher_mcp.models import TextResult

        client = GopherClient(cache_enabled=False)  # default: no cap
        inflight = 0
        peak = 0

        async def fake(_parsed_url):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            return TextResult(bytes=2, text="hi")

        client._fetch_content = fake  # type: ignore[method-assign]
        await asyncio.gather(
            *[client.fetch(f"gopher://example.com/0/{i}") for i in range(6)]
        )
        assert peak == 6  # all ran concurrently
        await client.close()

    @pytest.mark.asyncio
    async def test_dns_resolution_is_bounded_by_request_timeout(self):
        """A hanging resolver must not exceed the request deadline. DNS was
        previously outside the timeout envelope, so a tarpit nameserver could
        stall a worker far past timeout_seconds."""
        import asyncio

        client = GopherClient(timeout_seconds=0.05, cache_enabled=False)

        async def slow_validate(*args, **kwargs):
            await asyncio.sleep(5)
            return ["93.184.216.34"]

        with patch(
            "gopher_mcp.gopher_client.validate_target", side_effect=slow_validate
        ):
            # Outer guard fails the test if fetch hangs on DNS instead of
            # honouring its own deadline.
            result = await asyncio.wait_for(
                client.fetch("gopher://example.com/1/"), timeout=1.0
            )

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        await client.close()


class TestMenuItemCap:
    """A Gopher menu must be capped to a bounded number of items.

    max_rendered_chars caps text but never applied to menus, so a 1 MB
    directory could expand to ~87k GopherMenuItem objects all serialized to
    the LLM. Cap the item count and flag truncation, mirroring TextResult.
    """

    def _menu(self, n: int) -> bytes:
        lines = "".join(f"1Item{i}\t/sel{i}\texample.org\t70\r\n" for i in range(n))
        return (lines + ".\r\n").encode("utf-8")

    def test_menu_items_capped_to_limit(self):
        client = GopherClient(max_menu_items=10, cache_enabled=False)
        result = client._process_menu_response(self._menu(50))
        assert len(result.items) == 10
        assert result.truncated is True

    def test_menu_under_limit_not_truncated(self):
        client = GopherClient(max_menu_items=100, cache_enabled=False)
        result = client._process_menu_response(self._menu(5))
        assert len(result.items) == 5
        assert result.truncated is False
