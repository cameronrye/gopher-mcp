"""Tests for Gemini protocol models."""

import pytest
from pydantic import ValidationError

from gopher_mcp.models import (
    GeminiCacheEntry,
    GeminiCertificateInfo,
    GeminiCertificateResult,
    GeminiErrorResult,
    GeminiGemtextResult,
    GeminiInputResult,
    GeminiMimeType,
    GeminiRedirectResult,
    GeminiResponse,
    GeminiStatusCode,
    GeminiSuccessResult,
    GemtextDocument,
    GemtextLine,
    GemtextLineType,
    GemtextLink,
    TOFUEntry,
    TOFUTrustEntry,
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
        # Input expected: status codes 10 through 19
        assert 10 <= GeminiStatusCode.INPUT < 20
        assert 10 <= GeminiStatusCode.SENSITIVE_INPUT < 20

        # Success: status codes 20 through 29
        assert 20 <= GeminiStatusCode.SUCCESS < 30

        # Redirection: status codes 30 through 39
        assert 30 <= GeminiStatusCode.TEMPORARY_REDIRECT < 40
        assert 30 <= GeminiStatusCode.PERMANENT_REDIRECT < 40

        # Temporary failure: status codes 40 through 49
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

    def test_audio_mime_type(self):
        """Test audio MIME type."""
        mime = GeminiMimeType(type="audio", subtype="mpeg")

        assert mime.full_type == "audio/mpeg"
        assert mime.is_text is False
        assert mime.is_binary is True


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

    def test_gemtext_line_serialization_omits_null_fields(self):
        """The serialized line drops the always-null per-line fields to cut LLM
        token cost (a text line carried 7 null fields before)."""
        line = GemtextLine(type=GemtextLineType.TEXT, content="hello")
        assert line.model_dump() == {"type": "text", "content": "hello"}

    def test_gemtext_line_serialization_keeps_populated_fields(self):
        """Populated fields still serialize, and nothing repeats `content`."""
        line = GemtextLine(
            type=GemtextLineType.HEADING_1,
            content="# Hi",
            text="Hi",
            level=1,
        )
        dumped = line.model_dump()
        assert dumped == {
            "type": "heading1",
            "content": "# Hi",
            "text": "Hi",
            "level": 1,
        }

    def test_gemtext_line_has_no_nested_copy_of_itself(self):
        """The nested heading/list_item/quote/preformat objects are gone.

        Each of them carried a `raw_content` (or `content`) repeating the line
        verbatim, so a page serialized every line two or three times.
        """
        for gone in ("heading", "list_item", "quote", "preformat"):
            assert gone not in GemtextLine.model_fields

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
        assert len(doc.links) == 1

    def test_gemtext_document_defaults_to_no_links(self):
        """Test document without extracted links."""
        lines = [
            GemtextLine(type=GemtextLineType.TEXT, content="Just text."),
        ]

        doc = GemtextDocument(lines=lines)

        assert doc.links == []

    def test_gemtext_line_preformat_language(self):
        """A preformat opening toggle names the block's language."""
        line = GemtextLine(
            type=GemtextLineType.PREFORMAT,
            content="```python",
            alt_text="python",
            language="python",
        )

        assert line.model_dump() == {
            "type": "preformat",
            "content": "```python",
            "alt_text": "python",
            "language": "python",
        }

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


class TestGemtextParsing:
    """Parsing behaviour that the line model has to preserve.

    These belong beside the other ``parse_gemtext`` regressions in
    tests/test_gemini_utils.py; they are here because that file is not this
    change's to edit.
    """

    def test_list_item_is_recognised_and_its_marker_stripped(self):
        """The `* ` line type had no test at all, so nothing pinned it."""
        from gopher_mcp.utils import parse_gemtext

        line = parse_gemtext("* item one").lines[0]

        assert line.type == GemtextLineType.LIST_ITEM
        assert line.content == "* item one"
        assert line.text == "item one"

    def test_a_bare_asterisk_is_text_not_a_list_item(self):
        """Gemtext requires the space: `*emphasis*` is prose, not a list."""
        from gopher_mcp.utils import parse_gemtext

        assert parse_gemtext("*not a list*").lines[0].type == GemtextLineType.TEXT

    def test_list_item_carries_no_control_characters(self):
        """The document is sanitized before it is split, so a list item cannot
        smuggle an ANSI escape into a terminal or the model's context."""
        from gopher_mcp.utils import parse_gemtext

        line = parse_gemtext("* \x1b[31mitem").lines[0]

        assert line.type == GemtextLineType.LIST_ITEM
        assert "\x1b" not in line.content
        assert line.text == "[31mitem"

    def test_link_line_without_a_url_falls_back_to_text(self):
        """A bare `=>` carries no target, so it must not become a link line
        with an empty URL."""
        from gopher_mcp.utils import parse_gemtext

        line = parse_gemtext("=> ").lines[0]

        assert line.type == GemtextLineType.TEXT
        assert line.link is None
        assert parse_gemtext("=> ").links == []

    def test_a_link_url_never_carries_a_control_character(self):
        """The whole document is sanitized before it is split, so an ANSI escape
        in a link target is already gone by the time the URL is parsed -- it
        does not survive into `link.url` or the document's link list."""
        from gopher_mcp.utils import parse_gemtext

        document = parse_gemtext("=> \x1b[2J Clear your screen")

        assert document.lines[0].type == GemtextLineType.LINK
        assert document.lines[0].link.url == "[2J"
        assert "\x1b" not in str(document.model_dump())

    def test_serialized_lines_do_not_repeat_the_document(self):
        """One copy of each line: `type` says what the marker was, `content`
        carries the line, and only the resolved link, level, marker-stripped
        text and preformat alt-text/language are added."""
        from gopher_mcp.utils import parse_gemtext

        document = parse_gemtext(
            "# Title\n* item\n> quoted\n=> /a A link\n```python\ncode\n```",
            "gemini://example.org/index.gmi",
        )
        dumped = document.model_dump()["lines"]

        assert dumped[0] == {
            "type": "heading1",
            "content": "# Title",
            "text": "Title",
            "level": 1,
        }
        assert dumped[1] == {"type": "list", "content": "* item", "text": "item"}
        assert dumped[2] == {"type": "quote", "content": "> quoted", "text": "quoted"}
        assert dumped[3] == {
            "type": "link",
            "content": "=> /a A link",
            "link": {"url": "gemini://example.org/a", "text": "A link"},
        }
        # Block metadata sits on the opening toggle; the lines inside carry only
        # their verbatim content rather than repeating the alt text per line.
        assert dumped[4] == {
            "type": "preformat",
            "content": "```python",
            "alt_text": "python",
            "language": "python",
        }
        assert dumped[5] == {"type": "preformat", "content": "code"}
        assert dumped[6] == {"type": "preformat", "content": "```"}


class TestBinaryMimeSniffing:
    """Signatures whose branches no test reached.

    Content sniffed here decides whether a body reaches the model at all, so
    each branch needs a regression net; these belong in
    tests/test_gemini_utils.py beside the other sniffer tests.
    """

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
            (b"OggS\x00\x02" + b"\x00" * 10, "audio/ogg"),
            (b"\x1f\x8b\x08\x00" + b"\x00" * 12, "application/gzip"),
            (b"7z\xbc\xaf\x27\x1c" + b"\x00" * 10, "application/x-7z-compressed"),
            (b"\x7fELF\x02\x01\x01" + b"\x00" * 9, "application/x-executable"),
        ],
    )
    def test_signature_is_detected(self, content, expected):
        from gopher_mcp.utils import detect_binary_mime_type

        assert detect_binary_mime_type(content) == expected

    def test_short_text_starting_with_mz_is_not_an_executable(self):
        """ "MZ" is two printable characters: prose beginning with them must not
        be classified as a binary the model is then never shown."""
        from gopher_mcp.utils import detect_binary_mime_type

        assert detect_binary_mime_type(b"MZ hello world") == "application/octet-stream"


class TestRedirectTargetDescription:
    """A redirect is followed by the caller, so the payload has to describe it."""

    def test_a_target_on_another_host_is_flagged(self):
        result = GeminiRedirectResult(
            newUrl="gemini://elsewhere.example/x",
            permanent=True,
            requestInfo={"url": "gemini://example.org/a"},
        )

        assert result.cross_host is True
        assert result.scheme == "gemini"

    def test_a_target_on_the_same_host_is_not(self):
        result = GeminiRedirectResult(
            newUrl="gemini://example.org/b",
            requestInfo={"url": "gemini://example.org/a"},
        )

        assert result.cross_host is False

    def test_a_relative_target_stays_in_the_requests_scheme(self):
        result = GeminiRedirectResult(
            newUrl="/elsewhere", requestInfo={"url": "gemini://example.org/a"}
        )

        assert result.cross_host is False
        assert result.scheme == "gemini"

    def test_another_scheme_is_reported(self):
        """`newUrl` may leave Geminispace entirely; gemini_fetch cannot follow
        it, so the caller has to be able to see that from the payload."""
        result = GeminiRedirectResult(
            newUrl="https://evil.example/",
            requestInfo={"url": "gemini://example.org/a"},
        )

        assert result.scheme == "https"
        assert result.cross_host is True

    def test_nothing_is_claimed_when_the_request_url_is_unknown(self):
        """A guess would be worse than silence: `cross_host: false` on a target
        that is in fact another capsule is exactly the wrong signal."""
        result = GeminiRedirectResult(newUrl="gemini://example.org/b")

        assert result.cross_host is None

    def test_an_unsplittable_target_is_not_an_error(self):
        """The target is server-controlled, so a malformed one must not raise
        out of a result the caller is being handed."""
        result = GeminiRedirectResult(
            newUrl="gemini://[oops/x", requestInfo={"url": "gemini://example.org/a"}
        )

        assert result.new_url == "gemini://[oops/x"
        assert result.cross_host is None


class TestTOFUTrustEntry:
    """The projection gemini_trust_list reports, not the stored record."""

    def test_timestamps_are_reported_as_iso_8601_utc(self):
        """The client-certificate tools already report validity windows as ISO
        strings; epoch floats here made one `expires` concept two formats."""
        entry = TOFUEntry(
            host="example.org",
            fingerprint="sha256:abcdef1234567890",
            first_seen=1640995200.0,
            last_seen=1643673600.0,
            expires=1672531200.0,
        )

        reported = TOFUTrustEntry.from_entry(entry, now=1650000000.0)

        assert reported.first_seen == "2022-01-01T00:00:00+00:00"
        assert reported.last_seen == "2022-02-01T00:00:00+00:00"
        assert reported.expires == "2023-01-01T00:00:00+00:00"
        assert reported.expired is False
        assert reported.host == "example.org"
        assert reported.fingerprint == "sha256:abcdef1234567890"

    def test_expiry_is_precomputed(self):
        entry = TOFUEntry(
            host="example.org",
            fingerprint="fp",
            first_seen=1640995200.0,
            last_seen=1643673600.0,
            expires=1672531200.0,
        )

        assert TOFUTrustEntry.from_entry(entry, now=1700000000.0).expired is True

    def test_a_pin_without_an_expiry_reports_none(self):
        entry = TOFUEntry(
            host="example.org", fingerprint="fp", first_seen=1.0, last_seen=2.0
        )

        reported = TOFUTrustEntry.from_entry(entry, now=1700000000.0)

        assert reported.expires is None
        assert reported.expired is False

    def test_the_result_projects_stored_entries_itself(self):
        """The store's epoch floats must not reach the wire just because a
        caller passed the records it holds straight into the result."""
        from gopher_mcp.models import TOFUTrustListResult

        entry = TOFUEntry(
            host="example.org",
            fingerprint="fp",
            first_seen=1640995200.0,
            last_seen=1643673600.0,
        )

        dumped = TOFUTrustListResult(entries=[entry]).model_dump()

        assert dumped["entries"][0]["first_seen"] == "2022-01-01T00:00:00+00:00"
        assert dumped["entries"][0]["expires"] is None
