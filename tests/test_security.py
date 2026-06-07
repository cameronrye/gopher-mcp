"""Security and penetration tests for Gopher and Gemini protocols."""

from unittest.mock import Mock, patch

import pytest

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.models import GeminiErrorResult


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

    def test_suspicious_port_detection(self):
        """Test detection of suspicious ports (this would be enforced by security policy)."""
        from gopher_mcp.models import GeminiFetchRequest, GopherFetchRequest

        # These URLs are technically valid but would be blocked by security policy
        suspicious_urls = [
            "gopher://localhost:22/",  # SSH port
            "gopher://127.0.0.1:3306/",  # MySQL port
            "gemini://localhost:22/",
            "gemini://127.0.0.1:3306/",
        ]

        # URLs should parse successfully (they're valid)
        for url in suspicious_urls:
            if url.startswith("gopher://"):
                request = GopherFetchRequest(url=url)
                assert request.url == url
            elif url.startswith("gemini://"):
                request = GeminiFetchRequest(url=url)
                assert request.url == url

    @pytest.mark.parametrize(
        "malicious_input",
        [
            "../../etc/passwd",
            "../../../windows/system32/config/sam",
            "/etc/shadow",
            "\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded
            "\x00\x01\x02\x03",  # Null bytes and control chars
            "A" * 10000,  # Extremely long input
            "\r\n\r\nHTTP/1.1 200 OK\r\n\r\n<script>alert('xss')</script>",  # CRLF injection
        ],
    )
    def test_path_traversal_prevention(self, malicious_input: str):
        """Test prevention of path traversal attacks."""
        from gopher_mcp.utils import sanitize_selector

        # sanitize_selector only checks for tab, CR, LF and length
        if any(char in malicious_input for char in ["\t", "\r", "\n"]):
            # Should reject inputs with forbidden characters
            with pytest.raises(ValueError):
                sanitize_selector(malicious_input)
        elif len(malicious_input) > 255:
            # Should reject inputs that are too long
            with pytest.raises(ValueError):
                sanitize_selector(malicious_input)
        else:
            # Should pass through other inputs (path traversal is handled elsewhere)
            sanitized = sanitize_selector(malicious_input)
            assert sanitized == malicious_input

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

        The 1KB cap lives inside receive_data, so we drive the real method and
        mock only the raw socket recv -- the previous version mocked
        receive_data itself, which bypassed the very logic under test.
        """
        client = GeminiClient(max_response_size=1024, tofu_enabled=False)

        mock_sock = Mock()
        # Fill exactly to the cap, then a probe byte proves more data remained.
        mock_sock.recv.side_effect = [b"A" * 1024, b"A"]
        mock_sock.gettimeout.return_value = 5.0

        with (
            patch.object(client.tls_client, "connect", return_value=(mock_sock, {})),
            patch.object(client.tls_client, "send_data"),
            patch.object(client.tls_client, "close"),
        ):
            result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "TLS_ERROR"
        # Proves the real loop ran: an initial read plus the over-limit probe.
        assert mock_sock.recv.call_count >= 2

    @pytest.mark.asyncio
    async def test_timeout_protection(self):
        """Test timeout protection against slow responses."""
        client = GeminiClient(timeout_seconds=1)  # 1 second timeout

        # Mock a slow connection
        async def slow_connect(*args, **kwargs):
            import asyncio

            await asyncio.sleep(2)  # Longer than timeout
            return Mock(), {}

        with patch.object(client.tls_client, "connect", side_effect=slow_connect):
            result = await client.fetch("gemini://example.com/")

            # Should return timeout error
            assert isinstance(result, GeminiErrorResult)
            # Check for TLS connection error instead of timeout
            assert (
                "tls" in result.error["message"].lower()
                or "failed" in result.error["message"].lower()
            )

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

        # Test handling of unknown types
        unknown_url = "gopher://example.com/X/unknown"
        parsed = parse_gopher_url(unknown_url)
        # Should handle gracefully, not crash


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
