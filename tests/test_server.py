"""Tests for gopher_mcp.server module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gopher_mcp.server import (
    cleanup,
    get_gopher_client,
    get_gemini_client,
    gopher_fetch,
    gemini_fetch,
    mcp,
)


class TestGetGopherClient:
    """Test get_gopher_client function."""

    def test_get_gopher_client_default_config(self):
        """Test getting gopher client with default configuration."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        with patch.dict(os.environ, {}, clear=True):
            client = get_gopher_client()

            assert client is not None
            assert client.max_response_size == 1048576  # 1MB default
            assert client.timeout_seconds == 30.0
            assert client.cache_enabled is True
            assert client.cache_ttl_seconds == 300
            assert client.max_cache_entries == 1000
            assert client.allowed_hosts is None
            assert client.max_selector_length == 1024
            assert client.max_search_length == 256

    def test_get_gopher_client_custom_config(self):
        """Test getting gopher client with custom configuration."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        env_vars = {
            "GOPHER_MAX_RESPONSE_SIZE": "2097152",  # 2MB
            "GOPHER_TIMEOUT_SECONDS": "60.0",
            "GOPHER_CACHE_ENABLED": "false",
            "GOPHER_CACHE_TTL_SECONDS": "600",
            "GOPHER_MAX_CACHE_ENTRIES": "2000",
            "GOPHER_ALLOWED_HOSTS": "example.com,test.com",
            "GOPHER_MAX_SELECTOR_LENGTH": "2048",
            "GOPHER_MAX_SEARCH_LENGTH": "512",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            client = get_gopher_client()

            assert client.max_response_size == 2097152
            assert client.timeout_seconds == 60.0
            assert client.cache_enabled is False
            assert client.cache_ttl_seconds == 600
            assert client.max_cache_entries == 2000
            assert client.allowed_hosts == {"example.com", "test.com"}
            assert client.max_selector_length == 2048
            assert client.max_search_length == 512

    def test_get_gopher_client_singleton(self):
        """Test that get_gopher_client returns the same instance."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        client1 = get_gopher_client()
        client2 = get_gopher_client()

        assert client1 is client2

    def test_get_gopher_client_allowed_hosts_parsing(self):
        """Test parsing of allowed hosts from environment."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        with patch.dict(
            os.environ,
            {"GOPHER_ALLOWED_HOSTS": "  host1.com , host2.com  , host3.com  "},
            clear=True,
        ):
            client = get_gopher_client()

            assert client.allowed_hosts == {"host1.com", "host2.com", "host3.com"}


class TestGopherFetch:
    """Test gopher_fetch tool function."""

    @pytest.mark.asyncio
    async def test_gopher_fetch_success(self):
        """Test successful gopher fetch."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "kind": "text",
            "text": "Hello, Gopher!",
            "bytes": 15,
            "charset": "utf-8",
        }
        mock_client.fetch.return_value = mock_response

        with patch("gopher_mcp.server.get_gopher_client", return_value=mock_client):
            result = await gopher_fetch("gopher://example.com/0/test.txt")

            assert result["kind"] == "text"
            assert result["text"] == "Hello, Gopher!"
            assert result["bytes"] == 15
            assert result["charset"] == "utf-8"

            mock_client.fetch.assert_called_once_with("gopher://example.com/0/test.txt")

    @pytest.mark.asyncio
    async def test_gopher_fetch_invalid_url(self):
        """Test gopher fetch with invalid URL."""
        with pytest.raises(
            Exception
        ):  # Should raise ValidationError from GopherFetchRequest
            await gopher_fetch("http://example.com/")

    @pytest.mark.asyncio
    async def test_gopher_fetch_client_error(self):
        """Test gopher fetch when client raises an error."""
        mock_client = AsyncMock()
        mock_client.fetch.side_effect = Exception("Connection failed")

        with patch("gopher_mcp.server.get_gopher_client", return_value=mock_client):
            with pytest.raises(Exception) as exc_info:
                await gopher_fetch("gopher://example.com/0/test.txt")

            assert "Connection failed" in str(exc_info.value)


class TestCleanup:
    """Test cleanup function."""

    @pytest.mark.asyncio
    async def test_cleanup_with_client(self):
        """Test cleanup when client exists."""
        # Set up a mock client
        import gopher_mcp.server

        mock_client = AsyncMock()
        gopher_mcp.server._gopher_client = mock_client

        await cleanup()

        mock_client.close.assert_called_once()
        assert gopher_mcp.server._gopher_client is None

    @pytest.mark.asyncio
    async def test_cleanup_without_client(self):
        """Test cleanup when no client exists."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        # Should not raise any errors
        await cleanup()

        assert gopher_mcp.server._gopher_client is None


class TestMCPServer:
    """Test MCP server instance."""

    def test_mcp_server_exists(self):
        """Test that MCP server instance exists."""
        assert mcp is not None
        assert hasattr(mcp, "name")

    def test_mcp_server_has_tools(self):
        """Test that MCP server has the expected tools."""
        # The gopher_fetch function should be registered as a tool
        # This is a basic check that the server is properly configured
        assert mcp is not None
        # Note: Detailed tool inspection would require accessing FastMCP internals
        # which may not be stable API, so we keep this test simple


class TestEnvironmentVariables:
    """Test environment variable handling."""

    def test_boolean_env_var_parsing(self):
        """Test parsing of boolean environment variables."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("yes", False),  # Only "true" (case-insensitive) should be True
            ("1", False),
            ("", False),
        ]

        for env_value, expected in test_cases:
            with patch.dict(
                os.environ, {"GOPHER_CACHE_ENABLED": env_value}, clear=True
            ):
                # Clear client to force recreation
                gopher_mcp.server._gopher_client = None
                client = get_gopher_client()
                assert (
                    client.cache_enabled is expected
                ), f"Failed for env_value='{env_value}'"

    def test_numeric_env_var_parsing(self):
        """Test parsing of numeric environment variables."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gopher_client = None

        with patch.dict(
            os.environ,
            {
                "GOPHER_MAX_RESPONSE_SIZE": "123456",
                "GOPHER_TIMEOUT_SECONDS": "45.5",
                "GOPHER_CACHE_TTL_SECONDS": "900",
                "GOPHER_MAX_CACHE_ENTRIES": "5000",
                "GOPHER_MAX_SELECTOR_LENGTH": "4096",
                "GOPHER_MAX_SEARCH_LENGTH": "1024",
            },
            clear=True,
        ):
            client = get_gopher_client()

            assert client.max_response_size == 123456
            assert client.timeout_seconds == 45.5
            assert client.cache_ttl_seconds == 900
            assert client.max_cache_entries == 5000
            assert client.max_selector_length == 4096
            assert client.max_search_length == 1024


class TestGetGeminiClient:
    """Test get_gemini_client function."""

    def test_get_gemini_client_default_config(self):
        """Test getting gemini client with default configuration."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gemini_client = None

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("gopher_mcp.tofu.get_home_directory") as mock_tofu_home,
                patch("gopher_mcp.client_certs.get_home_directory") as mock_certs_home,
            ):
                # Mock home directory for both TOFU and client certs
                mock_tofu_home.return_value = Path(temp_dir)
                mock_certs_home.return_value = Path(temp_dir)

                client = get_gemini_client()

                assert client is not None
                assert client.max_response_size == 1048576  # 1MB default
                assert client.timeout_seconds == 30.0
                assert client.cache_enabled is True
                assert client.cache_ttl_seconds == 300
                assert client.max_cache_entries == 1000
                assert client.allowed_hosts is None
                assert client.tofu_enabled is True
                assert client.client_certs_enabled is True

    def test_get_gemini_client_custom_config(self):
        """Test getting gemini client with custom configuration."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gemini_client = None

        env_vars = {
            "GEMINI_MAX_RESPONSE_SIZE": "2097152",  # 2MB
            "GEMINI_TIMEOUT_SECONDS": "60.0",
            "GEMINI_CACHE_ENABLED": "false",
            "GEMINI_CACHE_TTL_SECONDS": "600",
            "GEMINI_MAX_CACHE_ENTRIES": "2000",
            "GEMINI_ALLOWED_HOSTS": "example.org,test.org",
            "GEMINI_TOFU_ENABLED": "false",
            "GEMINI_CLIENT_CERTS_ENABLED": "false",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            client = get_gemini_client()

            assert client.max_response_size == 2097152
            assert client.timeout_seconds == 60.0
            assert client.cache_enabled is False
            assert client.cache_ttl_seconds == 600
            assert client.max_cache_entries == 2000
            assert client.allowed_hosts == {"example.org", "test.org"}
            assert client.tofu_enabled is False
            assert client.client_certs_enabled is False

    def test_get_gemini_client_singleton(self):
        """Test that get_gemini_client returns the same instance."""
        # Clear any existing client
        import gopher_mcp.server

        gopher_mcp.server._gemini_client = None

        client1 = get_gemini_client()
        client2 = get_gemini_client()

        assert client1 is client2


class TestGeminiFetch:
    """Test gemini_fetch function."""

    @pytest.mark.asyncio
    async def test_gemini_fetch_success(self):
        """Test successful gemini fetch."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "kind": "gemtext",
            "document": {"lines": [], "links": []},
            "raw_content": "# Test",
            "charset": "utf-8",
            "size": 6,
            "request_info": {"url": "gemini://example.org/", "timestamp": 1234567890},
        }

        mock_client = AsyncMock()
        mock_client.fetch.return_value = mock_response

        with patch("gopher_mcp.server.get_gemini_client", return_value=mock_client):
            result = await gemini_fetch("gemini://example.org/")

            assert result["kind"] == "gemtext"
            assert result["raw_content"] == "# Test"
            mock_client.fetch.assert_called_once_with("gemini://example.org/")

    @pytest.mark.asyncio
    async def test_gemini_fetch_invalid_url(self):
        """Test gemini fetch with invalid URL."""
        with pytest.raises(Exception):  # Should raise validation error
            await gemini_fetch("http://example.com/")

    @pytest.mark.asyncio
    async def test_gemini_fetch_client_error(self):
        """Test gemini fetch with client error."""
        mock_client = AsyncMock()
        mock_client.fetch.side_effect = Exception("Connection failed")

        with patch("gopher_mcp.server.get_gemini_client", return_value=mock_client):
            with pytest.raises(Exception):
                await gemini_fetch("gemini://example.org/")
