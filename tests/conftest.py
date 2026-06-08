"""Pytest configuration and shared fixtures for gopher-mcp tests."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve hostnames deterministically and offline for the SSRF guard.

    Keeps the suite hermetic (no real DNS) while letting tests select an
    internal vs public outcome via the hostname:
      * ``localhost`` -> 127.0.0.1 (blocked)
      * ``*.internal`` / ``*.local`` -> 10.0.0.5 (blocked)
      * ``blocked.example`` -> 169.254.169.254 (blocked)
      * anything else -> a public address (allowed)
    IP-literal hosts are classified without resolution, so they bypass this.
    """

    async def fake_resolve(host: str, port: int) -> list[str]:
        h = host.strip().rstrip(".").lower()
        if h == "localhost":
            return ["127.0.0.1"]
        if h.endswith(".internal") or h.endswith(".local"):
            return ["10.0.0.5"]
        if h == "blocked.example":
            return ["169.254.169.254"]
        return ["93.184.216.34"]

    monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", fake_resolve)


@pytest.fixture(autouse=True)
def _reset_client_manager_singleton():
    """Reset the global client-manager singleton around every test.

    The manager is a class-level singleton, so an instance created by one test
    would otherwise leak into the next (an ordering dependency). This is the
    safety net so a forgotten manual reset can't contaminate later tests.
    """
    from gopher_mcp.server import ClientManager

    ClientManager._instance = None
    yield
    ClientManager._instance = None


@pytest.fixture
def mock_gopher_server() -> Mock:
    """Mock Gopher server for testing."""
    server = Mock()
    server.host = "gopher.example.com"
    server.port = 70
    return server


@pytest.fixture
async def mock_gopher_client() -> AsyncMock:
    """Mock Gopher client for testing."""
    client = AsyncMock()

    # Mock menu response
    client.fetch_menu.return_value = [
        {
            "type": "0",
            "title": "Test Document",
            "selector": "/test.txt",
            "host": "gopher.example.com",
            "port": 70,
        },
        {
            "type": "1",
            "title": "Test Directory",
            "selector": "/testdir/",
            "host": "gopher.example.com",
            "port": 70,
        },
    ]

    # Mock text response
    client.fetch_text.return_value = "This is test content from a Gopher server."

    # Mock binary response
    client.fetch_binary.return_value = b"Binary content"

    return client


@pytest.fixture
def sample_gopher_menu_response() -> str:
    """Sample Gopher menu response for testing."""
    return (
        "0About Gopher\tabout\tgopher.example.com\t70\r\n"
        "1Documents\tdocs/\tgopher.example.com\t70\r\n"
        "7Search\tsearch\tsearch.example.com\t70\r\n"
        ".\r\n"
    )


@pytest.fixture
def sample_gopher_text_response() -> str:
    """Sample Gopher text response for testing."""
    return (
        "Welcome to the Gopher protocol!\r\n"
        "\r\n"
        "This is a simple text document served via Gopher.\r\n"
        ".\r\n"
    )


@pytest.fixture
def sample_gopher_search_response() -> str:
    """Sample Gopher search response for testing."""
    return (
        "0Python Tutorial\ttutorials/python.txt\tdocs.example.com\t70\r\n"
        "0Python Reference\tref/python.txt\tdocs.example.com\t70\r\n"
        ".\r\n"
    )


@pytest.fixture
def mock_mcp_server() -> AsyncMock:
    """Mock MCP server for testing."""
    server = AsyncMock()
    server.list_tools.return_value = [
        {
            "name": "gopher.fetch",
            "description": "Fetch Gopher menus or text by URL.",
            "inputSchema": {
                "type": "object",
                "required": ["url"],
                "properties": {"url": {"type": "string", "format": "uri"}},
            },
        }
    ]
    return server


@pytest.fixture
def sample_gopher_urls() -> dict[str, str]:
    """Sample Gopher URLs for testing."""
    return {
        "menu": "gopher://gopher.example.com/1/",
        "text": "gopher://gopher.example.com/0/about.txt",
        "search": "gopher://search.example.com/7/search",
        "binary": "gopher://gopher.example.com/9/file.bin",
        "with_port": "gopher://gopher.example.com:7070/1/",
        "with_search": "gopher://search.example.com/7/search%09python",
    }


@pytest.fixture
def expected_menu_result() -> dict:
    """Expected menu result structure for testing."""
    return {
        "kind": "menu",
        "items": [
            {
                "type": "0",
                "title": "About Gopher",
                "selector": "about",
                "host": "gopher.example.com",
                "port": 70,
                "nextUrl": "gopher://gopher.example.com:70/0about",
            },
            {
                "type": "1",
                "title": "Documents",
                "selector": "docs/",
                "host": "gopher.example.com",
                "port": 70,
                "nextUrl": "gopher://gopher.example.com:70/1docs/",
            },
            {
                "type": "7",
                "title": "Search",
                "selector": "search",
                "host": "search.example.com",
                "port": 70,
                "nextUrl": "gopher://search.example.com:70/7search",
            },
        ],
    }


@pytest.fixture
def expected_text_result() -> dict:
    """Expected text result structure for testing."""
    return {
        "kind": "text",
        "charset": "utf-8",
        "bytes": 85,
        "text": (
            "Welcome to the Gopher protocol!\n"
            "\n"
            "This is a simple text document served via Gopher."
        ),
    }


@pytest.fixture
def expected_error_result() -> dict:
    """Expected error result structure for testing."""
    return {
        "error": {
            "code": "ECONN",
            "message": "dial tcp 203.0.113.1:70: i/o timeout",
        }
    }


# Pytest configuration
pytest_plugins = ["pytest_asyncio"]
