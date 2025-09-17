"""Pytest configuration and shared fixtures for gopher-mcp tests."""

import asyncio
from typing import Generator
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


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
