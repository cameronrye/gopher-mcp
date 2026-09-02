"""Shared fetch-pipeline scaffolding for the protocol clients.

The Gopher and Gemini clients previously carried a character-for-character
identical copy of everything wrapped *around* their protocol-specific fetch --
the rate-limit/concurrency bounding, the host allowlist, the robots gate wiring,
the cache setup and the sanitized error builder -- so any fix had to be applied
twice. This base class holds the one implementation, parameterised by the few
things that genuinely differ (agent tokens, the robots fail-open/closed choice,
the parsed-URL type); each client supplies only ``_fetch_content`` and
``_fetch_robots``.
"""

import asyncio
import contextlib
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import ClassVar, Generic, Protocol, TypeVar

import structlog

from .cache import TTLCacheMixin
from .models import ErrorResult, iso_utc
from .ratelimit import RateLimiter
from .robots import AI_AGENT_TOKENS, RobotsGate
from .ssrf import normalize_host

logger = structlog.get_logger(__name__)


class ParsedURL(Protocol):
    """The host/port pair every parsed protocol URL exposes."""

    host: str
    port: int


ResponseT = TypeVar("ResponseT")
UrlT = TypeVar("UrlT", bound=ParsedURL)


@dataclass
class _FetchBudget:
    """Network time still available to one ``fetch()`` call.

    ``timeout_seconds`` is documented -- in ``docs/configuration.md`` and in
    ``config/example.env`` -- as the "overall deadline for one fetch, covering
    DNS, connect, send and read". Handing each phase the full value instead let
    one call against a tarpit, answering every phase just under the limit,
    occupy several multiples of the configured deadline; with robots checking on
    by default the probe added phases of its own. This makes the documented
    sentence true.
    """

    remaining: float


# Budget for the fetch currently running in this task. A ContextVar rather than
# an argument because the robots probe is invoked through RobotsGate, which owns
# its fetcher signature; each task copies the context, so concurrent fetches get
# their own budget.
_FETCH_BUDGET: ContextVar[_FetchBudget | None] = ContextVar(
    "fetch_budget", default=None
)


class _BudgetExhausted(TimeoutError):
    """The fetch deadline ran out before this phase could start.

    Subclasses :class:`TimeoutError` because that is what it is, and because
    both clients already have a handler arm that maps a timeout to "the request
    timed out" rather than to their generic "malformed reply" message. A client
    whose error mapping keys off a protocol-specific base (Gopher's
    ``GopherProtocolError``) subclasses this alongside it and passes the
    subclass to :func:`_spend_budget`.
    """


@contextlib.asynccontextmanager
async def _spend_budget(
    default_timeout: float,
    exhausted_cls: type[_BudgetExhausted] = _BudgetExhausted,
) -> AsyncIterator[float]:
    """Yield the timeout for one wire phase, then charge what it used.

    Every phase that touches the network goes through here -- the robots
    probe's DNS lookup and transport read, then the guarded fetch's own two --
    so all of them draw down one deadline instead of each being handed a full
    one. Outside a fetch (no budget in the context) it yields the configured
    timeout unchanged, which is what a direct call to a client's internals gets.

    Args:
        default_timeout: The configured per-fetch deadline, yielded when no
            budget is active and quoted in the exhausted message.
        exhausted_cls: Exception raised when the budget is already spent; a
            client overrides it to keep its own error-mapping lineage.

    Yields:
        The number of seconds this phase may take.

    Raises:
        _BudgetExhausted: If nothing is left of the deadline. Only the phase
            that has not started yet is refused; a phase already running is
            bounded by the timeout it was handed.
    """
    budget = _FETCH_BUDGET.get()
    if budget is None:
        yield default_timeout
        return
    if budget.remaining <= 0:
        raise exhausted_cls(f"The request timed out after {default_timeout} seconds")
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        yield budget.remaining
    finally:
        budget.remaining -= loop.time() - started


class FetchClientBase(TTLCacheMixin[ResponseT], Generic[ResponseT, UrlT]):
    """Protocol-agnostic half of a fetch client.

    A subclass sets the class attributes below and ``_cache_entry_cls``, passes
    the shared settings to ``super().__init__``, and implements the two
    protocol-specific coroutines.
    """

    #: Protocol name used in log event names ("Gopher" / "Gemini").
    _log_label: ClassVar[str]
    #: Agent tokens the robots gate matches, most specific first.
    _robots_tokens: ClassVar[tuple[str, ...]]
    #: What the robots gate does when a policy cannot be retrieved.
    _robots_fail_closed: ClassVar[bool]
    #: Field on this protocol's results that carries the content length.
    #:
    #: One concept, two wire names: Gopher results call it ``bytes``
    #: (``TextResult``/``BinaryResult``) and Gemini results call it ``size``
    #: (``GeminiSuccessResult``/``GeminiBinaryResult``/``GeminiGemtextResult``).
    #: The names are part of the published tool output that
    #: ``docs/api-reference.md`` documents, so they are NOT unified on the wire
    #: -- renaming either would break every consumer. This indirection keeps the
    #: divergence in one place instead of making every protocol-agnostic caller
    #: know which protocol says which.
    _response_size_field: ClassVar[str]

    def __init__(
        self,
        *,
        max_response_size: int,
        timeout_seconds: float,
        cache_enabled: bool,
        cache_ttl_seconds: int,
        max_cache_entries: int,
        allowed_hosts: list[str] | None,
        allow_local_hosts: bool,
        allowed_ports: list[int] | None,
        max_rendered_chars: int,
        requests_per_minute: float,
        max_concurrent_requests: int,
        respect_robots_txt: bool,
        robots_cache_ttl_seconds: int,
        robots_honor_ai_tokens: bool,
        robots_failure_backoff_seconds: float,
    ) -> None:
        """Initialize the settings every protocol client shares.

        Args:
            max_response_size: Maximum response size in bytes
            timeout_seconds: Request timeout in seconds
            cache_enabled: Whether to enable response caching
            cache_ttl_seconds: Cache TTL in seconds
            max_cache_entries: Maximum number of cache entries
            allowed_hosts: List of allowed hostnames (None = allow all)
            allow_local_hosts: Permit loopback/private/internal targets
            allowed_ports: Optional positive port allowlist
            max_rendered_chars: LLM-facing cap on returned text characters
            requests_per_minute: Per-host outbound request rate cap
            max_concurrent_requests: Cap on simultaneous in-flight fetches
                (0 = unlimited); a coarse bound on concurrent sockets/memory.
            respect_robots_txt: Consult /robots.txt at the host root before
                fetching.
            robots_cache_ttl_seconds: Lifetime of a cached robots policy.
            robots_honor_ai_tokens: Also honour rules naming AI crawler
                tokens (ClaudeBot, GPTBot, ...).
            robots_failure_backoff_seconds: How long a host whose
                /robots.txt probe failed is left alone before being probed
                again; 0 retries on the very next request.

        """
        self.max_response_size = max_response_size
        self.timeout_seconds = timeout_seconds
        # A zero TTL stores entries that are already expired when they are read
        # back (_BaseCacheEntry.is_expired), i.e. all of the bookkeeping and none
        # of the hits, so treat it as caching off -- as the config layer does.
        self.cache_enabled = cache_enabled and cache_ttl_seconds > 0
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_entries = max_cache_entries
        self.max_rendered_chars = max_rendered_chars
        self._rate_limiter = RateLimiter(requests_per_minute)
        self.max_concurrent_requests = max_concurrent_requests
        # Coarse cap on simultaneous fetches; 0 disables it (None = unlimited).
        self._fetch_semaphore = (
            asyncio.Semaphore(max_concurrent_requests)
            if max_concurrent_requests > 0
            else None
        )

        self.allow_local_hosts = allow_local_hosts
        self.allowed_ports = allowed_ports

        # Convert allowed hosts to a set for faster lookup. An explicitly EMPTY
        # allowlist is an allowlist that admits nothing, not "no allowlist" --
        # matching how allowed_ports already behaves in ssrf.validate_target.
        # Normalized once here (case, trailing dot, IPv6 brackets) so the
        # per-request check is a plain membership test.
        self.allowed_hosts: set[str] | None = (
            {normalize_host(h) for h in allowed_hosts}
            if allowed_hosts is not None
            else None
        )

        # LRU cache (get/put behaviour lives in TTLCacheMixin). The element type
        # is inherited from the mixin annotation; each client supplies its own
        # ``_cache_entry_cls``.
        self._cache = OrderedDict()

        # Robot exclusion (opt-in); the fail-open/closed choice is the
        # protocol's, and is documented on each client's class attribute.
        self.respect_robots_txt = respect_robots_txt
        self._robots_gate = (
            RobotsGate(
                # Resolved at call time rather than bound here, so the
                # gate follows the method (and stays patchable in tests).
                fetcher=lambda host, port: self._fetch_robots(host, port),
                tokens=self._robots_tokens,
                extra_tokens=(AI_AGENT_TOKENS if robots_honor_ai_tokens else ()),
                ttl_seconds=robots_cache_ttl_seconds,
                fail_closed=self._robots_fail_closed,
                failure_backoff_seconds=robots_failure_backoff_seconds,
            )
            if respect_robots_txt
            else None
        )

    @contextlib.contextmanager
    def _budget(self) -> Iterator[None]:
        """Open ONE deadline for the whole call, for the duration of the block.

        Entered at the top of ``fetch()`` rather than in ``_bounded_fetch``: the
        robots.txt probe runs before that, on the way to deciding whether the
        fetch may happen at all, and would otherwise be granted a full deadline
        of its own on top of the one the fetch gets.

        Yields:
            None; the budget lives in a ContextVar, read by
            :func:`_spend_budget` at each wire phase.
        """
        token = _FETCH_BUDGET.set(_FetchBudget(self.timeout_seconds))
        try:
            yield
        finally:
            # A ContextVar set inside one fetch outlives it in the caller's
            # context, so a second fetch on the same task would otherwise
            # inherit whatever the first one had left.
            _FETCH_BUDGET.reset(token)

    def _response_size(self, response: ResponseT) -> int:
        """Return ``response``'s content length, whatever this protocol calls it.

        Defaults to 0 for the members of the response union that carry no body
        at all (menus, errors, redirects, input prompts), which is what the log
        lines want: "no bytes of content", not "unknown".
        """
        size = getattr(response, self._response_size_field, 0)
        return size if isinstance(size, int) else 0

    def _host_is_allowed(self, host: str) -> bool:
        """Return whether ``host`` passes the configured allowlist.

        The allowlist was normalized at construction (case, trailing dot, IPv6
        brackets) to close bypasses, so ``host`` is normalized the same way here.
        """
        return self.allowed_hosts is None or normalize_host(host) in self.allowed_hosts

    def _safe_error_url(self, url: str) -> str:
        """Return the form of ``url`` that may be logged and echoed back."""
        return url

    def _error_result(
        self, url: str, code: str, message: str, exc: Exception
    ) -> ErrorResult:
        """Build a sanitized error result, logging full detail server-side."""
        safe_url = self._safe_error_url(url)
        logger.error(
            f"{self._log_label} fetch failed",
            url=safe_url,
            code=code,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return ErrorResult(
            error={"code": code, "message": message},
            request_info={"url": safe_url, "timestamp": iso_utc(time.time())},
        )

    async def _bounded_fetch(self, parsed_url: UrlT) -> ResponseT:
        """Run :meth:`_fetch_content`, bounded by the concurrency cap if set.

        The per-host spacing is waited out BEFORE a concurrency slot is
        taken. Sleeping while holding the semaphore would let one
        throttled host occupy every slot, starving unrelated hosts that
        are not rate limited at all -- harmless when both settings were
        off by default, but not now that they ship enabled.
        """
        await self._rate_limiter.acquire(parsed_url.host)
        if self._fetch_semaphore is None:
            return await self._fetch_content(parsed_url)
        async with self._fetch_semaphore:
            return await self._fetch_content(parsed_url)

    async def _fetch_content(self, parsed_url: UrlT) -> ResponseT:
        """Fetch one resource over the protocol's own transport."""
        raise NotImplementedError

    async def _fetch_robots(self, host: str, port: int) -> str | None:
        """Fetch ``/robots.txt`` from ``host:port`` for the robots gate."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        self._cache.clear()
        logger.info(f"{self._log_label} client closed")
