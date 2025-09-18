#!/usr/bin/env python3
"""
Configuration validation script for Gopher & Gemini MCP Server.

This script validates environment variables and configuration settings
to ensure they are properly formatted and within acceptable ranges.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List


class ConfigValidator:
    """Validates configuration settings for the MCP server."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.config: Dict[str, Any] = {}

    def validate_all(self) -> bool:
        """Validate all configuration settings."""
        print("🔍 Validating Gopher & Gemini MCP Server Configuration...")
        print()

        # Load environment variables
        self._load_config()

        # Validate each category
        self._validate_gopher_config()
        self._validate_gemini_config()
        self._validate_tls_config()
        self._validate_logging_config()
        self._validate_security_config()
        self._validate_performance_config()

        # Report results
        self._report_results()

        return len(self.errors) == 0

    def _load_config(self):
        """Load configuration from environment variables."""
        # Gopher configuration
        self.config.update(
            {
                "gopher_max_response_size": os.getenv(
                    "GOPHER_MAX_RESPONSE_SIZE", "1048576"
                ),
                "gopher_timeout_seconds": os.getenv("GOPHER_TIMEOUT_SECONDS", "30"),
                "gopher_cache_enabled": os.getenv("GOPHER_CACHE_ENABLED", "true"),
                "gopher_cache_ttl_seconds": os.getenv(
                    "GOPHER_CACHE_TTL_SECONDS", "300"
                ),
                "gopher_max_cache_entries": os.getenv(
                    "GOPHER_MAX_CACHE_ENTRIES", "1000"
                ),
                "gopher_allowed_hosts": os.getenv("GOPHER_ALLOWED_HOSTS", ""),
                "gopher_max_selector_length": os.getenv(
                    "GOPHER_MAX_SELECTOR_LENGTH", "1024"
                ),
                "gopher_max_search_length": os.getenv(
                    "GOPHER_MAX_SEARCH_LENGTH", "256"
                ),
            }
        )

        # Gemini configuration
        self.config.update(
            {
                "gemini_max_response_size": os.getenv(
                    "GEMINI_MAX_RESPONSE_SIZE", "1048576"
                ),
                "gemini_timeout_seconds": os.getenv("GEMINI_TIMEOUT_SECONDS", "30"),
                "gemini_cache_enabled": os.getenv("GEMINI_CACHE_ENABLED", "true"),
                "gemini_cache_ttl_seconds": os.getenv(
                    "GEMINI_CACHE_TTL_SECONDS", "300"
                ),
                "gemini_max_cache_entries": os.getenv(
                    "GEMINI_MAX_CACHE_ENTRIES", "1000"
                ),
                "gemini_allowed_hosts": os.getenv("GEMINI_ALLOWED_HOSTS", ""),
                "gemini_tofu_enabled": os.getenv("GEMINI_TOFU_ENABLED", "true"),
                "gemini_client_certs_enabled": os.getenv(
                    "GEMINI_CLIENT_CERTS_ENABLED", "true"
                ),
                "gemini_tofu_storage_path": os.getenv("GEMINI_TOFU_STORAGE_PATH", ""),
                "gemini_client_cert_storage_path": os.getenv(
                    "GEMINI_CLIENT_CERT_STORAGE_PATH", ""
                ),
            }
        )

        # TLS configuration
        self.config.update(
            {
                "gemini_tls_version": os.getenv("GEMINI_TLS_VERSION", "TLSv1.2"),
                "gemini_tls_verify_hostname": os.getenv(
                    "GEMINI_TLS_VERIFY_HOSTNAME", "true"
                ),
                "gemini_tls_client_cert_path": os.getenv(
                    "GEMINI_TLS_CLIENT_CERT_PATH", ""
                ),
                "gemini_tls_client_key_path": os.getenv(
                    "GEMINI_TLS_CLIENT_KEY_PATH", ""
                ),
            }
        )

        # Other configuration
        self.config.update(
            {
                "log_level": os.getenv("LOG_LEVEL", "INFO"),
                "structured_logging": os.getenv("STRUCTURED_LOGGING", "true"),
                "log_file_path": os.getenv("LOG_FILE_PATH", ""),
                "development_mode": os.getenv("DEVELOPMENT_MODE", "false"),
                "strict_host_validation": os.getenv("STRICT_HOST_VALIDATION", "false"),
                "max_redirects": os.getenv("MAX_REDIRECTS", "5"),
                "max_concurrent_connections": os.getenv(
                    "MAX_CONCURRENT_CONNECTIONS", "10"
                ),
            }
        )

    def _validate_gopher_config(self):
        """Validate Gopher protocol configuration."""
        print("📡 Validating Gopher configuration...")

        # Validate numeric values
        self._validate_positive_int(
            "gopher_max_response_size",
            "GOPHER_MAX_RESPONSE_SIZE",
            1024,
            100 * 1024 * 1024,
        )
        self._validate_positive_float(
            "gopher_timeout_seconds", "GOPHER_TIMEOUT_SECONDS", 1.0, 300.0
        )
        self._validate_positive_int(
            "gopher_cache_ttl_seconds", "GOPHER_CACHE_TTL_SECONDS", 1, 86400
        )
        self._validate_positive_int(
            "gopher_max_cache_entries", "GOPHER_MAX_CACHE_ENTRIES", 1, 100000
        )
        self._validate_positive_int(
            "gopher_max_selector_length", "GOPHER_MAX_SELECTOR_LENGTH", 1, 8192
        )
        self._validate_positive_int(
            "gopher_max_search_length", "GOPHER_MAX_SEARCH_LENGTH", 1, 2048
        )

        # Validate boolean values
        self._validate_boolean("gopher_cache_enabled", "GOPHER_CACHE_ENABLED")

        # Validate host list
        self._validate_host_list("gopher_allowed_hosts", "GOPHER_ALLOWED_HOSTS")

    def _validate_gemini_config(self):
        """Validate Gemini protocol configuration."""
        print("🔐 Validating Gemini configuration...")

        # Validate numeric values
        self._validate_positive_int(
            "gemini_max_response_size",
            "GEMINI_MAX_RESPONSE_SIZE",
            1024,
            100 * 1024 * 1024,
        )
        self._validate_positive_float(
            "gemini_timeout_seconds", "GEMINI_TIMEOUT_SECONDS", 1.0, 300.0
        )
        self._validate_positive_int(
            "gemini_cache_ttl_seconds", "GEMINI_CACHE_TTL_SECONDS", 1, 86400
        )
        self._validate_positive_int(
            "gemini_max_cache_entries", "GEMINI_MAX_CACHE_ENTRIES", 1, 100000
        )

        # Validate boolean values
        self._validate_boolean("gemini_cache_enabled", "GEMINI_CACHE_ENABLED")
        self._validate_boolean("gemini_tofu_enabled", "GEMINI_TOFU_ENABLED")
        self._validate_boolean(
            "gemini_client_certs_enabled", "GEMINI_CLIENT_CERTS_ENABLED"
        )

        # Validate host list
        self._validate_host_list("gemini_allowed_hosts", "GEMINI_ALLOWED_HOSTS")

        # Validate storage paths
        self._validate_storage_path(
            "gemini_tofu_storage_path", "GEMINI_TOFU_STORAGE_PATH"
        )
        self._validate_storage_path(
            "gemini_client_cert_storage_path", "GEMINI_CLIENT_CERT_STORAGE_PATH"
        )

    def _validate_tls_config(self):
        """Validate TLS configuration."""
        print("🔒 Validating TLS configuration...")

        # Validate TLS version
        tls_version = self.config["gemini_tls_version"]
        if tls_version not in ["TLSv1.2", "TLSv1.3"]:
            self.errors.append(
                f"GEMINI_TLS_VERSION must be 'TLSv1.2' or 'TLSv1.3', got: {tls_version}"
            )

        # Validate boolean values
        self._validate_boolean(
            "gemini_tls_verify_hostname", "GEMINI_TLS_VERIFY_HOSTNAME"
        )

        # Validate certificate files
        cert_path = self.config["gemini_tls_client_cert_path"]
        key_path = self.config["gemini_tls_client_key_path"]

        if cert_path and not key_path:
            self.errors.append(
                "GEMINI_TLS_CLIENT_KEY_PATH must be set when GEMINI_TLS_CLIENT_CERT_PATH is set"
            )
        elif key_path and not cert_path:
            self.errors.append(
                "GEMINI_TLS_CLIENT_CERT_PATH must be set when GEMINI_TLS_CLIENT_KEY_PATH is set"
            )

        if cert_path and not Path(cert_path).exists():
            self.errors.append(f"Client certificate file not found: {cert_path}")
        if key_path and not Path(key_path).exists():
            self.errors.append(f"Client key file not found: {key_path}")

    def _validate_logging_config(self):
        """Validate logging configuration."""
        print("📝 Validating logging configuration...")

        # Validate log level
        log_level = self.config["log_level"].upper()
        if log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            self.errors.append(
                f"LOG_LEVEL must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL, got: {log_level}"
            )

        # Validate boolean values
        self._validate_boolean("structured_logging", "STRUCTURED_LOGGING")
        self._validate_boolean("development_mode", "DEVELOPMENT_MODE")

        # Validate log file path
        log_file = self.config["log_file_path"]
        if log_file:
            log_dir = Path(log_file).parent
            if not log_dir.exists():
                self.warnings.append(f"Log directory does not exist: {log_dir}")

    def _validate_security_config(self):
        """Validate security configuration."""
        print("🛡️ Validating security configuration...")

        # Validate boolean values
        self._validate_boolean("strict_host_validation", "STRICT_HOST_VALIDATION")

        # Validate max redirects
        self._validate_positive_int("max_redirects", "MAX_REDIRECTS", 0, 20)

    def _validate_performance_config(self):
        """Validate performance configuration."""
        print("⚡ Validating performance configuration...")

        # Validate connection limits
        self._validate_positive_int(
            "max_concurrent_connections", "MAX_CONCURRENT_CONNECTIONS", 1, 100
        )

    def _validate_positive_int(
        self, key: str, env_var: str, min_val: int, max_val: int
    ):
        """Validate a positive integer value."""
        try:
            value = int(self.config[key])
            if value < min_val or value > max_val:
                self.errors.append(
                    f"{env_var} must be between {min_val} and {max_val}, got: {value}"
                )
        except ValueError:
            self.errors.append(
                f"{env_var} must be a valid integer, got: {self.config[key]}"
            )

    def _validate_positive_float(
        self, key: str, env_var: str, min_val: float, max_val: float
    ):
        """Validate a positive float value."""
        try:
            value = float(self.config[key])
            if value < min_val or value > max_val:
                self.errors.append(
                    f"{env_var} must be between {min_val} and {max_val}, got: {value}"
                )
        except ValueError:
            self.errors.append(
                f"{env_var} must be a valid number, got: {self.config[key]}"
            )

    def _validate_boolean(self, key: str, env_var: str):
        """Validate a boolean value."""
        value = self.config[key].lower()
        if value not in ["true", "false", "1", "0", "yes", "no", "on", "off"]:
            self.errors.append(
                f"{env_var} must be a boolean value (true/false, 1/0, yes/no, on/off), got: {self.config[key]}"
            )

    def _validate_host_list(self, key: str, env_var: str):
        """Validate a comma-separated host list."""
        hosts = self.config[key]
        if not hosts:
            return

        host_list = [h.strip() for h in hosts.split(",")]
        for host in host_list:
            if not host:
                self.errors.append(f"{env_var} contains empty host name")
            elif " " in host:
                self.errors.append(
                    f"{env_var} host names cannot contain spaces: {host}"
                )
            elif not self._is_valid_hostname(host):
                self.warnings.append(
                    f"{env_var} contains potentially invalid hostname: {host}"
                )

    def _validate_storage_path(self, key: str, env_var: str):
        """Validate a storage path."""
        path = self.config[key]
        if not path:
            return

        path_obj = Path(path)
        if path_obj.exists() and not path_obj.is_dir() and not path_obj.suffix:
            # If it exists and is not a directory and has no extension, assume it should be a directory
            self.warnings.append(
                f"{env_var} points to existing file, expected directory: {path}"
            )

    def _is_valid_hostname(self, hostname: str) -> bool:
        """Check if hostname is roughly valid."""
        if len(hostname) > 253:
            return False
        if hostname.startswith(".") or hostname.endswith("."):
            return False
        allowed = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
        )
        return all(c in allowed for c in hostname)

    def _report_results(self):
        """Report validation results."""
        print()
        print("=" * 60)
        print("📊 VALIDATION RESULTS")
        print("=" * 60)

        if self.errors:
            print(f"❌ {len(self.errors)} ERROR(S) FOUND:")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")
            print()

        if self.warnings:
            print(f"⚠️  {len(self.warnings)} WARNING(S) FOUND:")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")
            print()

        if not self.errors and not self.warnings:
            print("✅ All configuration settings are valid!")
        elif not self.errors:
            print("✅ Configuration is valid (with warnings)")
        else:
            print("❌ Configuration validation failed")

        print()
        print("💡 TIP: See config/example.env for configuration examples")
        print("📖 DOC: See docs/ directory for detailed documentation")


def main():
    """Main entry point."""
    validator = ConfigValidator()
    success = validator.validate_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
