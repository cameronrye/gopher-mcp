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

from .helpers import describe_oserror

logger = structlog.get_logger(__name__)

READ_CHUNK = 65536
# Short probe deadline used once the size cap is reached, mirroring the Gemini
# transport. Waiting for EOF under the *overall* deadline instead meant a
# complete, exactly-``max_bytes`` response from a server that delays its close
# was thrown away as a generic timeout even though the whole body was already
# buffered; only an EOF within this window proves the response is complete.
PROBE_TIMEOUT_SECONDS = 1.0
# What ``errors="replace"`` substitutes for a byte that is not valid UTF-8.
_REPLACEMENT_CHAR = "\ufffd"


class GopherProtocolError(Exception):
    """Raised when a Gopher request cannot be completed."""


class GopherTimeoutError(GopherProtocolError):
    """Raised when a request did not finish within the deadline it was given.

    A distinct type, rather than a message the caller has to pattern-match, so
    the client can restate the failure against the timeout the *operator*
    configured: this transport is handed only whatever is left of that deadline
    after earlier phases, so the number it can name is a remainder.
    """


def build_request(selector: str, search: str | None = None) -> bytes:
    """Build the Gopher request line: ``selector[<TAB>search]<CR><LF>``.

    ``search`` is distinguished by ``is not None`` (not truthiness), so an
    explicit empty type-7 query still sends the ``<TAB>`` field -- an index
    server then sees an empty query rather than a bare selector.

    Encoded with ``surrogateescape`` so a selector that ``parse_gopher_url``
    recovered from a non-UTF-8 (latin-1) menu goes back on the wire as the exact
    bytes the server published, rather than as a fresh UTF-8 encoding of the
    characters those bytes happened to decode to. Only bytes >= 0x80 can arrive
    as surrogates, so this cannot smuggle a CR/LF/TAB past the caller's checks.
    """
    line = f"{selector}\t{search}" if search is not None else selector
    return line.encode("utf-8", errors="surrogateescape") + b"\r\n"


async def fetch_gopher(
    host: str,
    port: int,
    selector: str,
    search: str | None = None,
    *,
    max_bytes: int,
    timeout: float,
    connect_addresses: list[str] | None = None,
    truncate_at_max: bool = False,
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
        truncate_at_max: Return the first ``max_bytes`` bytes instead of raising
            when the server still has more to send. Used only by the robots.txt
            lookup, where RFC 9309 section 2.5 prescribes parsing a truncated
            prefix rather than rejecting the file.

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
            while total < max_bytes:
                chunk = await reader.read(min(READ_CHUNK, max_bytes - total))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)

            if truncate_at_max:
                return b"".join(chunks)

            # Hit the cap without EOF: probe one more byte under a short
            # deadline. A byte means the response is genuinely over the limit; a
            # probe that times out means the server has neither finished nor
            # closed, so the bytes in hand may be a mid-stream prefix -- report
            # that rather than either returning it as complete or burning the
            # whole request deadline waiting for a close that may never come.
            try:
                extra = await asyncio.wait_for(
                    reader.read(1), timeout=PROBE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                raise GopherProtocolError(
                    f"Response reached the maximum size of {max_bytes} bytes and "
                    f"the server did not close the connection; it may be truncated"
                ) from None
            if extra:
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
        raise GopherTimeoutError(f"Request timed out after {timeout} seconds") from e
    except GopherProtocolError:
        raise
    except OSError as e:
        # Report the errno's canonical text only, so the resolved IP/address
        # isn't echoed back to the caller (which would act as an
        # internal-reachability oracle). ``e.strerror`` is NOT safe for this:
        # asyncio builds every deferred connect failure as
        # ``OSError(err, f"Connect call failed {address}")``, so the sockaddr
        # ends up *inside* strerror. ``os.strerror(errno)`` is the address-free
        # description of the same failure.
        raise GopherProtocolError(f"Connection failed: {describe_oserror(e)}") from e


def decode_gopher_text(data: bytes) -> tuple[str, str]:
    """Decode Gopher bytes as UTF-8, falling back to latin-1.

    Legacy Gopher servers commonly serve latin-1 (or other 8-bit) content;
    latin-1 maps every byte so it never raises. Returns ``(text, charset)``
    so callers can report the encoding actually used.

    A body is only *called* latin-1 when it looks like one. Falling back on the
    first bad byte meant a single damaged byte -- a stray 0xFF, or a multi-byte
    character cut in half by the size cap -- re-read an otherwise valid UTF-8
    page as latin-1, turning every accented character in it into mojibake that
    was then cached for the whole TTL. So when the failures are sparse next to
    the non-ASCII characters that *did* decode, the UTF-8 reading is kept and
    only the bad bytes become U+FFFD; a genuinely 8-bit body, where essentially
    every non-ASCII byte fails, still decodes as latin-1.
    """
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    repaired = data.decode("utf-8", errors="replace")
    damaged = repaired.count(_REPLACEMENT_CHAR)
    intact = sum(
        1 for char in repaired if not char.isascii() and char != _REPLACEMENT_CHAR
    )
    if intact >= damaged:
        return repaired, "utf-8"
    return data.decode("latin-1"), "latin-1"
