"""Pytest configuration and shared fixtures for gopher-mcp tests."""

import pathlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the home directory to a per-test tmp dir.

    A default ``GeminiClient()`` builds a ``TOFUManager`` and a
    ``ClientCertificateManager`` whose storage defaults to ``~/.gemini`` (via
    ``get_home_directory()`` -> ``Path.home()``). Without this, every test that
    constructs a default client would *read and write the developer's real home
    directory* -- creating ``~/.gemini/certs`` and ``~/.gemini/tofu.json``.

    ``Path.home()`` honours ``$HOME`` on POSIX and ``$USERPROFILE`` on Windows,
    so the two env vars are set first: that is the mechanism the code already
    supports, and it needs no knowledge of every ``get_home_directory`` import
    site.

    The env vars alone are NOT enough, which is why ``Path.home`` itself is
    replaced as well. A test wrapping its body in
    ``patch.dict(os.environ, {}, clear=True)`` -- there are several -- drops
    ``HOME`` along with everything else, and on POSIX ``Path.home()`` then falls
    back to the *password database*, so it quietly returns the developer's real
    home and the suite writes into a real ``~/.gemini``. That has happened
    before (commit 8b857b6) and it fails silently: only Windows, which has no
    such fallback, errors outright. Do not drop the ``setattr`` -- see
    ``tests/test_home_isolation.py``, which pins this.

    Returned so tests that assert on the isolated location can request it by
    name.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    return home


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


# Pytest configuration
pytest_plugins = ["pytest_asyncio"]
