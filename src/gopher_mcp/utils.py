"""Utility functions for Gopher protocol operations."""

from typing import List, Optional
from urllib.parse import unquote, urlparse

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

    parsed = urlparse(url)

    if not parsed.hostname:
        raise ValueError("URL must contain a hostname")

    host = parsed.hostname
    port = parsed.port or 70

    # Parse the path to extract gopher type and selector
    path = parsed.path or "/"

    if len(path) <= 1:
        # Empty path or just "/", default to directory listing
        gopher_type = "1"
        selector = ""
    else:
        # First character after "/" is the gopher type
        gopher_type = path[1]
        selector = path[2:] if len(path) > 2 else ""

    # Handle search queries (type 7)
    search = None
    if parsed.query:
        # URL-decode the query
        search = unquote(parsed.query)
    elif "%09" in selector:
        # Handle tab-separated search in selector
        parts = selector.split("%09", 1)
        selector = parts[0]
        search = unquote(parts[1]) if len(parts) > 1 else ""

    return GopherURL(
        host=host,
        port=port,
        gopherType=gopher_type,
        selector=selector,
        search=search,
    )


def parse_menu_line(line: str) -> Optional[GopherMenuItem]:
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
        port = int(parts[3]) if parts[3].isdigit() else 70

        # Construct the next URL
        next_url = f"gopher://{host}:{port}/{item_type}{selector}"

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


def parse_gopher_menu(content: str) -> List[GopherMenuItem]:
    """Parse a complete Gopher menu response.

    Args:
        content: Raw menu content from Gopher server

    Returns:
        List of parsed menu items

    """
    items = []

    for line in content.split("\n"):
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
            raise ValueError(f"Selector contains forbidden character: {repr(char)}")

    # Limit length
    if len(selector) > 255:
        raise ValueError("Selector too long (max 255 characters)")

    return selector


def format_gopher_url(
    host: str,
    port: int = 70,
    gopher_type: str = "1",
    selector: str = "",
    search: Optional[str] = None,
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

    # Build the URL
    url = f"gopher://{host}"

    if port != 70:
        url += f":{port}"

    url += f"/{gopher_type}{selector}"

    if search and gopher_type == "7":
        url += f"%09{search}"

    return url


def guess_mime_type(gopher_type: str, selector: str = "") -> str:
    """Guess MIME type from Gopher type and selector.

    Args:
        gopher_type: Gopher item type
        selector: Selector string (for file extension hints)

    Returns:
        Guessed MIME type

    """
    # Standard Gopher type mappings
    type_mappings = {
        "0": "text/plain",
        "1": "text/gopher-menu",
        "4": "application/mac-binhex40",
        "5": "application/zip",
        "6": "application/x-uuencoded",
        "7": "text/gopher-menu",  # Search results are menus
        "9": "application/octet-stream",
        "g": "image/gif",
        "I": "image/jpeg",  # Generic image
    }

    mime_type = type_mappings.get(gopher_type, "application/octet-stream")

    # Refine based on file extension if available
    if selector and "." in selector:
        extension = selector.split(".")[-1].lower()
        extension_mappings = {
            "txt": "text/plain",
            "html": "text/html",
            "htm": "text/html",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "pdf": "application/pdf",
            "zip": "application/zip",
            "tar": "application/x-tar",
            "gz": "application/gzip",
        }

        if extension in extension_mappings:
            mime_type = extension_mappings[extension]

    return mime_type


def validate_gopher_response(content: bytes, max_size: int) -> None:
    """Validate a Gopher response.

    Args:
        content: Response content
        max_size: Maximum allowed size

    Raises:
        ValueError: If response is invalid

    """
    if len(content) > max_size:
        raise ValueError(f"Response too large: {len(content)} bytes (max {max_size})")

    # Additional validation could be added here
    # e.g., checking for proper termination markers
