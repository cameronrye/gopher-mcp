"""Placeholder tests to ensure the testing framework is working."""

import pytest


def test_placeholder():
    """Placeholder test to verify pytest is working."""
    assert True


@pytest.mark.asyncio
async def test_async_placeholder():
    """Placeholder async test to verify pytest-asyncio is working."""
    assert True


def test_fixtures_available(
    sample_gopher_urls,
    expected_menu_result,
    expected_text_result,
):
    """Test that fixtures are available and properly structured."""
    assert "menu" in sample_gopher_urls
    assert "text" in sample_gopher_urls
    assert sample_gopher_urls["menu"].startswith("gopher://")

    assert expected_menu_result["kind"] == "menu"
    assert "items" in expected_menu_result

    assert expected_text_result["kind"] == "text"
    assert "text" in expected_text_result


@pytest.mark.unit
def test_unit_marker():
    """Test that unit test marker works."""
    assert True


@pytest.mark.integration
def test_integration_marker():
    """Test that integration test marker works."""
    assert True


@pytest.mark.slow
def test_slow_marker():
    """Test that slow test marker works."""
    assert True
