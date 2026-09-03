"""Tests for gopher_mcp.models module."""

import pytest
from pydantic import ValidationError

from gopher_mcp.models import (
    BinaryResult,
    CacheEntry,
    ErrorResult,
    GopherFetchRequest,
    GopherMenuItem,
    GopherURL,
    MenuResult,
    TextResult,
    mark_from_cache,
)


class TestGopherFetchRequest:
    """Test GopherFetchRequest model."""

    def test_valid_gopher_url(self):
        """Test that valid Gopher URLs are accepted."""
        request = GopherFetchRequest(url="gopher://example.com/1/")
        assert request.url == "gopher://example.com/1/"

    def test_invalid_url_scheme(self):
        """Test that non-Gopher URLs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GopherFetchRequest(url="http://example.com/")

        assert "URL must start with 'gopher://'" in str(exc_info.value)

    def test_complex_gopher_url(self):
        """Test complex Gopher URL with port and path."""
        url = "gopher://gopher.floodgap.com:70/1/world"
        request = GopherFetchRequest(url=url)
        assert request.url == url

    @pytest.mark.parametrize(
        "url",
        [
            "GOPHER://example.com/1/",
            "Gopher://example.com/1/",
            "gOpHeR://example.com/1/",
        ],
    )
    def test_the_scheme_is_matched_case_insensitively(self, url):
        """RFC 3986 s3.1 makes the scheme case-insensitive, and the parsers
        accept a capitalised one. Matching it literally *here* -- at the MCP
        tool boundary, which the caller hits first -- rejected as
        INVALID_REQUEST a URL the parser behind it would have accepted."""
        request = GopherFetchRequest(url=url)

        # Canonicalised, so nothing downstream sees one entry per spelling.
        assert request.url == "gopher://example.com/1/"

    def test_a_case_insensitive_match_does_not_admit_another_scheme(self):
        """Only the case is forgiven; the scheme itself is still checked."""
        with pytest.raises(ValidationError) as exc_info:
            GopherFetchRequest(url="GEMINI://example.com/")

        assert "URL must start with 'gopher://'" in str(exc_info.value)

    def test_a_bare_host_is_still_rejected(self):
        """``partition`` finds no separator, so the message is unchanged."""
        with pytest.raises(ValidationError) as exc_info:
            GopherFetchRequest(url="gopher.floodgap.com")

        assert "URL must start with 'gopher://'" in str(exc_info.value)


class TestGopherMenuItem:
    """Test GopherMenuItem model."""

    def test_basic_menu_item(self):
        """Test basic menu item creation."""
        item = GopherMenuItem(
            type="1",
            title="Test Menu",
            selector="/test",
            host="example.com",
            port=70,
            nextUrl="gopher://example.com/1/test",
        )
        assert item.type == "1"
        assert item.title == "Test Menu"
        assert item.host == "example.com"
        assert item.port == 70

    def test_text_item(self):
        """Test text file menu item."""
        item = GopherMenuItem(
            type="0",
            title="Test File",
            selector="/test.txt",
            host="example.com",
            port=70,
            nextUrl="gopher://example.com/0/test.txt",
        )
        assert item.type == "0"
        assert item.title == "Test File"


class TestMenuResult:
    """Test MenuResult model."""

    def test_empty_menu(self):
        """Test empty menu result."""
        result = MenuResult(items=[])
        assert result.kind == "menu"
        assert result.items == []

    def test_menu_with_items(self):
        """Test menu with items."""
        items = [
            GopherMenuItem(
                type="1",
                title="Submenu",
                selector="/sub",
                host="example.com",
                port=70,
                nextUrl="gopher://example.com/1/sub",
            ),
            GopherMenuItem(
                type="0",
                title="Text File",
                selector="/file.txt",
                host="example.com",
                port=70,
                nextUrl="gopher://example.com/0/file.txt",
            ),
        ]
        result = MenuResult(items=items)
        assert result.kind == "menu"
        assert len(result.items) == 2
        assert result.items[0].type == "1"
        assert result.items[1].type == "0"


class TestTextResult:
    """Test TextResult model."""

    def test_basic_text_result(self):
        """Test basic text result."""
        text_content = "Hello, Gopher!"
        result = TextResult(
            text=text_content, bytes=len(text_content.encode("utf-8")), charset="utf-8"
        )
        assert result.kind == "text"
        assert result.text == text_content
        assert result.bytes == len(text_content.encode("utf-8"))
        assert result.charset == "utf-8"

    def test_text_result_with_unicode(self):
        """Test text result with Unicode content."""
        text_content = "Hello, 世界! 🌍"
        result = TextResult(
            text=text_content, bytes=len(text_content.encode("utf-8")), charset="utf-8"
        )
        assert result.kind == "text"
        assert result.text == text_content
        assert result.bytes == len(text_content.encode("utf-8"))


class TestBinaryResult:
    """Test BinaryResult model."""

    def test_basic_binary_result(self):
        """Test basic binary result."""
        result = BinaryResult(
            bytes=1024,
            mimeType="image/png",  # Use alias
        )
        assert result.kind == "binary"
        assert result.bytes == 1024
        assert result.mime_type == "image/png"
        assert "Binary content not returned" in result.note

    def test_binary_result_without_mime_type(self):
        """Test binary result without MIME type."""
        result = BinaryResult(bytes=512)
        assert result.kind == "binary"
        assert result.bytes == 512
        assert result.mime_type is None


class TestErrorResult:
    """Test ErrorResult model."""

    def test_basic_error_result(self):
        """Test basic error result."""
        error_info = {"code": "TIMEOUT", "message": "Connection timeout"}
        result = ErrorResult(error=error_info)
        assert result.error == error_info
        assert result.error["code"] == "TIMEOUT"
        assert result.error["message"] == "Connection timeout"

    def test_error_result_has_kind_discriminator(self):
        """ErrorResult carries kind='error' so 'kind' is a reliable
        discriminator across every Gopher result (matching MenuResult/TextResult
        /BinaryResult and GeminiErrorResult)."""
        result = ErrorResult(error={"code": "X", "message": "y"})
        assert result.kind == "error"
        assert result.model_dump()["kind"] == "error"


class TestGopherURL:
    """Test GopherURL model."""

    def test_basic_gopher_url(self):
        """Test basic Gopher URL parsing."""
        url = GopherURL(
            host="example.com", port=70, gopher_type="1", selector="/", search=None
        )
        assert url.host == "example.com"
        assert url.port == 70
        assert url.gopher_type == "1"
        assert url.selector == "/"
        assert url.search is None

    def test_gopher_url_with_search(self):
        """Test Gopher URL with search query."""
        url = GopherURL(
            host="example.com",
            port=70,
            gopherType="7",  # Use alias
            selector="/search",
            search="test query",
        )
        assert url.host == "example.com"
        assert url.gopher_type == "7"
        assert url.search == "test query"

    def test_empty_host_rejected(self):
        """An empty/whitespace host must be rejected at the model boundary, the
        same as GeminiURL (otherwise an empty host is only caught later)."""
        with pytest.raises(ValidationError, match="Host cannot be empty"):
            GopherURL(host="", port=70)
        with pytest.raises(ValidationError, match="Host cannot be empty"):
            GopherURL(host="   ", port=70)

    def test_gopher_type_validation(self):
        """Test Gopher type validation."""
        with pytest.raises(ValidationError) as exc_info:
            GopherURL(
                host="example.com",
                port=70,
                gopherType="invalid",  # Must be single character, use alias
                selector="/",
            )
        assert "Gopher type must be a single character" in str(exc_info.value)

    def test_port_validation_invalid_low(self):
        """Test port validation for values too low."""
        with pytest.raises(ValidationError) as exc_info:
            GopherURL(
                host="example.com",
                port=0,  # Invalid port
                gopher_type="1",
                selector="/",
            )
        assert "Port must be between 1 and 65535" in str(exc_info.value)

    def test_port_validation_invalid_high(self):
        """Test port validation for values too high."""
        with pytest.raises(ValidationError) as exc_info:
            GopherURL(
                host="example.com",
                port=65536,  # Invalid port
                gopher_type="1",
                selector="/",
            )
        assert "Port must be between 1 and 65535" in str(exc_info.value)

    def test_port_validation_valid_boundary(self):
        """Test port validation for boundary values."""
        # Test minimum valid port
        url1 = GopherURL(
            host="example.com",
            port=1,
            gopher_type="1",
            selector="/",
        )
        assert url1.port == 1

        # Test maximum valid port
        url2 = GopherURL(
            host="example.com",
            port=65535,
            gopher_type="1",
            selector="/",
        )
        assert url2.port == 65535


class TestCacheEntry:
    """Test CacheEntry model."""

    def test_cache_entry_creation(self):
        """Test cache entry creation."""
        text_result = TextResult(text="Test", bytes=4, charset="utf-8")
        entry = CacheEntry(
            key="test-key", value=text_result, timestamp=1234567890.0, ttl=300
        )
        assert entry.key == "test-key"
        assert entry.value == text_result
        assert entry.timestamp == 1234567890.0
        assert entry.ttl == 300

    def test_cache_entry_expiration(self):
        """Test cache entry expiration logic."""
        text_result = TextResult(text="Test", bytes=4, charset="utf-8")
        entry = CacheEntry(key="test-key", value=text_result, timestamp=1000.0, ttl=300)

        # Not expired
        assert not entry.is_expired(1200.0)  # 200 seconds later

        # Expired
        assert entry.is_expired(1400.0)  # 400 seconds later


class TestCacheProvenance:
    """What a replayed result says about when it was fetched."""

    def test_cached_at_is_reported_as_an_iso_8601_utc_string(self):
        """An epoch float made the model do arithmetic to answer "how old is
        this?", and clashed with the ISO timestamps the certificate tools
        report. The caller still passes a UNIX timestamp in."""
        marked = mark_from_cache(TextResult(text="hi", bytes=2), cached_at=1640995200.0)

        assert marked.cached is True
        assert marked.cached_at == "2022-01-01T00:00:00+00:00"
        assert marked.model_dump()["cached_at"] == "2022-01-01T00:00:00+00:00"

    def test_marking_does_not_touch_the_stored_response(self):
        """The cache hands back the instance it holds, so tagging must copy."""
        stored = TextResult(text="hi", bytes=2)

        mark_from_cache(stored, cached_at=1640995200.0)

        assert stored.cached is False
        assert stored.cached_at is None


class TestContinuationContract:
    """A truncated result has to say how much is missing and where to resume."""

    def test_a_menu_carries_an_item_count_and_an_offset(self):
        result = MenuResult(items=[], truncated=True, total_items=120, next_offset=50)

        dumped = result.model_dump()
        assert dumped["total_items"] == 120
        assert dumped["next_offset"] == 50

    def test_a_text_body_counts_characters_not_bytes(self):
        """An offset into a body is a character position: a byte offset cannot
        be handed back without the risk of splitting a UTF-8 sequence."""
        result = TextResult(
            text="Hello, 世界",
            bytes=13,
            truncated=True,
            total_chars=4096,
            next_offset=9,
        )

        assert result.total_chars == 4096
        assert result.next_offset == 9

    def test_an_untruncated_result_claims_nothing(self):
        """Nothing populates these yet, and a wrong number is worse than none."""
        result = MenuResult(items=[])

        assert result.total_items is None
        assert result.next_offset is None


class TestRequestInfoIsTyped:
    """`request_info` is a described model, not an anything-goes object.

    It was the last `dict[str, Any]` on the wire, so the outputSchema the fetch
    tools advertise described the one field that carries the provenance of the
    answer as "any object". These tests pin the three things that buys: an
    undeclared key is refused instead of silently riding along, a declared key
    is type-checked, and the payload still carries only the keys a call site
    actually supplied.
    """

    def test_an_undeclared_key_is_refused(self):
        """A key nobody declared is a typo or a leak, never a feature.

        Under `dict[str, Any]` `{"selektor": ...}` was accepted and published,
        so a misspelt provenance key reached the model as real provenance.
        """
        with pytest.raises(ValidationError) as exc_info:
            MenuResult(items=[], request_info={"selektor": "/typo"})

        assert "selektor" in str(exc_info.value)

    def test_a_declared_key_is_type_checked(self):
        """`port` is a port number; a string there was published unchecked."""
        with pytest.raises(ValidationError):
            MenuResult(items=[], request_info={"port": "not-a-port"})

    def test_only_the_keys_a_call_site_supplied_reach_the_wire(self):
        """No null padding: a Gopher menu must not grow `has_query`/`cipher`.

        Fourteen optional fields serialized in full would put ten permanently
        null keys on every result, which is exactly the noise this codebase
        refuses elsewhere (see the cache-provenance comment in models.py).
        """
        payload = MenuResult(
            items=[], request_info={"url": "gopher://example.com/1/"}
        ).model_dump()

        assert payload["request_info"] == {"url": "gopher://example.com/1/"}

    def test_a_key_supplied_as_null_still_reaches_the_wire(self):
        """`tls_version: None` means "we looked and the TLS layer had none".

        The Gemini client always writes the four connection-info keys, null
        included, so dropping nulls (rather than unsupplied keys) would delete
        four keys the payload has always carried.
        """
        payload = ErrorResult(
            error={"code": "X", "message": "y"},
            request_info={"url": "gemini://example.org/", "tls_version": None},
        ).model_dump()

        assert payload["request_info"] == {
            "url": "gemini://example.org/",
            "tls_version": None,
        }

    def test_it_still_reads_like_the_dict_it_replaced(self):
        """Consumers index `request_info` by key; that has to keep working.

        `result.request_info["url"]` and `"search_ignored" in request_info` are
        how the clients, the parser and the existing tests read provenance, so
        the model keeps a read-only mapping face over the keys that were
        actually supplied.
        """
        result = MenuResult(items=[], request_info={"url": "gopher://example.com/1/"})

        assert result.request_info["url"] == "gopher://example.com/1/"
        assert "url" in result.request_info
        assert "search_ignored" not in result.request_info
        assert result.request_info.get("search_ignored") is None
        assert result.request_info.get("port", 70) == 70
        with pytest.raises(KeyError):
            result.request_info["port"]


class TestRequestInfoEchoesWhatWasAskedEvenWhenItIsNonsense:
    """The provenance echo repeats the request; it does not re-judge it.

    Argument validation lives at the tools' boundary, where a bad value is
    turned into a structured `INVALID_REQUEST` the caller can read. Duplicating
    that judgement inside the echo makes the report of a bad argument
    impossible to construct.
    """

    def test_an_out_of_range_port_can_still_be_echoed_back(self):
        """`gemini_trust_update` builds its echo BEFORE it checks its port.

        It then rejects a bad port by quoting it back:
        `_error("INVALID_REQUEST", f"Invalid port number: {port}",
        **request_info)` with `port=70000` already in `request_info`. A
        `le=65535` on this field made constructing that rejection raise
        `ValidationError` out of the tool -- so the one code path whose entire
        job is to report an out-of-range port became an unhandled crash, which
        is what
        `test_trust_tool.py::TestTrustUpdateRejectsBadInput::
        test_an_out_of_range_port_is_refused` caught.
        """
        payload = ErrorResult(
            error={"code": "INVALID_REQUEST", "message": "Invalid port number: 70000"},
            request_info={"host": "example.org", "port": 70000},
        ).model_dump()

        assert payload["request_info"]["port"] == 70000

    def test_a_negative_port_is_echoed_too(self):
        """The same rejection path accepts `port=-1`; `ge=0` broke that half."""
        payload = ErrorResult(
            error={"code": "INVALID_REQUEST", "message": "Invalid port number: -1"},
            request_info={"host": "example.org", "port": -1},
        ).model_dump()

        assert payload["request_info"]["port"] == -1
