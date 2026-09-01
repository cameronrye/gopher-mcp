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
import concurrent.futures
import functools
import ipaddress
import queue
import socket
import threading
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")


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


# Name resolution runs in this module's own pool rather than the event loop's
# default executor. The ``asyncio.wait_for`` deadlines the clients wrap around
# validate_target cancel only the awaiting coroutine: the worker thread stays
# parked inside the OS resolver until it gives up by itself, which for a
# tarpitting nameserver is far longer than any configured timeout. A batch
# naming enough such hosts would occupy every default-executor thread, and every
# later request over either protocol would then queue behind them. Confining
# DNS to a pool of its own makes the worst case "resolution for this batch
# queues" instead of "the server stalls".
_DNS_MAX_WORKERS = 8
_DNS_THREAD_PREFIX = "gopher-mcp-dns"


class _DNSExecutor(concurrent.futures.Executor):
    """A bounded pool of daemon threads for blocking name resolution.

    ``ThreadPoolExecutor`` joins its workers at interpreter exit, so a single
    worker parked in ``getaddrinfo`` would hold the whole process open until the
    resolver gave up. Daemon workers are abandoned at exit instead.
    """

    def __init__(self, max_workers: int) -> None:
        """Initialize the pool.

        Args:
            max_workers: Upper bound on threads, and so on concurrently running
                lookups; further submissions queue until a worker frees up.
        """
        self._max_workers = max_workers
        self._work: queue.SimpleQueue[
            tuple[concurrent.futures.Future[Any], Callable[[], Any]]
        ] = queue.SimpleQueue()
        self._threads: list[threading.Thread] = []
        self._idle = threading.Semaphore(0)
        self._grow_lock = threading.Lock()

    def submit(
        self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any
    ) -> concurrent.futures.Future[_T]:
        """Schedule ``fn(*args, **kwargs)`` on a worker and return its future."""
        future: concurrent.futures.Future[_T] = concurrent.futures.Future()
        self._work.put((future, functools.partial(fn, *args, **kwargs)))
        self._grow()
        return future

    def _grow(self) -> None:
        """Start another worker unless one is idle or the pool is at capacity."""
        if self._idle.acquire(blocking=False):
            return
        with self._grow_lock:
            if len(self._threads) >= self._max_workers:
                return
            thread = threading.Thread(
                target=self._run,
                name=f"{_DNS_THREAD_PREFIX}-{len(self._threads)}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def _run(self) -> None:
        """Worker loop: drain the queue forever, relaying results and errors."""
        while True:
            future, call = self._work.get()
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(call())
                except BaseException as exc:
                    # A worker that died on an exception would leave its caller
                    # awaiting a future nobody will ever complete.
                    future.set_exception(exc)
            self._idle.release()


_dns_executor: _DNSExecutor | None = None
_dns_executor_lock = threading.Lock()


def _get_dns_executor() -> _DNSExecutor:
    """Return the process-wide DNS pool, starting it on first use."""
    global _dns_executor
    with _dns_executor_lock:
        if _dns_executor is None:
            _dns_executor = _DNSExecutor(_DNS_MAX_WORKERS)
        return _dns_executor


async def resolve_host(host: str, port: int) -> list[str]:
    """Resolve ``host`` to a list of IP address strings.

    Runs on the dedicated DNS pool (see :class:`_DNSExecutor`) rather than the
    event loop's default executor. Isolated in its own function so tests can
    stub DNS deterministically.
    """
    loop = asyncio.get_running_loop()
    infos = await loop.run_in_executor(
        _get_dns_executor(),
        functools.partial(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM),
    )
    # sockaddr is (address, port) for IPv4 and (address, port, flowinfo,
    # scope_id) for IPv6; the address is element 0 of either.
    return [str(info[4][0]) for info in infos]


async def validate_target(
    host: str,
    port: int,
    *,
    allow_local: bool = False,
    allowed_ports: Iterable[int] | None = None,
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
        allowed_ports: Optional iterable of permitted ports; when provided, only
            these ports are reachable (a positive allowlist that closes the
            arbitrary-port / port-scanning gap left by the DANGEROUS_PORTS
            denylist). When ``None`` the denylist alone applies.

    Returns:
        The validated IP address strings to connect to, in resolution order.

    Raises:
        SSRFError: If the host cannot be resolved, its port is not permitted,
            or (unless ``allow_local``) it resolves to an internal address.

    Note:
        There is deliberately no host allowlist here. The clients apply theirs
        in ``_validate_security``, against a set normalized once at
        construction, and report it as an INVALID_REQUEST rather than an SSRF
        block; a second copy of that check in this module only had tests for
        call sites.
    """
    norm = normalize_host(host)

    # Positive allowlist (opt-in): when configured, only these ports are
    # reachable -- this closes the port-scanning gap the DANGEROUS_PORTS
    # denylist leaves open (any non-listed port on a public host).
    if allowed_ports is not None and port not in set(allowed_ports):
        raise SSRFError(f"Port not allowed: {port}")

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
                # Keep the resolved IP out of the caller-facing error: returning
                # it would let a caller map internal topology by probing which
                # hostnames land in private/reserved space. Log it server-side
                # for operators, surface only the host and category.
                logger.warning(
                    "Blocked target resolving to internal address",
                    host=host,
                    reason=reason,
                    resolved_ip=addr,
                )
                raise SSRFError(f"Blocked {reason} address for {host}")

    return addresses
