"""Centralized configuration management using Pydantic Settings."""

import contextlib
import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GopherConfig(BaseSettings):
    """Configuration for Gopher protocol client."""

    max_response_size: int = Field(
        default=1048576,  # 1MB
        description="Maximum response size in bytes",
        ge=1024,  # At least 1KB
        le=104857600,  # At most 100MB
    )
    timeout_seconds: float = Field(
        default=30.0,
        description="Request timeout in seconds",
        gt=0,
        le=300,  # Max 5 minutes
    )
    cache_enabled: bool = Field(
        default=True,
        description="Whether to enable response caching",
    )
    cache_ttl_seconds: int = Field(
        default=300,  # 5 minutes
        description="Cache time-to-live in seconds",
        ge=0,
        le=86400,  # at most one day
    )
    max_cache_entries: int = Field(
        default=1000,
        description="Maximum number of cache entries",
        ge=1,  # 0 would break LRU eviction (popitem on an empty cache)
        le=100000,
    )
    allowed_hosts: list[str] | None = Field(
        default=None,
        description="List of allowed hostnames (None = allow all)",
    )
    allow_local_hosts: bool = Field(
        default=False,
        description="Allow connections to loopback/private/internal addresses "
        "(disabled by default to prevent SSRF)",
    )
    max_selector_length: int = Field(
        default=1024,
        description="Maximum selector string length",
        ge=1,
        le=65536,
    )
    max_search_length: int = Field(
        default=256,
        description="Maximum search query length",
        ge=1,
        le=4096,
    )
    max_rendered_chars: int = Field(
        default=50000,
        description="LLM-facing cap on returned text characters (distinct from "
        "the network byte cap); 0 = unlimited. Truncation is flagged on the "
        "result.",
        ge=0,
        le=10485760,
    )
    requests_per_minute: float = Field(
        default=0.0,
        description="Per-host outbound request rate cap (politeness for small "
        "Gopher servers); 0 = unlimited.",
        ge=0,
        le=6000,
    )

    model_config = SettingsConfigDict(
        env_prefix="GOPHER_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: str | None) -> list[str] | None:
        """Parse comma-separated allowed hosts from environment variable."""
        if v is None or v == "":
            return None
        if isinstance(v, list):  # type: ignore[unreachable]
            return v  # type: ignore[unreachable]
        return [host.strip() for host in v.split(",") if host.strip()]


class GeminiConfig(BaseSettings):
    """Configuration for Gemini protocol client."""

    max_response_size: int = Field(
        default=1048576,  # 1MB
        description="Maximum response size in bytes",
        ge=1024,
        le=104857600,
    )
    timeout_seconds: float = Field(
        default=30.0,
        description="Request timeout in seconds",
        gt=0,
        le=300,
    )
    cache_enabled: bool = Field(
        default=True,
        description="Whether to enable response caching",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        description="Cache time-to-live in seconds",
        ge=0,
        le=86400,  # at most one day
    )
    max_cache_entries: int = Field(
        default=1000,
        description="Maximum number of cache entries",
        ge=1,  # 0 would break LRU eviction (popitem on an empty cache)
        le=100000,
    )
    allowed_hosts: list[str] | None = Field(
        default=None,
        description="List of allowed hostnames (None = allow all)",
    )
    allow_local_hosts: bool = Field(
        default=False,
        description="Allow connections to loopback/private/internal addresses "
        "(disabled by default to prevent SSRF)",
    )
    tofu_enabled: bool = Field(
        default=True,
        description="Enable TOFU (Trust-on-First-Use) certificate validation",
    )
    tofu_storage_path: Path | None = Field(
        default=None,
        description="TOFU storage file path",
    )
    client_certs_enabled: bool = Field(
        default=True,
        description="Enable client certificate support",
    )
    client_certs_storage_path: Path | None = Field(
        default=None,
        description="Client certificates storage directory path",
    )
    max_rendered_chars: int = Field(
        default=50000,
        description="LLM-facing cap on returned text characters (distinct from "
        "the network byte cap); 0 = unlimited. Truncation is flagged on the "
        "result.",
        ge=0,
        le=10485760,
    )
    requests_per_minute: float = Field(
        default=0.0,
        description="Per-host outbound request rate cap (politeness for small "
        "Gemini servers); 0 = unlimited. A status-44 SLOW_DOWN is always "
        "honoured regardless of this setting.",
        ge=0,
        le=6000,
    )
    denied_mime_types: list[str] = Field(
        default_factory=list,
        description="MIME types (or `type/*` wildcards) to reject as filtered "
        "content, e.g. 'text/html,image/*'; empty = no content filtering.",
    )

    model_config = SettingsConfigDict(
        env_prefix="GEMINI_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: None | str | list[str]) -> list[str] | None:
        """Parse comma-separated allowed hosts from environment variable."""
        if v is None or v == "":
            return None
        if isinstance(v, list):
            return v
        return [host.strip() for host in v.split(",") if host.strip()]

    @field_validator("denied_mime_types", mode="before")
    @classmethod
    def parse_denied_mime_types(cls, v: None | str | list[str]) -> list[str]:
        """Parse a comma-separated MIME deny list from an environment variable."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        return [m.strip().lower() for m in v.split(",") if m.strip()]


class ServerConfig(BaseSettings):
    """Configuration for the MCP server."""

    log_level: str = Field(
        default="INFO",
        description="Log level",
    )
    structured_logging: bool = Field(
        default=True,
        description="Enable structured logging",
    )
    log_file_path: Path | None = Field(
        default=None,
        description="Log file path (optional, logs to stdout if not set)",
    )
    development_mode: bool = Field(
        default=False,
        description="Enable development mode",
    )

    model_config = SettingsConfigDict(
        # Namespace server settings so common ambient vars (LOG_LEVEL,
        # DEVELOPMENT_MODE, ...) set by other tooling don't silently bleed in.
        env_prefix="GOPHER_MCP_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v_upper


class AppConfig(BaseSettings):
    """Main application configuration combining all sub-configs."""

    gopher: GopherConfig = Field(default_factory=GopherConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global configuration instance
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def reset_config() -> None:
    """Reset the global configuration instance (useful for testing)."""
    global _config
    _config = None


class _TeeStream:
    """Write-only text stream that fans each write out to several streams.

    structlog's PrintLogger writes every rendered line to a single file
    object; teeing stderr and a log file lets the configured file receive the
    same records without a second open handle or a stdlib logging bridge.
    """

    def __init__(self, *streams: Any) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


_log_file_handle: Any = None


def configure_logging(config: ServerConfig | None = None) -> None:
    """Configure structlog/stdlib logging from the server configuration.

    Logs are written to STDERR, never stdout: the stdio MCP transport uses
    stdout for the protocol stream, so logging there would corrupt it. When
    ``log_file_path`` is set, the same records are mirrored to that file.
    """
    global _log_file_handle

    config = config or ServerConfig()
    level = getattr(logging, config.log_level.upper(), logging.INFO)

    # Close any handle opened by a previous call so reconfiguring doesn't leak
    # file descriptors.
    if _log_file_handle is not None:
        with contextlib.suppress(Exception):
            _log_file_handle.close()
        _log_file_handle = None

    # Every module logs through structlog, whose PrintLogger writes to one
    # stream. A stdlib FileHandler would therefore never see those records, so
    # mirror to the file by teeing stderr + the file and pointing both stdlib
    # logging and structlog at that single stream.
    log_stream: Any = sys.stderr
    if config.log_file_path:
        # Long-lived handle: logging writes through it for the process lifetime,
        # so it can't use a closing context manager. It's tracked module-wide
        # and closed on the next reconfigure (above).
        log_file = Path(config.log_file_path).open("a", encoding="utf-8")  # noqa: SIM115
        _log_file_handle = log_file
        log_stream = _TeeStream(sys.stderr, log_file)

    logging.basicConfig(
        level=level,
        handlers=[logging.StreamHandler(log_stream)],
        format="%(message)s",
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if config.structured_logging:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=log_stream),
        cache_logger_on_first_use=True,
    )
