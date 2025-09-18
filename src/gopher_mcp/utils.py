"""Utility functions for Gopher protocol operations."""

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from urllib.parse import unquote, urlparse

from .models import (
    GopherMenuItem,
    GopherURL,
    GeminiURL,
    GemtextDocument,
    GeminiResponse,
    GeminiMimeType,
    GeminiFetchResponse,
    GeminiInputResult,
    GeminiSuccessResult,
    GeminiGemtextResult,
    GeminiRedirectResult,
    GeminiErrorResult,
    GeminiCertificateResult,
)


def atomic_write_json(file_path: str, data: Any) -> None:
    """Atomically write JSON data to a file.

    This function writes to a temporary file first, then renames it to the target
    path. On Windows, it handles the case where the target file already exists.

    Args:
        file_path: Target file path
        data: Data to write as JSON

    Raises:
        Exception: If the write operation fails
    """
    # Ensure directory exists
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    # Create temporary file in the same directory as the target
    temp_dir = Path(file_path).parent
    with tempfile.NamedTemporaryFile(
        mode="w", dir=temp_dir, delete=False, suffix=".tmp"
    ) as temp_file:
        json.dump(data, temp_file, indent=2)
        temp_path = temp_file.name

    try:
        # On Windows, we need to remove the target file first if it exists
        if os.name == "nt" and Path(file_path).exists():
            Path(file_path).unlink()

        # Rename temporary file to target
        Path(temp_path).rename(file_path)
    except Exception:
        # Clean up temporary file if rename fails
        try:
            Path(temp_path).unlink()
        except Exception:  # nosec B110
            pass  # Ignore cleanup failures to preserve original error
        raise


def get_home_directory() -> Optional[Path]:
    """Get the user's home directory with fallback handling.

    Returns:
        Path to home directory or None if it cannot be determined
    """
    try:
        return Path.home()
    except Exception:
        # Fallback to environment variables
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
        if home:
            return Path(home)
        return None


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

    # Check URL length limit (1024 bytes as per Gemini spec)
    if len(url.encode("utf-8")) > 1024:
        raise ValueError("URL must not exceed 1024 bytes")

    try:
        parsed = urlparse(url)
    except ValueError as e:
        # Handle port parsing errors from urllib
        if "Port out of range" in str(e):
            raise ValueError("Invalid port number: port out of range")
        raise

    if not parsed.hostname:
        raise ValueError("URL must contain a hostname")

    # Gemini spec forbids userinfo and fragment
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain userinfo (username/password)")

    if parsed.fragment:
        raise ValueError("URL must not contain fragment")

    host = parsed.hostname
    port = parsed.port or 1965  # Default Gemini port
    path = parsed.path or "/"  # Default to root path
    query = parsed.query or None  # Query string for user input

    # Validate port range (additional check in case urllib didn't catch it)
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
    query: Optional[str] = None,
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
    # Build the URL
    url = f"gemini://{host}"

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


def _detect_language_from_alt_text(alt_text: Optional[str]) -> Optional[str]:
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


def _extract_preformat_metadata(
    alt_text: Optional[str], content: str
) -> Dict[str, Any]:
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


def _parse_gemtext_link_line(line: str) -> Optional[Dict[str, Optional[str]]]:
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


def parse_gemtext(content: str) -> "GemtextDocument":
    """Parse gemtext content into structured format.

    Args:
        content: Raw gemtext content

    Returns:
        Parsed gemtext document

    """
    # Import here to avoid circular imports
    from .models import (
        GemtextDocument,
        GemtextLine,
        GemtextLineType,
        GemtextLink,
        GemtextHeading,
        GemtextList,
        GemtextQuote,
        GemtextPreformat,
    )

    lines = []
    links = []
    in_preformat = False
    current_alt_text = None

    # Split content into lines, preserving line endings
    raw_lines = content.splitlines()

    for raw_line in raw_lines:
        line_content = raw_line.rstrip()  # Remove trailing whitespace

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
                    GemtextLine(
                        type=GemtextLineType.PREFORMAT,
                        content=line_content,
                        link=None,
                        level=None,
                        alt_text=current_alt_text,
                        heading=None,
                        list_item=None,
                        quote=None,
                        preformat=preformat_obj,
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
                    GemtextLine(
                        type=GemtextLineType.PREFORMAT,
                        content=line_content,
                        link=None,
                        level=None,
                        alt_text=current_alt_text,
                        heading=None,
                        list_item=None,
                        quote=None,
                        preformat=preformat_obj,
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
                GemtextLine(
                    type=GemtextLineType.PREFORMAT,
                    content=line_content,
                    link=None,
                    level=None,
                    alt_text=current_alt_text,
                    heading=None,
                    list_item=None,
                    quote=None,
                    preformat=preformat_obj,
                )
            )

        elif line_content.startswith("=>"):
            # Link line
            link_data = _parse_gemtext_link_line(line_content)
            if link_data and link_data["url"]:
                link_obj = GemtextLink(url=link_data["url"], text=link_data["text"])
                links.append(link_obj)
                lines.append(
                    GemtextLine(
                        type=GemtextLineType.LINK,
                        content=line_content,
                        link=link_obj,
                        level=None,
                        alt_text=None,
                        heading=None,
                        list_item=None,
                        quote=None,
                        preformat=None,
                    )
                )
            else:
                # Invalid link line, treat as text
                lines.append(
                    GemtextLine(
                        type=GemtextLineType.TEXT,
                        content=line_content,
                        link=None,
                        level=None,
                        alt_text=None,
                        heading=None,
                        list_item=None,
                        quote=None,
                        preformat=None,
                    )
                )

        elif line_content.startswith("###"):
            # Heading level 3
            heading_text = line_content[3:].strip()
            heading_obj = GemtextHeading(
                level=3,
                text=heading_text,
                raw_content=line_content,
            )
            lines.append(
                GemtextLine(
                    type=GemtextLineType.HEADING_3,
                    content=line_content,
                    link=None,
                    level=3,
                    alt_text=None,
                    heading=heading_obj,
                    list_item=None,
                    quote=None,
                    preformat=None,
                )
            )

        elif line_content.startswith("##"):
            # Heading level 2
            heading_text = line_content[2:].strip()
            heading_obj = GemtextHeading(
                level=2,
                text=heading_text,
                raw_content=line_content,
            )
            lines.append(
                GemtextLine(
                    type=GemtextLineType.HEADING_2,
                    content=line_content,
                    link=None,
                    level=2,
                    alt_text=None,
                    heading=heading_obj,
                    list_item=None,
                    quote=None,
                    preformat=None,
                )
            )

        elif line_content.startswith("#"):
            # Heading level 1
            heading_text = line_content[1:].strip()
            heading_obj = GemtextHeading(
                level=1,
                text=heading_text,
                raw_content=line_content,
            )
            lines.append(
                GemtextLine(
                    type=GemtextLineType.HEADING_1,
                    content=line_content,
                    link=None,
                    level=1,
                    alt_text=None,
                    heading=heading_obj,
                    list_item=None,
                    quote=None,
                    preformat=None,
                )
            )

        elif line_content.startswith("* "):
            # List item (must have space after asterisk)
            list_text = line_content[2:].strip()
            list_obj = GemtextList(
                text=list_text,
                raw_content=line_content,
            )
            lines.append(
                GemtextLine(
                    type=GemtextLineType.LIST_ITEM,
                    content=line_content,
                    link=None,
                    level=None,
                    alt_text=None,
                    heading=None,
                    list_item=list_obj,
                    quote=None,
                    preformat=None,
                )
            )

        elif line_content.startswith(">"):
            # Quote line
            quote_text = line_content[1:].strip()
            quote_obj = GemtextQuote(
                text=quote_text,
                raw_content=line_content,
            )
            lines.append(
                GemtextLine(
                    type=GemtextLineType.QUOTE,
                    content=line_content,
                    link=None,
                    level=None,
                    alt_text=None,
                    heading=None,
                    list_item=None,
                    quote=quote_obj,
                    preformat=None,
                )
            )

        else:
            # Default: text line
            lines.append(
                GemtextLine(
                    type=GemtextLineType.TEXT,
                    content=line_content,
                    link=None,
                    level=None,
                    alt_text=None,
                    heading=None,
                    list_item=None,
                    quote=None,
                    preformat=None,
                )
            )

    return GemtextDocument(lines=lines, links=links)


def validate_gemini_url_components(
    host: str,
    port: int = 1965,
    path: str = "/",
    query: Optional[str] = None,
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

        # Validate status code
        if not status_str.isdigit():
            raise ValueError(f"Invalid status code: {status_str}")

        status_code = int(status_str)

        # Validate status code range
        if not (10 <= status_code <= 69):
            raise ValueError(f"Status code out of range: {status_code}")

        # Import here to avoid circular imports
        from .models import GeminiStatusCode, GeminiResponse

        # Convert to enum
        try:
            status_enum: Union[GeminiStatusCode, int] = GeminiStatusCode(status_code)
        except ValueError:
            # Handle unknown status codes within valid range
            status_enum = status_code

        return GeminiResponse(status=status_enum, meta=meta, body=body)

    except UnicodeDecodeError as e:
        raise ValueError(f"Invalid UTF-8 in status line: {e}")
    except Exception as e:
        raise ValueError(f"Failed to parse response: {e}")


def parse_gemini_mime_type(mime_string: str) -> "GeminiMimeType":
    """Parse MIME type string into GeminiMimeType object.

    Args:
        mime_string: MIME type string (e.g., "text/gemini; charset=utf-8")

    Returns:
        Parsed GeminiMimeType object

    Raises:
        ValueError: If MIME type format is invalid
    """
    from .models import GeminiMimeType

    if not mime_string.strip():
        raise ValueError("Empty MIME type")

    # Split main type from parameters
    parts = mime_string.split(";")
    main_type = parts[0].strip()

    # Parse main type/subtype
    if "/" not in main_type:
        raise ValueError(f"Invalid MIME type format: {main_type}")

    type_parts = main_type.split("/", 1)
    if len(type_parts) != 2:
        raise ValueError(f"Invalid MIME type format: {main_type}")

    mime_type = type_parts[0].strip().lower()
    mime_subtype = type_parts[1].strip().lower()

    if not mime_type or not mime_subtype:
        raise ValueError(f"Invalid MIME type format: {main_type}")

    # Check for additional slashes in subtype (invalid)
    if "/" in mime_subtype:
        raise ValueError(f"Invalid MIME type format: {main_type}")

    # Parse parameters
    charset = "utf-8"  # Default
    lang = None

    for param in parts[1:]:
        param = param.strip()
        if "=" in param:
            key, value = param.split("=", 1)
            key = key.strip().lower()
            value = value.strip().strip("\"'")  # Remove quotes

            if key == "charset":
                charset = value
            elif key == "lang":
                lang = value
            # Note: content-encoding not supported in Gemini protocol

    return GeminiMimeType(
        type=mime_type, subtype=mime_subtype, charset=charset, lang=lang
    )


def get_default_gemini_mime_type() -> "GeminiMimeType":
    """Get default MIME type for Gemini responses.

    Returns:
        Default GeminiMimeType (text/gemini; charset=utf-8)
    """
    from .models import GeminiMimeType

    return GeminiMimeType(type="text", subtype="gemini", charset="utf-8", lang=None)


def detect_binary_mime_type(content: bytes) -> str:
    """Detect MIME type from binary content headers.

    Args:
        content: Binary content to analyze

    Returns:
        Detected MIME type string or 'application/octet-stream' as fallback
    """
    if not content:
        return "application/octet-stream"

    # Get first 16 bytes for header analysis
    header = content[:16]

    # Image formats
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    elif header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    elif header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"
    elif header.startswith(b"RIFF") and len(content) > 11 and content[8:12] == b"WEBP":
        return "image/webp"
    elif header.startswith(b"BM"):
        return "image/bmp"

    # Document formats
    elif header.startswith(b"%PDF"):
        return "application/pdf"
    elif header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06"):
        # Could be ZIP, DOCX, XLSX, etc.
        return "application/zip"

    # Audio/Video formats
    elif header.startswith(b"ID3") or header.startswith(b"\xff\xfb"):
        return "audio/mpeg"
    elif header.startswith(b"OggS"):
        return "audio/ogg"
    elif header.startswith(b"RIFF") and len(content) > 11 and content[8:12] == b"WAVE":
        return "audio/wav"
    elif header.startswith(b"\x00\x00\x00\x18ftypmp4") or header.startswith(
        b"\x00\x00\x00\x20ftypmp4"
    ):
        return "video/mp4"

    # Archive formats
    elif header.startswith(b"\x1f\x8b"):
        return "application/gzip"
    elif header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"

    # Executable formats
    elif header.startswith(b"MZ"):
        return "application/x-msdownload"
    elif header.startswith(b"\x7fELF"):
        return "application/x-executable"

    # Default fallback
    return "application/octet-stream"


def validate_gemini_mime_type(mime_type: "GeminiMimeType") -> bool:
    """Validate that a MIME type is appropriate for Gemini protocol.

    Args:
        mime_type: GeminiMimeType to validate

    Returns:
        True if valid for Gemini, False otherwise
    """
    # All MIME types are technically valid in Gemini
    # But we can check for common issues

    # Check for empty or invalid components
    if not mime_type.type or not mime_type.subtype:
        return False

    # Check charset for text types
    if mime_type.is_text and not mime_type.charset:
        return False

    # Validate language tag format (basic check)
    if mime_type.lang:
        # Basic BCP47 validation - should contain only letters, numbers, and hyphens
        import re

        if not re.match(r"^[a-zA-Z0-9-]+$", mime_type.lang):
            return False

    return True


def process_gemini_response(
    response: "GeminiResponse", request_url: str, request_time: Optional[float] = None
) -> "GeminiFetchResponse":
    """Process Gemini response based on status code.

    Args:
        response: Parsed Gemini response
        request_url: Original request URL
        request_time: Request timestamp (defaults to current time)

    Returns:
        Appropriate response result object based on status code

    Raises:
        ValueError: If status code is unsupported or response is invalid
    """
    import time
    from .models import (
        GeminiErrorResult,
    )

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

    # Success (20-29)
    elif 20 <= status_code <= 29:
        return _process_success_response(meta, body, request_info)

    # Redirect (30-39)
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
    status_code: int, meta: str, request_info: Dict[str, Any]
) -> "GeminiInputResult":
    """Process input request response (status 10-11).

    Args:
        status_code: Gemini status code
        meta: Input prompt text
        request_info: Request information

    Returns:
        GeminiInputResult object
    """
    from .models import GeminiInputResult, GeminiStatusCode

    sensitive = status_code == GeminiStatusCode.SENSITIVE_INPUT.value

    return GeminiInputResult(
        prompt=meta,
        sensitive=sensitive,
        requestInfo=request_info,
    )


def _process_success_response(
    meta: str, body: Optional[bytes], request_info: Dict[str, Any]
) -> Union["GeminiSuccessResult", "GeminiGemtextResult"]:
    """Process success response (status 20-29).

    Args:
        meta: MIME type string
        body: Response body bytes
        request_info: Request information

    Returns:
        GeminiSuccessResult or GeminiGemtextResult based on content type

    Raises:
        ValueError: If MIME type is invalid or body is missing
    """
    from .models import GeminiSuccessResult

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
        # For binary content, try to detect MIME type from content
        if body and len(body) > 0:
            detected_type = detect_binary_mime_type(body)
            try:
                mime_type = parse_gemini_mime_type(detected_type)
            except ValueError:
                # Fallback to default
                mime_type = get_default_gemini_mime_type()
        else:
            # For empty body, fallback to default
            mime_type = get_default_gemini_mime_type()

    size = len(body)

    # Handle gemtext content specially
    if mime_type.is_gemtext:
        try:
            content = body.decode(mime_type.charset)
            # Parse gemtext into structured format
            document = parse_gemtext(content)

            # Import here to avoid circular imports
            from .models import GeminiGemtextResult

            return GeminiGemtextResult(
                document=document,
                rawContent=content,
                charset=mime_type.charset,
                lang=mime_type.lang,
                size=size,
                requestInfo=request_info,
            )
        except UnicodeDecodeError as e:
            # Try fallback charsets for gemtext content
            for fallback_charset in ["latin1", "ascii", "utf-8"]:
                if fallback_charset != mime_type.charset:
                    try:
                        content = body.decode(fallback_charset)
                        # Update charset in mime_type
                        mime_type.charset = fallback_charset
                        return GeminiSuccessResult(
                            mimeType=mime_type,
                            content=content,
                            size=size,
                            requestInfo=request_info,
                        )
                    except UnicodeDecodeError:
                        continue
            raise ValueError(f"Failed to decode gemtext content with any charset: {e}")

    # Handle text content
    elif mime_type.is_text:
        try:
            content = body.decode(mime_type.charset)
            return GeminiSuccessResult(
                mimeType=mime_type,
                content=content,
                size=size,
                requestInfo=request_info,
            )
        except UnicodeDecodeError as e:
            # Try fallback charsets for text content
            for fallback_charset in ["latin1", "ascii", "utf-8"]:
                if fallback_charset != mime_type.charset:
                    try:
                        content = body.decode(fallback_charset)
                        # Update charset in mime_type
                        mime_type.charset = fallback_charset
                        return GeminiSuccessResult(
                            mimeType=mime_type,
                            content=content,
                            size=size,
                            requestInfo=request_info,
                        )
                    except UnicodeDecodeError:
                        continue
            raise ValueError(f"Failed to decode text content with any charset: {e}")

    # Handle binary content
    else:
        # For binary content, ensure we have the right MIME type
        if mime_type.full_type == "application/octet-stream" and body:
            # Try to detect a more specific MIME type
            detected_type = detect_binary_mime_type(body)
            if detected_type != "application/octet-stream":
                try:
                    mime_type = parse_gemini_mime_type(detected_type)
                except ValueError:
                    pass  # Keep original mime_type

        return GeminiSuccessResult(
            mimeType=mime_type,
            content=body,  # Keep as bytes for binary content
            size=size,
            requestInfo=request_info,
        )


def _process_redirect_response(
    status_code: int, meta: str, request_info: Dict[str, Any]
) -> "GeminiRedirectResult":
    """Process redirect response (status 30-31).

    Args:
        status_code: Gemini status code
        meta: Redirect URL
        request_info: Request information

    Returns:
        GeminiRedirectResult object
    """
    from .models import GeminiRedirectResult, GeminiStatusCode

    permanent = status_code == GeminiStatusCode.PERMANENT_REDIRECT.value

    return GeminiRedirectResult(
        newUrl=meta,
        permanent=permanent,
        requestInfo=request_info,
    )


def _process_error_response(
    status_code: int, meta: str, request_info: Dict[str, Any], temporary: bool = True
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
    from .models import GeminiErrorResult

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
    status_code: int, meta: str, request_info: Dict[str, Any]
) -> "GeminiCertificateResult":
    """Process certificate request response (status 60-62).

    Args:
        status_code: Gemini status code
        meta: Certificate-related message
        request_info: Request information

    Returns:
        GeminiCertificateResult object
    """
    from .models import GeminiCertificateResult

    return GeminiCertificateResult(
        message=meta,
        required=True,
        requestInfo=request_info,
    )
