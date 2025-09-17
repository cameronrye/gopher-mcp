"""Pydantic models for Gopher MCP data validation."""

from typing import Any, Dict, List, Literal, Optional, Union

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
