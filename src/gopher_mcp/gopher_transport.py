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
import contextlib

import structlog

logger = structlog.get_logger(__name__)

READ_CHUNK = 65536


class GopherProtocolError(Exception):
    """Raised when a Gopher request cannot be completed."""


def build_request(selector: str, search: str | None = None) -> bytes:
    """Build the Gopher request line: ``selector[<TAB>search]<CR><LF>``."""
    line = f"{selector}\t{search}" if search else selector
    return line.encode("utf-8", errors="strict") + b"\r\n"


async def fetch_gopher(
    host: str,
    port: int,
    selector: str,
    search: str | None = None,
    *,
    max_bytes: int,
    timeout: float,
    connect_addresses: list[str] | None = None,
) -> bytes:
    """Fetch a raw Gopher response with a bounded size and an overall deadline.

    Args:
        host: Target hostname (already SSRF/allowlist validated by the caller).
        port: Target port.
        selector: Gopher selector string.
        search: Optional type-7 search query.
        max_bytes: Hard cap on response size; larger responses are rejected.
        timeout: Overall deadline in seconds covering connect, send and read.
        connect_addresses: Pre-validated IPs to connect to (in order). When
            given, the host is NOT re-resolved -- this pins the connection to
            the addresses the SSRF guard actually vetted, closing the
            DNS-rebinding window. Gopher carries no host header, so connecting
            by IP is fully equivalent.

    Returns:
        Raw response bytes (at most ``max_bytes``).

    Raises:
        GopherProtocolError: On connection failure, timeout, or oversize response.
    """
    request = build_request(selector, search)
    targets = connect_addresses or [host]

    async def _open() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        last_exc: OSError | None = None
        for addr in targets:
            try:
                return await asyncio.open_connection(addr, port)
            except OSError as e:
                last_exc = e
        raise last_exc if last_exc else OSError("no addresses to connect to")

    async def _io() -> bytes:
        reader, writer = await _open()
        try:
            writer.write(request)
            await writer.drain()

            chunks: list[bytes] = []
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
            # Best-effort close; ignore errors so they don't mask the result.
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    try:
        return await asyncio.wait_for(_io(), timeout=timeout)
    except TimeoutError as e:
        raise GopherProtocolError(f"Request timed out after {timeout} seconds") from e
    except GopherProtocolError:
        raise
    except OSError as e:
        # Use strerror only, so the resolved IP/address isn't echoed back to
        # the caller (which would act as an internal-reachability oracle).
        raise GopherProtocolError(
            f"Connection failed: {e.strerror or 'unable to connect'}"
        ) from e


def decode_gopher_text(data: bytes) -> tuple[str, str]:
    """Decode Gopher bytes as UTF-8, falling back to latin-1.

    Legacy Gopher servers commonly serve latin-1 (or other 8-bit) content;
    latin-1 maps every byte so it never raises. Returns ``(text, charset)``
    so callers can report the encoding actually used.
    """
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"
