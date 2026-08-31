"""Pydantic models for Gopher MCP data validation."""

import time
from enum import Enum, IntEnum
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_serializer,
)

# Cache provenance. Only the result kinds the clients actually cache carry these
# fields -- Gopher menus/text/binaries and the Gemini success/gemtext bodies. An
# error, redirect, input prompt or certificate prompt is never cached, so adding
# three permanently-null keys to it would be noise. The descriptions are the
# whole point of the feature: they are what the model reads when it has to
# decide whether a response is fresh enough to answer with.
_CachedFlag = Annotated[
    bool,
    Field(
        description=(
            "True when this result was replayed from the local response cache "
            "instead of being fetched from the server during this call. Treat "
            "the content as a snapshot taken at `cached_at`, not as the "
            "current state of the resource."
        )
    ),
]
_CachedAt = Annotated[
    float | None,
    Field(
        description=(
            "UNIX timestamp (seconds) at which the cached copy was actually "
            "fetched from the server. Null when `cached` is false."
        )
    ),
]
_CacheAgeSeconds = Annotated[
    float | None,
    Field(
        description=(
            "How old the cached copy was, in seconds, when this result was "
            "returned. If the user is asking about something that may have "
            "changed since then, fetch again with `refresh=true`. Null when "
            "`cached` is false."
        )
    ),
]

_ResultT = TypeVar("_ResultT", bound=BaseModel)


def mark_from_cache(response: _ResultT, cached_at: float) -> _ResultT:
    """Return a copy of ``response`` tagged as served from the cache.

    A copy, never the stored object: the cache hands back the very instance it
    holds, so tagging in place would also mark the entry itself -- and with it
    the response already returned by the fetch that populated the entry.

    Args:
        response: The cached result to tag.
        cached_at: When the cached copy was fetched from the server.

    Returns:
        A copy of ``response`` carrying the cache-provenance fields.

    """
    return response.model_copy(
        update={
            "cached": True,
            "cached_at": cached_at,
            "cache_age_seconds": round(time.time() - cached_at, 1),
        }
    )


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
        if len(v.encode("utf-8")) > 8192:
            raise ValueError("URL must not exceed 8192 bytes")
        return v


class GopherMenuItem(BaseModel):
    """Model for a single Gopher menu item."""

    type: str = Field(..., description="Gopher item type (single character)")
    title: str = Field(..., description="Human-readable item title")
    selector: str = Field(..., description="Selector string for this item")
    host: str = Field(..., description="Hostname where item resides")
    # Info ('i') lines conventionally carry port 0, so 0 is permitted here.
    port: int = Field(..., ge=0, le=65535, description="Port number (typically 70)")
    next_url: str = Field(
        ..., alias="nextUrl", description="Fully formed gopher:// URL for this item"
    )


class MenuResult(BaseModel):
    """Result model for Gopher menu responses."""

    kind: Literal["menu"] = "menu"
    items: list[GopherMenuItem] = Field(..., description="List of menu items")
    truncated: bool = Field(
        default=False,
        description="True if the menu had more items than the render limit and "
        "`items` was truncated",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class TextResult(BaseModel):
    """Result model for Gopher text responses."""

    kind: Literal["text"] = "text"
    charset: str = Field(default="utf-8", description="Character encoding")
    bytes: int = Field(..., ge=0, description="Size of content in bytes")
    text: str = Field(..., description="Text content")
    truncated: bool = Field(
        default=False,
        description="True if `text` was truncated to the render limit (`bytes` "
        "still reports the full original size)",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class BinaryResult(BaseModel):
    """Result model for Gopher binary responses."""

    kind: Literal["binary"] = "binary"
    bytes: int = Field(..., ge=0, description="Size of content in bytes")
    mime_type: str | None = Field(
        None, alias="mimeType", description="Guessed MIME type"
    )
    note: str = Field(
        default="Binary content not returned to preserve context",
        description="Note about binary handling",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class ErrorResult(BaseModel):
    """Result model for error responses, shared by both protocols.

    ``error`` is deliberately ``dict[str, Any]``: a Gemini failure carries the
    numeric ``status`` (and the boolean ``temporary``) beside the message, and a
    Gopher-only ``dict[str, str]`` twin meant that annotation was the only thing
    keeping those fields out of a Gopher error.
    """

    # 'kind' makes the result self-describing and a reliable discriminator
    # across every result type.
    kind: Literal["error"] = "error"
    error: dict[str, Any] = Field(..., description="Error information")
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


# Union type for all possible response types
GopherFetchResponse = MenuResult | TextResult | BinaryResult | ErrorResult

_CacheValueT = TypeVar("_CacheValueT")


class _BaseCacheEntry(BaseModel, Generic[_CacheValueT]):
    """Shared base for protocol cache entries (TTL-based expiry)."""

    key: str = Field(..., description="Cache key")
    value: _CacheValueT = Field(..., description="Cached response")
    timestamp: float = Field(..., description="Cache entry timestamp")
    ttl: int = Field(..., description="Time to live in seconds")

    def is_expired(self, current_time: float) -> bool:
        """Check if cache entry is expired."""
        return current_time - self.timestamp > self.ttl


class GopherURL(BaseModel):
    """Model for parsed Gopher URLs."""

    host: str = Field(..., description="Hostname")
    port: int = Field(default=70, description="Port number")
    gopher_type: str = Field(
        default="1", alias="gopherType", description="Gopher item type"
    )
    selector: str = Field(default="", description="Selector string")
    search: str | None = Field(None, description="Search string for type 7 items")

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

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate hostname is not empty (mirrors GeminiURL)."""
        if not v.strip():
            raise ValueError("Host cannot be empty")
        return v.strip()


class CacheEntry(_BaseCacheEntry[GopherFetchResponse]):
    """Model for Gopher cache entries."""


# ============================================================================
# Gemini Protocol Models
# ============================================================================


class GeminiURL(BaseModel):
    """Model for parsed Gemini URLs.

    Based on the ``gemini://<host>[:<port>][/<path>][?<query>]`` format.
    """

    host: str = Field(..., description="Hostname or IP address")
    port: int = Field(default=1965, description="Port number (default: 1965)")
    path: str = Field(default="/", description="Resource path")
    query: str | None = Field(None, description="Query string for user input")

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

    # Input expected: status codes 10 through 19
    INPUT = 10
    SENSITIVE_INPUT = 11

    # Success: status codes 20 through 29
    SUCCESS = 20

    # Redirection: status codes 30 through 39
    TEMPORARY_REDIRECT = 30
    PERMANENT_REDIRECT = 31

    # Temporary failure: status codes 40 through 49
    TEMPORARY_FAILURE = 40
    SERVER_UNAVAILABLE = 41
    CGI_ERROR = 42
    PROXY_ERROR = 43
    SLOW_DOWN = 44

    # Permanent failure: status codes 50 through 59
    PERMANENT_FAILURE = 50
    NOT_FOUND = 51
    GONE = 52
    PROXY_REQUEST_REFUSED = 53
    BAD_REQUEST = 59

    # Client certificates: status codes 60 through 69
    CERTIFICATE_REQUIRED = 60
    CERTIFICATE_NOT_AUTHORIZED = 61
    CERTIFICATE_NOT_VALID = 62


class GeminiMimeType(BaseModel):
    """Model for Gemini MIME type parsing."""

    type: str = Field(..., description="Main MIME type (e.g., 'text')")
    subtype: str = Field(..., description="MIME subtype (e.g., 'gemini')")
    charset: str = Field(default="utf-8", description="Character encoding")
    lang: str | None = Field(None, description="Language tag (BCP47)")

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


class GeminiResponse(BaseModel):
    """Base model for Gemini protocol responses."""

    status: GeminiStatusCode | int = Field(..., description="Gemini status code")
    meta: str = Field(..., description="Status-dependent metadata")
    body: bytes | None = Field(None, description="Response body (if any)")

    @field_validator("meta")
    @classmethod
    def validate_meta_length(cls, v: str) -> str:
        """Validate meta field length (reasonable limit)."""
        if len(v.encode("utf-8")) > 1024:
            raise ValueError("Meta field too long")
        return v


# Response result models following Gopher patterns
class GeminiSuccessResult(BaseModel):
    """Result model for a successful Gemini response carrying TEXT content.

    Binary success responses use :class:`GeminiBinaryResult` (metadata only), so
    ``content`` is always decoded text here.
    """

    kind: Literal["success"] = "success"
    mime_type: GeminiMimeType = Field(
        ..., alias="mimeType", description="Content MIME type"
    )
    content: str = Field(..., description="Decoded text response content")
    size: int = Field(..., ge=0, description="Content size in bytes")
    truncated: bool = Field(
        default=False,
        description="True if `content` was truncated to the render limit "
        "(`size` still reports the full original size).",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None

    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiBinaryResult(BaseModel):
    """Result model for a successful BINARY Gemini response (metadata only).

    Mirrors the Gopher :class:`BinaryResult`: the raw bytes are NOT returned to
    the model. A 1 MB body is ~1.4M base64 characters (~350k tokens), so
    inlining it would flood the context for content the model can't render
    anyway. The consumer gets the size and detected MIME type and can fetch the
    resource directly if it genuinely needs the bytes.
    """

    kind: Literal["binary"] = "binary"
    mime_type: GeminiMimeType = Field(
        ..., alias="mimeType", description="Detected content MIME type"
    )
    size: int = Field(..., ge=0, description="Content size in bytes")
    note: str = Field(
        default="Binary content not returned to preserve context",
        description="Note about binary handling",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiInputResult(BaseModel):
    """Result model for input request responses (status 10/11)."""

    kind: Literal["input"] = "input"
    prompt: str = Field(..., description="Input prompt text")
    sensitive: bool = Field(default=False, description="Whether input is sensitive")
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiRedirectResult(BaseModel):
    """Result model for redirect responses (status 30/31)."""

    kind: Literal["redirect"] = "redirect"
    new_url: str = Field(..., alias="newUrl", description="Redirect target URL")
    permanent: bool = Field(default=False, description="Whether redirect is permanent")
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


# The Gemini error result IS :class:`ErrorResult`; the alias keeps the
# protocol-suffixed spelling used by the Gemini modules and their tests.
GeminiErrorResult = ErrorResult


class GeminiCertificateResult(BaseModel):
    """Result model for certificate request responses (status 60-62)."""

    kind: Literal["certificate"] = "certificate"
    message: str = Field(..., description="Certificate-related message")
    status: int = Field(
        default=60,
        ge=60,
        le=69,
        description="Gemini certificate status code: 60 required, 61 not "
        "authorized, 62 not valid",
    )
    required: bool = Field(
        default=True,
        description="Whether the server is prompting for a certificate (status "
        "60). False for 61/62, which are rejections of a presented identity.",
    )
    request_info: dict[str, Any] = Field(
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

    url: str = Field(
        ...,
        description=(
            "Link URL, resolved against the request URL when the document was "
            "fetched, so links returned by a fetch are absolute"
        ),
    )
    text: str | None = Field(None, description="Link text (optional)")

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
    alt_text: str | None = Field(None, description="Alt text for accessibility")
    is_toggle: bool = Field(
        default=False, description="Whether this is a toggle line (```)"
    )
    language: str | None = Field(None, description="Detected programming language")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        """Drop null/empty fields on serialization.

        Block-level metadata (alt_text/language/metadata) is populated only on
        the opening toggle line; a content line then serializes to just its
        ``content`` and ``is_toggle`` instead of repeating empty alt_text,
        language and an empty metadata dict on every line. Attribute access is
        unaffected; only the serialized dict is trimmed.
        """
        data: dict[str, Any] = handler(self)
        return {k: v for k, v in data.items() if v is not None and v != {}}


class GemtextLine(BaseModel):
    """Model for a single line in gemtext format."""

    type: GemtextLineType = Field(..., description="Type of gemtext line")
    content: str = Field(..., description="Line content")
    link: GemtextLink | None = Field(None, description="Link data (for link lines)")
    level: int | None = Field(None, description="Heading level (1-3, for headings)")
    alt_text: str | None = Field(None, description="Alt text (for preformat blocks)")

    # Structured content for specific line types
    heading: GemtextHeading | None = Field(
        None, description="Heading data (for heading lines)"
    )
    list_item: GemtextList | None = Field(
        None, description="List data (for list lines)"
    )
    quote: GemtextQuote | None = Field(None, description="Quote data (for quote lines)")
    preformat: GemtextPreformat | None = Field(
        None, description="Preformat data (for preformat lines)"
    )

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        """Drop the always-null per-line fields on serialization.

        Every line only populates the one structured field matching its type, so
        the other six (link/level/alt_text/heading/list_item/quote/preformat)
        were emitted as ``null`` on every line -- pure token bloat for the LLM.
        Attribute access is unaffected; only the serialized dict is trimmed.
        """
        data: dict[str, Any] = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class GemtextDocument(BaseModel):
    """Model for parsed gemtext document."""

    lines: list[GemtextLine] = Field(..., description="Document lines")
    links: list[GemtextLink] = Field(
        default_factory=list, description="Extracted links"
    )


class GeminiGemtextResult(BaseModel):
    """Result model for gemtext content responses."""

    kind: Literal["gemtext"] = "gemtext"
    document: GemtextDocument = Field(..., description="Parsed gemtext document")
    raw_content: str = Field(..., alias="rawContent", description="Raw gemtext content")
    charset: str = Field(default="utf-8", description="Character encoding")
    lang: str | None = Field(None, description="Language tag")
    size: int = Field(..., description="Content size in bytes")
    truncated: bool = Field(
        default=False,
        description="True if the gemtext was truncated to the render limit "
        "(`size` still reports the full original byte size)",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


# Union type for all possible Gemini fetch responses
GeminiFetchResponse = (
    GeminiSuccessResult
    | GeminiBinaryResult
    | GeminiGemtextResult
    | GeminiInputResult
    | GeminiRedirectResult
    | GeminiErrorResult
    | GeminiCertificateResult
)


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
    expires: float | None = Field(None, description="Certificate expiry timestamp")

    def is_expired(self, current_time: float) -> bool:
        """Check if certificate is expired."""
        return self.expires is not None and current_time > self.expires


class TOFUTrustListResult(BaseModel):
    """Result model for a read-only inspection of the TOFU trust store.

    Only the entries the caller asked about are returned. The store's own
    filesystem path is deliberately absent: it is operator configuration that
    belongs in the server log, not in a payload handed to a model.
    """

    kind: Literal["trust_list"] = "trust_list"
    entries: list[TOFUEntry] = Field(
        ...,
        description="Pinned certificates matching the request, ordered by host",
    )
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class TOFUTrustUpdateResult(BaseModel):
    """Result model for a change to the TOFU trust store.

    Reports only the host the caller named, so a modification can never become
    a way to enumerate the rest of the store.
    """

    kind: Literal["trust_update"] = "trust_update"
    action: Literal["remove", "pin"] = Field(
        ..., description="The change that was requested"
    )
    host: str = Field(..., description="Host whose pin was targeted")
    port: int = Field(..., ge=1, le=65535, description="Port whose pin was targeted")
    changed: bool = Field(
        ...,
        description="True if the trust store was actually modified. False means "
        "there was nothing to change (e.g. the host had no pin to remove)",
    )
    message: str = Field(..., description="Human-readable summary of the outcome")
    request_info: dict[str, Any] = Field(
        default_factory=dict,
        alias="requestInfo",
        description="Information about the original request",
    )


class GeminiCacheEntry(_BaseCacheEntry[GeminiFetchResponse]):
    """Model for Gemini cache entries."""
