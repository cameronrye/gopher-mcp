"""Tests for Gemini protocol utilities."""

import pytest
from pydantic import ValidationError

from gopher_mcp.models import GeminiFetchRequest, GeminiURL
from gopher_mcp.utils import (
    format_gemini_url,
    parse_gemini_url,
    validate_gemini_url_components,
)


class TestGeminiURLParsing:
    """Test Gemini URL parsing functionality."""

    def test_basic_gemini_url(self):
        """Test parsing a basic Gemini URL."""
        url = "gemini://example.org/"
        parsed = parse_gemini_url(url)

        assert parsed.host == "example.org"
        assert parsed.port == 1965
        assert parsed.path == "/"
        assert parsed.query is None

    def test_gemini_url_with_port(self):
        """Test parsing Gemini URL with custom port."""
        url = "gemini://example.org:7070/"
        parsed = parse_gemini_url(url)

        assert parsed.host == "example.org"
        assert parsed.port == 7070
        assert parsed.path == "/"
        assert parsed.query is None

    def test_gemini_url_with_path(self):
        """Test parsing Gemini URL with path."""
        url = "gemini://example.org/docs/spec.gmi"
        parsed = parse_gemini_url(url)

        assert parsed.host == "example.org"
        assert parsed.port == 1965
        assert parsed.path == "/docs/spec.gmi"
        assert parsed.query is None

    def test_gemini_url_with_query(self):
        """Test parsing Gemini URL with query string."""
        url = "gemini://example.org/search?gemini%20protocol"
        parsed = parse_gemini_url(url)

        assert parsed.host == "example.org"
        assert parsed.port == 1965
        assert parsed.path == "/search"
        assert parsed.query == "gemini%20protocol"

    def test_gemini_url_complete(self):
        """Test parsing complete Gemini URL with all components."""
        url = "gemini://gemini.circumlunar.space:1965/docs/specification.gmi?section=status"
        parsed = parse_gemini_url(url)

        assert parsed.host == "gemini.circumlunar.space"
        assert parsed.port == 1965
        assert parsed.path == "/docs/specification.gmi"
        assert parsed.query == "section=status"

    def test_gemini_url_empty_path(self):
        """Test parsing Gemini URL with empty path."""
        url = "gemini://example.org"
        parsed = parse_gemini_url(url)

        assert parsed.host == "example.org"
        assert parsed.port == 1965
        assert parsed.path == "/"
        assert parsed.query is None

    def test_gemini_url_ip_address(self):
        """Test parsing Gemini URL with IP address."""
        url = "gemini://192.168.1.100:1965/test"
        parsed = parse_gemini_url(url)

        assert parsed.host == "192.168.1.100"
        assert parsed.port == 1965
        assert parsed.path == "/test"
        assert parsed.query is None

    def test_invalid_scheme(self):
        """Test that non-Gemini URLs are rejected."""
        with pytest.raises(ValueError, match="URL must start with 'gemini://'"):
            parse_gemini_url("http://example.org/")

    def test_missing_host(self):
        """Test that URLs without hostname are rejected."""
        with pytest.raises(ValueError, match="URL must contain a hostname"):
            parse_gemini_url("gemini:///path")

    def test_userinfo_forbidden(self):
        """Test that URLs with userinfo are rejected."""
        with pytest.raises(ValueError, match="URL must not contain userinfo"):
            parse_gemini_url("gemini://user:pass@example.org/")

    def test_fragment_forbidden(self):
        """Test that URLs with fragments are rejected."""
        with pytest.raises(ValueError, match="URL must not contain fragment"):
            parse_gemini_url("gemini://example.org/path#fragment")

    def test_url_length_limit(self):
        """Test that URLs exceeding 1024 bytes are rejected."""
        # Create a URL that exceeds 1024 bytes
        # "gemini://example.org/" is 21 bytes, so we need path > 1003 bytes
        long_path = "a" * 1010  # This will make the total URL > 1024 bytes
        url = f"gemini://example.org/{long_path}"

        with pytest.raises(ValueError, match="URL must not exceed 1024 bytes"):
            parse_gemini_url(url)

    def test_invalid_port_range(self):
        """Test that invalid port numbers are rejected."""
        with pytest.raises(ValueError, match=r"Invalid port number|Port out of range"):
            parse_gemini_url("gemini://example.org:70000/")

    @pytest.mark.parametrize(
        "url",
        [
            "gemini://example.org/a\x00b",  # NUL
            "gemini://example.org/a\x0bb",  # vertical tab
            "gemini://example.org/a\x0cb",  # form feed
            "gemini://example.org/a\rb",  # CR (urlparse silently strips this)
            "gemini://example.org/a\nb",  # LF (request-line injection shape)
            "gemini://example.org/a\tb",  # TAB
            "gemini://example.org/a\x7fb",  # DEL
        ],
    )
    def test_control_characters_rejected(self, url):
        """Raw control characters anywhere in the URL must be rejected.

        urlparse silently strips CR/LF/TAB, which would otherwise mask a
        request-line injection attempt; other C0 bytes (NUL/VT/FF) survive into
        the on-wire request verbatim. Both must fail closed.
        """
        with pytest.raises(ValueError, match="control character"):
            parse_gemini_url(url)

    def test_raw_space_in_path_rejected(self):
        """A raw (unencoded) space in the path yields a malformed request line."""
        with pytest.raises(ValueError, match="space"):
            parse_gemini_url("gemini://example.org/a b")

    def test_url_wire_length_includes_crlf(self):
        """The on-wire request is ``<url>\\r\\n``; the 1024-byte Gemini cap
        covers the whole line, so the URL itself must be <= 1022 bytes."""
        base = "gemini://example.org/"  # 21 bytes
        ok = base + "a" * (1022 - len(base))  # 1022-byte URL -> 1024 on wire
        assert parse_gemini_url(ok).host == "example.org"

        too_long = base + "a" * (1023 - len(base))  # 1023-byte URL -> 1025 wire
        with pytest.raises(ValueError, match="1024 bytes"):
            parse_gemini_url(too_long)


class TestGeminiURLFormatting:
    """Test Gemini URL formatting functionality."""

    def test_basic_url_formatting(self):
        """Test formatting a basic Gemini URL."""
        url = format_gemini_url("example.org")
        assert url == "gemini://example.org/"

    def test_url_formatting_with_port(self):
        """Test formatting Gemini URL with custom port."""
        url = format_gemini_url("example.org", port=7070)
        assert url == "gemini://example.org:7070/"

    def test_url_formatting_default_port_omitted(self):
        """Test that default port 1965 is omitted."""
        url = format_gemini_url("example.org", port=1965)
        assert url == "gemini://example.org/"

    def test_url_formatting_with_path(self):
        """Test formatting Gemini URL with path."""
        url = format_gemini_url("example.org", path="/docs/spec.gmi")
        assert url == "gemini://example.org/docs/spec.gmi"

    def test_url_formatting_path_normalization(self):
        """Test that paths are normalized to start with /."""
        url = format_gemini_url("example.org", path="docs/spec.gmi")
        assert url == "gemini://example.org/docs/spec.gmi"

    def test_url_formatting_with_query(self):
        """Test formatting Gemini URL with query."""
        url = format_gemini_url("example.org", query="search=test")
        assert url == "gemini://example.org/?search=test"

    def test_url_formatting_complete(self):
        """Test formatting complete Gemini URL."""
        url = format_gemini_url(
            "example.org", port=7070, path="/search", query="q=gemini"
        )
        assert url == "gemini://example.org:7070/search?q=gemini"


class TestGeminiURLValidation:
    """Test Gemini URL component validation."""

    def test_valid_components(self):
        """Test validation of valid URL components."""
        # Should not raise any exception
        validate_gemini_url_components("example.org", 1965, "/path", "query=test")

    def test_empty_host(self):
        """Test that empty host is rejected."""
        with pytest.raises(ValueError, match="Host cannot be empty"):
            validate_gemini_url_components("", 1965, "/")

    def test_whitespace_host(self):
        """Test that whitespace-only host is rejected."""
        with pytest.raises(ValueError, match="Host cannot be empty"):
            validate_gemini_url_components("   ", 1965, "/")

    def test_invalid_port_low(self):
        """Test that port below 1 is rejected."""
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            validate_gemini_url_components("example.org", 0, "/")

    def test_invalid_port_high(self):
        """Test that port above 65535 is rejected."""
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            validate_gemini_url_components("example.org", 70000, "/")

    def test_invalid_path(self):
        """Test that path not starting with / is rejected."""
        with pytest.raises(ValueError, match="Path must start with '/'"):
            validate_gemini_url_components("example.org", 1965, "path")

    def test_url_length_limit_validation(self):
        """Test that resulting URL length is validated."""
        # Create components that would result in a URL > 1024 bytes
        # "gemini://example.org/" is 21 bytes, so path needs to be > 1003 bytes
        long_path = "/" + "a" * 1010  # This will make the total URL > 1024 bytes

        with pytest.raises(
            ValueError, match="Resulting URL would exceed 1024 byte limit"
        ):
            validate_gemini_url_components("example.org", 1965, long_path)


class TestGeminiURLModel:
    """Test GeminiURL Pydantic model."""

    def test_valid_gemini_url_model(self):
        """Test creating valid GeminiURL model."""
        url = GeminiURL(
            host="example.org", port=1965, path="/test", query="search=test"
        )

        assert url.host == "example.org"
        assert url.port == 1965
        assert url.path == "/test"
        assert url.query == "search=test"

    def test_gemini_url_defaults(self):
        """Test GeminiURL model defaults."""
        url = GeminiURL(host="example.org")

        assert url.host == "example.org"
        assert url.port == 1965
        assert url.path == "/"
        assert url.query is None

    def test_gemini_url_port_validation(self):
        """Test GeminiURL port validation."""
        with pytest.raises(ValidationError):
            GeminiURL(host="example.org", port=0)

        with pytest.raises(ValidationError):
            GeminiURL(host="example.org", port=70000)

    def test_gemini_url_host_validation(self):
        """Test GeminiURL host validation."""
        with pytest.raises(ValidationError):
            GeminiURL(host="")

        with pytest.raises(ValidationError):
            GeminiURL(host="   ")


class TestGeminiFetchRequest:
    """Test GeminiFetchRequest model."""

    def test_valid_gemini_fetch_request(self):
        """Test creating valid GeminiFetchRequest."""
        request = GeminiFetchRequest(url="gemini://example.org/")
        assert request.url == "gemini://example.org/"

    def test_invalid_scheme(self):
        """Test that non-Gemini URLs are rejected."""
        with pytest.raises(ValidationError, match="URL must start with 'gemini://'"):
            GeminiFetchRequest(url="http://example.org/")

    def test_url_length_validation(self):
        """Test URL length validation in request model."""
        # Create a URL that exceeds 1024 bytes
        long_url = "gemini://example.org/" + "a" * 1010

        with pytest.raises(ValidationError, match="URL must not exceed 1024 bytes"):
            GeminiFetchRequest(url=long_url)

    def test_gemini_fetch_request_examples(self):
        """Test that example URLs in the model are valid."""
        examples = [
            "gemini://gemini.circumlunar.space/",
            "gemini://gemini.circumlunar.space/docs/specification.gmi",
        ]

        for example_url in examples:
            request = GeminiFetchRequest(url=example_url)
            assert request.url == example_url


class TestGeminiURLRoundTrip:
    """Test round-trip parsing and formatting."""

    def test_parse_format_roundtrip(self):
        """Test that parsing and formatting are consistent."""
        original_urls = [
            "gemini://example.org/",
            "gemini://example.org:7070/",
            "gemini://example.org/path",
            "gemini://example.org/path?query=test",
            "gemini://example.org:7070/path?query=test",
        ]

        for original_url in original_urls:
            parsed = parse_gemini_url(original_url)
            formatted = format_gemini_url(
                parsed.host, parsed.port, parsed.path, parsed.query
            )

            # Parse again to compare components
            reparsed = parse_gemini_url(formatted)

            assert reparsed.host == parsed.host
            assert reparsed.port == parsed.port
            assert reparsed.path == parsed.path
            assert reparsed.query == parsed.query


class TestGeminiUtilityFunctions:
    """Test additional utility functions for better coverage."""

    def test_atomic_write_json(self):
        """Test atomic JSON writing utility."""
        import json
        import tempfile
        from pathlib import Path

        from gopher_mcp.utils import atomic_write_json

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.json"
            test_data = {"test": "data", "number": 42}

            # Write data atomically
            atomic_write_json(str(file_path), test_data)

            # Verify file exists and contains correct data
            assert file_path.exists()
            with open(file_path) as f:
                loaded_data = json.load(f)
            assert loaded_data == test_data

    def test_atomic_write_json_nested_directory(self):
        """Test atomic JSON writing with nested directory creation."""
        import json
        import tempfile
        from pathlib import Path

        from gopher_mcp.utils import atomic_write_json

        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = Path(temp_dir) / "nested" / "dir" / "test.json"
            test_data = {"nested": True}

            # Write data atomically (should create directories)
            atomic_write_json(str(nested_path), test_data)

            # Verify file exists and contains correct data
            assert nested_path.exists()
            with open(nested_path) as f:
                loaded_data = json.load(f)
            assert loaded_data == test_data

    def test_get_home_directory(self):
        """Test home directory utility function."""
        from gopher_mcp.utils import get_home_directory

        home_dir = get_home_directory()
        assert home_dir is not None
        assert home_dir.exists()
        assert home_dir.is_dir()

    def test_get_home_directory_fallback(self):
        """Test home directory fallback handling."""
        import os
        from pathlib import Path
        from unittest.mock import patch

        from gopher_mcp.utils import get_home_directory

        # Test fallback to environment variables
        with patch("pathlib.Path.home", side_effect=Exception("No home")):
            with patch.dict(os.environ, {"HOME": "/tmp"}, clear=False):
                home_dir = get_home_directory()
                assert home_dir is not None
                assert home_dir == Path("/tmp")

    def test_guess_mime_type(self):
        """Test MIME type guessing functionality."""
        from gopher_mcp.utils import guess_mime_type

        # Test various gopher types
        assert guess_mime_type("0") == "text/plain"
        assert guess_mime_type("1") == "text/gopher-menu"
        assert guess_mime_type("g") == "image/gif"
        assert guess_mime_type("I") == "image/jpeg"
        assert guess_mime_type("9") == "application/octet-stream"

    def test_detect_binary_mime_type(self):
        """Test binary MIME type detection."""
        from gopher_mcp.utils import detect_binary_mime_type

        # Test PNG detection
        png_header = b"\x89PNG\r\n\x1a\n" + b"x" * 8
        assert detect_binary_mime_type(png_header) == "image/png"

        # Test JPEG detection
        jpeg_header = b"\xff\xd8\xff" + b"x" * 13
        assert detect_binary_mime_type(jpeg_header) == "image/jpeg"

        # Test PDF detection
        pdf_header = b"%PDF-1.4" + b"x" * 8
        assert detect_binary_mime_type(pdf_header) == "application/pdf"

        # Test empty content
        assert detect_binary_mime_type(b"") == "application/octet-stream"

    def test_validate_gemini_mime_type(self):
        """Test Gemini MIME type validation."""
        from gopher_mcp.models import GeminiMimeType
        from gopher_mcp.utils import validate_gemini_mime_type

        # Test valid MIME type
        valid_mime = GeminiMimeType(type="text", subtype="plain", charset="utf-8")
        assert validate_gemini_mime_type(valid_mime) is True

        # Test invalid MIME type (empty type)
        invalid_mime = GeminiMimeType(type="", subtype="plain", charset="utf-8")
        assert validate_gemini_mime_type(invalid_mime) is False

    def test_parse_gemtext_functionality(self):
        """Test gemtext parsing functionality."""
        from gopher_mcp.utils import parse_gemtext

        # Test basic gemtext parsing
        content = "# Heading\nRegular text\n=> /link Link text"
        document = parse_gemtext(content)

        assert len(document.lines) == 3
        assert document.lines[0].type == "heading1"
        assert document.lines[1].type == "text"
        assert document.lines[2].type == "link"

    def test_format_gopher_url_with_search(self):
        """Test Gopher URL formatting with search parameter."""
        from gopher_mcp.utils import format_gopher_url

        # Test with search parameter for type 7 (search)
        url = format_gopher_url(
            host="example.com",
            port=70,
            gopher_type="7",
            selector="/search",
            search="test query",
        )

        assert url == "gopher://example.com/7/search%09test query"

    def test_format_gopher_url_non_standard_port(self):
        """Test Gopher URL formatting with non-standard port."""
        from gopher_mcp.utils import format_gopher_url

        url = format_gopher_url(
            host="example.com", port=7070, gopher_type="1", selector="/menu"
        )

        assert url == "gopher://example.com:7070/1/menu"

    def test_guess_mime_type_with_selector(self):
        """Test MIME type guessing with selector hints."""
        from gopher_mcp.utils import guess_mime_type

        # Test with file extension hints in selector
        mime_type = guess_mime_type("0", "/documents/readme.txt")
        assert mime_type == "text/plain"

        # Test with image extension
        mime_type = guess_mime_type("9", "/images/photo.jpg")
        assert mime_type == "image/jpeg"


class TestGeminiUrlPortHandling:
    """Regression tests for Gemini URL port parsing fixes."""

    def test_port_zero_is_rejected(self):
        from gopher_mcp.utils import parse_gemini_url

        with pytest.raises(ValueError, match=r"[Pp]ort"):
            parse_gemini_url("gemini://example.org:0/")

    def test_port_out_of_range_friendly_message(self):
        from gopher_mcp.utils import parse_gemini_url

        with pytest.raises(ValueError, match="Invalid port"):
            parse_gemini_url("gemini://example.org:99999/")


class TestGemtextParsingRobustness:
    """Regression tests for gemtext line-splitting and preformat handling."""

    def test_preformat_preserves_trailing_whitespace(self):
        from gopher_mcp.utils import parse_gemtext

        content = "```\ncode with trailing   \n```"
        document = parse_gemtext(content)
        pre_contents = [
            line.content for line in document.lines if line.type == "preformat"
        ]
        assert "code with trailing   " in pre_contents

    def test_preformat_content_lines_serialize_lean(self):
        """A code block must not repeat a 6-key metadata dict (plus duplicated
        alt_text/language) on every content line -- that tripled the serialized
        size of code blocks. Content lines serialize to just content+is_toggle."""
        from gopher_mcp.utils import parse_gemtext

        document = parse_gemtext("```python\nprint(1)\nprint(2)\n```")
        dumped = document.model_dump()
        content_lines = [
            line
            for line in dumped["lines"]
            if line["type"] == "preformat" and line["preformat"]["is_toggle"] is False
        ]
        assert len(content_lines) == 2
        for line in content_lines:
            assert set(line["preformat"].keys()) == {"content", "is_toggle"}
        # The opening toggle still carries the block-level language/metadata.
        opening = next(
            line
            for line in dumped["lines"]
            if line["type"] == "preformat" and line["preformat"]["is_toggle"] is True
        )
        assert opening["preformat"]["language"] == "python"

    def test_does_not_split_on_vertical_tab(self):
        from gopher_mcp.utils import parse_gemtext

        # Vertical tab is not a gemtext line terminator; must stay one line.
        document = parse_gemtext("line1\x0bstill line1")
        assert len(document.lines) == 1

    def test_does_not_split_on_form_feed(self):
        from gopher_mcp.utils import parse_gemtext

        document = parse_gemtext("a\x0cb")
        assert len(document.lines) == 1

    def test_crlf_and_lf_both_split_lines(self):
        from gopher_mcp.utils import parse_gemtext

        document = parse_gemtext("a\r\nb\nc")
        assert len(document.lines) == 3

    def test_heading_without_space_is_parsed(self):
        from gopher_mcp.utils import parse_gemtext

        line = parse_gemtext("#NoSpace").lines[0]
        assert line.type == "heading1"
        assert line.heading.text == "NoSpace"

    def test_extra_hash_not_kept_in_heading_text(self):
        from gopher_mcp.utils import parse_gemtext

        # A 4th '#' is content, not a 4th level: cap at H3 and don't leak '#'.
        line = parse_gemtext("#### four").lines[0]
        assert line.type == "heading3"
        assert line.heading.text == "four"

    def test_quote_strips_only_one_leading_space(self):
        from gopher_mcp.utils import parse_gemtext

        # Convention removes at most one space after '>', preserving intentional
        # inner indentation of the quoted text.
        line = parse_gemtext(">  two leading spaces").lines[0]
        assert line.type == "quote"
        assert line.quote.text == " two leading spaces"


class TestGeminiResponseErrorMessages:
    """parse_gemini_response must not double-wrap its own validation errors."""

    def test_validation_error_not_double_wrapped(self):
        from gopher_mcp.utils import parse_gemini_response

        # "2\r\n" -> status line "2" is too short; the message must be the
        # original validation error, not "Failed to parse response: ...".
        with pytest.raises(ValueError, match=r"^Status line too short$"):
            parse_gemini_response(b"2\r\n")
