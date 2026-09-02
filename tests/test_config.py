"""Tests for configuration and logging setup."""

import structlog

from gopher_mcp.config import AppConfig, ServerConfig, configure_logging


def test_stray_unprefixed_env_var_does_not_crash_startup(monkeypatch):
    """A bare GOPHER/GEMINI/SERVER env var set by unrelated tooling must not be
    misread as the nested config object and crash AppConfig() at startup."""
    monkeypatch.setenv("GOPHER", "some-unrelated-value")
    monkeypatch.setenv("SERVER", "another-value")
    cfg = AppConfig()  # must not raise
    assert cfg.gopher.max_response_size == 1048576
    assert cfg.server.log_level == "INFO"


def test_configure_logging_writes_application_logs_to_file(tmp_path):
    """Setting log_file_path must route application (structlog) logs to the
    file, not just create an empty one.

    Regression test: structlog was configured with a PrintLoggerFactory bound
    to stderr only, so the FileHandler added to stdlib logging never received
    any of the application's records and the configured file stayed empty.
    """
    log_file = tmp_path / "audit.log"
    config = ServerConfig(log_file_path=log_file)

    try:
        configure_logging(config)
        logger = structlog.get_logger("test.config.logfile")
        logger.info("ssrf_block_event", host="169.254.169.254")
    finally:
        # Restore stderr-only logging so the open file handle to tmp_path is
        # released for subsequent tests.
        configure_logging(ServerConfig(log_file_path=None))

    contents = log_file.read_text(encoding="utf-8")
    assert "ssrf_block_event" in contents


class TestPolitenessDefaults:
    """Rate limiting ships enabled; robots checking ships opt-in."""

    def test_rate_limiting_is_on_by_default(self):
        from gopher_mcp.config import GeminiConfig, GopherConfig

        assert GopherConfig().requests_per_minute == 60.0
        assert GeminiConfig().requests_per_minute == 60.0

    def test_concurrency_is_capped_by_default(self):
        from gopher_mcp.config import GeminiConfig, GopherConfig

        assert GopherConfig().max_concurrent_requests == 5
        assert GeminiConfig().max_concurrent_requests == 5

    def test_robots_is_on_by_default(self):
        """Flipped in 0.7.0. Ignoring a server's stated policy is not a
        defensible default for a tool an LLM drives unattended, and the probe
        is cached per host so it costs one round-trip per host, not per fetch."""
        from gopher_mcp.config import GeminiConfig, GopherConfig

        assert GopherConfig().respect_robots_txt is True
        assert GeminiConfig().respect_robots_txt is True

    def test_robots_defaults(self):
        from gopher_mcp.config import GeminiConfig, GopherConfig

        for cfg in (GopherConfig(), GeminiConfig()):
            assert cfg.robots_cache_ttl_seconds == 86400
            assert cfg.robots_honor_ai_tokens is True
            assert cfg.robots_failure_backoff_seconds == 60.0

    def test_robots_env_vars(self, monkeypatch):
        from gopher_mcp.config import GeminiConfig, GopherConfig

        monkeypatch.setenv("GOPHER_RESPECT_ROBOTS_TXT", "true")
        monkeypatch.setenv("GOPHER_ROBOTS_CACHE_TTL_SECONDS", "3600")
        monkeypatch.setenv("GEMINI_RESPECT_ROBOTS_TXT", "true")
        monkeypatch.setenv("GEMINI_ROBOTS_HONOR_AI_TOKENS", "false")
        monkeypatch.setenv("GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS", "5")

        gopher = GopherConfig()
        assert gopher.respect_robots_txt is True
        assert gopher.robots_cache_ttl_seconds == 3600

        gemini = GeminiConfig()
        assert gemini.respect_robots_txt is True
        assert gemini.robots_honor_ai_tokens is False
        assert gemini.robots_failure_backoff_seconds == 5.0

    def test_defaults_match_the_client_constants(self):
        """config.py restates these as literals (the module's convention).

        This test is the guard against the two drifting apart.
        """
        from gopher_mcp import gemini_client, gopher_client
        from gopher_mcp.config import GeminiConfig, GopherConfig

        # Each client module carries its own copy, as it already does for
        # response size and timeout; guard both against drifting from config.
        for module, cfg in (
            (gopher_client, GopherConfig()),
            (gemini_client, GeminiConfig()),
        ):
            assert cfg.requests_per_minute == module.DEFAULT_REQUESTS_PER_MINUTE
            assert cfg.max_concurrent_requests == (
                module.DEFAULT_MAX_CONCURRENT_REQUESTS
            )
            assert cfg.robots_cache_ttl_seconds == (
                module.DEFAULT_ROBOTS_CACHE_TTL_SECONDS
            )
            assert cfg.robots_failure_backoff_seconds == (
                module.DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS
            )

    def test_the_two_client_modules_agree(self):
        """gopher_client and gemini_client each carry their own copy."""
        from gopher_mcp import gemini_client, gopher_client

        for const in (
            "DEFAULT_REQUESTS_PER_MINUTE",
            "DEFAULT_MAX_CONCURRENT_REQUESTS",
            "DEFAULT_ROBOTS_CACHE_TTL_SECONDS",
            "DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS",
        ):
            assert getattr(gopher_client, const) == getattr(gemini_client, const)

    def test_the_backoff_default_matches_the_gate(self):
        """A third copy lives on RobotsGate, where the rationale is written.

        The gate is the only one of the three that is also a *fallback* -- it is
        what a RobotsGate built without the argument uses -- so a drift here
        would go unnoticed everywhere except in direct gate construction.
        """
        from gopher_mcp import gopher_client
        from gopher_mcp.robots import RobotsGate

        assert (
            gopher_client.DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS
            == RobotsGate.FAILURE_BACKOFF_SECONDS
        )
