"""Centralized configuration management using Pydantic Settings."""

from pathlib import Path
from typing import List, Optional, Union

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
    )
    max_cache_entries: int = Field(
        default=1000,
        description="Maximum number of cache entries",
        ge=0,
        le=100000,
    )
    allowed_hosts: Optional[List[str]] = Field(
        default=None,
        description="List of allowed hostnames (None = allow all)",
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

    model_config = SettingsConfigDict(
        env_prefix="GOPHER_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: Optional[str]) -> Optional[List[str]]:
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
    )
    max_cache_entries: int = Field(
        default=1000,
        description="Maximum number of cache entries",
        ge=0,
        le=100000,
    )
    allowed_hosts: Optional[List[str]] = Field(
        default=None,
        description="List of allowed hostnames (None = allow all)",
    )
    tofu_enabled: bool = Field(
        default=True,
        description="Enable TOFU (Trust-on-First-Use) certificate validation",
    )
    tofu_storage_path: Optional[Path] = Field(
        default=None,
        description="TOFU storage file path",
    )
    client_certs_enabled: bool = Field(
        default=True,
        description="Enable client certificate support",
    )
    client_certs_storage_path: Optional[Path] = Field(
        default=None,
        description="Client certificates storage directory path",
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
    def parse_allowed_hosts(cls, v: Union[None, str, List[str]]) -> Optional[List[str]]:
        """Parse comma-separated allowed hosts from environment variable."""
        if v is None or v == "":
            return None
        if isinstance(v, list):
            return v
        return [host.strip() for host in v.split(",") if host.strip()]


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
    log_file_path: Optional[Path] = Field(
        default=None,
        description="Log file path (optional, logs to stdout if not set)",
    )
    development_mode: bool = Field(
        default=False,
        description="Enable development mode",
    )

    model_config = SettingsConfigDict(
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
_config: Optional[AppConfig] = None


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
