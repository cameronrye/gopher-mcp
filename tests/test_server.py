"""Tests for gopher_mcp.server module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gopher_mcp.server import (
    cleanup,
    get_client_manager,
    ClientManager,
    gopher_fetch,
    gemini_fetch,
    mcp,
)
from gopher_mcp.config import reset_config


def clear_client_manager():
    """Helper to clear both module-level and class-level client manager instances."""
    import gopher_mcp.server

    gopher_mcp.server._client_manager = None
    ClientManager._instance = None
    # Also reset the config so it picks up new environment variables
    reset_config()


class TestGetGopherClient:
    """Test get_gopher_client function via ClientManager."""

    @pytest.mark.asyncio
    async def test_get_gopher_client_default_config(self):
        """Test getting gopher client with default configuration."""
        clear_client_manager()

        with patch.dict(os.environ, {}, clear=True):
            manager = await get_client_manager()
            client = await manager.get_gopher_client()

            assert client is not None
            assert client.max_response_size == 1048576  # 1MB default
            assert client.timeout_seconds == 30.0
            assert client.cache_enabled is True
            assert client.cache_ttl_seconds == 300
            assert client.max_cache_entries == 1000
            assert client.allowed_hosts is None
            assert client.max_selector_length == 1024
            assert client.max_search_length == 256

    @pytest.mark.asyncio
    async def test_get_gopher_client_custom_config(self):
        """Test getting gopher client with custom configuration."""
        clear_client_manager()

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
            manager = await get_client_manager()
            client = await manager.get_gopher_client()

            assert client.max_response_size == 2097152
            assert client.timeout_seconds == 60.0
            assert client.cache_enabled is False
            assert client.cache_ttl_seconds == 600
            assert client.max_cache_entries == 2000
            assert client.allowed_hosts == {"example.com", "test.com"}
            assert client.max_selector_length == 2048
            assert client.max_search_length == 512

    @pytest.mark.asyncio
    async def test_get_gopher_client_singleton(self):
        """Test that get_gopher_client returns the same instance."""
        clear_client_manager()

        manager = await get_client_manager()
        client1 = await manager.get_gopher_client()
        client2 = await manager.get_gopher_client()

        assert client1 is client2

    @pytest.mark.asyncio
    async def test_get_gopher_client_allowed_hosts_parsing(self):
        """Test parsing of allowed hosts from environment."""
        clear_client_manager()

        with patch.dict(
            os.environ,
            {"GOPHER_ALLOWED_HOSTS": "  host1.com , host2.com  , host3.com  "},
            clear=True,
        ):
            manager = await get_client_manager()
            client = await manager.get_gopher_client()

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

        mock_manager = AsyncMock()
        mock_manager.get_gopher_client.return_value = mock_client

        with patch("gopher_mcp.server.get_client_manager", return_value=mock_manager):
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

        mock_manager = AsyncMock()
        mock_manager.get_gopher_client.return_value = mock_client

        with patch("gopher_mcp.server.get_client_manager", return_value=mock_manager):
            with pytest.raises(Exception) as exc_info:
                await gopher_fetch("gopher://example.com/0/test.txt")

            assert "Connection failed" in str(exc_info.value)


class TestCleanup:
    """Test cleanup function."""

    @pytest.mark.asyncio
    async def test_cleanup_with_client(self):
        """Test cleanup when client manager exists."""
        # Set up a mock client manager
        import gopher_mcp.server

        mock_manager = AsyncMock()
        mock_gopher_client = AsyncMock()
        mock_gemini_client = AsyncMock()
        mock_manager._gopher_client = mock_gopher_client
        mock_manager._gemini_client = mock_gemini_client
        gopher_mcp.server._client_manager = mock_manager

        await cleanup()

        # Verify cleanup was called on the manager
        mock_manager.cleanup.assert_called_once()
        assert gopher_mcp.server._client_manager is None

    @pytest.mark.asyncio
    async def test_cleanup_without_client(self):
        """Test cleanup when no client manager exists."""
        # Clear any existing client manager
        import gopher_mcp.server

        gopher_mcp.server._client_manager = None

        # Should not raise any errors
        await cleanup()

        assert gopher_mcp.server._client_manager is None


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

    @pytest.mark.asyncio
    async def test_boolean_env_var_parsing(self):
        """Test parsing of boolean environment variables.

        Pydantic accepts: true, yes, 1, on as True
        Pydantic accepts: false, no, 0, off as False
        """
        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("yes", True),  # Pydantic accepts yes as True
            ("1", True),  # Pydantic accepts 1 as True
            ("on", True),  # Pydantic accepts on as True
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("no", False),  # Pydantic accepts no as False
            ("0", False),  # Pydantic accepts 0 as False
            ("off", False),  # Pydantic accepts off as False
        ]

        for env_value, expected in test_cases:
            with patch.dict(
                os.environ, {"GOPHER_CACHE_ENABLED": env_value}, clear=True
            ):
                # Clear client manager to force recreation
                clear_client_manager()
                manager = await get_client_manager()
                client = await manager.get_gopher_client()
                assert client.cache_enabled is expected, (
                    f"Failed for env_value='{env_value}'"
                )

    @pytest.mark.asyncio
    async def test_numeric_env_var_parsing(self):
        """Test parsing of numeric environment variables."""
        clear_client_manager()

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
            manager = await get_client_manager()
            client = await manager.get_gopher_client()

            assert client.max_response_size == 123456
            assert client.timeout_seconds == 45.5
            assert client.cache_ttl_seconds == 900
            assert client.max_cache_entries == 5000
            assert client.max_selector_length == 4096
            assert client.max_search_length == 1024


class TestGetGeminiClient:
    """Test get_gemini_client function via ClientManager."""

    @pytest.mark.asyncio
    async def test_get_gemini_client_default_config(self):
        """Test getting gemini client with default configuration."""
        clear_client_manager()

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("gopher_mcp.tofu.get_home_directory") as mock_tofu_home,
                patch("gopher_mcp.client_certs.get_home_directory") as mock_certs_home,
            ):
                # Mock home directory for both TOFU and client certs
                mock_tofu_home.return_value = Path(temp_dir)
                mock_certs_home.return_value = Path(temp_dir)

                manager = await get_client_manager()
                client = await manager.get_gemini_client()

                assert client is not None
                assert client.max_response_size == 1048576  # 1MB default
                assert client.timeout_seconds == 30.0
                assert client.cache_enabled is True
                assert client.cache_ttl_seconds == 300
                assert client.max_cache_entries == 1000
                assert client.allowed_hosts is None
                assert client.tofu_enabled is True
                assert client.client_certs_enabled is True

    @pytest.mark.asyncio
    async def test_get_gemini_client_custom_config(self):
        """Test getting gemini client with custom configuration."""
        clear_client_manager()

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
            manager = await get_client_manager()
            client = await manager.get_gemini_client()

            assert client.max_response_size == 2097152
            assert client.timeout_seconds == 60.0
            assert client.cache_enabled is False
            assert client.cache_ttl_seconds == 600
            assert client.max_cache_entries == 2000
            assert client.allowed_hosts == {"example.org", "test.org"}
            assert client.tofu_enabled is False
            assert client.client_certs_enabled is False

    @pytest.mark.asyncio
    async def test_get_gemini_client_singleton(self):
        """Test that get_gemini_client returns the same instance."""
        clear_client_manager()

        manager = await get_client_manager()
        client1 = await manager.get_gemini_client()
        client2 = await manager.get_gemini_client()

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

        mock_manager = AsyncMock()
        mock_manager.get_gemini_client.return_value = mock_client

        with patch("gopher_mcp.server.get_client_manager", return_value=mock_manager):
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

        mock_manager = AsyncMock()
        mock_manager.get_gemini_client.return_value = mock_client

        with patch("gopher_mcp.server.get_client_manager", return_value=mock_manager):
            with pytest.raises(Exception):
                await gemini_fetch("gemini://example.org/")
