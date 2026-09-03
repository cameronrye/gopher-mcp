"""The MCP wire contract: the envelope a real client receives.

Every other test in this suite calls the tool coroutines directly. That is the
right shape for asserting what a tool *decides*, but it skips the entire FastMCP
layer that turns a decision into a protocol message: the ``outputSchema`` each
tool advertises, the ``structuredContent`` body, the ``isError`` flag, and the
``result`` key the batch tools' list arrives wrapped in. None of that is written
by hand here -- it is derived from the tools' type annotations -- which is
exactly why it breaks *silently*. Drop a tool's return annotation and its
``structuredContent`` becomes ``None`` on every call while this repo's other
1400-odd tests stay green, because none of them ever looked at a wire message.

``create_connected_server_and_client_session`` connects a real client session to
the real server object over an in-memory transport, so what follows travels the
same request path a stdio client does, JSON-RPC framing and all.

These are also the guard for the mcp 2.x port this project is deliberately
holding off (``mcp>=1.28.1,<2`` in pyproject.toml). Last time the wire surface
had to be checked by hand-diffing raw JSON-RPC bytes, because nothing automated
it; the point of this file is that the port does not need that again.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from gopher_mcp.config import reset_config
from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.server import mcp

# The tool surface, in full. A tool added or removed without a deliberate
# decision changes the model's whole vocabulary, so the list is exhaustive
# rather than a membership check.
EXPECTED_TOOLS = {
    "gopher_fetch",
    "gemini_fetch",
    "gopher_batch_fetch",
    "gemini_batch_fetch",
    "gemini_trust_list",
    "gemini_trust_update",
    "gemini_client_cert_list",
    "gemini_client_cert_update",
}

# Enough menu entries to overrun the small render caps set below.
_MENU = (
    "".join(f"0File {i}\t/f{i}.txt\texample.com\t70\r\n" for i in range(6)) + ".\r\n"
).encode()


def _connected():
    """A client session speaking to this server over an in-memory transport."""
    return create_connected_server_and_client_session(mcp._mcp_server)


@asynccontextmanager
async def _offline_gopher(raw: bytes) -> AsyncIterator[None]:
    """Serve ``raw`` as the Gopher transport, with an allow-all robots policy.

    The robots probe travels the same transport as the content, so leaving it
    unstubbed would feed it the canned body as though it were a robots.txt --
    and spend one of the transport calls these tests count.
    """
    with (
        patch.object(GopherClient, "_fetch_robots", AsyncMock(return_value="")),
        patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=raw),
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _small_render_caps(monkeypatch: pytest.MonkeyPatch):
    """Tiny render caps and no throttling, for the whole module.

    The caps make truncation reachable with a handful of lines instead of a
    thousand, so the continuation fields can be asserted on a readable fixture.
    ``get_config()`` memoizes into a module global monkeypatch cannot restore,
    hence the explicit resets on both sides.
    """
    monkeypatch.setenv("GOPHER_MAX_MENU_ITEMS", "2")
    monkeypatch.setenv("GOPHER_MAX_RENDERED_CHARS", "10")
    monkeypatch.setenv("GOPHER_REQUESTS_PER_MINUTE", "0")
    monkeypatch.setenv("GEMINI_REQUESTS_PER_MINUTE", "0")
    reset_config()
    yield
    reset_config()


class TestToolListing:
    """What a client learns about the server before it calls anything."""

    @pytest.mark.asyncio
    async def test_every_tool_is_listed_with_an_output_schema(self):
        """A missing ``outputSchema`` is the visible symptom of the silent
        break this file exists for: FastMCP derives the schema from the return
        annotation, so a tool that loses one is advertised as returning nothing
        in particular and stops sending ``structuredContent`` at all."""
        async with _connected() as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}

        assert set(tools) == EXPECTED_TOOLS
        for name, tool in tools.items():
            assert tool.outputSchema is not None, f"{name} advertises no outputSchema"
            assert tool.description, f"{name} advertises no description"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name,kinds",
        [
            ("gopher_fetch", {"menu", "text", "binary", "error"}),
            (
                "gemini_fetch",
                {
                    "gemtext",
                    "success",
                    "binary",
                    "input",
                    "redirect",
                    "certificate",
                    "error",
                },
            ),
        ],
    )
    async def test_the_fetch_tools_advertise_their_real_result_kinds(self, name, kinds):
        """The fetch tools pass their result union as the advertised output, so
        the schema enumerates the exact ``kind`` values a client must branch on.
        Falling back to a bare ``dict[str, Any]`` would still be a valid schema
        and would still be listed -- it would just stop telling the model
        anything, which is why the kinds themselves are asserted."""
        async with _connected() as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}

        schema = tools[name].outputSchema
        assert schema is not None
        assert set(schema["discriminator"]["mapping"]) == kinds
        assert schema["discriminator"]["propertyName"] == "kind"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["gopher_batch_fetch", "gemini_batch_fetch"])
    async def test_the_batch_tools_advertise_the_result_wrapper(self, name):
        """A tool returning a list cannot put a bare array in
        ``structuredContent`` (the field is an object), so FastMCP wraps it
        under ``result``. Both the schema and the payload say so, and the tool
        docstrings promise it to the model -- pin it here rather than
        rediscovering it from a client bug report."""
        async with _connected() as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}

        schema = tools[name].outputSchema
        assert schema is not None
        assert schema["properties"]["result"]["type"] == "array"


class TestErrorFlagging:
    """``isError`` is the flag a host styles and retries on, and this server's
    tools never raise -- so it can only come from the payload."""

    @pytest.mark.asyncio
    async def test_a_refused_url_is_flagged_and_still_structured(self):
        """The no-raise contract means a rejected fetch is a *returned* error.
        It must arrive flagged (per the spec, a tool's own failures are reported
        inside the result with ``isError: true``) AND still carry the structured
        body, so a host that only reads the flag and a host that reads the body
        agree."""
        async with _connected() as session:
            result = await session.call_tool(
                "gopher_fetch", {"url": "http://example.com/"}
            )

        assert result.isError is True
        assert result.structuredContent is not None
        assert result.structuredContent["kind"] == "error"
        assert result.structuredContent["error"]["code"] == "INVALID_REQUEST"
        # The text block is what a client that ignores structuredContent reads,
        # and it must be the same fact, not a stack trace.
        assert "gopher://" in result.content[0].text

    @pytest.mark.asyncio
    async def test_a_successful_fetch_is_not_flagged(self):
        """The inverse: flagging must key off the payload's ``kind``, not off
        "a tool ran". A server that flags everything is as useless as one that
        flags nothing."""
        async with _offline_gopher(b"Hello, Gopher!"), _connected() as session:
            result = await session.call_tool(
                "gopher_fetch", {"url": "gopher://example.com/0/hi.txt"}
            )

        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["kind"] == "text"
        assert result.structuredContent["text"] == "Hello, Gop"

    @pytest.mark.asyncio
    async def test_a_wrong_typed_argument_is_a_protocol_error(self):
        """An argument the input schema rejects never reaches the tool, so this
        is a *protocol* failure rather than one of ours: it is flagged, it
        carries no structured body, and the message names the offending
        parameter. Distinct from the case above, which is the tool answering."""
        async with _connected() as session:
            result = await session.call_tool("gopher_fetch", {"url": 123})

        assert result.isError is True
        assert result.structuredContent is None
        assert "validation error" in result.content[0].text.lower()
        assert "url" in result.content[0].text

    @pytest.mark.asyncio
    async def test_a_batch_of_failures_is_not_flagged_as_a_failed_call(self):
        """A batch's failures are per item: some URLs can fail while the call
        itself succeeded, so there is no single flag to set honestly. Each
        element carries its own error instead, one per input URL and in order,
        so a caller can zip responses to requests."""
        async with _connected() as session:
            result = await session.call_tool(
                "gopher_batch_fetch",
                {"urls": ["http://one.example/", "http://two.example/"]},
            )

        assert result.isError is False
        assert result.structuredContent is not None
        items = result.structuredContent["result"]
        assert [item["kind"] for item in items] == ["error", "error"]
        assert [item["request_info"]["url"] for item in items] == [
            "http://one.example/",
            "http://two.example/",
        ]

    @pytest.mark.asyncio
    async def test_batch_results_arrive_under_the_result_key(self):
        """The wrapper the batch docstrings promise, on a successful batch."""
        async with _offline_gopher(b"Hello, Gopher!"), _connected() as session:
            result = await session.call_tool(
                "gopher_batch_fetch",
                {"urls": ["gopher://a.example/0/x.txt", "gopher://b.example/0/y.txt"]},
            )

        assert result.isError is False
        assert result.structuredContent is not None
        assert list(result.structuredContent) == ["result"]
        items = result.structuredContent["result"]
        assert isinstance(items, list)
        assert [item["kind"] for item in items] == ["text", "text"]
        # One text block per URL, alongside the structured array.
        assert len(result.content) == 2


class TestContinuationFieldsOnTheWire:
    """A truncated result has to be continuable *by a client*, which means the
    continuation fields have to survive serialization -- they are the newest
    part of this contract and the part with no other wire-level test."""

    @pytest.mark.asyncio
    async def test_a_truncated_menu_carries_its_continuation_fields(self):
        async with _offline_gopher(_MENU), _connected() as session:
            first = await session.call_tool(
                "gopher_fetch", {"url": "gopher://example.com/1/"}
            )
            payload = first.structuredContent
            assert payload is not None
            assert payload["kind"] == "menu"
            assert payload["truncated"] is True
            assert len(payload["items"]) == 2
            # Hitting the cap proves there are more items but not how many, so
            # no total is invented; `next_offset` is what makes the rest
            # reachable regardless.
            assert payload["total_items"] is None
            assert payload["next_offset"] == 2

            # And the offset really is accepted back over the wire.
            second = await session.call_tool(
                "gopher_fetch",
                {"url": "gopher://example.com/1/", "offset": payload["next_offset"]},
            )

        assert second.structuredContent is not None
        assert [item["title"] for item in second.structuredContent["items"]] == [
            "File 2",
            "File 3",
        ]

    @pytest.mark.asyncio
    async def test_a_truncated_text_body_carries_its_continuation_fields(self):
        async with _offline_gopher(b"0123456789abcdefghij"), _connected() as session:
            first = await session.call_tool(
                "gopher_fetch", {"url": "gopher://example.com/0/long.txt"}
            )
            payload = first.structuredContent
            assert payload is not None
            assert payload["text"] == "0123456789"
            assert payload["truncated"] is True
            # A text body's length IS known, so the total is reported -- in
            # characters, which is the unit `next_offset` speaks. `bytes` still
            # reports the full original size and is not an offset.
            assert payload["total_chars"] == 20
            assert payload["next_offset"] == 10

            second = await session.call_tool(
                "gopher_fetch",
                {
                    "url": "gopher://example.com/0/long.txt",
                    "offset": payload["next_offset"],
                },
            )

        assert second.structuredContent is not None
        assert second.structuredContent["text"] == "abcdefghij"
        assert second.structuredContent["truncated"] is False
        assert second.structuredContent["next_offset"] is None
