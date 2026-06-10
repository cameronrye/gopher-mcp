"""Tests for the SSRF protection layer.

The ``_stub_dns`` autouse fixture in conftest resolves hostnames offline:
``localhost`` and ``*.internal`` map to internal addresses, ``blocked.example``
to the cloud-metadata IP, and everything else to a public address.
"""

import pytest

from gopher_mcp.ssrf import (
    SSRFError,
    classify_blocked_ip,
    normalize_host,
    validate_target,
)


class TestNormalizeHost:
    def test_lowercases(self):
        assert normalize_host("Example.COM") == "example.com"

    def test_strips_trailing_dot(self):
        assert normalize_host("example.com.") == "example.com"

    def test_strips_ipv6_brackets(self):
        assert normalize_host("[::1]") == "::1"


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

    async def test_allowlist_rejects_other_hosts(self):
        with pytest.raises(SSRFError, match="not allowed"):
            await validate_target("example.com", 70, allowed_hosts=["other.com"])

    async def test_allowlist_normalizes(self):
        # Trailing dot / case must still match the allowlist entry.
        await validate_target("Example.com.", 70, allowed_hosts=["example.com"])

    async def test_resolution_failure_raises(self, monkeypatch):
        async def boom(host, port):
            raise OSError("name resolution failed")

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", boom)
        with pytest.raises(SSRFError, match="Could not resolve"):
            await validate_target("nope.example", 70)


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
