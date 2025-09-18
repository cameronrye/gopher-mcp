"""
Gemini Protocol Data Models Design
==================================

This file contains the design for Gemini-specific Pydantic models that will be
integrated into the existing models.py file. These models follow the established
patterns from the Gopher implementation while accommodating Gemini-specific features.

Based on Gemini Protocol Specification v0.24.1
"""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator
from enum import IntEnum, Enum


# ============================================================================
# Core URL and Request Models
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


# ============================================================================
# Status Code Models
# ============================================================================


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


class GeminiResponse(BaseModel):
    """Base model for Gemini protocol responses."""

    status: GeminiStatusCode = Field(..., description="Gemini status code")
    meta: str = Field(..., description="Status-dependent metadata")
    body: Optional[bytes] = Field(None, description="Response body (if any)")

    @field_validator("meta")
    @classmethod
    def validate_meta_length(cls, v: str) -> str:
        """Validate meta field length (reasonable limit)."""
        if len(v.encode("utf-8")) > 1024:
            raise ValueError("Meta field too long")
        return v


# ============================================================================
# Content Type Models
# ============================================================================


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


# ============================================================================
# Gemtext Content Models
# ============================================================================


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


class GemtextLine(BaseModel):
    """Model for a single line in gemtext format."""

    type: GemtextLineType = Field(..., description="Type of gemtext line")
    content: str = Field(..., description="Line content")
    link: Optional[GemtextLink] = Field(None, description="Link data (for link lines)")
    level: Optional[int] = Field(None, description="Heading level (1-3, for headings)")
    alt_text: Optional[str] = Field(None, description="Alt text (for preformat blocks)")


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


# ============================================================================
# Response Result Models (following Gopher patterns)
# ============================================================================


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


# Union type for all possible Gemini fetch responses
GeminiFetchResponse = Union[
    GeminiSuccessResult,
    GeminiGemtextResult,
    GeminiInputResult,
    GeminiRedirectResult,
    GeminiErrorResult,
    GeminiCertificateResult,
]


# ============================================================================
# Certificate and Security Models
# ============================================================================


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


# ============================================================================
# Cache Models (extending existing patterns)
# ============================================================================


class GeminiCacheEntry(BaseModel):
    """Model for Gemini cache entries."""

    key: str = Field(..., description="Cache key")
    value: GeminiFetchResponse = Field(..., description="Cached response")
    timestamp: float = Field(..., description="Cache entry timestamp")
    ttl: int = Field(..., description="Time to live in seconds")

    def is_expired(self, current_time: float) -> bool:
        """Check if cache entry is expired."""
        return current_time - self.timestamp > self.ttl
