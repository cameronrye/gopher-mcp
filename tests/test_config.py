"""Tests for configuration and logging setup."""

import structlog

from gopher_mcp.config import ServerConfig, configure_logging


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
