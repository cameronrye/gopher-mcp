"""Tests for the SSRF protection layer.

The ``_stub_dns`` autouse fixture in conftest resolves hostnames offline:
``localhost`` and ``*.internal`` map to internal addresses, ``blocked.example``
to the cloud-metadata IP, and everything else to a public address.
"""

import asyncio
import socket
import threading
import time

import pytest

from gopher_mcp import ssrf
from gopher_mcp.ssrf import (
    HostResolutionError,
    SSRFError,
    classify_blocked_ip,
    normalize_host,
    resolve_host,
    validate_target,
)

# ``_stub_dns`` rebinds ``gopher_mcp.ssrf.resolve_host``; this module-level name
# was bound at import time and so still refers to the real implementation, which
# is what TestResolveHost needs to exercise.
_real_resolve_host = resolve_host


class TestNormalizeHost:
    def test_lowercases(self):
        assert normalize_host("Example.COM") == "example.com"

    def test_strips_trailing_dot(self):
        assert normalize_host("example.com.") == "example.com"

    def test_strips_ipv6_brackets(self):
        assert normalize_host("[::1]") == "::1"

    @pytest.mark.parametrize(
        "host",
        ["example.com", "sub.example.com", "192.0.2.1", "xn--exmple-cua.org"],
    )
    def test_ascii_hosts_are_returned_unchanged(self, host):
        assert normalize_host(host) == host

    @pytest.mark.parametrize(
        "spelling",
        [
            "exämple.org",  # U-label
            "EXÄMPLE.ORG.",  # U-label, upper case, trailing dot
            "xn--exmple-cua.org",  # A-label
            "[xn--exmple-cua.org]",  # bracketed
        ],
    )
    def test_idn_spellings_collapse_to_one_a_label(self, spelling):
        """Every key derived from a host -- the TOFU pin, the client-certificate
        scope, the rate-limit bucket, the robots policy cache -- must land on
        one entry, because ``getaddrinfo`` and ``ssl`` apply this same codec and
        reach one server. Without it a pinned capsule visited by its Unicode
        spelling gets a fresh trust-on-first-use instead of CERTIFICATE_CHANGED.
        """
        assert normalize_host(spelling) == "xn--exmple-cua.org"

    @pytest.mark.parametrize(
        "host",
        [
            "a\u0080b.org",  # nameprep-prohibited C1 control
            "ä" * 60 + ".org",  # label too long once punycoded
        ],
    )
    def test_unencodable_unicode_host_is_refused(self, host):
        """Fail closed: returning the raw U-label would reopen exactly the split
        the IDNA step closes, and there is no other canonical form to key on."""
        with pytest.raises(SSRFError, match="IDNA"):
            normalize_host(host)

    @pytest.mark.parametrize("host", ["a..b", "a" * 64 + ".com"])
    def test_ascii_hosts_the_codec_rejects_still_pass_through(self, host):
        """``encodings.idna`` refuses an empty or over-long ASCII label. Those
        spellings belong in front of the SSRF and allowlist checks unaltered
        rather than raising out of a normalizer."""
        assert normalize_host(host) == host


class TestClassifyBlockedIp:
    @pytest.mark.parametrize(
        ("ip", "reason"),
        [
            ("127.0.0.1", "loopback"),
            ("::1", "loopback"),
            ("10.0.0.5", "private"),
            ("192.168.1.1", "private"),
            ("172.16.0.1", "private"),
            ("169.254.169.254", "link-local"),  # cloud metadata
            ("0.0.0.0", "unspecified"),
            ("224.0.0.1", "multicast"),
            ("::ffff:127.0.0.1", "loopback"),  # IPv4-mapped IPv6
            ("100.64.0.1", "non-global"),  # CGNAT / RFC 6598
            ("100.127.255.255", "non-global"),  # CGNAT upper bound
            ("fec0::1", "site-local"),  # deprecated IPv6 site-local
            ("240.0.0.1", "private"),  # class E; CPython files 240/4 as private
            # IPv6 ranges IANA has never allocated. CPython reports these as
            # is_global=True, so only the explicit is_reserved check stops them.
            ("200::1", "reserved"),
            ("4000::1", "reserved"),
            ("fe00::1", "reserved"),
        ],
    )
    def test_blocked_ips(self, ip, reason):
        assert classify_blocked_ip(ip) == reason

    @pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "1.1.1.1"])
    def test_public_ips_allowed(self, ip):
        assert classify_blocked_ip(ip) is None

    def test_hostname_is_not_a_literal(self):
        assert classify_blocked_ip("example.com") is None


@pytest.mark.asyncio
class TestValidateTarget:
    async def test_public_host_allowed(self):
        await validate_target("example.com", 70)  # resolves public via stub

    async def test_public_ip_literal_allowed(self):
        await validate_target("8.8.8.8", 70)

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "::1",
            "10.0.0.5",
            "169.254.169.254",
            "[::ffff:127.0.0.1]",
            "100.64.0.1",  # CGNAT (RFC 6598) — used for internal infra
            "[fec0::1]",  # deprecated IPv6 site-local
        ],
    )
    async def test_internal_ip_literal_blocked(self, host):
        with pytest.raises(SSRFError, match="Blocked"):
            await validate_target(host, 70)

    @pytest.mark.parametrize("host", ["localhost", "db.internal", "blocked.example"])
    async def test_hostname_resolving_internal_blocked(self, host):
        with pytest.raises(SSRFError, match="Blocked"):
            await validate_target(host, 1965)

    async def test_resolved_internal_ip_not_leaked_in_error(self):
        """The error returned to the caller must name the host and category but
        NOT the resolved internal IP -- otherwise a caller can map internal
        network topology by probing which hostnames resolve to private space.
        The stub resolves ``*.internal`` to 10.0.0.5."""
        with pytest.raises(SSRFError) as exc_info:
            await validate_target("db.internal", 1965)
        message = str(exc_info.value)
        assert "10.0.0.5" not in message
        assert "db.internal" in message
        assert "private" in message

    async def test_allow_local_bypasses_check(self):
        # No exception even though localhost resolves to loopback.
        await validate_target("localhost", 70, allow_local=True)
        await validate_target("127.0.0.1", 70, allow_local=True)

    async def test_resolution_failure_raises(self, monkeypatch):
        async def boom(host, port):
            raise OSError("name resolution failed")

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", boom)
        with pytest.raises(SSRFError, match="Could not resolve"):
            await validate_target("nope.example", 70)

    async def test_empty_resolution_raises(self, monkeypatch):
        """A resolver that answers with no addresses must not be treated as a
        successful lookup: returning an empty list would hand the caller nothing
        to connect to, and every address check below would vacuously pass."""

        async def nothing(host, port):
            return []

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", nothing)
        with pytest.raises(SSRFError, match="Could not resolve"):
            await validate_target("nope.example", 70)

    async def test_resolution_failure_is_its_own_exception_type(self, monkeypatch):
        """A name that does not resolve was never *refused* by the SSRF policy:
        nothing was evaluated, because there was no address to evaluate. The
        clients key their error code off this, so the type must stay distinct --
        while remaining an SSRFError so every existing handler still catches it.
        """

        async def boom(host, port):
            raise OSError("name resolution failed")

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", boom)
        with pytest.raises(HostResolutionError):
            await validate_target("nope.example", 70)
        assert issubclass(HostResolutionError, SSRFError)

    async def test_a_real_policy_refusal_is_not_a_resolution_error(self):
        """The inverse: a genuine block must NOT be reported as a DNS problem."""
        with pytest.raises(SSRFError) as blocked:
            await validate_target("127.0.0.1", 70)
        assert not isinstance(blocked.value, HostResolutionError)

    async def test_reserved_address_from_dns_is_blocked(self, monkeypatch):
        """An unallocated IPv6 range reports is_global=True, so it reaches the
        connect path unless the reserved check catches it."""

        async def reserved(host, port):
            return ["4000::1"]

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", reserved)
        with pytest.raises(SSRFError, match="Blocked reserved address"):
            await validate_target("sneaky.example", 1965)


@pytest.mark.asyncio
class TestResolveHost:
    """The real ``resolve_host``, which the autouse ``_stub_dns`` fixture
    replaces everywhere else -- so its call shape and result handling would
    otherwise run in no test at all."""

    async def test_shapes_getaddrinfo_results(self, monkeypatch):
        """Only stream sockets are asked for, and the address is element 0 of
        each sockaddr (a 2-tuple for IPv4, a 4-tuple for IPv6)."""
        seen: dict[str, object] = {}

        def fake_getaddrinfo(host, port, *args, **kwargs):
            seen["host"] = host
            seen["port"] = port
            seen["type"] = kwargs.get("type")
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("2606:2800::1", port, 0, 0),
                ),
            ]

        monkeypatch.setattr(ssrf.socket, "getaddrinfo", fake_getaddrinfo)
        addresses = await _real_resolve_host("example.com", 1965)

        assert addresses == ["93.184.216.34", "2606:2800::1"]
        assert seen == {"host": "example.com", "port": 1965, "type": socket.SOCK_STREAM}

    async def test_resolver_error_propagates_as_oserror(self, monkeypatch):
        """validate_target maps OSError to SSRFError, so it must reach it."""

        def boom(host, port, *args, **kwargs):
            raise socket.gaierror("nodename nor servname provided")

        monkeypatch.setattr(ssrf.socket, "getaddrinfo", boom)
        with pytest.raises(OSError):
            await _real_resolve_host("nope.example", 70)


@pytest.mark.asyncio
class TestDNSExecutorIsolation:
    """DNS must not run on the event loop's default executor.

    ``asyncio.wait_for`` cancels only the awaiting coroutine; the worker thread
    stays parked inside the OS resolver. A batch naming hosts whose nameservers
    tarpit queries would therefore occupy every default-executor thread, and
    every later request over either protocol would queue behind them long past
    its own deadline.
    """

    async def test_lookup_runs_on_the_dedicated_pool(self, monkeypatch):
        threads: list[str] = []

        def fake_getaddrinfo(host, port, *args, **kwargs):
            threads.append(threading.current_thread().name)
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ]

        monkeypatch.setattr(ssrf.socket, "getaddrinfo", fake_getaddrinfo)
        await _real_resolve_host("example.com", 70)

        assert threads
        assert all(name.startswith(ssrf._DNS_THREAD_PREFIX) for name in threads)

    async def test_concurrent_lookups_are_capped(self, monkeypatch):
        """Past the cap, lookups queue instead of claiming another thread."""
        release = threading.Event()
        lock = threading.Lock()
        inflight = 0
        peak = 0

        def stalling_getaddrinfo(host, port, *args, **kwargs):
            nonlocal inflight, peak
            with lock:
                inflight += 1
                peak = max(peak, inflight)
            release.wait(10.0)
            with lock:
                inflight -= 1
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ]

        monkeypatch.setattr(ssrf.socket, "getaddrinfo", stalling_getaddrinfo)
        tasks = [
            asyncio.create_task(_real_resolve_host(f"h{i}.example", 70))
            for i in range(ssrf._DNS_MAX_WORKERS * 3)
        ]
        try:
            deadline = time.monotonic() + 10.0
            while peak < ssrf._DNS_MAX_WORKERS and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            # Give any thread the pool should not have started time to appear.
            await asyncio.sleep(0.25)
            assert peak == ssrf._DNS_MAX_WORKERS
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)


@pytest.mark.asyncio
class TestValidateTargetReturnsAddresses:
    """validate_target returns the vetted IPs to pin the connection to."""

    async def test_returns_resolved_addresses_for_hostname(self):
        addrs = await validate_target("example.com", 70)
        assert addrs == ["93.184.216.34"]

    async def test_returns_ip_literal_unchanged(self):
        addrs = await validate_target("8.8.8.8", 70)
        assert addrs == ["8.8.8.8"]

    async def test_allow_local_still_returns_addresses(self):
        addrs = await validate_target("localhost", 70, allow_local=True)
        assert addrs == ["127.0.0.1"]


@pytest.mark.asyncio
class TestValidateTargetPortPolicy:
    """A dangerous-port denylist provides defense-in-depth against using the
    fetcher as a cross-protocol probe."""

    async def test_dangerous_port_is_blocked(self):
        with pytest.raises(SSRFError, match="port"):
            await validate_target("example.com", 6379)  # Redis

    async def test_protocol_default_ports_allowed(self):
        await validate_target("example.com", 70)  # Gopher
        await validate_target("example.com", 1965)  # Gemini


class TestPortAllowlist:
    """An optional positive port allowlist closes the port-scanning gap: the
    DANGEROUS_PORTS denylist leaves every non-listed port on a public host
    reachable, so operators can opt into allowing only specific ports.
    """

    @pytest.mark.asyncio
    async def test_non_allowed_port_rejected(self):
        with pytest.raises(SSRFError, match="Port not allowed"):
            await validate_target("8.8.8.8", 8080, allowed_ports=[70, 1965])

    @pytest.mark.asyncio
    async def test_allowed_port_passes(self):
        result = await validate_target("8.8.8.8", 1965, allowed_ports=[70, 1965])
        assert result == ["8.8.8.8"]

    @pytest.mark.asyncio
    async def test_none_allows_any_non_dangerous_port(self):
        # Default (no allowlist): an arbitrary non-dangerous port is allowed.
        await validate_target("8.8.8.8", 8080)
