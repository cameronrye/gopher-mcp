"""Gopher URL and menu parsing, selector sanitizing, and item-type categories."""

import re
from urllib.parse import quote, unquote, urlparse

from .helpers import bracket_host
from .models import GopherMenuItem, GopherURL


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
            # Construct the next URL. Percent-encode the selector (keeping '/')
            # so a selector containing spaces, '?', '#' or '%' round-trips back
            # through parse_gopher_url instead of mis-splitting into a bogus
            # query. Bracket an IPv6 literal host so its colons don't collide
            # with the port separator and break the re-parse.
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
