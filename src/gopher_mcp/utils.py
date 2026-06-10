"""Utility functions for Gopher protocol operations."""

import contextlib

# ``os`` stays importable from this module so the suite can keep patching
# ``gopher_mcp.utils.os.fsync`` -- the durability fsync used by
# ``atomic_write_json``, which now lives in ``helpers``.
import os  # noqa: F401
import re
from typing import Any, Optional, Union
from urllib.parse import quote, unquote, urljoin, urlparse

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
    GemtextDocument,
    GemtextHeading,
    GemtextLine,
    GemtextLineType,
    GemtextLink,
    GemtextList,
    GemtextPreformat,
    GemtextQuote,
    GopherMenuItem,
    GopherURL,
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


def parse_gopher_url(url: str) -> GopherURL:
    """Parse a Gopher URL into its components.

    Args:
        url: Gopher URL to parse

    Returns:
        Parsed URL components

    Raises:
        ValueError: If URL is invalid

    """
    if not url.startswith("gopher://"):
        raise ValueError("URL must start with 'gopher://'")

    # ``urlparse`` is lazy: an out-of-range port only raises when ``.port`` is
    # accessed, so the access must live inside the try block.
    try:
        parsed = urlparse(url)
        port = parsed.port if parsed.port is not None else 70
    except ValueError as e:
        if "Port out of range" in str(e):
            raise ValueError("Invalid port number: port out of range") from e
        raise

    if not parsed.hostname:
        raise ValueError("URL must contain a hostname")

    # Reject an explicit invalid port instead of silently coercing it (``0`` is
    # falsy, so the old ``parsed.port or 70`` rewrote it to the default).
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid port number: {port}")

    host = parsed.hostname

    # Parse the path to extract gopher type and selector
    path = parsed.path or "/"

    if len(path) <= 1:
        # Empty path or just "/", default to directory listing
        gopher_type = "1"
        raw_selector = ""
    else:
        # First character after "/" is the gopher type
        gopher_type = path[1]
        raw_selector = path[2:] if len(path) > 2 else ""

    # Decode the selector to its on-wire form. Split any embedded %09 search
    # BEFORE decoding so a literal tab in the decoded text can't be confused
    # with the field separator.
    search = None
    if parsed.query:
        search = unquote(parsed.query)
        selector = unquote(raw_selector)
    elif "%09" in raw_selector:
        sel_part, _, search_part = raw_selector.partition("%09")
        selector = unquote(sel_part)
        search = unquote(search_part)
    else:
        selector = unquote(raw_selector)

    # Fail closed on raw control bytes that percent-decoding can introduce. A
    # C0/DEL byte (CR/LF/TAB/NUL/ESC/...) in the selector or search would inject
    # extra fields or terminate the single Gopher request line (which the
    # transport builds as ``selector<TAB>search\r\n``). The client re-checks
    # this too, but the parser must not depend on a separate validation pass --
    # mirror parse_gemini_url and reject here.
    if re.search(r"[\x00-\x1f\x7f]", selector):
        raise ValueError("Selector must not contain control characters")
    if search is not None and re.search(r"[\x00-\x1f\x7f]", search):
        raise ValueError("Search query must not contain control characters")

    return GopherURL(
        host=host,
        port=port,
        gopherType=gopher_type,
        selector=selector,
        search=search,
    )


def parse_menu_line(line: str) -> GopherMenuItem | None:
    """Parse a single Gopher menu line.

    Args:
        line: Raw menu line from Gopher server

    Returns:
        Parsed menu item or None if invalid

    """
    # Remove CRLF
    line = line.rstrip("\r\n")

    # Skip empty lines and termination marker
    if not line or line == ".":
        return None

    # Menu lines are tab-separated: type + display + tab + selector + tab + host + tab + port
    parts = line.split("\t")

    if len(parts) < 4:
        return None

    try:
        item_type = parts[0][0] if parts[0] else "i"  # Default to info line
        display = parts[0][1:] if len(parts[0]) > 1 else ""
        selector = parts[1]
        host = parts[2]
        # ``str.isdigit()`` accepts unicode digits (e.g. "²") that ``int()``
        # rejects; require ASCII so a bad port degrades to the default rather
        # than dropping the whole menu item. Also bound the value: a numeric
        # but out-of-range port (>65535) would otherwise fail model validation
        # and drop the item -- degrade it to 70 instead.
        port = 70
        if parts[3].isascii() and parts[3].isdigit():
            candidate = int(parts[3])
            if 0 <= candidate <= 65535:
                port = candidate

        # Construct the next URL. Percent-encode the selector (keeping '/')
        # so a selector containing spaces, '?', '#' or '%' round-trips back
        # through parse_gopher_url instead of mis-splitting into a bogus query.
        # Bracket an IPv6 literal host so its colons don't collide with the
        # port separator and break the re-parse.
        next_url = (
            f"gopher://{bracket_host(host)}:{port}/"
            f"{item_type}{quote(selector, safe='/')}"
        )

        return GopherMenuItem(
            type=item_type,
            title=display,
            selector=selector,
            host=host,
            port=port,
            nextUrl=next_url,
        )
    except (ValueError, IndexError):
        return None


def parse_gopher_menu(content: str) -> list[GopherMenuItem]:
    """Parse a complete Gopher menu response.

    Args:
        content: Raw menu content from Gopher server

    Returns:
        List of parsed menu items

    """
    items = []

    # Normalize all three RFC 1436 line endings (CRLF), bare LF and legacy
    # bare CR before splitting -- a CR-only server would otherwise collapse the
    # whole menu into one unparseable line. Avoid str.splitlines(), which also
    # breaks on VT/FF/NEL and could split a display string mid-field.
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        # RFC 1436: a lone '.' terminates the menu. Stop here so data a server
        # places AFTER the terminator is never parsed into navigable items.
        # Strip trailing whitespace first so a non-conformant `. ` line still
        # reads as the terminator instead of leaking later items to the model.
        if line.strip() == ".":
            break
        item = parse_menu_line(line)
        if item:
            items.append(item)

    return items


def sanitize_selector(selector: str) -> str:
    """Sanitize a Gopher selector string.

    Args:
        selector: Raw selector string

    Returns:
        Sanitized selector string

    Raises:
        ValueError: If selector contains invalid characters

    """
    # Check for forbidden characters per RFC 1436
    forbidden_chars = ["\t", "\r", "\n"]

    for char in forbidden_chars:
        if char in selector:
            raise ValueError(f"Selector contains forbidden character: {char!r}")

    # Limit length
    if len(selector) > 255:
        raise ValueError("Selector too long (max 255 characters)")

    return selector


def format_gopher_url(
    host: str,
    port: int = 70,
    gopher_type: str = "1",
    selector: str = "",
    search: str | None = None,
) -> str:
    """Format a Gopher URL from components.

    Args:
        host: Hostname
        port: Port number (default 70)
        gopher_type: Gopher item type
        selector: Selector string
        search: Search string for type 7 items

    Returns:
        Formatted Gopher URL

    """
    # Sanitize inputs
    selector = sanitize_selector(selector)

    # Build the URL (bracket an IPv6 literal host per RFC 3986)
    url = f"gopher://{bracket_host(host)}"

    if port != 70:
        url += f":{port}"

    url += f"/{gopher_type}{selector}"

    if search and gopher_type == "7":
        url += f"%09{search}"

    return url


# Canonical Gopher item-type -> handling category. Single source of truth so
# the fetch dispatcher and MIME guessing agree on what each type is, instead of
# maintaining divergent ad-hoc sets. Categories: "menu", "text", "binary",
# "interactive" (no fetchable body). Unknown types fall back to best-effort text.
_GOPHER_TYPE_CATEGORY: dict[str, str] = {
    "0": "text",  # plain text file
    "1": "menu",  # directory/menu
    "7": "menu",  # search server (results are a menu)
    "h": "text",  # HTML (served as text/html)
    "i": "text",  # informational line
    "3": "text",  # error
    "4": "binary",  # BinHexed Macintosh file
    "5": "binary",  # DOS binary / archive
    "6": "binary",  # uuencoded file
    "9": "binary",  # generic binary
    "g": "binary",  # GIF image
    "I": "binary",  # image
    "d": "binary",  # document (PDF/word) by common convention
    "s": "binary",  # sound
    ";": "binary",  # video
    "p": "binary",  # PNG (common extension)
    "M": "binary",  # MIME multipart message
    "<": "binary",  # sound (legacy)
    "2": "interactive",  # CSO name/phone-book server
    "8": "interactive",  # Telnet session
    "T": "interactive",  # tn3270 session
}


def gopher_type_category(gopher_type: str) -> str:
    """Return the handling category for a Gopher item type.

    One of ``"menu"``, ``"text"``, ``"binary"`` or ``"interactive"``. Unknown
    types default to ``"text"`` (best-effort), matching historical behaviour.
    """
    return _GOPHER_TYPE_CATEGORY.get(gopher_type, "text")


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


def _detect_language_from_alt_text(alt_text: str | None) -> str | None:
    """Detect programming language from preformat alt-text.

    Args:
        alt_text: Alt-text from preformat block

    Returns:
        Detected language or None

    """
    if not alt_text:
        return None

    # Normalize alt-text for comparison
    alt_lower = alt_text.lower().strip()

    # Common programming language mappings
    language_map = {
        "python": "python",
        "py": "python",
        "javascript": "javascript",
        "js": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "rust": "rust",
        "rs": "rust",
        "go": "go",
        "golang": "go",
        "c": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "java": "java",
        "kotlin": "kotlin",
        "swift": "swift",
        "ruby": "ruby",
        "rb": "ruby",
        "php": "php",
        "html": "html",
        "css": "css",
        "sql": "sql",
        "bash": "bash",
        "sh": "bash",
        "shell": "bash",
        "json": "json",
        "xml": "xml",
        "yaml": "yaml",
        "yml": "yaml",
        "toml": "toml",
        "markdown": "markdown",
        "md": "markdown",
        "text": "text",
        "txt": "text",
    }

    return language_map.get(alt_lower)


def _extract_preformat_metadata(alt_text: str | None, content: str) -> dict[str, Any]:
    """Extract metadata from preformat block.

    Args:
        alt_text: Alt-text from preformat block
        content: Preformat content

    Returns:
        Metadata dictionary

    """
    metadata = {
        "language": _detect_language_from_alt_text(alt_text),
        "alt_text": alt_text,
        "line_count": len(content.splitlines()) if content else 0,
        "char_count": len(content) if content else 0,
        "is_code": False,
        "is_data": False,
    }

    # Determine content type based on language
    if metadata["language"]:
        code_languages = {
            "python",
            "javascript",
            "typescript",
            "rust",
            "go",
            "c",
            "cpp",
            "java",
            "kotlin",
            "swift",
            "ruby",
            "php",
            "bash",
        }
        data_languages = {"json", "xml", "yaml", "toml", "sql"}

        if metadata["language"] in code_languages:
            metadata["is_code"] = True
        elif metadata["language"] in data_languages:
            metadata["is_data"] = True

    return metadata


def _parse_gemtext_link_line(line: str) -> dict[str, str | None] | None:
    """Parse a gemtext link line.

    Format: =>[whitespace]<URL>[whitespace]<link-text>

    Args:
        line: Raw link line starting with '=>'

    Returns:
        Dict with 'url' and 'text' keys, or None if invalid

    """
    if not line.startswith("=>"):
        return None

    # Remove the '=>' prefix
    content = line[2:]

    # Split on whitespace to separate URL from text
    parts = content.split(None, 1)  # Split on any whitespace, max 1 split

    if not parts:
        return None  # No URL found

    url = parts[0].strip()
    if not url:
        return None  # Empty URL

    # Extract link text if present
    text = None
    if len(parts) > 1:
        text = parts[1].strip()
        if not text:  # Empty text after whitespace
            text = None

    return {"url": url, "text": text}


def _create_gemtext_line(
    line_type: "GemtextLineType",
    content: str,
    link: Optional["GemtextLink"] = None,
    heading: Optional["GemtextHeading"] = None,
    list_item: Optional["GemtextList"] = None,
    quote: Optional["GemtextQuote"] = None,
    preformat: Optional["GemtextPreformat"] = None,
    level: int | None = None,
    alt_text: str | None = None,
) -> "GemtextLine":
    """Create a GemtextLine object with the given parameters.

    Args:
        line_type: Type of the line
        content: Raw line content
        link: Link object if this is a link line
        heading: Heading object if this is a heading line
        list_item: List object if this is a list item line
        quote: Quote object if this is a quote line
        preformat: Preformat object if this is a preformat line
        level: Heading level if this is a heading line
        alt_text: Alt text for preformat blocks

    Returns:
        GemtextLine object
    """

    return GemtextLine(
        type=line_type,
        content=content,
        link=link,
        level=level,
        alt_text=alt_text,
        heading=heading,
        list_item=list_item,
        quote=quote,
        preformat=preformat,
    )


def _parse_heading(line_content: str) -> Optional["GemtextLine"]:
    """Parse a heading line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a heading, None otherwise
    """

    # Strip the leading marker run, then any extra '#'s (a 4th '#' is content,
    # not a 4th level -- gemtext only defines H1-H3), then surrounding space.
    if line_content.startswith("###"):
        heading_text = line_content[3:].lstrip("#").strip()
        heading_obj = GemtextHeading(
            level=3, text=heading_text, raw_content=line_content
        )
        return _create_gemtext_line(
            GemtextLineType.HEADING_3, line_content, heading=heading_obj, level=3
        )
    elif line_content.startswith("##"):
        heading_text = line_content[2:].lstrip("#").strip()
        heading_obj = GemtextHeading(
            level=2, text=heading_text, raw_content=line_content
        )
        return _create_gemtext_line(
            GemtextLineType.HEADING_2, line_content, heading=heading_obj, level=2
        )
    elif line_content.startswith("#"):
        heading_text = line_content[1:].lstrip("#").strip()
        heading_obj = GemtextHeading(
            level=1, text=heading_text, raw_content=line_content
        )
        return _create_gemtext_line(
            GemtextLineType.HEADING_1, line_content, heading=heading_obj, level=1
        )

    return None


def _parse_link(
    line_content: str,
) -> tuple["GemtextLine", Optional["GemtextLink"]] | None:
    """Parse a link line.

    Args:
        line_content: Raw line content

    Returns:
        Tuple of (GemtextLine, GemtextLink) if this is a valid link, (GemtextLine as text, None) if invalid link syntax, None if not a link
    """

    if not line_content.startswith("=>"):
        return None

    link_data = _parse_gemtext_link_line(line_content)
    if link_data and link_data["url"]:
        link_obj = GemtextLink(url=link_data["url"], text=link_data["text"])
        line = _create_gemtext_line(GemtextLineType.LINK, line_content, link=link_obj)
        return (line, link_obj)
    else:
        # Invalid link line, treat as text
        line = _create_gemtext_line(GemtextLineType.TEXT, line_content)
        return (line, None)


def _parse_list_item(line_content: str) -> Optional["GemtextLine"]:
    """Parse a list item line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a list item, None otherwise
    """

    if line_content.startswith("* "):
        list_text = line_content[2:].strip()
        list_obj = GemtextList(text=list_text, raw_content=line_content)
        return _create_gemtext_line(
            GemtextLineType.LIST_ITEM, line_content, list_item=list_obj
        )

    return None


def _parse_quote(line_content: str) -> Optional["GemtextLine"]:
    """Parse a quote line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a quote, None otherwise
    """

    if line_content.startswith(">"):
        # Remove at most a single space after '>', preserving any intentional
        # inner indentation of the quoted text (the gemtext convention).
        quote_text = line_content[1:].removeprefix(" ")
        quote_obj = GemtextQuote(text=quote_text, raw_content=line_content)
        return _create_gemtext_line(
            GemtextLineType.QUOTE, line_content, quote=quote_obj
        )

    return None


def _parse_text(line_content: str) -> "GemtextLine":
    """Parse a text line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object for text
    """

    return _create_gemtext_line(GemtextLineType.TEXT, line_content)


def parse_gemtext(content: str) -> "GemtextDocument":
    """Parse gemtext content into structured format.

    Args:
        content: Raw gemtext content

    Returns:
        Parsed gemtext document

    """

    lines = []
    links = []
    in_preformat = False
    current_alt_text = None

    # Split on CRLF/LF only. ``str.splitlines()`` also breaks on \v, \f, NEL,
    # U+2028/U+2029 etc., which are NOT gemtext line terminators and would
    # corrupt line structure. Drop a single trailing empty element so a final
    # newline doesn't synthesize an extra blank line (matching splitlines).
    normalized = content.replace("\r\n", "\n")
    raw_lines = normalized.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()

    for raw_line in raw_lines:
        # Preformatted content must be preserved verbatim; only rstrip lines we
        # are about to classify in normal mode.
        line_content = raw_line if in_preformat else raw_line.rstrip()

        # Handle preformat mode
        if in_preformat:
            # Check for preformat toggle (end)
            if line_content.startswith("```"):
                # End preformat block
                in_preformat = False
                current_alt_text = None
                preformat_obj = GemtextPreformat(
                    content=line_content,
                    alt_text=None,
                    is_toggle=True,
                    language=None,
                    metadata={},
                )
                lines.append(
                    _create_gemtext_line(
                        GemtextLineType.PREFORMAT,
                        line_content,
                        preformat=preformat_obj,
                        alt_text=current_alt_text,
                    )
                )
                continue
            else:
                # Regular preformat content
                metadata = _extract_preformat_metadata(current_alt_text, line_content)
                preformat_obj = GemtextPreformat(
                    content=line_content,
                    alt_text=current_alt_text,
                    is_toggle=False,
                    language=metadata["language"],
                    metadata=metadata,
                )
                lines.append(
                    _create_gemtext_line(
                        GemtextLineType.PREFORMAT,
                        line_content,
                        preformat=preformat_obj,
                        alt_text=current_alt_text,
                    )
                )
                continue

        # Normal mode - recognize line types
        if line_content.startswith("```"):
            # Start preformat block
            in_preformat = True
            # Extract alt text (everything after ``` and optional whitespace)
            alt_text_part = line_content[3:].strip()
            current_alt_text = alt_text_part if alt_text_part else None
            metadata = _extract_preformat_metadata(current_alt_text, line_content)
            preformat_obj = GemtextPreformat(
                content=line_content,
                alt_text=current_alt_text,
                is_toggle=True,
                language=metadata["language"],
                metadata=metadata,
            )
            lines.append(
                _create_gemtext_line(
                    GemtextLineType.PREFORMAT,
                    line_content,
                    preformat=preformat_obj,
                    alt_text=current_alt_text,
                )
            )

        elif line_content.startswith("=>"):
            # Link line
            result = _parse_link(line_content)
            if result:
                line, link_obj = result
                lines.append(line)
                if link_obj:
                    links.append(link_obj)

        elif (heading_line := _parse_heading(line_content)) is not None:
            lines.append(heading_line)

        elif (list_line := _parse_list_item(line_content)) is not None:
            lines.append(list_line)

        elif (quote_line := _parse_quote(line_content)) is not None:
            lines.append(quote_line)

        else:
            # Default: text line
            lines.append(_parse_text(line_content))

    return GemtextDocument(lines=lines, links=links)


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
