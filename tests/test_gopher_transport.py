"""Tests for the native async Gopher transport.

These exercise the real socket path against a loopback server (no mocking
of the transport itself), proving the bounded read, overall deadline and
latin-1 decode that replaced the unmaintained pituophis dependency.
"""

import asyncio

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


def test_build_request_empty_type7_query_sends_tab():
    # An explicit empty type-7 query ("") must still send the TAB field so an
    # index server sees an empty query rather than a bare selector. None (no
    # query) sends just the selector.
    assert build_request("/find", "") == b"/find\t\r\n"
    assert build_request("/find", None) == b"/find\r\n"


def test_decode_utf8():
    assert decode_gopher_text("héllo".encode()) == ("héllo", "utf-8")


def test_decode_latin1_fallback():
    raw = "café".encode("latin-1")  # 0xe9, invalid as UTF-8
    text, charset = decode_gopher_text(raw)
    assert charset == "latin-1"
    assert text == "café"


async def _serve(
    payload: bytes,
    record: list[bytes] | None = None,
) -> tuple[asyncio.AbstractServer, int]:
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
    record: list[bytes] = []
    server, port = await _serve(b"hello menu\r\n.\r\n", record)
    async with server:
        data = await fetch_gopher(
            "127.0.0.1", port, "/sel", None, max_bytes=1024, timeout=5
        )
    assert data == b"hello menu\r\n.\r\n"
    assert record[0] == b"/sel\r\n"


@pytest.mark.asyncio
async def test_fetch_gopher_search_sends_tab_query():
    record: list[bytes] = []
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
    # A dead port surfaces as a GopherProtocolError. The exact message is
    # platform-dependent: POSIX reports the connection refused immediately,
    # while Windows can let the connect attempt run until it times out.
    with pytest.raises(GopherProtocolError, match=r"Connection failed|timed out"):
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
        except (TimeoutError, asyncio.CancelledError):
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


@pytest.mark.asyncio
async def test_fetch_gopher_connects_to_pinned_address():
    """The connection must target the pinned IP, not re-resolve the host."""
    server, port = await _serve(b"pinned\r\n")
    async with server:
        data = await fetch_gopher(
            "host.that.never.resolves.invalid",
            port,
            "/sel",
            None,
            max_bytes=1024,
            timeout=5,
            connect_addresses=["127.0.0.1"],
        )
    assert data == b"pinned\r\n"
