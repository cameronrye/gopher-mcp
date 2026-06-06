"""Tests for the native async Gopher transport.

These exercise the real socket path against a loopback server (no mocking
of the transport itself), proving the bounded read, overall deadline and
latin-1 decode that replaced the unmaintained pituophis dependency.
"""

import asyncio
from typing import List, Optional, Tuple

import pytest

from gopher_mcp.gopher_transport import (
    GopherProtocolError,
    build_request,
    decode_gopher_text,
    fetch_gopher,
)


def test_build_request_plain():
    assert build_request("/foo") == b"/foo\r\n"


def test_build_request_with_search():
    assert build_request("/find", "python") == b"/find\tpython\r\n"


def test_decode_utf8():
    assert decode_gopher_text("héllo".encode("utf-8")) == ("héllo", "utf-8")


def test_decode_latin1_fallback():
    raw = "café".encode("latin-1")  # 0xe9, invalid as UTF-8
    text, charset = decode_gopher_text(raw)
    assert charset == "latin-1"
    assert text == "café"


async def _serve(
    payload: bytes,
    record: Optional[List[bytes]] = None,
) -> Tuple[asyncio.AbstractServer, int]:
    """Start a one-shot loopback Gopher server returning ``payload``."""

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        data = await reader.readline()
        if record is not None:
            record.append(data)
        writer.write(payload)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


@pytest.mark.asyncio
async def test_fetch_gopher_success():
    record: List[bytes] = []
    server, port = await _serve(b"hello menu\r\n.\r\n", record)
    async with server:
        data = await fetch_gopher(
            "127.0.0.1", port, "/sel", None, max_bytes=1024, timeout=5
        )
    assert data == b"hello menu\r\n.\r\n"
    assert record[0] == b"/sel\r\n"


@pytest.mark.asyncio
async def test_fetch_gopher_search_sends_tab_query():
    record: List[bytes] = []
    server, port = await _serve(b"ok\r\n", record)
    async with server:
        await fetch_gopher(
            "127.0.0.1", port, "/find", "python", max_bytes=1024, timeout=5
        )
    assert record[0] == b"/find\tpython\r\n"


@pytest.mark.asyncio
async def test_fetch_gopher_rejects_oversize():
    server, port = await _serve(b"x" * 5000)
    async with server:
        with pytest.raises(GopherProtocolError, match="exceeds maximum size"):
            await fetch_gopher("127.0.0.1", port, "/", None, max_bytes=1000, timeout=5)


@pytest.mark.asyncio
async def test_fetch_gopher_exact_size_ok():
    server, port = await _serve(b"x" * 1000)
    async with server:
        data = await fetch_gopher(
            "127.0.0.1", port, "/", None, max_bytes=1000, timeout=5
        )
    assert len(data) == 1000


@pytest.mark.asyncio
async def test_fetch_gopher_connection_refused():
    server, port = await _serve(b"")
    server.close()
    await server.wait_closed()
    with pytest.raises(GopherProtocolError, match="Connection failed"):
        await fetch_gopher("127.0.0.1", port, "/", None, max_bytes=1024, timeout=2)


@pytest.mark.asyncio
async def test_fetch_gopher_timeout():
    stop = asyncio.Event()

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.readline()
            await asyncio.wait_for(stop.wait(), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        with pytest.raises(GopherProtocolError, match="timed out"):
            await fetch_gopher(
                "127.0.0.1", port, "/", None, max_bytes=1024, timeout=0.2
            )
        stop.set()
