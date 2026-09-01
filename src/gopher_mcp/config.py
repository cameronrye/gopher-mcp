"""Centralized configuration management using Pydantic Settings."""

import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Any, Self

import structlog
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# List fields are annotated ``NoDecode`` so pydantic-settings hands the raw
# environment string to the validators below instead of JSON-decoding it first
# (a non-union complex type such as ``list[str]`` otherwise fails startup with a
# SettingsError on the documented comma-separated form). That also disables JSON
# list input, so the helpers accept both spellings.


def _blank_path_is_unset(v: object) -> object:
    """Treat an empty environment value for an optional path as "not set".

    ``FOO_PATH=`` is the natural way to spell "leave this at the default" in an
    env file, but pydantic coerces the empty string to ``Path(".")`` -- a
    directory, which then fails at use (opening it as a log file raises
    IsADirectoryError at startup) rather than at parse time.
    """
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _split_list_value(value: str) -> list[str]:
    """Split a raw environment value into entries.

    Args:
        value: Either a JSON array (``["a", "b"]``) or the documented
            comma-separated form (``a,b``).

    Returns:
        The non-empty, whitespace-stripped entries.

    Raises:
        ValueError: If the value opens like a JSON array but is not one.
    """
    stripped = value.strip()
    if stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON list: {value!r}") from exc
        return [str(item).strip() for item in decoded if str(item).strip()]
    return [entry.strip() for entry in stripped.split(",") if entry.strip()]


def _parse_host_allowlist(v: None | str | list[str], env_var: str) -> list[str] | None:
    """Parse a host allowlist from an environment variable.

    Args:
        v: Raw value: unset, an empty string, a JSON array, a comma-separated
            list, or an already-built list.
        env_var: Name of the environment variable, used in error messages.

    Returns:
        The parsed hosts, or None when no allowlist is configured.

    Raises:
        ValueError: If a non-empty value yields no hosts. Downstream an empty
            allowlist is indistinguishable from "unset" and would silently drop
            the restriction, so fail closed at startup instead.
    """
    if v is None or v == "":
        return None
    if isinstance(v, list):
        return v
    hosts = _split_list_value(v)
    if not hosts:
        raise ValueError(
            f"{env_var} is set to {v!r} but names no hosts; unset it to allow "
            "all hosts."
        )
    return hosts


def _parse_port_allowlist(v: None | str | list[int], env_var: str) -> list[int] | None:
    """Parse a port allowlist from an environment variable.

    Args:
        v: Raw value: unset, an empty string, a JSON array, a comma-separated
            list, or an already-built list.
        env_var: Name of the environment variable, used in error messages.

    Returns:
        The parsed ports, or None when no allowlist is configured.

    Raises:
        ValueError: If a non-empty value yields no ports, or any port falls
            outside 1-65535 and so could never match a request.
    """
    if v is None or v == "":
        return None
    ports = [int(p) for p in v] if isinstance(v, list) else _parse_ports(v, env_var)
    for port in ports:
        if not 1 <= port <= 65535:
            raise ValueError(f"{env_var} port must be between 1 and 65535: {port}")
    return ports


def _parse_ports(v: str, env_var: str) -> list[int]:
    """Parse the entries of a port allowlist string.

    Args:
        v: A JSON array or comma-separated port list.
        env_var: Name of the environment variable, used in error messages.

    Returns:
        The parsed ports.

    Raises:
        ValueError: If the value names no ports.
    """
    ports = [int(entry) for entry in _split_list_value(v)]
    if not ports:
        raise ValueError(
            f"{env_var} is set to {v!r} but names no ports; unset it to allow "
            "any non-dangerous port."
        )
    return ports


class _ProtocolConfig(BaseSettings):
    """Settings every protocol client shares.

    The two protocol configs declared the same fourteen fields -- same defaults,
    bounds and (mostly) descriptions -- plus byte-identical allowlist
    validators, so a corrected bound or a fixed parse had to be applied twice.
    They live here once; a subclass supplies its ``env_prefix``, its own fields,
    and a replacement Field only where the *description* is protocol-specific.
    """

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
        description="Cache time-to-live in seconds; 0 disables caching (every "
        "entry would expire the instant it is stored).",
        ge=0,
        le=86400,  # at most one day
    )
    max_cache_entries: int = Field(
        default=1000,
        description="Maximum number of cache entries",
        ge=1,  # 0 would break LRU eviction (popitem on an empty cache)
        le=100000,
    )
    allowed_hosts: Annotated[list[str] | None, NoDecode] = Field(
        default=None,
        description="List of allowed hostnames, comma-separated (None = allow "
        "all). An explicitly empty list is rejected rather than read as "
        "allow-all.",
    )
    allow_local_hosts: bool = Field(
        default=False,
        description="Allow connections to loopback/private/internal addresses "
        "(disabled by default to prevent SSRF)",
    )
    max_rendered_chars: int = Field(
        default=50000,
        description="LLM-facing cap on returned text characters (distinct from "
        "the network byte cap); 0 = unlimited. Truncation is flagged on the "
        "result.",
        ge=0,
        le=10485760,
    )
    max_concurrent_requests: int = Field(
        default=5,  # matches the batch tools' own concurrency
        description="Cap on simultaneous in-flight fetches (0 = unlimited); a "
        "coarse bound on concurrent sockets/memory, complementary to the "
        "per-host rate limit. Defaults to the batch tools' own concurrency so "
        "parallel tool calls cannot multiply past it.",
        ge=0,
        le=1000,
    )
    robots_cache_ttl_seconds: int = Field(
        default=86400,  # 24 hours; RFC 9309 s2.4 permits up to this
        description="How long a fetched robots.txt policy stays valid, in "
        "seconds. RFC 9309 s2.4 permits up to 24 hours.",
        ge=0,
        le=604800,  # at most one week
    )

    model_config = SettingsConfigDict(
        # env_prefix is supplied per protocol; the rest is shared.
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def _env_var(cls, field_name: str) -> str:
        """Name the environment variable a field is read from, for messages."""
        return f"{cls.model_config.get('env_prefix', '')}{field_name}".upper()

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: None | str | list[str]) -> list[str] | None:
        """Parse comma-separated allowed hosts from environment variable."""
        return _parse_host_allowlist(v, cls._env_var("allowed_hosts"))

    # ``allowed_ports`` is declared per protocol (only its documented example
    # port differs), so the field is absent from this class at decoration time.
    @field_validator("allowed_ports", mode="before", check_fields=False)
    @classmethod
    def parse_allowed_ports(cls, v: None | str | list[int]) -> list[int] | None:
        """Parse a comma-separated port allowlist from an environment variable."""
        return _parse_port_allowlist(v, cls._env_var("allowed_ports"))

    @model_validator(mode="after")
    def disable_cache_without_ttl(self) -> Self:
        """Treat a zero TTL as caching disabled rather than a no-hit cache."""
        if self.cache_ttl_seconds == 0:
            self.cache_enabled = False
        return self


class GopherConfig(_ProtocolConfig):
    """Configuration for Gopher protocol client."""

    allowed_ports: Annotated[list[int] | None, NoDecode] = Field(
        default=None,
        description="Optional positive port allowlist (comma-separated, e.g. "
        "70). When set, only these ports may be connected to, closing the "
        "arbitrary-port port-scanning gap. None = any non-dangerous port.",
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
    max_menu_items: int = Field(
        default=1000,
        description="LLM-facing cap on the number of Gopher menu items returned "
        "(a 1 MB directory can expand to tens of thousands of items); 0 = "
        "unlimited. Truncation is flagged on the result.",
        ge=0,
        le=1000000,
    )
    requests_per_minute: float = Field(
        default=60.0,  # one request per second, per host
        description="Per-host outbound request rate cap (politeness for small "
        "Gopher servers); 0 = unlimited. Defaults to one request per second "
        "per host, which is imperceptible when browsing but stops a model "
        "looping over the fetch tools from hammering one hobbyist server.",
        ge=0,
        le=6000,
    )
    respect_robots_txt: bool = Field(
        default=False,
        description="Fetch and honour /robots.txt from the host root before "
        "retrieving a resource, following the convention Veronica-2 documents "
        "(User-agent 'gopher-mcp' and '*'). Off by default because it adds a "
        "round-trip per host; see docs for the fail-open caveat.",
    )
    robots_honor_ai_tokens: bool = Field(
        default=True,
        description="Also honour Disallow rules aimed at named AI crawler "
        "tokens (ClaudeBot, GPTBot, CCBot, ...). These are not part of the "
        "Gopher convention, but an operator who wrote one meant 'no LLM "
        "tooling'.",
    )

    model_config = SettingsConfigDict(env_prefix="GOPHER_")


class GeminiConfig(_ProtocolConfig):
    """Configuration for Gemini protocol client."""

    allowed_ports: Annotated[list[int] | None, NoDecode] = Field(
        default=None,
        description="Optional positive port allowlist (comma-separated, e.g. "
        "1965). When set, only these ports may be connected to, closing the "
        "arbitrary-port port-scanning gap. None = any non-dangerous port.",
    )
    tofu_enabled: bool = Field(
        default=True,
        description="Enable TOFU (Trust-on-First-Use) certificate validation",
    )
    tofu_storage_path: Path | None = Field(
        default=None,
        description="TOFU storage file path",
    )
    tofu_reject_expired: bool = Field(
        default=False,
        description="Fail closed on a certificate outside its validity window "
        "(already expired, or not yet valid on first use) instead of accepting "
        "it with a warning. Off by default to match the conventional Gemini TOFU "
        "model where the fingerprint pin is the real authenticator.",
    )
    client_certs_enabled: bool = Field(
        default=True,
        description="Enable client certificate support",
    )
    client_certs_storage_path: Path | None = Field(
        default=None,
        description="Client certificates storage directory path",
    )

    @field_validator("tofu_storage_path", "client_certs_storage_path", mode="before")
    @classmethod
    def blank_path_is_unset(cls, v: object) -> object:
        """Read an empty ``GEMINI_*_PATH`` as unset rather than the cwd."""
        return _blank_path_is_unset(v)

    requests_per_minute: float = Field(
        default=60.0,  # one request per second, per host
        description="Per-host outbound request rate cap (politeness for small "
        "Gemini servers); 0 = unlimited. Defaults to one request per second "
        "per host. A status-44 SLOW_DOWN is always honoured regardless of "
        "this setting.",
        ge=0,
        le=6000,
    )
    respect_robots_txt: bool = Field(
        default=False,
        description="Fetch and honour /robots.txt from the capsule root before "
        "retrieving a resource, following the Gemini companion specification "
        "(virtual agents 'webproxy' and 'indexer', plus '*'). Off by default "
        "because it adds a round-trip per host.",
    )
    robots_honor_ai_tokens: bool = Field(
        default=True,
        description="Also honour Disallow rules aimed at named AI crawler "
        "tokens (ClaudeBot, GPTBot, CCBot, ...). Not part of the companion "
        "spec, but capsules that name them mean 'no LLM tooling'.",
    )
    denied_mime_types: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="MIME types (or `type/*` wildcards) to reject as filtered "
        "content, e.g. 'text/html,image/*'; empty = no content filtering.",
    )

    model_config = SettingsConfigDict(env_prefix="GEMINI_")

    @field_validator("denied_mime_types", mode="before")
    @classmethod
    def parse_denied_mime_types(cls, v: None | str | list[str]) -> list[str]:
        """Parse a comma-separated MIME deny list from an environment variable."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        return [mime.lower() for mime in _split_list_value(v)]


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

    @field_validator("log_file_path", mode="before")
    @classmethod
    def blank_path_is_unset(cls, v: object) -> object:
        """Read an empty ``GOPHER_MCP_LOG_FILE_PATH`` as unset rather than the cwd."""
        return _blank_path_is_unset(v)

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
        # Namespace the (complex) nested fields so a bare ``GOPHER``/``GEMINI``/
        # ``SERVER`` env var set by unrelated tooling is NOT mistaken for the
        # whole sub-config object -- without this, pydantic-settings tries to
        # JSON-parse that value and crashes startup with a SettingsError. The
        # sub-configs are populated by their default_factory (each reading its
        # own ``GOPHER_``/``GEMINI_``/``GOPHER_MCP_`` prefix), so this prefix only
        # closes the bare-name collision; it is not expected to match anything.
        env_prefix="GOPHER_MCP_APP_",
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
