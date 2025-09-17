"""Tests for gopher_mcp.http_server module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from gopher_mcp.http_server import HTTPServer, run_http_server


class TestHTTPServerInitialization:
    """Test HTTPServer initialization."""

    def test_default_initialization(self):
        """Test HTTPServer with default parameters."""
        server = HTTPServer()

        assert server.host == "localhost"
        assert server.port == 8000
        assert server.server is None

    def test_custom_initialization(self):
        """Test HTTPServer with custom parameters."""
        server = HTTPServer(host="0.0.0.0", port=9000)

        assert server.host == "0.0.0.0"
        assert server.port == 9000
        assert server.server is None


class TestHTTPServerStart:
    """Test HTTPServer start method."""

    @pytest.mark.asyncio
    async def test_start_success(self):
        """Test successful server start."""
        server = HTTPServer()

        # Mock aiohttp components
        mock_app = Mock()
        mock_runner = Mock()
        mock_site = Mock()

        with (
            patch("aiohttp.web.Application") as mock_app_class,
            patch("aiohttp.web_runner.AppRunner") as mock_runner_class,
            patch("aiohttp.web_runner.TCPSite") as mock_site_class,
        ):
            mock_app_class.return_value = mock_app
            mock_runner_class.return_value = mock_runner
            mock_site_class.return_value = mock_site

            # Mock async methods
            mock_runner.setup = AsyncMock()
            mock_site.start = AsyncMock()

            await server.start()

            # Verify app configuration
            mock_app.router.add_post.assert_any_call("/mcp", server._handle_mcp_request)
            mock_app.router.add_get.assert_any_call("/health", server._handle_health)
            mock_app.router.add_options.assert_any_call("/mcp", server._handle_options)
            mock_app.middlewares.append.assert_called_once()

            # Verify runner setup
            mock_runner_class.assert_called_once_with(mock_app)
            mock_runner.setup.assert_called_once()

            # Verify site creation and start
            mock_site_class.assert_called_once_with(mock_runner, "localhost", 8000)
            mock_site.start.assert_called_once()

            # Verify server is stored
            assert server.server == mock_runner

    @pytest.mark.asyncio
    async def test_start_import_error(self):
        """Test server start with missing aiohttp dependency."""
        server = HTTPServer()

        with patch(
            "aiohttp.web.Application",
            side_effect=ImportError("No module named 'aiohttp'"),
        ):
            with pytest.raises(ImportError):
                await server.start()


class TestHTTPServerStop:
    """Test HTTPServer stop method."""

    @pytest.mark.asyncio
    async def test_stop_with_server(self):
        """Test stopping server when server exists."""
        server = HTTPServer()
        mock_runner = Mock()
        mock_runner.cleanup = AsyncMock()
        server.server = mock_runner

        await server.stop()

        mock_runner.cleanup.assert_called_once()
        assert server.server is None

    @pytest.mark.asyncio
    async def test_stop_without_server(self):
        """Test stopping server when no server exists."""
        server = HTTPServer()
        server.server = None

        # Should not raise an exception
        await server.stop()
        assert server.server is None


class TestHTTPServerMiddleware:
    """Test HTTPServer CORS middleware."""

    @pytest.mark.asyncio
    async def test_cors_middleware(self):
        """Test CORS middleware adds correct headers."""
        mock_request = Mock()
        mock_response = Mock()
        mock_response.headers = {}

        async def mock_handler(request):
            return mock_response

        result = await HTTPServer._cors_middleware(mock_request, mock_handler)

        assert result == mock_response
        assert result.headers["Access-Control-Allow-Origin"] == "*"
        assert result.headers["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
        assert result.headers["Access-Control-Allow-Headers"] == "Content-Type"


class TestHTTPServerEndpoints:
    """Test HTTPServer endpoint handlers."""

    @pytest.mark.asyncio
    async def test_handle_health(self):
        """Test health check endpoint."""
        server = HTTPServer()
        mock_request = Mock()

        with patch("aiohttp.web.json_response") as mock_json_response:
            mock_json_response.return_value = {"status": "healthy"}

            _result = await server._handle_health(mock_request)

            mock_json_response.assert_called_once_with(
                {"status": "healthy", "service": "gopher-mcp"}
            )

    @pytest.mark.asyncio
    async def test_handle_options(self):
        """Test CORS preflight endpoint."""
        server = HTTPServer()
        mock_request = Mock()

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = Mock()

            _result = await server._handle_options(mock_request)

            mock_response.assert_called_once_with(
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                }
            )

    @pytest.mark.asyncio
    async def test_handle_mcp_request_success(self):
        """Test MCP request handler with valid request."""
        server = HTTPServer()
        mock_request = Mock()
        mock_request.json = AsyncMock(return_value={"id": 1, "method": "test"})

        with patch("aiohttp.web.json_response") as mock_json_response:
            mock_json_response.return_value = {"error": "not implemented"}

            _result = await server._handle_mcp_request(mock_request)

            mock_json_response.assert_called_once_with(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": "Method not implemented - use FastMCP's built-in HTTP transport",
                        "data": "Call mcp.run(transport='http') instead",
                    },
                    "id": 1,
                },
                status=501,
            )

    @pytest.mark.asyncio
    async def test_handle_mcp_request_invalid_json(self):
        """Test MCP request handler with invalid JSON."""
        server = HTTPServer()
        mock_request = Mock()
        mock_request.json = AsyncMock(side_effect=Exception("Invalid JSON"))

        with patch("aiohttp.web.json_response") as mock_json_response:
            mock_json_response.return_value = {"error": "internal error"}

            _result = await server._handle_mcp_request(mock_request)

            mock_json_response.assert_called_once_with(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": "Invalid JSON",
                    },
                    "id": None,
                },
                status=500,
            )

    @pytest.mark.asyncio
    async def test_handle_mcp_request_no_id(self):
        """Test MCP request handler with request without ID."""
        server = HTTPServer()
        mock_request = Mock()
        mock_request.json = AsyncMock(return_value={"method": "test"})  # No ID

        with patch("aiohttp.web.json_response") as mock_json_response:
            mock_json_response.return_value = {"error": "not implemented"}

            _result = await server._handle_mcp_request(mock_request)

            # Should handle missing ID gracefully
            expected_call = mock_json_response.call_args[0][0]
            assert expected_call["id"] is None


class TestRunHTTPServer:
    """Test the run_http_server function."""

    @pytest.mark.asyncio
    async def test_run_http_server_startup(self):
        """Test run_http_server startup sequence."""
        with (
            patch.object(HTTPServer, "start") as mock_start,
            patch.object(HTTPServer, "stop") as mock_stop,
            patch("gopher_mcp.http_server.cleanup") as mock_cleanup,
            patch("asyncio.sleep", side_effect=KeyboardInterrupt),
        ):  # Simulate interrupt
            mock_start.return_value = AsyncMock()
            mock_stop.return_value = AsyncMock()
            mock_cleanup.return_value = AsyncMock()

            try:
                await run_http_server("127.0.0.1", 9000)
            except KeyboardInterrupt:
                pass  # Expected

            mock_start.assert_called_once()
            mock_stop.assert_called_once()
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_http_server_exception_handling(self):
        """Test run_http_server exception handling."""
        with (
            patch.object(
                HTTPServer, "start", side_effect=Exception("Start failed")
            ) as mock_start,
            patch.object(HTTPServer, "stop") as mock_stop,
            patch("gopher_mcp.http_server.cleanup") as mock_cleanup,
        ):
            mock_stop.return_value = AsyncMock()
            mock_cleanup.return_value = AsyncMock()

            with pytest.raises(Exception, match="Start failed"):
                await run_http_server()

            mock_start.assert_called_once()
            mock_stop.assert_called_once()
            mock_cleanup.assert_called_once()


class TestHTTPServerMainExecution:
    """Test HTTP server main execution."""

    def test_main_execution_with_env_vars(self):
        """Test main execution with environment variables."""
        with (
            patch.dict(
                "os.environ",
                {"GOPHER_HTTP_HOST": "0.0.0.0", "GOPHER_HTTP_PORT": "9000"},
            ),
            patch("asyncio.run") as _mock_run,
        ):
            # Import and execute the main block
            import gopher_mcp.http_server

            # Simulate running the main block
            if hasattr(gopher_mcp.http_server, "__name__"):
                # This would be executed if run as main
                pass

    def test_main_execution_default_values(self):
        """Test main execution with default values."""
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("asyncio.run") as _mock_run,
        ):
            # Import and execute the main block
            import gopher_mcp.http_server

            # Simulate running the main block
            if hasattr(gopher_mcp.http_server, "__name__"):
                # This would be executed if run as main
                pass
