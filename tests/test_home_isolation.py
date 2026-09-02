"""Regression tests: the suite must never read or write the real home directory.

A default ``GeminiClient()`` builds a ``TOFUManager`` and a
``ClientCertificateManager`` whose storage defaults to ``~/.gemini/tofu.json``
and ``~/.gemini/certs``. Without test isolation, running the suite would read
and *write the real user home*. The autouse ``isolated_home`` fixture in
``conftest.py`` redirects ``$HOME`` / ``$USERPROFILE`` -- and ``Path.home``
itself, which POSIX would otherwise answer from the password database once a
test clears the environment -- to a per-test tmp dir; these tests fail if that
isolation ever regresses.
"""

import os
from pathlib import Path
from unittest.mock import patch

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.utils import get_home_directory

# Captured at import time -- before any per-test HOME monkeypatch runs -- so it
# is the developer's actual home directory regardless of the isolation fixture.
_REAL_HOME = Path.home()
_REAL_GEMINI_DIR = _REAL_HOME / ".gemini"


def test_home_directory_is_isolated_from_real_home() -> None:
    """``get_home_directory()`` must not resolve to the real home during tests.

    Fails without the autouse isolation fixture: ``get_home_directory()`` would
    return the developer's real home. This check performs no filesystem access,
    so even the failing (pre-fixture) state leaves the real ``~/.gemini``
    untouched.
    """
    home = get_home_directory()
    assert home is not None
    assert home != _REAL_HOME, (
        "Tests resolved the REAL home directory -- the autouse home-isolation "
        "fixture is not active, so the suite would read/write ~/.gemini."
    )


def test_default_gemini_client_stores_under_isolated_home(
    isolated_home: Path,
) -> None:
    """Default manager storage must live under the isolated home, not the real one."""
    client = GeminiClient()

    assert client.tofu_manager is not None
    assert client.client_cert_manager is not None

    tofu_path = Path(client.tofu_manager.storage_path)
    cert_path = Path(client.client_cert_manager.storage_path)

    # Resolved under the per-test isolated home...
    assert isolated_home in tofu_path.parents
    assert isolated_home in cert_path.parents
    # ...and never under the developer's real ~/.gemini.
    assert _REAL_GEMINI_DIR not in tofu_path.parents
    assert _REAL_GEMINI_DIR not in cert_path.parents


def test_tofu_write_lands_in_isolated_home(isolated_home: Path) -> None:
    """A real TOFU write must land in the isolated home, never the real one."""
    client = GeminiClient()
    assert client.tofu_manager is not None

    # Exercises the actual on-disk write path (atomic_write_json).
    client.update_tofu_certificate("example.org", 1965, "a" * 64)

    written = Path(client.tofu_manager.storage_path)
    assert written.exists()
    assert isolated_home in written.parents
    assert _REAL_GEMINI_DIR not in written.parents


def test_isolation_survives_a_cleared_environment(isolated_home: Path) -> None:
    """``patch.dict(os.environ, clear=True)`` must not reopen the real home.

    Several tests clear the environment to assert a client's *default*
    configuration. That drops the ``HOME``/``USERPROFILE`` the isolation fixture
    sets, and on POSIX ``Path.home()`` then falls back to the password database
    -- silently returning the developer's real home, so a default client would
    ``mkdir`` and rewrite a real ``~/.gemini/tofu.json``. Only Windows, which
    has no such fallback, fails loudly; that is how it was caught last time.

    So the fixture also replaces ``Path.home`` itself, and this is the test that
    fails if that line is ever removed.
    """
    with patch.dict(os.environ, {}, clear=True):
        assert Path.home() == isolated_home
        assert get_home_directory() == isolated_home

        client = GeminiClient()
        assert client.tofu_manager is not None
        assert client.client_cert_manager is not None

        tofu_path = Path(client.tofu_manager.storage_path)
        cert_path = Path(client.client_cert_manager.storage_path)

    assert isolated_home in tofu_path.parents
    assert isolated_home in cert_path.parents
    assert _REAL_GEMINI_DIR not in tofu_path.parents
    assert _REAL_GEMINI_DIR not in cert_path.parents
