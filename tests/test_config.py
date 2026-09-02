"""Tests for configuration, logging setup and the command-line entry point."""

import io
import json
import logging
import sys
from unittest.mock import patch

import pytest
import structlog

from gopher_mcp.config import AppConfig, ServerConfig, configure_logging, reset_config


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


class TestOneLoggingPipeline:
    """Records from the MCP SDK and uvicorn go through the same chain as ours.

    Only structlog used to be configured, so stdlib records were emitted raw:
    a stream documented as line-delimited JSON carried the SDK's "Processing
    request of type ListToolsRequest" verbatim, and the log file mirrored none
    of them.
    """

    def _capture(self, config, emit):
        stream = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = stream
        try:
            configure_logging(config)
            emit()
        finally:
            sys.stderr = original_stderr
            # Restore stderr-only logging so later tests don't write into the
            # dead buffer above.
            configure_logging(ServerConfig())
        return [line for line in stream.getvalue().splitlines() if line.strip()]

    def test_every_line_is_json_when_structured_logging_is_on(self):
        def emit():
            structlog.get_logger("test.pipeline").info("app_event", host="example.com")
            logging.getLogger("uvicorn.error").info(
                "Processing request of type %s", "ListToolsRequest"
            )

        lines = self._capture(ServerConfig(structured_logging=True), emit)

        assert len(lines) == 2, lines
        # The assertion is that *every* line parses: one raw line is enough to
        # break a log shipper reading the stream as JSON.
        records = [json.loads(line) for line in lines]
        assert records[0]["event"] == "app_event"
        assert records[0]["host"] == "example.com"
        assert records[1]["event"] == "Processing request of type ListToolsRequest"
        # Foreign records get the logger name, which is how an operator tells
        # the SDK's lines from ours.
        assert records[1]["logger"] == "uvicorn.error"
        assert all(record["level"] == "info" for record in records)
        assert all("timestamp" in record for record in records)

    def test_stdlib_records_reach_the_log_file_too(self, tmp_path):
        """The opt-in log file used to omit every SDK and uvicorn line."""
        log_file = tmp_path / "audit.log"

        def emit():
            logging.getLogger("mcp.server.lowlevel").warning("sdk_warning")

        self._capture(ServerConfig(log_file_path=log_file), emit)

        assert "sdk_warning" in log_file.read_text(encoding="utf-8")

    def test_a_traceback_is_rendered_inside_the_json_record(self):
        """A logged exception used to reduce to the token ``"exc_info": true``
        (ours) or three reprs (uvicorn's) -- never the traceback itself."""

        def emit():
            try:
                raise ValueError("boom")
            except ValueError:
                logging.getLogger("uvicorn.error").exception("stdlib_failure")

        lines = self._capture(ServerConfig(structured_logging=True), emit)

        assert len(lines) == 1, lines
        record = json.loads(lines[0])
        assert "ValueError: boom" in record["exception"]


class TestConfigErrorMessages:
    """An invalid environment value is a configuration mistake, not a crash."""

    @pytest.fixture(autouse=True)
    def _drop_cached_config(self):
        # get_config() memoizes, so an already-built config would hide the
        # invalid environment these tests set up (and a config built from it
        # must not outlive them).
        reset_config()
        yield
        reset_config()

    def test_invalid_value_names_the_env_var_and_does_not_traceback(
        self, monkeypatch, capsys
    ):
        from gopher_mcp import __main__ as entry

        monkeypatch.setenv("GOPHER_TIMEOUT_SECONDS", "abc")
        with patch("sys.argv", ["gopher-mcp"]), pytest.raises(SystemExit) as exc:
            entry.main()

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert err.splitlines() == [
            "gopher-mcp: configuration error: GOPHER_TIMEOUT_SECONDS: Input "
            "should be a valid number, unable to parse string as a number "
            "(got 'abc')"
        ]
        # The pydantic field name and class are what the 26-line traceback used
        # to point at; neither is anything the operator can edit.
        assert "Traceback" not in err
        assert "timeout_seconds" not in err
        assert "GopherConfig" not in err

    def test_out_of_range_value_reports_the_accepted_range(self, monkeypatch, capsys):
        from gopher_mcp import __main__ as entry

        monkeypatch.setenv("GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS", "99999")
        with patch("sys.argv", ["gopher-mcp"]), pytest.raises(SystemExit):
            entry.main()

        err = capsys.readouterr().err
        assert "GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS" in err
        assert "less than or equal to 3600" in err
        assert "99999" in err

    def test_help_survives_an_invalid_environment(self, monkeypatch, capsys):
        """--help is what an operator reaches for while diagnosing, so it must
        not be taken down by the very value they are diagnosing."""
        from gopher_mcp import __main__ as entry

        monkeypatch.setenv("GOPHER_MCP_LOG_LEVEL", "verbose")
        with (
            patch("sys.argv", ["gopher-mcp", "--help"]),
            pytest.raises(SystemExit) as e,
        ):
            entry.main()

        assert e.value.code == 0
        captured = capsys.readouterr()
        assert "--transport" in captured.out
        assert captured.err == ""


def _run_cli(*flags):
    """Run the entry point with ``flags``, returning the Host policy it set.

    ``mcp.run`` is patched out so nothing binds a socket; the singleton's
    original policy is put back so one test's flags cannot leak into another's.
    """
    from gopher_mcp import __main__ as entry
    from gopher_mcp.server import mcp as server_mcp

    original = server_mcp.settings.transport_security
    try:
        with (
            patch("sys.argv", ["gopher-mcp", "--transport", "streamable-http", *flags]),
            patch.object(server_mcp, "run"),
        ):
            entry.main()
        return server_mcp.settings.transport_security
    finally:
        server_mcp.settings.transport_security = original


def _post_with_host(security, host_header):
    """Boot a streamable-http app under ``security`` and POST to it as
    ``host_header`` would, returning the response."""
    from mcp.server.fastmcp import FastMCP
    from starlette.testclient import TestClient

    app = FastMCP(
        "host-header-probe", transport_security=security
    ).streamable_http_app()
    with TestClient(app, base_url=f"http://{host_header}") as client:
        return client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )


class TestHostHeaderPolicy:
    """--host must actually make the server reachable under that host.

    FastMCP settles its DNS-rebinding policy in the constructor, and server.py
    constructs it with no host at all, so it locks in a loopback-only Host
    allowlist. Assigning ``settings.host`` afterwards -- all a CLI flag can do
    -- left that allowlist in place, and the Docker image (whose CMD binds
    0.0.0.0 precisely to be reachable) answered 421 Misdirected Request to
    every client that was not on localhost.
    """

    def test_fastmcps_own_default_rejects_a_remote_host_header(self):
        """The control the other tests are measured against: this is the policy
        server.py's construction installs, and it is why the bug existed."""
        from mcp.server.fastmcp import FastMCP

        loopback_only = FastMCP("control").settings.transport_security
        assert _post_with_host(loopback_only, "192.168.1.50:8000").status_code == 421

    def test_a_wildcard_bind_accepts_a_remote_host_header(self):
        security = _run_cli("--host", "0.0.0.0")

        assert security.enable_dns_rebinding_protection is False
        assert _post_with_host(security, "192.168.1.50:8000").status_code != 421
        assert _post_with_host(security, "gopher-mcp:8000").status_code != 421

    def test_allowed_host_admits_a_proxy_name_without_disabling_the_check(self):
        """The narrow alternative to turning the protection off: name the hosts
        this deployment answers to and everything else still gets 421."""
        security = _run_cli("--host", "0.0.0.0", "--allowed-host", "gopher.example")

        assert security.enable_dns_rebinding_protection is True
        assert _post_with_host(security, "gopher.example:8000").status_code != 421
        # A bare name in the flag covers whatever port was bound.
        assert _post_with_host(security, "gopher.example").status_code != 421
        assert _post_with_host(security, "evil.example:8000").status_code == 421
        # Loopback stays usable for a health check on the box itself.
        assert _post_with_host(security, "localhost:8000").status_code != 421

    def test_allowed_host_is_repeatable(self):
        security = _run_cli(
            "--host",
            "0.0.0.0",
            "--allowed-host",
            "a.example",
            "--allowed-host",
            "b.example:8443",
        )

        assert _post_with_host(security, "a.example:8000").status_code != 421
        assert _post_with_host(security, "b.example:8443").status_code != 421
        # An entry that names a port is taken literally, not widened.
        assert _post_with_host(security, "b.example:9000").status_code == 421

    def test_a_loopback_bind_keeps_the_protection_it_already_had(self):
        """Nothing about binding localhost says the operator accepted exposure,
        so the SDK's own allowlist must survive untouched."""
        security = _run_cli("--host", "127.0.0.1")

        assert security.enable_dns_rebinding_protection is True
        assert security.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"]


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
