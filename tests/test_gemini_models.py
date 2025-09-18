"""Tests for Gemini protocol models."""

import pytest
from pydantic import ValidationError

from gopher_mcp.models import (
    GeminiStatusCode,
    GeminiMimeType,
    GeminiResponse,
    GeminiSuccessResult,
    GeminiInputResult,
    GeminiRedirectResult,
    GeminiErrorResult,
    GeminiCertificateResult,
    GeminiGemtextResult,
    GemtextLineType,
    GemtextLink,
    GemtextLine,
    GemtextDocument,
    GeminiCertificateInfo,
    TOFUEntry,
    GeminiCacheEntry,
)


class TestGeminiStatusCode:
    """Test GeminiStatusCode enum."""

    def test_status_code_values(self):
        """Test that status codes have correct values."""
        assert GeminiStatusCode.INPUT == 10
        assert GeminiStatusCode.SENSITIVE_INPUT == 11
        assert GeminiStatusCode.SUCCESS == 20
        assert GeminiStatusCode.TEMPORARY_REDIRECT == 30
        assert GeminiStatusCode.PERMANENT_REDIRECT == 31
        assert GeminiStatusCode.TEMPORARY_FAILURE == 40
        assert GeminiStatusCode.NOT_FOUND == 51
        assert GeminiStatusCode.CERTIFICATE_REQUIRED == 60

    def test_status_code_ranges(self):
        """Test status code ranges."""
        # Input expected (10-19)
        assert 10 <= GeminiStatusCode.INPUT < 20
        assert 10 <= GeminiStatusCode.SENSITIVE_INPUT < 20

        # Success (20-29)
        assert 20 <= GeminiStatusCode.SUCCESS < 30

        # Redirection (30-39)
        assert 30 <= GeminiStatusCode.TEMPORARY_REDIRECT < 40
        assert 30 <= GeminiStatusCode.PERMANENT_REDIRECT < 40

        # Temporary failure (40-49)
        assert 40 <= GeminiStatusCode.TEMPORARY_FAILURE < 50

        # Permanent failure (50-59)
        assert 50 <= GeminiStatusCode.NOT_FOUND < 60

        # Client certificates (60-69)
        assert 60 <= GeminiStatusCode.CERTIFICATE_REQUIRED < 70


class TestGeminiMimeType:
    """Test GeminiMimeType model."""

    def test_basic_mime_type(self):
        """Test basic MIME type creation."""
        mime = GeminiMimeType(type="text", subtype="gemini")

        assert mime.type == "text"
        assert mime.subtype == "gemini"
        assert mime.charset == "utf-8"  # default
        assert mime.lang is None
        assert mime.full_type == "text/gemini"
        assert mime.is_text is True
        assert mime.is_gemtext is True

    def test_mime_type_with_charset(self):
        """Test MIME type with custom charset."""
        mime = GeminiMimeType(type="text", subtype="plain", charset="iso-8859-1")

        assert mime.charset == "iso-8859-1"
        assert mime.full_type == "text/plain"
        assert mime.is_text is True
        assert mime.is_gemtext is False

    def test_mime_type_with_language(self):
        """Test MIME type with language tag."""
        mime = GeminiMimeType(type="text", subtype="gemini", lang="en-US")

        assert mime.lang == "en-US"
        assert mime.is_gemtext is True

    def test_binary_mime_type(self):
        """Test binary MIME type."""
        mime = GeminiMimeType(type="image", subtype="jpeg")

        assert mime.full_type == "image/jpeg"
        assert mime.is_text is False
        assert mime.is_gemtext is False
        assert mime.is_binary is True
        assert mime.is_image is True
        assert mime.is_audio is False
        assert mime.is_video is False
        assert mime.is_application is False

    def test_audio_mime_type(self):
        """Test audio MIME type."""
        mime = GeminiMimeType(type="audio", subtype="mpeg")

        assert mime.full_type == "audio/mpeg"
        assert mime.is_text is False
        assert mime.is_binary is True
        assert mime.is_image is False
        assert mime.is_audio is True
        assert mime.is_video is False
        assert mime.is_application is False

    def test_video_mime_type(self):
        """Test video MIME type."""
        mime = GeminiMimeType(type="video", subtype="mp4")

        assert mime.full_type == "video/mp4"
        assert mime.is_text is False
        assert mime.is_binary is True
        assert mime.is_image is False
        assert mime.is_audio is False
        assert mime.is_video is True
        assert mime.is_application is False

    def test_application_mime_type(self):
        """Test application MIME type."""
        mime = GeminiMimeType(type="application", subtype="pdf")

        assert mime.full_type == "application/pdf"
        assert mime.is_text is False
        assert mime.is_binary is True
        assert mime.is_image is False
        assert mime.is_audio is False
        assert mime.is_video is False
        assert mime.is_application is True

    def test_charset_support(self):
        """Test charset support detection."""
        text_mime = GeminiMimeType(type="text", subtype="plain")
        binary_mime = GeminiMimeType(type="image", subtype="png")

        assert text_mime.supports_charset() is True
        assert binary_mime.supports_charset() is False

    def test_file_extensions(self):
        """Test file extension detection."""
        test_cases = [
            ("text", "gemini", ".gmi"),
            ("text", "plain", ".txt"),
            ("text", "html", ".html"),
            ("image", "jpeg", ".jpg"),
            ("image", "png", ".png"),
            ("audio", "mpeg", ".mp3"),
            ("video", "mp4", ".mp4"),
            ("application", "pdf", ".pdf"),
            ("application", "zip", ".zip"),
            ("unknown", "type", ""),  # Unknown type should return empty string
        ]

        for mime_type, subtype, expected_ext in test_cases:
            mime = GeminiMimeType(type=mime_type, subtype=subtype)
            assert mime.get_file_extension() == expected_ext


class TestGeminiResponse:
    """Test GeminiResponse model."""

    def test_basic_response(self):
        """Test basic response creation."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="text/gemini", body=b"Hello, Gemini!"
        )

        assert response.status == GeminiStatusCode.SUCCESS
        assert response.meta == "text/gemini"
        assert response.body == b"Hello, Gemini!"

    def test_response_without_body(self):
        """Test response without body."""
        response = GeminiResponse(
            status=GeminiStatusCode.INPUT, meta="Enter search terms"
        )

        assert response.status == GeminiStatusCode.INPUT
        assert response.meta == "Enter search terms"
        assert response.body is None

    def test_meta_length_validation(self):
        """Test meta field length validation."""
        long_meta = "a" * 1025  # Exceeds 1024 byte limit

        with pytest.raises(ValidationError, match="Meta field too long"):
            GeminiResponse(status=GeminiStatusCode.SUCCESS, meta=long_meta)


class TestGeminiResultModels:
    """Test Gemini result models."""

    def test_success_result(self):
        """Test GeminiSuccessResult model."""
        mime_type = GeminiMimeType(type="text", subtype="plain")
        result = GeminiSuccessResult(
            mimeType=mime_type,
            content="Hello, world!",
            size=13,
            requestInfo={"url": "gemini://example.org/"},
        )

        assert result.kind == "success"
        assert result.mime_type == mime_type
        assert result.content == "Hello, world!"
        assert result.size == 13
        assert result.request_info["url"] == "gemini://example.org/"

    def test_input_result(self):
        """Test GeminiInputResult model."""
        result = GeminiInputResult(
            prompt="Enter search terms",
            sensitive=False,
            requestInfo={"url": "gemini://example.org/search"},
        )

        assert result.kind == "input"
        assert result.prompt == "Enter search terms"
        assert result.sensitive is False

    def test_sensitive_input_result(self):
        """Test sensitive input result."""
        result = GeminiInputResult(prompt="Enter password", sensitive=True)

        assert result.sensitive is True

    def test_redirect_result(self):
        """Test GeminiRedirectResult model."""
        result = GeminiRedirectResult(newUrl="/new-location", permanent=True)

        assert result.kind == "redirect"
        assert result.new_url == "/new-location"
        assert result.permanent is True

    def test_temporary_redirect_result(self):
        """Test temporary redirect result."""
        result = GeminiRedirectResult(newUrl="/temp-location")

        assert result.permanent is False  # default

    def test_error_result(self):
        """Test GeminiErrorResult model."""
        result = GeminiErrorResult(
            error={
                "code": "NOT_FOUND",
                "message": "The requested resource was not found",
                "status": 51,
            }
        )

        assert result.kind == "error"
        assert result.error["code"] == "NOT_FOUND"
        assert result.error["status"] == 51

    def test_certificate_result(self):
        """Test GeminiCertificateResult model."""
        result = GeminiCertificateResult(
            message="Certificate required for access", required=True
        )

        assert result.kind == "certificate"
        assert result.message == "Certificate required for access"
        assert result.required is True


class TestGemtextModels:
    """Test gemtext content models."""

    def test_gemtext_line_types(self):
        """Test GemtextLineType enum values."""
        assert GemtextLineType.TEXT == "text"
        assert GemtextLineType.LINK == "link"
        assert GemtextLineType.HEADING_1 == "heading1"
        assert GemtextLineType.HEADING_2 == "heading2"
        assert GemtextLineType.HEADING_3 == "heading3"
        assert GemtextLineType.LIST_ITEM == "list"
        assert GemtextLineType.QUOTE == "quote"
        assert GemtextLineType.PREFORMAT == "preformat"

    def test_gemtext_link(self):
        """Test GemtextLink model."""
        link = GemtextLink(url="gemini://example.org/", text="Example Site")

        assert link.url == "gemini://example.org/"
        assert link.text == "Example Site"

    def test_gemtext_link_without_text(self):
        """Test GemtextLink without text."""
        link = GemtextLink(url="/local/path")

        assert link.url == "/local/path"
        assert link.text is None

    def test_gemtext_link_empty_url_validation(self):
        """Test that empty URLs are rejected."""
        with pytest.raises(ValidationError, match="Link URL cannot be empty"):
            GemtextLink(url="")

    def test_gemtext_link_whitespace_url_validation(self):
        """Test that whitespace-only URLs are rejected."""
        with pytest.raises(ValidationError, match="Link URL cannot be empty"):
            GemtextLink(url="   ")

    def test_gemtext_line_text(self):
        """Test text line."""
        line = GemtextLine(type=GemtextLineType.TEXT, content="This is a text line.")

        assert line.type == GemtextLineType.TEXT
        assert line.content == "This is a text line."
        assert line.link is None
        assert line.level is None
        assert line.alt_text is None

    def test_gemtext_line_link(self):
        """Test link line."""
        link = GemtextLink(url="/about", text="About")
        line = GemtextLine(
            type=GemtextLineType.LINK, content="=> /about About", link=link
        )

        assert line.type == GemtextLineType.LINK
        assert line.link == link

    def test_gemtext_line_heading(self):
        """Test heading line."""
        line = GemtextLine(
            type=GemtextLineType.HEADING_1, content="# Main Heading", level=1
        )

        assert line.type == GemtextLineType.HEADING_1
        assert line.level == 1

    def test_gemtext_line_preformat(self):
        """Test preformat line."""
        line = GemtextLine(
            type=GemtextLineType.PREFORMAT, content="```python", alt_text="python"
        )

        assert line.type == GemtextLineType.PREFORMAT
        assert line.alt_text == "python"

    def test_gemtext_document(self):
        """Test GemtextDocument model."""
        lines = [
            GemtextLine(type=GemtextLineType.HEADING_1, content="# Title", level=1),
            GemtextLine(type=GemtextLineType.TEXT, content="Some text."),
            GemtextLine(
                type=GemtextLineType.LINK,
                content="=> /about About",
                link=GemtextLink(url="/about", text="About"),
            ),
        ]

        links = [GemtextLink(url="/about", text="About")]

        doc = GemtextDocument(lines=lines, links=links)

        assert len(doc.lines) == 3
        assert doc.link_count == 1
        assert doc.has_headings is True

    def test_gemtext_document_no_headings(self):
        """Test document without headings."""
        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Just text."),
        ]

        doc = GemtextDocument(lines=lines)

        assert doc.has_headings is False
        assert doc.link_count == 0

    def test_gemini_gemtext_result(self):
        """Test GeminiGemtextResult model."""
        doc = GemtextDocument(
            lines=[GemtextLine(type=GemtextLineType.TEXT, content="Hello")], links=[]
        )

        result = GeminiGemtextResult(document=doc, rawContent="Hello", size=5)

        assert result.kind == "gemtext"
        assert result.document == doc
        assert result.raw_content == "Hello"
        assert result.charset == "utf-8"  # default
        assert result.size == 5


class TestSecurityModels:
    """Test certificate and security models."""

    def test_certificate_info(self):
        """Test GeminiCertificateInfo model."""
        cert = GeminiCertificateInfo(
            fingerprint="sha256:1234567890abcdef",
            subject="CN=example.org",
            issuer="CN=example.org",
            not_before="2024-01-01T00:00:00Z",
            not_after="2025-01-01T00:00:00Z",
            host="example.org",
        )

        assert cert.fingerprint == "sha256:1234567890abcdef"
        assert cert.host == "example.org"
        assert cert.port == 1965  # default
        assert cert.path == "/"  # default

    def test_tofu_entry(self):
        """Test TOFUEntry model."""
        entry = TOFUEntry(
            host="example.org",
            fingerprint="sha256:abcdef1234567890",
            first_seen=1640995200.0,
            last_seen=1640995200.0,
            expires=1672531200.0,
        )

        assert entry.host == "example.org"
        assert entry.port == 1965  # default
        assert entry.fingerprint == "sha256:abcdef1234567890"
        assert not entry.is_expired(1640995200.0)  # Before expiry
        assert entry.is_expired(1672531300.0)  # After expiry

    def test_tofu_entry_no_expiry(self):
        """Test TOFU entry without expiry."""
        entry = TOFUEntry(
            host="example.org",
            fingerprint="sha256:abcdef1234567890",
            first_seen=1640995200.0,
            last_seen=1640995200.0,
        )

        assert entry.expires is None
        assert not entry.is_expired(9999999999.0)  # Never expires

    def test_cache_entry(self):
        """Test GeminiCacheEntry model."""
        response = GeminiSuccessResult(
            mimeType=GeminiMimeType(type="text", subtype="plain"),
            content="Cached content",
            size=14,
        )

        entry = GeminiCacheEntry(
            key="gemini://example.org/", value=response, timestamp=1640995200.0, ttl=300
        )

        assert entry.key == "gemini://example.org/"
        assert entry.value == response
        assert not entry.is_expired(1640995300.0)  # Within TTL
        assert entry.is_expired(1640995600.0)  # After TTL


class TestGemtextDocumentProperties:
    """Test GemtextDocument property methods."""

    def test_content_summary_property(self):
        """Test content_summary property method."""
        from gopher_mcp.models import (
            GemtextHeading,
            GemtextList,
            GemtextQuote,
            GemtextPreformat,
        )

        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Regular text"),
            GemtextLine(
                type=GemtextLineType.HEADING_1,
                content="# Heading 1",
                heading=GemtextHeading(
                    level=1, text="Heading 1", raw_content="# Heading 1"
                ),
            ),
            GemtextLine(
                type=GemtextLineType.LINK,
                content="=> /test Link text",
                link=GemtextLink(url="/test", text="Link text"),
            ),
            GemtextLine(
                type=GemtextLineType.LIST_ITEM,
                content="* List item",
                list_item=GemtextList(text="List item", raw_content="* List item"),
            ),
            GemtextLine(
                type=GemtextLineType.QUOTE,
                content="> Quote text",
                quote=GemtextQuote(text="Quote text", raw_content="> Quote text"),
            ),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="```",
                preformat=GemtextPreformat(content="```", is_toggle=True, alt_text=""),
            ),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="code",
                preformat=GemtextPreformat(
                    content="code", is_toggle=False, alt_text=""
                ),
            ),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="```",
                preformat=GemtextPreformat(content="```", is_toggle=True, alt_text=""),
            ),
        ]

        document = GemtextDocument(lines=lines)
        summary = document.content_summary

        assert summary["text_lines"] == 1
        assert summary["headings"] == 1
        assert summary["links"] == 1
        assert summary["list_items"] == 1
        assert summary["quotes"] == 1
        assert summary["preformat_blocks"] == 1

    def test_heading_hierarchy_property(self):
        """Test heading_hierarchy property method."""
        from gopher_mcp.models import GemtextHeading

        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Text"),
            GemtextLine(
                type=GemtextLineType.HEADING_1,
                content="# Main Heading",
                heading=GemtextHeading(
                    level=1, text="Main Heading", raw_content="# Main Heading"
                ),
            ),
            GemtextLine(
                type=GemtextLineType.HEADING_2,
                content="## Sub Heading",
                heading=GemtextHeading(
                    level=2, text="Sub Heading", raw_content="## Sub Heading"
                ),
            ),
        ]

        document = GemtextDocument(lines=lines)
        hierarchy = document.heading_hierarchy

        assert len(hierarchy) == 2
        assert hierarchy[0]["line_number"] == 2
        assert hierarchy[0]["level"] == 1
        assert hierarchy[0]["text"] == "Main Heading"
        assert hierarchy[1]["line_number"] == 3
        assert hierarchy[1]["level"] == 2
        assert hierarchy[1]["text"] == "Sub Heading"

    def test_text_content_property(self):
        """Test text_content property method."""
        from gopher_mcp.models import (
            GemtextHeading,
            GemtextList,
            GemtextQuote,
            GemtextPreformat,
        )

        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Regular text"),
            GemtextLine(
                type=GemtextLineType.HEADING_1,
                content="# Heading",
                heading=GemtextHeading(
                    level=1, text="Heading", raw_content="# Heading"
                ),
            ),
            GemtextLine(
                type=GemtextLineType.LIST_ITEM,
                content="* List item",
                list_item=GemtextList(text="List item", raw_content="* List item"),
            ),
            GemtextLine(
                type=GemtextLineType.QUOTE,
                content="> Quote",
                quote=GemtextQuote(text="Quote", raw_content="> Quote"),
            ),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="```",
                preformat=GemtextPreformat(content="```", is_toggle=True, alt_text=""),
            ),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="code content",
                preformat=GemtextPreformat(
                    content="code content", is_toggle=False, alt_text=""
                ),
            ),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="```",
                preformat=GemtextPreformat(content="```", is_toggle=True, alt_text=""),
            ),
        ]

        document = GemtextDocument(lines=lines)
        text_content = document.text_content

        expected_lines = [
            "Regular text",
            "Heading",
            "List item",
            "Quote",
            "code content",
        ]
        assert text_content == "\n".join(expected_lines)

    def test_line_count_property(self):
        """Test line_count property method."""
        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Line 1"),
            GemtextLine(type=GemtextLineType.TEXT, content="Line 2"),
            GemtextLine(type=GemtextLineType.TEXT, content="Line 3"),
        ]

        document = GemtextDocument(lines=lines)
        assert document.line_count == 3


class TestGeminiGemtextResultProperties:
    """Test GeminiGemtextResult property methods."""

    def test_summary_property(self):
        """Test summary property method."""
        link = GemtextLink(url="/test", text="Link")
        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Text"),
            GemtextLine(type=GemtextLineType.LINK, content="=> /test Link", link=link),
        ]
        document = GemtextDocument(lines=lines, links=[link])

        result = GeminiGemtextResult(
            document=document,
            rawContent="Text\n=> /test Link",
            size=20,
            charset="utf-8",
            lang="en",
        )

        summary = result.summary
        assert summary["content_type"] == "gemtext"
        assert summary["line_count"] == 2
        assert summary["link_count"] == 1
        assert summary["charset"] == "utf-8"
        assert summary["language"] == "en"
        assert summary["size_bytes"] == 20

    def test_plain_text_property(self):
        """Test plain_text property method."""
        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Plain text content"),
        ]
        document = GemtextDocument(lines=lines)

        result = GeminiGemtextResult(
            document=document, rawContent="Plain text content", size=18
        )

        assert result.plain_text == "Plain text content"

    def test_structured_content_property(self):
        """Test structured_content property method."""
        from gopher_mcp.models import GemtextHeading

        link1 = GemtextLink(url="/internal", text="Internal link")
        link2 = GemtextLink(url="https://example.com", text="External link")

        lines = [
            GemtextLine(
                type=GemtextLineType.HEADING_1,
                content="# Title",
                heading=GemtextHeading(level=1, text="Title", raw_content="# Title"),
            ),
            GemtextLine(
                type=GemtextLineType.LINK,
                content="=> /internal Internal link",
                link=link1,
            ),
            GemtextLine(
                type=GemtextLineType.LINK,
                content="=> https://example.com External link",
                link=link2,
            ),
        ]
        document = GemtextDocument(lines=lines, links=[link1, link2])

        result = GeminiGemtextResult(
            document=document,
            rawContent="# Title\n=> /internal Internal link\n=> https://example.com External link",
            size=70,
        )

        structured = result.structured_content
        assert "summary" in structured
        assert "headings" in structured
        assert "links" in structured
        assert "content_blocks" in structured

        # Check link types
        links = structured["links"]
        assert len(links) == 2
        assert links[0]["type"] == "internal"
        assert links[1]["type"] == "external"

        # Check content blocks structure
        blocks = structured["content_blocks"]
        assert len(blocks) == 3
        assert blocks[0]["structured_data"]["heading"]["level"] == 1
        assert blocks[1]["structured_data"]["link"]["url"] == "/internal"
