"""Tests for gopher_mcp.utils module."""

import pytest

from gopher_mcp.utils import (
    format_gopher_url,
    guess_mime_type,
    parse_gopher_menu,
    parse_gopher_url,
    parse_menu_line,
    sanitize_selector,
    validate_gopher_response,
)


class TestParseGopherUrl:
    """Test parse_gopher_url function."""

    def test_basic_gopher_url(self):
        """Test parsing basic Gopher URL."""
        url = "gopher://example.com/1/"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.port == 70
        assert result.gopher_type == "1"
        assert result.selector == "/"
        assert result.search is None

    def test_gopher_url_with_port(self):
        """Test parsing Gopher URL with custom port."""
        url = "gopher://example.com:7070/0/test.txt"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.port == 7070
        assert result.gopher_type == "0"
        assert result.selector == "/test.txt"

    def test_gopher_url_with_search(self):
        """Test parsing Gopher URL with search query."""
        url = "gopher://example.com/7/search?test%20query"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.gopher_type == "7"
        assert result.selector == "/search"
        assert result.search == "test query"

    def test_gopher_url_with_tab_search(self):
        """Test parsing Gopher URL with tab-separated search."""
        url = "gopher://example.com/7/search%09test%20query"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.gopher_type == "7"
        assert result.selector == "/search"
        assert result.search == "test query"

    def test_invalid_url_scheme(self):
        """Test parsing invalid URL scheme."""
        with pytest.raises(ValueError) as exc_info:
            parse_gopher_url("http://example.com/")
        assert "URL must start with 'gopher://'" in str(exc_info.value)

    def test_url_without_hostname(self):
        """Test parsing URL without hostname."""
        with pytest.raises(ValueError) as exc_info:
            parse_gopher_url("gopher:///1/")
        assert "URL must contain a hostname" in str(exc_info.value)

    def test_empty_path_defaults(self):
        """Test that empty path defaults to directory listing."""
        url = "gopher://example.com"
        result = parse_gopher_url(url)

        assert result.gopher_type == "1"
        assert result.selector == ""

    def test_root_path_defaults(self):
        """Test that root path defaults to directory listing."""
        url = "gopher://example.com/"
        result = parse_gopher_url(url)

        assert result.gopher_type == "1"
        assert result.selector == ""


class TestParseMenuLine:
    """Test parse_menu_line function."""

    def test_valid_menu_line(self):
        """Test parsing valid menu line."""
        line = "1About\t/about\texample.com\t70"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "1"
        assert result.title == "About"
        assert result.selector == "/about"
        assert result.host == "example.com"
        assert result.port == 70
        assert result.next_url == "gopher://example.com:70/1/about"

    def test_info_line(self):
        """Test parsing info line."""
        line = "iThis is information\t\terror.host\t1"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "i"
        assert result.title == "This is information"
        assert result.selector == ""
        assert result.host == "error.host"
        assert result.port == 1

    def test_empty_line(self):
        """Test parsing empty line."""
        result = parse_menu_line("")
        assert result is None

    def test_termination_marker(self):
        """Test parsing termination marker."""
        result = parse_menu_line(".")
        assert result is None

    def test_line_with_crlf(self):
        """Test parsing line with CRLF."""
        line = "0Test File\t/test.txt\texample.com\t70\r\n"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "0"
        assert result.title == "Test File"

    def test_insufficient_parts(self):
        """Test parsing line with insufficient parts."""
        line = "1About\t/about"  # Missing host and port
        result = parse_menu_line(line)
        assert result is None

    def test_invalid_port(self):
        """Test parsing line with invalid port."""
        line = "1About\t/about\texample.com\tinvalid"
        result = parse_menu_line(line)

        assert result is not None
        assert result.port == 70  # Should default to 70

    def test_empty_type_defaults_to_info(self):
        """Test that empty type defaults to info line."""
        line = "\t\terror.host\t1"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "i"


class TestParseGopherMenu:
    """Test parse_gopher_menu function."""

    def test_complete_menu(self):
        """Test parsing complete menu."""
        content = """1About\t/about\texample.com\t70
0README\t/README.txt\texample.com\t70
iThis is information\t\terror.host\t1
.
"""
        result = parse_gopher_menu(content)

        assert len(result) == 3
        assert result[0].type == "1"
        assert result[0].title == "About"
        assert result[1].type == "0"
        assert result[1].title == "README"
        assert result[2].type == "i"
        assert result[2].title == "This is information"

    def test_empty_menu(self):
        """Test parsing empty menu."""
        content = ".\n"
        result = parse_gopher_menu(content)
        assert len(result) == 0

    def test_menu_with_invalid_lines(self):
        """Test parsing menu with some invalid lines."""
        content = """1Valid\t/valid\texample.com\t70
invalid line
0Another Valid\t/valid2\texample.com\t70
"""
        result = parse_gopher_menu(content)

        assert len(result) == 2
        assert result[0].title == "Valid"
        assert result[1].title == "Another Valid"


class TestSanitizeSelector:
    """Test sanitize_selector function."""

    def test_valid_selector(self):
        """Test sanitizing valid selector."""
        selector = "/path/to/file.txt"
        result = sanitize_selector(selector)
        assert result == selector

    def test_selector_with_tab(self):
        """Test selector with forbidden tab character."""
        with pytest.raises(ValueError) as exc_info:
            sanitize_selector("/path\t/file")
        assert "forbidden character" in str(exc_info.value)

    def test_selector_with_newline(self):
        """Test selector with forbidden newline character."""
        with pytest.raises(ValueError) as exc_info:
            sanitize_selector("/path\n/file")
        assert "forbidden character" in str(exc_info.value)

    def test_selector_with_carriage_return(self):
        """Test selector with forbidden carriage return character."""
        with pytest.raises(ValueError) as exc_info:
            sanitize_selector("/path\r/file")
        assert "forbidden character" in str(exc_info.value)

    def test_selector_too_long(self):
        """Test selector that is too long."""
        long_selector = "a" * 256
        with pytest.raises(ValueError) as exc_info:
            sanitize_selector(long_selector)
        assert "too long" in str(exc_info.value)

    def test_selector_max_length(self):
        """Test selector at maximum allowed length."""
        max_selector = "a" * 255
        result = sanitize_selector(max_selector)
        assert result == max_selector


class TestFormatGopherUrl:
    """Test format_gopher_url function."""

    def test_basic_url(self):
        """Test formatting basic URL."""
        result = format_gopher_url("example.com")
        assert result == "gopher://example.com/1"

    def test_url_with_custom_port(self):
        """Test formatting URL with custom port."""
        result = format_gopher_url("example.com", port=7070)
        assert result == "gopher://example.com:7070/1"

    def test_url_with_selector(self):
        """Test formatting URL with selector."""
        result = format_gopher_url("example.com", selector="/path/file.txt")
        assert result == "gopher://example.com/1/path/file.txt"

    def test_url_with_search(self):
        """Test formatting URL with search."""
        result = format_gopher_url("example.com", gopher_type="7", search="test query")
        assert result == "gopher://example.com/7%09test query"

    def test_url_search_ignored_for_non_search_type(self):
        """Test that search is ignored for non-search types."""
        result = format_gopher_url("example.com", gopher_type="1", search="test")
        assert result == "gopher://example.com/1"


class TestGuessMimeType:
    """Test guess_mime_type function."""

    def test_text_type(self):
        """Test MIME type for text."""
        assert guess_mime_type("0") == "text/plain"

    def test_menu_type(self):
        """Test MIME type for menu."""
        assert guess_mime_type("1") == "text/gopher-menu"

    def test_search_type(self):
        """Test MIME type for search."""
        assert guess_mime_type("7") == "text/gopher-menu"

    def test_image_types(self):
        """Test MIME types for images."""
        assert guess_mime_type("g") == "image/gif"
        assert guess_mime_type("I") == "image/jpeg"

    def test_unknown_type(self):
        """Test MIME type for unknown type."""
        assert guess_mime_type("X") == "application/octet-stream"

    def test_extension_override(self):
        """Test that file extension overrides type mapping."""
        assert guess_mime_type("9", "file.jpg") == "image/jpeg"
        assert guess_mime_type("9", "file.png") == "image/png"
        assert guess_mime_type("9", "file.pdf") == "application/pdf"

    def test_no_extension(self):
        """Test selector without extension."""
        assert guess_mime_type("9", "somefile") == "application/octet-stream"


class TestValidateGopherResponse:
    """Test validate_gopher_response function."""

    def test_valid_response(self):
        """Test validating valid response."""
        content = b"Hello, Gopher!"
        validate_gopher_response(content, 1024)  # Should not raise

    def test_response_too_large(self):
        """Test response that is too large."""
        content = b"x" * 1025
        with pytest.raises(ValueError) as exc_info:
            validate_gopher_response(content, 1024)
        assert "too large" in str(exc_info.value)

    def test_empty_response(self):
        """Test empty response."""
        content = b""
        validate_gopher_response(content, 1024)  # Should not raise

    def test_response_at_limit(self):
        """Test response at size limit."""
        content = b"x" * 1024
        validate_gopher_response(content, 1024)  # Should not raise
