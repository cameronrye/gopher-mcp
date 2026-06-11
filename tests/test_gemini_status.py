"""Tests for Gemini status code processing."""

import pytest

from gopher_mcp.models import (
    GeminiCertificateResult,
    GeminiErrorResult,
    GeminiGemtextResult,
    GeminiInputResult,
    GeminiMimeType,
    GeminiRedirectResult,
    GeminiResponse,
    GeminiStatusCode,
    GeminiSuccessResult,
    GemtextLineType,
)
from gopher_mcp.utils import (
    detect_binary_mime_type,
    get_default_gemini_mime_type,
    parse_gemini_mime_type,
    parse_gemini_response,
    process_gemini_response,
    validate_gemini_mime_type,
)


class TestParseGeminiResponse:
    """Test Gemini response parsing."""

    def test_basic_response_parsing(self):
        """Test basic response parsing."""
        raw_response = b"20 text/gemini\r\nHello, Gemini!"
        response = parse_gemini_response(raw_response)

        assert response.status == GeminiStatusCode.SUCCESS
        assert response.meta == "text/gemini"
        assert response.body == b"Hello, Gemini!"

    def test_response_without_body(self):
        """Test response without body."""
        raw_response = b"10 Enter search terms\r\n"
        response = parse_gemini_response(raw_response)

        assert response.status == GeminiStatusCode.INPUT
        assert response.meta == "Enter search terms"
        assert response.body == b""

    def test_response_with_empty_body(self):
        """Test response with empty body."""
        raw_response = b"20 text/plain\r\n"
        response = parse_gemini_response(raw_response)

        assert response.status == GeminiStatusCode.SUCCESS
        assert response.meta == "text/plain"
        assert response.body == b""

    def test_response_with_long_meta(self):
        """Test response with long meta field."""
        meta = "text/gemini; charset=utf-8; lang=en-US"
        raw_response = f"20 {meta}\r\nContent".encode()
        response = parse_gemini_response(raw_response)

        assert response.status == GeminiStatusCode.SUCCESS
        assert response.meta == meta
        assert response.body == b"Content"

    def test_oversize_redirect_meta_rejected(self):
        """An over-long meta (>1024 bytes) must be rejected, not silently
        truncated. For a 3x redirect the meta is the target URL; truncating it
        would hand back a corrupted URL pointing somewhere unintended."""
        long_url = "gemini://example.org/" + "a" * 1100  # > 1024 bytes
        raw_response = f"31 {long_url}\r\n".encode()

        with pytest.raises(ValueError, match="Meta field exceeds 1024 bytes"):
            parse_gemini_response(raw_response)

    def test_all_status_codes(self):
        """Test parsing all valid status codes."""
        test_cases = [
            (10, "INPUT"),
            (11, "SENSITIVE_INPUT"),
            (20, "SUCCESS"),
            (30, "TEMPORARY_REDIRECT"),
            (31, "PERMANENT_REDIRECT"),
            (40, "TEMPORARY_FAILURE"),
            (41, "SERVER_UNAVAILABLE"),
            (42, "CGI_ERROR"),
            (43, "PROXY_ERROR"),
            (44, "SLOW_DOWN"),
            (50, "PERMANENT_FAILURE"),
            (51, "NOT_FOUND"),
            (52, "GONE"),
            (53, "PROXY_REQUEST_REFUSED"),
            (59, "BAD_REQUEST"),
            (60, "CERTIFICATE_REQUIRED"),
            (61, "CERTIFICATE_NOT_AUTHORIZED"),
            (62, "CERTIFICATE_NOT_VALID"),
        ]

        for status_code, _ in test_cases:
            raw_response = f"{status_code} Test meta\r\n".encode()
            response = parse_gemini_response(raw_response)
            assert response.status.value == status_code

    def test_empty_response(self):
        """Test empty response handling."""
        with pytest.raises(ValueError, match="Empty response"):
            parse_gemini_response(b"")

    def test_missing_crlf(self):
        """Test response missing CRLF."""
        with pytest.raises(ValueError, match="missing CRLF"):
            parse_gemini_response(b"20 text/plain")

    def test_short_status_line(self):
        """Test status line too short."""
        with pytest.raises(ValueError, match="Status line too short"):
            parse_gemini_response(b"2\r\n")

    def test_missing_space_after_status(self):
        """Test missing space after status code."""
        with pytest.raises(ValueError, match="missing space after status"):
            parse_gemini_response(b"20text/plain\r\n")

    def test_non_digit_status(self):
        """Test non-digit status code."""
        with pytest.raises(ValueError, match="Invalid status code"):
            parse_gemini_response(b"XX text/plain\r\n")

    def test_status_out_of_range_low(self):
        """Test status code too low."""
        with pytest.raises(ValueError, match="Status code out of range"):
            parse_gemini_response(b"09 text/plain\r\n")

    def test_status_out_of_range_high(self):
        """Test status code too high."""
        with pytest.raises(ValueError, match="Status code out of range"):
            parse_gemini_response(b"70 text/plain\r\n")

    def test_invalid_utf8_status_line(self):
        """Test invalid UTF-8 in status line."""
        with pytest.raises(ValueError, match="Invalid UTF-8"):
            parse_gemini_response(b"20 \xff\xfe\r\n")

    def test_unknown_status_code_in_range(self):
        """Test unknown but valid status code."""
        raw_response = b"25 unknown status\r\nContent"
        response = parse_gemini_response(raw_response)

        # Should accept unknown status codes in valid range
        assert response.status == 25
        assert response.meta == "unknown status"


class TestParseGeminiMimeType:
    """Test MIME type parsing."""

    def test_basic_mime_type(self):
        """Test basic MIME type parsing."""
        mime = parse_gemini_mime_type("text/gemini")

        assert mime.type == "text"
        assert mime.subtype == "gemini"
        assert mime.charset == "utf-8"  # default
        assert mime.lang is None

    def test_mime_type_with_charset(self):
        """Test MIME type with charset parameter."""
        mime = parse_gemini_mime_type("text/plain; charset=iso-8859-1")

        assert mime.type == "text"
        assert mime.subtype == "plain"
        assert mime.charset == "iso-8859-1"

    def test_mime_type_with_language(self):
        """Test MIME type with language parameter."""
        mime = parse_gemini_mime_type("text/gemini; lang=en-US")

        assert mime.type == "text"
        assert mime.subtype == "gemini"
        assert mime.lang == "en-US"

    def test_mime_type_with_multiple_params(self):
        """Test MIME type with multiple parameters."""
        mime = parse_gemini_mime_type("text/gemini; charset=utf-8; lang=fr-CA")

        assert mime.type == "text"
        assert mime.subtype == "gemini"
        assert mime.charset == "utf-8"
        assert mime.lang == "fr-CA"

    def test_mime_type_case_insensitive(self):
        """Test MIME type case insensitivity."""
        mime = parse_gemini_mime_type("TEXT/GEMINI; CHARSET=UTF-8")

        assert mime.type == "text"
        assert mime.subtype == "gemini"
        assert mime.charset == "UTF-8"  # Preserve case for charset

    def test_mime_type_with_quotes(self):
        """Test MIME type with quoted parameters."""
        mime = parse_gemini_mime_type("text/plain; charset=\"utf-8\"; lang='en-US'")

        assert mime.charset == "utf-8"
        assert mime.lang == "en-US"

    def test_binary_mime_type(self):
        """Test binary MIME type."""
        mime = parse_gemini_mime_type("image/jpeg")

        assert mime.type == "image"
        assert mime.subtype == "jpeg"
        assert mime.is_text is False
        assert mime.is_gemtext is False

    def test_empty_mime_type(self):
        """Test empty MIME type."""
        with pytest.raises(ValueError, match="Empty MIME type"):
            parse_gemini_mime_type("")

    def test_invalid_mime_type_no_slash(self):
        """Test MIME type without slash."""
        with pytest.raises(ValueError, match="Invalid MIME type format"):
            parse_gemini_mime_type("textplain")

    def test_invalid_mime_type_empty_parts(self):
        """Test MIME type with empty parts."""
        with pytest.raises(ValueError, match="Invalid MIME type format"):
            parse_gemini_mime_type("/gemini")

        with pytest.raises(ValueError, match="Invalid MIME type format"):
            parse_gemini_mime_type("text/")


class TestGetDefaultGeminiMimeType:
    """Test default MIME type function."""

    def test_default_mime_type(self):
        """Test default MIME type creation."""
        mime = get_default_gemini_mime_type()

        assert mime.type == "text"
        assert mime.subtype == "gemini"
        assert mime.charset == "utf-8"
        assert mime.lang is None
        assert mime.is_gemtext is True


class TestDetectBinaryMimeType:
    """Test binary MIME type detection."""

    def test_png_detection(self):
        """Test PNG image detection."""
        png_header = b"\x89PNG\r\n\x1a\n" + b"fake_png_data"
        mime_type = detect_binary_mime_type(png_header)
        assert mime_type == "image/png"

    def test_jpeg_detection(self):
        """Test JPEG image detection."""
        jpeg_header = b"\xff\xd8\xff" + b"fake_jpeg_data"
        mime_type = detect_binary_mime_type(jpeg_header)
        assert mime_type == "image/jpeg"

    def test_gif_detection(self):
        """Test GIF image detection."""
        gif87_header = b"GIF87a" + b"fake_gif_data"
        mime_type = detect_binary_mime_type(gif87_header)
        assert mime_type == "image/gif"

        gif89_header = b"GIF89a" + b"fake_gif_data"
        mime_type = detect_binary_mime_type(gif89_header)
        assert mime_type == "image/gif"

    def test_pdf_detection(self):
        """Test PDF document detection."""
        pdf_header = b"%PDF-1.4" + b"fake_pdf_data"
        mime_type = detect_binary_mime_type(pdf_header)
        assert mime_type == "application/pdf"

    def test_zip_detection(self):
        """Test ZIP archive detection."""
        zip_header = b"PK\x03\x04" + b"fake_zip_data"
        mime_type = detect_binary_mime_type(zip_header)
        assert mime_type == "application/zip"

    def test_mp3_detection(self):
        """Test MP3 audio detection."""
        mp3_header = b"ID3" + b"fake_mp3_data"
        mime_type = detect_binary_mime_type(mp3_header)
        assert mime_type == "audio/mpeg"

    def test_empty_content(self):
        """Test empty content detection."""
        mime_type = detect_binary_mime_type(b"")
        assert mime_type == "application/octet-stream"

    def test_unknown_binary(self):
        """Test unknown binary content."""
        unknown_data = b"unknown_binary_format"
        mime_type = detect_binary_mime_type(unknown_data)
        assert mime_type == "application/octet-stream"


class TestValidateGeminiMimeType:
    """Test MIME type validation."""

    def test_valid_text_mime_type(self):
        """Test valid text MIME type."""
        mime = GeminiMimeType(type="text", subtype="gemini")
        assert validate_gemini_mime_type(mime) is True

    def test_valid_binary_mime_type(self):
        """Test valid binary MIME type."""
        mime = GeminiMimeType(type="image", subtype="png")
        assert validate_gemini_mime_type(mime) is True

    def test_invalid_empty_type(self):
        """Test invalid MIME type with empty type."""
        mime = GeminiMimeType(type="", subtype="gemini")
        assert validate_gemini_mime_type(mime) is False

    def test_invalid_empty_subtype(self):
        """Test invalid MIME type with empty subtype."""
        mime = GeminiMimeType(type="text", subtype="")
        assert validate_gemini_mime_type(mime) is False

    def test_text_without_charset(self):
        """Test text MIME type without charset."""
        mime = GeminiMimeType(type="text", subtype="plain", charset="")
        assert validate_gemini_mime_type(mime) is False

    def test_valid_language_tag(self):
        """Test valid language tag."""
        mime = GeminiMimeType(type="text", subtype="gemini", lang="en-US")
        assert validate_gemini_mime_type(mime) is True

    def test_invalid_language_tag(self):
        """Test invalid language tag."""
        mime = GeminiMimeType(type="text", subtype="gemini", lang="en@US")
        assert validate_gemini_mime_type(mime) is False

    def test_comma_separated_language_list(self):
        """The Gemini spec allows a comma-separated list of BCP47 tags in the
        lang parameter (e.g. `lang=en,fr`); rejecting it discards the whole
        MIME type (including the declared charset) downstream."""
        mime = GeminiMimeType(type="text", subtype="gemini", lang="en,fr")
        assert validate_gemini_mime_type(mime) is True
        mime = GeminiMimeType(type="text", subtype="gemini", lang="en-US,fr-CA,de")
        assert validate_gemini_mime_type(mime) is True

    def test_malformed_language_list_is_rejected(self):
        """A trailing/empty tag in the list is still malformed."""
        for bad in ("en,", ",fr", "en,,fr"):
            mime = GeminiMimeType(type="text", subtype="gemini", lang=bad)
            assert validate_gemini_mime_type(mime) is False


class TestProcessGeminiResponse:
    """Test Gemini response processing."""

    def test_input_response(self):
        """Test input response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.INPUT, meta="Enter search terms", body=None
        )

        result = process_gemini_response(response, "gemini://example.org/search")

        assert isinstance(result, GeminiInputResult)
        assert result.kind == "input"
        assert result.prompt == "Enter search terms"
        assert result.sensitive is False

    def test_sensitive_input_response(self):
        """Test sensitive input response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.SENSITIVE_INPUT, meta="Enter password", body=None
        )

        result = process_gemini_response(response, "gemini://example.org/login")

        assert isinstance(result, GeminiInputResult)
        assert result.sensitive is True

    def test_success_text_response(self):
        """Test success text response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="text/plain; charset=utf-8",
            body=b"Hello, world!",
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiSuccessResult)
        assert result.kind == "success"
        assert result.content == "Hello, world!"
        assert result.size == 13
        assert result.mime_type.is_text is True

    def test_success_gemtext_response(self):
        """Test success gemtext response processing."""
        gemtext_content = "# Welcome\nThis is a gemtext document."
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="text/gemini",
            body=gemtext_content.encode("utf-8"),
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiGemtextResult)
        assert result.raw_content == gemtext_content
        assert result.truncated is False
        assert len(result.document.lines) == 2
        assert result.document.lines[0].type == GemtextLineType.HEADING_1

    def test_success_gemtext_truncated_to_render_limit(self):
        """A gemtext body over the render limit must be truncated -- both
        raw_content AND the parsed document -- and flagged, so an attacker-
        controlled page cannot flood the model context. text/gemini is the
        dominant Gemini type, so the cap that protects text/* must apply here."""
        body = "# Heading\n" + "filler line\n" * 5000
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="text/gemini",
            body=body.encode("utf-8"),
        )

        result = process_gemini_response(
            response, "gemini://example.org/", max_rendered_chars=100
        )

        assert isinstance(result, GeminiGemtextResult)
        assert len(result.raw_content) <= 100
        assert result.truncated is True
        # The parsed document must be bounded too, not all 5001 lines.
        assert len(result.document.lines) < 200
        # `size` still reports the full original byte length.
        assert result.size == len(body.encode("utf-8"))

    def test_success_malformed_mime_with_text_body_defaults_to_gemtext(self):
        """A status-20 with an unparseable MIME and a textual body must default
        to text/gemini (the Gemini spec default), not be content-sniffed into
        application/octet-stream and returned as binary."""
        body = "# Heading\n=> /x A link\nsome text"
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="garbage-no-slash",
            body=body.encode("utf-8"),
        )
        result = process_gemini_response(response, "gemini://example.org/")
        assert isinstance(result, GeminiGemtextResult)
        assert result.raw_content == body

    def test_success_malformed_mime_with_binary_body_still_detected(self):
        """Real binary content served with a bad MIME is still detected by its
        signature (octet-stream fallback only applies when nothing matched)."""
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="garbage-no-slash", body=png
        )
        result = process_gemini_response(response, "gemini://example.org/")
        assert isinstance(result, GeminiSuccessResult)
        assert result.mime_type.full_type == "image/png"

    def test_success_binary_response(self):
        """Test success binary response processing."""
        binary_data = b"\x89PNG\r\n\x1a\n"  # PNG header
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="image/png", body=binary_data
        )

        result = process_gemini_response(response, "gemini://example.org/image.png")

        assert isinstance(result, GeminiSuccessResult)
        assert result.content == binary_data
        assert result.mime_type.is_text is False

    def test_temporary_redirect_response(self):
        """Test temporary redirect response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.TEMPORARY_REDIRECT, meta="/new-location", body=None
        )

        result = process_gemini_response(response, "gemini://example.org/old")

        assert isinstance(result, GeminiRedirectResult)
        assert result.kind == "redirect"
        # The relative target is resolved against the request URL so the caller
        # gets an absolute URL it can re-fetch (and SSRF-validate).
        assert result.new_url == "gemini://example.org/new-location"
        assert result.permanent is False

    def test_redirect_resolves_sibling_relative_target(self):
        """A bare relative reference resolves against the request path."""
        response = GeminiResponse(
            status=GeminiStatusCode.TEMPORARY_REDIRECT, meta="sibling", body=None
        )
        result = process_gemini_response(response, "gemini://example.org/dir/old")
        assert isinstance(result, GeminiRedirectResult)
        assert result.new_url == "gemini://example.org/dir/sibling"

    def test_empty_redirect_target_is_rejected(self):
        """A 3x redirect with an empty meta is malformed: urljoin('', base)
        resolves to the request URL, so an LLM following newUrl would re-fetch
        the same URL forever. It must be reported as an error instead."""
        response = GeminiResponse(
            status=GeminiStatusCode.TEMPORARY_REDIRECT, meta="", body=None
        )
        result = process_gemini_response(response, "gemini://example.org/page")
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "INVALID_REDIRECT"

    def test_whitespace_redirect_target_is_rejected(self):
        response = GeminiResponse(
            status=GeminiStatusCode.PERMANENT_REDIRECT, meta="   ", body=None
        )
        result = process_gemini_response(response, "gemini://example.org/page")
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "INVALID_REDIRECT"

    def test_self_redirect_is_rejected(self):
        """A redirect whose resolved target equals the request URL is a loop."""
        response = GeminiResponse(
            status=GeminiStatusCode.TEMPORARY_REDIRECT,
            meta="gemini://example.org/page",
            body=None,
        )
        result = process_gemini_response(response, "gemini://example.org/page")
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "INVALID_REDIRECT"

    def test_redirect_preserves_absolute_cross_scheme_target(self):
        """An absolute target (its own scheme) is passed through unchanged."""
        response = GeminiResponse(
            status=GeminiStatusCode.PERMANENT_REDIRECT,
            meta="https://example.com/web",
            body=None,
        )
        result = process_gemini_response(response, "gemini://example.org/old")
        assert isinstance(result, GeminiRedirectResult)
        assert result.new_url == "https://example.com/web"

    def test_permanent_redirect_response(self):
        """Test permanent redirect response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.PERMANENT_REDIRECT,
            meta="gemini://example.org/moved",
            body=None,
        )

        result = process_gemini_response(response, "gemini://example.org/old")

        assert isinstance(result, GeminiRedirectResult)
        assert result.permanent is True

    def test_success_text_response_truncates_to_render_limit(self):
        """A text/* body beyond the render cap is truncated and flagged."""
        response = GeminiResponse(status=20, meta="text/plain", body=b"abcdefghij")
        result = process_gemini_response(
            response, "gemini://example.org/", max_rendered_chars=5
        )
        assert isinstance(result, GeminiSuccessResult)
        assert result.content == "abcde"
        assert result.truncated is True

    def test_success_text_response_not_truncated_under_limit(self):
        response = GeminiResponse(status=20, meta="text/plain", body=b"short")
        result = process_gemini_response(
            response, "gemini://example.org/", max_rendered_chars=100
        )
        assert isinstance(result, GeminiSuccessResult)
        assert result.truncated is False

    def test_denied_mime_type_is_filtered(self):
        """A response whose MIME matches the deny list is rejected, not returned."""
        from gopher_mcp.models import GeminiErrorResult

        response = GeminiResponse(status=20, meta="text/html", body=b"<h1>hi</h1>")
        result = process_gemini_response(
            response,
            "gemini://example.org/",
            denied_mime_types=frozenset({"text/html"}),
        )
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "CONTENT_FILTERED"

    def test_denied_mime_wildcard_is_filtered(self):
        from gopher_mcp.models import GeminiErrorResult

        response = GeminiResponse(status=20, meta="image/png", body=b"\x89PNG")
        result = process_gemini_response(
            response, "gemini://example.org/", denied_mime_types=frozenset({"image/*"})
        )
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "CONTENT_FILTERED"

    def test_non_denied_mime_passes(self):
        response = GeminiResponse(status=20, meta="text/plain", body=b"ok")
        result = process_gemini_response(
            response,
            "gemini://example.org/",
            denied_mime_types=frozenset({"text/html"}),
        )
        assert isinstance(result, GeminiSuccessResult)

    def test_temporary_error_response(self):
        """Test temporary error response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.TEMPORARY_FAILURE,
            meta="Server temporarily unavailable",
            body=None,
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiErrorResult)
        assert result.kind == "error"
        assert result.error["temporary"] is True
        assert result.error["message"] == "Server temporarily unavailable"

    def test_permanent_error_response(self):
        """Test permanent error response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.NOT_FOUND, meta="Resource not found", body=None
        )

        result = process_gemini_response(response, "gemini://example.org/missing")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["temporary"] is False
        assert result.error["status"] == 51

    def test_certificate_response(self):
        """Test certificate request response processing."""
        response = GeminiResponse(
            status=GeminiStatusCode.CERTIFICATE_REQUIRED,
            meta="Certificate required for access",
            body=None,
        )

        result = process_gemini_response(response, "gemini://example.org/private")

        assert isinstance(result, GeminiCertificateResult)
        assert result.kind == "certificate"
        assert result.message == "Certificate required for access"
        assert result.required is True
        assert result.status == 60

    def test_certificate_not_authorized_is_a_rejection(self):
        """Status 61 (NOT_AUTHORIZED) is a rejection, not a prompt for a cert."""
        response = GeminiResponse(
            status=GeminiStatusCode.CERTIFICATE_NOT_AUTHORIZED,
            meta="Certificate not authorized",
            body=None,
        )

        result = process_gemini_response(response, "gemini://example.org/private")

        assert isinstance(result, GeminiCertificateResult)
        assert result.status == 61
        # The presented identity was refused; the caller must NOT re-prompt for
        # a (fresh) certificate as if none had been sent.
        assert result.required is False

    def test_certificate_not_valid_is_a_rejection(self):
        """Status 62 (NOT_VALID) is a rejection (expired/malformed cert)."""
        response = GeminiResponse(
            status=GeminiStatusCode.CERTIFICATE_NOT_VALID,
            meta="Certificate not valid",
            body=None,
        )

        result = process_gemini_response(response, "gemini://example.org/private")

        assert isinstance(result, GeminiCertificateResult)
        assert result.status == 62
        assert result.required is False

    def test_success_response_empty_body(self):
        """Test success response with empty body."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="text/plain", body=b""
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiSuccessResult)
        assert result.content == ""
        assert result.size == 0

    def test_success_response_invalid_mime_type(self):
        """An invalid MIME with a textual body defaults to text/gemini (the
        Gemini spec default), not content-sniffed binary."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="invalid-mime-type", body=b"content"
        )

        result = process_gemini_response(response, "gemini://example.org/")
        assert isinstance(result, GeminiGemtextResult)
        assert result.raw_content == "content"

    def test_success_response_decode_error(self):
        """Test success response with decode error."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="text/plain; charset=utf-8",
            body=b"\xff\xfe",  # Invalid UTF-8
        )

        # Should fallback to other charsets instead of raising error
        result = process_gemini_response(response, "gemini://example.org/")
        assert isinstance(result, GeminiSuccessResult)
        # Should fallback to latin1 charset
        assert result.mime_type.charset == "latin-1"

    def test_request_info_included(self):
        """Test that request info is included in results."""
        response = GeminiResponse(
            status=GeminiStatusCode.INPUT, meta="Enter query", body=None
        )

        result = process_gemini_response(
            response, "gemini://example.org/search", request_time=1234567890.0
        )

        assert result.request_info["url"] == "gemini://example.org/search"
        assert result.request_info["timestamp"] == 1234567890.0

    def test_success_response_empty_meta(self):
        """Test success response with empty meta (uses default MIME type)."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="", body=b"Hello, world!"
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiGemtextResult)
        assert result.charset == "utf-8"
        assert result.raw_content == "Hello, world!"

    def test_success_response_charset_fallback(self):
        """Test success response with charset fallback."""
        # Create content that's valid latin1 but not utf-8
        latin1_content = "Café".encode("latin1")

        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="text/plain; charset=utf-8",  # Wrong charset
            body=latin1_content,
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiSuccessResult)
        assert result.content == "Café"
        assert result.mime_type.charset == "latin-1"  # Should fallback to latin1

    def test_success_response_binary_detection(self):
        """Test success response with binary content detection."""
        png_data = b"\x89PNG\r\n\x1a\n" + b"fake_png_data"

        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="application/octet-stream",
            body=png_data,
        )

        result = process_gemini_response(response, "gemini://example.org/image")

        assert isinstance(result, GeminiSuccessResult)
        assert result.mime_type.full_type == "image/png"
        assert result.content == png_data

    def test_success_response_invalid_mime_fallback(self):
        """An invalid MIME with non-binary content defaults to text/gemini."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS,
            meta="invalid/mime/type",
            body=b"Hello, world!",
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiGemtextResult)
        assert result.raw_content == "Hello, world!"

    def test_success_response_invalid_mime_empty_body_fallback(self):
        """Test success response with invalid MIME type and empty body fallback."""
        response = GeminiResponse(
            status=GeminiStatusCode.SUCCESS, meta="invalid/mime/type", body=b""
        )

        result = process_gemini_response(response, "gemini://example.org/")

        assert isinstance(result, GeminiGemtextResult)
        # Should fallback to default gemtext for empty body
        assert result.charset == "utf-8"
        assert result.raw_content == ""
