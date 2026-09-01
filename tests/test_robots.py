"""Tests for robot exclusion (robots.txt) support.

Covers the parser (which deliberately implements the original 1994 grammar
rather than RFC 9309), the caching gate, and the integration of both into the
Gopher and Gemini clients.
"""

import asyncio
import re
from unittest.mock import patch

import pytest

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.models import (
    ErrorResult,
    GeminiErrorResult,
    GeminiSuccessResult,
    TextResult,
)
from gopher_mcp.robots import (
    AI_AGENT_TOKENS,
    GEMINI_TOKENS,
    GOPHER_TOKENS,
    RobotsGate,
    RobotsUnavailable,
    _matches,
    gopher_candidate_paths,
    parse_robots,
)


class _FakeClock:
    """A controllable monotonic clock."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class TestParser:
    """The 1994 grammar: only #, User-agent: and Disallow: are recognised."""

    def test_basic_group(self):
        policy = parse_robots("User-agent: *\nDisallow: /private/\n")
        assert policy.groups == {"*": ["/private/"]}

    def test_allow_is_ignored(self):
        """The highest-value regression test in this file.

        The Gemini companion spec uses the 1994 grammar, which has no ``Allow:``
        and says "All other lines are ignored". An RFC 9309 parser would honour
        the Allow and permit /public/, i.e. behave MORE permissively than the
        capsule author intended.
        """
        policy = parse_robots("User-agent: *\nDisallow: /\nAllow: /public/\n")
        assert policy.groups == {"*": ["/"]}
        assert policy.is_allowed(["/public/page"], GEMINI_TOKENS) is False

    def test_other_fields_ignored(self):
        policy = parse_robots(
            "User-agent: *\n"
            "Crawl-delay: 10\n"
            "Sitemap: gemini://example.com/sitemap\n"
            "Disallow: /x\n"
        )
        assert policy.groups == {"*": ["/x"]}

    def test_comments_and_blank_lines(self):
        policy = parse_robots(
            "# leading comment\n\nUser-agent: indexer  # trailing\nDisallow: /a\n"
        )
        assert policy.groups == {"indexer": ["/a"]}

    def test_tokens_are_lowercased(self):
        policy = parse_robots("User-Agent: ClaudeBot\nDisallow: /\n")
        assert "claudebot" in policy.groups

    def test_consecutive_agents_share_rules(self):
        policy = parse_robots(
            "User-agent: indexer\nUser-agent: archiver\nDisallow: /no\n"
        )
        assert policy.groups == {"indexer": ["/no"], "archiver": ["/no"]}

    def test_disallow_closes_the_agent_run(self):
        """A User-agent after a Disallow starts a fresh record."""
        policy = parse_robots(
            "User-agent: a\nDisallow: /one\nUser-agent: b\nDisallow: /two\n"
        )
        assert policy.groups == {"a": ["/one"], "b": ["/two"]}

    def test_empty_disallow_means_allow_everything(self):
        policy = parse_robots("User-agent: *\nDisallow:\n")
        assert policy.groups == {"*": []}
        assert policy.is_allowed(["/anything"], GEMINI_TOKENS) is True

    def test_disallow_without_agent_is_dropped(self):
        assert parse_robots("Disallow: /orphan\n").groups == {}

    def test_garbage_parses_to_allow_all(self):
        """A Gopher server has no way to say "no such selector".

        Whatever it returns instead -- a menu, an error document, HTML -- must
        collapse to an empty policy rather than being misread as rules.
        """
        menu = (
            "iThis is a Gopher menu\t\terror.host\t1\r\n1Some dir\t/dir\thost\t70\r\n"
        )
        assert parse_robots(menu).groups == {}
        assert parse_robots("<html><body>404 Not Found</body></html>").groups == {}
        assert parse_robots("").groups == {}


class TestMatching:
    def test_prefix_match(self):
        policy = parse_robots("User-agent: *\nDisallow: /priv\n")
        assert policy.is_allowed(["/private/x"], ("*",)) is False
        assert policy.is_allowed(["/public/x"], ("*",)) is True

    def test_wildcard_and_anchor(self):
        policy = parse_robots("User-agent: *\nDisallow: /*.gmi$\n")
        assert policy.is_allowed(["/a/b.gmi"], ("*",)) is False
        assert policy.is_allowed(["/a/b.txt"], ("*",)) is True


class TestWildcardMatcher:
    """The greedy scan that stands in for a translated regular expression.

    ``_matches`` trades ``re`` for a linear leftmost scan to stay ReDoS-safe
    (see :func:`_matches`), so its equivalence to ``re.match`` of the same
    pattern is a security property: under-matching would let the client fetch
    resources a capsule disallowed. Every case here is cross-checked against
    the regex the pattern translates to.
    """

    @staticmethod
    def _via_regex(rule: str, path: str) -> bool:
        """Match ``path`` the way a naive regex translation of ``rule`` would."""
        anchored = rule.endswith("$")
        pattern = rule[:-1] if anchored else rule
        translated = ".*".join(re.escape(part) for part in pattern.split("*"))
        return re.match(translated + ("$" if anchored else ""), path) is not None

    @pytest.mark.parametrize(
        ("rule", "path", "expected"),
        [
            # Leading segment must sit at the start of the path.
            ("/a*b", "/ab", True),
            ("/a*b", "/xa/b", False),
            ("/a*b", "/", False),
            # A single interior literal segment between two stars.
            ("/a*mid*end", "/a-mid-end", True),
            ("/a*mid*end", "/a-mid-and-then-end", True),
            ("/a*mid*end", "/a-end", False),
            ("/a*mid*end", "/a-mid-nope", False),
            # The interior segment may not be found before the previous match.
            ("/x*ab*ab", "/x-ab", False),
            ("/x*ab*ab", "/x-abab", True),
            # Several interior segments, matched leftmost in order.
            ("/*a*b*c", "/zzazzbzzc", True),
            ("/*a*b*c", "/zzczzbzza", False),
            # A trailing star absorbs whatever is left, including nothing.
            ("/private*", "/private", True),
            ("/private*", "/private/notes.gmi", True),
            ("/private*", "/public", False),
            ("*", "/anything", True),
            # Adjacent stars must behave like a single one.
            ("/a**b", "/a-b", True),
            ("/a**b", "/b-a", False),
            ("/*****", "/deep/path", True),
            # Overlapping literals: the tail may not reuse characters the head
            # already consumed.
            ("/aaa*aaa", "/aaaaa", False),
            ("/aaa*aaa", "/aaaaaa", True),
            ("/ab*b", "/ab", False),
            ("/ab*b", "/abb", True),
            # `$` anchoring combined with stars.
            ("/*.gmi$", "/a/b.gmi", True),
            ("/*.gmi$", "/a/b.gmi.txt", False),
            ("/a*b$", "/ab", True),
            ("/a*b$", "/abc", False),
            ("/ab*b$", "/ab", False),
            ("/*aa*aa$", "/aaa", False),
            ("/*aa*aa$", "/aaaa", True),
            ("/*ab*ba$", "/abba", True),
            # No star at all: prefix match, or exact match when anchored.
            ("/priv", "/private/x", True),
            ("/priv$", "/private/x", False),
            ("/priv$", "/priv", True),
        ],
    )
    def test_matches_agrees_with_the_regex_it_replaces(self, rule, path, expected):
        assert _matches(rule, path) is expected
        assert self._via_regex(rule, path) is expected

    def test_empty_rule_never_matches(self):
        """``Disallow:`` with no value is the 1994 way to say "nothing"."""
        assert _matches("", "/anything") is False

    def test_specific_token_beats_catch_all(self):
        policy = parse_robots(
            "User-agent: *\nDisallow: /\nUser-agent: webproxy\nDisallow:\n"
        )
        # The webproxy group is empty, so nothing is disallowed for us even
        # though the catch-all forbids everything.
        assert policy.is_allowed(["/anything"], GEMINI_TOKENS) is True

    def test_union_of_matching_tokens_is_most_restrictive(self):
        """The companion spec's own tie-breaker for overlapping categories."""
        policy = parse_robots(
            "User-agent: webproxy\nDisallow: /a\nUser-agent: indexer\nDisallow: /b\n"
        )
        assert policy.is_allowed(["/a"], GEMINI_TOKENS) is False
        assert policy.is_allowed(["/b"], GEMINI_TOKENS) is False
        assert policy.is_allowed(["/c"], GEMINI_TOKENS) is True

    def test_unmatched_agent_is_ignored(self):
        policy = parse_robots("User-agent: veronica\nDisallow: /\n")
        # We never claim the `veronica` token, so its rules are not ours.
        assert policy.is_allowed(["/x"], GOPHER_TOKENS) is True

    def test_project_token_is_honoured(self):
        policy = parse_robots("User-agent: gopher-mcp\nDisallow: /secret\n")
        assert policy.is_allowed(["/secret/x"], GOPHER_TOKENS) is False

    def test_empty_policy_allows(self):
        assert parse_robots("").is_allowed(["/x"], GOPHER_TOKENS) is True


class TestGopherCandidatePaths:
    def test_both_spellings_generated(self):
        """quux.org lists rules against the selector AND the typed URI path."""
        paths = gopher_candidate_paths("1", "/Archives/mirrors")
        assert "/Archives/mirrors" in paths
        assert "/1/Archives/mirrors" in paths
        assert "1/Archives/mirrors" in paths

    def test_selector_without_leading_slash(self):
        assert "/foo" in gopher_candidate_paths("0", "foo")

    def test_rule_written_either_way_matches(self):
        policy = parse_robots("User-agent: *\nDisallow: 1/Archives/\n")
        paths = gopher_candidate_paths("1", "/Archives/mirrors")
        assert policy.is_allowed(paths, ("*",)) is False


class TestRobotsUnavailableBackoff:
    """An unreachable robots.txt must not be re-probed on every single fetch.

    A failure is deliberately not cached for the full TTL (a temporary outage
    should be retried), but with robots on by default that left every request to
    a dead host -- including one that would otherwise be served from the content
    cache -- paying a fresh connect timeout, and on Gopher failing open and
    proceeding anyway. A short backoff keeps the retry without the per-request
    cost.
    """

    async def test_failure_is_not_reprobed_within_the_backoff(self):
        calls = []
        now = [1000.0]

        async def fetcher(host, port):
            calls.append((host, port))
            raise RobotsUnavailable("connect timeout")

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=86400,
            fail_closed=False,
            clock=lambda: now[0],
        )

        assert (await gate.allows("dead.example", 70, ["/x"])).allowed is True
        assert (await gate.allows("dead.example", 70, ["/y"])).allowed is True
        assert (await gate.allows("dead.example", 70, ["/z"])).allowed is True
        assert len(calls) == 1, "an unreachable host was re-probed within the backoff"

    async def test_failure_is_retried_after_the_backoff(self):
        calls = []
        now = [1000.0]

        async def fetcher(host, port):
            calls.append((host, port))
            raise RobotsUnavailable("connect timeout")

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=86400,
            fail_closed=False,
            clock=lambda: now[0],
        )

        await gate.allows("dead.example", 70, ["/x"])
        now[0] += RobotsGate.FAILURE_BACKOFF_SECONDS + 1
        await gate.allows("dead.example", 70, ["/x"])
        assert len(calls) == 2, "the backoff must expire, not pin the failure"

    async def test_backoff_is_far_shorter_than_the_policy_ttl(self):
        """The point is a retry, not a 24h cache of a transient outage."""
        assert 0 < RobotsGate.FAILURE_BACKOFF_SECONDS <= 300

    async def test_a_recovered_host_is_cached_normally(self):
        state = {"fail": True}
        calls = []
        now = [1000.0]

        async def fetcher(host, port):
            calls.append(1)
            if state["fail"]:
                raise RobotsUnavailable("temporary")
            return "User-agent: *\nDisallow: /private\n"

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=86400,
            fail_closed=False,
            clock=lambda: now[0],
        )

        await gate.allows("flaky.example", 70, ["/x"])
        state["fail"] = False
        now[0] += RobotsGate.FAILURE_BACKOFF_SECONDS + 1
        assert (await gate.allows("flaky.example", 70, ["/private"])).allowed is False
        # Recovered: the real policy is now cached for the full TTL, and the
        # spent backoff entry must not force another probe.
        now[0] += 1
        assert (await gate.allows("flaky.example", 70, ["/private"])).allowed is False
        assert len(calls) == 2


class TestRobotsGate:
    async def test_allows_when_no_policy(self):
        async def fetcher(host, port):
            return None

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is True

    async def test_denies_on_disallow(self):
        async def fetcher(host, port):
            return "User-agent: *\nDisallow: /\n"

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is False

    async def test_result_is_cached(self):
        calls = []

        async def fetcher(host, port):
            calls.append((host, port))
            return "User-agent: *\nDisallow: /no\n"

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        for _ in range(5):
            await gate.allows("example.com", 70, ["/ok"])
        assert len(calls) == 1

    async def test_concurrent_lookups_fetch_once(self):
        """A batch of 10 URLs on one host must not trigger 10 robots fetches."""
        calls = []

        async def fetcher(host, port):
            calls.append(host)
            await asyncio.sleep(0.01)
            return "User-agent: *\nDisallow: /no\n"

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        await asyncio.gather(
            *[gate.allows("example.com", 70, [f"/p{i}"]) for i in range(10)]
        )
        assert len(calls) == 1

    async def test_cache_expires(self):
        calls = []
        clock = _FakeClock()

        async def fetcher(host, port):
            calls.append(1)
            return "User-agent: *\nDisallow: /no\n"

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=100,
            fail_closed=False,
            clock=clock,
        )
        await gate.allows("example.com", 70, ["/ok"])
        clock.t += 50
        await gate.allows("example.com", 70, ["/ok"])
        assert len(calls) == 1
        clock.t += 100  # past the TTL
        await gate.allows("example.com", 70, ["/ok"])
        assert len(calls) == 2

    async def test_hosts_are_cached_separately(self):
        async def fetcher(host, port):
            return "User-agent: *\nDisallow: /\n" if host == "closed.example" else None

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        assert (await gate.allows("closed.example", 70, ["/x"])).allowed is False
        assert (await gate.allows("open.example", 70, ["/x"])).allowed is True

    async def test_port_is_part_of_the_cache_key(self):
        async def fetcher(host, port):
            return "User-agent: *\nDisallow: /\n" if port == 70 else None

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is False
        assert (await gate.allows("example.com", 7070, ["/x"])).allowed is True

    async def test_fail_open_on_unavailable(self):
        async def fetcher(host, port):
            raise RobotsUnavailable("boom")

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is True

    async def test_fail_closed_on_unavailable(self):
        """RFC 9309 s2.3.1.4: a temporary failure means a complete disallow."""

        async def fetcher(host, port):
            raise RobotsUnavailable("boom")

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=True
        )
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is False

    async def test_unavailable_falls_back_to_stale_policy(self):
        """A blip must not throw away a policy we already fetched."""
        state = {"fail": False}

        async def fetcher(host, port):
            if state["fail"]:
                raise RobotsUnavailable("blip")
            return "User-agent: *\nDisallow: /no\n"

        clock = _FakeClock()
        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=10,
            fail_closed=True,
            clock=clock,
        )
        assert (await gate.allows("example.com", 70, ["/ok"])).allowed is True
        clock.t += 100  # expire the entry
        state["fail"] = True
        # Stale rules still apply rather than blanket-denying.
        assert (await gate.allows("example.com", 70, ["/ok"])).allowed is True
        assert (await gate.allows("example.com", 70, ["/no"])).allowed is False

    async def test_transient_failure_is_not_cached_for_the_ttl(self):
        """A blip must not disable robots checking for the whole TTL.

        It is re-probed after FAILURE_BACKOFF_SECONDS, not on the very next
        request -- see TestRobotsUnavailableBackoff for why the immediate retry
        had to go. The TTL here is 600s and the backoff 60s, so a retry after
        the backoff proves the failure was not pinned to the TTL.
        """
        calls = []
        state = {"fail": True}
        now = [1000.0]

        async def fetcher(host, port):
            calls.append(1)
            if state["fail"]:
                raise RobotsUnavailable("blip")
            return "User-agent: *\nDisallow:\n"

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=600,
            fail_closed=True,
            clock=lambda: now[0],
        )
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is False
        state["fail"] = False
        now[0] += RobotsGate.FAILURE_BACKOFF_SECONDS + 1
        assert (await gate.allows("example.com", 70, ["/x"])).allowed is True
        assert len(calls) == 2
        assert RobotsGate.FAILURE_BACKOFF_SECONDS < 600


class TestGopherClientIntegration:
    async def test_enabled_by_default(self):
        """Flipped in 0.7.0: a bare client now consults robots.txt."""
        client = GopherClient()
        assert client.respect_robots_txt is True
        assert client._robots_gate is not None
        await client.close()

    async def test_no_robots_fetch_when_disabled(self):
        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=False
        )
        assert client._robots_gate is None
        with patch.object(client, "_fetch_robots") as robots:
            client._fetch_content = _fake_gopher_content()
            await client.fetch("gopher://example.com/0/page")
            robots.assert_not_called()
        await client.close()

    async def test_disallow_blocks_the_fetch(self):
        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gopher_content()
        with patch.object(
            client, "_fetch_robots", return_value="User-agent: *\nDisallow: /\n"
        ):
            result = await client.fetch("gopher://example.com/0/page")
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()

    async def test_allowed_path_still_fetches(self):
        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gopher_content()
        with patch.object(
            client, "_fetch_robots", return_value="User-agent: *\nDisallow: /private/\n"
        ):
            result = await client.fetch("gopher://example.com/0/public/page")
        assert isinstance(result, TextResult)
        await client.close()

    async def test_gate_beats_the_content_cache(self):
        """A Disallow must withhold content cached from an earlier run."""
        # Robots off for the warm-up: the gate is switched on explicitly below,
        # with a stubbed fetcher. Left at the 0.7.0 default it would be on for
        # the warm-up too, and its unstubbed fetcher would make a real
        # connection to example.com:70 that stalls for the full 30s timeout
        # before failing open.
        client = GopherClient(requests_per_minute=0, respect_robots_txt=False)
        client._fetch_content = _fake_gopher_content()
        url = "gopher://example.com/0/page"

        # Warm the cache with robots checking off.
        assert isinstance(await client.fetch(url), TextResult)

        client.respect_robots_txt = True
        from gopher_mcp.robots import GOPHER_TOKENS as _t

        async def deny(host, port):
            return "User-agent: *\nDisallow: /\n"

        client._robots_gate = RobotsGate(
            fetcher=deny, tokens=_t, ttl_seconds=60, fail_closed=False
        )
        result = await client.fetch(url)
        assert isinstance(result, ErrorResult)
        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()

    async def test_robots_lookup_does_not_deadlock_at_concurrency_one(self):
        """The lookup must not run inside the fetch semaphore.

        ``_bounded_fetch`` holds ``_fetch_semaphore``; a robots fetch issued
        from within it would self-deadlock whenever the cap is 1.
        """
        client = GopherClient(
            cache_enabled=False,
            requests_per_minute=0,
            max_concurrent_requests=1,
            respect_robots_txt=True,
        )
        client._fetch_content = _fake_gopher_content()
        with patch.object(
            client, "_fetch_robots", return_value="User-agent: *\nDisallow: /no\n"
        ):
            result = await asyncio.wait_for(
                client.fetch("gopher://example.com/0/page"), timeout=2.0
            )
        assert isinstance(result, TextResult)
        await client.close()

    async def test_robots_fetch_does_not_recurse(self):
        """The gate's fetcher must not re-enter the gated fetch path."""
        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gopher_content()
        calls = []

        async def counting_fetch_gopher(*args, **kwargs):
            calls.append(args)
            return b"User-agent: *\nDisallow: /no\n"

        with patch(
            "gopher_mcp.gopher_client.validate_target", return_value=["93.184.216.34"]
        ):
            with patch(
                "gopher_mcp.gopher_client.fetch_gopher",
                side_effect=counting_fetch_gopher,
            ):
                result = await asyncio.wait_for(
                    client.fetch("gopher://example.com/0/page"), timeout=2.0
                )
        assert isinstance(result, TextResult)
        # Exactly one robots.txt request, for the root selector.
        assert len(calls) == 1
        assert calls[0][2] == "/robots.txt"
        await client.close()

    async def test_unreachable_host_fails_open(self):
        """Gopher cannot distinguish "no file" from "no server"."""
        from gopher_mcp.gopher_transport import GopherProtocolError

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gopher_content()
        with patch(
            "gopher_mcp.gopher_client.validate_target", return_value=["93.184.216.34"]
        ):
            with patch(
                "gopher_mcp.gopher_client.fetch_gopher",
                side_effect=GopherProtocolError("timed out"),
            ):
                result = await client.fetch("gopher://example.com/0/page")
        assert isinstance(result, TextResult)
        await client.close()


class TestGeminiClientIntegration:
    async def test_enabled_by_default(self):
        """Flipped in 0.7.0: a bare client now consults robots.txt."""
        client = GeminiClient()
        assert client.respect_robots_txt is True
        assert client._robots_gate is not None
        await client.close()

    async def test_disallow_blocks_the_fetch(self):
        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gemini_content()
        with patch.object(
            client, "_fetch_robots", return_value="User-agent: *\nDisallow: /\n"
        ):
            result = await client.fetch("gemini://example.com/page")
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()

    async def test_webproxy_token_is_honoured(self):
        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gemini_content()
        with patch.object(
            client,
            "_fetch_robots",
            return_value="User-agent: webproxy\nDisallow: /private/\n",
        ):
            blocked = await client.fetch("gemini://example.com/private/x")
            allowed = await client.fetch("gemini://example.com/public/x")
        assert isinstance(blocked, GeminiErrorResult)
        assert isinstance(allowed, GeminiSuccessResult)
        await client.close()

    async def test_status_51_means_no_policy(self):
        """Gemini inverts HTTP's numbering: 5x is permanent, and 51 NOT FOUND
        is simply how a capsule says it has no robots.txt."""
        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gemini_content(
            robots=GeminiErrorResult(
                error={"code": "NOT_FOUND", "message": "not found", "status": 51}
            )
        )
        result = await client.fetch("gemini://example.com/page")
        assert isinstance(result, GeminiSuccessResult)
        await client.close()

    async def test_status_4x_fails_closed(self):
        """A temporary failure is RFC 9309 s2.3.1.4's complete disallow."""
        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gemini_content(
            robots=GeminiErrorResult(
                error={"code": "UNAVAILABLE", "message": "temp", "status": 41}
            )
        )
        result = await client.fetch("gemini://example.com/page")
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()

    async def test_robots_request_is_size_capped(self):
        from gopher_mcp.robots import ROBOTS_MAX_BYTES

        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        seen = {}

        async def fake_fetch_content(
            parsed_url, *, max_bytes=None, apply_content_policy=True, **kwargs
        ):
            if parsed_url.path == "/robots.txt":
                seen["max_bytes"] = max_bytes
                return GeminiErrorResult(
                    error={"code": "NOT_FOUND", "message": "x", "status": 51}
                )
            return _gemini_success()

        client._fetch_content = fake_fetch_content
        await client.fetch("gemini://example.com/page")
        assert seen["max_bytes"] == ROBOTS_MAX_BYTES
        await client.close()

    async def test_robots_lookup_does_not_deadlock_at_concurrency_one(self):
        """The lookup must bypass ``_bounded_fetch``, which holds the semaphore."""
        client = GeminiClient(
            cache_enabled=False,
            requests_per_minute=0,
            max_concurrent_requests=1,
            respect_robots_txt=True,
        )
        client._fetch_content = _fake_gemini_content(
            robots=GeminiErrorResult(
                error={"code": "NOT_FOUND", "message": "x", "status": 51}
            )
        )
        result = await asyncio.wait_for(
            client.fetch("gemini://example.com/page"), timeout=2.0
        )
        assert isinstance(result, GeminiSuccessResult)
        await client.close()


class TestBatchToolsAreGated:
    """The batch tools route through client.fetch, so the gate covers them."""

    async def test_gopher_batch_is_blocked(self):
        from gopher_mcp import server

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gopher_content()

        class _Manager:
            async def get_gopher_client(self):
                return client

        with patch.object(
            client, "_fetch_robots", return_value="User-agent: *\nDisallow: /\n"
        ):
            with patch.object(server, "get_client_manager", return_value=_Manager()):
                results = await server.gopher_batch_fetch(
                    [f"gopher://example.com/0/p{i}" for i in range(3)]
                )
        assert len(results) == 3
        for item in results:
            assert item["error"]["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()


# --- helpers ---------------------------------------------------------------


def _fake_gopher_content():
    async def fake(_parsed_url):
        return TextResult(bytes=2, text="hi")

    return fake


def _gemini_success():
    return GeminiSuccessResult(
        mimeType={"type": "text", "subtype": "plain", "full_type": "text/plain"},
        content="hi",
        size=2,
    )


def _fake_gemini_content(robots=None):
    async def fake(parsed_url, *, max_bytes=None, apply_content_policy=True, **kwargs):
        if parsed_url.path == "/robots.txt":
            if robots is None:
                raise AssertionError("unexpected robots fetch")
            return robots
        return _gemini_success()

    return fake


class TestGateMemoryIsBounded:
    """An open-world fetcher sees unbounded distinct hosts."""

    async def test_expired_entries_are_swept(self):
        clock = _FakeClock()

        async def fetcher(host, port):
            return "User-agent: *\nDisallow: /no\n"

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=10,
            fail_closed=False,
            clock=clock,
        )
        gate._sweep_threshold = 50

        for i in range(60):
            await gate.allows(f"host{i}.example", 70, ["/ok"])
        clock.t += 1000  # expire everything

        # The next lookup past the threshold triggers the sweep.
        for i in range(60, 120):
            await gate.allows(f"host{i}.example", 70, ["/ok"])

        assert len(gate._cache) <= 120
        assert len(gate._locks) <= gate._sweep_threshold + 1

    async def test_sweep_never_drops_a_lock_with_waiters(self):
        """A lock released this tick still has coroutines queued on it.

        ``asyncio.Lock.release()`` clears the flag and only *schedules* the
        first waiter, so for one loop iteration a contended lock reports
        ``locked() == False``. Sweeping on that flag dropped the lock while a
        waiter still held it, the next caller ``setdefault``-created a second
        lock for the same host, and both fetched ``/robots.txt`` concurrently --
        the duplicate outbound request the gate exists to prevent. A failed
        fetch is the worst case, since ``RobotsUnavailable`` is not cached.

        The interleaving below is deterministic: ``first.set()`` queues the
        holder's resumption ahead of the third caller, so the third caller runs
        (and sweeps) in exactly the window between the release and the waiter
        waking up.
        """
        started = asyncio.Event()
        first = asyncio.Event()
        inflight = 0
        peak = 0
        calls = 0

        async def fetcher(host, port):
            nonlocal inflight, peak, calls
            calls += 1
            mine = calls
            inflight += 1
            peak = max(peak, inflight)
            if mine == 1:
                started.set()
                await first.wait()
            else:
                await asyncio.sleep(0)
            inflight -= 1
            raise RobotsUnavailable("blip")

        gate = RobotsGate(
            fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
        )
        gate._sweep_threshold = 0  # sweep on every lookup

        holder = asyncio.create_task(gate.allows("example.com", 70, ["/a"]))
        await started.wait()
        waiter = asyncio.create_task(gate.allows("example.com", 70, ["/b"]))
        await asyncio.sleep(0)  # let the waiter sweep and queue on the lock
        first.set()  # schedules the holder's release...
        third = asyncio.create_task(gate.allows("example.com", 70, ["/c"]))

        await asyncio.wait_for(asyncio.gather(holder, waiter, third), timeout=5.0)

        assert peak == 1
        # The bookkeeping that keeps the sweep honest must not itself leak.
        assert gate._lock_users == {}

    async def test_sweep_preserves_live_entries(self):
        calls = []
        clock = _FakeClock()

        async def fetcher(host, port):
            calls.append(host)
            return "User-agent: *\nDisallow: /no\n"

        gate = RobotsGate(
            fetcher=fetcher,
            tokens=("*",),
            ttl_seconds=10_000,
            fail_closed=False,
            clock=clock,
        )
        gate._sweep_threshold = 5
        await gate.allows("keep.example", 70, ["/ok"])
        for i in range(20):
            await gate.allows(f"other{i}.example", 70, ["/ok"])

        before = len(calls)
        # Still cached: no refetch.
        assert (await gate.allows("keep.example", 70, ["/no"])).allowed is False
        assert len(calls) == before


class TestReviewRegressions:
    """One test per defect found reviewing the original implementation."""

    def test_wildcard_matching_is_not_exponential(self):
        """A hostile Disallow must not stall the event loop.

        Translating the pattern to a regex produced adjacent unbounded `.*`
        groups: eight stars took 11s against a 61-char path, nine took 93s, and
        the match runs synchronously on the loop.
        """
        import time

        from gopher_mcp.robots import _matches

        started = time.monotonic()
        assert _matches("/" + "*" * 24 + "zzz", "/" + "a" * 200) is False
        assert time.monotonic() - started < 1.0

    def test_ignored_field_does_not_merge_two_records(self):
        """Only Disallow used to close a User-agent run.

        `Allow:` is ignored by the 1994 grammar, but it still terminates the
        record. Without that, agent `b` below inherited agent `a`'s identity and
        both got `/y`.
        """
        policy = parse_robots("User-agent: a\nAllow: /x\nUser-agent: b\nDisallow: /y\n")
        assert policy.groups == {"a": [], "b": ["/y"]}

    def test_ai_tokens_are_additive_only(self):
        """Claiming an AI token must never *grant* access.

        Treated as an ordinary specific token, matching `ClaudeBot` suppressed
        the blanket `User-agent: *` group, so honouring more tokens made the
        client less restricted than ignoring them entirely.
        """
        policy = parse_robots(
            "User-agent: *\nDisallow: /\nUser-agent: ClaudeBot\nDisallow: /private\n"
        )
        assert policy.is_allowed(["/open"], GEMINI_TOKENS, AI_AGENT_TOKENS) is False
        assert (
            policy.is_allowed(["/private/x"], GEMINI_TOKENS, AI_AGENT_TOKENS) is False
        )

    def test_ai_tokens_still_restrict(self):
        policy = parse_robots("User-agent: GPTBot\nDisallow: /no\n")
        assert policy.is_allowed(["/no/x"], GEMINI_TOKENS, AI_AGENT_TOKENS) is False
        assert policy.is_allowed(["/yes"], GEMINI_TOKENS, AI_AGENT_TOKENS) is True

    def test_percent_encoded_path_cannot_bypass(self):
        policy = parse_robots("User-agent: *\nDisallow: /~private/\n")
        assert policy.is_allowed(["/%7Eprivate/x"], ("*",)) is False

    def test_dot_segments_cannot_bypass(self):
        policy = parse_robots("User-agent: *\nDisallow: /private\n")
        assert policy.is_allowed(["/pub/../private/x"], ("*",)) is False

    def test_encoded_rule_matches_decoded_path(self):
        policy = parse_robots("User-agent: *\nDisallow: /%7Eprivate/\n")
        assert policy.is_allowed(["/~private/x"], ("*",)) is False

    def test_trailing_dot_host_shares_one_policy(self):
        """A FQDN trailing dot must not create a second, unchecked bucket."""

        async def fetcher(host, port):
            return "User-agent: *\nDisallow: /\n"

        async def run():
            gate = RobotsGate(
                fetcher=fetcher, tokens=("*",), ttl_seconds=60, fail_closed=False
            )
            assert (await gate.allows("example.com", 70, ["/x"])).allowed is False
            assert (await gate.allows("example.com.", 70, ["/x"])).allowed is False

        asyncio.run(run())

    async def test_gemini_gemtext_robots_is_honoured(self):
        """text/gemini is Gemini's DEFAULT MIME.

        Reading only `content` missed GeminiGemtextResult (whose text lives in
        `raw_content`), so a policy served as text/gemini, or with an absent or
        malformed meta, was discarded and allow-all cached for the whole TTL.
        """
        from gopher_mcp.models import GeminiGemtextResult, GemtextDocument

        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gemini_content(
            robots=GeminiGemtextResult(
                rawContent="User-agent: *\nDisallow: /\n",
                document=GemtextDocument(lines=[]),
                size=26,
            )
        )
        result = await client.fetch("gemini://example.com/secret")
        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()

    async def test_gemini_robots_bypasses_the_render_cap(self):
        """max_rendered_chars shapes what reaches the model.

        Applying it to a robots.txt truncates the policy mid-file and silently
        drops every rule past the cap.
        """
        client = GeminiClient(
            cache_enabled=False,
            requests_per_minute=0,
            respect_robots_txt=True,
            max_rendered_chars=10,
        )
        seen = {}

        async def fake(
            parsed_url, *, max_bytes=None, apply_content_policy=True, **kwargs
        ):
            if parsed_url.path == "/robots.txt":
                seen["policy_applied"] = apply_content_policy
                return GeminiErrorResult(
                    error={"code": "NOT_FOUND", "message": "x", "status": 51}
                )
            return _gemini_success()

        client._fetch_content = fake
        await client.fetch("gemini://example.com/page")
        assert seen["policy_applied"] is False
        await client.close()

    async def test_gemini_robots_capped_by_max_response_size(self):
        """A lowered max_response_size must still bound the robots read."""
        client = GeminiClient(
            cache_enabled=False,
            requests_per_minute=0,
            respect_robots_txt=True,
            max_response_size=4096,
        )
        seen = {}

        async def fake(
            parsed_url, *, max_bytes=None, apply_content_policy=True, **kwargs
        ):
            if parsed_url.path == "/robots.txt":
                seen["max_bytes"] = max_bytes
                return GeminiErrorResult(
                    error={"code": "NOT_FOUND", "message": "x", "status": 51}
                )
            return _gemini_success()

        client._fetch_content = fake
        await client.fetch("gemini://example.com/page")
        assert seen["max_bytes"] == 4096
        await client.close()

    async def test_gopher_transient_failure_is_not_cached(self):
        """Returning None for a timeout cached "no policy" for 24 hours.

        A blip must not disable robots checking for the host for the full TTL.
        """
        from gopher_mcp.gopher_transport import GopherProtocolError

        client = GopherClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gopher_content()
        state = {"fail": True}

        async def flaky(*args, **kwargs):
            if state["fail"]:
                raise GopherProtocolError("timed out")
            return b"User-agent: *\nDisallow: /\n"

        with patch(
            "gopher_mcp.gopher_client.validate_target", return_value=["93.184.216.34"]
        ):
            with patch("gopher_mcp.gopher_client.fetch_gopher", side_effect=flaky):
                # Fails open while unreachable...
                assert isinstance(
                    await client.fetch("gopher://example.com/0/page"), TextResult
                )
                state["fail"] = False
                # ...and the real policy applies once the short retry backoff
                # has passed, rather than the failure being remembered for the
                # whole 24h TTL. (The backoff itself is what stops a dead host
                # costing a connect timeout on every single request.)
                gate = client._robots_gate
                assert gate is not None
                gate._retry_after.clear()
                blocked = await client.fetch("gopher://example.com/0/page")
        assert isinstance(blocked, ErrorResult)
        assert blocked.error["code"] == "BLOCKED_BY_ROBOTS"
        await client.close()

    async def test_unavailable_reason_is_reported_distinctly(self):
        """ "We could not find out" must not be reported as "they said no"."""
        client = GeminiClient(
            cache_enabled=False, requests_per_minute=0, respect_robots_txt=True
        )
        client._fetch_content = _fake_gemini_content(
            robots=GeminiErrorResult(
                error={"code": "UNAVAILABLE", "message": "temp", "status": 41}
            )
        )
        result = await client.fetch("gemini://example.com/page")
        assert isinstance(result, GeminiErrorResult)
        assert "Could not retrieve robots.txt" in result.error["message"]
        await client.close()
