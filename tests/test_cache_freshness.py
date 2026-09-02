"""Tests for cache provenance on results and the per-request cache bypass.

Caching used to be invisible and uncontrollable: a response replayed from the
cache was indistinguishable from a fresh one, so a model asked "has the author
posted yet?" would confidently answer from a copy up to five minutes old. These
tests pin both halves of the fix -- the provenance a cached result carries, and
the `refresh` argument that skips the cache for one read.
"""

import re
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.models import (
    GeminiMimeType,
    GeminiSuccessResult,
    MenuResult,
    TextResult,
    mark_from_cache,
)
from gopher_mcp.server import gemini_fetch, gopher_fetch, mcp

# Every instant a result reports looks like this and nothing else.
_ISO_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")


def _reported_instant(reported: object) -> datetime:
    """Read a reported instant back, insisting on the one wire format.

    Results report instants as ISO-8601 UTC strings rather than epoch floats,
    so the assertions below compare instants. Parsing here (instead of calling
    the production `iso_utc`) keeps the expected value derived from the cache
    entry itself rather than from the code under test.
    """
    assert isinstance(reported, str), f"expected an ISO-8601 string, got {reported!r}"
    assert _ISO_UTC.fullmatch(reported), f"{reported!r} is not ISO-8601 UTC"
    return datetime.fromisoformat(reported)


def _gemini_result(content: str = "hello") -> GeminiSuccessResult:
    """Build a minimal successful Gemini result."""
    return GeminiSuccessResult(
        content=content,
        mimeType=GeminiMimeType(type="text", subtype="plain"),
        size=len(content),
        requestInfo={},
    )


class TestFreshResponsesAreMarkedFresh:
    """A response fetched during the call must not look like a replay."""

    @pytest.mark.asyncio
    async def test_gopher_fresh_response_has_no_cache_provenance(self):
        client = GopherClient(respect_robots_txt=False)
        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = TextResult(text="fresh", bytes=5)
            result = await client.fetch("gopher://example.com/0/a.txt")

        assert result.cached is False
        assert result.cached_at is None
        assert result.cache_age_seconds is None

    @pytest.mark.asyncio
    async def test_gemini_fresh_response_has_no_cache_provenance(self):
        client = GeminiClient(
            tofu_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
        )
        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = _gemini_result()
            result = await client.fetch("gemini://example.org/")

        assert result.cached is False
        assert result.cached_at is None
        assert result.cache_age_seconds is None


class TestCachedResponsesAreMarkedCached:
    """A replay says so, and says how old it is."""

    @pytest.mark.asyncio
    async def test_gopher_cache_hit_reports_when_the_copy_was_fetched(self):
        client = GopherClient(respect_robots_txt=False)
        url = "gopher://example.com/0/a.txt"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = TextResult(text="fresh", bytes=5)
            first = await client.fetch(url)
            # Backdate the stored entry rather than sleeping, so "when this
            # copy was fetched" and "now" are two minutes apart. The reported
            # instant has one-second resolution: without the gap, a result that
            # wrongly stamped the replay's own clock would read the same.
            client._cache[url].timestamp = time.time() - 120
            second = await client.fetch(url)

        assert mock_fetch.call_count == 1
        assert second.cached is True
        # The timestamp is when the copy was actually fetched, which is the
        # provenance already recorded on the entry -- not "now". Reported to
        # whole seconds, so the entry's own instant is truncated to match.
        entry_at = datetime.fromtimestamp(client._cache[url].timestamp, UTC)
        assert _reported_instant(second.cached_at) == entry_at.replace(microsecond=0)
        assert second.cache_age_seconds is not None
        assert second.cache_age_seconds >= 0
        # The fresh response must not be retroactively marked by the replay.
        assert first.cached is False

    @pytest.mark.asyncio
    async def test_gemini_cache_hit_reports_when_the_copy_was_fetched(self):
        client = GeminiClient(
            tofu_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
        )
        url = "gemini://example.org/"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = _gemini_result()
            first = await client.fetch(url)
            # Backdate the stored entry rather than sleeping, so "when this
            # copy was fetched" and "now" are two minutes apart. The reported
            # instant has one-second resolution: without the gap, a result that
            # wrongly stamped the replay's own clock would read the same.
            client._cache[url].timestamp = time.time() - 120
            second = await client.fetch(url)

        assert mock_fetch.call_count == 1
        assert second.cached is True
        entry_at = datetime.fromtimestamp(client._cache[url].timestamp, UTC)
        assert _reported_instant(second.cached_at) == entry_at.replace(microsecond=0)
        assert first.cached is False

    @pytest.mark.asyncio
    async def test_cache_age_grows_with_the_entry(self):
        """The age is measured from the entry, so a five-minute-old copy says so."""
        client = GopherClient(cache_ttl_seconds=3600, respect_robots_txt=False)
        url = "gopher://example.com/0/a.txt"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = TextResult(text="fresh", bytes=5)
            await client.fetch(url)
            # Backdate the stored entry rather than sleeping.
            client._cache[url].timestamp = time.time() - 300
            result = await client.fetch(url)

        assert result.cache_age_seconds == pytest.approx(300, abs=5)

    @pytest.mark.asyncio
    async def test_the_stored_entry_is_never_mutated_by_a_hit(self):
        """The cache hands back the instance it holds, so the marking has to be
        applied to a copy -- otherwise the entry (and every consumer still
        holding the original response) would be marked too."""
        client = GopherClient(respect_robots_txt=False)
        url = "gopher://example.com/1/"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = MenuResult(items=[])
            await client.fetch(url)
            await client.fetch(url)

        stored = client._cache[url].value
        assert stored.cached is False
        assert stored.cached_at is None

    def test_mark_from_cache_returns_a_copy(self):
        """The caller still passes a UNIX timestamp in; the copy reports it as
        an ISO-8601 UTC string, which is what the model reads."""
        response = MenuResult(items=[])
        marked = mark_from_cache(response, cached_at=1000.0)

        assert marked is not response
        assert marked.cached is True
        assert marked.cached_at == "1970-01-01T00:16:40+00:00"
        assert response.cached is False


class TestReportedInstantsShareOneFormat:
    """One payload must never spell the same concept two ways.

    `cached_at` and `request_info["timestamp"]` both name an instant, and a
    replayed result carries both at once. Reporting one as an ISO-8601 string
    while the other stayed an epoch float left a model doing arithmetic on one
    and string handling on the other, and invited it to read either as the
    other -- the same clash that made `expires` two formats across the two
    certificate tools. These assert on `model_dump()`, because the format only
    matters where the model actually reads it.
    """

    @pytest.mark.asyncio
    async def test_a_replayed_gopher_payload_reports_both_the_same_way(self):
        client = GopherClient(respect_robots_txt=False)
        url = "gopher://example.com/0/a.txt"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = TextResult(text="fresh", bytes=5)
            await client.fetch(url)
            replayed = await client.fetch(url)

        payload = replayed.model_dump()
        cached_at = _reported_instant(payload["cached_at"])
        requested_at = _reported_instant(payload["request_info"]["timestamp"])
        # Both name the same fetch -- the request that populated the entry --
        # so agreeing on format is not enough: they have to agree on the
        # instant too, or one of them is reporting the replay instead.
        assert abs((cached_at - requested_at).total_seconds()) <= 2

    @pytest.mark.asyncio
    async def test_a_replayed_gemini_payload_reports_both_the_same_way(self):
        client = GeminiClient(
            tofu_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
        )
        url = "gemini://example.org/"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = _gemini_result()
            await client.fetch(url)
            replayed = await client.fetch(url)

        payload = replayed.model_dump()
        cached_at = _reported_instant(payload["cached_at"])
        requested_at = _reported_instant(payload["request_info"]["timestamp"])
        assert abs((cached_at - requested_at).total_seconds()) <= 2

    def test_a_fresh_error_reports_its_instant_the_same_way(self):
        """Errors carry no cache provenance, so `request_info` is the only
        instant they report -- and it is the same spelling. This one is built
        by the shared error path every protocol funnels its failures through."""
        client = GopherClient(respect_robots_txt=False)

        result = client._error_result(
            "gopher://example.com/0/a.txt",
            "TIMEOUT",
            "The server did not answer in time.",
            TimeoutError("slow"),
        )

        _reported_instant(result.model_dump()["request_info"]["timestamp"])


class TestRefreshBypassesTheCache:
    """`refresh` skips the cached copy for one read without disabling caching."""

    @pytest.mark.asyncio
    async def test_gopher_refresh_refetches_and_repopulates(self):
        # Three reads of one URL. Robots is off, so there is no probe whose
        # rate-limit slot the fetch could inherit and each read would wait a
        # full politeness interval; this test is about the cache, not spacing.
        client = GopherClient(respect_robots_txt=False, requests_per_minute=0)
        url = "gopher://example.com/0/a.txt"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = TextResult(text="fresh", bytes=5)
            await client.fetch(url)
            refreshed = await client.fetch(url, refresh=True)
            # Backdate the stored entry rather than sleeping, so "when this
            # copy was fetched" and "now" are two minutes apart. The reported
            # instant has one-second resolution: without the gap, a result that
            # wrongly stamped the replay's own clock would read the same.
            client._cache[url].timestamp = time.time() - 120
            replayed = await client.fetch(url)

        # The bypassing fetch really went to the server ...
        assert mock_fetch.call_count == 2
        assert refreshed.cached is False
        # ... and its response is what later reads are served from.
        assert replayed.cached is True
        entry_at = datetime.fromtimestamp(client._cache[url].timestamp, UTC)
        assert _reported_instant(replayed.cached_at) == entry_at.replace(microsecond=0)

    @pytest.mark.asyncio
    async def test_gemini_refresh_refetches_and_repopulates(self):
        # See the Gopher twin above: three reads of one URL, and spacing them is
        # not what is under test.
        client = GeminiClient(
            tofu_enabled=False,
            client_certs_enabled=False,
            respect_robots_txt=False,
            requests_per_minute=0,
        )
        url = "gemini://example.org/"

        with patch.object(client, "_fetch_content") as mock_fetch:
            mock_fetch.return_value = _gemini_result()
            await client.fetch(url)
            refreshed = await client.fetch(url, refresh=True)
            replayed = await client.fetch(url)

        assert mock_fetch.call_count == 2
        assert refreshed.cached is False
        assert replayed.cached is True

    @pytest.mark.asyncio
    async def test_refresh_does_not_skip_the_robots_gate(self):
        """The bypass is a cache control, not a policy override: a disallowed
        resource must stay disallowed however the model asks for it."""
        client = GopherClient(respect_robots_txt=True)

        with (
            patch.object(client, "_fetch_robots") as mock_robots,
            patch.object(client, "_fetch_content") as mock_fetch,
        ):
            mock_robots.return_value = "User-agent: *\nDisallow: /"
            result = await client.fetch(
                "gopher://example.com/0/a.txt",
                refresh=True,
            )

        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        mock_fetch.assert_not_called()


class TestRefreshReachesTheClientFromTheTools:
    """The tools thread `refresh` through to the client that owns the cache."""

    @staticmethod
    def _mock_manager(attr: str) -> tuple[AsyncMock, AsyncMock]:
        client = AsyncMock()
        response = MagicMock()
        response.model_dump.return_value = {"kind": "text"}
        client.fetch.return_value = response
        manager = AsyncMock()
        getattr(manager, attr).return_value = client
        return manager, client

    @pytest.mark.asyncio
    async def test_gopher_fetch_passes_refresh_through(self):
        manager, client = self._mock_manager("get_gopher_client")
        with patch("gopher_mcp.server.get_client_manager", return_value=manager):
            await gopher_fetch("gopher://example.com/1/", refresh=True)

        client.fetch.assert_called_once_with("gopher://example.com/1/", refresh=True)

    @pytest.mark.asyncio
    async def test_gemini_fetch_passes_refresh_through(self):
        manager, client = self._mock_manager("get_gemini_client")
        with patch("gopher_mcp.server.get_client_manager", return_value=manager):
            await gemini_fetch("gemini://example.org/", refresh=True)

        client.fetch.assert_called_once_with("gemini://example.org/", refresh=True)

    @pytest.mark.asyncio
    async def test_refresh_defaults_to_false_alongside_an_input_answer(self):
        """The Gemini `input` path builds its own URL; `refresh` still rides along."""
        manager, client = self._mock_manager("get_gemini_client")
        with patch("gopher_mcp.server.get_client_manager", return_value=manager):
            await gemini_fetch("gemini://example.org/q", input="answer")

        client.fetch.assert_called_once_with(
            "gemini://example.org/q?answer", refresh=False
        )


class TestCacheSchemaReachesTheModel:
    """The parameter and field descriptions ARE the model-facing interface."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["gopher_fetch", "gemini_fetch"])
    async def test_refresh_is_an_optional_documented_param(self, name):
        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools[name].inputSchema
        assert "refresh" in schema["properties"]
        assert "refresh" not in schema.get("required", [])
        description = schema["properties"]["refresh"]["description"]
        # It must say both when to use it and when not to, or the model will
        # either never refresh or refresh on every hop.
        assert "current state" in description
        assert "browsing" in description

    @pytest.mark.parametrize("model", [MenuResult, TextResult, GeminiSuccessResult])
    def test_cache_fields_describe_themselves(self, model):
        fields = model.model_fields
        for name in ("cached", "cached_at", "cache_age_seconds"):
            assert fields[name].description, f"{name} must describe itself"
        assert "refresh=true" in fields["cache_age_seconds"].description

    @pytest.mark.asyncio
    async def test_instructions_tell_the_model_cached_results_exist(self):
        assert "cached" in mcp.instructions
        assert "refresh=true" in mcp.instructions
