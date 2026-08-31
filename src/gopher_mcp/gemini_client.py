"""Gemini protocol client implementation."""

import asyncio
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog

from .cache import TTLCacheMixin
from .client_certs import ClientCertificateManager
from .gemini_parse import GeminiProtocolError
from .gemini_tls import GeminiTLSClient, TLSConfig, TLSConnection, TLSConnectionError
from .models import (
    GeminiCacheEntry,
    GeminiCertificateInfo,
    GeminiErrorResult,
    GeminiFetchResponse,
    GeminiURL,
    TOFUEntry,
)
from .ratelimit import RateLimiter
from .robots import (
    AI_AGENT_TOKENS,
    GEMINI_TOKENS,
    ROBOTS_MAX_BYTES,
    RobotsGate,
    RobotsUnavailable,
)
from .ssrf import SSRFError, normalize_host, validate_target
from .tofu import (
    TOFUExpiredError,
    TOFUManager,
    TOFUStorageError,
    TOFUUnavailableError,
    TOFUValidationError,
)
from .utils import (
    bracket_host,
    normalize_cache_key,
    parse_gemini_response,
    parse_gemini_url,
    process_gemini_response,
)

logger = structlog.get_logger(__name__)

# Default configuration constants
DEFAULT_MAX_RESPONSE_SIZE = 1024 * 1024  # 1MB
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_CACHE_ENTRIES = 1000
DEFAULT_MAX_RENDERED_CHARS = 50000  # LLM-facing text cap; 0 = unlimited
# Politeness defaults. Gopher and Gemini are served largely by small
# hobbyist hosts, and a model can call the fetch tools in a tight loop, so
# both are on out of the box rather than opt-in.
DEFAULT_REQUESTS_PER_MINUTE = 60.0  # one request per second, per host
DEFAULT_MAX_CONCURRENT_REQUESTS = 5  # matches the batch tools' concurrency
DEFAULT_ROBOTS_CACHE_TTL_SECONDS = 86400  # RFC 9309 s2.4 permits 24h


@dataclass
class _FetchBudget:
    """Network time still available to one :meth:`GeminiClient.fetch` call.

    ``timeout_seconds`` is a budget for the whole exchange, not for each phase.
    Every :meth:`GeminiClient._fetch_content` charges the time it spends on the
    wire against this, so the robots.txt probe and the fetch it guards share one
    deadline instead of each being granted a full one.
    """

    remaining: float


# Budget for the fetch currently running in this task. A ContextVar rather than
# an argument because the robots probe is invoked through RobotsGate, which owns
# its fetcher signature; each task copies the context, so concurrent fetches get
# their own budget.
_FETCH_BUDGET: ContextVar[_FetchBudget | None] = ContextVar(
    "gemini_fetch_budget", default=None
)


def _ipv4_first(addresses: list[str]) -> list[str]:
    """Order vetted connect addresses IPv4 first, keeping every one of them.

    IPv4 leads because the historical behaviour was AF_INET-only, but the IPv6
    answers are retained so an IPv6-only host still resolves to something to
    try -- and so a dual-homed host survives its first address being down.
    """
    return [a for a in addresses if ":" not in a] + [a for a in addresses if ":" in a]


def _safe_display_url(parsed_url: GeminiURL) -> str:
    """Render a ``gemini://`` URL WITHOUT its query string.

    A status-10/11 input answer is percent-encoded into the query and may be a
    secret (status 11 = SENSITIVE_INPUT), so the query must never be logged or
    reflected back to the caller. This mirrors the host/port/path-only logging
    used throughout this module.
    """
    url = f"gemini://{bracket_host(parsed_url.host)}"
    if parsed_url.port != 1965:
        url = f"{url}:{parsed_url.port}"
    return f"{url}{parsed_url.path}"


class GeminiClient(TTLCacheMixin[GeminiFetchResponse]):
    """Async Gemini protocol client with TLS, caching and safety features."""

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
        tls_config: TLSConfig | None = None,
        tofu_enabled: bool = True,
        tofu_storage_path: str | None = None,
        tofu_reject_expired: bool = False,
        client_certs_enabled: bool = True,
        client_certs_storage_path: str | None = None,
        max_rendered_chars: int = DEFAULT_MAX_RENDERED_CHARS,
        requests_per_minute: float = DEFAULT_REQUESTS_PER_MINUTE,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
        denied_mime_types: list[str] | None = None,
        respect_robots_txt: bool = False,
        robots_cache_ttl_seconds: int = DEFAULT_ROBOTS_CACHE_TTL_SECONDS,
        robots_honor_ai_tokens: bool = True,
    ) -> None:
        """Initialize the Gemini client.

        Args:
            max_response_size: Maximum response size in bytes
            timeout_seconds: Request timeout in seconds
            cache_enabled: Whether to enable response caching
            cache_ttl_seconds: Cache TTL in seconds
            max_cache_entries: Maximum number of cache entries
            allowed_hosts: List of allowed hostnames (None = allow all)
            tls_config: TLS configuration (uses defaults if None)
            tofu_enabled: Whether to enable TOFU certificate validation
            tofu_storage_path: Path to TOFU storage file
            tofu_reject_expired: Fail closed on a certificate outside its
                validity window instead of accepting it with a warning
            client_certs_enabled: Whether to enable client certificate management
            client_certs_storage_path: Path to client certificate storage directory
            respect_robots_txt: Consult /robots.txt at the capsule root before
                fetching, per the Gemini companion specification
            robots_cache_ttl_seconds: Lifetime of a cached robots policy
            robots_honor_ai_tokens: Also honour rules naming AI crawler tokens
                (ClaudeBot, GPTBot, ...)
        """
        self.max_response_size = max_response_size
        self.timeout_seconds = timeout_seconds
        self.cache_enabled = cache_enabled
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
        self.denied_mime_types = frozenset(denied_mime_types or ())
        # An explicitly EMPTY allowlist is an allowlist that admits nothing, not
        # "no allowlist" -- matching how allowed_ports already behaves in
        # ssrf.validate_target. Normalized once here (case, trailing dot, IPv6
        # brackets) so the per-request check is a plain membership test.
        self.allowed_hosts: set[str] | None = (
            {normalize_host(h) for h in allowed_hosts}
            if allowed_hosts is not None
            else None
        )
        self.allow_local_hosts = allow_local_hosts
        self.allowed_ports = allowed_ports
        self.tofu_enabled = tofu_enabled
        self.client_certs_enabled = client_certs_enabled

        # Initialize TLS client
        if tls_config is None:
            tls_config = TLSConfig(timeout_seconds=timeout_seconds)
        self.tls_client = GeminiTLSClient(tls_config)

        # Initialize TOFU manager
        self.tofu_manager: TOFUManager | None = None
        if self.tofu_enabled:
            self.tofu_manager = TOFUManager(
                tofu_storage_path, reject_expired=tofu_reject_expired
            )
        else:
            # Gemini TLS runs with CERT_NONE, so TOFU is the ONLY peer
            # authentication. Disabling it leaves every connection unauthenticated
            # and trivially MITM-able -- make that loud rather than a silent toggle.
            logger.warning(
                "TOFU is DISABLED: Gemini connections are unauthenticated "
                "(CERT_NONE TLS with no certificate pinning) and vulnerable to "
                "active MITM. Re-enable TOFU unless you fully trust the network."
            )

        # Initialize client certificate manager
        self.client_cert_manager: ClientCertificateManager | None = None
        if self.client_certs_enabled:
            self.client_cert_manager = ClientCertificateManager(
                client_certs_storage_path
            )

        # Cache of TLS clients bound to a client certificate, keyed by
        # (cert_path, key_path). Each holds a lazily-built SSL context, so the
        # system CA bundle load + cert/key PEM reads happen once per cert pair
        # instead of on every client-cert request (blocking work on the loop).
        self._client_cert_tls_clients: dict[tuple[str, str], GeminiTLSClient] = {}

        # LRU cache (get/put behaviour lives in TTLCacheMixin). The element type
        # is inherited from the mixin annotation; only the entry class differs.
        self._cache = OrderedDict()
        self._cache_entry_cls = GeminiCacheEntry

        # Robot exclusion (opt-in), following the Gemini companion spec rather
        # than RFC 9309. Unlike Gopher this fails *closed* on a temporary
        # failure (RFC 9309 s2.3.1.4), which Gemini can express because it has
        # status codes -- see :meth:`_fetch_robots` for the 4x/5x mapping.
        self.respect_robots_txt = respect_robots_txt
        self._robots_gate = (
            RobotsGate(
                # Resolved at call time rather than bound here, so the
                # gate follows the method (and stays patchable in tests).
                fetcher=lambda host, port: self._fetch_robots(host, port),
                tokens=GEMINI_TOKENS,
                extra_tokens=(AI_AGENT_TOKENS if robots_honor_ai_tokens else ()),
                ttl_seconds=robots_cache_ttl_seconds,
                fail_closed=True,
            )
            if respect_robots_txt
            else None
        )

    def _tls_client_for_cert(self, cert_path: str, key_path: str) -> GeminiTLSClient:
        """Return a TLS client bound to a client certificate, cached per pair.

        Building the client (and its SSL context) reloads the system CA bundle
        and reads the cert/key PEMs from disk; doing that on every client-cert
        request was blocking work on the event loop. Cache by (cert, key) path so
        it is paid once. Concurrent first-use may briefly build two clients (last
        write wins) -- both are valid, so no lock is needed.
        """
        cache_key = (cert_path, key_path)
        client = self._client_cert_tls_clients.get(cache_key)
        if client is None:
            base = self.tls_client.config
            cfg = TLSConfig(
                min_version=base.min_version,
                verify_mode=base.verify_mode,
                client_cert_path=cert_path,
                client_key_path=key_path,
                timeout_seconds=base.timeout_seconds,
            )
            client = GeminiTLSClient(cfg)
            self._client_cert_tls_clients[cache_key] = client
        return client

    def _validate_security(self, parsed_url: GeminiURL) -> None:
        """Validate security constraints for a Gemini request.

        Args:
            parsed_url: Parsed Gemini URL

        Raises:
            ValueError: If security constraints are violated
        """
        # Check allowed hosts (normalized at construction to close
        # trailing-dot/case bypasses).
        if (
            self.allowed_hosts is not None
            and normalize_host(parsed_url.host) not in self.allowed_hosts
        ):
            raise ValueError(f"Host not allowed: {parsed_url.host}")

        # Validate port range
        if not 1 <= parsed_url.port <= 65535:
            raise ValueError(f"Invalid port number: {parsed_url.port}")

    async def fetch(self, url: str) -> GeminiFetchResponse:
        """Fetch content from a Gemini URL.

        Args:
            url: Gemini URL to fetch

        Returns:
            Structured response based on status code

        """
        # One budget for the whole call. Without it the robots.txt probe below
        # runs the same multi-phase exchange as the fetch it guards, so a tarpit
        # host could spend the configured timeout twice over in one tool call.
        budget_token = _FETCH_BUDGET.set(_FetchBudget(self.timeout_seconds))
        try:
            # Parse the URL
            parsed_url = parse_gemini_url(url)

            # Validate security constraints
            self._validate_security(parsed_url)

            # Robot exclusion, before the cache lookup below: a Disallow must
            # also withhold content cached from an earlier, permitted run.
            if self._robots_gate is not None:
                decision = await self._robots_gate.allows(
                    parsed_url.host, parsed_url.port, [parsed_url.path]
                )
                if not decision.allowed:
                    return self._robots_denied_result(parsed_url, decision.reason)

            # Canonical cache key (case-insensitive host) so requests differing
            # only in host case share one entry instead of duplicating.
            cache_key = normalize_cache_key(url)

            # Check cache first
            if self.cache_enabled:
                cached_response = self._get_cached_response(cache_key)
                if cached_response:
                    # Log without the query string: a status-10/11 answer (which
                    # the caller percent-encodes into the query) may be a secret.
                    logger.debug(
                        "Cache hit",
                        url=f"gemini://{parsed_url.host}:{parsed_url.port}{parsed_url.path}",
                        cached=True,
                        response_type=getattr(cached_response, "kind", "unknown"),
                        response_size=getattr(cached_response, "size", 0),
                    )
                    return cached_response

            # Create request info for provenance. The query is deliberately
            # omitted (and `url` rendered without it): a status-10/11 input
            # answer is carried in the query and may be a secret (status 11).
            # This result is returned to the LLM/transcript via model_dump(),
            # so record only that a query was present, matching the log policy.
            request_info = {
                "url": _safe_display_url(parsed_url),
                "host": parsed_url.host,
                "port": parsed_url.port,
                "path": parsed_url.path,
                "has_query": bool(parsed_url.query),
                "timestamp": time.time(),
            }

            # Fetch the content (optionally bounded by the concurrency cap)
            response = await self._bounded_fetch(parsed_url)

            # Honour a server SLOW_DOWN (status 44): back off this host for the
            # advertised number of seconds (meta) regardless of the configured
            # rate limit, so we don't keep hammering a server asking us to wait.
            self._maybe_honor_slow_down(parsed_url.host, response)

            # Add request info to response
            if hasattr(response, "request_info"):
                response.request_info.update(request_info)

            # Cache the response. Skip transient/non-content results: error
            # and redirect targets can change moment to moment, and
            # input/certificate prompts are per-interaction, so caching them
            # would serve a stale failure or redirect for the full TTL. Also
            # skip any request that carried a query: the answer (possibly a
            # secret status-11 input) would otherwise be retained in the cache
            # key for the full TTL.
            if (
                self.cache_enabled
                and not parsed_url.query
                and getattr(response, "kind", None)
                not in (
                    "error",
                    "redirect",
                    "input",
                    "certificate",
                )
            ):
                self._cache_response(cache_key, response)

            # Host/port/path are request metadata; keep them at DEBUG so default
            # INFO logs don't record every browsed resource. The query is NOT
            # logged: a status-10/11 input answer is carried there and may be a
            # secret (status 11). Record only whether a query was present.
            logger.debug(
                "Gemini fetch successful",
                host=parsed_url.host,
                port=parsed_url.port,
                path=parsed_url.path,
                has_query=bool(parsed_url.query),
                response_type=getattr(response, "kind", "unknown"),
                response_size=getattr(response, "size", 0),
                cached=False,
            )

            return response

        except SSRFError as e:
            # Policy messages name a host/category only (no internal detail).
            return self._error_result(url, "BLOCKED", str(e), e)
        except TOFUExpiredError as e:
            # Distinct from a fingerprint change: the cert MATCHES the pin but is
            # outside its validity window. Report it accurately (must precede the
            # TOFUValidationError handler since it is a subclass). The message
            # names host:port and a category only -- safe to surface.
            return self._error_result(url, "CERTIFICATE_EXPIRED", str(e), e)
        except TOFUUnavailableError as e:
            # No certificate to compare against (not a mismatch). Also a subclass,
            # so it must precede the TOFUValidationError handler.
            return self._error_result(url, "CERTIFICATE_UNVERIFIED", str(e), e)
        except TOFUValidationError as e:
            return self._error_result(
                url,
                "CERTIFICATE_CHANGED",
                "Server certificate failed TOFU verification (it does not match "
                "the previously trusted certificate). Self-signed Gemini "
                "certificates are routinely reissued, so if this rotation is "
                "expected, remove the host's pinned entry from the TOFU trust "
                "store and retry; the server log for this request names the "
                "store path and the entry.",
                e,
            )
        except TOFUStorageError as e:
            # The certificate itself was never in question -- the pin could not
            # be recorded. The store path stays in the log, not in the reply.
            return self._error_result(
                url,
                "CERTIFICATE_STORE_UNAVAILABLE",
                "The TOFU trust store is locked by another process, so the "
                "server certificate could not be recorded",
                e,
            )
        except TimeoutError as e:
            # DNS resolution, connect/handshake, send or read exceeded the one
            # request deadline. The transport now reports a connect timeout AS a
            # timeout, so a firewalled host no longer masquerades as a TLS fault.
            return self._error_result(url, "FETCH_ERROR", "The request timed out", e)
        except TLSConnectionError as e:
            return self._error_result(url, "TLS_ERROR", "TLS connection failed", e)
        except GeminiProtocolError as e:
            # The SERVER sent a malformed response (missing CRLF, bad status,
            # over-long meta, ...). Report it as a server-side fault rather than
            # INVALID_REQUEST, which would wrongly tell the model to fix its URL.
            # Must precede the ValueError handler (it is a subclass). The message
            # describes the response shape only -- no body bytes or secrets.
            return self._error_result(
                url,
                "PROTOCOL_ERROR",
                f"The server sent a malformed Gemini response: {e}",
                e,
            )
        except ValueError as e:
            # URL/host validation errors are safe to surface verbatim.
            return self._error_result(url, "INVALID_REQUEST", str(e), e)
        except Exception as e:
            return self._error_result(
                url, "FETCH_ERROR", "Failed to fetch the requested resource", e
            )
        finally:
            _FETCH_BUDGET.reset(budget_token)

    def _error_result(
        self, url: str, code: str, message: str, exc: Exception
    ) -> GeminiErrorResult:
        """Build a sanitized error result, logging full detail server-side."""
        # Drop any query string: for a status-10/11 follow-up the answer (a
        # possible secret) is encoded there and must not be logged or returned.
        safe_url = url.split("?", 1)[0]
        logger.error(
            "Gemini fetch failed",
            url=safe_url,
            code=code,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return GeminiErrorResult(
            error={"code": code, "message": message},
            requestInfo={"url": safe_url, "timestamp": time.time()},
        )

    def _maybe_honor_slow_down(self, host: str, response: GeminiFetchResponse) -> None:
        """If ``response`` is a status-44 SLOW_DOWN, back off this host.

        The Gemini spec says the meta of a 44 is the number of seconds to wait;
        fall back to a conservative default if it isn't a plain number.
        """
        if not isinstance(response, GeminiErrorResult):
            return
        if response.error.get("status") != 44:
            return
        message = response.error.get("message", "")
        try:
            seconds = float(str(message).strip())
        except (TypeError, ValueError):
            seconds = 60.0
        self._rate_limiter.penalize(host, seconds)

    def _robots_denied_result(
        self, parsed_url: GeminiURL, reason: str
    ) -> GeminiErrorResult:
        """Build the result returned when the robots gate blocks a resource."""
        logger.info(
            "Blocked by robots.txt",
            host=parsed_url.host,
            path=parsed_url.path,
            reason=reason,
        )
        if reason == "unavailable":
            message = (
                f"Could not retrieve robots.txt from {parsed_url.host}, so access "
                f"is denied (RFC 9309 section 2.3.1.4 treats a temporary failure "
                f"as a complete disallow). Set GEMINI_RESPECT_ROBOTS_TXT=false to "
                f"disable robots checking."
            )
        else:
            message = (
                f"{parsed_url.host} disallows this resource in its robots.txt. "
                f"Set GEMINI_RESPECT_ROBOTS_TXT=false to disable robots checking."
            )
        return GeminiErrorResult(
            error={"code": "BLOCKED_BY_ROBOTS", "message": message},
            requestInfo={
                "url": _safe_display_url(parsed_url),
                "host": parsed_url.host,
                "port": parsed_url.port,
                "path": parsed_url.path,
                "timestamp": time.time(),
            },
        )

    async def _fetch_robots(self, host: str, port: int) -> str | None:
        """Fetch ``/robots.txt`` for the robots gate.

        Calls :meth:`_fetch_content` directly rather than :meth:`fetch`: the
        former would recurse into the gate, and :meth:`_bounded_fetch` holds
        ``_fetch_semaphore``, so a lookup issued from inside it would deadlock
        whenever ``max_concurrent_requests`` is 1.

        Status mapping is deliberately *not* the HTTP one. Gemini inverts the
        numbering: 5x is the permanent class, and ``51 NOT FOUND`` is the normal
        answer from a capsule that simply has no robots.txt, so 5x means "no
        policy, allow everything" (RFC 9309 s2.3.1.3). 4x is the temporary class
        and maps to s2.3.1.4's complete disallow. A capsule that demands a client
        certificate (6x) cannot serve us a policy at all, so it is allowed
        through -- the resource itself is gated by the certificate anyway.

        An :class:`SSRFError` deliberately propagates instead of becoming a
        :class:`RobotsUnavailable`: it is a client-side policy refusal, not the
        "server or network error" RFC 9309 s2.3.1.4 contemplates, and reporting
        it as an unreachable robots.txt would tell the caller to disable robots
        checking for a target that the SSRF guard blocks either way.
        """
        robots_url = GeminiURL(host=host, port=port, path="/robots.txt", query=None)
        # This bypasses _bounded_fetch (see above), which is where the per-host
        # spacing is now applied, so throttle here instead.
        await self._rate_limiter.acquire(host)
        try:
            result = await self._fetch_content(
                robots_url,
                # Never read more than the operator allows for a normal body.
                max_bytes=min(ROBOTS_MAX_BYTES, self.max_response_size),
                apply_content_policy=False,
                truncate_oversize=True,
            )
        except (
            GeminiProtocolError,
            TLSConnectionError,
            OSError,
            TimeoutError,
        ) as e:
            raise RobotsUnavailable(f"could not reach {host}:{port}") from e

        # A 44 SLOW_DOWN here is still the server asking us to back off, and the
        # backoff must be recorded even though this response is discarded.
        self._maybe_honor_slow_down(host, result)

        kind = getattr(result, "kind", None)
        if kind in ("success", "gemtext"):
            # text/gemini is the Gemini default MIME -- it is what an absent,
            # empty or unparseable meta falls back to -- so a policy served that
            # way arrives as GeminiGemtextResult, which carries its text in
            # `raw_content` rather than `content`. Reading only `content` would
            # silently discard the policy and cache allow-all for the full TTL.
            body = getattr(result, "content", None)
            if body is None:
                body = getattr(result, "raw_content", None)
            return body if isinstance(body, str) else None
        if kind == "error":
            status = getattr(result, "error", {}).get("status")
            if isinstance(status, int) and 40 <= status <= 49:
                raise RobotsUnavailable(f"status {status} fetching robots.txt")
            # 5x (including 51 NOT FOUND) and anything unclassifiable: no policy.
            return None
        # Redirect, input prompt, certificate request or a binary body: none of
        # these is a policy we can apply, so nothing is disallowed.
        return None

    async def _bounded_fetch(self, parsed_url: GeminiURL) -> GeminiFetchResponse:
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

    async def _fetch_content(
        self,
        parsed_url: GeminiURL,
        *,
        max_bytes: int | None = None,
        apply_content_policy: bool = True,
        truncate_oversize: bool = False,
    ) -> GeminiFetchResponse:
        """Fetch content from parsed Gemini URL using TLS.

        Args:
            parsed_url: Parsed Gemini URL
            max_bytes: Optional response-size cap for this request only,
                used by the robots.txt lookup so a capsule cannot make the
                gate download a full-sized body.
            apply_content_policy: When False, skip the LLM-facing render cap
                and the MIME deny list. Both exist to shape what reaches the
                model; applying them to a robots.txt would silently truncate
                a policy mid-file or discard it entirely.
            truncate_oversize: Parse the first ``max_bytes`` bytes instead of
                failing when the server has more to send. Only the robots.txt
                lookup sets this: RFC 9309 section 2.5 prescribes parsing a
                truncated prefix, and rejecting instead made an over-cap
                robots.txt deny an entire capsule forever (the gate fails closed
                and never caches an unavailable policy, so every request
                re-downloaded and re-denied).

        Returns:
            Appropriate response based on status code

        """
        loop = asyncio.get_running_loop()
        budget = _FETCH_BUDGET.get()
        # ONE deadline for the whole exchange -- DNS, connect + handshake, TOFU
        # persistence, send and read. Each phase used to get its own full-length
        # timeout, so a tarpit answering every phase just under the limit could
        # hold a call for several multiples of timeout_seconds.
        timeout = self.timeout_seconds if budget is None else budget.remaining
        started = loop.time()
        limit = max_bytes or self.max_response_size
        connection: TLSConnection | None = None
        connection_info: dict[str, Any] = {}
        tls_client = self.tls_client
        try:
            if timeout <= 0:
                raise TimeoutError(
                    "Request deadline exhausted before the connection was opened"
                )
            async with asyncio.timeout(timeout):
                # SSRF guard: reject internal/loopback/link-local targets before
                # opening the TLS connection, and pin the connection to a
                # validated IP so the TLS layer can't re-resolve to a rebinding
                # answer. DNS is inside the deadline because getaddrinfo is
                # otherwise unbounded (a tarpit nameserver could stall a worker
                # -- and tie up an event-loop executor thread -- indefinitely).
                connect_addresses = await validate_target(
                    parsed_url.host,
                    parsed_url.port,
                    allow_local=self.allow_local_hosts,
                    allowed_ports=self.allowed_ports,
                )

                # Check for client certificate
                client_cert_path = None
                client_key_path = None
                if self.client_cert_manager:
                    cert_paths = self.client_cert_manager.get_certificate_for_scope(
                        parsed_url.host, parsed_url.port, parsed_url.path
                    )
                    if cert_paths:
                        client_cert_path, client_key_path = cert_paths
                        logger.debug(
                            "Using client certificate",
                            host=parsed_url.host,
                            port=parsed_url.port,
                            path=parsed_url.path,
                            cert_path=client_cert_path,
                        )

                # Pick the TLS client: a client-cert-bound one (whose SSL context
                # is built and cached once per cert pair) when a cert applies to
                # this scope, otherwise the shared default client. Every
                # subsequent call uses it, so the certificate really is scoped.
                if client_cert_path and client_key_path:
                    tls_client = self._tls_client_for_cert(
                        client_cert_path, client_key_path
                    )

                # Try every vetted address, IPv4 first (the historical behaviour
                # was AF_INET-only). Attempting only one left a dual-homed
                # capsule whose first A record is down unreachable over Gemini
                # while the Gopher transport, which iterates, still reached it.
                last_error: TLSConnectionError | None = None
                for connect_ip in _ipv4_first(connect_addresses):
                    try:
                        connection, connection_info = await tls_client.connect(
                            parsed_url.host,
                            parsed_url.port,
                            timeout=self.timeout_seconds,
                            connect_ip=connect_ip,
                        )
                        break
                    except TLSConnectionError as e:
                        last_error = e
                if connection is None:
                    raise last_error or TLSConnectionError(
                        f"Could not connect to {parsed_url.host}:{parsed_url.port}"
                    )

                # Validate certificate using TOFU if enabled (fail CLOSED).
                tofu_warning = None
                if self.tofu_manager:
                    cert_fingerprint = connection_info.get("cert_fingerprint")
                    if not cert_fingerprint:
                        # The TLS layer runs with CERT_NONE, so TOFU is the only
                        # thing authenticating the peer. Without a fingerprint we
                        # cannot apply the pin -- refuse rather than send the
                        # request to an unverified server. This is a distinct
                        # failure from a fingerprint mismatch (nothing to compare).
                        raise TOFUUnavailableError(
                            "No certificate fingerprint available; cannot verify "
                            "the server identity via TOFU"
                        )
                    # Off the event loop: a first pin (and every last_seen flush)
                    # runs a cross-process flock, a full store re-read and an
                    # fsync'd rewrite, which would otherwise stall every other
                    # in-flight request in the process.
                    #
                    # A fingerprint mismatch raises TOFUValidationError, which
                    # propagates to fetch() and becomes a CERTIFICATE_CHANGED error.
                    is_valid, warning = await asyncio.to_thread(
                        self.tofu_manager.validate_certificate,
                        parsed_url.host,
                        parsed_url.port,
                        cert_fingerprint,
                        connection_info.get("peer_cert_info"),
                    )
                    if not is_valid:
                        # Defense-in-depth: a non-raising False result must still
                        # reject (fail CLOSED), not merely warn -- so this gate is
                        # robust regardless of how the validator signals failure.
                        raise TOFUValidationError(
                            warning
                            or f"TOFU validation failed for "
                            f"{parsed_url.host}:{parsed_url.port}"
                        )
                    if warning:
                        tofu_warning = warning
                        logger.warning(
                            "TOFU validation warning",
                            host=parsed_url.host,
                            port=parsed_url.port,
                            warning=warning,
                        )

                # Format Gemini request: URL + CRLF (bracket an IPv6 literal host
                # per RFC 3986 so its colons aren't read as a port separator).
                request_url = f"gemini://{bracket_host(parsed_url.host)}"
                if parsed_url.port != 1965:
                    request_url += f":{parsed_url.port}"
                request_url += parsed_url.path
                if parsed_url.query:
                    request_url += f"?{parsed_url.query}"

                request_data = f"{request_url}\r\n".encode()

                await tls_client.send_data(connection, request_data)

                raw_response = await tls_client.receive_data(
                    connection, limit, truncate_at_max=truncate_oversize
                )

                if truncate_oversize and len(raw_response) >= limit:
                    # RFC 9309 section 2.5: parse the prefix rather than reject
                    # the file, but drop the trailing line -- it was cut mid-way
                    # and half a Disallow must not be applied as a whole one.
                    logger.warning(
                        "robots.txt truncated at the size cap",
                        host=parsed_url.host,
                        port=parsed_url.port,
                        max_bytes=limit,
                    )
                    raw_response = raw_response[: raw_response.rfind(b"\n") + 1]

                # Parse response
                parsed_response = parse_gemini_response(raw_response)

                # Process response based on status code
                result = process_gemini_response(
                    parsed_response,
                    request_url,
                    time.time(),
                    max_rendered_chars=(
                        self.max_rendered_chars if apply_content_policy else 0
                    ),
                    denied_mime_types=(
                        self.denied_mime_types if apply_content_policy else None
                    ),
                )

                # Add connection info to request info
                if hasattr(result, "request_info"):
                    result.request_info.update(
                        {
                            "tls_version": connection_info.get("tls_version"),
                            "cipher": connection_info.get("cipher"),
                            "cert_fingerprint": connection_info.get("cert_fingerprint"),
                            "tofu_warning": tofu_warning,
                        }
                    )

                return result

        except Exception as e:
            # Preserve the exception type (TLSConnectionError, TOFUValidationError,
            # SSRFError, TimeoutError, ...) so fetch() can map it to a distinct
            # error code. Log without the query string (a status-11 secret).
            logger.error(
                "Gemini fetch failed",
                url=_safe_display_url(parsed_url),
                error=str(e),
            )
            raise
        finally:
            # Charge only wire time to the budget: waiting for a rate-limit slot
            # or a concurrency slot happens outside this method and must not eat
            # the deadline the operator configured for the exchange itself.
            if budget is not None:
                budget.remaining -= loop.time() - started
            # Always close the connection
            if connection is not None:
                await tls_client.close(connection)

    # _get_cached_response / _cache_response are provided by TTLCacheMixin.

    def update_tofu_certificate(
        self, host: str, port: int, cert_fingerprint: str, force: bool = False
    ) -> None:
        """Update TOFU certificate for a host.

        Args:
            host: Hostname
            port: Port number
            cert_fingerprint: Certificate fingerprint
            force: Force update even if certificate exists

        Raises:
            ValueError: If TOFU is not enabled
        """
        if not self.tofu_manager:
            raise ValueError("TOFU is not enabled")

        self.tofu_manager.update_certificate(host, port, cert_fingerprint, force=force)

    def remove_tofu_certificate(self, host: str, port: int) -> bool:
        """Remove TOFU certificate for a host.

        Args:
            host: Hostname
            port: Port number

        Returns:
            True if certificate was removed, False if not found

        Raises:
            ValueError: If TOFU is not enabled
        """
        if not self.tofu_manager:
            raise ValueError("TOFU is not enabled")

        return self.tofu_manager.remove_certificate(host, port)

    def list_tofu_certificates(self) -> list[TOFUEntry]:
        """List all TOFU certificates.

        Returns:
            List of TOFU entries

        Raises:
            ValueError: If TOFU is not enabled
        """
        if not self.tofu_manager:
            raise ValueError("TOFU is not enabled")

        return self.tofu_manager.list_certificates()

    def generate_client_certificate(
        self,
        host: str,
        port: int = 1965,
        path: str = "/",
        common_name: str | None = None,
        validity_days: int = 365,
    ) -> tuple[str, str]:
        """Generate a new client certificate for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope
            common_name: Certificate common name
            validity_days: Certificate validity in days

        Returns:
            Tuple of (cert_path, key_path)

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.generate_certificate(
            host, port, path, common_name, validity_days
        )

    def get_client_certificate_for_scope(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> tuple[str, str] | None:
        """Get client certificate paths for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            Tuple of (cert_path, key_path) or None if not found

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.get_certificate_for_scope(host, port, path)

    def list_client_certificates(self) -> list[GeminiCertificateInfo]:
        """List all client certificates.

        Returns:
            List of client certificate information

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.list_certificates()

    def remove_client_certificate(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> bool:
        """Remove client certificate for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            True if certificate was removed, False if not found

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.remove_certificate(host, port, path)

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        self._cache.clear()
        logger.info("Gemini client closed")
