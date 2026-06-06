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
from typing import Iterable, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class SSRFError(ValueError):
    """Raised when a target host/address is blocked by the SSRF policy."""


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


def classify_blocked_ip(value: str) -> Optional[str]:
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
    return None


async def resolve_host(host: str, port: int) -> List[str]:
    """Resolve ``host`` to a list of IP address strings.

    Isolated in its own function so tests can stub DNS deterministically.
    """
    loop = asyncio.get_event_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def validate_target(
    host: str,
    port: int,
    *,
    allow_local: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> None:
    """Validate a connection target against the SSRF policy.

    Args:
        host: Target hostname or IP literal.
        port: Target port (used for resolution).
        allow_local: If True, skip the internal-address checks (opt-in).
        allowed_hosts: Optional iterable of permitted hostnames; when provided,
            ``host`` must normalize to one of them.

    Raises:
        SSRFError: If the host is not allow-listed, cannot be resolved, or
            (unless ``allow_local``) resolves to an internal address.
    """
    norm = normalize_host(host)

    if allowed_hosts is not None:
        if norm not in {normalize_host(h) for h in allowed_hosts}:
            raise SSRFError(f"Host not allowed: {host}")

    if allow_local:
        return

    # IP-literal host: classify directly, no DNS needed.
    try:
        ipaddress.ip_address(norm)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        reason = classify_blocked_ip(norm)
        if reason is not None:
            raise SSRFError(f"Blocked {reason} address: {host}")
        return

    # Hostname: resolve and validate every returned address (defeats DNS
    # rebinding to an internal IP for at least the connection we validate).
    # Resolve the normalized host so the literal check and the resolution use
    # the same value.
    try:
        addresses = await resolve_host(norm, port)
    except OSError as e:  # socket.gaierror is a subclass of OSError
        raise SSRFError(f"Could not resolve host: {host}") from e

    if not addresses:
        raise SSRFError(f"Could not resolve host: {host}")

    for addr in addresses:
        reason = classify_blocked_ip(addr)
        if reason is not None:
            raise SSRFError(f"Blocked {reason} address for {host}: {addr}")
