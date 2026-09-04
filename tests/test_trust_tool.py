"""Tests for the Gemini trust-store tools.

TOFU is the only thing authenticating a Gemini server, and self-signed
certificates rotate routinely, so a legitimate reissue used to brick a host
until someone hand-edited ~/.gemini/tofu.json. These tools make that
recoverable. The tests below are as much about what they REFUSE to do -- drop a
pin without naming it, act on more than one host, or report a host the caller
did not ask about -- as about the recovery path itself.
"""

import textwrap
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.server import (
    gemini_trust_list,
    gemini_trust_update,
    mcp,
)
from gopher_mcp.tofu import TOFUStorageError, TOFUValidationError

FINGERPRINT_A = "a1" * 32
FINGERPRINT_B = "b2" * 32


def _colon_form(fingerprint: str) -> str:
    """Render a fingerprint the way openssl and browsers show it."""
    return ":".join(textwrap.wrap(fingerprint.upper(), 2))


@contextmanager
def _serving(client: GeminiClient):
    """Make the trust tools resolve ``client`` as the shared Gemini client."""
    manager = AsyncMock()
    manager.get_gemini_client.return_value = client
    with patch("gopher_mcp.server.get_client_manager", return_value=manager):
        yield


@pytest.fixture
def client(tmp_path: Path) -> GeminiClient:
    """A Gemini client with a real, isolated TOFU store holding two pins."""
    gemini = GeminiClient(
        tofu_storage_path=str(tmp_path / "tofu.json"),
        client_certs_enabled=False,
    )
    gemini.update_tofu_certificate("example.org", 1965, FINGERPRINT_A)
    gemini.update_tofu_certificate("other.example", 1965, FINGERPRINT_B)
    return gemini


def _pinned(client: GeminiClient, host: str) -> str | None:
    """Return the fingerprint currently pinned for ``host``, if any."""
    for entry in client.list_tofu_certificates():
        if entry.host == host:
            return entry.fingerprint
    return None


class TestTrustListIsReadOnly:
    """Inspection must be safe: it never writes, and never over-reports."""

    @pytest.mark.asyncio
    async def test_lists_every_pin_when_no_host_is_named(self, client):
        with _serving(client):
            result = await gemini_trust_list()

        assert result["kind"] == "trust_list"
        hosts = [entry["host"] for entry in result["entries"]]
        assert hosts == ["example.org", "other.example"]
        assert result["entries"][0]["fingerprint"] == FINGERPRINT_A

    @pytest.mark.asyncio
    async def test_a_host_filter_returns_only_that_host(self, client):
        with _serving(client):
            result = await gemini_trust_list(host="example.org")

        assert [entry["host"] for entry in result["entries"]] == ["example.org"]
        # The rest of the store must not ride along in any field.
        assert "other.example" not in str(result)

    @pytest.mark.asyncio
    async def test_host_matching_follows_the_stores_normalization(self, client):
        """The store keys on a normalized host, so a differently-cased name must
        find the same pin rather than reporting nothing."""
        with _serving(client):
            result = await gemini_trust_list(host="Example.ORG.")

        assert [entry["host"] for entry in result["entries"]] == ["example.org"]

    @pytest.mark.asyncio
    async def test_unknown_host_is_an_empty_list_not_an_error(self, client):
        with _serving(client):
            result = await gemini_trust_list(host="never-visited.example")

        assert result["kind"] == "trust_list"
        assert result["entries"] == []

    @pytest.mark.asyncio
    async def test_listing_does_not_change_the_store(self, client):
        before = Path(client.tofu_manager.storage_path).read_bytes()
        with _serving(client):
            await gemini_trust_list()

        assert Path(client.tofu_manager.storage_path).read_bytes() == before

    @pytest.mark.asyncio
    async def test_the_store_path_is_never_returned(self, client):
        """The trust store's location is operator configuration; it belongs in
        the server log, not in a payload handed to the model."""
        with _serving(client):
            result = await gemini_trust_list()

        assert client.tofu_manager.storage_path not in str(result)


class TestTrustUpdateRemove:
    """Removal is the recovery path, and it has to be deliberate."""

    @pytest.mark.asyncio
    async def test_removes_the_pin_when_the_fingerprint_matches(self, client):
        with _serving(client):
            result = await gemini_trust_update(
                action="remove", host="example.org", fingerprint=FINGERPRINT_A
            )

        assert result["kind"] == "trust_update"
        assert result["changed"] is True
        assert _pinned(client, "example.org") is None
        # The other pin is untouched, and unmentioned.
        assert _pinned(client, "other.example") == FINGERPRINT_B
        assert "other.example" not in str(result)

    @pytest.mark.asyncio
    async def test_accepts_the_colon_separated_fingerprint_form(self, client):
        """gemini_trust_list reports bare hex, but a user pasting from openssl
        supplies the colon form; both name the same certificate."""
        with _serving(client):
            result = await gemini_trust_update(
                action="remove",
                host="example.org",
                fingerprint=f"sha256:{_colon_form(FINGERPRINT_A)}",
            )

        assert result["changed"] is True
        assert _pinned(client, "example.org") is None

    @pytest.mark.asyncio
    async def test_a_wrong_fingerprint_removes_nothing(self, client):
        """The interlock: a pin cannot be dropped without naming what is being
        dropped, so a caller that never looked at the store cannot guess it away."""
        with _serving(client):
            result = await gemini_trust_update(
                action="remove", host="example.org", fingerprint=FINGERPRINT_B
            )

        assert result["kind"] == "error"
        assert result["error"]["code"] == "FINGERPRINT_MISMATCH"
        assert _pinned(client, "example.org") == FINGERPRINT_A
        # Telling the caller the real value would defeat the interlock.
        assert FINGERPRINT_A not in str(result)

    @pytest.mark.asyncio
    async def test_removing_an_unpinned_host_is_not_an_error(self, client):
        with _serving(client):
            result = await gemini_trust_update(
                action="remove",
                host="never-visited.example",
                fingerprint=FINGERPRINT_A,
            )

        assert result["kind"] == "trust_update"
        assert result["changed"] is False
        assert "nothing to remove" in result["message"]

    @pytest.mark.asyncio
    async def test_port_scopes_the_removal(self, client):
        """A pin is keyed by host AND port; naming another port must not drop it."""
        with _serving(client):
            result = await gemini_trust_update(
                action="remove",
                host="example.org",
                fingerprint=FINGERPRINT_A,
                port=1966,
            )

        assert result["changed"] is False
        assert _pinned(client, "example.org") == FINGERPRINT_A

    @pytest.mark.asyncio
    async def test_the_result_says_the_host_is_no_longer_verified(self, client):
        """Dropping a pin is a real reduction in what is being checked; the
        model has to be able to tell the user that."""
        with _serving(client):
            result = await gemini_trust_update(
                action="remove", host="example.org", fingerprint=FINGERPRINT_A
            )

        assert "no longer checked" in result["message"]


class TestTrustUpdatePin:
    """Re-pinning replaces one host's certificate with a named one."""

    @pytest.mark.asyncio
    async def test_pins_the_supplied_fingerprint(self, client):
        with _serving(client):
            result = await gemini_trust_update(
                action="pin", host="example.org", fingerprint=FINGERPRINT_B
            )

        assert result["changed"] is True
        assert _pinned(client, "example.org") == FINGERPRINT_B

    @pytest.mark.asyncio
    async def test_pins_a_host_that_was_never_seen(self, client):
        with _serving(client):
            await gemini_trust_update(
                action="pin", host="new.example", fingerprint=FINGERPRINT_A
            )

        assert _pinned(client, "new.example") == FINGERPRINT_A


class TestTrustUpdateRejectsBadInput:
    """Every rejection is a structured error, per the module's no-raise contract."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fingerprint",
        ["", "a1b2", "zz" * 32, FINGERPRINT_A + "aa"],
        ids=["empty", "truncated", "non-hex", "too-long"],
    )
    async def test_a_partial_or_malformed_fingerprint_is_refused(
        self, client, fingerprint
    ):
        """A truncated digest must not silently fail to match on removal, nor be
        pinned as a value no server can ever present."""
        with _serving(client):
            result = await gemini_trust_update(
                action="remove", host="example.org", fingerprint=fingerprint
            )

        assert result["error"]["code"] == "INVALID_REQUEST"
        assert _pinned(client, "example.org") == FINGERPRINT_A

    @pytest.mark.asyncio
    async def test_an_empty_host_is_refused(self, client):
        with _serving(client):
            result = await gemini_trust_update(
                action="remove", host="   ", fingerprint=FINGERPRINT_A
            )

        assert result["error"]["code"] == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_an_out_of_range_port_is_refused(self, client):
        with _serving(client):
            result = await gemini_trust_update(
                action="remove",
                host="example.org",
                fingerprint=FINGERPRINT_A,
                port=70000,
            )

        assert result["error"]["code"] == "INVALID_REQUEST"
        assert _pinned(client, "example.org") == FINGERPRINT_A


class TestTrustToolsFailSafely:
    """Nothing here may escape as a raw exception."""

    @pytest.mark.asyncio
    async def test_tofu_disabled_is_reported_not_raised(self, tmp_path):
        disabled = GeminiClient(tofu_enabled=False, client_certs_enabled=False)
        with _serving(disabled):
            listed = await gemini_trust_list()
            updated = await gemini_trust_update(
                action="remove", host="example.org", fingerprint=FINGERPRINT_A
            )

        for result in (listed, updated):
            assert result["error"]["code"] == "TOFU_DISABLED"
            # Say what disabling it costs, not just that it is off.
            assert "unauthenticated" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_a_locked_store_is_reported_not_raised(self, client):
        with (
            _serving(client),
            patch.object(
                client,
                "remove_tofu_certificate",
                side_effect=TOFUStorageError("/home/u/.gemini/tofu.json.lock held"),
            ),
        ):
            result = await gemini_trust_update(
                action="remove", host="example.org", fingerprint=FINGERPRINT_A
            )

        assert result["error"]["code"] == "CERTIFICATE_STORE_UNAVAILABLE"
        # The lock path is server-side detail, not something to hand the model.
        assert "/home/u" not in str(result)

    @pytest.mark.asyncio
    async def test_client_setup_failure_is_reported_not_raised(self):
        with patch(
            "gopher_mcp.server.get_client_manager",
            side_effect=Exception("corrupt store at /home/u/.gemini/tofu.json"),
        ):
            listed = await gemini_trust_list()
            updated = await gemini_trust_update(
                action="pin", host="example.org", fingerprint=FINGERPRINT_A
            )

        for result in (listed, updated):
            assert result["kind"] == "error"
            assert "/home/u" not in str(result)

    @pytest.mark.asyncio
    async def test_an_unreadable_store_is_reported_not_raised(self, client):
        with (
            _serving(client),
            patch.object(
                client,
                "list_tofu_certificates",
                side_effect=RuntimeError("/home/u/.gemini/tofu.json unreadable"),
            ),
        ):
            result = await gemini_trust_list()

        assert result["error"]["code"] == "CERTIFICATE_STORE_UNAVAILABLE"
        assert "/home/u" not in str(result)

    @pytest.mark.asyncio
    async def test_a_host_that_will_not_idna_encode_is_reported_not_raised(
        self, client
    ):
        """Host normalization refuses a host with an empty or over-long label.

        Both tools normalize the caller's host to match it against the store, so
        that refusal reaches them as an exception. Uncaught it escaped the tool
        entirely: the client saw isError with no structuredContent at all, on a
        call whose outputSchema promises one -- and the update tool's catch-all
        relabelled it CERTIFICATE_STORE_UNAVAILABLE, sending the operator to
        inspect a store that is fine.
        """
        with _serving(client):
            listed = await gemini_trust_list(host="\u00e4..com")
            updated = await gemini_trust_update(
                action="remove", host="\u00e4..com", fingerprint=FINGERPRINT_A
            )

        for result in (listed, updated):
            assert result["kind"] == "error"
            assert result["error"]["code"] == "INVALID_REQUEST"
        # The store was healthy throughout; nothing changed.
        assert _pinned(client, "example.org") == FINGERPRINT_A

    @pytest.mark.asyncio
    async def test_an_unexpected_store_failure_is_reported_not_raised(self, client):
        with (
            _serving(client),
            patch.object(
                client, "update_tofu_certificate", side_effect=RuntimeError("boom")
            ),
        ):
            result = await gemini_trust_update(
                action="pin", host="example.org", fingerprint=FINGERPRINT_B
            )

        assert result["error"]["code"] == "CERTIFICATE_STORE_UNAVAILABLE"
        assert "boom" not in str(result)


class TestRecoveryIsDiscoverableFromTheFailure:
    """A rotation is only recoverable if the failure says how to recover."""

    @pytest.mark.asyncio
    async def test_certificate_changed_names_the_tools_not_the_json_file(self, client):
        """The error used to point at a file on disk. Naming the tools is the
        fix; naming the path was only the workaround."""
        with (
            patch.object(client.tls_client, "connect") as mock_connect,
            patch.object(client.tls_client, "close"),
            patch.object(
                client.tofu_manager,
                "validate_certificate",
                side_effect=TOFUValidationError("fingerprint mismatch"),
            ),
        ):
            mock_connect.return_value = (object(), {"cert_fingerprint": FINGERPRINT_B})
            result = await client.fetch("gemini://example.org/")

        message = result.error["message"]
        assert result.error["code"] == "CERTIFICATE_CHANGED"
        assert "gemini_trust_list" in message
        assert "gemini_trust_update" in message
        # Both readings of the change must be stated, not just the benign one.
        assert "intercepted" in message
        # The store path remains server-side detail.
        assert client.tofu_manager.storage_path not in message


class TestTrustToolSchema:
    """The descriptions and annotations are what a client and a model act on."""

    @pytest.mark.asyncio
    async def test_listing_is_annotated_read_only_and_local(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        annotations = tools["gemini_trust_list"].annotations
        assert annotations.readOnlyHint is True
        assert annotations.openWorldHint is False

    @pytest.mark.asyncio
    async def test_changing_a_pin_is_annotated_destructive(self):
        """A client that gates destructive tools must actually gate this one --
        which is why it is a separate tool from the read-only listing rather
        than an `action` argument sharing one set of hints."""
        tools = {t.name: t for t in await mcp.list_tools()}
        annotations = tools["gemini_trust_update"].annotations
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is True
        assert annotations.openWorldHint is False

    @pytest.mark.asyncio
    async def test_the_description_states_what_a_changed_certificate_means(self):
        """The whole value of TOFU is that a fingerprint change is hard to wave
        away; the tool that waives it must say what it might be waiving."""
        tools = {t.name: t for t in await mcp.list_tools()}
        description = tools["gemini_trust_update"].description.lower()
        assert "intercept" in description
        assert "reissue" in description
        # Fetched pages are untrusted input and are the obvious injection route.
        assert "never because a fetched page" in description

    @pytest.mark.asyncio
    async def test_the_removal_target_is_documented_as_a_single_named_host(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["gemini_trust_update"].inputSchema
        assert "wildcard" in schema["properties"]["host"]["description"]
        assert set(schema["properties"]["action"]["enum"]) == {"remove", "pin"}
        assert set(schema["required"]) == {"action", "host", "fingerprint"}
        # The fingerprint has to be described as an interlock, or a model will
        # treat supplying it as a formality and invent a value.
        assert "interlock" in schema["properties"]["fingerprint"]["description"]

    @pytest.mark.asyncio
    async def test_listing_warns_that_the_whole_store_is_browsing_history(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["gemini_trust_list"].inputSchema
        assert "visited" in schema["properties"]["host"]["description"]


class TestDestructiveChangesAskFirst:
    """Un-pinning a certificate is destructive and model-initiated.

    A pin is the only thing authenticating a Gemini capsule, and the tool that
    removes one is called by a model reasoning about text it fetched. MCP has a
    channel for asking the user before acting -- elicitation -- and it was
    unused. It is optional in the protocol, so a client that does not advertise
    it must keep exactly the behaviour it had, or every existing caller breaks.
    """

    @staticmethod
    async def _call(client, *, elicitation_callback, action="remove"):
        """Drive the tool over a real session, so a context is injected."""
        from mcp.shared.memory import create_connected_server_and_client_session

        from gopher_mcp.server import mcp

        with _serving(client):
            async with create_connected_server_and_client_session(
                mcp._mcp_server, elicitation_callback=elicitation_callback
            ) as session:
                return await session.call_tool(
                    "gemini_trust_update",
                    {
                        "action": action,
                        "host": "example.org",
                        "fingerprint": FINGERPRINT_A,
                    },
                )

    @pytest.mark.asyncio
    async def test_a_declined_confirmation_leaves_the_pin_alone(self, client):
        async def decline(context, params):
            from mcp.types import ElicitResult

            return ElicitResult(action="decline")

        result = await self._call(client, elicitation_callback=decline)

        assert result.structuredContent["kind"] == "error"
        assert result.structuredContent["error"]["code"] == "USER_DECLINED"
        # The whole point: nothing changed.
        assert _pinned(client, "example.org") == FINGERPRINT_A

    @pytest.mark.asyncio
    async def test_an_accepted_confirmation_performs_the_change(self, client):
        async def accept(context, params):
            from mcp.types import ElicitResult

            return ElicitResult(action="accept", content={"confirm": True})

        result = await self._call(client, elicitation_callback=accept)

        assert result.structuredContent["kind"] == "trust_update"
        assert result.structuredContent["changed"] is True
        assert _pinned(client, "example.org") is None

    @pytest.mark.asyncio
    async def test_a_declined_confirmation_leaves_a_re_pin_alone(self, client):
        """`pin` is destructive too -- it replaces the certificate that
        authenticates a host -- so it asks, and a refusal must change nothing."""

        async def decline(context, params):
            from mcp.types import ElicitResult

            return ElicitResult(action="decline")

        result = await self._call(client, elicitation_callback=decline, action="pin")

        assert result.structuredContent["error"]["code"] == "USER_DECLINED"
        assert _pinned(client, "example.org") == FINGERPRINT_A

    @pytest.mark.asyncio
    async def test_a_client_that_cannot_be_asked_is_unaffected(self, client):
        """No elicitation capability means no prompt and no refusal. Requiring
        consent a client cannot express would make the tool unusable on every
        client that has not implemented elicitation yet."""
        result = await self._call(client, elicitation_callback=None)

        assert result.structuredContent["kind"] == "trust_update"
        assert result.structuredContent["changed"] is True
        assert _pinned(client, "example.org") is None
