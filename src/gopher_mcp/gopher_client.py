"""Gopher protocol client implementation."""

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NamedTuple

import structlog

from .client_base import FetchClientBase
from .gopher_parse import (
    gopher_type_category,
    parse_gopher_menu,
    parse_gopher_url,
)
from .gopher_transport import (
    GopherProtocolError,
    GopherTimeoutError,
    decode_gopher_text,
    fetch_gopher,
)
from .helpers import normalize_cache_key, sanitize_display_text, window_text
from .mime import detect_binary_mime_type
from .models import (
    BinaryResult,
    CacheEntry,
    ErrorResult,
    GopherFetchResponse,
    GopherURL,
    MenuResult,
    RequestInfo,
    TextResult,
    iso_utc,
    mark_from_cache,
)
from .robots import (
    GOPHER_TOKENS,
    ROBOTS_MAX_BYTES,
    RobotsUnavailable,
    gopher_candidate_paths,
)
from .ssrf import HostResolutionError, SSRFError, validate_target

logger = structlog.get_logger(__name__)

# Default configuration constants
DEFAULT_MAX_RESPONSE_SIZE = 1024 * 1024  # 1MB
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_CACHE_ENTRIES = 1000
DEFAULT_MAX_SELECTOR_LENGTH = 1024
DEFAULT_MAX_SEARCH_LENGTH = 256
DEFAULT_MAX_RENDERED_CHARS = 50000  # LLM-facing text cap; 0 = unlimited
DEFAULT_MAX_MENU_ITEMS = 1000  # LLM-facing menu item cap; 0 = unlimited
# Politeness defaults. Gopher and Gemini are served largely by small
# hobbyist hosts, and a model can call the fetch tools in a tight loop, so
# both are on out of the box rather than opt-in.
DEFAULT_REQUESTS_PER_MINUTE = 60.0  # one request per second, per host
DEFAULT_MAX_CONCURRENT_REQUESTS = 5  # matches the batch tools' concurrency
DEFAULT_ROBOTS_CACHE_TTL_SECONDS = 86400  # RFC 9309 s2.4 permits 24h
DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS = 60.0  # dead host: retry, not per request


@dataclass
class _FetchBudget:
    """Network time still available to one :meth:`GopherClient.fetch` call.

    ``timeout_seconds`` is documented -- in ``docs/configuration.md`` and in
    ``config/example.env`` -- as the "overall deadline for one fetch, covering
    DNS, connect, send and read". It was not: the DNS ``wait_for`` and the
    transport fetch were each handed the full value, and with robots checking on
    by default the probe spent two more full-length phases of its own, so one
    call could occupy four multiples of the configured deadline against a tarpit
    answering each phase just under the limit. This makes the documented
    sentence true. Mirrors the Gemini client's budget of the same name.
    """

    remaining: float


# Budget for the fetch currently running in this task. A ContextVar rather than
# an argument because the robots probe is invoked through RobotsGate, which owns
# its fetcher signature; each task copies the context, so concurrent fetches get
# their own budget.
_FETCH_BUDGET: ContextVar[_FetchBudget | None] = ContextVar(
    "gopher_fetch_budget", default=None
)


@dataclass
class _ProbeCredit:
    """What the robots probe already paid for, on behalf of the fetch it guards.

    The probe and the fetch it precedes are one user-visible request to one
    host, but each used to take its own rate-limit token and run its own DNS
    lookup -- so with the shipped defaults (60 rpm, robots on) every first fetch
    to a host slept a full second before anything could be sent, and resolved
    the same name twice. Both halves are handed straight to the fetch that
    follows, which is the only thing that ever runs after a probe.
    """

    host: str
    port: int
    addresses: list[str]
    rate_slot: bool


# Set by the robots probe, consumed by the fetch it guards. A ContextVar for the
# same reason as the budget above: the probe is invoked through RobotsGate, which
# owns its fetcher signature, and awaits it inside the calling task.
_PROBE_CREDIT: ContextVar[_ProbeCredit | None] = ContextVar(
    "gopher_probe_credit", default=None
)


# Where the render window starts for the fetch running in this task: menu item
# index / character position, 0 for the beginning. A ContextVar for the same
# reason as the budget above -- it has to reach the render step across
# ``_bounded_fetch``/``_fetch_content``, the seam subclasses and test doubles
# implement, and each task's own copy keeps concurrent fetches from reading each
# other's window (a value parked on the shared client instance would not).
_RENDER_OFFSET: ContextVar[int] = ContextVar("gopher_render_offset", default=0)

# Cache key of the resource currently being fetched, WITHOUT the offset suffix.
# Set by ``fetch`` and read by ``_fetch_content`` so the body it downloaded can
# be filed under the resource rather than under one window of it -- the same
# indirection ``_RENDER_OFFSET`` uses, and for the same reason: the transport
# path is reached through the shared base class and cannot take extra arguments.
_BODY_SLOT_KEY: ContextVar[str | None] = ContextVar(
    "gopher_body_slot_key", default=None
)


class _ContinuationBody(NamedTuple):
    """One downloaded body, held so its remaining windows are free.

    Gopher has no range request, so a windowed read downloads the WHOLE
    resource and shows a slice of it. Before this, every continuation went back
    to the server for the same bytes: walking a 208 KB page at a 10k cap cost 21
    downloads and 4.4 MB, and with the shipped per-host rate limit it also cost
    21 seconds -- paid by whoever is hosting it, which is usually a hobbyist on
    a small machine.

    ONE slot, not a cache. A continuation is a sequential walk over a single
    document, so one body serves the whole walk; the memory is bounded by
    ``max_response_size`` (1 MiB by default) no matter how many resources are
    read, which a per-URL cache could not promise. Superseding it on the next
    truncated resource is the eviction policy.

    Sized against the alternative rather than assumed: the per-window entries
    this replaces held 217,438 bytes after a full walk of that 208,005-byte
    page, so the slot costs LESS than what it saves, not more.
    """

    key: str
    raw: bytes
    stored_at: float


class _BudgetExhausted(GopherProtocolError):
    """The fetch deadline ran out before this phase could start.

    Subclasses :class:`GopherProtocolError` so :meth:`GopherClient.fetch` keeps
    mapping it to ``FETCH_ERROR`` -- a timeout is a fetch failure -- while the
    robots probe, whose generic handler would otherwise call it "the reply was
    not a valid Gopher response", can report it for what it is.
    """


@contextlib.asynccontextmanager
async def _spend_budget(default_timeout: float) -> AsyncIterator[float]:
    """Yield the timeout for one wire phase, then charge what it used.

    Every phase that touches the network goes through here -- the robots
    probe's DNS lookup and transport read, then the guarded fetch's own two --
    so all four draw down one deadline instead of each being handed a full one.
    """
    budget = _FETCH_BUDGET.get()
    if budget is None:
        yield default_timeout
        return
    if budget.remaining <= 0:
        raise _BudgetExhausted(f"The request timed out after {default_timeout} seconds")
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        yield budget.remaining
    finally:
        budget.remaining -= loop.time() - started


def _display_selector(selector: str) -> str:
    """Render a selector for the JSON echoed back to the caller.

    ``parse_gopher_url`` carries a selector byte that is not valid UTF-8 as a
    surrogate escape so the transport can put the original byte back on the
    wire. A lone surrogate cannot be encoded into JSON at all, so serializing
    the response would fail outright -- the echo (and the debug log) therefore
    shows the lossy U+FFFD form while the wire still gets the exact bytes.

    Args:
        selector: Selector as parsed from the URL.

    Returns:
        The same selector with unencodable bytes shown as U+FFFD.

    """
    return selector.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _strip_gopher_text_terminator(text: str) -> str:
    """Reverse RFC 1436 text-mode framing.

    Removes a trailing lone-``.`` terminator line and un-dot-stuffs lines that
    begin with ``..`` (the protocol doubles a leading ``.``). Only a terminator
    at the very end is removed -- servers that don't dot-stuff could otherwise
    have a legitimate mid-document ``.`` line truncated.

    Un-dot-stuffing is applied ONLY when a terminator was actually present:
    dot-stuffing is part of the period-termination framing, so an unframed
    document (no terminator line) carries literal ``..`` content that must not
    be collapsed to ``.``.
    """
    # Split on LF but keep any trailing '\r' on each line so CRLF is preserved
    # when we rejoin; remember a final newline so it survives the round-trip.
    lines = text.split("\n")
    trailing_newline = bool(lines) and lines[-1] == ""
    if trailing_newline:
        lines = lines[:-1]

    # Drop a trailing terminator line ('.' possibly with a trailing '\r').
    had_terminator = bool(lines) and lines[-1].rstrip("\r") == "."
    if had_terminator:
        lines = lines[:-1]

    if had_terminator:
        lines = [line[1:] if line.startswith("..") else line for line in lines]
    result = "\n".join(lines)
    if trailing_newline and result:
        result += "\n"
    return result


class GopherClient(FetchClientBase[GopherFetchResponse, GopherURL]):
    """Async Gopher protocol client with caching and safety features."""

    _log_label = "Gopher"
    _cache_entry_cls = CacheEntry
    # Gopher results spell the content length ``bytes`` (Gemini says ``size``).
    _response_size_field = "bytes"
    _robots_tokens = GOPHER_TOKENS
    # Gopher fails *open*: the protocol has no status codes, so a missing
    # selector, an error document and an empty file are indistinguishable on the
    # wire, and RFC 9309 s2.3.1.4's "treat unreachable as complete disallow"
    # would deny most of Gopherspace. The lenient parser makes that safe -- an
    # error page yields no User-agent group and so imposes no rules.
    _robots_fail_closed = False

    def __init__(
        self,
        *,
        max_response_size: int = DEFAULT_MAX_RESPONSE_SIZE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_cache_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        allowed_hosts: list[str] | None = None,
        allow_local_hosts: bool = False,
        allowed_ports: list[int] | None = None,
        max_selector_length: int = DEFAULT_MAX_SELECTOR_LENGTH,
        max_search_length: int = DEFAULT_MAX_SEARCH_LENGTH,
        max_rendered_chars: int = DEFAULT_MAX_RENDERED_CHARS,
        max_menu_items: int = DEFAULT_MAX_MENU_ITEMS,
        requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
        respect_robots_txt: bool = True,
        robots_cache_ttl_seconds: int = DEFAULT_ROBOTS_CACHE_TTL_SECONDS,
        robots_honor_ai_tokens: bool = True,
        robots_failure_backoff_seconds: float = DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS,
    ) -> None:
        """Initialize the Gopher client.

        Args:
            max_response_size: Maximum response size in bytes
            timeout_seconds: Request timeout in seconds
            cache_enabled: Whether to enable response caching
            cache_ttl_seconds: Cache TTL in seconds
            max_cache_entries: Maximum number of cache entries
            allowed_hosts: List of allowed hostnames (None = allow all)
            max_selector_length: Maximum selector string length
            max_search_length: Maximum search query length
            max_concurrent_requests: Cap on simultaneous in-flight fetches
                (0 = unlimited); a coarse bound on concurrent sockets/memory.
            respect_robots_txt: Consult /robots.txt at the host root before
                fetching, per the convention Veronica-2 documents.
            robots_cache_ttl_seconds: Lifetime of a cached robots policy.
            robots_honor_ai_tokens: Also honour rules naming AI crawler
                tokens (ClaudeBot, GPTBot, ...).
            robots_failure_backoff_seconds: How long a host whose /robots.txt
                probe failed is left alone before being probed again

        """
        super().__init__(
            max_response_size=max_response_size,
            timeout_seconds=timeout_seconds,
            cache_enabled=cache_enabled,
            cache_ttl_seconds=cache_ttl_seconds,
            max_cache_entries=max_cache_entries,
            allowed_hosts=allowed_hosts,
            allow_local_hosts=allow_local_hosts,
            allowed_ports=allowed_ports,
            max_rendered_chars=max_rendered_chars,
            requests_per_minute=requests_per_minute,
            max_concurrent_requests=max_concurrent_requests,
            respect_robots_txt=respect_robots_txt,
            robots_cache_ttl_seconds=robots_cache_ttl_seconds,
            robots_honor_ai_tokens=robots_honor_ai_tokens,
            robots_failure_backoff_seconds=robots_failure_backoff_seconds,
        )

        # One downloaded body, so the windows after the first are free.
        self._continuation_body: _ContinuationBody | None = None
        self.max_selector_length = max_selector_length
        self.max_search_length = max_search_length
        self.max_menu_items = max_menu_items

    def _validate_security(self, parsed_url: GopherURL) -> None:
        """Validate security constraints for a Gopher request.

        Args:
            parsed_url: Parsed Gopher URL

        Raises:
            ValueError: If security validation fails

        """
        if not self._host_is_allowed(parsed_url.host):
            raise ValueError(f"Host '{parsed_url.host}' not in allowed hosts list")

        # Validate selector length
        if len(parsed_url.selector) > self.max_selector_length:
            raise ValueError(
                f"Selector too long: {len(parsed_url.selector)} > {self.max_selector_length}"
            )

        # Validate search query length
        if parsed_url.search and len(parsed_url.search) > self.max_search_length:
            raise ValueError(
                f"Search query too long: {len(parsed_url.search)} > {self.max_search_length}"
            )

        # Validate selector doesn't contain dangerous characters. Reject every
        # C0 control byte (0x00-0x1f) and DEL (0x7f), not just CR/LF/TAB: a
        # percent-encoded NUL/ESC is decoded by parse_gopher_url and would
        # otherwise be sent verbatim inside the single Gopher request line.
        if re.search(r"[\x00-\x1f\x7f]", parsed_url.selector):
            raise ValueError("Selector contains invalid control characters")

        # Same rule for the search query. TAB in particular must be rejected:
        # the transport joins selector and search with a literal TAB, so an
        # unescaped TAB here would inject an extra field into the request line.
        if parsed_url.search and re.search(r"[\x00-\x1f\x7f]", parsed_url.search):
            raise ValueError("Search query contains invalid control characters")

        # Validate port range
        if not 1 <= parsed_url.port <= 65535:
            raise ValueError(f"Invalid port number: {parsed_url.port}")

    async def fetch(
        self, url: str, *, refresh: bool = False, offset: int = 0
    ) -> GopherFetchResponse:
        """Fetch content from a Gopher URL.

        Args:
            url: Gopher URL to fetch
            refresh: Skip the cache lookup and go to the server. The fresh
                response still replaces the cached one, so this bypasses the
                cache for this read rather than disabling it.
            offset: Where the render window starts -- the item index for a menu,
                the character position for a text body. Pass back the
                ``next_offset`` of a truncated result to read the part that was
                cut; 0 is the beginning. Offsets past the end return an empty
                window, not an error.

        Returns:
            Structured response based on content type

        """
        # ONE budget for the whole call, drawn down by every phase that touches
        # the wire -- including the robots.txt probe, which runs before the
        # fetch it guards and would otherwise be granted a full deadline of its
        # own. Reset in the matching ``finally`` below.
        budget_token = _FETCH_BUDGET.set(_FetchBudget(self.timeout_seconds))
        # Cleared for the same reason the budget is: a ContextVar set inside one
        # fetch outlives it in the caller's context, so a second fetch on the
        # same task would otherwise inherit the first one's rate-limit slot and
        # its already-resolved addresses.
        credit_token = _PROBE_CREDIT.set(None)
        # Set here rather than passed down through ``_bounded_fetch``: that
        # method and ``_fetch_content`` are the seam a subclass (and the robots
        # gate's own fetcher) implement, and widening it for a value only the
        # two render paths read would push the parameter through code that has
        # no use for it. Same lifecycle as the budget above -- a ContextVar set
        # inside one fetch outlives it in the caller's context, so it is reset
        # in the ``finally``, and each task's copy keeps concurrent fetches
        # from reading each other's window.
        offset_token = _RENDER_OFFSET.set(offset)
        # Established here, next to the offset, so the reset in ``finally`` has
        # a token no matter where the request fails. Set to the real key only
        # once the URL has been validated -- an oversized selector or a
        # smuggling attempt is rejected before there is a resource to file a
        # body under, and the token must already exist by then.
        body_key_token = _BODY_SLOT_KEY.set(None)
        try:
            # Rejected rather than clamped: a negative offset is a caller
            # mistake, and silently reading from 0 would answer a question that
            # was not asked.
            if offset < 0:
                raise ValueError("offset must not be negative")

            # Parse the URL
            parsed_url = parse_gopher_url(url)

            # Validate security constraints
            self._validate_security(parsed_url)

            # Answer interactive types before the robots gate. The gate probes
            # /robots.txt, which resolves DNS and dials the host -- exactly the
            # pointless connection this item type is meant to avoid, for a
            # resource that is never fetched over Gopher at all.
            interactive = self._interactive_result(parsed_url)
            if interactive is not None:
                # _interactive_result has no URL string of its own, so the echo
                # every other error carries is completed here rather than left
                # as the empty echo this one code used to return. Assignment on
                # the model, not item assignment: RequestInfo takes writes only
                # through validated attributes, so a misspelt key is a
                # type-check failure here instead of a published nonsense key.
                interactive.request_info.url = url
                return interactive

            # Robot exclusion, before the cache lookup below: a Disallow must
            # also withhold content cached from an earlier, permitted run.
            if self._robots_gate is not None:
                decision = await self._robots_gate.allows(
                    parsed_url.host,
                    parsed_url.port,
                    gopher_candidate_paths(parsed_url.gopher_type, parsed_url.selector),
                )
                if not decision.allowed:
                    return self._robots_denied_result(
                        url, parsed_url.host, decision.reason, decision.detail
                    )

            # Canonical cache key (case-insensitive host) so requests differing
            # only in host case share one entry instead of duplicating.
            cache_key = normalize_cache_key(url)
            # The body is filed under the RESOURCE, so every window of it can be
            # rendered from one download; only the rendered-window cache below
            # is keyed per offset.
            body_key = cache_key
            _BODY_SLOT_KEY.set(body_key)
            if offset:
                # What the cache stores is the RENDERED WINDOW, not the body, so
                # two windows of one resource are two entries -- serving window
                # 0 to a request for window 200 would silently answer the wrong
                # question. The alternative (cache the whole body and window on
                # the way out) would put full-size bodies in a cache whose
                # entry cap exists to bound its memory, so the offset goes in
                # the key instead and a continuation pays for its own fetch.
                # NUL cannot appear in a URL, so this can never collide with a
                # key some other URL normalizes to.
                cache_key = f"{cache_key}\x00offset={offset}"

            # Check cache first, unless the caller asked for the current state.
            if self.cache_enabled and not refresh:
                cached_entry = self._get_cached_entry(cache_key)
                if cached_entry is not None:
                    # Tag the copy handed back so the model can see it is a
                    # replay, and how stale, rather than reading it as current.
                    cached_response = mark_from_cache(
                        cached_entry.value, cached_entry.timestamp
                    )
                    logger.debug(
                        "Cache hit",
                        url=url,
                        cached=True,
                        # Direct attribute access, not getattr with a default:
                        # every member of the response union declares ``kind``,
                        # so a rename or a typo must fail mypy rather than
                        # silently logging "unknown" forever.
                        response_type=cached_response.kind,
                        response_size=self._response_size(cached_response),
                    )
                    return cached_response

            # Create request info for provenance
            request_info = RequestInfo(
                url=url,
                host=parsed_url.host,
                port=parsed_url.port,
                type=parsed_url.gopher_type,
                selector=_display_selector(parsed_url.selector),
                timestamp=iso_utc(time.time()),
            )
            # RFC 1436 gives only type-7 (Index-Search) servers a query field, so
            # _fetch_content drops a ?query on anything else. Say so: a menu (or
            # the model) that mislabels a search item as type 0/1 otherwise gets
            # an unrelated page back with nothing to reveal the terms vanished.
            if parsed_url.search is not None and parsed_url.gopher_type != "7":
                request_info.search_ignored = True

            # A body this client already downloaded serves every remaining
            # window of the same resource. Checked HERE rather than deeper in
            # the transport path because the point is to skip the network
            # entirely -- including the per-host rate limit, which exists to
            # pace requests to a server and must not charge for a request that
            # is never made.
            held = self._reuse_continuation_body(body_key, refresh)
            if held is not None:
                response = self._render_body(
                    held, gopher_type_category(parsed_url.gopher_type)
                )
                logger.debug(
                    "Continuation served from the body already downloaded",
                    url=url,
                    response_type=response.kind,
                )
            else:
                # Fetch the content (optionally bounded by the concurrency cap)
                response = await self._bounded_fetch(parsed_url)
            # Merge (not clobber) so any fields a processor attached survive --
            # matches the Gemini client and avoids a latent maintenance trap.
            response.request_info.merge(request_info)

            # Cache the response, but skip errors: a transient failure would
            # otherwise be served stale for the whole TTL. Mirrors the Gemini
            # client, which excludes error/redirect/input/certificate results.
            if self.cache_enabled and response.kind != "error":
                self._cache_response(cache_key, response)

            # Full URL/selector/search are request metadata; keep them at DEBUG
            # so default INFO logs don't record every browsed resource/query.
            logger.debug(
                "Gopher fetch successful",
                url=url,
                host=parsed_url.host,
                port=parsed_url.port,
                gopher_type=parsed_url.gopher_type,
                selector=_display_selector(parsed_url.selector),
                search=parsed_url.search,
                response_type=response.kind,
                response_size=self._response_size(response),
                cached=False,
            )

            return response

        except HostResolutionError as e:
            # Must precede SSRFError (its base): a name that does not resolve
            # was never refused by the SSRF policy, and reporting it as BLOCKED
            # sends the reader hunting for an allowlist problem.
            return self._error_result(url, "DNS_ERROR", str(e), e)
        except SSRFError as e:
            return self._error_result(url, "BLOCKED", str(e), e)
        except GopherProtocolError as e:
            # Network-level failure (timeout / connection / oversize). The
            # transport keeps these messages free of internal detail.
            return self._error_result(url, "FETCH_ERROR", str(e), e)
        except ValueError as e:
            # Validation errors (allowlist, selector, port) are safe to surface.
            return self._error_result(url, "INVALID_REQUEST", str(e), e)
        except Exception as e:
            return self._error_result(
                url, "FETCH_ERROR", "Failed to fetch the requested resource", e
            )
        finally:
            _FETCH_BUDGET.reset(budget_token)
            _PROBE_CREDIT.reset(credit_token)
            _RENDER_OFFSET.reset(offset_token)
            _BODY_SLOT_KEY.reset(body_key_token)

    async def _bounded_fetch(self, parsed_url: GopherURL) -> GopherFetchResponse:
        """Run the guarded fetch, spending what the robots probe already paid.

        Overrides the base only to skip a *second* per-host rate-limit token:
        the probe and the fetch it guards are one user request to one host, and
        charging both made every first fetch to a host sleep a full interval --
        a second, with the shipped defaults -- before anything could be sent.
        The probe's reservation still spaces the *next* request, and the
        concurrency cap is applied here exactly as the base applies it.
        """
        credit = _PROBE_CREDIT.get()
        if credit is None or not credit.rate_slot or credit.host != parsed_url.host:
            return await super()._bounded_fetch(parsed_url)
        credit.rate_slot = False
        if self._fetch_semaphore is None:
            return await self._fetch_content(parsed_url)
        async with self._fetch_semaphore:
            return await self._fetch_content(parsed_url)

    def _robots_denied_result(
        self, url: str, host: str, reason: str, detail: str | None = None
    ) -> ErrorResult:
        """Build the result returned when the robots gate blocks a resource.

        Gopher fails **open** (``_robots_fail_closed`` is False), so an
        unretrievable policy allows the fetch and only "disallowed" can reach
        here today -- ``ROBOTS_UNAVAILABLE`` is therefore a code this client
        does not currently emit. The branch is written anyway rather than
        assuming: a one-character change to that class attribute would otherwise
        have this assert the host refused us when the host never answered, which
        is precisely the confusion the Gemini side exists to avoid.
        """
        logger.info(
            "Blocked by robots.txt"
            if reason == "disallowed"
            else "Robots probe failed",
            url=url,
            host=host,
            reason=reason,
            detail=detail,
        )
        if reason == "unavailable":
            cause = f" because {detail}" if detail else ""
            message = (
                f"Could not fetch robots.txt from {host}{cause}, so this request "
                f"was refused rather than sent. The host did not disallow this "
                f"resource -- its policy could not be read. Retry shortly."
            )
        else:
            # The single actionable sentence used to be an unconditional "set
            # GOPHER_RESPECT_ROBOTS_TXT=false", which is read by the model, not
            # the operator -- so the natural next step became telling the user to
            # switch off a politeness control the server explicitly opted into.
            # docs/ai-assistant-guide.md says the opposite ("do not suggest
            # disabling robots checking unless the user has said they operate the
            # host"). State the decision and the correct next step first; keep
            # the env-var pointer, under its condition. Kept word-for-word in
            # step with the Gemini wording, which was fixed first.
            message = (
                f"{host} disallows this resource in its robots.txt. "
                f"This is the server operator's decision and will not change on "
                f"a retry: do not retry, and do not try a different spelling of "
                f"the selector. Tell the user the resource is excluded and stop. "
                f"GOPHER_RESPECT_ROBOTS_TXT=false overrides the check, but only "
                f"for a host the user has said they operate."
            )
        code = "ROBOTS_UNAVAILABLE" if reason == "unavailable" else "BLOCKED_BY_ROBOTS"
        return ErrorResult(
            error={"code": code, "message": message},
            request_info=RequestInfo(url=url, timestamp=iso_utc(time.time())),
        )

    async def _fetch_robots(self, host: str, port: int) -> str | None:
        """Fetch ``/robots.txt`` for the robots gate.

        Deliberately bypasses :meth:`fetch` and :meth:`_bounded_fetch`: going
        through the former would recurse into the gate, and the latter holds
        ``_fetch_semaphore``, so a robots lookup issued from inside it would
        deadlock whenever ``max_concurrent_requests`` is 1. The SSRF guard and
        the per-host rate limiter still apply.

        A failure raises :class:`RobotsUnavailable` rather than returning
        ``None``. The two are not interchangeable: ``None`` means "the server
        answered and has no policy", which the gate caches for the full TTL,
        so reporting a timeout that way would disable robots checking for the
        host for 24 hours. The gate is configured ``fail_closed=False`` here, so
        an unavailable policy still allows the request through (Gopher cannot
        distinguish a missing selector from an unreachable server, and the real
        fetch would fail the same way) -- it just is not remembered.

        An over-cap file is truncated and parsed rather than rejected (RFC 9309
        section 2.5). Rejecting it made every request re-download the full cap
        only to discard it, because an unavailable policy is never cached.
        """
        cap = min(ROBOTS_MAX_BYTES, self.max_response_size)
        try:
            async with _spend_budget(self.timeout_seconds) as timeout:
                connect_addresses = await asyncio.wait_for(
                    validate_target(
                        host,
                        port,
                        allow_local=self.allow_local_hosts,
                        allowed_ports=self.allowed_ports,
                    ),
                    timeout=timeout,
                )
            # Outside the budget: waiting for a rate-limit slot is not wire time
            # and must not eat the deadline configured for the exchange itself.
            await self._rate_limiter.acquire(host)
            # The fetch this probe guards is the same user request to the same
            # host, so it inherits this slot and these vetted addresses instead
            # of paying for a second of each. Recorded before the probe's own
            # read: even a probe that then fails has already spent them.
            _PROBE_CREDIT.set(
                _ProbeCredit(
                    host=host,
                    port=port,
                    addresses=connect_addresses,
                    rate_slot=True,
                )
            )
            async with _spend_budget(self.timeout_seconds) as timeout:
                raw = await fetch_gopher(
                    host,
                    port,
                    "/robots.txt",
                    None,
                    max_bytes=cap,
                    timeout=timeout,
                    connect_addresses=connect_addresses,
                    truncate_at_max=True,
                )
        except (TimeoutError, _BudgetExhausted, GopherTimeoutError) as e:
            # _BudgetExhausted and GopherTimeoutError must precede the
            # GopherProtocolError arm below (both are subclasses): a deadline
            # that ran out is a timeout, not a malformed reply.
            raise RobotsUnavailable("the connection timed out") from e
        except HostResolutionError as e:
            raise RobotsUnavailable("the host could not be resolved") from e
        except SSRFError as e:
            raise RobotsUnavailable("the SSRF guard refused the target") from e
        except GopherProtocolError as e:
            raise RobotsUnavailable("the reply was not a valid Gopher response") from e
        except (OSError, ValueError) as e:
            raise RobotsUnavailable("the connection failed") from e
        if len(raw) >= cap:
            # Drop the trailing line: it was cut mid-way, and half a Disallow
            # must not be applied as if it were a whole one.
            logger.warning(
                "robots.txt truncated at the size cap",
                host=host,
                port=port,
                max_bytes=cap,
            )
            raw = raw[: raw.rfind(b"\n") + 1]
        text, _charset = decode_gopher_text(raw)
        return text

    def _interactive_result(self, parsed_url: GopherURL) -> ErrorResult | None:
        """The NOT_FETCHABLE answer for an interactive item, else ``None``.

        Interactive types (telnet/tn3270/CSO) have no Gopher-fetchable body, so
        the answer comes from the item type alone and no connection is needed.
        """
        if gopher_type_category(parsed_url.gopher_type) != "interactive":
            return None
        return ErrorResult(
            error={
                "code": "NOT_FETCHABLE",
                "message": (
                    f"Gopher item type '{parsed_url.gopher_type}' is interactive "
                    f"(telnet/tn3270/CSO) and has no fetchable content; "
                    f"connect to {parsed_url.host}:{parsed_url.port} with an "
                    f"appropriate client."
                ),
            },
            # Echo the request like every other Gopher error does. Returning an
            # empty dict here left exactly one error code uncorrelatable with the
            # request that produced it -- most visibly for one entry of a
            # gopher_batch_fetch list. The ``url`` is filled in by ``fetch``,
            # which is the only caller that has the original string.
            request_info=RequestInfo(
                host=parsed_url.host,
                port=parsed_url.port,
                type=parsed_url.gopher_type,
                selector=_display_selector(parsed_url.selector),
                timestamp=iso_utc(time.time()),
            ),
        )

    async def _fetch_content(self, parsed_url: GopherURL) -> GopherFetchResponse:
        """Fetch content from a parsed Gopher URL over the native transport.

        The configured ``max_response_size`` and ``timeout_seconds`` are
        enforced by :func:`fetch_gopher` (bounded read + overall deadline),
        unlike the previous pituophis path which ignored both.

        Args:
            parsed_url: Parsed Gopher URL

        Returns:
            Appropriate response based on content type
        """
        gopher_type = parsed_url.gopher_type
        category = gopher_type_category(gopher_type)

        # Normally already handled in fetch(); kept so any other caller of
        # _fetch_content still cannot dial an interactive item.
        interactive = self._interactive_result(parsed_url)
        if interactive is not None:
            return interactive

        # SSRF guard: reject internal/loopback/link-local targets before
        # connecting, and pin the connection to the exact IPs we validated so
        # the transport can't re-resolve to a rebinding answer.
        #
        # Bound DNS resolution by the request deadline: getaddrinfo is otherwise
        # unbounded (a tarpit nameserver could stall a worker far past
        # timeout_seconds), so the documented "overall deadline" must cover it
        # too. The wait_for only abandons the lookup -- the worker itself is
        # confined to ssrf.py's own bounded DNS pool, so a stalled resolver can
        # never occupy the event loop's default executor.
        #
        # The robots probe that just ran resolved and vetted this very
        # host:port, so reuse its answer rather than paying for a second
        # getaddrinfo on the same name microseconds later.
        credit = _PROBE_CREDIT.get()
        if (
            credit is not None
            and credit.host == parsed_url.host
            and credit.port == parsed_url.port
        ):
            connect_addresses = credit.addresses
        else:
            try:
                async with _spend_budget(self.timeout_seconds) as timeout:
                    connect_addresses = await asyncio.wait_for(
                        validate_target(
                            parsed_url.host,
                            parsed_url.port,
                            allow_local=self.allow_local_hosts,
                            allowed_ports=self.allowed_ports,
                        ),
                        timeout=timeout,
                    )
            except TimeoutError as e:
                raise GopherProtocolError(
                    f"Timed out resolving host '{parsed_url.host}'"
                ) from e

        # RFC 1436 only defines the <TAB>query field for type-7 (Index-Search)
        # servers; never forward a stray search to a plain selector.
        search = parsed_url.search if gopher_type == "7" else None

        try:
            async with _spend_budget(self.timeout_seconds) as transport_timeout:
                raw = await fetch_gopher(
                    parsed_url.host,
                    parsed_url.port,
                    parsed_url.selector,
                    search,
                    max_bytes=self.max_response_size,
                    timeout=transport_timeout,
                    connect_addresses=connect_addresses,
                )
        except GopherTimeoutError as e:
            # The transport is handed whatever is LEFT of the deadline, so it
            # named that remainder as "the timeout" -- an 18-digit fraction that
            # matches nothing the operator configured and, after a slow robots
            # probe, can read as absurdly small ("why is my timeout 0.08
            # seconds?"). Re-phrase against the configured deadline, which is
            # the one that was actually reached; _BudgetExhausted already words
            # it this way.
            raise GopherProtocolError(
                f"The request timed out after {self.timeout_seconds} seconds"
            ) from e

        response = self._render_body(raw, category)
        self._remember_continuation_body(raw, response)
        return response

    def _render_body(self, raw: bytes, category: str) -> GopherFetchResponse:
        """Turn a downloaded body into the window the caller asked for.

        Split out from :meth:`_fetch_content` so a body already in hand can be
        re-rendered at a new offset without going back to the server. Pure: no
        I/O, no rate limit, no robots probe -- everything here operates on bytes
        that have already been fetched and vetted.
        """
        # Where the caller asked the render window to start. The whole response
        # is still read from the server -- Gopher has no range request -- so
        # this windows what is handed to the model, not what is transferred.
        offset = _RENDER_OFFSET.get()

        if category == "menu":
            # Menu/directory or search results (which are menus)
            return self._process_menu_response(raw, offset)
        elif category == "binary":
            # Binary content - return metadata only (no body to window).
            return self._process_binary_response(raw)
        else:
            # Text (type 0, h/HTML, i/info) and unknown types - try as text
            return self._process_text_response(raw, offset)

    def _remember_continuation_body(
        self, raw: bytes, response: GopherFetchResponse
    ) -> None:
        """Hold this body only if a later window could ask for it.

        A response that was not truncated has no next window, so keeping its
        body would spend the slot on a resource nothing will ask about again and
        evict one that is mid-walk.
        """
        key = _BODY_SLOT_KEY.get()
        if key is None or not self.cache_enabled:
            return
        if getattr(response, "next_offset", None) is None:
            return
        self._continuation_body = _ContinuationBody(key, raw, time.time())

    def _reuse_continuation_body(self, key: str, refresh: bool) -> bytes | None:
        """The body for ``key`` if this client just downloaded it.

        ``refresh`` means "go and look again", so it must miss here as well as
        in the response cache -- otherwise the flag would silently re-render
        stale bytes. The slot expires on the same TTL as a cached response, so a
        continuation can never outlive the freshness the rest of the client
        promises.
        """
        held = self._continuation_body
        if held is None or refresh or not self.cache_enabled:
            return None
        if held.key != key:
            return None
        if time.time() - held.stored_at > self.cache_ttl_seconds:
            self._continuation_body = None
            return None
        return held.raw

    def _process_menu_response(self, raw: bytes, offset: int = 0) -> MenuResult:
        """Parse a Gopher menu (RFC 1436) into a structured result.

        Uses the project's own ``parse_gopher_menu``, which honours the
        ``.`` terminator and skips malformed lines. An empty result means
        an empty directory, not a swallowed parse failure (unexpected
        errors propagate to the caller and surface as an ErrorResult).

        Args:
            raw: Raw response bytes from the server
            offset: Index of the first item to return, so a directory bigger
                than the render cap can be read a window at a time.

        Returns:
            Parsed menu result
        """
        # The charset goes with the content: each item's nextUrl percent-encodes
        # the selector back into its ON-WIRE bytes, so a latin-1 menu's links
        # stay fetchable from the server that published them.
        content, charset = decode_gopher_text(raw)
        # Cap the number of items handed to the LLM (distinct from the network
        # byte cap): a 1 MB directory can expand to tens of thousands of items,
        # each serialized to JSON, flooding the model context. 0 = unlimited.
        # Parse at most one past the cap so we never materialise the whole
        # directory yet can still tell whether it was truncated.
        if self.max_menu_items:
            parsed = parse_gopher_menu(
                content, max_items=offset + self.max_menu_items + 1, charset=charset
            )
            items = parsed[offset : offset + self.max_menu_items]
            truncated = len(parsed) > offset + self.max_menu_items
            # An exact count only when the parse ended on its own: hitting the
            # cap proves there are more items but not how many, and inventing a
            # number would be worse than admitting none. Counting the rest would
            # mean materialising the whole directory, which is precisely what
            # the cap above exists to avoid -- `next_offset` is what makes the
            # remainder reachable regardless.
            total_items = None if truncated else len(parsed)
        else:
            parsed = parse_gopher_menu(content, charset=charset)
            items = parsed[offset:]
            truncated = False
            total_items = len(parsed)
        return MenuResult(
            items=items,
            truncated=truncated,
            total_items=total_items,
            next_offset=offset + len(items) if truncated else None,
        )

    def _process_text_response(self, raw: bytes, offset: int = 0) -> TextResult:
        """Process a Gopher text response.

        Args:
            raw: Raw response bytes from the server
            offset: Character position the returned window starts at, so a body
                longer than the render cap can be read a window at a time.

        Returns:
            Text result
        """
        text_content, charset = decode_gopher_text(raw)

        # Reverse RFC 1436 text-mode framing before sanitizing: drop a trailing
        # lone-'.' terminator line and un-dot-stuff lines beginning with '..'.
        text_content = _strip_gopher_text_terminator(text_content)

        # Server-controlled text: drop control characters, but keep the
        # whitespace that carries a multi-line body's structure.
        sanitized_text = sanitize_display_text(text_content)

        # Normalise line endings to LF. RFC 1436 frames lines with CRLF, but the
        # CR carries no information -- and the gemtext parser already strips it
        # -- so every line of every CRLF-served page was spending an escaped
        # "\r" in the JSON handed to the model. Bare CR (legacy Mac) is folded
        # too, so a CR-only document is not one unreadable line.
        sanitized_text = sanitized_text.replace("\r\n", "\n").replace("\r", "\n")

        # Cap the text handed to the LLM (distinct from the network byte cap);
        # `bytes` still reports the full original size. The window is measured
        # in characters, which is what `next_offset` speaks -- `bytes` cannot be
        # used as an offset without risking a split UTF-8 sequence.
        window = window_text(sanitized_text, offset, self.max_rendered_chars)

        return TextResult(
            text=window.text,
            bytes=len(raw),
            charset=charset,
            truncated=window.next_offset is not None,
            total_chars=window.total,
            next_offset=window.next_offset,
        )

    # Note: Search is handled by _process_menu_response since search results are menus

    def _process_binary_response(self, raw: bytes) -> BinaryResult:
        """Process a Gopher binary response (metadata only; no bytes to the LLM).

        Args:
            raw: Raw response bytes from the server

        Returns:
            Binary result with size and sniffed MIME type
        """
        return BinaryResult(
            bytes=len(raw),
            mime_type=detect_binary_mime_type(raw),
        )

    # The cache accessors, _bounded_fetch, _error_result and close() are
    # provided by FetchClientBase.
