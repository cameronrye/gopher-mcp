"""Gopher URL and menu parsing, selector sanitizing, and item-type categories."""

import re
from urllib.parse import quote, unquote, urlparse

from .helpers import bracket_host, sanitize_display_text
from .models import GopherMenuItem, GopherURL

# A single percent escape -- the form ``encode_item_type`` emits for an item
# type character that cannot appear literally in a URL path.
_ESCAPE_RE = re.compile(r"%([0-9A-Fa-f]{2})")

# ASCII punctuation that is safe to leave literal in the item-type position:
# unreserved per RFC 3986. Everything else in ASCII (notably '?', '#', '/', '%'
# and the control characters) is percent-encoded.
_UNRESERVED_PUNCTUATION = "+-._~"


def _encode_item_type(item_type: str) -> str:
    """Percent-encode a Gopher item type for the first character of a URL path.

    The type character is fully server-controlled, so a '?', '#', '/' or control
    byte would otherwise restructure the URL: ``?Click`` turns the selector into
    a search query and ``#`` swallows it into a fragment. Non-ASCII characters
    carry no URL syntax and are left literal so they survive the round trip.

    Args:
        item_type: Single-character Gopher item type.

    Returns:
        The item type, percent-encoded when it is unsafe ASCII.

    """
    if (
        len(item_type) == 1
        and item_type.isascii()
        and not (item_type.isalnum() or item_type in _UNRESERVED_PUNCTUATION)
    ):
        return f"%{ord(item_type):02X}"
    return item_type


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
        # First character after "/" is the gopher type, percent-encoded by
        # ``_encode_item_type`` when it is unsafe ASCII. Decode that single
        # escape back so the type survives the round trip; a non-ASCII byte is
        # not something the encoder emits, so leave it read literally.
        escape = _ESCAPE_RE.match(path, 1)
        if escape and int(escape.group(1), 16) < 0x80:
            gopher_type = chr(int(escape.group(1), 16))
            raw_selector = path[escape.end() :]
        else:
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
        # A line with fewer than four fields is malformed. An explicit info line
        # ("iSome banner text" with the trailing fields omitted) is common enough
        # that lenient clients still render its text, so degrade it to an info
        # item rather than dropping the content; it has no navigable target, so
        # it carries no selector/host/nextUrl. Any other short line is genuine
        # junk -- its first character is not reliably an item type, so reading it
        # as one would mangle the text.
        info_title = sanitize_display_text(parts[0][1:], keep_whitespace=False)
        if not parts[0].startswith("i") or not info_title:
            return None
        return GopherMenuItem(
            type="i",
            title=info_title,
            selector="",
            host="",
            port=0,
            nextUrl="",
        )

    try:
        item_type = parts[0][0] if parts[0] else "i"  # Default to info line
        # Every field below is server-controlled and reaches the model verbatim,
        # so strip ANSI escapes and other control characters before use --
        # including from the selector, which the outbound path would reject
        # anyway, so that nextUrl is built from the usable value.
        display = sanitize_display_text(
            parts[0][1:] if len(parts[0]) > 1 else "", keep_whitespace=False
        )
        selector = sanitize_display_text(parts[1], keep_whitespace=False)
        host = sanitize_display_text(parts[2], keep_whitespace=False)
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

        # hURL web-link convention: a selector of the form "URL:<target>"
        # (overwhelmingly on type-h items, but recognised by selector prefix
        # like real clients do) is a direct link to <target> -- usually an
        # http/https/gemini URL -- NOT a gopher selector. Surface the real
        # destination so the model can follow it, instead of a gopher:// URL
        # that would just re-fetch the gopher host. Match the exact "URL:"
        # prefix so an ordinary selector that merely starts with "url" is left
        # alone.
        if selector.startswith("URL:") and len(selector) > 4:
            next_url = selector[4:]
        else:
            # Construct the next URL. Percent-encode the item type and the
            # selector (keeping '/') so a server-chosen '?', '#' or '%' in either
            # round-trips back through parse_gopher_url instead of mis-splitting
            # into a bogus query, fragment or search. Bracket an IPv6 literal
            # host so its colons don't collide with the port separator and break
            # the re-parse.
            next_url = (
                f"gopher://{bracket_host(host)}:{port}/"
                f"{_encode_item_type(item_type)}{quote(selector, safe='/')}"
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


def parse_gopher_menu(
    content: str, max_items: int | None = None
) -> list[GopherMenuItem]:
    """Parse a complete Gopher menu response.

    Args:
        content: Raw menu content from Gopher server
        max_items: Stop after constructing this many items (None = unlimited).
            A 1 MB directory can hold tens of thousands of lines; without a cap
            every one becomes a model object even though the caller only keeps a
            slice. The caller passes its display cap + 1 so it can still detect
            (and flag) truncation without materialising the whole directory.

    Returns:
        List of parsed menu items (at most ``max_items`` when set).

    """
    items: list[GopherMenuItem] = []

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
            if max_items is not None and len(items) >= max_items:
                break

    return items


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
