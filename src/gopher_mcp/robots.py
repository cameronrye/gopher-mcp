"""Robot exclusion (``robots.txt``) support for the Gopher and Gemini clients.

Neither Gopher nor Gemini sends a User-Agent header, so a server cannot
recognise this client on the wire. Both ecosystems solved that the same way: a
``/robots.txt`` at the host root naming *virtual* user agents that describe what
a bot does rather than what software it is.

Which convention applies depends on the protocol:

* **Gemini** follows the official companion specification at
  ``gemini://geminiprotocol.net/docs/companion/robots.gmi``, which defines the
  tokens ``archiver``, ``indexer``, ``researcher`` and ``webproxy``, and uses
  the *original 1994* robots.txt grammar: only ``#``, ``User-agent:`` and
  ``Disallow:`` are recognised, and "All other lines are ignored". There is no
  ``Allow:``. An RFC 9309 parser would therefore act on ``Allow:`` lines that
  capsule authors expect to be dropped and end up *more permissive* than
  intended, which is why this module carries its own parser rather than using
  ``urllib.robotparser``, ``protego`` or ``reppy``.
* **Gopher** follows the convention Veronica-2 documents at
  ``gopher://gopher.floodgap.com/0/v2/help/indexer`` ("you can use a regular old
  robots.txt file ... Veronica-2 obeys User-agent of 'veronica' and '*'"), which
  uses the same 1994 grammar.

RFC 9309 is not the normative reference for either protocol, but it is
scheme-generic (§1 scopes it to any RFC 3986 URI, and §2.3 uses an ``ftp://``
example) and its file-location rule is followed here: ``robots.txt`` lives at
the top-level path of the service and nowhere else. Neither that RFC nor either
protocol convention defines a per-directory or per-user ``robots.txt``; on
shared hosts the established pattern is a single root file using path prefixes.

Two deliberate departures from a strict 1994 reading, both chosen because they
can only ever make this client *less* permissive:

* ``*`` and ``$`` in a ``Disallow`` value are honoured as wildcards. The 1994
  grammar treats them literally, but authors who write them plainly intend the
  broader match.
* When several of our tokens match, the union of their rules applies rather than
  the first match. This follows the companion spec's own tie-breaker: when more
  than one category applies, "obey the most restrictive set of directives".
"""

import asyncio
import posixpath
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import unquote

import structlog

logger = structlog.get_logger(__name__)

# RFC 9309 §2.5 asks parsers to handle at least 500 KiB. A real robots.txt is a
# fraction of that; the cap matters because a Gopher server has no way to say
# "no such selector" and may answer with an arbitrary menu or error document.
ROBOTS_MAX_BYTES = 512_000

# Advertised token for this project. The Gemini companion spec explicitly lets a
# bot honour directives aimed at "their own individual User-agent which they
# prominently advertise", so operators can name us specifically.
PROJECT_TOKEN = "gopher-mcp"  # nosec B105 # a robots.txt agent name, not a secret

# Gopher: Veronica-2's documented convention. `veronica` is deliberately NOT
# claimed -- that token belongs to Floodgap's indexer, not to us.
GOPHER_TOKENS: tuple[str, ...] = (PROJECT_TOKEN, "*")

# Gemini: the companion spec's virtual agents that actually describe this tool.
# `webproxy` covers the on-demand, human-triggered fetch; `indexer` is included
# because the batch tools fetch many URLs at once, which is crawl-shaped.
# `archiver` and `researcher` are NOT claimed: nothing here retains content, and
# `researcher` requires operating "without rehosting, linking to, or allowing
# search of any fetched content", which is the opposite of showing page text to
# a user.
GEMINI_TOKENS: tuple[str, ...] = (PROJECT_TOKEN, "webproxy", "indexer", "*")

# Product tokens used by AI crawlers on the HTTP web. These are not part of
# either protocol's convention and are largely transplanted boilerplate where
# they appear in Gopherspace/Geminispace -- but an operator who wrote one meant
# "no LLM tooling", and honouring that costs nothing.
AI_AGENT_TOKENS: tuple[str, ...] = (
    "anthropic-ai",
    "ccbot",
    "chatgpt-user",
    "claude-code",
    "claude-searchbot",
    "claude-user",
    "claude-web",
    "claudebot",
    "cohere-ai",
    "gptbot",
    "oai-searchbot",
    "perplexity-user",
    "perplexitybot",
)


class RobotsUnavailable(Exception):
    """The policy for a host could not be determined.

    Raised by a fetcher for a *temporary* failure, which RFC 9309 §2.3.1.4 says
    must be treated as a complete disallow. A permanently absent file is not
    this: a fetcher signals "no policy, allow everything" by returning ``None``.
    """


@dataclass
class RobotsPolicy:
    """Parsed ``robots.txt`` groups: lowercased agent token -> disallow rules.

    An empty ``groups`` mapping means no policy was found and everything is
    allowed, which is also what unparseable content collapses to.
    """

    groups: dict[str, list[str]] = field(default_factory=dict)

    def is_allowed(
        self,
        paths: list[str],
        tokens: tuple[str, ...],
        extra_tokens: tuple[str, ...] = (),
    ) -> bool:
        """Return whether any of ``paths`` may be fetched under ``tokens``.

        ``paths`` is a list of candidate spellings of the same resource (Gopher
        needs several; see :func:`gopher_candidate_paths`). A rule matching any
        candidate denies the fetch.

        ``extra_tokens`` (the named AI crawler agents) are *additive only*: their
        rules are unioned into whatever the protocol tokens select, but matching
        one never suppresses the catch-all group. Treating them like ordinary
        specific tokens would invert their purpose -- a capsule with a blanket
        ``User-agent: *`` / ``Disallow: /`` plus a narrower ``User-agent:
        ClaudeBot`` section would end up granting us *more* access than a client
        that ignored the AI tokens entirely.
        """
        if not self.groups:
            return True

        # Specific tokens win over the catch-all, and all matching specific
        # groups apply together (most-restrictive tie-breaker). A specific group
        # that is *present but empty* still wins: writing "User-agent: webproxy"
        # followed by a bare "Disallow:" is how an operator grants us access a
        # blanket "User-agent: *" rule would otherwise deny.
        matched_specific = False
        rules: list[str] = []
        for agent in tokens:
            if agent != "*" and agent in self.groups:
                matched_specific = True
                rules.extend(self.groups[agent])

        if not matched_specific and "*" in tokens:
            rules = list(self.groups.get("*", []))

        for agent in extra_tokens:
            if agent in self.groups:
                rules.extend(self.groups[agent])

        if not rules:
            return True

        candidates = expand_path_candidates(paths)
        # Normalise the rules as well: an operator may write "/%7Eprivate/"
        # while the request carries "/~private/". Expanding only one side would
        # miss the cross case.
        expanded_rules = []
        for rule in rules:
            if rule not in expanded_rules:
                expanded_rules.append(rule)
            decoded = unquote(rule)
            if decoded not in expanded_rules:
                expanded_rules.append(decoded)
        return not any(
            _matches(rule, path) for rule in expanded_rules for path in candidates
        )


def _matches(rule: str, path: str) -> bool:
    """Return whether ``rule`` (a Disallow value) covers ``path``.

    Plain prefix match, extended with ``*`` (any sequence) and ``$`` (end
    anchor). An empty rule never matches: ``Disallow:`` with no value is the
    1994 way to say "nothing is disallowed".

    Matching is a linear greedy scan rather than a translated regular
    expression. ``rule`` comes verbatim from a remote server, and a pattern such
    as ``/********zzz`` compiles to adjacent unbounded ``.*`` groups whose
    backtracking cost is exponential in the number of stars -- eleven seconds at
    eight stars, and this runs synchronously on the event loop. A greedy scan is
    O(len(rule) x len(path)) for this pattern class and gives the same answer:
    each literal segment only ever needs its leftmost placement, because the
    wildcard before it can absorb anything skipped.
    """
    if not rule:
        return False

    anchored = rule.endswith("$")
    pattern = rule[:-1] if anchored else rule

    if "*" not in pattern:
        return path == pattern if anchored else path.startswith(pattern)

    segments = pattern.split("*")

    # The segment before the first star must sit at the start of the path.
    if not path.startswith(segments[0]):
        return False
    pos = len(segments[0])

    # Interior segments may appear anywhere after the previous match.
    for segment in segments[1:-1]:
        if not segment:
            continue
        found = path.find(segment, pos)
        if found == -1:
            return False
        pos = found + len(segment)

    tail = segments[-1]
    if not tail:
        # Pattern ends in a star, which absorbs whatever is left.
        return True
    if anchored:
        return path.endswith(tail) and len(path) - len(tail) >= pos
    return path.find(tail, pos) != -1


def expand_path_candidates(paths: list[str]) -> list[str]:
    """Return each path plus the other spellings a rule might be written in.

    A rule and a request can disagree on percent-encoding (``/%7Euser`` versus
    ``/~user``) or carry dot segments (``/pub/../private``), and matching only
    the literal request path would let either slip past a Disallow. Every
    spelling is tested and any match denies, so normalisation can only make this
    stricter.
    """
    candidates: list[str] = []
    for path in paths:
        for variant in (path, unquote(path)):
            if variant not in candidates:
                candidates.append(variant)
            if "./" in variant or variant.endswith("/.."):
                resolved = posixpath.normpath(variant)
                if variant.endswith("/") and not resolved.endswith("/"):
                    resolved += "/"
                if resolved not in candidates:
                    candidates.append(resolved)
    return candidates


def parse_robots(text: str) -> RobotsPolicy:
    """Parse ``robots.txt`` content using the original 1994 grammar.

    Only ``User-agent:`` and ``Disallow:`` are recognised; every other field --
    including ``Allow:``, ``Crawl-delay:`` and ``Sitemap:`` -- is ignored, per
    the Gemini companion spec and the pre-RFC convention Gopher indexers follow.

    Content that yields no ``User-agent:`` group at all produces an empty policy
    (allow everything). That is what makes it safe to feed this whatever a
    Gopher server returned for a selector it does not have: an error page or a
    menu simply parses to nothing.
    """
    groups: dict[str, list[str]] = {}
    # Tokens whose group is still open, i.e. consecutive User-agent lines that
    # share the Disallow rules that follow them.
    current: list[str] = []
    # A Disallow line closes the run of User-agent lines above it; the next
    # User-agent then starts a fresh group.
    accepting_agents = True

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        field_name, sep, value = line.partition(":")
        if not sep:
            continue
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            if not accepting_agents:
                current = []
                accepting_agents = True
            if value:
                token = value.lower()
                current.append(token)
                groups.setdefault(token, [])
        else:
            # ANY non-User-agent field closes the run of agent lines above it,
            # not just Disallow. Otherwise "User-agent: a / Allow: /x /
            # User-agent: b / Disallow: /y" would treat a and b as one group and
            # apply b's rules to a -- an ignored field must not silently merge
            # two unrelated records.
            accepting_agents = False
            if field_name != "disallow" or not current or not value:
                continue
            for token in current:
                groups[token].append(value)

    return RobotsPolicy(groups)


def gopher_candidate_paths(gopher_type: str, selector: str) -> list[str]:
    """Return the path spellings a Gopher rule might be written against.

    A Gopher URI carries the item type as the first path segment character, so
    ``gopher://host/0/users/foo`` has the URI path ``/0/users/foo`` while the
    on-wire selector is ``/users/foo``. Operators write rules both ways --
    quux.org's own file lists ``Disallow: /Archives/mirrors/`` *and*
    ``Disallow: 1/Archives/mirrors/`` to cover the ambiguity -- so a rule that
    matches any spelling is honoured.
    """
    sel = selector if selector.startswith("/") else f"/{selector}"
    return [sel, f"/{gopher_type}{sel}", f"{gopher_type}{sel}"]


@dataclass
class RobotsDecision:
    """The outcome of a gate check, and the reason behind it."""

    allowed: bool
    # "allowed" | "disallowed" | "unavailable"
    reason: str = "allowed"


@dataclass
class _CachedPolicy:
    policy: RobotsPolicy
    expires_at: float


class RobotsGate:
    """Per-host ``robots.txt`` lookup with caching, for one protocol client.

    The fetcher is injected so this class stays protocol-agnostic and directly
    testable. It must fetch ``/robots.txt`` from the host root *without* going
    back through the client's own gated fetch path, and must return ``None`` for
    "no policy here" or raise :class:`RobotsUnavailable` for a temporary failure.
    """

    def __init__(
        self,
        *,
        fetcher: Callable[[str, int], Awaitable[str | None]],
        tokens: tuple[str, ...],
        extra_tokens: tuple[str, ...] = (),
        ttl_seconds: int,
        fail_closed: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the gate.

        Args:
            fetcher: Coroutine ``(host, port) -> robots.txt text or None``.
            tokens: Protocol agent tokens to match, most specific first.
            extra_tokens: Additive-only tokens (the named AI crawler
                agents). Their rules are unioned in but never suppress the
                catch-all group; see :meth:`RobotsPolicy.is_allowed`.
            ttl_seconds: How long a fetched policy stays valid. RFC 9309 §2.4
                permits up to 24h; Floodgap suggests "several hours up to a day".
            fail_closed: What to do when the fetcher raises
                :class:`RobotsUnavailable`. True denies (RFC 9309 §2.3.1.4);
                False allows, which is the only workable choice for Gopher.
            clock: Monotonic clock source (injectable for tests).
        """
        self._fetcher = fetcher
        self._tokens = tokens
        self._extra_tokens = extra_tokens
        self._ttl_seconds = ttl_seconds
        self._fail_closed = fail_closed
        self._clock = clock
        self._cache: dict[str, _CachedPolicy] = {}
        # One lock per host so a batch of concurrent fetches to the same server
        # triggers a single robots.txt request rather than one per URL.
        self._locks: dict[str, asyncio.Lock] = {}
        # How many coroutines are currently holding or queued on each host lock.
        # ``asyncio.Lock.locked()`` cannot answer that: ``release()`` clears the
        # flag and only *schedules* the first waiter, so for one loop iteration
        # a contended lock reports ``locked() == False``. Sweeping on that flag
        # would drop a lock waiters still reference, and the next caller would
        # create a second lock for the same host -- two concurrent robots.txt
        # fetches at the very server the gate exists to spare.
        self._lock_users: dict[str, int] = {}
        # When a probe fails, the host is not re-probed until this timestamp.
        # See FAILURE_BACKOFF_SECONDS.
        self._retry_after: dict[str, float] = {}
        # An open-world fetcher sees an unbounded number of distinct hosts, so
        # neither map may grow without limit (the rate limiter has the same
        # constraint and solves it the same way). Past this many entries, sweep
        # out expired policies and unheld locks -- both are reconstructible, so
        # dropping them is behaviour-preserving.
        self._sweep_threshold = 1024

    #: How long an unreachable host is left alone before being probed again.
    #: A failure is deliberately not cached for the full TTL -- a transient
    #: outage should be retried -- but without any backoff, robots-on-by-default
    #: made every request to a dead host pay a fresh connect timeout, including
    #: requests that would otherwise be served entirely from the content cache
    #: (the gate runs ahead of that lookup). On Gopher the gate then fails open
    #: and proceeds anyway, so the wait bought nothing at all. Short enough to
    #: still be a retry, long enough to stop the per-request cost.
    FAILURE_BACKOFF_SECONDS = 60.0

    async def allows(self, host: str, port: int, paths: list[str]) -> RobotsDecision:
        """Return whether ``paths`` on ``host:port`` may be fetched."""
        policy = await self._policy_for(host, port)
        if policy is None:
            # Undeterminable; the fail-open/closed choice is the caller's.
            return RobotsDecision(allowed=not self._fail_closed, reason="unavailable")
        if policy.is_allowed(paths, self._tokens, self._extra_tokens):
            return RobotsDecision(allowed=True)
        return RobotsDecision(allowed=False, reason="disallowed")

    async def _policy_for(self, host: str, port: int) -> RobotsPolicy | None:
        # Strip the FQDN trailing dot so "example.com." and "example.com"
        # share one policy rather than each getting their own.
        key = f"{host.lower().rstrip('.')}:{port}"

        cached = self._cache.get(key)
        if cached is not None and cached.expires_at > self._clock():
            return cached.policy

        # A recent probe failed: serve the stale policy if we have one, else
        # stay undeterminable, but do not pay another connect timeout yet.
        retry_after = self._retry_after.get(key)
        if retry_after is not None and retry_after > self._clock():
            return cached.policy if cached is not None else None

        if (
            len(self._cache) > self._sweep_threshold
            or len(self._locks) > self._sweep_threshold
        ):
            self._sweep()

        # Registering before touching the lock is what keeps _sweep safe; see
        # the note on ``_lock_users``.
        self._lock_users[key] = self._lock_users.get(key, 0) + 1
        try:
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                # Re-check: another waiter may have populated the entry while we
                # queued on the lock.
                cached = self._cache.get(key)
                if cached is not None and cached.expires_at > self._clock():
                    return cached.policy

                try:
                    text = await self._fetcher(host, port)
                except RobotsUnavailable as e:
                    logger.debug(
                        "robots.txt unavailable", host=host, port=port, reason=str(e)
                    )
                    # Deliberately not cached: a temporary failure should be
                    # retried, not pinned for the whole TTL. Fall back to the
                    # stale policy if we have one rather than throwing away a
                    # known-good answer.
                    self._retry_after[key] = (
                        self._clock() + self.FAILURE_BACKOFF_SECONDS
                    )
                    stale = self._cache.get(key)
                    return stale.policy if stale is not None else None

                policy = parse_robots(text) if text is not None else RobotsPolicy()
                self._retry_after.pop(key, None)
                self._cache[key] = _CachedPolicy(
                    policy=policy, expires_at=self._clock() + self._ttl_seconds
                )
                if policy.groups:
                    logger.debug(
                        "robots.txt policy loaded",
                        host=host,
                        port=port,
                        agents=sorted(policy.groups),
                    )
                return policy
        finally:
            remaining = self._lock_users[key] - 1
            if remaining:
                self._lock_users[key] = remaining
            else:
                del self._lock_users[key]

    def _sweep(self) -> None:
        """Drop expired policies and locks nobody is holding or waiting on."""
        now = self._clock()
        self._cache = {k: v for k, v in self._cache.items() if v.expires_at > now}
        # A held or contended lock must survive: dropping it would let a second
        # caller create a fresh lock and start a duplicate fetch. An unused lock
        # is safe to recreate.
        self._locks = {k: v for k, v in self._locks.items() if k in self._lock_users}
        self._retry_after = {k: v for k, v in self._retry_after.items() if v > now}
