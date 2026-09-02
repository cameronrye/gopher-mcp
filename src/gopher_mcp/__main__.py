"""Main entry point for the Gopher MCP server."""

import argparse
import asyncio
import contextlib
import ipaddress
import sys

import structlog
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError

from . import __version__
from .config import configure_logging, describe_config_error, get_config
from .server import cleanup, mcp

logger = structlog.get_logger(__name__)

#: Host header values that always name this machine, so they stay acceptable
#: whatever address the server is bound to.
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _has_explicit_port(entry: str) -> bool:
    """Return whether an allowlist entry already carries a port."""
    host, separator, tail = entry.rpartition(":")
    if not separator or not tail.isdigit():
        return False
    # A bare IPv6 literal is all colons and no port ("::1"); a bracketed one
    # ends its host part with "]" ("[::1]:8000").
    return entry.count(":") == 1 or host.endswith("]")


def _host_patterns(entry: str) -> list[str]:
    """Expand one allowlist entry into the patterns FastMCP matches.

    The Host header carries a port whenever the client did not use the scheme's
    default one, and FastMCP compares the header verbatim against the allowlist
    (with ``host:*`` as the only wildcard). An operator naming a bare hostname
    means "on whatever port I bound", so admit both spellings.
    """
    if entry.endswith(":*") or _has_explicit_port(entry):
        return [entry]
    return [entry, f"{entry}:*"]


def _is_loopback(host: str) -> bool:
    """Return whether a bind address reaches only this machine."""
    if host == "localhost":
        return True
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    return False


def _is_wildcard(host: str) -> bool:
    """Return whether a bind address means "every interface" (0.0.0.0, ::)."""
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(host.strip("[]")).is_unspecified
    return False


def _transport_security(
    host: str | None, allowed_hosts: list[str] | None
) -> TransportSecuritySettings | None:
    """Decide the Host/Origin policy for the HTTP transports.

    FastMCP settles this in its constructor: built with a loopback host (or
    none, as server.py does) it installs a loopback-only Host allowlist as DNS
    rebinding protection, and built with a routable host it installs nothing,
    on the reasoning that the operator has asked to be reachable. Assigning
    ``settings.host`` afterwards -- the only route a CLI flag has -- skips that
    decision entirely, so ``--host 0.0.0.0`` kept the loopback allowlist and the
    container answered 421 Misdirected Request to every client that was not on
    localhost. Reproduce the constructor's decision here, after the fact.

    Args:
        host: The ``--host`` value, or None when the flag was not given.
        allowed_hosts: Host header values from ``--allowed-host``, if any.

    Returns:
        The settings to assign, or None to leave FastMCP's own choice alone.
    """
    if allowed_hosts:
        # Protection stays ON, widened to the names this deployment answers to:
        # a reverse proxy's public name, a container hostname, a service DNS
        # name. This is the alternative to turning the check off wholesale.
        entries = [*allowed_hosts]
        if host is not None and not _is_wildcard(host):
            entries.append(host)
        entries.extend(_LOOPBACK_HOSTS)
        patterns: list[str] = []
        for entry in entries:
            patterns.extend(p for p in _host_patterns(entry) if p not in patterns)
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=patterns,
            # Browser clients send Origin; an allowed Host with a rejected
            # Origin is the same 421 by another name.
            allowed_origins=[
                f"{scheme}://{pattern}"
                for pattern in patterns
                for scheme in ("http", "https")
            ],
        )
    if host is not None and not _is_loopback(host):
        # No allowlist to build, and no way to guess the name clients will use
        # for a routable (often wildcard) bind. Match what FastMCP does when it
        # is constructed with such a host: no Host/Origin check. Narrow it back
        # down with --allowed-host.
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return None


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="gopher-mcp",
        description=(
            f"gopher-mcp {__version__}: MCP server for browsing Gopher and "
            "Gemini resources"
        ),
        epilog=(
            "Everything else is configured through environment variables: "
            "GOPHER_* (Gopher client), GEMINI_* (Gemini client) and "
            "GOPHER_MCP_* (logging). See "
            "https://cameronrye.github.io/gopher-mcp/configuration/"
        ),
    )
    # The first question on any bug report. `python -c "import gopher_mcp"` --
    # what the docs used to point at -- cannot be run for the uvx and Docker
    # installs the same docs recommend.
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Bind host for the sse/streamable-http transports (ignored for stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port for the sse/streamable-http transports (ignored for stdio)",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        default=None,
        metavar="HOST[:PORT]",
        help=(
            "Host header to accept for the sse/streamable-http transports; "
            "repeatable. Give the name clients or the reverse proxy use "
            "(a bare name matches any port). Requests arriving under any other "
            "name are refused with 421. Without this flag a non-loopback "
            "--host accepts any Host, as FastMCP itself does when constructed "
            "with one."
        ),
    )
    return parser


def main() -> None:
    """Run the main entry point."""
    # Parsed BEFORE the configuration is loaded so that --help and --version
    # answer even when the environment holds a value the config layer rejects.
    parser = _build_parser()
    args = parser.parse_args()

    try:
        config = get_config()
    except ValidationError as exc:
        # A typo in .env is a configuration mistake, not a crash: name the
        # variable to fix instead of printing pydantic's internals.
        for line in describe_config_error(exc):
            print(f"{parser.prog}: configuration error: {line}", file=sys.stderr)
        sys.exit(2)

    # Configure logging (to stderr) from ServerConfig before anything logs.
    configure_logging(config.server)

    # Bind address/port for the HTTP-based transports live on FastMCP's settings
    # (its run() reads them from there); wire the CLI flags in before run().
    if args.host is not None:
        mcp.settings.host = args.host
    if args.port is not None:
        mcp.settings.port = args.port
    security = _transport_security(args.host, args.allowed_hosts)
    if security is not None:
        mcp.settings.transport_security = security
        # Log it: the Host check is invisible when it passes and a bare 421 when
        # it does not, so record what is actually being enforced.
        logger.info(
            "Transport security configured",
            host=args.host,
            dns_rebinding_protection=security.enable_dns_rebinding_protection,
            allowed_hosts=security.allowed_hosts,
        )

    try:
        # FastMCP handles its own event loop. For the HTTP transports it reaches
        # this package's own uvicorn runner (see ``server._GopherMCP``), which is
        # what keeps uvicorn's records on the configured logging pipeline.
        mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        pass
    finally:
        # Release client/transport resources on shutdown.
        with contextlib.suppress(Exception):
            asyncio.run(cleanup())


if __name__ == "__main__":
    main()
