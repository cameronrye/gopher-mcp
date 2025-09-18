"""Pydantic models for Gopher MCP data validation."""

from typing import Any, Dict, List, Literal, Optional, Union
from enum import IntEnum, Enum

from pydantic import BaseModel, Field, field_validator


class GopherFetchRequest(BaseModel):
    """Request model for gopher.fetch tool."""

    url: str = Field(
        ...,
        description="Gopher URL to fetch (e.g., gopher://gopher.floodgap.com/1/)",
        examples=[
            "gopher://gopher.floodgap.com/1/",
            "gopher://gopher.floodgap.com/0/about.txt",
        ],
    )

    @field_validator("url")
    @classmethod
    def validate_gopher_url(cls, v: str) -> str:
        """Validate that the URL is a proper Gopher URL."""
        if not v.startswith("gopher://"):
            raise ValueError("URL must start with 'gopher://'")
        return v


class GopherMenuItem(BaseModel):
    """Model for a single Gopher menu item."""

    type: str = Field(..., description="Gopher item type (single character)")
    title: str = Field(..., description="Human-readable item title")
    selector: str = Field(..., description="Selector string for this item")
    host: str = Field(..., description="Hostname where item resides")
    port: int = Field(..., description="Port number (typically 70)")
    next_url: str = Field(
        ..., alias="nextUrl", description="Fully formed gopher:// URL for this item"
    )


class MenuResult(BaseModel):
    """Result model for Gopher menu responses."""

    kind: Literal["menu"] = "menu"
    items: List[GopherMenuItem] = Field(..., description="List of menu items")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class TextResult(BaseModel):
    """Result model for Gopher text responses."""

    kind: Literal["text"] = "text"
    charset: str = Field(default="utf-8", description="Character encoding")
    bytes: int = Field(..., description="Size of content in bytes")
    text: str = Field(..., description="Text content")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class BinaryResult(BaseModel):
    """Result model for Gopher binary responses."""

    kind: Literal["binary"] = "binary"
    bytes: int = Field(..., description="Size of content in bytes")
    mime_type: Optional[str] = Field(
        None, alias="mimeType", description="Guessed MIME type"
    )
    note: str = Field(
        default="Binary content not returned to preserve context",
        description="Note about binary handling",
    )
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class ErrorResult(BaseModel):
    """Result model for error responses."""

    error: Dict[str, str] = Field(..., description="Error information")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


# Union type for all possible response types
GopherFetchResponse = Union[MenuResult, TextResult, BinaryResult, ErrorResult]


class GopherURL(BaseModel):
    """Model for parsed Gopher URLs."""

    host: str = Field(..., description="Hostname")
    port: int = Field(default=70, description="Port number")
    gopher_type: str = Field(
        default="1", alias="gopherType", description="Gopher item type"
    )
    selector: str = Field(default="", description="Selector string")
    search: Optional[str] = Field(None, description="Search string for type 7 items")

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("gopher_type")
    @classmethod
    def validate_gopher_type(cls, v: str) -> str:
        """Validate Gopher type is a single character."""
        if len(v) != 1:
            raise ValueError("Gopher type must be a single character")
        return v


class CacheEntry(BaseModel):
    """Model for cache entries."""

    key: str = Field(..., description="Cache key")
    value: GopherFetchResponse = Field(..., description="Cached response")
    timestamp: float = Field(..., description="Cache entry timestamp")
    ttl: int = Field(..., description="Time to live in seconds")

    def is_expired(self, current_time: float) -> bool:
        """Check if cache entry is expired."""
        return current_time - self.timestamp > self.ttl


# ============================================================================
# Gemini Protocol Models
# ============================================================================


class GeminiURL(BaseModel):
    """Model for parsed Gemini URLs.

    Based on gemini://<host>[:<port>][/<path>][?<query>] format.
    """

    host: str = Field(..., description="Hostname or IP address")
    port: int = Field(default=1965, description="Port number (default: 1965)")
    path: str = Field(default="/", description="Resource path")
    query: Optional[str] = Field(None, description="Query string for user input")

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate hostname is not empty."""
        if not v.strip():
            raise ValueError("Host cannot be empty")
        return v.strip()


class GeminiFetchRequest(BaseModel):
    """Request model for gemini_fetch tool."""

    url: str = Field(
        ...,
        description="Gemini URL to fetch (e.g., gemini://gemini.circumlunar.space/)",
        examples=[
            "gemini://gemini.circumlunar.space/",
            "gemini://gemini.circumlunar.space/docs/specification.gmi",
        ],
    )

    @field_validator("url")
    @classmethod
    def validate_gemini_url(cls, v: str) -> str:
        """Validate that the URL is a proper Gemini URL."""
        if not v.startswith("gemini://"):
            raise ValueError("URL must start with 'gemini://'")
        if len(v.encode("utf-8")) > 1024:
            raise ValueError("URL must not exceed 1024 bytes")
        return v


class GeminiStatusCode(IntEnum):
    """Gemini protocol status codes."""

    # Input expected (10-19)
    INPUT = 10
    SENSITIVE_INPUT = 11

    # Success (20-29)
    SUCCESS = 20

    # Redirection (30-39)
    TEMPORARY_REDIRECT = 30
    PERMANENT_REDIRECT = 31

    # Temporary failure (40-49)
    TEMPORARY_FAILURE = 40
    SERVER_UNAVAILABLE = 41
    CGI_ERROR = 42
    PROXY_ERROR = 43
    SLOW_DOWN = 44

    # Permanent failure (50-59)
    PERMANENT_FAILURE = 50
    NOT_FOUND = 51
    GONE = 52
    PROXY_REQUEST_REFUSED = 53
    BAD_REQUEST = 59

    # Client certificates (60-69)
    CERTIFICATE_REQUIRED = 60
    CERTIFICATE_NOT_AUTHORIZED = 61
    CERTIFICATE_NOT_VALID = 62


class GeminiMimeType(BaseModel):
    """Model for Gemini MIME type parsing."""

    type: str = Field(..., description="Main MIME type (e.g., 'text')")
    subtype: str = Field(..., description="MIME subtype (e.g., 'gemini')")
    charset: str = Field(default="utf-8", description="Character encoding")
    lang: Optional[str] = Field(None, description="Language tag (BCP47)")

    @property
    def full_type(self) -> str:
        """Get full MIME type string."""
        return f"{self.type}/{self.subtype}"

    @property
    def is_text(self) -> bool:
        """Check if this is a text MIME type."""
        return self.type == "text"

    @property
    def is_gemtext(self) -> bool:
        """Check if this is text/gemini."""
        return self.type == "text" and self.subtype == "gemini"

    @property
    def is_binary(self) -> bool:
        """Check if this is a binary MIME type."""
        return not self.is_text

    @property
    def is_image(self) -> bool:
        """Check if this is an image MIME type."""
        return self.type == "image"

    @property
    def is_audio(self) -> bool:
        """Check if this is an audio MIME type."""
        return self.type == "audio"

    @property
    def is_video(self) -> bool:
        """Check if this is a video MIME type."""
        return self.type == "video"

    @property
    def is_application(self) -> bool:
        """Check if this is an application MIME type."""
        return self.type == "application"

    def supports_charset(self) -> bool:
        """Check if this MIME type supports charset parameter."""
        return self.is_text

    def get_file_extension(self) -> str:
        """Get common file extension for this MIME type."""
        # Common MIME type to extension mappings
        extensions = {
            "text/gemini": ".gmi",
            "text/plain": ".txt",
            "text/html": ".html",
            "text/css": ".css",
            "text/javascript": ".js",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/wav": ".wav",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "application/pdf": ".pdf",
            "application/zip": ".zip",
            "application/json": ".json",
            "application/xml": ".xml",
        }
        return extensions.get(self.full_type, "")


class GeminiResponse(BaseModel):
    """Base model for Gemini protocol responses."""

    status: Union[GeminiStatusCode, int] = Field(..., description="Gemini status code")
    meta: str = Field(..., description="Status-dependent metadata")
    body: Optional[bytes] = Field(None, description="Response body (if any)")

    @field_validator("meta")
    @classmethod
    def validate_meta_length(cls, v: str) -> str:
        """Validate meta field length (reasonable limit)."""
        if len(v.encode("utf-8")) > 1024:
            raise ValueError("Meta field too long")
        return v


# Response result models following Gopher patterns
class GeminiSuccessResult(BaseModel):
    """Result model for successful Gemini responses."""

    kind: Literal["success"] = "success"
    mime_type: GeminiMimeType = Field(
        ..., alias="mimeType", description="Content MIME type"
    )
    content: Union[str, bytes] = Field(..., description="Response content")
    size: int = Field(..., description="Content size in bytes")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiInputResult(BaseModel):
    """Result model for input request responses (status 10/11)."""

    kind: Literal["input"] = "input"
    prompt: str = Field(..., description="Input prompt text")
    sensitive: bool = Field(default=False, description="Whether input is sensitive")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiRedirectResult(BaseModel):
    """Result model for redirect responses (status 30/31)."""

    kind: Literal["redirect"] = "redirect"
    new_url: str = Field(..., alias="newUrl", description="Redirect target URL")
    permanent: bool = Field(default=False, description="Whether redirect is permanent")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiErrorResult(BaseModel):
    """Result model for error responses."""

    kind: Literal["error"] = "error"
    error: Dict[str, Any] = Field(..., description="Error information")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiCertificateResult(BaseModel):
    """Result model for certificate request responses (status 60-62)."""

    kind: Literal["certificate"] = "certificate"
    message: str = Field(..., description="Certificate-related message")
    required: bool = Field(default=True, description="Whether certificate is required")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


# Gemtext content models
class GemtextLineType(str, Enum):
    """Types of lines in gemtext format."""

    TEXT = "text"
    LINK = "link"
    HEADING_1 = "heading1"
    HEADING_2 = "heading2"
    HEADING_3 = "heading3"
    LIST_ITEM = "list"
    QUOTE = "quote"
    PREFORMAT = "preformat"


class GemtextLink(BaseModel):
    """Model for gemtext link lines."""

    url: str = Field(..., description="Link URL (absolute or relative)")
    text: Optional[str] = Field(None, description="Link text (optional)")

    @field_validator("url")
    @classmethod
    def validate_url_not_empty(cls, v: str) -> str:
        """Validate URL is not empty."""
        if not v.strip():
            raise ValueError("Link URL cannot be empty")
        return v.strip()


class GemtextHeading(BaseModel):
    """Model for gemtext heading lines."""

    level: int = Field(..., description="Heading level (1-3)", ge=1, le=3)
    text: str = Field(..., description="Heading text content")
    raw_content: str = Field(..., description="Raw line content including # markers")


class GemtextList(BaseModel):
    """Model for gemtext list items."""

    text: str = Field(..., description="List item text content")
    raw_content: str = Field(..., description="Raw line content including * marker")


class GemtextQuote(BaseModel):
    """Model for gemtext quote lines."""

    text: str = Field(..., description="Quote text content")
    raw_content: str = Field(..., description="Raw line content including > marker")


class GemtextPreformat(BaseModel):
    """Model for gemtext preformat content."""

    content: str = Field(..., description="Preformat content")
    alt_text: Optional[str] = Field(None, description="Alt text for accessibility")
    is_toggle: bool = Field(
        default=False, description="Whether this is a toggle line (```)"
    )
    language: Optional[str] = Field(None, description="Detected programming language")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class GemtextLine(BaseModel):
    """Model for a single line in gemtext format."""

    type: GemtextLineType = Field(..., description="Type of gemtext line")
    content: str = Field(..., description="Line content")
    link: Optional[GemtextLink] = Field(None, description="Link data (for link lines)")
    level: Optional[int] = Field(None, description="Heading level (1-3, for headings)")
    alt_text: Optional[str] = Field(None, description="Alt text (for preformat blocks)")

    # Structured content for specific line types
    heading: Optional[GemtextHeading] = Field(
        None, description="Heading data (for heading lines)"
    )
    list_item: Optional[GemtextList] = Field(
        None, description="List data (for list lines)"
    )
    quote: Optional[GemtextQuote] = Field(
        None, description="Quote data (for quote lines)"
    )
    preformat: Optional[GemtextPreformat] = Field(
        None, description="Preformat data (for preformat lines)"
    )


class GemtextDocument(BaseModel):
    """Model for parsed gemtext document."""

    lines: List[GemtextLine] = Field(..., description="Document lines")
    links: List[GemtextLink] = Field(
        default_factory=list, description="Extracted links"
    )

    @property
    def link_count(self) -> int:
        """Get number of links in document."""
        return len(self.links)

    @property
    def has_headings(self) -> bool:
        """Check if document has any headings."""
        return any(line.type.startswith("heading") for line in self.lines)

    @property
    def line_count(self) -> int:
        """Get total number of lines in document."""
        return len(self.lines)

    @property
    def content_summary(self) -> Dict[str, int]:
        """Get summary of content types for LLM consumption."""
        summary = {
            "text_lines": 0,
            "headings": 0,
            "links": 0,
            "list_items": 0,
            "quotes": 0,
            "preformat_blocks": 0,
        }

        in_preformat = False
        for line in self.lines:
            if line.type == GemtextLineType.TEXT:
                summary["text_lines"] += 1
            elif line.type.startswith("heading"):
                summary["headings"] += 1
            elif line.type == GemtextLineType.LINK:
                summary["links"] += 1
            elif line.type == GemtextLineType.LIST_ITEM:
                summary["list_items"] += 1
            elif line.type == GemtextLineType.QUOTE:
                summary["quotes"] += 1
            elif line.type == GemtextLineType.PREFORMAT:
                if line.preformat and line.preformat.is_toggle:
                    if not in_preformat:
                        summary["preformat_blocks"] += 1
                        in_preformat = True
                    else:
                        in_preformat = False

        return summary

    @property
    def heading_hierarchy(self) -> List[Dict[str, Any]]:
        """Get document heading structure for navigation."""
        headings = []
        for i, line in enumerate(self.lines):
            if line.heading:
                headings.append(
                    {
                        "line_number": i + 1,
                        "level": line.heading.level,
                        "text": line.heading.text,
                        "raw_content": line.heading.raw_content,
                    }
                )
        return headings

    @property
    def text_content(self) -> str:
        """Get plain text content (excluding markup) for search/analysis."""
        text_parts = []
        for line in self.lines:
            if line.type == GemtextLineType.TEXT:
                text_parts.append(line.content)
            elif line.heading:
                text_parts.append(line.heading.text)
            elif line.list_item:
                text_parts.append(line.list_item.text)
            elif line.quote:
                text_parts.append(line.quote.text)
            elif (
                line.type == GemtextLineType.PREFORMAT
                and line.preformat
                and not line.preformat.is_toggle
            ):
                text_parts.append(line.content)
        return "\n".join(text_parts)


class GeminiGemtextResult(BaseModel):
    """Result model for gemtext content responses."""

    kind: Literal["gemtext"] = "gemtext"
    document: GemtextDocument = Field(..., description="Parsed gemtext document")
    raw_content: str = Field(..., alias="rawContent", description="Raw gemtext content")
    charset: str = Field(default="utf-8", description="Character encoding")
    lang: Optional[str] = Field(None, description="Language tag")
    size: int = Field(..., description="Content size in bytes")
    request_info: Dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )

    @property
    def summary(self) -> Dict[str, Any]:
        """Get LLM-optimized summary of the gemtext content."""
        return {
            "content_type": "gemtext",
            "line_count": self.document.line_count,
            "link_count": self.document.link_count,
            "has_headings": self.document.has_headings,
            "content_summary": self.document.content_summary,
            "heading_hierarchy": self.document.heading_hierarchy,
            "charset": self.charset,
            "language": self.lang,
            "size_bytes": self.size,
        }

    @property
    def plain_text(self) -> str:
        """Get plain text version for search and analysis."""
        return self.document.text_content

    @property
    def structured_content(self) -> Dict[str, Any]:
        """Get structured content optimized for LLM consumption."""
        return {
            "summary": self.summary,
            "headings": self.document.heading_hierarchy,
            "links": [
                {
                    "url": link.url,
                    "text": link.text,
                    "type": "internal" if link.url.startswith("/") else "external",
                }
                for link in self.document.links
            ],
            "content_blocks": [
                {
                    "line_number": i + 1,
                    "type": line.type,
                    "content": line.content,
                    "structured_data": {
                        "heading": {
                            "level": line.heading.level,
                            "text": line.heading.text,
                        }
                        if line.heading
                        else None,
                        "link": {
                            "url": line.link.url,
                            "text": line.link.text,
                        }
                        if line.link
                        else None,
                        "list_item": {
                            "text": line.list_item.text,
                        }
                        if line.list_item
                        else None,
                        "quote": {
                            "text": line.quote.text,
                        }
                        if line.quote
                        else None,
                        "preformat": {
                            "alt_text": line.preformat.alt_text,
                            "is_toggle": line.preformat.is_toggle,
                        }
                        if line.preformat
                        else None,
                    },
                }
                for i, line in enumerate(self.document.lines)
            ],
            "plain_text": self.plain_text,
        }


# Union type for all possible Gemini fetch responses
GeminiFetchResponse = Union[
    GeminiSuccessResult,
    GeminiGemtextResult,
    GeminiInputResult,
    GeminiRedirectResult,
    GeminiErrorResult,
    GeminiCertificateResult,
]


# Certificate and security models
class GeminiCertificateInfo(BaseModel):
    """Model for client certificate information."""

    fingerprint: str = Field(..., description="Certificate SHA-256 fingerprint")
    subject: str = Field(..., description="Certificate subject")
    issuer: str = Field(..., description="Certificate issuer")
    not_before: str = Field(..., description="Certificate validity start")
    not_after: str = Field(..., description="Certificate validity end")
    host: str = Field(..., description="Associated hostname")
    port: int = Field(default=1965, description="Associated port")
    path: str = Field(default="/", description="Associated path scope")


class TOFUEntry(BaseModel):
    """Model for Trust-on-First-Use certificate storage."""

    host: str = Field(..., description="Hostname")
    port: int = Field(default=1965, description="Port number")
    fingerprint: str = Field(..., description="Certificate SHA-256 fingerprint")
    first_seen: float = Field(..., description="Timestamp of first connection")
    last_seen: float = Field(..., description="Timestamp of last connection")
    expires: Optional[float] = Field(None, description="Certificate expiry timestamp")

    def is_expired(self, current_time: float) -> bool:
        """Check if certificate is expired."""
        return self.expires is not None and current_time > self.expires


class GeminiCacheEntry(BaseModel):
    """Model for Gemini cache entries."""

    key: str = Field(..., description="Cache key")
    value: GeminiFetchResponse = Field(..., description="Cached response")
    timestamp: float = Field(..., description="Cache entry timestamp")
    ttl: int = Field(..., description="Time to live in seconds")

    def is_expired(self, current_time: float) -> bool:
        """Check if cache entry is expired."""
        return current_time - self.timestamp > self.ttl
