"""Tests for gopher_mcp.gopher_client module."""

import socket
import time
from unittest.mock import AsyncMock, patch

import pytest

from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.gopher_transport import (
    GopherProtocolError,
    GopherTimeoutError,
    fetch_gopher,
)
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

    def test_zero_ttl_disables_the_cache(self):
        """A zero TTL means every entry is expired the instant it is written, so
        the client must treat it as caching off rather than keep the bookkeeping
        for a cache that can never hit -- the same rule the config layer applies.
        """
        client = GopherClient(cache_ttl_seconds=0)
        assert client.cache_enabled is False

        client._cache_response("gopher://example.com/1/", MenuResult(items=[]))
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
        # Explicitly enable cache; robots is not what this test covers.
        client = GopherClient(cache_enabled=True, respect_robots_txt=False)
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
            # The cached items come back, marked as a replay rather than as the
            # current state of the menu.
            assert isinstance(result, MenuResult)
            assert result.items == expected_result.items
            assert result.cached is True
            # parse_gopher_url should still be called for validation even with cache hit
            mock_parse.assert_called_once_with(url)

    @pytest.mark.asyncio
    async def test_fetch_security_validation_error(self):
        """Test fetch method with security validation error."""
        client = GopherClient(allowed_hosts=["allowed.com"], respect_robots_txt=False)
        url = "gopher://forbidden.com/1/"

        with patch("gopher_mcp.gopher_client.parse_gopher_url") as mock_parse:
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
        """A parser ValueError becomes INVALID_REQUEST with its text intact.

        The patch target is ``gopher_mcp.gopher_client.parse_gopher_url``, the
        name the client actually calls: patching ``gopher_mcp.utils`` (the
        compat facade) was inert, because the client binds its own reference at
        import time -- the assertion below only ever saw the *real* parser's
        message. Validation errors are deliberately surfaced verbatim
        (gopher_client.py: "Validation errors ... are safe to surface"), so the
        injected text is what the caller must see.
        """
        client = GopherClient(respect_robots_txt=False)
        url = "invalid://url"

        with patch("gopher_mcp.gopher_client.parse_gopher_url") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid URL")

            result = await client.fetch(url)
            assert isinstance(result, ErrorResult)
            assert result.error["code"] == "INVALID_REQUEST"
            assert result.error["message"] == "Invalid URL"

    @pytest.mark.asyncio
    async def test_fetch_rejects_non_gopher_scheme(self):
        """The unpatched parser still rejects a non-gopher scheme."""
        client = GopherClient(respect_robots_txt=False)

        result = await client.fetch("invalid://url")
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "INVALID_REQUEST"
        assert "URL must start with 'gopher://'" in result.error["message"]

    @pytest.mark.asyncio
    async def test_fetch_content_error(self):
        """Test fetch method with content fetching error."""
        client = GopherClient(respect_robots_txt=False)
        url = "gopher://example.com/1/"

        with (
            patch("gopher_mcp.gopher_client.parse_gopher_url") as mock_parse,
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
        client = GopherClient(respect_robots_txt=False)
        url = "gopher://example.com/1/"
        expected_result = MenuResult(items=[])

        with (
            patch("gopher_mcp.gopher_client.parse_gopher_url") as mock_parse,
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
        client = GopherClient(respect_robots_txt=False)
        expected_result = MenuResult(items=[])

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = expected_result

            first = await client.fetch("gopher://Example.COM/1/")
            second = await client.fetch("gopher://example.com/1/")

            assert first == expected_result
            assert isinstance(second, MenuResult)
            assert second.items == expected_result.items
            # The second request is served from cache -- no second fetch.
            assert second.cached is True
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_does_not_cache_error_result(self):
        """An ErrorResult must not be cached: a transient failure would
        otherwise be served stale for the whole TTL. Matches the Gemini client,
        which already excludes error/redirect/input/certificate results."""
        client = GopherClient(respect_robots_txt=False)
        url = "gopher://example.com/1/"

        with (
            patch("gopher_mcp.gopher_client.parse_gopher_url") as mock_parse,
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
        """Control characters are stripped except \\n and \\t; CR is folded into
        the LF it framed."""
        client = GopherClient()
        raw = b"Hello\x00\x01\x02World\r\nTest\t"

        result = client._process_text_response(raw)

        assert result.text == "HelloWorld\nTest\t"
        assert result.charset == "utf-8"

    def test_process_text_response_normalises_line_endings(self):
        """CRLF and legacy bare CR both reach the model as LF: the CR carries no
        information and cost an escaped "\\r" on every line of the JSON."""
        client = GopherClient()

        assert client._process_text_response(b"a\r\nb\r\nc").text == "a\nb\nc"
        assert client._process_text_response(b"a\rb\rc").text == "a\nb\nc"
        # A body that was already LF-framed is untouched.
        assert client._process_text_response(b"a\nb\nc").text == "a\nb\nc"

    def test_process_text_response_strips_terminator_and_undot_stuffs(self):
        """RFC 1436 text framing is reversed: drop the lone '.' terminator and
        un-dot-stuff lines beginning with '..'."""
        client = GopherClient()
        raw = b"..dotted\r\nnormal line\r\n.\r\n"

        result = client._process_text_response(raw)

        assert result.text == ".dotted\nnormal line\n"
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
    async def test_fetch_acquires_rate_limiter(self):
        """Each network fetch passes through the per-host rate limiter.

        The limiter is acquired in ``_bounded_fetch``, deliberately *outside*
        the concurrency semaphore; see
        ``test_rate_limiter_waits_outside_the_concurrency_cap``.
        """
        client = GopherClient()
        client._rate_limiter.acquire = AsyncMock()  # type: ignore[method-assign]
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="0", selector="/f", search=None
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hi"),
        ):
            await client._bounded_fetch(parsed_url)
        client._rate_limiter.acquire.assert_awaited_once_with("example.com")

    @pytest.mark.asyncio
    async def test_rate_limiter_waits_outside_the_concurrency_cap(self):
        """A throttled host must not occupy concurrency slots while sleeping.

        Both settings now ship enabled, so sleeping inside the semaphore would
        let one slow host starve unrelated hosts that are not throttled at all.
        """

        from gopher_mcp.models import TextResult

        client = GopherClient(
            cache_enabled=False,
            max_concurrent_requests=1,
            requests_per_minute=60,
            respect_robots_txt=False,
        )
        held = []

        async def fake(_parsed_url):
            held.append(client._fetch_semaphore._value)
            return TextResult(bytes=2, text="hi")

        client._fetch_content = fake  # type: ignore[method-assign]
        sleeps = []

        async def fake_sleep(seconds):
            # The semaphore must be free while the limiter is waiting.
            sleeps.append(client._fetch_semaphore._value)

        client._rate_limiter._sleep = fake_sleep  # type: ignore[method-assign]
        await client.fetch("gopher://example.com/0/a")
        await client.fetch("gopher://example.com/0/b")

        assert sleeps, "expected the limiter to throttle the second request"
        # 1 == the whole cap is still available while we wait.
        assert all(v == 1 for v in sleeps)
        await client.close()

    @pytest.mark.asyncio
    async def test_fetch_internal_host_is_blocked(self):
        """A URL resolving to an internal address yields a BLOCKED error (the
        SSRF guard is wired into the gopher client, not only end-to-end)."""
        client = GopherClient(respect_robots_txt=False)
        result = await client.fetch("gopher://db.internal/1/")
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED"

    @pytest.mark.asyncio
    async def test_allow_local_hosts_permits_loopback(self):
        """With allow_local_hosts the guard is bypassed and the fetch proceeds to
        the (mocked) transport instead of being blocked."""
        client = GopherClient(allow_local_hosts=True, respect_robots_txt=False)
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

        # Rate limiting is on by default and would serialize same-host
        # requests to one per second, hiding the concurrency behaviour.
        client = GopherClient(
            max_concurrent_requests=2,
            cache_enabled=False,
            requests_per_minute=0,
            respect_robots_txt=False,
        )
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
    async def test_concurrency_capped_by_default(self):
        """The cap ships on: a default client bounds in-flight fetches."""
        import asyncio

        from gopher_mcp.gopher_client import DEFAULT_MAX_CONCURRENT_REQUESTS
        from gopher_mcp.models import TextResult

        # Rate limiting is also on by default and would serialize these to one
        # per second, hiding what this test measures; disable just that.
        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=False
        )
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
            *[client.fetch(f"gopher://example.com/0/{i}") for i in range(10)]
        )
        assert peak == DEFAULT_MAX_CONCURRENT_REQUESTS
        await client.close()

    @pytest.mark.asyncio
    async def test_unlimited_concurrency_when_explicitly_disabled(self):
        """Setting the cap to 0 still means unbounded."""
        import asyncio

        from gopher_mcp.models import TextResult

        client = GopherClient(
            cache_enabled=False,
            max_concurrent_requests=0,
            requests_per_minute=0,
            respect_robots_txt=False,
        )
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

        client = GopherClient(
            timeout_seconds=0.05, cache_enabled=False, respect_robots_txt=False
        )

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


class TestEmptyAllowlistDenies:
    """An explicitly empty allowlist admits nothing.

    ``set(allowed_hosts) if allowed_hosts else None`` collapsed ``[]`` to "no
    allowlist configured", so a caller who deliberately locked the client down
    got NO host restriction at all -- the opposite of what they asked for.
    ``allowed_ports`` in ssrf.validate_target already behaves this way.
    """

    def test_empty_list_blocks_every_host(self):
        client = GopherClient(allowed_hosts=[])
        assert client.allowed_hosts == set()
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/", search=None
        )
        with pytest.raises(ValueError, match="not in allowed hosts list"):
            client._validate_security(parsed_url)

    def test_none_still_allows_every_host(self):
        client = GopherClient(allowed_hosts=None)
        assert client.allowed_hosts is None
        parsed_url = GopherURL(
            host="example.com", port=70, gopherType="1", selector="/", search=None
        )
        client._validate_security(parsed_url)

    def test_allowlist_is_normalized_once_at_construction(self):
        """Normalizing per request rebuilt the set on every fetch even though
        the allowlist is fixed at construction."""
        client = GopherClient(allowed_hosts=["Example.COM."])
        assert client.allowed_hosts == {"example.com"}
        parsed_url = GopherURL(
            host="EXAMPLE.com", port=70, gopherType="1", selector="/", search=None
        )
        client._validate_security(parsed_url)


class TestRobotsOversizeHandling:
    """An over-cap robots.txt is truncated and parsed (RFC 9309 s2.5), not
    re-downloaded in full and discarded on every single request."""

    @pytest.mark.asyncio
    async def test_robots_fetch_is_capped_by_max_response_size(self):
        client = GopherClient(max_response_size=4096, respect_robots_txt=True)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"User-agent: *\r\nDisallow:\r\n"),
        ) as mock_fetch:
            await client._fetch_robots("example.com", 70)

        assert mock_fetch.await_args.kwargs["max_bytes"] == 4096
        assert mock_fetch.await_args.kwargs["truncate_at_max"] is True

    @pytest.mark.asyncio
    async def test_truncated_robots_drops_the_incomplete_final_line(self):
        """Half a Disallow must not be applied as if it were a whole one."""
        # The transport stops exactly at the cap, so the body it hands back ends
        # mid-directive.
        body = b"User-agent: *\nDisallow: /private/\nDisallow: /secr"
        client = GopherClient(max_response_size=len(body), respect_robots_txt=True)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=body),
        ):
            text = await client._fetch_robots("example.com", 70)

        assert text == "User-agent: *\nDisallow: /private/\n"


class TestInfoLinesAreNotLinks:
    """An 'i' line is banner text, not a navigable target."""

    def test_info_item_carries_no_next_url(self):
        """Servers park placeholders ("error.host"/1, "(NULL)"/0) in an info
        line's unused host/port fields, so a URL built from them is dead by
        construction -- and info lines are most of a real menu. The item is
        still returned so the banner text reads."""
        client = GopherClient()
        raw = (
            b"iWelcome to the server\t\terror.host\t1\r\n"
            b"iSecond banner\tfake\t(NULL)\t0\r\n"
            b"0Real file\t/real.txt\texample.com\t70\r\n"
            b".\r\n"
        )

        items = client._process_menu_response(raw).items

        assert [i.type for i in items] == ["i", "i", "0"]
        assert items[0].title == "Welcome to the server"
        assert items[0].next_url == ""
        assert items[1].next_url == ""
        # Navigable items are untouched.
        assert items[2].next_url == "gopher://example.com:70/0/real.txt"

    def test_info_line_keeps_an_explicit_hurl_target(self):
        """A "URL:" selector states the destination outright rather than
        deriving it from the placeholder host/port, so it survives the rule."""
        client = GopherClient()
        raw = b"iSee the website\tURL:https://example.org/\terror.host\t1\r\n"

        item = client._process_menu_response(raw).items[0]

        assert item.type == "i"
        assert item.next_url == "https://example.org/"

    def test_non_printable_item_type_degrades_to_info(self):
        """The type is the one server-controlled field that never passed through
        sanitize_display_text, so an ESC/NUL there reached the model raw."""
        client = GopherClient()
        raw = b"\x1b[31mRed\tsel\texample.com\t70\r\n\x00x\tsel\texample.com\t70\r\n"

        items = client._process_menu_response(raw).items

        assert [i.type for i in items] == ["i", "i"]
        assert [i.next_url for i in items] == ["", ""]
        assert items[0].title == "[31mRed"


class TestLatin1SelectorRoundTrip:
    """A latin-1 server's selector bytes must survive menu -> nextUrl -> wire."""

    def test_latin1_selector_bytes_survive_the_url_round_trip(self):
        from gopher_mcp.gopher_transport import build_request
        from gopher_mcp.utils import parse_gopher_url

        client = GopherClient()
        # An unmistakably latin-1 menu: the accented bytes are invalid UTF-8.
        raw = "0Café menu\t/café.txt\tgopher.example\t70\r\n.\r\n".encode("latin-1")

        item = client._process_menu_response(raw).items[0]

        # The selector is percent-encoded back to its ON-WIRE byte, not to the
        # two UTF-8 bytes the character would encode to.
        assert item.next_url == "gopher://gopher.example:70/0/caf%E9.txt"
        parsed = parse_gopher_url(item.next_url)
        assert build_request(parsed.selector) == b"/caf\xe9.txt\r\n"

    def test_utf8_selector_still_round_trips_as_utf8(self):
        from gopher_mcp.gopher_transport import build_request
        from gopher_mcp.utils import parse_gopher_url

        client = GopherClient()
        raw = "0Café menu\t/café.txt\tgopher.example\t70\r\n.\r\n".encode()

        item = client._process_menu_response(raw).items[0]

        assert item.next_url == "gopher://gopher.example:70/0/caf%C3%A9.txt"
        parsed = parse_gopher_url(item.next_url)
        assert parsed.selector == "/café.txt"
        assert build_request(parsed.selector) == "/café.txt\r\n".encode()

    @pytest.mark.asyncio
    async def test_request_info_selector_is_json_safe(self):
        """A recovered latin-1 byte travels as a surrogate escape, which cannot
        be encoded into JSON at all -- the echo must be the lossy form or the
        whole response fails to serialize."""
        client = GopherClient(respect_robots_txt=False)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"body"),
        ):
            result = await client.fetch("gopher://example.com/0/caf%E9.txt")

        assert isinstance(result, TextResult)
        assert result.request_info["selector"] == "/caf�.txt"
        result.model_dump_json()  # must not raise


class TestDamagedUtf8Decoding:
    """One bad byte must not re-read a whole UTF-8 body as latin-1."""

    def test_single_bad_byte_keeps_the_utf8_reading(self):
        client = GopherClient()
        raw = "café — naïve résumé".encode() + b"\xff" + b" fin"

        result = client._process_text_response(raw)

        assert result.charset == "utf-8"
        assert result.text == "café — naïve résumé� fin"

    def test_pervasive_high_bytes_still_decode_as_latin1(self):
        client = GopherClient()
        raw = "Café déjà vu".encode("latin-1")

        result = client._process_text_response(raw)

        assert result.charset == "latin-1"
        assert result.text == "Café déjà vu"


class TestBinaryItemTypeCoverage:
    """'P' (PDF) and ':' (bitmap) are listed item types, not unknown ones."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("gopher_type", "body", "expected_mime"),
        [
            ("P", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj", "application/pdf"),
            (":", b"BM\x46\x00\x00\x00\x00\x00\x00\x00\x36\x00\x00\x00", "image/bmp"),
        ],
    )
    async def test_binary_item_types_do_not_reach_the_text_path(
        self, gopher_type, body, expected_mime
    ):
        client = GopherClient()
        parsed_url = GopherURL(
            host="example.com",
            port=70,
            gopherType=gopher_type,
            selector="/file",
            search=None,
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=body),
        ):
            result = await client._fetch_content(parsed_url)

        assert isinstance(result, BinaryResult)
        assert result.mime_type == expected_mime


class TestIgnoredSearchIsVisible:
    """Dropping a ?query on a non-type-7 URL is correct, but must be reported."""

    @pytest.mark.asyncio
    async def test_non_search_type_reports_search_ignored(self):
        client = GopherClient(respect_robots_txt=False)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"plain file body"),
        ):
            result = await client.fetch("gopher://example.com/0file?zzz")

        assert isinstance(result, TextResult)
        assert result.request_info["search_ignored"] is True

    @pytest.mark.asyncio
    async def test_search_type_and_query_less_urls_carry_no_flag(self):
        # Two uncached reads of one host: without the robots probe to inherit a
        # slot from, the second would wait a full politeness interval, and the
        # flag is what is under test here rather than the spacing.
        client = GopherClient(
            respect_robots_txt=False, cache_enabled=False, requests_per_minute=0
        )
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b".\r\n"),
        ):
            searched = await client.fetch("gopher://example.com/7find?term")
            plain = await client.fetch("gopher://example.com/1/")

        assert "search_ignored" not in searched.request_info
        assert "search_ignored" not in plain.request_info


class TestTimeoutMessageNamesTheConfiguredDeadline:
    """The transport is handed what is LEFT of the budget, not the setting."""

    @pytest.mark.asyncio
    async def test_timeout_reports_configured_timeout_not_the_remainder(self):
        client = GopherClient(respect_robots_txt=False, timeout_seconds=30.0)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(
                side_effect=GopherTimeoutError(
                    "Request timed out after 0.999915084001259 seconds"
                )
            ),
        ):
            result = await client.fetch("gopher://example.com/1/")

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        assert result.error["message"] == "The request timed out after 30.0 seconds"

    @pytest.mark.asyncio
    async def test_other_transport_errors_are_untouched(self):
        client = GopherClient(respect_robots_txt=False)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(
                side_effect=GopherProtocolError("Response exceeds maximum size")
            ),
        ):
            result = await client.fetch("gopher://example.com/1/")

        assert isinstance(result, ErrorResult)
        assert result.error["message"] == "Response exceeds maximum size"


class TestInteractiveResultEchoesTheRequest:
    """NOT_FETCHABLE was the one Gopher error returning an empty request_info."""

    @pytest.mark.asyncio
    async def test_interactive_error_echoes_url_and_selector(self):
        client = GopherClient(respect_robots_txt=False)
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher", new=AsyncMock()
        ) as mock_fetch:
            result = await client.fetch("gopher://example.com/8/login")

        # Still no connection: the answer comes from the item type alone.
        mock_fetch.assert_not_awaited()
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "NOT_FETCHABLE"
        assert result.request_info["url"] == "gopher://example.com/8/login"
        assert result.request_info["host"] == "example.com"
        assert result.request_info["port"] == 70
        assert result.request_info["type"] == "8"
        assert result.request_info["selector"] == "/login"
        assert "timestamp" in result.request_info


class TestRobotsProbeSharesOneRequestsWorthOfBudget:
    """The probe and the fetch it guards are one user request to one host."""

    @pytest.mark.asyncio
    async def test_probe_and_fetch_take_one_rate_slot_and_one_lookup(self, monkeypatch):
        resolved: list[str] = []

        async def counting_resolve(host: str, port: int) -> list[str]:
            resolved.append(host)
            return ["93.184.216.34"]

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", counting_resolve)

        client = GopherClient(respect_robots_txt=True, cache_enabled=False)
        client._rate_limiter.acquire = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hello"),
        ) as mock_fetch:
            result = await client.fetch("gopher://example.com/0/f.txt")

        assert isinstance(result, TextResult)
        # Two wire exchanges (the /robots.txt probe, then the content), but one
        # rate-limit token and one DNS lookup between them.
        assert mock_fetch.await_count == 2
        assert client._rate_limiter.acquire.await_count == 1
        assert resolved == ["example.com"]

    @pytest.mark.asyncio
    async def test_a_later_fetch_does_not_inherit_the_probes_credit(self, monkeypatch):
        """The credit lives in a ContextVar, which outlives the fetch that set
        it; a second fetch on the same task must pay its own way."""
        resolved: list[str] = []

        async def counting_resolve(host: str, port: int) -> list[str]:
            resolved.append(host)
            return ["93.184.216.34"]

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", counting_resolve)

        client = GopherClient(respect_robots_txt=True, cache_enabled=False)
        client._rate_limiter.acquire = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=b"hello"),
        ):
            await client.fetch("gopher://example.com/0/one.txt")
            await client.fetch("gopher://example.com/0/two.txt")

        # The policy is cached after the first probe, so the second fetch runs
        # alone -- and pays for its own slot and its own lookup.
        assert client._rate_limiter.acquire.await_count == 2
        assert resolved == ["example.com", "example.com"]


class TestConnectFailureDoesNotEchoTheAddress:
    """A failed connect must not report which IP was actually tried."""

    @pytest.mark.asyncio
    async def test_refused_connect_omits_the_resolved_ip(self):
        """The transport is handed the IPs the SSRF guard vetted; echoing one
        back in the error turns a failed fetch into an internal-reachability
        oracle. asyncio hides the sockaddr *inside* ``strerror``
        (``OSError(err, f"Connect call failed {address}")``), so reporting
        ``e.strerror`` -- as this code used to -- leaked it anyway.
        """
        # Bind and release a port so the connect is refused rather than filtered.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]

        with pytest.raises(GopherProtocolError) as exc_info:
            await fetch_gopher(
                "example.com",
                closed_port,
                "/",
                max_bytes=1024,
                timeout=5.0,
                connect_addresses=["127.0.0.1"],
            )

        message = str(exc_info.value)
        assert "127.0.0.1" not in message
        assert str(closed_port) not in message
        assert message.startswith("Connection failed: ")


class TestResponseSizeAccessor:
    """One concept, two wire names -- resolved in one place, not at every caller."""

    def test_gopher_reads_the_bytes_field(self):
        client = GopherClient()
        assert client._response_size(TextResult(bytes=42, text="x")) == 42

    def test_bodiless_results_report_zero(self):
        """A menu carries no content length at all; 0 is the honest answer."""
        client = GopherClient()
        assert client._response_size(MenuResult(items=[])) == 0


class TestOffsetContinuation:
    """A truncated result must be continuable, not a dead end.

    The render caps used to cut and discard: `truncated: true` told the model
    something was missing but no call could retrieve it, and a menu did not
    even say how much was gone.
    """

    MENU = (
        "".join(f"1Item {i}\t/item{i}\texample.com\t70\r\n" for i in range(20))
        + ".\r\n"
    ).encode()
    TEXT = "".join(f"line {i}\n" for i in range(40)).encode()

    def _client(self, **kwargs):
        defaults = {
            "respect_robots_txt": False,
            "requests_per_minute": 0,
            "cache_enabled": False,
        }
        return GopherClient(**{**defaults, **kwargs})

    @pytest.mark.asyncio
    async def test_a_truncated_menu_says_where_the_rest_starts(self):
        client = self._client(max_menu_items=3)

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=self.MENU),
        ):
            first = await client.fetch("gopher://example.com/1/")
            second = await client.fetch("gopher://example.com/1/", offset=3)

        assert [i.title for i in first.items] == ["Item 0", "Item 1", "Item 2"]
        assert first.truncated is True
        assert first.next_offset == 3
        # The cap was hit, so the true total is not known -- and a made-up
        # number would be worse than none. next_offset is what makes the rest
        # reachable.
        assert first.total_items is None
        assert [i.title for i in second.items] == ["Item 3", "Item 4", "Item 5"]
        assert second.next_offset == 6

    @pytest.mark.asyncio
    async def test_a_complete_menu_reports_its_total_and_no_next_offset(self):
        client = self._client(max_menu_items=100)

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=self.MENU),
        ):
            result = await client.fetch("gopher://example.com/1/")

        assert result.truncated is False
        assert result.total_items == 20
        assert result.next_offset is None

    @pytest.mark.asyncio
    async def test_an_uncapped_menu_still_honours_the_offset(self):
        """max_menu_items=0 means no render cap, so nothing is ever truncated --
        but an offset the caller asks for is still where the window starts."""
        client = self._client(max_menu_items=0)

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=self.MENU),
        ):
            result = await client.fetch("gopher://example.com/1/", offset=18)

        assert [i.title for i in result.items] == ["Item 18", "Item 19"]
        assert result.truncated is False
        assert result.total_items == 20
        assert result.next_offset is None

    @pytest.mark.asyncio
    async def test_text_windows_reassemble_into_the_whole_body(self):
        client = self._client(max_rendered_chars=40)

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=self.TEXT),
        ):
            result = await client.fetch("gopher://example.com/0/a.txt")
            assert result.total_chars == len(self.TEXT.decode())
            # `bytes` is still the full body, and is NOT an offset: it counts
            # bytes where next_offset counts characters.
            assert result.bytes == len(self.TEXT)

            seen = result.text
            offset = result.next_offset
            # Bounded, not `while offset is not None`: a next_offset that stops
            # advancing must fail this one test, not spin until the suite-wide
            # timeout kills the process without a pytest summary.
            for _ in range(20):
                if offset is None:
                    break
                window = await client.fetch(
                    "gopher://example.com/0/a.txt", offset=offset
                )
                seen += window.text
                offset = window.next_offset
            else:
                pytest.fail(f"windows never terminated: next_offset stuck at {offset}")

        assert seen == self.TEXT.decode()

    @pytest.mark.asyncio
    async def test_an_offset_past_the_end_is_empty_not_an_error(self):
        client = self._client(max_rendered_chars=40)

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=self.TEXT),
        ):
            result = await client.fetch("gopher://example.com/0/a.txt", offset=10_000)

        assert isinstance(result, TextResult)
        assert result.text == ""
        assert result.truncated is False
        assert result.next_offset is None

    @pytest.mark.asyncio
    async def test_a_negative_offset_is_rejected(self):
        client = self._client()

        result = await client.fetch("gopher://example.com/0/a.txt", offset=-1)

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_the_cache_does_not_serve_one_window_for_another(self):
        """The cache stores the rendered window, not the body, so the offset is
        part of the key -- otherwise a request for the second window would be
        answered with the first one, silently.

        The offset stays in the cache key even now that the BODY is held
        separately: the two do different jobs. The held body saves the
        download; the per-offset cache key is what stops window 0 being handed
        back for a request for window 1. Dropping either would be wrong, and
        dropping the key would be wrong silently.
        """
        client = self._client(cache_enabled=True, max_rendered_chars=40)

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=self.TEXT),
        ) as mock_fetch:
            first = await client.fetch("gopher://example.com/0/a.txt")
            second = await client.fetch("gopher://example.com/0/a.txt", offset=40)
            replay = await client.fetch("gopher://example.com/0/a.txt")

        assert second.text != first.text
        assert second.text == self.TEXT.decode()[40:80]
        # ONE download for both windows: the second is rendered from the body
        # the first already downloaded. This was 2 before that body was held --
        # the count is the whole point of the change, so it is asserted rather
        # than left to drift.
        assert mock_fetch.await_count == 1
        assert replay.cached is True
        assert replay.text == first.text


class TestContinuationDoesNotRefetchTheBody:
    """Walking one document must cost one download, not one per window.

    Gopher has no range request, so every window read the WHOLE body again:
    reading a 208 KB page at a 10k cap cost 21 fetches and 4.4 MB, and with the
    shipped per-host rate limit those 21 fetches are also 21 seconds. The cache
    did not help, because what it stored was the rendered window -- keyed by
    offset -- so window 2 was always a miss that went back to the server.

    The comment that chose that trade said caching bodies "would put full-size
    bodies in a cache whose entry cap exists to bound its memory". Measured, the
    opposite is true: a full walk of that page left 21 entries holding 217,438
    bytes, MORE than the 208,005-byte body it declined to cache.
    """

    BODY = ("".join(f"line {i}\n" for i in range(400))).encode()

    def _client(self, **kwargs):
        defaults = {
            "respect_robots_txt": False,
            "requests_per_minute": 0,
            "cache_enabled": True,
            "max_rendered_chars": 400,
        }
        return GopherClient(**{**defaults, **kwargs})

    async def _walk(self, *, cache_enabled: bool):
        """Read one document to the end, reporting cost and content."""
        client = self._client(cache_enabled=cache_enabled)
        transport = AsyncMock(return_value=self.BODY + b".\r\n")

        with patch("gopher_mcp.gopher_client.fetch_gopher", new=transport):
            offset: int | None = 0
            windows = 0
            seen = ""
            while offset is not None and windows < 40:
                result = await client.fetch("gopher://example.com/0/big", offset=offset)
                seen += result.text
                windows += 1
                offset = result.next_offset
        return windows, transport.await_count, seen

    @pytest.mark.asyncio
    async def test_walking_a_body_downloads_it_once(self):
        windows, downloads, _ = await self._walk(cache_enabled=True)

        assert windows > 3, "test needs a body that takes several windows"
        assert downloads == 1, (
            f"{windows} windows cost {downloads} downloads of the same body"
        )

    @pytest.mark.asyncio
    async def test_the_held_body_changes_the_cost_and_not_the_content(self):
        """The invariant that matters: a reused body must render exactly what
        another download would have rendered.

        Asserted twice over, against the walk that re-downloads AND against the
        source body, because the two catch different mistakes: the first would
        miss a change that corrupts both walks identically, and the second would
        miss a difference in window boundaries that still reassembles.
        """
        held_windows, held_downloads, held_text = await self._walk(cache_enabled=True)
        refetched_windows, refetched_downloads, refetched_text = await self._walk(
            cache_enabled=False
        )

        assert held_text == refetched_text
        assert held_windows == refetched_windows
        assert held_downloads == 1
        assert refetched_downloads == refetched_windows
        # Every character of the document, exactly once, in order.
        assert held_text == self.BODY.decode()

    @pytest.mark.asyncio
    async def test_refresh_still_goes_back_to_the_server(self):
        """A reused body must not turn `refresh` into a lie."""
        client = self._client()
        transport = AsyncMock(return_value=self.BODY + b".\r\n")

        with patch("gopher_mcp.gopher_client.fetch_gopher", new=transport):
            await client.fetch("gopher://example.com/0/big")
            await client.fetch("gopher://example.com/0/big", offset=400, refresh=True)

        assert transport.await_count == 2

    @pytest.mark.asyncio
    async def test_a_different_url_is_never_served_another_documents_body(self):
        """The slot holds one body; a request for a different resource must
        miss it rather than be answered from whatever was read last."""
        client = self._client()
        first = ("".join(f"aaa {i}\n" for i in range(400))).encode() + b"\r\n.\r\n"
        second = ("".join(f"bbb {i}\n" for i in range(400))).encode() + b"\r\n.\r\n"
        transport = AsyncMock(side_effect=[first, second])

        with patch("gopher_mcp.gopher_client.fetch_gopher", new=transport):
            await client.fetch("gopher://example.com/0/one")
            other = await client.fetch("gopher://example.com/0/two", offset=400)

        assert transport.await_count == 2
        assert "bbb" in other.text and "aaa" not in other.text
