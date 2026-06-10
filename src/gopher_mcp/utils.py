"""Utility functions for Gopher protocol operations."""

import contextlib

# ``os`` stays importable from this module so the suite can keep patching
# ``gopher_mcp.utils.os.fsync`` -- the durability fsync used by
# ``atomic_write_json``, which now lives in ``helpers``.
import os  # noqa: F401
from typing import Any, Union
from urllib.parse import urljoin, urlparse

from .gemtext import parse_gemtext
from .gopher_parse import (
    format_gopher_url,
    gopher_type_category,
    parse_gopher_menu,
    parse_gopher_url,
    parse_menu_line,
    sanitize_selector,
)
from .helpers import (
    atomic_write_json,
    bracket_host,
    get_home_directory,
    normalize_cache_key,
    truncate_text,
)
from .mime import (
    detect_binary_mime_type,
    get_default_gemini_mime_type,
    guess_mime_type,
    mime_is_denied,
    parse_gemini_mime_type,
    validate_gemini_mime_type,
)
from .models import (
    GeminiCertificateResult,
    GeminiErrorResult,
    GeminiFetchResponse,
    GeminiGemtextResult,
    GeminiInputResult,
    GeminiRedirectResult,
    GeminiResponse,
    GeminiStatusCode,
    GeminiSuccessResult,
    GeminiURL,
)

# Public API of this module. ``utils`` is kept as a thin facade: the
# implementations live in focused submodules (``helpers``, ``mime``,
# ``gemtext``, ``gopher_parse``, ``gemini_parse``) and are re-exported here so
# that ``from gopher_mcp.utils import X`` keeps working for every X.
__all__ = [
    "atomic_write_json",
    "bracket_host",
    "detect_binary_mime_type",
    "format_gemini_url",
    "format_gopher_url",
    "get_default_gemini_mime_type",
    "get_home_directory",
    "gopher_type_category",
    "guess_mime_type",
    "mime_is_denied",
    "normalize_cache_key",
    "parse_gemini_mime_type",
    "parse_gemini_response",
    "parse_gemini_url",
    "parse_gemtext",
    "parse_gopher_menu",
    "parse_gopher_url",
    "parse_menu_line",
    "process_gemini_response",
    "sanitize_selector",
    "truncate_text",
    "validate_gemini_mime_type",
    "validate_gemini_url_components",
]


# ============================================================================
# Gemini Protocol Utilities
# ============================================================================


def parse_gemini_url(url: str) -> GeminiURL:
    """Parse a Gemini URL into its components.

    Args:
        url: Gemini URL to parse (e.g., gemini://example.org/path?query)

    Returns:
        Parsed URL components

    Raises:
        ValueError: If URL is invalid

    """
    if not url.startswith("gemini://"):
        raise ValueError("URL must start with 'gemini://'")

    # Reject raw ASCII control characters (C0 range + DEL) anywhere in the URL.
    # ``urlparse`` silently *strips* CR/LF/TAB, which would otherwise mask a
    # request-line injection attempt; other C0 bytes (NUL/VT/FF) survive into
    # the on-wire ``<url>\r\n`` request verbatim. Both must fail closed.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        raise ValueError("URL must not contain control characters")

    # Check URL length limit. The spec's 1024-byte cap applies to the whole
    # CRLF-terminated request line (``<url>\r\n``), so the URL itself must be
    # <= 1022 bytes -- not 1024.
    if len(url.encode("utf-8")) + len(b"\r\n") > 1024:
        raise ValueError("URL must not exceed 1024 bytes (request line incl. CRLF)")

    # ``urlparse`` is lazy: an out-of-range port only raises when ``.port`` is
    # accessed, so the access must live inside the try block for the friendly
    # message to be reachable.
    try:
        parsed = urlparse(url)
        port = parsed.port if parsed.port is not None else 1965  # Default port
    except ValueError as e:
        # Handle port parsing errors from urllib
        if "Port out of range" in str(e):
            raise ValueError("Invalid port number: port out of range") from e
        raise

    if not parsed.hostname:
        raise ValueError("URL must contain a hostname")

    # Gemini spec forbids userinfo and fragment
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain userinfo (username/password)")

    if parsed.fragment:
        raise ValueError("URL must not contain fragment")

    host = parsed.hostname
    path = parsed.path or "/"  # Default to root path
    query = parsed.query or None  # Query string for user input

    # A raw (unencoded) space in the path/query produces a malformed request
    # line -- URLs must percent-encode spaces. Reject rather than send garbage.
    if " " in path or (query is not None and " " in query):
        raise ValueError("URL path/query must not contain a raw space")

    # Reject an explicit invalid port instead of silently coercing it (``0`` is
    # falsy, so the old ``parsed.port or 1965`` rewrote it to the default).
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid port number: {port}")

    return GeminiURL(
        host=host,
        port=port,
        path=path,
        query=query,
    )


def format_gemini_url(
    host: str,
    port: int = 1965,
    path: str = "/",
    query: str | None = None,
) -> str:
    """Format a Gemini URL from components.

    Args:
        host: Hostname
        port: Port number (default 1965)
        path: Resource path (default "/")
        query: Query string for user input

    Returns:
        Formatted Gemini URL

    """
    # Build the URL (bracket an IPv6 literal host per RFC 3986)
    url = f"gemini://{bracket_host(host)}"

    # Only include port if it's not the default
    if port != 1965:
        url += f":{port}"

    # Add path (ensure it starts with /)
    if not path.startswith("/"):
        path = "/" + path
    url += path

    # Add query string if provided
    if query:
        url += f"?{query}"

    return url


def validate_gemini_url_components(
    host: str,
    port: int = 1965,
    path: str = "/",
    query: str | None = None,
) -> None:
    """Validate Gemini URL components.

    Args:
        host: Hostname
        port: Port number
        path: Resource path
        query: Query string

    Raises:
        ValueError: If any component is invalid

    """
    # Validate host
    if not host or not host.strip():
        raise ValueError("Host cannot be empty")

    # Validate port
    if not 1 <= port <= 65535:
        raise ValueError(f"Port must be between 1 and 65535, got {port}")

    # Validate path
    if not path.startswith("/"):
        raise ValueError("Path must start with '/'")

    # Check overall URL length
    test_url = format_gemini_url(host, port, path, query)
    if len(test_url.encode("utf-8")) > 1024:
        raise ValueError("Resulting URL would exceed 1024 byte limit")


def parse_gemini_response(raw_response: bytes) -> "GeminiResponse":
    """Parse raw Gemini response into status, meta, and body.

    Args:
        raw_response: Raw response bytes from Gemini server

    Returns:
        Parsed GeminiResponse object

    Raises:
        ValueError: If response format is invalid
    """
    if not raw_response:
        raise ValueError("Empty response")

    try:
        # Find the end of the status line (CRLF)
        crlf_pos = raw_response.find(b"\r\n")
        if crlf_pos == -1:
            raise ValueError("Invalid response format: missing CRLF")

        # Extract status line and body
        status_line = raw_response[:crlf_pos].decode("utf-8")
        body = raw_response[crlf_pos + 2 :] if len(raw_response) > crlf_pos + 2 else b""

        # Parse status line: "<STATUS><SPACE><META>"
        if len(status_line) < 3:  # Minimum: "XX "
            raise ValueError("Status line too short")

        if status_line[2] != " ":
            raise ValueError("Invalid status line format: missing space after status")

        # Extract status code and meta
        status_str = status_line[:2]
        meta = status_line[3:]  # Everything after "XX "

        # A spec-compliant meta is at most 1024 bytes. Reject an over-long
        # meta rather than truncating it: for a 3x redirect the meta is the
        # target URL, so truncation would hand back a corrupted URL pointing
        # somewhere other than intended instead of a clear protocol error.
        if len(meta.encode("utf-8")) > 1024:
            raise ValueError("Meta field exceeds 1024 bytes")

        # Validate status code
        if not status_str.isdigit():
            raise ValueError(f"Invalid status code: {status_str}")

        status_code = int(status_str)

        # Validate status code range
        if not (10 <= status_code <= 69):
            raise ValueError(f"Status code out of range: {status_code}")

        # Convert to enum
        try:
            status_enum: GeminiStatusCode | int = GeminiStatusCode(status_code)
        except ValueError:
            # Handle unknown status codes within valid range
            status_enum = status_code

        return GeminiResponse(status=status_enum, meta=meta, body=body)

    except UnicodeDecodeError as e:
        raise ValueError(f"Invalid UTF-8 in status line: {e}") from e
    except ValueError:
        # Re-raise our own validation errors unchanged (don't double-wrap).
        raise
    except Exception as e:
        raise ValueError(f"Failed to parse response: {e}") from e


def process_gemini_response(
    response: "GeminiResponse",
    request_url: str,
    request_time: float | None = None,
    *,
    max_rendered_chars: int = 0,
    denied_mime_types: "frozenset[str] | None" = None,
) -> "GeminiFetchResponse":
    """Process Gemini response based on status code.

    Args:
        response: Parsed Gemini response
        request_url: Original request URL
        request_time: Request timestamp (defaults to current time)
        max_rendered_chars: LLM-facing cap on returned text characters
            (0 = unlimited). Only applies to textual success bodies.
        denied_mime_types: MIME types (or ``type/*`` wildcards) to reject on a
            success response; empty/None = no content filtering.

    Returns:
        Appropriate response result object based on status code

    Raises:
        ValueError: If status code is unsupported or response is invalid
    """
    import time

    if request_time is None:
        request_time = time.time()

    request_info = {
        "url": request_url,
        "timestamp": request_time,
    }

    status = response.status
    meta = response.meta
    body = response.body

    # Handle status code ranges - extract integer value
    status_code = status if isinstance(status, int) else int(status)

    # Input expected (10-19)
    if 10 <= status_code <= 19:
        return _process_input_response(status_code, meta, request_info)

    # Success: status codes 20 through 29
    elif 20 <= status_code <= 29:
        return _process_success_response(
            meta,
            body,
            request_info,
            max_rendered_chars=max_rendered_chars,
            denied_mime_types=denied_mime_types,
        )

    # Redirect: status codes 30 through 39
    elif 30 <= status_code <= 39:
        return _process_redirect_response(status_code, meta, request_info)

    # Temporary failure (40-49)
    elif 40 <= status_code <= 49:
        return _process_error_response(status_code, meta, request_info, temporary=True)

    # Permanent failure (50-59)
    elif 50 <= status_code <= 59:
        return _process_error_response(status_code, meta, request_info, temporary=False)

    # Client certificate required (60-69)
    elif 60 <= status_code <= 69:
        return _process_certificate_response(status_code, meta, request_info)

    else:
        # This shouldn't happen due to validation in parse_gemini_response
        return GeminiErrorResult(
            error={
                "code": "INVALID_STATUS",
                "message": f"Invalid status code: {status_code}",
                "status": status_code,
            },
            requestInfo=request_info,
        )


def _process_input_response(
    status_code: int, meta: str, request_info: dict[str, Any]
) -> "GeminiInputResult":
    """Process input request response (status 10-11).

    Args:
        status_code: Gemini status code
        meta: Input prompt text
        request_info: Request information

    Returns:
        GeminiInputResult object
    """

    sensitive = status_code == GeminiStatusCode.SENSITIVE_INPUT.value

    return GeminiInputResult(
        prompt=meta,
        sensitive=sensitive,
        requestInfo=request_info,
    )


def _process_success_response(
    meta: str,
    body: bytes | None,
    request_info: dict[str, Any],
    *,
    max_rendered_chars: int = 0,
    denied_mime_types: "frozenset[str] | None" = None,
) -> Union["GeminiSuccessResult", "GeminiGemtextResult", "GeminiErrorResult"]:
    """Process success response (status 20-29).

    Args:
        meta: MIME type string
        body: Response body bytes
        request_info: Request information
        max_rendered_chars: LLM-facing cap on returned text characters
            (0 = unlimited); applies to textual bodies only, never binary.
        denied_mime_types: MIME types (or ``type/*``) to reject as filtered.

    Returns:
        GeminiSuccessResult / GeminiGemtextResult, or GeminiErrorResult if the
        content type is on the deny list.

    Raises:
        ValueError: If MIME type is invalid or body is missing
    """

    if body is None or len(body) == 0:
        # Allow empty body for success responses
        body = b""

    # Parse MIME type with enhanced error handling
    try:
        if not meta.strip():
            # Use default MIME type for empty meta
            mime_type = get_default_gemini_mime_type()
        else:
            mime_type = parse_gemini_mime_type(meta)

            # Validate the parsed MIME type
            if not validate_gemini_mime_type(mime_type):
                raise ValueError(f"Invalid MIME type: {meta}")

    except ValueError:
        # Per the Gemini spec, an absent/unparseable MIME defaults to text/gemini.
        # Sniff the body so genuinely binary content served with a bad MIME is
        # still detected by signature -- but a non-match yields the octet-stream
        # fallback, which must NOT misclassify textual/gemtext content as binary;
        # in that case fall back to the text/gemini default.
        detected_type = (
            detect_binary_mime_type(body) if body else "application/octet-stream"
        )
        if detected_type != "application/octet-stream":
            try:
                mime_type = parse_gemini_mime_type(detected_type)
            except ValueError:
                mime_type = get_default_gemini_mime_type()
        else:
            mime_type = get_default_gemini_mime_type()

    size = len(body)

    # Content filtering: reject a denied MIME type before decoding/returning it.
    if denied_mime_types and mime_is_denied(mime_type.full_type, denied_mime_types):
        return GeminiErrorResult(
            error={
                "code": "CONTENT_FILTERED",
                "message": f"Content type '{mime_type.full_type}' is blocked by "
                f"the configured content filter",
                "mimeType": mime_type.full_type,
            },
            requestInfo=request_info,
        )

    # Handle gemtext content specially
    if mime_type.is_gemtext:
        content, used_charset = _decode_with_fallback(body, mime_type.charset)
        mime_type.charset = used_charset
        # Cap the gemtext handed to the LLM BEFORE parsing, so both rawContent
        # and the parsed document are bounded. text/gemini is the dominant
        # Gemini type, so without this the max_rendered_chars cap that protects
        # text/* would not protect the common case: a 1 MB gemtext page (well
        # under the byte limit) is ~250k tokens. `size` still reports the full
        # original byte length.
        content, truncated = truncate_text(content, max_rendered_chars)
        # Parse gemtext into structured format
        document = parse_gemtext(content)

        return GeminiGemtextResult(
            document=document,
            rawContent=content,
            charset=used_charset,
            lang=mime_type.lang,
            size=size,
            truncated=truncated,
            requestInfo=request_info,
        )

    # Handle text content
    elif mime_type.is_text:
        content, used_charset = _decode_with_fallback(body, mime_type.charset)
        mime_type.charset = used_charset
        # Cap the text handed to the LLM; `size` still reports the full bytes.
        rendered, truncated = truncate_text(content, max_rendered_chars)
        return GeminiSuccessResult(
            mimeType=mime_type,
            content=rendered,
            size=size,
            truncated=truncated,
            requestInfo=request_info,
        )

    # Handle binary content
    else:
        # For binary content, ensure we have the right MIME type
        if mime_type.full_type == "application/octet-stream" and body:
            # Try to detect a more specific MIME type
            detected_type = detect_binary_mime_type(body)
            if detected_type != "application/octet-stream":
                # Keep the original mime_type if the detected one won't parse.
                with contextlib.suppress(ValueError):
                    mime_type = parse_gemini_mime_type(detected_type)

        # Binary content is base64-encoded on serialization; flag it so the
        # consumer knows how to interpret the content field.
        binary_request_info = {**request_info, "content_encoding": "base64"}
        return GeminiSuccessResult(
            mimeType=mime_type,
            content=body,  # serialized as base64 (JSON-safe) by the model
            size=size,
            requestInfo=binary_request_info,
        )


def _decode_with_fallback(body: bytes, charset: str) -> tuple[str, str]:
    """Decode ``body`` using ``charset``, falling back to latin-1.

    Catches both UnicodeDecodeError and LookupError (an unknown charset name),
    so a server advertising a bogus charset degrades gracefully instead of
    crashing the whole response. Returns ``(text, charset_actually_used)``.
    latin-1 maps every byte, so the final fallback never fails.
    """
    for candidate in [charset, "utf-8", "latin-1"]:
        try:
            return body.decode(candidate), candidate
        except (UnicodeDecodeError, LookupError):
            continue
    # Unreachable: latin-1 always succeeds, but keep mypy/readers happy.
    return body.decode("latin-1", errors="replace"), "latin-1"


def _process_redirect_response(
    status_code: int, meta: str, request_info: dict[str, Any]
) -> "GeminiRedirectResult | GeminiErrorResult":
    """Process redirect response (status 30-31).

    Args:
        status_code: Gemini status code
        meta: Redirect URL
        request_info: Request information

    Returns:
        GeminiRedirectResult, or GeminiErrorResult for a malformed redirect.
    """

    permanent = status_code == GeminiStatusCode.PERMANENT_REDIRECT.value

    # The meta of a 3x response is the redirect target URL and must be present.
    # An empty/blank meta is malformed: urljoin would resolve it to the request
    # URL, so a client following newUrl would re-fetch the same URL forever.
    target = meta.strip()
    if not target:
        return GeminiErrorResult(
            error={
                "code": "INVALID_REDIRECT",
                "message": "Server sent a redirect (3x) with an empty target URL",
                "status": status_code,
            },
            requestInfo=request_info,
        )

    base_url = str(request_info.get("url", ""))
    resolved = _resolve_gemini_reference(base_url, target) if base_url else target

    # Guard against a redirect to the same URL (a one-hop loop) so a single
    # malformed response cannot drive an unbounded client re-fetch loop.
    if base_url and resolved == base_url:
        return GeminiErrorResult(
            error={
                "code": "INVALID_REDIRECT",
                "message": "Server redirected to the same URL (redirect loop)",
                "status": status_code,
            },
            requestInfo=request_info,
        )

    return GeminiRedirectResult(
        newUrl=resolved,
        permanent=permanent,
        requestInfo=request_info,
    )


def _resolve_gemini_reference(base_url: str, target: str) -> str:
    """Resolve a (possibly relative) Gemini redirect target against ``base_url``.

    ``urllib.parse.urljoin`` doesn't treat ``gemini`` as a hierarchical scheme,
    so relative references would pass through unresolved. Resolve under an
    ``https`` placeholder (which urljoin understands) and swap the scheme back.
    An absolute reference that carries its own scheme (gemini://, https://, ...)
    is returned unchanged so the caller/SSRF layer can inspect cross-scheme or
    cross-host redirects.
    """
    if urlparse(target).scheme:  # already absolute
        return target

    if not base_url.startswith("gemini://"):
        return urljoin(base_url, target)

    placeholder_base = "https://" + base_url[len("gemini://") :]
    joined = urljoin(placeholder_base, target)
    if joined.startswith("https://"):
        return "gemini://" + joined[len("https://") :]
    return joined


def _process_error_response(
    status_code: int, meta: str, request_info: dict[str, Any], temporary: bool = True
) -> "GeminiErrorResult":
    """Process error response (status 40-59).

    Args:
        status_code: Gemini status code
        meta: Error message
        request_info: Request information
        temporary: Whether error is temporary (40-49) or permanent (50-59)

    Returns:
        GeminiErrorResult object
    """

    error_type = "TEMPORARY_ERROR" if temporary else "PERMANENT_ERROR"

    return GeminiErrorResult(
        error={
            "code": error_type,
            "message": meta,
            "status": status_code,
            "temporary": temporary,
        },
        requestInfo=request_info,
    )


def _process_certificate_response(
    status_code: int, meta: str, request_info: dict[str, Any]
) -> "GeminiCertificateResult":
    """Process certificate request response (status 60-62).

    The three subcodes mean different things and must not be collapsed:

    * 60 CERTIFICATE_REQUIRED -- the server is prompting the client to present
      a certificate and retry (``required=True``).
    * 61 CERTIFICATE_NOT_AUTHORIZED -- the presented identity was refused.
    * 62 CERTIFICATE_NOT_VALID -- the presented certificate is expired/invalid.

    61 and 62 are *rejections*, so ``required`` is False: re-prompting for a
    fresh certificate (as if none had been sent) would just loop.

    Args:
        status_code: Gemini status code (60-69).
        meta: Certificate-related message.
        request_info: Request information.

    Returns:
        GeminiCertificateResult object.
    """

    required = status_code == GeminiStatusCode.CERTIFICATE_REQUIRED.value

    return GeminiCertificateResult(
        message=meta,
        status=status_code,
        required=required,
        requestInfo=request_info,
    )
