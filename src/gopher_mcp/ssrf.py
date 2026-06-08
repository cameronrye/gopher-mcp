"""SSRF protection for outbound Gopher/Gemini connections.

Both protocol clients route every connection through :func:`validate_target`
before opening a socket. By default this rejects targets that resolve to
loopback, link-local (including the cloud-metadata address
``169.254.169.254``), private (RFC 1918), reserved, multicast or unspecified
addresses, so an attacker-influenced URL handed to the LLM cannot be used to
reach internal services or scan the local network.

Operators who genuinely need to reach local hosts (e.g. testing against a
Gopher server on localhost) can opt in per protocol with
``GOPHER_ALLOW_LOCAL_HOSTS`` / ``GEMINI_ALLOW_LOCAL_HOSTS``.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Iterable

import structlog

logger = structlog.get_logger(__name__)


class SSRFError(ValueError):
    """Raised when a target host/address is blocked by the SSRF policy."""


# Deprecated IPv6 site-local prefix. CPython reports ``fec0::/10`` as
# ``is_global=True`` (it predates the modern special-registry rules), so the
# generic ``not is_global`` catch-all below would miss it -- block it explicitly.
_IPV6_SITE_LOCAL = ipaddress.ip_network("fec0::/10")


# Ports for non-Gopher/Gemini services an SSRF could otherwise be steered to
# poke. Blocked as defense-in-depth -- this complements (does not replace) the
# internal-address checks. Gopher (70) and Gemini (1965) are deliberately absent.
DANGEROUS_PORTS = frozenset(
    {
        22,  # SSH
        23,  # Telnet
        25,  # SMTP
        110,  # POP3
        143,  # IMAP
        445,  # SMB
        465,  # SMTPS
        587,  # SMTP submission
        993,  # IMAPS
        995,  # POP3S
        1433,  # MSSQL
        3306,  # MySQL
        3389,  # RDP
        5432,  # PostgreSQL
        5900,  # VNC
        6379,  # Redis
        9200,  # Elasticsearch
        11211,  # Memcached
        27017,  # MongoDB
    }
)


def normalize_host(host: str) -> str:
    """Normalize a hostname for comparison.

    Strips surrounding IPv6 brackets, a single trailing dot, and lowercases,
    so that ``Example.COM`` and ``example.com.`` compare equal to
    ``example.com`` (closing common allowlist-bypass tricks).
    """
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if h.endswith("."):
        h = h[:-1]
    return h.lower()


def classify_blocked_ip(value: str) -> str | None:
    """Return a reason string if ``value`` is a blocked IP literal, else ``None``.

    Returns ``None`` when ``value`` is not an IP literal at all (i.e. it is a
    hostname that must be resolved first).
    """
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None

    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) so it can't bypass checks.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    # Deprecated IPv6 site-local needs an explicit check (see _IPV6_SITE_LOCAL).
    if isinstance(ip, ipaddress.IPv6Address) and ip in _IPV6_SITE_LOCAL:
        return "site-local"

    # Order matters: check specific categories before the broad is_private,
    # which in CPython also covers loopback/link-local/unspecified ranges.
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_multicast:
        return "multicast"
    if ip.is_private:
        return "private"
    if ip.is_reserved:
        return "reserved"

    # Catch-all: anything not globally routable that the specific checks above
    # missed -- CGNAT (RFC 6598, 100.64.0.0/10), benchmarking, future-use, etc.
    # Inverting on is_global future-proofs the denylist against new non-public
    # ranges without enumerating each one.
    if not ip.is_global:
        return "non-global"
    return None


async def resolve_host(host: str, port: int) -> list[str]:
    """Resolve ``host`` to a list of IP address strings.

    Isolated in its own function so tests can stub DNS deterministically.
    """
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def validate_target(
    host: str,
    port: int,
    *,
    allow_local: bool = False,
    allowed_hosts: Iterable[str] | None = None,
) -> list[str]:
    """Validate a connection target and return the vetted IP(s) to connect to.

    The returned addresses MUST be the ones the caller actually connects to.
    Resolving here and then connecting to a re-resolved hostname would reopen a
    DNS-rebinding hole (the validated answer and the connected answer could
    differ), so callers pin the connection to these IPs.

    Args:
        host: Target hostname or IP literal.
        port: Target port (used for resolution).
        allow_local: If True, skip the internal-address checks (opt-in).
        allowed_hosts: Optional iterable of permitted hostnames; when provided,
            ``host`` must normalize to one of them.

    Returns:
        The validated IP address strings to connect to, in resolution order.

    Raises:
        SSRFError: If the host is not allow-listed, cannot be resolved, or
            (unless ``allow_local``) resolves to an internal address.
    """
    norm = normalize_host(host)

    if allowed_hosts is not None and norm not in {
        normalize_host(h) for h in allowed_hosts
    }:
        raise SSRFError(f"Host not allowed: {host}")

    # Defense-in-depth: refuse well-known non-protocol service ports regardless
    # of how the host resolves.
    if port in DANGEROUS_PORTS:
        raise SSRFError(f"Blocked dangerous port: {port}")

    # IP-literal host: no DNS needed; the literal IS the connect target.
    try:
        ipaddress.ip_address(norm)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        if not allow_local:
            reason = classify_blocked_ip(norm)
            if reason is not None:
                raise SSRFError(f"Blocked {reason} address: {host}")
        return [norm]

    # Hostname: resolve once and return the vetted addresses so the caller
    # connects to exactly what we validated (defeating DNS rebinding).
    try:
        addresses = await resolve_host(norm, port)
    except OSError as e:  # socket.gaierror is a subclass of OSError
        raise SSRFError(f"Could not resolve host: {host}") from e

    if not addresses:
        raise SSRFError(f"Could not resolve host: {host}")

    if not allow_local:
        for addr in addresses:
            reason = classify_blocked_ip(addr)
            if reason is not None:
                raise SSRFError(f"Blocked {reason} address for {host}: {addr}")

    return addresses
