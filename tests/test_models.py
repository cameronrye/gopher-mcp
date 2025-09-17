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
