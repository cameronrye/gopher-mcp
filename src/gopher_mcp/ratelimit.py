"""Per-host outbound rate limiting.

Gopher and Gemini are largely hobbyist ecosystems served by small, fragile
hosts. A model can call the fetch tools in a tight loop and hammer one server,
so both clients route each outbound request through a :class:`RateLimiter` that
enforces a minimum spacing between requests *to the same host* and honours a
server's request to slow down (Gemini status 44).

The limiter is disabled by default (``requests_per_minute=0``); operators opt in
via ``GOPHER_REQUESTS_PER_MINUTE`` / ``GEMINI_REQUESTS_PER_MINUTE``.
"""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

# Upper bound on a single SLOW_DOWN (status-44) backoff. The Gemini spec lets a
# server name any number of seconds to wait, but the meta is attacker-controlled:
# an unclamped value (notably ``inf``) makes ``acquire`` sleep effectively
# forever while holding the per-client/batch concurrency semaphore, hanging every
# later fetch -- and the penalty persists in ``_next_allowed``, poisoning the
# host. Cap it so a server can still ask us to slow down, but only within a
# bounded window (matches the configurable request-timeout ceiling).
MAX_PENALTY_SECONDS = 300.0


class RateLimiter:
    """Throttle outbound requests to at most one per ``min_interval`` per host.

    The clock and sleep function are injectable so the spacing logic can be
    tested deterministically without real time passing.
    """

    def __init__(
        self,
        requests_per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Initialize the limiter.

        Args:
            requests_per_minute: Allowed requests per host per minute; 0 (or
                less) disables interval throttling (penalties still apply).
            clock: Monotonic clock source (injectable for tests).
            sleep: Async sleep function (injectable for tests).
        """
        self.min_interval = (
            60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        )
        self._next_allowed: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._clock = clock
        self._sleep = sleep
        # When throttling is enabled, hosts visited once would otherwise live in
        # ``_next_allowed`` forever (an "open-world" fetcher sees unbounded
        # distinct hosts). Once the map grows past this many entries, sweep out
        # hosts whose reservation has already elapsed (they impose no future
        # constraint, so dropping them is behaviour-preserving).
        self._sweep_threshold = 1024

    async def acquire(self, host: str) -> None:
        """Block until a request to ``host`` is permitted.

        Fast-paths out entirely when throttling is disabled and the host carries
        no outstanding penalty, so it adds no overhead in the default config.
        """
        if self.min_interval <= 0 and host not in self._next_allowed:
            return

        async with self._lock:
            now = self._clock()
            allowed_at = self._next_allowed.get(host, 0.0)
            wait = allowed_at - now
            base = allowed_at if wait > 0 else now
            if self.min_interval > 0:
                self._next_allowed[host] = base + self.min_interval
                # Bound memory: drop hosts whose reserved time has already
                # passed. The host just reserved above is in the future, so it
                # survives. Amortized via the threshold so the common path stays
                # O(1).
                if len(self._next_allowed) > self._sweep_threshold:
                    self._next_allowed = {
                        h: t for h, t in self._next_allowed.items() if t > now
                    }
            elif wait <= 0:
                # Disabled and the penalty (if any) has elapsed -- forget the host.
                self._next_allowed.pop(host, None)

        if wait > 0:
            logger.debug("Rate limiting outbound request", host=host, wait_s=wait)
            await self._sleep(wait)

    def penalize(self, host: str, seconds: float) -> None:
        """Back off all requests to ``host`` for at least ``seconds``.

        Used to honour a Gemini status-44 (SLOW_DOWN) response. ``seconds`` is
        server-controlled, so it is sanitized: a non-finite value (``inf``/NaN)
        is rejected and anything over ``MAX_PENALTY_SECONDS`` is clamped, so a
        malicious server cannot pin the host (and a held semaphore slot) forever.
        """
        seconds = float(seconds)
        if not math.isfinite(seconds) and seconds == float("inf"):
            # An explicit "wait forever" is treated as the maximum bounded wait.
            seconds = MAX_PENALTY_SECONDS
        elif not math.isfinite(seconds):
            # NaN (or -inf): not a meaningful backoff -- ignore rather than
            # writing a value that would wedge the reservation.
            return
        seconds = min(max(seconds, 0.0), MAX_PENALTY_SECONDS)
        if seconds <= 0.0:
            return

        now = self._clock()
        self._next_allowed[host] = max(self._next_allowed.get(host, 0.0), now + seconds)
        logger.debug("Backing off host after slow-down", host=host, seconds=seconds)
