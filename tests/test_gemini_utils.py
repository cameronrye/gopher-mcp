"""Tests for Gemini protocol utilities."""

import pytest
from pydantic import ValidationError

from gopher_mcp.models import GeminiURL, GeminiFetchRequest
from gopher_mcp.utils import (
    parse_gemini_url,
    format_gemini_url,
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
        with pytest.raises(ValueError, match="Invalid port number|Port out of range"):
            parse_gemini_url("gemini://example.org:70000/")


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
