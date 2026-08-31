"""Security and penetration tests for Gopher and Gemini protocols."""

from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import quote

import pytest

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.models import ErrorResult, GeminiErrorResult


class TestInputSanitization:
    """Test input sanitization and validation."""

    @pytest.mark.parametrize(
        "malicious_url",
        [
            "javascript:alert('xss')",
            "data:text/html,<script>alert('xss')</script>",
            "file:///etc/passwd",
            "ftp://malicious.com/",
            "http://malicious.com/",
            "https://malicious.com/",
        ],
    )
    def test_malicious_url_rejection(self, malicious_url: str):
        """Test that malicious URLs are rejected."""
        from gopher_mcp.models import GeminiFetchRequest, GopherFetchRequest

        # These should all be rejected due to wrong scheme
        with pytest.raises(ValueError):
            GopherFetchRequest(url=malicious_url)

        with pytest.raises(ValueError):
            GeminiFetchRequest(url=malicious_url)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "selector",
        [
            "%0d%0a%0d%0aHTTP/1.1%20200%20OK",
            "sel%09a%09b",
            "sel%0dmore",
            "sel%0amore",
        ],
    )
    async def test_request_smuggling_characters_are_rejected(self, selector: str):
        """RFC 1436 frames a request as one CRLF-terminated, tab-delimited line.

        A selector carrying CR/LF could forge a second request on the wire, and a
        TAB beyond the one that separates a type-7 search could forge an extra
        field, so the client must refuse them before sending.
        """
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, timeout_seconds=1
        )
        result = await client.fetch(f"gopher://example.com/0/{selector}")
        await client.close()

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_oversized_selector_is_rejected(self):
        """The configured selector cap is a hard boundary, not an approximate one."""
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(
            cache_enabled=False,
            requests_per_minute=0,
            timeout_seconds=1,
            max_selector_length=255,
        )
        result = await client.fetch("gopher://example.com/0/" + "A" * 256)
        await client.close()

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "INVALID_REQUEST"
        assert "too long" in result.error["message"].lower()

    @pytest.mark.parametrize(
        "url",
        [
            "gopher://example.com/0/a%00b",  # NUL
            "gopher://example.com/0/a%0d%0afoo",  # CRLF injection
            "gopher://example.com/0/a%09bar%09baz",  # extra tab-delimited field
            "gopher://example.com/0/a%1b[2J",  # terminal escape
        ],
    )
    def test_control_characters_cannot_enter_a_selector_via_the_url(self, url: str):
        """Percent-encoding is how a control character would reach the wire.

        The URL parser is the layer that decodes, so it is the layer that has to
        refuse -- by the time a selector exists the encoding is gone.
        """
        from gopher_mcp.utils import parse_gopher_url

        with pytest.raises(ValueError, match="control characters"):
            parse_gopher_url(url)

    @pytest.mark.parametrize(
        "traversal",
        [
            "../../etc/passwd",
            "../../../windows/system32/config/sam",
            "/etc/shadow",
            "\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ],
    )
    def test_traversal_selectors_are_forwarded_verbatim(self, traversal: str):
        """A Gopher selector is an opaque server-side token, not a path.

        Containment is the remote server's job, and rewriting a selector would
        change which resource the operator's server is asked for. Pinned so that
        a change to that policy has to be a deliberate one -- the robots gate,
        which *does* resolve dot segments, is tested in test_robots.py.
        """
        from gopher_mcp.utils import parse_gopher_url

        parsed = parse_gopher_url(f"gopher://example.com/0/{quote(traversal)}")

        assert parsed.selector == f"/{traversal}"

    def test_url_length_limits(self):
        """Test URL length validation."""
        from gopher_mcp.models import GeminiFetchRequest, GopherFetchRequest

        # Test extremely long URLs - only Gemini has length limits (1024 bytes)
        long_path = "A" * 2000
        long_gopher_url = f"gopher://example.com/{long_path}"
        long_gemini_url = f"gemini://example.com/{long_path}"

        # Gopher doesn't have URL length limits in the model
        gopher_request = GopherFetchRequest(url=long_gopher_url)
        assert gopher_request.url == long_gopher_url

        # Gemini has 1024 byte limit
        with pytest.raises(ValueError, match="URL must not exceed 1024 bytes"):
            GeminiFetchRequest(url=long_gemini_url)


class TestResourceExhaustion:
    """Test protection against resource exhaustion attacks."""

    @pytest.mark.asyncio
    async def test_response_size_limits(self):
        """Oversized responses are rejected by the REAL receive_data cap.

        The 1KB cap lives inside receive_data, so we drive the real method over a
        real asyncio stream fed past the cap -- the previous version mocked
        receive_data itself, which bypassed the very logic under test.
        """
        import asyncio

        from gopher_mcp.gemini_tls import TLSConnection

        client = GeminiClient(max_response_size=1024, tofu_enabled=False)

        reader = asyncio.StreamReader()
        reader.feed_data(b"A" * 2048)  # exceeds the 1 KB cap
        reader.feed_eof()
        conn = TLSConnection(reader=reader, writer=Mock())

        with (
            patch.object(client.tls_client, "connect", return_value=(conn, {})),
            patch.object(client.tls_client, "send_data"),
            patch.object(client.tls_client, "close"),
        ):
            result = await client.fetch("gemini://example.com/")

        # The real receive_data loop hit the cap and rejected the response.
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "TLS_ERROR"

    @pytest.mark.asyncio
    async def test_timeout_protection(self):
        """A response slower than the deadline is bounded, not awaited forever.

        TOFU is disabled here so the request reaches the read phase; the slow
        ``receive_data`` is wrapped in the client's overall ``wait_for`` deadline,
        which must fire and surface a timeout error rather than hang.
        """
        import asyncio

        client = GeminiClient(
            timeout_seconds=0.1,
            tofu_enabled=False,
            client_certs_enabled=False,
        )

        async def slow_receive(*args, **kwargs):
            await asyncio.sleep(2)  # far longer than the 0.1s deadline
            return b"20 text/gemini\r\nhi"

        client.tls_client.connect = AsyncMock(  # type: ignore[method-assign]
            return_value=(Mock(), {"cert_fingerprint": "x"})
        )
        client.tls_client.send_data = AsyncMock()  # type: ignore[method-assign]
        client.tls_client.receive_data = slow_receive  # type: ignore[method-assign]
        client.tls_client.close = AsyncMock()  # type: ignore[method-assign]

        result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "FETCH_ERROR"
        assert "timed out" in result.error["message"].lower()

    def test_memory_exhaustion_protection(self):
        """Test protection against memory exhaustion."""
        # Test with many cache entries
        client = GeminiClient(max_cache_entries=10)

        # Fill cache beyond limit
        from gopher_mcp.models import GeminiMimeType, GeminiSuccessResult

        for i in range(20):
            url = f"gemini://example{i}.com/"
            # Create a proper response object instead of Mock
            mock_response = GeminiSuccessResult(
                mimeType=GeminiMimeType(type="text", subtype="plain"),
                content="test content",
                size=12,
            )
            client._cache_response(url, mock_response)

        # Cache should not exceed limit
        assert len(client._cache) <= 10


class TestProtocolCompliance:
    """Test protocol compliance and security."""

    def test_gemini_status_code_validation(self):
        """Test Gemini status code validation."""
        from gopher_mcp.utils import parse_gemini_response

        # Test valid status codes
        valid_responses = [
            b"20 text/gemini\r\n# Test content",
            b"30 gemini://example.com/redirect\r\n",
            b"40 Temporary failure\r\n",
            b"50 Permanent failure\r\n",
            b"60 Client certificate required\r\n",
        ]

        for response in valid_responses:
            parsed = parse_gemini_response(response)
            # Use status.value to get the integer value
            status_value = (
                parsed.status.value
                if hasattr(parsed.status, "value")
                else parsed.status
            )
            assert 10 <= status_value <= 69

        # Test invalid status codes
        invalid_responses = [
            b"99 Invalid status\r\n",
            b"00 Invalid status\r\n",
            b"abc Invalid status\r\n",
        ]

        for response in invalid_responses:
            with pytest.raises(ValueError):
                parse_gemini_response(response)

    def test_gopher_type_validation(self):
        """Test Gopher type validation."""
        from gopher_mcp.utils import parse_gopher_url

        # Test valid Gopher types
        valid_urls = [
            "gopher://example.com/0/file.txt",
            "gopher://example.com/1/menu",
            "gopher://example.com/7/search",
        ]

        for url in valid_urls:
            parsed = parse_gopher_url(url)
            assert parsed.gopher_type in "0179gI"

    def test_unknown_gopher_type_is_preserved_not_guessed(self):
        """RFC 1436 leaves the type space open, so an unrecognised type is
        carried through as-is rather than rejected or rewritten."""
        from gopher_mcp.utils import parse_gopher_url

        parsed = parse_gopher_url("gopher://example.com/X/unknown")
        assert parsed.gopher_type == "X"
        assert parsed.selector == "/unknown"

    @pytest.mark.asyncio
    async def test_unknown_gopher_type_does_not_bypass_the_ssrf_guard(self):
        """An unrecognised type takes the generic content path, which must still
        run every check -- an unknown type is exactly the kind of input an
        attacker would use to look for an unguarded branch."""
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, timeout_seconds=1
        )
        result = await client.fetch("gopher://localhost/X/unknown")
        await client.close()

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED"

    @pytest.mark.asyncio
    async def test_interactive_gopher_type_opens_no_connection(self):
        """Telnet/tn3270/CSO items have no Gopher-fetchable body; the client
        must answer from the type alone rather than dialling the host."""
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, timeout_seconds=1
        )
        with patch("gopher_mcp.gopher_client.validate_target") as validate:
            result = await client.fetch("gopher://example.com/8/login")
        await client.close()

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "NOT_FETCHABLE"
        validate.assert_not_called()


class TestErrorHandling:
    """Test secure error handling."""

    @pytest.mark.asyncio
    async def test_error_information_leakage(self):
        """Test that errors don't leak sensitive information."""
        client = GeminiClient()

        # Mock various error conditions
        with patch.object(
            client.tls_client,
            "connect",
            side_effect=Exception("Internal error with /etc/passwd"),
        ):
            result = await client.fetch("gemini://example.com/")

            # The sanitized client-facing message must not leak the raw
            # exception text or filesystem paths.
            assert isinstance(result, GeminiErrorResult)
            error_msg = result.error["message"]
            assert "/etc/passwd" not in error_msg
            assert "Internal error" not in error_msg
            assert result.error["code"] == "FETCH_ERROR"

    @pytest.mark.asyncio
    async def test_stack_trace_sanitization(self):
        """Error responses must not expose exception types or internal text."""
        client = GeminiClient()

        with patch.object(
            client.tls_client,
            "connect",
            side_effect=RuntimeError("boom in module foo at line 42"),
        ):
            result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        msg = result.error["message"]
        assert "RuntimeError" not in msg
        assert "boom" not in msg
        assert "Traceback" not in msg
        assert result.error["code"] == "FETCH_ERROR"


@pytest.mark.slow
class TestSecurityIntegration:
    """Integration tests for security features."""

    @pytest.mark.asyncio
    async def test_end_to_end_security_validation(self):
        """Test complete security validation flow."""
        client = GeminiClient(
            allowed_hosts=["example.com"],
            timeout_seconds=5,
            max_response_size=1024,
            tofu_enabled=False,
        )

        # Test that all security measures work together
        with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
            with patch.object(client.tls_client, "send_data"):
                with patch.object(
                    client.tls_client,
                    "receive_data",
                    return_value=b"20 text/plain\r\nTest content",
                ):
                    with patch.object(client.tls_client, "close"):
                        result = await client.fetch("gemini://example.com/")

                        # Should succeed for allowed host
                        assert not isinstance(result, GeminiErrorResult)


@pytest.mark.asyncio
class TestSSRFEndToEnd:
    """The SSRF guard must block internal targets end-to-end through the
    public tool surface, returning a sanitized BLOCKED error code.

    The autouse ``_stub_dns`` fixture resolves ``localhost`` -> 127.0.0.1 and
    ``blocked.example`` -> 169.254.169.254 (cloud metadata), both blocked.
    """

    async def test_gopher_fetch_blocks_loopback(self):
        from gopher_mcp.server import gopher_fetch

        result = await gopher_fetch("gopher://localhost/1/")
        assert result["error"]["code"] == "BLOCKED"

    async def test_gemini_fetch_blocks_cloud_metadata(self):
        from gopher_mcp.server import gemini_fetch

        result = await gemini_fetch("gemini://blocked.example/")
        assert result["error"]["code"] == "BLOCKED"

    async def test_allow_local_hosts_permits_loopback(self):
        # With the opt-in, the SSRF guard no longer blocks; the request fails
        # later at connect time instead (proving the block was lifted).
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(allow_local_hosts=True, timeout_seconds=1)
        result = await client.fetch("gopher://localhost/1/")
        assert result.error["code"] != "BLOCKED"


@pytest.mark.asyncio
class TestDangerousPortPolicy:
    """A suspicious port must be *refused*, not merely parsed.

    The test this replaces asserted only that such URLs parse, so it passed
    whatever the port policy did -- including doing nothing at all.
    """

    @pytest.mark.parametrize(
        ("url", "port"),
        [
            ("gopher://localhost:22/1/", 22),  # SSH
            ("gopher://127.0.0.1:3306/1/", 3306),  # MySQL
            ("gopher://example.com:6379/1/", 6379),  # Redis on a public host
        ],
    )
    async def test_gopher_dangerous_port_is_blocked(self, url: str, port: int):
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, timeout_seconds=1
        )
        result = await client.fetch(url)
        await client.close()

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED"
        assert str(port) in result.error["message"]

    @pytest.mark.parametrize(
        ("url", "port"),
        [
            ("gemini://localhost:22/", 22),
            ("gemini://127.0.0.1:3306/", 3306),
            ("gemini://example.com:11211/", 11211),  # Memcached on a public host
        ],
    )
    async def test_gemini_dangerous_port_is_blocked(self, url: str, port: int):
        client = GeminiClient(
            cache_enabled=False,
            requests_per_minute=0,
            timeout_seconds=1,
            tofu_enabled=False,
        )
        result = await client.fetch(url)
        await client.close()

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "BLOCKED"
        assert str(port) in result.error["message"]

    async def test_port_allowlist_closes_the_scanning_gap(self):
        """The denylist leaves every unlisted port on a public host reachable,
        so an operator can opt into a positive allowlist instead."""
        from gopher_mcp.gopher_client import GopherClient

        client = GopherClient(
            cache_enabled=False,
            requests_per_minute=0,
            timeout_seconds=1,
            allowed_ports=[70],
        )
        result = await client.fetch("gopher://example.com:8080/1/")
        await client.close()

        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED"
        assert "Port not allowed" in result.error["message"]


@pytest.mark.asyncio
class TestTOFUFailClosed:
    """A non-raising False from TOFU validation must still reject (fail closed)."""

    async def test_invalid_tofu_result_is_rejected(self):
        client = GeminiClient(tofu_enabled=True)
        mock_sock = Mock()
        conn_info = {"cert_fingerprint": "abc123"}

        with (
            patch.object(
                client.tls_client, "connect", return_value=(mock_sock, conn_info)
            ),
            patch.object(client.tls_client, "send_data"),
            patch.object(client.tls_client, "close"),
            patch.object(
                client.tofu_manager,
                "validate_certificate",
                return_value=(False, "fabricated soft failure"),
            ),
        ):
            result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "CERTIFICATE_CHANGED"
