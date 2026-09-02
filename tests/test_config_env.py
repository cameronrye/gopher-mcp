"""Tests for parsing list-valued settings from environment variables.

These construct the config objects with the environment actually set, rather
than calling the validators directly: pydantic-settings decodes complex fields
before validation runs, so only the real env path exercises that seam.
"""

import pytest
from pydantic import ValidationError

from gopher_mcp.config import (
    GeminiConfig,
    GopherConfig,
    ServerConfig,
    configure_logging,
)

CONFIGS = [(GopherConfig, "GOPHER_"), (GeminiConfig, "GEMINI_")]


class TestAllowedHostsEnv:
    """GOPHER_ALLOWED_HOSTS / GEMINI_ALLOWED_HOSTS parsing."""

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_comma_separated(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_HOSTS", "example.com,test.org")
        assert config_cls().allowed_hosts == ["example.com", "test.org"]

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_json_array(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_HOSTS", '["example.com", "test.org"]')
        assert config_cls().allowed_hosts == ["example.com", "test.org"]

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_single_value_and_whitespace(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_HOSTS", "  example.com  ")
        assert config_cls().allowed_hosts == ["example.com"]

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_empty_string_means_no_allowlist(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_HOSTS", "")
        assert config_cls().allowed_hosts is None

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_separator_only_value_is_rejected(self, monkeypatch, config_cls, prefix):
        """`"$HOST_A,$HOST_B"` with empty interpolations must not silently
        degrade an intended allowlist into allow-all."""
        monkeypatch.setenv(f"{prefix}ALLOWED_HOSTS", " , ")
        with pytest.raises(ValidationError, match=f"{prefix}ALLOWED_HOSTS"):
            config_cls()

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_malformed_json_array_is_rejected(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_HOSTS", '["example.com"')
        with pytest.raises(ValidationError, match="Invalid JSON list"):
            config_cls()

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_list_argument_passes_through(self, monkeypatch, config_cls, prefix):
        monkeypatch.delenv(f"{prefix}ALLOWED_HOSTS", raising=False)
        assert config_cls(allowed_hosts=["example.com"]).allowed_hosts == [
            "example.com"
        ]


class TestAllowedPortsEnv:
    """GOPHER_ALLOWED_PORTS / GEMINI_ALLOWED_PORTS parsing."""

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_comma_separated(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", "70,1965")
        assert config_cls().allowed_ports == [70, 1965]

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_json_array(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", "[70, 1965]")
        assert config_cls().allowed_ports == [70, 1965]

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_single_value_and_whitespace(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", "  70 , 7070  ")
        assert config_cls().allowed_ports == [70, 7070]

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_empty_string_means_no_allowlist(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", "")
        assert config_cls().allowed_ports is None

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_separator_only_value_is_rejected(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", " , ")
        with pytest.raises(ValidationError, match=f"{prefix}ALLOWED_PORTS"):
            config_cls()

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    @pytest.mark.parametrize("port", ["0", "70000", "-1"])
    def test_out_of_range_port_is_rejected(self, monkeypatch, config_cls, prefix, port):
        """An out-of-range port can never match, so it must fail at startup
        rather than reject every request at fetch time."""
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", port)
        with pytest.raises(ValidationError, match="between 1 and 65535"):
            config_cls()

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_out_of_range_port_in_list_argument_is_rejected(
        self, monkeypatch, config_cls, prefix
    ):
        monkeypatch.delenv(f"{prefix}ALLOWED_PORTS", raising=False)
        with pytest.raises(ValidationError, match="between 1 and 65535"):
            config_cls(allowed_ports=[70, 70000])

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_non_numeric_port_is_rejected(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ALLOWED_PORTS", "gopher")
        with pytest.raises(ValidationError):
            config_cls()


class TestDeniedMimeTypesEnv:
    """GEMINI_DENIED_MIME_TYPES parsing."""

    def test_comma_separated(self, monkeypatch):
        """The documented format must not crash startup.

        Regression test: the field's non-union list type made
        pydantic-settings JSON-decode the value before validation, raising
        SettingsError on the documented comma-separated form.
        """
        monkeypatch.setenv("GEMINI_DENIED_MIME_TYPES", "text/html,image/*")
        assert GeminiConfig().denied_mime_types == ["text/html", "image/*"]

    def test_json_array(self, monkeypatch):
        monkeypatch.setenv("GEMINI_DENIED_MIME_TYPES", '["text/HTML", "image/*"]')
        assert GeminiConfig().denied_mime_types == ["text/html", "image/*"]

    def test_single_value_and_whitespace(self, monkeypatch):
        monkeypatch.setenv("GEMINI_DENIED_MIME_TYPES", "  TEXT/HTML  ")
        assert GeminiConfig().denied_mime_types == ["text/html"]

    def test_empty_string_means_no_filtering(self, monkeypatch):
        monkeypatch.setenv("GEMINI_DENIED_MIME_TYPES", "")
        assert GeminiConfig().denied_mime_types == []

    def test_separator_only_value_means_no_filtering(self, monkeypatch):
        """Unlike an allowlist, an empty deny list fails open by design."""
        monkeypatch.setenv("GEMINI_DENIED_MIME_TYPES", " , ")
        assert GeminiConfig().denied_mime_types == []

    def test_list_argument_passes_through(self, monkeypatch):
        monkeypatch.delenv("GEMINI_DENIED_MIME_TYPES", raising=False)
        assert GeminiConfig(denied_mime_types=["text/html"]).denied_mime_types == [
            "text/html"
        ]


class TestZeroCacheTtl:
    """A zero TTL means caching off, matching this module's 0-is-special rule."""

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_zero_ttl_disables_caching(self, monkeypatch, config_cls, prefix):
        """Otherwise every entry expires the instant it is stored, so the cache
        evicts and never serves a hit."""
        monkeypatch.setenv(f"{prefix}CACHE_TTL_SECONDS", "0")
        config = config_cls()
        assert config.cache_ttl_seconds == 0
        assert config.cache_enabled is False

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_nonzero_ttl_leaves_caching_enabled(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}CACHE_TTL_SECONDS", "600")
        config = config_cls()
        assert config.cache_ttl_seconds == 600
        assert config.cache_enabled is True


class TestBlankPathIsUnset:
    """An empty path value in an env file means "leave the default alone"."""

    @pytest.mark.parametrize(
        ("env_var", "attribute"),
        [
            ("GEMINI_TOFU_STORAGE_PATH", "tofu_storage_path"),
            ("GEMINI_CLIENT_CERTS_STORAGE_PATH", "client_certs_storage_path"),
        ],
    )
    def test_blank_gemini_path_is_none(self, monkeypatch, env_var, attribute):
        monkeypatch.setenv(env_var, "")
        assert getattr(GeminiConfig(), attribute) is None

    def test_blank_log_path_does_not_break_logging(self, monkeypatch):
        """Coerced to Path("."), it reached configure_logging and raised
        IsADirectoryError, so the server could not start."""
        monkeypatch.setenv("GOPHER_MCP_LOG_FILE_PATH", "   ")
        config = ServerConfig()
        assert config.log_file_path is None
        configure_logging(config)

    def test_a_real_path_still_parses(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOPHER_MCP_LOG_FILE_PATH", str(tmp_path / "server.log"))
        assert ServerConfig().log_file_path == tmp_path / "server.log"


class TestRobotsFailureBackoffEnv:
    """GOPHER_/GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS bounds."""

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_zero_is_accepted(self, monkeypatch, config_cls, prefix):
        """0 means "retry on the very next request" -- the pre-0.7.0 behaviour,
        which has to stay reachable rather than being read as unset."""
        monkeypatch.setenv(f"{prefix}ROBOTS_FAILURE_BACKOFF_SECONDS", "0")
        assert config_cls().robots_failure_backoff_seconds == 0.0

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_fractional_seconds_are_accepted(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ROBOTS_FAILURE_BACKOFF_SECONDS", "0.5")
        assert config_cls().robots_failure_backoff_seconds == 0.5

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    @pytest.mark.parametrize("value", ["-1", "3601"])
    def test_out_of_range_is_rejected(self, monkeypatch, config_cls, prefix, value):
        """A negative backoff would put the retry deadline in the past (no
        backoff at all), and past an hour it caches the outage rather than
        retrying it -- the one thing the failure path is documented not to do."""
        monkeypatch.setenv(f"{prefix}ROBOTS_FAILURE_BACKOFF_SECONDS", value)
        with pytest.raises(ValidationError):
            config_cls()

    @pytest.mark.parametrize(("config_cls", "prefix"), CONFIGS)
    def test_non_numeric_is_rejected(self, monkeypatch, config_cls, prefix):
        monkeypatch.setenv(f"{prefix}ROBOTS_FAILURE_BACKOFF_SECONDS", "soon")
        with pytest.raises(ValidationError):
            config_cls()
