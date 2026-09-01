"""MIME-type helpers for the gopher and gemini protocols.

``detect_binary_mime_type`` sniffs binary content by signature; the rest
parse, default, validate and deny-list Gemini MIME types.
"""

from .models import GeminiMimeType


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


def _looks_like_bmp(content: bytes) -> bool:
    """Whether ``content`` is a BMP rather than text starting with "BM"."""
    # The 14-byte BITMAPFILEHEADER reserves bytes 6-9, which real encoders zero.
    return len(content) >= 14 and content[6:10] == b"\x00\x00\x00\x00"


def _looks_like_id3(content: bytes) -> bool:
    """Whether ``content`` is an ID3v2 tag rather than text starting with "ID3"."""
    # ID3v2: "ID3", major version (2-4) and revision (never 0xFF), flags, then a
    # four-byte synchsafe size whose bytes all have the high bit clear.
    return (
        len(content) >= 10
        and content[3] in (2, 3, 4)
        and content[4] != 0xFF
        and all(byte < 0x80 for byte in content[6:10])
    )


def _looks_like_pe(content: bytes) -> bool:
    """Whether ``content`` is a PE executable rather than text starting with "MZ"."""
    # The DOS stub's e_lfanew (offset 0x3C) points at the "PE\0\0" signature.
    if len(content) < 0x40:
        return False
    pe_offset = int.from_bytes(content[0x3C:0x40], "little")
    return content[pe_offset : pe_offset + 4] == b"PE\x00\x00"


def detect_binary_mime_type(content: bytes) -> str:
    """Detect MIME type from binary content headers.

    Signatures that are only two or three printable ASCII bytes ("BM", "MZ",
    "ID3") need corroborating structure: matching them on the prefix alone
    classified ordinary prose as binary, and the Gemini success path then
    withholds binary content from the model entirely.

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
    elif header.startswith(b"BM") and _looks_like_bmp(content):
        return "image/bmp"

    # Document formats
    elif header.startswith(b"%PDF"):
        return "application/pdf"
    elif header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06"):
        # Could be ZIP, DOCX, XLSX, etc.
        return "application/zip"

    # Audio/Video formats. MPEG audio frame syncs cover MPEG-1 and MPEG-2
    # Layer III, with and without a CRC.
    elif (header.startswith(b"ID3") and _looks_like_id3(content)) or header[:2] in (
        b"\xff\xfb",
        b"\xff\xf3",
        b"\xff\xf2",
    ):
        return "audio/mpeg"
    elif header.startswith(b"OggS"):
        return "audio/ogg"
    elif header.startswith(b"RIFF") and len(content) > 11 and content[8:12] == b"WAVE":
        return "audio/wav"
    elif len(content) >= 12 and content[4:8] == b"ftyp":
        # Any ISO base-media file: the box size varies and the brand may be
        # isom/mp42/M4V/... -- keying on the 'ftyp' box is the standard check.
        return "video/mp4"

    # Archive formats
    elif header.startswith(b"\x1f\x8b"):
        return "application/gzip"
    elif header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"

    # Executable formats
    elif header.startswith(b"MZ") and _looks_like_pe(content):
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
