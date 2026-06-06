"""Native async transport for the Gopher protocol (RFC 1436).

Replaces the unmaintained ``pituophis`` dependency with a small asyncio
client that the project owns end to end. Compared to pituophis this:

* enforces a hard response-size cap and an overall request deadline
  (pituophis did an unbounded blocking ``stream.read()`` with only a
  fixed 10s per-recv timeout), closing a memory/DoS exposure; and
* decodes legacy latin-1 content that the UTF-8-only library crashed on.

Callers are responsible for validating ``host``/``port`` (SSRF/allowlist)
and for rejecting selectors/queries containing CR/LF/TAB before calling
``fetch_gopher`` -- those checks keep the single request line un-injectable.
"""

import asyncio
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

READ_CHUNK = 65536


class GopherProtocolError(Exception):
    """Raised when a Gopher request cannot be completed."""


def build_request(selector: str, search: Optional[str] = None) -> bytes:
    """Build the Gopher request line: ``selector[<TAB>search]<CR><LF>``."""
    line = f"{selector}\t{search}" if search else selector
    return line.encode("utf-8", errors="strict") + b"\r\n"


async def fetch_gopher(
    host: str,
    port: int,
    selector: str,
    search: Optional[str] = None,
    *,
    max_bytes: int,
    timeout: float,
) -> bytes:
    """Fetch a raw Gopher response with a bounded size and an overall deadline.

    Args:
        host: Target hostname (already SSRF/allowlist validated by the caller).
        port: Target port.
        selector: Gopher selector string.
        search: Optional type-7 search query.
        max_bytes: Hard cap on response size; larger responses are rejected.
        timeout: Overall deadline in seconds covering connect, send and read.

    Returns:
        Raw response bytes (at most ``max_bytes``).

    Raises:
        GopherProtocolError: On connection failure, timeout, or oversize response.
    """
    request = build_request(selector, search)

    async def _io() -> bytes:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(request)
            await writer.drain()

            chunks: List[bytes] = []
            total = 0
            while True:
                # Read one byte past the cap so an over-limit response is
                # detected rather than silently truncated.
                want = min(READ_CHUNK, max_bytes - total + 1)
                chunk = await reader.read(want)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise GopherProtocolError(
                        f"Response exceeds maximum size of {max_bytes} bytes"
                    )
            return b"".join(chunks)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:  # pragma: no cover - best-effort close
                pass

    try:
        return await asyncio.wait_for(_io(), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise GopherProtocolError(f"Request timed out after {timeout} seconds") from e
    except GopherProtocolError:
        raise
    except OSError as e:
        raise GopherProtocolError(f"Connection failed: {e}") from e


def decode_gopher_text(data: bytes) -> Tuple[str, str]:
    """Decode Gopher bytes as UTF-8, falling back to latin-1.

    Legacy Gopher servers commonly serve latin-1 (or other 8-bit) content;
    latin-1 maps every byte so it never raises. Returns ``(text, charset)``
    so callers can report the encoding actually used.
    """
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"
