"""Integration tests for Gopher and Gemini protocol workflows.

These tests verify end-to-end functionality including:
- Complete fetch workflows for both protocols
- Error handling and recovery
- Concurrency and thread safety
- Network failure scenarios
"""

import asyncio
from unittest.mock import Mock, patch
from typing import Any

import pytest

from gopher_mcp.server import (
    gopher_fetch,
    gemini_fetch,
    get_client_manager,
    ClientManager,
)


def clear_client_manager():
    """Helper to clear client manager singleton."""
    import gopher_mcp.server

    gopher_mcp.server._client_manager = None
    ClientManager._instance = None


@pytest.mark.integration
class TestGopherIntegration:
    """Integration tests for complete Gopher fetch workflow."""

    @pytest.mark.asyncio
    async def test_gopher_menu_fetch_workflow(self):
        """Test complete workflow for fetching a Gopher menu."""
        clear_client_manager()

        # Mock the Pituophis response
        mock_menu_item = Mock()
        mock_menu_item.itype = "0"
        mock_menu_item.text = "Test Document"
        mock_menu_item.path = "/test.txt"
        mock_menu_item.host = "example.com"
        mock_menu_item.port = 70

        mock_response = Mock()
        mock_response.menu.return_value = [mock_menu_item]

        mock_request = Mock()
        mock_request.get.return_value = mock_response

        with (
            patch("pituophis.Request", return_value=mock_request),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            # Mock event loop executor
            asyncio.get_event_loop()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.return_value.run_in_executor.return_value = future

            result = await gopher_fetch("gopher://example.com/1/")

            assert result["kind"] == "menu"
            assert len(result["items"]) == 1
            assert result["items"][0]["title"] == "Test Document"
            assert result["items"][0]["type"] == "0"

    @pytest.mark.asyncio
    async def test_gopher_text_fetch_workflow(self):
        """Test complete workflow for fetching Gopher text."""
        clear_client_manager()

        mock_response = Mock()
        mock_response.text = Mock(return_value="Hello, Gopher!")
        mock_response.binary = b"Hello, Gopher!"

        mock_request = Mock()
        mock_request.get.return_value = mock_response

        with (
            patch("pituophis.Request", return_value=mock_request),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            asyncio.get_event_loop()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.return_value.run_in_executor.return_value = future

            result = await gopher_fetch("gopher://example.com/0/test.txt")

            assert result["kind"] == "text"
            assert result["text"] == "Hello, Gopher!"
            assert result["charset"] == "utf-8"

    @pytest.mark.asyncio
    async def test_gopher_binary_fetch_workflow(self):
        """Test complete workflow for fetching Gopher binary content."""
        clear_client_manager()

        mock_response = Mock()
        mock_response.size = Mock(return_value=1024)
        mock_response.binary = b"x" * 1024

        mock_request = Mock()
        mock_request.get.return_value = mock_response

        with (
            patch("pituophis.Request", return_value=mock_request),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            asyncio.get_event_loop()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.return_value.run_in_executor.return_value = future

            result = await gopher_fetch("gopher://example.com/9/file.bin")

            assert result["kind"] == "binary"
            assert result["bytes"] == 1024

    @pytest.mark.asyncio
    async def test_gopher_caching_workflow(self):
        """Test that caching works across multiple requests."""
        clear_client_manager()

        mock_response = Mock()
        mock_response.text = Mock(return_value="Cached content")
        mock_response.binary = b"Cached content"

        mock_request = Mock()
        mock_request.get.return_value = mock_response

        with (
            patch("pituophis.Request", return_value=mock_request),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            asyncio.get_event_loop()
            future = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.return_value.run_in_executor.return_value = future

            # First fetch - should hit the network
            result1 = await gopher_fetch("gopher://example.com/0/cached.txt")
            assert result1["kind"] == "text"
            assert result1["text"] == "Cached content"

            # Second fetch - should use cache
            result2 = await gopher_fetch("gopher://example.com/0/cached.txt")
            assert result2["kind"] == "text"
            assert result2["text"] == "Cached content"

            # Both results should be identical (from cache)
            assert result1 == result2


@pytest.mark.integration
class TestGeminiIntegration:
    """Integration tests for complete Gemini fetch workflow."""

    @pytest.mark.asyncio
    async def test_gemini_success_fetch_workflow(self):
        """Test complete workflow for fetching Gemini content."""
        clear_client_manager()

        # Mock TLS connection and response
        mock_ssl_sock = Mock()
        mock_connection_info = {
            "peer_cert": Mock(),
            "cipher": ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256),
        }

        raw_response = b"20 text/gemini\r\n# Test Page\nHello, Gemini!"

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data") as mock_send,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_response
            mock_tofu.return_value = None  # No TOFU errors

            result = await gemini_fetch("gemini://example.com/")

            assert result["kind"] == "gemtext"
            assert "document" in result
            assert "raw_content" in result
            mock_connect.assert_called_once()
            mock_send.assert_called_once()
            mock_receive.assert_called_once()

    @pytest.mark.asyncio
    async def test_gemini_redirect_workflow(self):
        """Test handling of Gemini redirects."""
        clear_client_manager()

        mock_ssl_sock = Mock()
        mock_connection_info = {"peer_cert": Mock(), "cipher": ("TLS", "TLSv1.3", 256)}

        # Redirect response
        raw_response = b"30 gemini://example.com/new-location\r\n"

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_response
            mock_tofu.return_value = None

            result = await gemini_fetch("gemini://example.com/old-location")

            assert result["kind"] == "redirect"
            assert result["new_url"] == "gemini://example.com/new-location"

    @pytest.mark.asyncio
    async def test_gemini_error_workflow(self):
        """Test handling of Gemini error responses."""
        clear_client_manager()

        mock_ssl_sock = Mock()
        mock_connection_info = {"peer_cert": Mock(), "cipher": ("TLS", "TLSv1.3", 256)}

        # Error response
        raw_response = b"40 Not Found\r\n"

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_response
            mock_tofu.return_value = None

            result = await gemini_fetch("gemini://example.com/notfound")

            assert result["kind"] == "error"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_gemini_caching_workflow(self):
        """Test that Gemini caching works across multiple requests."""
        clear_client_manager()

        mock_ssl_sock = Mock()
        mock_connection_info = {"peer_cert": Mock(), "cipher": ("TLS", "TLSv1.3", 256)}
        raw_response = b"20 text/gemini\r\n# Cached\nCached content"

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_response
            mock_tofu.return_value = None

            # First fetch
            result1 = await gemini_fetch("gemini://example.com/cached")
            assert result1["kind"] == "gemtext"

            # Second fetch - should use cache
            result2 = await gemini_fetch("gemini://example.com/cached")
            assert result2["kind"] == "gemtext"

            # Verify connection was only made once
            assert mock_connect.call_count == 1


@pytest.mark.integration
class TestErrorPaths:
    """Integration tests for error handling and recovery."""

    @pytest.mark.asyncio
    async def test_gopher_network_timeout(self) -> None:
        """Test handling of network timeout errors."""
        clear_client_manager()

        with patch("pituophis.Request") as mock_request_class:
            mock_request = Mock()
            mock_request.get.side_effect = TimeoutError("Connection timeout")
            mock_request_class.return_value = mock_request

            result = await gopher_fetch("gopher://timeout.example.com/1/")

            assert "error" in result
            assert "timeout" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_gopher_connection_refused(self) -> None:
        """Test handling of connection refused errors."""
        clear_client_manager()

        with patch("pituophis.Request") as mock_request_class:
            mock_request = Mock()
            mock_request.get.side_effect = ConnectionRefusedError("Connection refused")
            mock_request_class.return_value = mock_request

            result = await gopher_fetch("gopher://refused.example.com/1/")

            assert "error" in result
            assert "refused" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_gopher_malformed_response(self) -> None:
        """Test handling of malformed Gopher responses."""
        clear_client_manager()

        mock_response = Mock()
        mock_response.menu.side_effect = ValueError("Malformed menu")

        mock_request = Mock()
        mock_request.get.return_value = mock_response

        with (
            patch("pituophis.Request", return_value=mock_request),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            asyncio.get_event_loop()
            future: asyncio.Future[Any] = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.return_value.run_in_executor.return_value = future

            result = await gopher_fetch("gopher://example.com/1/")

            # Should return empty menu on parse error
            assert result["kind"] == "menu"
            assert result["items"] == []

    @pytest.mark.asyncio
    async def test_gemini_tls_connection_error(self) -> None:
        """Test handling of TLS connection errors."""
        clear_client_manager()

        with patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect:
            from gopher_mcp.gemini_tls import TLSConnectionError

            mock_connect.side_effect = TLSConnectionError("TLS handshake failed")

            result = await gemini_fetch("gemini://tls-error.example.com/")

            assert "error" in result
            assert "tls" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_gemini_tofu_validation_error(self) -> None:
        """Test handling of TOFU certificate validation errors."""
        clear_client_manager()

        mock_ssl_sock = Mock()
        mock_connection_info = {
            "peer_cert": Mock(),
            "cipher": ("TLS", "TLSv1.3", 256),
            "cert_fingerprint": "test_fingerprint_123",
        }

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            from gopher_mcp.tofu import TOFUValidationError

            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = b"20 text/gemini\r\nTest"
            mock_tofu.side_effect = TOFUValidationError("Certificate mismatch")

            result = await gemini_fetch("gemini://tofu-error.example.com/")

            assert "error" in result
            assert "certificate" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_gemini_malformed_response(self) -> None:
        """Test handling of malformed Gemini responses."""
        clear_client_manager()

        mock_ssl_sock = Mock()
        mock_connection_info = {"peer_cert": Mock(), "cipher": ("TLS", "TLSv1.3", 256)}

        # Invalid response (missing CRLF)
        raw_response = b"20 text/gemini"

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_response
            mock_tofu.return_value = None

            result = await gemini_fetch("gemini://example.com/malformed")

            assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_url_formats(self) -> None:
        """Test handling of invalid URL formats."""
        clear_client_manager()

        # Test invalid Gopher URL
        with pytest.raises(Exception):
            await gopher_fetch("http://example.com/")

        # Test invalid Gemini URL
        with pytest.raises(Exception):
            await gemini_fetch("http://example.com/")


@pytest.mark.integration
class TestConcurrency:
    """Integration tests for concurrency and thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_gopher_requests(self) -> None:
        """Test multiple concurrent Gopher requests."""
        clear_client_manager()

        mock_response = Mock()
        mock_response.text = Mock(return_value="Concurrent content")
        mock_response.binary = b"Concurrent content"

        mock_request = Mock()
        mock_request.get.return_value = mock_response

        with (
            patch("pituophis.Request", return_value=mock_request),
            patch("asyncio.get_event_loop") as mock_loop,
        ):
            asyncio.get_event_loop()
            future: asyncio.Future[Any] = asyncio.Future()
            future.set_result(mock_response)
            mock_loop.return_value.run_in_executor.return_value = future

            # Make 10 concurrent requests
            tasks = [
                gopher_fetch(f"gopher://example.com/0/file{i}.txt") for i in range(10)
            ]
            results = await asyncio.gather(*tasks)

            # All should succeed
            assert len(results) == 10
            for result in results:
                assert result["kind"] == "text"
                assert result["text"] == "Concurrent content"

    @pytest.mark.asyncio
    async def test_concurrent_gemini_requests(self) -> None:
        """Test multiple concurrent Gemini requests."""
        clear_client_manager()

        mock_ssl_sock = Mock()
        mock_connection_info = {"peer_cert": Mock(), "cipher": ("TLS", "TLSv1.3", 256)}
        raw_response = b"20 text/gemini\r\n# Concurrent\nContent"

        with (
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_response
            mock_tofu.return_value = None

            # Make 10 concurrent requests
            tasks = [gemini_fetch(f"gemini://example.com/page{i}") for i in range(10)]
            results = await asyncio.gather(*tasks)

            # All should succeed
            assert len(results) == 10
            for result in results:
                assert result["kind"] == "gemtext"

    @pytest.mark.asyncio
    async def test_client_manager_singleton_thread_safety(self) -> None:
        """Test that ClientManager singleton is thread-safe."""
        clear_client_manager()

        # Get client manager multiple times concurrently
        tasks = [get_client_manager() for _ in range(10)]
        managers = await asyncio.gather(*tasks)

        # All should be the same instance
        first_manager = managers[0]
        for manager in managers[1:]:
            assert manager is first_manager

    @pytest.mark.asyncio
    async def test_mixed_protocol_concurrent_requests(self) -> None:
        """Test concurrent requests to both Gopher and Gemini."""
        clear_client_manager()

        # Mock Gopher
        mock_gopher_response = Mock()
        mock_gopher_response.text.return_value = "Gopher content"
        mock_gopher_request = Mock()
        mock_gopher_request.get.return_value = mock_gopher_response

        # Mock Gemini
        mock_ssl_sock = Mock()
        mock_connection_info = {"peer_cert": Mock(), "cipher": ("TLS", "TLSv1.3", 256)}
        raw_gemini_response = b"20 text/gemini\r\n# Gemini\nContent"

        with (
            patch("pituophis.Request", return_value=mock_gopher_request),
            patch("asyncio.get_event_loop") as mock_loop,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.connect") as mock_connect,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.send_data"),
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.receive_data") as mock_receive,
            patch("gopher_mcp.gemini_tls.GeminiTLSClient.close"),
            patch("gopher_mcp.tofu.TOFUManager.validate_certificate") as mock_tofu,
        ):
            asyncio.get_event_loop()
            future: asyncio.Future[Any] = asyncio.Future()
            future.set_result(mock_gopher_response)
            mock_loop.return_value.run_in_executor.return_value = future

            mock_connect.return_value = (mock_ssl_sock, mock_connection_info)
            mock_receive.return_value = raw_gemini_response
            mock_tofu.return_value = None

            # Mix of Gopher and Gemini requests
            tasks = [
                gopher_fetch("gopher://example.com/0/file1.txt"),
                gemini_fetch("gemini://example.com/page1"),
                gopher_fetch("gopher://example.com/0/file2.txt"),
                gemini_fetch("gemini://example.com/page2"),
                gopher_fetch("gopher://example.com/0/file3.txt"),
            ]
            results = await asyncio.gather(*tasks)

            # All should succeed
            assert len(results) == 5
            assert results[0]["kind"] == "text"
            assert results[1]["kind"] == "gemtext"
            assert results[2]["kind"] == "text"
            assert results[3]["kind"] == "gemtext"
            assert results[4]["kind"] == "text"
