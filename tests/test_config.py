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
