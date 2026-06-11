"""MIME-type helpers for the gopher and gemini protocols.

``guess_mime_type`` maps a Gopher item type/extension to a MIME type;
``detect_binary_mime_type`` sniffs binary content by signature; the rest
parse, default, validate and deny-list Gemini MIME types.
"""

from .models import GeminiMimeType


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


def parse_gemini_mime_type(mime_string: str) -> "GeminiMimeType":
    """Parse MIME type string into GeminiMimeType object.

    Args:
        mime_string: MIME type string (e.g., "text/gemini; charset=utf-8")

    Returns:
        Parsed GeminiMimeType object

    Raises:
        ValueError: If MIME type format is invalid
    """

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

    for raw_param in parts[1:]:
        param = raw_param.strip()
        if "=" in param:
            key, value = param.split("=", 1)
            key = key.strip().lower()
            value = value.strip().strip("\"'")  # Remove quotes

            # Ignore empty values (e.g. "charset=") so they fall back to the
            # default rather than propagating an empty string downstream.
            if key == "charset" and value:
                charset = value
            elif key == "lang" and value:
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

    # Validate language tag format (basic check). The Gemini spec permits a
    # comma-separated LIST of BCP47 tags (e.g. "en,fr"), so validate each tag
    # rather than the whole string -- a bare letters/numbers/hyphens regex would
    # reject a spec-valid list, and the caller then discards the entire MIME type
    # (charset included) on that failure.
    if mime_type.lang:
        import re

        tags = mime_type.lang.split(",")
        if not all(re.fullmatch(r"[a-zA-Z0-9-]+", tag) for tag in tags):
            return False

    return True


def mime_is_denied(full_type: str, denied: "frozenset[str] | set[str]") -> bool:
    """Whether ``full_type`` matches a deny-list entry (exact or ``type/*``)."""
    if not denied:
        return False
    full = full_type.lower()
    if full in denied:
        return True
    top = full.split("/", 1)[0]
    return f"{top}/*" in denied
