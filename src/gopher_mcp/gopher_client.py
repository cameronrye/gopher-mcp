"""Gopher protocol client implementation."""

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass

import structlog

from .client_base import FetchClientBase
from .gopher_transport import GopherProtocolError, decode_gopher_text, fetch_gopher
from .helpers import sanitize_display_text
from .models import (
    BinaryResult,
    CacheEntry,
    ErrorResult,
    GopherFetchResponse,
    GopherURL,
    MenuResult,
    TextResult,
    mark_from_cache,
)
from .robots import (
    GOPHER_TOKENS,
    ROBOTS_MAX_BYTES,
    RobotsUnavailable,
    gopher_candidate_paths,
)
from .ssrf import HostResolutionError, SSRFError, validate_target
from .utils import (
    detect_binary_mime_type,
    gopher_type_category,
    normalize_cache_key,
    parse_gopher_menu,
    parse_gopher_url,
    truncate_text,
)

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

    async def fetch(self, url: str, *, refresh: bool = False) -> GopherFetchResponse:
        """Fetch content from a Gopher URL.

        Args:
            url: Gopher URL to fetch
            refresh: Skip the cache lookup and go to the server. The fresh
                response still replaces the cached one, so this bypasses the
                cache for this read rather than disabling it.

        Returns:
            Structured response based on content type

        """
        # ONE budget for the whole call, drawn down by every phase that touches
        # the wire -- including the robots.txt probe, which runs before the
        # fetch it guards and would otherwise be granted a full deadline of its
        # own. Reset in the matching ``finally`` below.
        budget_token = _FETCH_BUDGET.set(_FetchBudget(self.timeout_seconds))
        try:
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
                        response_type=getattr(cached_response, "kind", "unknown"),
                        response_size=getattr(cached_response, "bytes", 0),
                    )
                    return cached_response

            # Create request info for provenance
            request_info = {
                "url": url,
                "host": parsed_url.host,
                "port": parsed_url.port,
                "type": parsed_url.gopher_type,
                "selector": parsed_url.selector,
                "timestamp": time.time(),
            }

            # Fetch the content (optionally bounded by the concurrency cap)
            response = await self._bounded_fetch(parsed_url)
            # Merge (not clobber) so any fields a processor attached survive --
            # matches the Gemini client and avoids a latent maintenance trap.
            if hasattr(response, "request_info"):
                response.request_info.update(request_info)

            # Cache the response, but skip errors: a transient failure would
            # otherwise be served stale for the whole TTL. Mirrors the Gemini
            # client, which excludes error/redirect/input/certificate results.
            if self.cache_enabled and getattr(response, "kind", None) != "error":
                self._cache_response(cache_key, response)

            # Full URL/selector/search are request metadata; keep them at DEBUG
            # so default INFO logs don't record every browsed resource/query.
            logger.debug(
                "Gopher fetch successful",
                url=url,
                host=parsed_url.host,
                port=parsed_url.port,
                gopher_type=parsed_url.gopher_type,
                selector=parsed_url.selector,
                search=parsed_url.search,
                response_type=getattr(response, "kind", "unknown"),
                response_size=getattr(response, "bytes", 0),
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
            message = (
                f"{host} disallows this resource in its robots.txt. "
                f"Set GOPHER_RESPECT_ROBOTS_TXT=false to disable robots "
                f"checking."
            )
        code = "ROBOTS_UNAVAILABLE" if reason == "unavailable" else "BLOCKED_BY_ROBOTS"
        return ErrorResult(
            error={"code": code, "message": message},
            requestInfo={"url": url, "timestamp": time.time()},
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
        except (TimeoutError, _BudgetExhausted) as e:
            # _BudgetExhausted must precede the GopherProtocolError arm below
            # (it is a subclass): a deadline that ran out is a timeout, not a
            # malformed reply.
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
            }
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

        if category == "menu":
            # Menu/directory or search results (which are menus)
            return self._process_menu_response(raw)
        elif category == "binary":
            # Binary content - return metadata only
            return self._process_binary_response(raw)
        else:
            # Text (type 0, h/HTML, i/info) and unknown types - try as text
            return self._process_text_response(raw)

    def _process_menu_response(self, raw: bytes) -> MenuResult:
        """Parse a Gopher menu (RFC 1436) into a structured result.

        Uses the project's own ``parse_gopher_menu``, which honours the
        ``.`` terminator and skips malformed lines. An empty result means
        an empty directory, not a swallowed parse failure (unexpected
        errors propagate to the caller and surface as an ErrorResult).

        Args:
            raw: Raw response bytes from the server

        Returns:
            Parsed menu result
        """
        content, _ = decode_gopher_text(raw)
        # Cap the number of items handed to the LLM (distinct from the network
        # byte cap): a 1 MB directory can expand to tens of thousands of items,
        # each serialized to JSON, flooding the model context. 0 = unlimited.
        # Parse at most one past the cap so we never materialise the whole
        # directory yet can still tell whether it was truncated.
        if self.max_menu_items:
            items = parse_gopher_menu(content, max_items=self.max_menu_items + 1)
            truncated = len(items) > self.max_menu_items
            if truncated:
                items = items[: self.max_menu_items]
        else:
            items = parse_gopher_menu(content)
            truncated = False
        return MenuResult(items=items, truncated=truncated)

    def _process_text_response(self, raw: bytes) -> TextResult:
        """Process a Gopher text response.

        Args:
            raw: Raw response bytes from the server

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

        # Cap the text handed to the LLM (distinct from the network byte cap);
        # `bytes` still reports the full original size.
        rendered, truncated = truncate_text(sanitized_text, self.max_rendered_chars)

        return TextResult(
            text=rendered,
            bytes=len(raw),
            charset=charset,
            truncated=truncated,
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
            mimeType=detect_binary_mime_type(raw),
        )

    # The cache accessors, _bounded_fetch, _error_result and close() are
    # provided by FetchClientBase.
