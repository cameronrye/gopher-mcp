"""Gemini protocol client implementation."""

import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog

from .client_base import FetchClientBase
from .client_certs import ClientCertificateManager
from .gemini_parse import (
    GeminiProtocolError,
    format_gemini_url,
    parse_gemini_response,
    parse_gemini_url,
    process_gemini_response,
)
from .gemini_tls import (
    GeminiConnectionError,
    GeminiResponseTooLargeError,
    GeminiTLSClient,
    TLSConfig,
    TLSConnection,
    TLSConnectionError,
)
from .models import (
    GeminiCacheEntry,
    GeminiCertificateInfo,
    GeminiErrorResult,
    GeminiFetchResponse,
    GeminiURL,
    TOFUEntry,
    iso_utc,
    mark_from_cache,
)
from .ratelimit import RateLimited, sanitize_penalty_seconds
from .robots import (
    GEMINI_TOKENS,
    ROBOTS_MAX_BYTES,
    RobotsUnavailable,
)
from .ssrf import HostResolutionError, SSRFError, validate_target
from .tofu import (
    TOFUExpiredError,
    TOFUManager,
    TOFUNotYetValidError,
    TOFUStorageError,
    TOFUUnavailableError,
    TOFUValidationError,
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
DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS = 60.0  # dead host: retry, not per request
# Applied when a status-44 SLOW_DOWN does not name a usable number of seconds.
# The capsule still asked us to back off, so a conservative period beats none.
DEFAULT_SLOW_DOWN_SECONDS = 60.0


# The 4x statuses, spelled the way the Gemini specification names them. A robots
# probe that ends in one is reported with the status *named* rather than as a
# bare number: "41 SERVER UNAVAILABLE" tells a reader the capsule is down, where
# "status 41" reads as an internal code and invites the conclusion that the
# refusal was a policy decision.
_TEMPORARY_STATUS_NAMES: dict[int, str] = {
    40: "TEMPORARY FAILURE",
    41: "SERVER UNAVAILABLE",
    42: "CGI ERROR",
    43: "PROXY ERROR",
    44: "SLOW_DOWN",
}


def _status_phrase(status: int) -> str:
    """Render a status for a user-facing message: ``41 SERVER UNAVAILABLE``."""
    name = _TEMPORARY_STATUS_NAMES.get(status)
    return f"{status} {name}" if name else str(status)


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


@dataclass
class _ProbeCredit:
    """What the robots probe already paid for, on behalf of the fetch it guards.

    The probe and the fetch it precedes are one user-visible request to one
    capsule, but each used to take its own rate-limit token and run its own DNS
    lookup -- so with the shipped defaults (60 rpm, robots on) every first fetch
    to a host slept a full second before anything could be sent, and resolved
    the same name twice. Both halves are handed straight to the fetch that
    follows, which is the only thing that ever runs after a probe. Mirrors the
    Gopher client, which carries the identical structure for the same reason.
    """

    host: str
    port: int
    #: Vetted connect addresses, filled in by the probe's own ``_fetch_content``
    #: (which is where Gemini resolves) and read by the fetch that follows.
    addresses: list[str] | None
    rate_slot: bool


# Set by the robots probe, consumed by the fetch it guards. A ContextVar for the
# same reason as the budget above: the probe is invoked through RobotsGate, which
# owns its fetcher signature, and awaits it inside the calling task.
_PROBE_CREDIT: ContextVar[_ProbeCredit | None] = ContextVar(
    "gemini_probe_credit", default=None
)


# Where the render window starts for the fetch running in this task: menu item
# index / character position, 0 for the beginning. A ContextVar for the same
# reason as the budget above -- it has to reach the render step across
# ``_bounded_fetch``/``_fetch_content``, the seam subclasses and test doubles
# implement, and each task's own copy keeps concurrent fetches from reading each
# other's window (a value parked on the shared client instance would not).
_RENDER_OFFSET: ContextVar[int] = ContextVar("gemini_render_offset", default=0)


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
    return format_gemini_url(parsed_url.host, parsed_url.port, parsed_url.path)


class GeminiClient(FetchClientBase[GeminiFetchResponse, GeminiURL]):
    """Async Gemini protocol client with TLS, caching and safety features."""

    _log_label = "Gemini"
    _cache_entry_cls = GeminiCacheEntry
    # Gemini results spell the content length ``size`` (Gopher says ``bytes``).
    _response_size_field = "size"
    _robots_tokens = GEMINI_TOKENS
    # Unlike Gopher this fails *closed* on a temporary failure (RFC 9309
    # s2.3.1.4), which Gemini can express because it has status codes -- see
    # :meth:`_fetch_robots` for the 4x/5x mapping.
    _robots_fail_closed = True

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
        respect_robots_txt: bool = True,
        robots_cache_ttl_seconds: int = DEFAULT_ROBOTS_CACHE_TTL_SECONDS,
        robots_honor_ai_tokens: bool = True,
        robots_failure_backoff_seconds: float = DEFAULT_ROBOTS_FAILURE_BACKOFF_SECONDS,
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
        # A status-44 penalty is capped at MAX_PENALTY_SECONDS (300), which is
        # far longer than one tool call may spend asleep: the MCP client's own
        # call timeout fires first, and in a batch the sleeping call also ties up
        # a concurrency slot. Past the configured request deadline the limiter
        # answers with RateLimited instead, which fetch() turns into a structured
        # "backing off, retry in N seconds" the model can act on.
        self._rate_limiter.max_wait_seconds = timeout_seconds
        self.denied_mime_types = frozenset(denied_mime_types or ())
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
        if not self._host_is_allowed(parsed_url.host):
            raise ValueError(f"Host not allowed: {parsed_url.host}")

        # Validate port range
        if not 1 <= parsed_url.port <= 65535:
            raise ValueError(f"Invalid port number: {parsed_url.port}")

    async def fetch(
        self, url: str, *, refresh: bool = False, offset: int = 0
    ) -> GeminiFetchResponse:
        """Fetch content from a Gemini URL.

        Args:
            url: Gemini URL to fetch
            refresh: Skip the cache lookup and go to the server. The fresh
                response still replaces the cached one, so this bypasses the
                cache for this read rather than disabling it.
            offset: Character position the returned body window starts at. Pass
                back the ``next_offset`` of a truncated result to read the part
                that was cut; 0 is the beginning. Offsets past the end return an
                empty window, not an error.

        Returns:
            Structured response based on status code

        """
        # One budget for the whole call. Without it the robots.txt probe below
        # runs the same multi-phase exchange as the fetch it guards, so a tarpit
        # host could spend the configured timeout twice over in one tool call.
        budget_token = _FETCH_BUDGET.set(_FetchBudget(self.timeout_seconds))
        # Cleared for the same reason the budget is: a ContextVar set inside one
        # fetch outlives it in the caller's context, so a second fetch on the
        # same task would otherwise inherit the first one's rate-limit slot and
        # its already-resolved addresses.
        credit_token = _PROBE_CREDIT.set(None)
        # Set here rather than passed down through ``_bounded_fetch``: that
        # method and ``_fetch_content`` are the seam a subclass (and the robots
        # gate's own fetcher) implement, and widening it for a value only the
        # render path reads would push the parameter through code with no use
        # for it. Same lifecycle as the budget above, and each task's copy keeps
        # concurrent fetches from reading each other's window.
        offset_token = _RENDER_OFFSET.set(offset)
        try:
            # Rejected rather than clamped: a negative offset is a caller
            # mistake, and silently reading from 0 would answer a question that
            # was not asked.
            if offset < 0:
                raise ValueError("offset must not be negative")

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
                    return self._robots_denied_result(
                        parsed_url, decision.reason, decision.detail
                    )

            # Key on the request that will actually go on the wire, not on the
            # string the caller typed. Five spellings of the same resource
            # ("gemini://h", "gemini://h/", "gemini://H/a/../", an explicit
            # ":1965", a "%2e" segment) all rebuild to one request line, and
            # keying on the raw URL gave each its own entry -- a re-fetch from a
            # small capsule plus a wasted LRU slot for identical content.
            # The query stays in the key so the deliberate "never store a
            # query-bearing response" rule below still misses.
            cache_key = format_gemini_url(
                parsed_url.host, parsed_url.port, parsed_url.path, parsed_url.query
            )
            if offset:
                # What the cache stores is the RENDERED WINDOW, not the body, so
                # two windows of one page are two entries -- serving window 0 to
                # a request for window 50000 would silently answer the wrong
                # question. Caching the whole body instead would put full-size
                # bodies in a cache whose entry cap exists to bound its memory,
                # so the offset goes in the key and a continuation pays for its
                # own fetch. NUL cannot appear in a URL, so this can never
                # collide with the key another URL formats to.
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
                    # Log without the query string: a status-10/11 answer (which
                    # the caller percent-encodes into the query) may be a secret.
                    logger.debug(
                        "Cache hit",
                        url=f"gemini://{parsed_url.host}:{parsed_url.port}{parsed_url.path}",
                        cached=True,
                        # Direct attribute access, not getattr with a default:
                        # every member of the response union declares ``kind``,
                        # so a rename or a typo must fail mypy rather than
                        # silently logging "unknown" forever.
                        response_type=cached_response.kind,
                        response_size=self._response_size(cached_response),
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
                # ``is not None``: an empty answer to a status-10/11 prompt is a
                # present query, and reporting it as absent contradicts the
                # request that was actually sent.
                "has_query": parsed_url.query is not None,
                "timestamp": iso_utc(time.time()),
            }

            # Fetch the content (optionally bounded by the concurrency cap)
            response = await self._bounded_fetch(parsed_url)

            # Honour a server SLOW_DOWN (status 44): back off this host for the
            # advertised number of seconds (meta) regardless of the configured
            # rate limit, so we don't keep hammering a server asking us to wait.
            self._maybe_honor_slow_down(parsed_url.host, response)

            # Add request info to response. Every union member declares
            # ``request_info``, so access it directly rather than behind a
            # hasattr guard mypy can never check.
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
                and parsed_url.query is None
                and response.kind
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
                has_query=parsed_url.query is not None,
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
            # Policy messages name a host/category only (no internal detail).
            return self._error_result(url, "BLOCKED", str(e), e)
        except TOFUNotYetValidError as e:
            # A subclass of TOFUExpiredError, so it MUST precede that handler:
            # otherwise a certificate presented before its notBefore is reported
            # as CERTIFICATE_EXPIRED, which inverts the diagnosis and sends the
            # reader looking for a renewal that is not the problem.
            return self._error_result(url, "CERTIFICATE_NOT_YET_VALID", str(e), e)
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
                "certificates are routinely reissued, so this may be a "
                "legitimate rotation -- or an intercepted connection; the two "
                "are indistinguishable from here. Ask the user before "
                "proceeding: gemini_trust_list reports what is pinned for this "
                "host, and gemini_trust_update removes or replaces that pin "
                "once they confirm the change is expected.",
                e,
            )
        except TOFUStorageError as e:
            # The certificate itself was never in question -- the pin could not
            # be recorded. The store path stays in the log, not in the reply.
            return self._error_result(
                url,
                "CERTIFICATE_STORE_UNAVAILABLE",
                "The TOFU trust store could not be written -- it is locked by "
                "another process, or the location is not writable -- so the "
                "server certificate could not be recorded. This is a local "
                "problem, not a problem with the capsule: check "
                "GEMINI_TOFU_STORAGE_PATH (and the HOME it defaults under) "
                "rather than retrying.",
                e,
            )
        except RateLimited as e:
            # The host is backing off (almost always after its own status-44
            # SLOW_DOWN) for longer than one call may spend asleep. Answer with
            # the wait instead of sitting in it: the MCP client's call timeout
            # would otherwise fire first, and in a batch the sleeping call also
            # holds one of the concurrency slots.
            return self._slow_down_result(url, e)
        except TimeoutError as e:
            # DNS resolution, connect/handshake, send or read exceeded the one
            # request deadline. The transport now reports a connect timeout AS a
            # timeout, so a firewalled host no longer masquerades as a TLS fault.
            return self._error_result(url, "FETCH_ERROR", "The request timed out", e)
        except GeminiResponseTooLargeError as e:
            # Must precede TLSConnectionError (its base). A size cap is the
            # operator's own policy, not a transport fault -- the bytes arrived
            # fine, there were simply too many of them. The message names the
            # cap, which is the actionable part.
            return self._error_result(url, "FETCH_ERROR", str(e), e)
        except GeminiConnectionError as e:
            # Must precede TLSConnectionError (its base). Refused, unreachable
            # or reset: nothing is listening, and pointing the caller at TLS
            # sends them to inspect certificates for a connection that never
            # reached a handshake.
            return self._error_result(url, "FETCH_ERROR", str(e), e)
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
            _PROBE_CREDIT.reset(credit_token)
            _RENDER_OFFSET.reset(offset_token)

    async def _bounded_fetch(self, parsed_url: GeminiURL) -> GeminiFetchResponse:
        """Run the guarded fetch, spending what the robots probe already paid.

        Overrides the base only to skip a *second* per-host rate-limit token:
        the probe and the fetch it guards are one user request to one capsule,
        and charging both made every first fetch to a host sleep a full interval
        -- a second, with the shipped defaults -- before anything could be sent.
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

    def _slow_down_result(self, url: str, exc: RateLimited) -> GeminiErrorResult:
        """Build the structured answer for a host that is still backing off."""
        retry_after = round(exc.retry_after, 1)
        safe_url = self._safe_error_url(url)
        logger.info(
            "Gemini fetch deferred: host is backing off",
            url=safe_url,
            host=exc.host,
            retry_after_seconds=retry_after,
        )
        return GeminiErrorResult(
            error={
                "code": "SLOW_DOWN",
                "message": (
                    f"{exc.host} asked this client to slow down, and the backoff "
                    f"has {retry_after} seconds left to run. Nothing was sent. "
                    f"Fetch something else and come back after that, or tell the "
                    f"user how long the wait is -- retrying immediately only "
                    f"gets this same answer."
                ),
                "retry_after_seconds": retry_after,
            },
            request_info={"url": safe_url, "timestamp": iso_utc(time.time())},
        )

    def _safe_error_url(self, url: str) -> str:
        """Drop the query string before an error URL is logged or returned.

        For a status-10/11 follow-up the answer (a possible secret) is
        percent-encoded there, so it must reach neither the log nor the caller.
        """
        return url.split("?", 1)[0]

    @staticmethod
    def _slow_down_seconds(response: GeminiFetchResponse) -> float | None:
        """Seconds a status-44 SLOW_DOWN actually named, or ``None``.

        The Gemini spec says the meta of a 44 is that number. ``None`` means the
        capsule named no usable period -- the meta was not a number at all, or
        was NaN, negative or zero. Callers decide their own fallback, and the
        distinction matters: the robots gate may only let a period the capsule
        *actually named* override the operator's configured backoff, so an
        invented default must not arrive looking like a server instruction.

        The meta is attacker-controlled, so a usable value is clamped here
        rather than at each use -- the gate takes it as a backoff, and an
        unclamped ``inf`` would have it refuse the capsule for the maximum
        window on the server's say-so. It is read from ``error["meta"]``, which
        is where the capsule's own text lives; ``error["message"]`` is this
        server's explanation and never a number.
        """
        meta = getattr(response, "error", {}).get("meta", "")
        try:
            seconds = float(str(meta).strip())
        except (TypeError, ValueError):
            return None
        seconds = sanitize_penalty_seconds(seconds)
        return seconds if seconds > 0 else None

    def _maybe_honor_slow_down(self, host: str, response: GeminiFetchResponse) -> None:
        """If ``response`` is a status-44 SLOW_DOWN, back off this host.

        A 44 with an unusable meta is still a 44: the capsule asked us to slow
        down, it just did not say for how long, so a conservative default
        applies rather than no penalty at all.
        """
        if not isinstance(response, GeminiErrorResult):
            return
        if response.error.get("status") != 44:
            return
        named = self._slow_down_seconds(response)
        self._rate_limiter.penalize(
            host, named if named is not None else DEFAULT_SLOW_DOWN_SECONDS
        )

    def _robots_denied_result(
        self, parsed_url: GeminiURL, reason: str, detail: str | None = None
    ) -> GeminiErrorResult:
        """Build the result returned when the robots gate blocks a resource.

        The two cases this covers mean opposite things and call for opposite
        responses, so they get separate error codes, wording and remedies. A
        *disallow* is the operator's decision and will not change on a retry;
        that is ``BLOCKED_BY_ROBOTS``. An *unavailable* policy is a transport or
        availability failure that is reported here only because RFC 9309 section
        2.3.1.4 makes it deny; that is ``ROBOTS_UNAVAILABLE``, and the useful
        advice is to retry -- telling the caller to turn robots checking off
        would trade a clear error for the underlying one while leaving a safety
        control switched off.

        The split is a code and not just a message because the retry decision
        turns on it, and because naming an unreachable capsule "blocked by
        robots" claims the operator wrote a rule they did not write. It follows
        the same reasoning as ``CERTIFICATE_STORE_UNAVAILABLE`` beside
        ``CERTIFICATE_UNVERIFIED``: "the check could not happen" is a different
        answer from "the check says no", not a variant of it.
        """
        logger.info(
            "Blocked by robots.txt"
            if reason == "disallowed"
            else "Robots probe failed",
            host=parsed_url.host,
            path=parsed_url.path,
            reason=reason,
            detail=detail,
        )
        if reason == "unavailable":
            cause = f" because {detail}" if detail else ""
            message = (
                f"Could not fetch robots.txt from {parsed_url.host}{cause}, so "
                f"this request was refused: Gemini fails closed when a capsule's "
                f"policy cannot be retrieved (RFC 9309 section 2.3.1.4 treats a "
                f"temporary failure as a complete disallow). This is not a rule "
                f"the capsule wrote against you -- most likely the capsule is "
                f"down or unreachable, in which case the fetch would fail anyway "
                f"with robots checking off. Retry shortly: the policy is "
                f"re-probed once the failure backoff elapses (normally "
                f"GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS, or the capsule's own "
                f"period if it named one in a 44 SLOW_DOWN)."
            )
        else:
            # The single actionable sentence used to be an unconditional "set
            # GEMINI_RESPECT_ROBOTS_TXT=false", which is read by the model, not
            # the operator -- so the natural next step became telling the user to
            # switch off a politeness control the capsule explicitly opted into.
            # docs/ai-assistant-guide.md says the opposite ("do not suggest
            # disabling robots checking unless the user has said they operate the
            # host"), and every comparable remedy in this file is qualified the
            # same way. State the decision and the correct next step first; keep
            # the env-var pointer, under its condition.
            message = (
                f"{parsed_url.host} disallows this resource in its robots.txt. "
                f"This is the capsule operator's decision and will not change on "
                f"a retry: do not retry, and do not try a different spelling of "
                f"the path. Tell the user the resource is excluded and stop. "
                f"GEMINI_RESPECT_ROBOTS_TXT=false overrides the check, but only "
                f"for a host the user has said they operate."
            )
        code = "ROBOTS_UNAVAILABLE" if reason == "unavailable" else "BLOCKED_BY_ROBOTS"
        return GeminiErrorResult(
            error={"code": code, "message": message},
            request_info={
                "url": _safe_display_url(parsed_url),
                "host": parsed_url.host,
                "port": parsed_url.port,
                "path": parsed_url.path,
                "timestamp": iso_utc(time.time()),
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
        # The fetch this probe guards is the same user request to the same
        # capsule, so it inherits this slot -- and the addresses the probe's own
        # _fetch_content is about to vet -- instead of paying for a second of
        # each. Recorded before the probe's own read: even a probe that then
        # fails has already spent the rate-limit token.
        _PROBE_CREDIT.set(
            _ProbeCredit(host=host, port=port, addresses=None, rate_slot=True)
        )
        try:
            result = await self._fetch_content(
                robots_url,
                # Never read more than the operator allows for a normal body.
                max_bytes=min(ROBOTS_MAX_BYTES, self.max_response_size),
                apply_content_policy=False,
                truncate_oversize=True,
            )
        except TimeoutError as e:
            raise RobotsUnavailable("the connection timed out") from e
        except GeminiProtocolError as e:
            # The capsule answered, but not with a Gemini response. Reporting
            # that as a robots policy would blame the operator for a server
            # that is simply broken.
            raise RobotsUnavailable("the reply was not a valid Gemini response") from e
        except GeminiResponseTooLargeError as e:
            raise RobotsUnavailable("the robots.txt response was too large") from e
        except GeminiConnectionError as e:
            raise RobotsUnavailable("the connection was refused or unreachable") from e
        except TLSConnectionError as e:
            raise RobotsUnavailable("the TLS handshake failed") from e
        except OSError as e:
            raise RobotsUnavailable("the connection failed") from e

        # A 44 SLOW_DOWN here is still the server asking us to back off, and the
        # backoff must be recorded even though this response is discarded.
        self._maybe_honor_slow_down(host, result)

        kind = result.kind
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
                # 44 is the one 4x that says when to come back. Honour that
                # instead of the generic backoff -- the rate limiter has already
                # been penalised for the same period (just above), and adding
                # the backoff on top would keep refusing requests after the
                # server was ready to serve them.
                #
                # Only a *usable* period counts. The meta is attacker-controlled
                # and sanitizes to 0.0 for NaN, -inf, a negative or a literal
                # zero; passing that through would read as "the server said
                # retry immediately" and drop the backoff entirely, which is
                # weaker than the default the operator configured. Fall back.
                # Only a period the capsule ACTUALLY named may override the
                # operator's configured backoff; _slow_down_seconds returns None
                # for anything else, which falls through to the configured value
                # rather than silently replacing it with an invented one.
                retry_after = self._slow_down_seconds(result) if status == 44 else None
                raise RobotsUnavailable(
                    f"the capsule answered {_status_phrase(status)}",
                    retry_after=retry_after,
                )
            # 5x (including 51 NOT FOUND) and anything unclassifiable: no policy.
            return None
        # Redirect, input prompt, certificate request or a binary body: none of
        # these is a policy we can apply, so nothing is disallowed.
        return None

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

        Note:
            A client certificate applying to this scope is presented DURING the
            handshake, which completes before ``tofu_manager.validate_certificate``
            runs below -- Gemini TLS uses ``CERT_NONE``, so the pin can only be
            checked once the peer certificate is in hand. A rogue or on-path
            server whose fingerprint TOFU then rejects has therefore already
            received the user's persistent pseudonymous identity for that scope,
            and learned that the user was active at that moment. The request
            itself is still withheld, but the identity disclosure has happened.
            Closing that window costs an extra certificate-less round trip on
            every cert-bearing request; it is documented rather than paid for.

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
                # indefinitely); the stalled worker itself is confined to
                # ssrf.py's own bounded DNS pool, never the loop's executor.
                #
                # The robots probe that just ran resolved and vetted this very
                # host:port, so reuse its answer rather than paying for a second
                # getaddrinfo on the same name microseconds later.
                credit = _PROBE_CREDIT.get()
                same_target = (
                    credit is not None
                    and credit.host == parsed_url.host
                    and credit.port == parsed_url.port
                )
                if credit is not None and same_target and credit.addresses is not None:
                    connect_addresses = credit.addresses
                else:
                    connect_addresses = await validate_target(
                        parsed_url.host,
                        parsed_url.port,
                        allow_local=self.allow_local_hosts,
                        allowed_ports=self.allowed_ports,
                    )
                    if credit is not None and same_target:
                        # This IS the probe's own fetch; hand what it vetted to
                        # the guarded fetch that follows it.
                        credit.addresses = connect_addresses

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
                #
                # Each attempt gets its own share of what is LEFT of the
                # deadline, and a TimeoutError is caught alongside
                # TLSConnectionError. A host that is down overwhelmingly DROPS
                # SYNs rather than refusing them, and a dropped SYN raises a bare
                # TimeoutError -- so with one shared deadline and no TimeoutError
                # arm the first black-holed address burned the whole budget and
                # the remaining vetted addresses were never tried at all, which
                # is the one case the fail-over exists for. Re-raising the last
                # error preserves "a timeout is reported AS a timeout".
                addresses = _ipv4_first(connect_addresses)
                last_error: Exception | None = None
                for attempt, connect_ip in enumerate(addresses):
                    remaining = timeout - (loop.time() - started)
                    per_attempt = max(0.001, remaining / (len(addresses) - attempt))
                    try:
                        connection, connection_info = await tls_client.connect(
                            parsed_url.host,
                            parsed_url.port,
                            timeout=per_attempt,
                            connect_ip=connect_ip,
                        )
                        break
                    except (TLSConnectionError, TimeoutError) as e:
                        last_error = e
                if connection is None:
                    raise last_error or TLSConnectionError(
                        f"Could not connect to {parsed_url.host}:{parsed_url.port}"
                    )

                # TLS 1.2 sends the client certificate in the clear, so an
                # identity minted for this scope is visible to any passive
                # observer of the connection. The Gemini specification makes
                # warning about that a client SHOULD, and nothing said so before:
                # neither the tool result nor the logs mentioned it.
                client_cert_warning = None
                if client_cert_path and connection_info.get("tls_version") == "TLSv1.2":
                    client_cert_warning = (
                        "Identity certificate was transmitted in the clear: the "
                        "server negotiated TLS 1.2, which sends client "
                        "certificates unencrypted"
                    )
                    logger.warning(
                        "Client certificate sent over TLS 1.2",
                        host=parsed_url.host,
                        port=parsed_url.port,
                        path=parsed_url.path,
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

                # Format Gemini request: URL + CRLF. Unlike the display/log form
                # this one MUST carry the query -- it is the status-10/11 answer.
                request_url = format_gemini_url(
                    parsed_url.host,
                    parsed_url.port,
                    parsed_url.path,
                    parsed_url.query,
                )

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
                    # Where the caller asked the render window to start. Gemini
                    # has no range request, so the whole body was still
                    # transferred; this windows what is handed to the model.
                    # A robots.txt probe never pages -- it runs with the
                    # default 0 because the gate calls it outside a fetch.
                    offset=_RENDER_OFFSET.get() if apply_content_policy else 0,
                    max_rendered_chars=(
                        self.max_rendered_chars if apply_content_policy else 0
                    ),
                    denied_mime_types=(
                        self.denied_mime_types if apply_content_policy else None
                    ),
                )

                # Add connection info to request info. Every union member
                # declares ``request_info``, so no hasattr guard is needed.
                result.request_info.update(
                    {
                        "tls_version": connection_info.get("tls_version"),
                        "cipher": connection_info.get("cipher"),
                        "cert_fingerprint": connection_info.get("cert_fingerprint"),
                        "tofu_warning": tofu_warning,
                    }
                )
                if client_cert_warning is not None:
                    result.request_info["client_cert_warning"] = client_cert_warning

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

    # The cache accessors, _bounded_fetch, _error_result and close() are
    # provided by FetchClientBase.

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
            host, port, path, common_name=common_name, validity_days=validity_days
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

    def get_client_certificate_info_for_scope(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> GeminiCertificateInfo | None:
        """Get the stored certificate a request for this scope would present.

        The same resolution the fetch path uses, reported as the registry entry
        rather than as file paths, so a caller can name the identity in play
        without learning where it is kept.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            The certificate in play for that scope, or None

        Raises:
            ValueError: If client certificates are not enabled
        """
        if not self.client_cert_manager:
            raise ValueError("Client certificates are not enabled")

        return self.client_cert_manager.get_certificate_info_for_scope(host, port, path)

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
