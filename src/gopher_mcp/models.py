"""Pydantic models for Gopher MCP data validation."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Generic, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_serializer,
    model_validator,
)

# Cache provenance. Only the result kinds the clients actually cache carry these
# fields -- Gopher menus/text/binaries and the Gemini success/gemtext bodies. An
# error, redirect, input prompt or certificate prompt is never cached, so adding
# three permanently-null keys to it would be noise. The descriptions are the
# whole point of the feature: they are what the model reads when it has to
# decide whether a response is fresh enough to answer with.
_CachedFlag = Annotated[
    bool,
    Field(
        description=(
            "True when this result was replayed from the local response cache "
            "instead of being fetched from the server during this call. Treat "
            "the content as a snapshot taken at `cached_at`, not as the "
            "current state of the resource."
        )
    ),
]
_CachedAt = Annotated[
    str | None,
    Field(
        description=(
            "ISO-8601 UTC timestamp at which the cached copy was actually "
            "fetched from the server. Null when `cached` is false."
        )
    ),
]
_CacheAgeSeconds = Annotated[
    float | None,
    Field(
        description=(
            "How old the cached copy was, in seconds, when this result was "
            "returned. If the user is asking about something that may have "
            "changed since then, fetch again with `refresh=true`. Null when "
            "`cached` is false."
        )
    ),
]

# Continuation contract for the render caps. `truncated` alone is a dead end:
# it tells the model something is missing but not how much, and gives it nothing
# to pass back to see the rest. These three say how big the whole resource is
# and where the next window starts, in the same unit the caller counts in --
# items for a menu, characters for a page body (`bytes`/`size` are byte counts,
# which an offset cannot be expressed in without splitting a UTF-8 sequence).
_TotalItems = Annotated[
    int | None,
    Field(
        description=(
            "How many items the menu holds in total, before the render limit "
            "was applied. Null when the total was not counted."
        )
    ),
]
_TotalChars = Annotated[
    int | None,
    Field(
        description=(
            "How many characters the full body holds, before the render limit "
            "was applied. Null when the total was not counted."
        )
    ),
]
_NextOffset = Annotated[
    int | None,
    Field(
        description=(
            "Where the part that was cut begins. Pass it back as `offset` to "
            "fetch the next window of the same resource. Null when nothing was "
            "cut and there is no more to fetch."
        )
    ),
]

_ResultT = TypeVar("_ResultT", bound=BaseModel)

# Every result model carries a ``kind`` literal, so the fetch unions are tagged
# unions: naming the discriminator turns validation into a single dict lookup
# (instead of trying each member in turn) and makes the advertised JSON schema a
# ``oneOf`` with a ``kind`` -> schema mapping, which is what tells a client -- and
# the model -- that these are alternatives to branch on rather than an anything-goes
# object.
_KIND = Field(discriminator="kind")


# Wire-name reconciliation for the camelCase aliases these models were written
# with. A plain ``alias`` quietly made three different names for one field:
#
# * the payload said ``next_url`` -- ``model_dump()`` without ``by_alias`` emits
#   *field* names, and that snake_case spelling is what every tool result has
#   always carried and what docs/api-reference.md documents;
# * anything dumping ``by_alias=True`` said ``nextUrl`` -- and the MCP SDK's
#   ``convert_result`` does exactly that once a tool declares an output model,
#   so annotating the fetch tools would have silently renamed half the payload;
# * a plain ``alias`` is also the *validation* name, so a result could not be
#   validated back from its own ``model_dump()`` ("nextUrl Field required"),
#   which is precisely the round trip the SDK performs before returning
#   structured content.
#
# So every such field now names ITSELF first in an ``AliasChoices`` and pins
# ``serialization_alias`` to the same string: the snake_case name validates,
# serializes and appears in the advertised JSON schema, while the camelCase
# spelling stays accepted on input so stored JSON and any external caller
# keep working. Nothing about the published payload changes. Written out at
# each field rather than built by a helper -- mypy reads ``Field(...)`` as a
# dataclass field specifier and cannot follow ``**kwargs`` into one.


# NOTE: this class's docstring becomes the ``description`` of the ``RequestInfo``
# entry in both fetch tools' advertised ``outputSchema``, which is shipped to
# every client on ``tools/list`` and, in hosts that render schemas into the
# prompt, spent as context tokens on every session. So the design rationale
# lives here, in a comment nothing publishes, and the docstring says only what a
# consumer of the payload needs. A 1,500-character docstring narrating this
# class's own change history grew gopher_fetch's schema by 61% (8,323 -> 13,438
# bytes) and told the reader nothing it could act on.
#
# WHY THIS IS A MODEL AND NOT A DICT
# ---------------------------------
# It was ``dict[str, Any]`` on fourteen result models: the one unconstrained
# object left on the wire, so the advertised schema described the field that
# says *which request this answer belongs to* as "any object". A client could
# not tell ``selector`` from a typo of it, and nothing checked ``port`` was a
# number. Every key below was read off a real construction site (the two
# clients, the Gemini status parser and the server's ``_error``/trust/
# certificate tools), not invented. ``extra="forbid"`` is the point: an
# undeclared key is a misspelling or an accidental disclosure, and under the old
# annotation both were published verbatim.
#
# WHY NOTHING IS REQUIRED
# -----------------------
# * ``timestamp`` is absent from the server's URL-only error paths -- the
#   ``_error("INVALID_REQUEST", ..., url=display)`` rejections raised before a
#   client is ever built, including one per URL of a rejected batch fetch.
# * ``url`` is absent from the trust-store and certificate-store tools, whose
#   echo is ``host``/``port``, and from the Gopher NOT_FETCHABLE result, which
#   has no URL string of its own until :meth:`GopherClient.fetch` fills it in.
#
# Making either one required would turn those paths into crashes at the moment
# they are trying to report a failure.
class RequestInfo(BaseModel):
    """What this result answers for: the request, echoed back.

    Only the keys the request actually had are present, so a missing key means
    "did not apply here", not "unknown". `url` plus `timestamp` identify which
    question a result belongs to when several arrive together from a batch.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # -- Present for both protocols ------------------------------------------
    url: str | None = Field(
        default=None,
        description="The resource this result answers for, as the server was "
        "asked for it. A Gemini URL never carries its query string here: the "
        "answer to a status-10/11 prompt travels in the query and may be a "
        "secret",
    )
    timestamp: str | None = Field(
        default=None,
        description="ISO-8601 UTC instant at which this request was made. With "
        "`cached_at` it is what distinguishes 'fetched now' from 'replayed "
        "from cache'. Absent when the request was rejected before it was sent",
    )
    host: str | None = Field(default=None, description="Host that was contacted")
    # Deliberately UNBOUNDED, despite naming a port. ``gemini_trust_update``
    # builds its provenance echo -- host, port, timestamp -- before it validates
    # its arguments, and then reports a bad port by echoing it back:
    # ``_error("INVALID_REQUEST", f"Invalid port number: {port}", **request_info)``
    # with port=70000. A ``le=65535`` here makes constructing that rejection
    # raise ValidationError out of the tool, so the one call that exists to
    # *report* an out-of-range port becomes an unhandled crash instead
    # (tests/test_trust_tool.py::TestTrustUpdateRejectsBadInput::
    # test_an_out_of_range_port_is_refused). The echo's job is to repeat what
    # was asked, including when what was asked is nonsense; range-checking
    # belongs at the tools' argument boundary, where it already happens.
    port: int | None = Field(
        default=None, description="Port that was contacted, as it was named"
    )

    # -- Gopher-only ----------------------------------------------------------
    type: str | None = Field(
        default=None,
        description="Gopher item type character the URL named (RFC 1436)",
    )
    selector: str | None = Field(
        default=None,
        description="Gopher selector that was sent, rendered JSON-safe",
    )
    search_ignored: bool | None = Field(
        default=None,
        description="True when the URL carried a search query that was NOT "
        "sent: RFC 1436 gives only type-7 items a query field, so a query on "
        "any other type is dropped. Absent when nothing was dropped",
    )

    # -- Gemini-only ----------------------------------------------------------
    path: str | None = Field(default=None, description="Path that was requested")
    has_query: bool | None = Field(
        default=None,
        description="Whether the request carried a query string. Reported as a "
        "flag rather than a value because the query holds the answer to a "
        "status-10/11 prompt, which may be sensitive",
    )
    tls_version: str | None = Field(
        default=None,
        description="TLS version negotiated with the capsule. Null when the "
        "connection reported none",
    )
    cipher: str | None = Field(
        default=None,
        description="TLS cipher suite negotiated with the capsule. Null when "
        "the connection reported none",
    )
    cert_fingerprint: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of the certificate the capsule "
        "presented, as `sha256:<hex>`. Null when none was available",
    )
    tofu_warning: str | None = Field(
        default=None,
        description="Why this connection's certificate is not the pinned one, "
        "when it is not. Null on a clean trust-on-first-use check",
    )
    client_cert_warning: str | None = Field(
        default=None,
        description="Why the client identity that was presented may not have "
        "been usable. Present only when there is such a caveat",
    )

    @model_serializer(mode="wrap")
    def _emit_only_what_was_supplied(
        self, handler: Callable[["RequestInfo"], dict[str, Any]]
    ) -> dict[str, Any]:
        """Serialize the keys a call site set, and no others.

        Fourteen optional fields dumped in full would put ten permanently-null
        keys on every Gopher menu (`has_query`, `cipher`, ...) and three on
        every Gemini page -- the same per-call noise the cache-provenance fields
        are deliberately kept off uncacheable results to avoid. It would also be
        a gratuitous wire change: `request_info` has always carried exactly the
        keys its producer wrote.

        Unset, not null, is the filter: the Gemini client writes `tls_version`,
        `cipher`, `cert_fingerprint` and `tofu_warning` on every fetch, null
        included, and those nulls are real answers ("we looked; there was
        none"). Dropping nulls instead would silently delete four keys the
        payload has always had.

        Every field's serialization name equals its field name, so the filter
        holds under ``by_alias=True`` as well -- which matters, because that is
        how the MCP SDK dumps a tool result once the tool declares an output
        model.
        """
        return {
            name: value
            for name, value in handler(self).items()
            if name in self.model_fields_set
        }

    # -- The read-only mapping face -------------------------------------------
    #
    # Provenance is read by key everywhere it is read at all -- the Gemini
    # status parser resolves a redirect against ``request_info["url"]``, and
    # both clients' tests ask whether ``"search_ignored"``/
    # ``"client_cert_warning"`` is present at all. Keeping ``[]``, ``in`` and
    # ``.get()`` working is what let this field become a model without
    # rewriting every consumer of it, and the semantics are the dict's: a key
    # nobody supplied is ABSENT, not None, so ``"search_ignored" not in
    # request_info`` still distinguishes "no query was dropped" from "a query
    # was dropped and the flag says so".
    #
    # Writes deliberately do NOT get a mapping face: ``merge`` is the only way
    # in, so every write is validated against the declared keys.

    def __getitem__(self, key: str) -> Any:
        """Return the supplied value for ``key``, as the old dict did."""
        if key not in self.model_fields_set:
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key: object) -> bool:
        """Report whether a call site actually supplied ``key``."""
        return isinstance(key, str) and key in self.model_fields_set

    def get(self, key: str, default: Any = None) -> Any:
        """Return the supplied value for ``key``, or ``default``."""
        if key not in self.model_fields_set:
            return default
        return getattr(self, key)

    def merge(self, other: "RequestInfo") -> None:
        """Copy the keys ``other`` supplies onto this echo, in place.

        Both clients build their result first and learn the rest of the
        provenance afterwards -- the Gopher client attaches the URL and selector
        once the response is back, the Gemini client attaches the negotiated TLS
        details. That merge used to be ``dict.update``, the one write on this
        field that nothing checked: a misspelt key there became a published key
        that no schema, test or reader would ever question.

        In place, not a copy, because the caller holds the result and not the
        echo. Only ``other``'s SUPPLIED keys are copied, so merging cannot
        resurrect a key as null and change what reaches the wire.
        """
        for name in other.model_fields_set:
            setattr(self, name, getattr(other, name))


# The one description of the provenance echo, shared by all fourteen result
# models the way ``_CachedFlag`` and friends are shared -- it was a seven-line
# ``Field(...)`` block copy-pasted at each, which is how the descriptions drifted
# out of saying anything.
_RequestInfo = Annotated[
    RequestInfo,
    Field(
        validation_alias=AliasChoices("request_info", "requestInfo"),
        serialization_alias="request_info",
        description="What was actually requested, echoed back so an answer can "
        "be matched to its question -- which matters most in a batch, where "
        "several results arrive together",
    ),
]

# The default belongs in the ASSIGNMENT, not in the ``Annotated`` above, and the
# difference is not cosmetic: mypy reads a model body through
# ``dataclass_transform``, where ``x: T`` with no assignment means "required in
# ``__init__``" and only an assigned field specifier makes it optional. With the
# ``default_factory`` buried in the annotation, pydantic filled the field in at
# runtime while ``mypy src`` reported "Missing named argument "request_info"" at
# every ``MenuResult``/``TextResult``/``BinaryResult`` the Gopher client builds
# -- the type checker forbidding what the code already does, and CI red. Same
# reason ``cached: _CachedFlag = False`` assigns its default here rather than in
# ``_CachedFlag``.
#
# A ``default_factory``, never a shared ``RequestInfo()`` instance: the clients
# merge provenance INTO this object in place, so one shared default would let
# every result on the process write over every other result's echo.
_REQUEST_INFO = Field(default_factory=RequestInfo)


def iso_utc(timestamp: float | None) -> str | None:
    """Render a UNIX timestamp the way tool results report instants.

    Results speak ISO-8601 UTC (``2026-09-02T12:00:00+00:00``) rather than epoch
    seconds: the client-certificate tools already report validity windows that
    way, so an epoch float elsewhere made the identical `expires` concept arrive
    in two incompatible formats, and left a model doing arithmetic to answer
    "when was this pinned" or "has this expired". Sub-second precision is
    dropped -- it is noise to every reader of a payload.

    EVERY instant a result reports goes through here -- ``cached_at``, the trust
    store's ``first_seen``/``last_seen``/``expires``, and the ``timestamp`` in
    each result's ``request_info`` -- so one payload can never carry two
    spellings of the same concept. Times that are *computed with* rather than
    reported stay floats: cache entry timestamps and ``cache_age_seconds``, the
    rate limiter and robots clocks, the deadline and budget arithmetic, and the
    on-disk ``tofu.json`` epoch format (docs/architecture.md). Only the wire
    changes.

    Args:
        timestamp: UNIX timestamp in seconds, or None.

    Returns:
        The ISO-8601 UTC rendering, or None when ``timestamp`` is None.

    """
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).replace(microsecond=0).isoformat()


def mark_from_cache(response: _ResultT, cached_at: float) -> _ResultT:
    """Return a copy of ``response`` tagged as served from the cache.

    A copy, never the stored object: the cache hands back the very instance it
    holds, so tagging in place would also mark the entry itself -- and with it
    the response already returned by the fetch that populated the entry.

    Args:
        response: The cached result to tag.
        cached_at: When the cached copy was fetched from the server, as a UNIX
            timestamp. Reported to the caller as an ISO-8601 UTC string.

    Returns:
        A copy of ``response`` carrying the cache-provenance fields.

    """
    return response.model_copy(
        update={
            "cached": True,
            "cached_at": iso_utc(cached_at),
            "cache_age_seconds": round(time.time() - cached_at, 1),
        }
    )


def _canonical_scheme(url: str, scheme: str) -> str:
    """Check ``url``'s scheme case-insensitively and return it canonicalised.

    RFC 3986 section 3.1 makes the scheme case-insensitive, and
    :func:`~gopher_mcp.gemini_parse.parse_gemini_url` accepts ``GEMINI://``
    accordingly. Matching the prefix literally here refused *at the MCP tool
    boundary* what the parser behind it accepts, so a capitalised link this
    server had itself just surfaced -- ``resolve_gemini_reference`` returns a
    scheme-bearing target verbatim -- came back as ``INVALID_REQUEST`` with a
    message claiming it was not a Gemini URL at all.

    The lowercase spelling is returned rather than the caller's, so everything
    downstream (the parsers, the cache key, the TOFU pin) sees the one
    canonical form instead of one entry per spelling.

    Args:
        url: The URL as the caller wrote it.
        scheme: The expected scheme, lowercase and without ``://``.

    Returns:
        ``url`` with its scheme lowercased.

    Raises:
        ValueError: If ``url`` does not carry ``scheme`` in any case.

    """
    prefix, separator, remainder = url.partition("://")
    if separator != "://" or prefix.lower() != scheme:
        raise ValueError(f"URL must start with '{scheme}://'")
    return f"{scheme}://{remainder}"


class GopherFetchRequest(BaseModel):
    """Request model for gopher.fetch tool."""

    url: str = Field(
        ...,
        description="Gopher URL to fetch (e.g., gopher://gopher.floodgap.com/1/)",
        examples=[
            "gopher://gopher.floodgap.com/1/",
            "gopher://gopher.floodgap.com/0/about.txt",
        ],
    )

    @field_validator("url")
    @classmethod
    def validate_gopher_url(cls, v: str) -> str:
        """Validate that the URL is a proper Gopher URL."""
        v = _canonical_scheme(v, "gopher")
        if len(v.encode("utf-8")) > 8192:
            raise ValueError("URL must not exceed 8192 bytes")
        return v


class GopherMenuItem(BaseModel):
    """Model for a single Gopher menu item."""

    type: str = Field(..., description="Gopher item type (single character)")
    title: str = Field(..., description="Human-readable item title")
    selector: str = Field(..., description="Selector string for this item")
    host: str = Field(..., description="Hostname where item resides")
    # Info ('i') lines conventionally carry port 0, so 0 is permitted here.
    port: int = Field(..., ge=0, le=65535, description="Port number (typically 70)")
    next_url: str = Field(
        ...,
        validation_alias=AliasChoices("next_url", "nextUrl"),
        serialization_alias="next_url",
        description="Fully formed gopher:// URL for this item",
    )


class MenuResult(BaseModel):
    """Result model for Gopher menu responses."""

    kind: Literal["menu"] = "menu"
    items: list[GopherMenuItem] = Field(..., description="List of menu items")
    truncated: bool = Field(
        default=False,
        description="True if the directory holds more items after this window. "
        "`next_offset` is where they start -- call again with `offset` set to "
        "it rather than treating `items` as the whole directory.",
    )
    total_items: _TotalItems = None
    next_offset: _NextOffset = None
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: _RequestInfo = _REQUEST_INFO


class TextResult(BaseModel):
    """Result model for Gopher text responses."""

    kind: Literal["text"] = "text"
    charset: str = Field(default="utf-8", description="Character encoding")
    bytes: int = Field(..., ge=0, description="Size of content in bytes")
    text: str = Field(..., description="Text content")
    truncated: bool = Field(
        default=False,
        description="True if the body continues after this window. "
        "`next_offset` is where it continues; `bytes` still reports the full "
        "original size (in bytes, which is not the unit an offset counts in).",
    )
    total_chars: _TotalChars = None
    next_offset: _NextOffset = None
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: _RequestInfo = _REQUEST_INFO


class BinaryResult(BaseModel):
    """Result model for Gopher binary responses."""

    kind: Literal["binary"] = "binary"
    bytes: int = Field(..., ge=0, description="Size of content in bytes")
    mime_type: str | None = Field(
        None,
        validation_alias=AliasChoices("mime_type", "mimeType"),
        serialization_alias="mime_type",
        description="Guessed MIME type",
    )
    note: str = Field(
        default="Binary content not returned to preserve context",
        description="Note about binary handling",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: _RequestInfo = _REQUEST_INFO


class ErrorResult(BaseModel):
    """Result model for error responses, shared by both protocols.

    `error` always carries `code` and `message`; a Gemini failure adds the
    numeric `status` and a boolean `temporary` saying whether retrying may help.
    """

    # ``error`` is ``dict[str, Any]`` rather than a typed model, and this
    # comment rather than the docstring says so because the docstring is
    # published as the ``ErrorResult`` description in both fetch tools'
    # ``outputSchema``. A Gopher-only ``dict[str, str]`` twin was the only thing
    # keeping ``status``/``temporary`` out of a Gopher error, which is a
    # constraint the two protocols should not have to share a class to express.

    # 'kind' makes the result self-describing and a reliable discriminator
    # across every result type.
    kind: Literal["error"] = "error"
    error: dict[str, Any] = Field(..., description="Error information")
    request_info: _RequestInfo = _REQUEST_INFO


# Union type for all possible response types
GopherFetchResponse = MenuResult | TextResult | BinaryResult | ErrorResult


# A tool's ``outputSchema`` is built from its return annotation, and the wrappers
# below are what let the fetch tools declare theirs. A bare union will not do:
# the MCP SDK wraps any non-``BaseModel`` return in ``{"result": ...}``, which
# would change the payload every client already reads. A ``RootModel`` IS a
# ``BaseModel``, so it is used unwrapped -- the result keeps exactly the shape it
# has always had, while the advertised schema becomes the real thing: a ``oneOf``
# over the result kinds, discriminated by ``kind``, instead of the open
# ``{"additionalProperties": true}`` object a ``-> dict[str, Any]`` annotation
# produced. The docstrings are deliberately short: they are published to the
# model as the schema's description.
class GopherFetchOutput(RootModel[Annotated[GopherFetchResponse, _KIND]]):
    """One Gopher fetch result: a menu, text, binary metadata, or an error."""


_CacheValueT = TypeVar("_CacheValueT")


class _BaseCacheEntry(BaseModel, Generic[_CacheValueT]):
    """Shared base for protocol cache entries (TTL-based expiry)."""

    key: str = Field(..., description="Cache key")
    value: _CacheValueT = Field(..., description="Cached response")
    timestamp: float = Field(..., description="Cache entry timestamp")
    ttl: int = Field(..., description="Time to live in seconds")

    def is_expired(self, current_time: float) -> bool:
        """Check if cache entry is expired."""
        return current_time - self.timestamp > self.ttl


class GopherURL(BaseModel):
    """Model for parsed Gopher URLs."""

    host: str = Field(..., description="Hostname")
    port: int = Field(default=70, description="Port number")
    gopher_type: str = Field(
        default="1", alias="gopherType", description="Gopher item type"
    )
    selector: str = Field(default="", description="Selector string")
    search: str | None = Field(None, description="Search string for type 7 items")

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("gopher_type")
    @classmethod
    def validate_gopher_type(cls, v: str) -> str:
        """Validate Gopher type is a single character."""
        if len(v) != 1:
            raise ValueError("Gopher type must be a single character")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate hostname is not empty (mirrors GeminiURL)."""
        if not v.strip():
            raise ValueError("Host cannot be empty")
        return v.strip()


class CacheEntry(_BaseCacheEntry[GopherFetchResponse]):
    """Model for Gopher cache entries."""


# ============================================================================
# Gemini Protocol Models
# ============================================================================


class GeminiURL(BaseModel):
    """Model for parsed Gemini URLs.

    Based on the ``gemini://<host>[:<port>][/<path>][?<query>]`` format.
    """

    host: str = Field(..., description="Hostname or IP address")
    port: int = Field(default=1965, description="Port number (default: 1965)")
    path: str = Field(default="/", description="Resource path")
    query: str | None = Field(None, description="Query string for user input")

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate hostname is not empty."""
        if not v.strip():
            raise ValueError("Host cannot be empty")
        return v.strip()


class GeminiFetchRequest(BaseModel):
    """Request model for gemini_fetch tool."""

    url: str = Field(
        ...,
        # gemini.circumlunar.space is retired -- it now serves only a notice
        # asking visitors to update their bookmarks -- and these strings are
        # what the tool's inputSchema teaches every calling model to fetch, as
        # well as what the published Data Models reference renders. Both
        # replacements were checked as reachable.
        description="Gemini URL to fetch (e.g., gemini://geminiprotocol.net/)",
        examples=[
            "gemini://geminiprotocol.net/",
            "gemini://skyjake.fi/",
        ],
    )

    @field_validator("url")
    @classmethod
    def validate_gemini_url(cls, v: str) -> str:
        """Validate that the URL is a proper Gemini URL."""
        v = _canonical_scheme(v, "gemini")
        if len(v.encode("utf-8")) > 1024:
            raise ValueError("URL must not exceed 1024 bytes")
        return v


class GeminiStatusCode(IntEnum):
    """Gemini protocol status codes."""

    # Input expected: status codes 10 through 19
    INPUT = 10
    SENSITIVE_INPUT = 11

    # Success: status codes 20 through 29
    SUCCESS = 20

    # Redirection: status codes 30 through 39
    TEMPORARY_REDIRECT = 30
    PERMANENT_REDIRECT = 31

    # Temporary failure: status codes 40 through 49
    TEMPORARY_FAILURE = 40
    SERVER_UNAVAILABLE = 41
    CGI_ERROR = 42
    PROXY_ERROR = 43
    SLOW_DOWN = 44

    # Permanent failure: status codes 50 through 59
    PERMANENT_FAILURE = 50
    NOT_FOUND = 51
    GONE = 52
    PROXY_REQUEST_REFUSED = 53
    BAD_REQUEST = 59

    # Client certificates: status codes 60 through 69
    CERTIFICATE_REQUIRED = 60
    CERTIFICATE_NOT_AUTHORIZED = 61
    CERTIFICATE_NOT_VALID = 62


class GeminiMimeType(BaseModel):
    """Model for Gemini MIME type parsing."""

    type: str = Field(..., description="Main MIME type (e.g., 'text')")
    subtype: str = Field(..., description="MIME subtype (e.g., 'gemini')")
    charset: str = Field(default="utf-8", description="Character encoding")
    lang: str | None = Field(None, description="Language tag (BCP47)")

    @property
    def full_type(self) -> str:
        """Get full MIME type string."""
        return f"{self.type}/{self.subtype}"

    @property
    def is_text(self) -> bool:
        """Check if this is a text MIME type."""
        return self.type == "text"

    @property
    def is_gemtext(self) -> bool:
        """Check if this is text/gemini."""
        return self.type == "text" and self.subtype == "gemini"

    @property
    def is_binary(self) -> bool:
        """Check if this is a binary MIME type."""
        return not self.is_text


class GeminiResponse(BaseModel):
    """Base model for Gemini protocol responses."""

    status: GeminiStatusCode | int = Field(..., description="Gemini status code")
    meta: str = Field(..., description="Status-dependent metadata")
    body: bytes | None = Field(None, description="Response body (if any)")

    @field_validator("meta")
    @classmethod
    def validate_meta_length(cls, v: str) -> str:
        """Validate meta field length (reasonable limit)."""
        if len(v.encode("utf-8")) > 1024:
            raise ValueError("Meta field too long")
        return v


# Response result models following Gopher patterns.
#
# One deliberate exception to "following": the Gemini results name the content
# length `size` where the Gopher results name the same fact `bytes`. It is one
# concept under two wire names, and it is kept only because renaming either
# would break every consumer of the tool output that already reads it. Anything
# protocol-agnostic (the clients' log lines, docs) must therefore handle both
# spellings; converge on one name only in a release that is already breaking.
class GeminiSuccessResult(BaseModel):
    """Result model for a successful Gemini response carrying TEXT content.

    Binary success responses use :class:`GeminiBinaryResult` (metadata only), so
    ``content`` is always decoded text here.
    """

    kind: Literal["success"] = "success"
    mime_type: GeminiMimeType = Field(
        ...,
        validation_alias=AliasChoices("mime_type", "mimeType"),
        serialization_alias="mime_type",
        description="Content MIME type",
    )
    content: str = Field(..., description="Decoded text response content")
    size: int = Field(..., ge=0, description="Content size in bytes")
    truncated: bool = Field(
        default=False,
        description="True if the body continues after this window. "
        "`next_offset` is where it continues; `size` still reports the full "
        "original size (in bytes, which is not the unit an offset counts in).",
    )
    total_chars: _TotalChars = None
    next_offset: _NextOffset = None
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None

    request_info: _RequestInfo = _REQUEST_INFO


class GeminiBinaryResult(BaseModel):
    """Result model for a successful BINARY Gemini response (metadata only).

    Mirrors the Gopher :class:`BinaryResult`: the raw bytes are NOT returned to
    the model. A 1 MB body is ~1.4M base64 characters (~350k tokens), so
    inlining it would flood the context for content the model can't render
    anyway. The consumer gets the size and detected MIME type and can fetch the
    resource directly if it genuinely needs the bytes.
    """

    kind: Literal["binary"] = "binary"
    mime_type: GeminiMimeType = Field(
        ...,
        validation_alias=AliasChoices("mime_type", "mimeType"),
        serialization_alias="mime_type",
        description="Detected content MIME type",
    )
    size: int = Field(..., ge=0, description="Content size in bytes")
    note: str = Field(
        default="Binary content not returned to preserve context",
        description="Note about binary handling",
    )
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: _RequestInfo = _REQUEST_INFO


class GeminiInputResult(BaseModel):
    """Result model for input request responses (status 10/11)."""

    kind: Literal["input"] = "input"
    prompt: str = Field(..., description="Input prompt text")
    sensitive: bool = Field(default=False, description="Whether input is sensitive")
    request_info: _RequestInfo = _REQUEST_INFO


class GeminiRedirectResult(BaseModel):
    """Result model for redirect responses (status 30/31).

    This server does not follow redirects: the caller does, by fetching
    ``new_url``. So the payload has to carry what a caller needs to decide
    whether following is safe -- the Gemini spec's five-hop limit is only
    enforceable by whoever is counting the hops, and a target on another host
    or in another scheme is the one worth stopping on.
    """

    kind: Literal["redirect"] = "redirect"
    new_url: str = Field(
        ...,
        validation_alias=AliasChoices("new_url", "newUrl"),
        serialization_alias="new_url",
        description="Redirect target URL. Follow at most five in a row, and "
        "stop if a URL you have already visited comes back: a capsule can "
        "otherwise spin a client through an unbounded chain of fetches",
    )
    permanent: bool = Field(default=False, description="Whether redirect is permanent")
    cross_host: bool | None = Field(
        default=None,
        description="True when `new_url` names a host other than the one that "
        "was requested, so the content it serves is a different party's. Null "
        "when the target could not be compared with the request",
    )
    scheme: str | None = Field(
        default=None,
        description="Scheme of `new_url`. Anything other than `gemini` leaves "
        "Geminispace and cannot be fetched with this tool. Null when the "
        "target names no scheme and the request's is unknown",
    )
    request_info: _RequestInfo = _REQUEST_INFO

    @model_validator(mode="after")
    def describe_target(self) -> "GeminiRedirectResult":
        """Fill ``scheme`` and ``cross_host`` from the target and the request.

        Derived here rather than at the call site so every redirect result
        carries them, whichever code path built it.
        """
        try:
            target = urlsplit(self.new_url)
            # ``.url`` rather than ``.get("url")``: the echo is a typed model
            # now, so the "is it even a string?" guard the dict needed is gone.
            requested = self.request_info.url
            source = urlsplit(requested) if requested is not None else None
        except ValueError:  # a target too malformed to split tells us nothing
            return self

        if self.scheme is None:
            # A relative target ("/elsewhere") stays in the request's scheme.
            inherited = source.scheme if source is not None else ""
            self.scheme = (target.scheme or inherited).lower() or None

        if self.cross_host is None:
            if not target.netloc:
                self.cross_host = False
            elif source is not None and source.hostname:
                self.cross_host = target.hostname != source.hostname

        return self


# The Gemini error result IS :class:`ErrorResult`; the alias keeps the
# protocol-suffixed spelling used by the Gemini modules and their tests.
GeminiErrorResult = ErrorResult


class GeminiCertificateResult(BaseModel):
    """Result model for certificate request responses (status 60-62).

    ``message`` is the capsule's own text and is untrusted; ``next_step`` is
    written by this server and is the only instruction in the payload.
    """

    kind: Literal["certificate"] = "certificate"
    message: str = Field(..., description="Certificate-related message")
    status: int = Field(
        default=60,
        ge=60,
        le=69,
        description="Gemini certificate status code: 60 required, 61 not "
        "authorized, 62 not valid",
    )
    required: bool = Field(
        default=True,
        description="Whether the server is prompting for a certificate (status "
        "60). False for 61/62, which are rejections of a presented identity.",
    )
    next_step: str = Field(
        default="",
        description="What to do about this response, written by this server "
        "rather than by the capsule. The three sub-codes need different "
        "answers, and only one of them is fixed by creating a certificate.",
    )
    request_info: _RequestInfo = _REQUEST_INFO


# Gemtext content models
class GemtextLineType(StrEnum):
    """Types of lines in gemtext format."""

    TEXT = "text"
    LINK = "link"
    HEADING_1 = "heading1"
    HEADING_2 = "heading2"
    HEADING_3 = "heading3"
    LIST_ITEM = "list"
    QUOTE = "quote"
    PREFORMAT = "preformat"


class GemtextLink(BaseModel):
    """Model for gemtext link lines."""

    url: str = Field(
        ...,
        description=(
            "Link URL, resolved against the request URL when the document was "
            "fetched, so links returned by a fetch are absolute"
        ),
    )
    text: str | None = Field(None, description="Link text (optional)")

    @field_validator("url")
    @classmethod
    def validate_url_not_empty(cls, v: str) -> str:
        """Validate URL is not empty."""
        if not v.strip():
            raise ValueError("Link URL cannot be empty")
        return v.strip()


class GemtextLine(BaseModel):
    """One line of a gemtext document: `type`, `content`, and nothing repeated.

    Beyond `type` and `content` a line carries only what those two cannot say --
    a link's resolved `url`, a heading's `level`, the marker-stripped `text`,
    and a preformatted block's alt-text and detected language.
    """

    # This docstring is published as the ``GemtextLine`` description in
    # gemini_fetch's ``outputSchema``, so the history stays in this comment.
    # Each line type used to nest a second object (``heading``/``list_item``/
    # ``quote``/``preformat``), and every one of those carried a
    # ``raw_content`` (or ``content``) repeating this line's ``content``
    # verbatim -- a parsed page serialized each line two or three times, and the
    # whole body once more in ``GeminiGemtextResult.raw_content``. Context is
    # the scarce resource for a model reading a capsule.

    type: GemtextLineType = Field(..., description="Type of gemtext line")
    content: str = Field(
        ..., description="The line as the server sent it, leading marker included"
    )
    text: str | None = Field(
        None,
        description=(
            "The line's text with its leading marker removed, for heading, "
            "list-item and quote lines. Absent where `content` is already the "
            "text"
        ),
    )
    link: GemtextLink | None = Field(
        None, description="Link target and text (for link lines)"
    )
    level: int | None = Field(None, description="Heading level (1-3, for headings)")
    alt_text: str | None = Field(
        None,
        description=(
            "Alt text of a preformatted block, carried on the opening ``` "
            "toggle that declares it rather than repeated on every line inside"
        ),
    )
    language: str | None = Field(
        None,
        description=(
            "Programming language recognised from `alt_text`, on the opening "
            "toggle of a preformatted block"
        ),
    )

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        """Drop the always-null per-line fields on serialization.

        A line populates only the fields its type uses, so the rest were
        emitted as ``null`` on every line -- pure token bloat for the LLM. A
        plain text line serializes to just ``type`` and ``content``. Attribute
        access is unaffected; only the serialized dict is trimmed.
        """
        data: dict[str, Any] = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class GemtextDocument(BaseModel):
    """Model for parsed gemtext document."""

    lines: list[GemtextLine] = Field(..., description="Document lines")
    links: list[GemtextLink] = Field(
        default_factory=list, description="Extracted links"
    )


class GeminiGemtextResult(BaseModel):
    """Result model for gemtext content responses."""

    kind: Literal["gemtext"] = "gemtext"
    document: GemtextDocument = Field(..., description="Parsed gemtext document")
    # Held for callers that need the body as one string -- the robots.txt reader
    # in gemini_client.py parses it -- but deliberately NOT serialized: every
    # line of it is already in `document.lines[*].content`, and shipping the
    # whole page a second time was a third of the payload the model paid for.
    # Defaulted, not required, and the default is load-bearing: `exclude=True`
    # keeps this out of `model_dump()`, and the SDK validates a tool's payload
    # back through the advertised output schema. A required-but-excluded field
    # cannot survive that round trip, so requiring it here made every gemtext
    # response fail output validation with "raw_content Field required".
    raw_content: str = Field(
        default="",
        validation_alias=AliasChoices("raw_content", "rawContent"),
        serialization_alias="raw_content",
        exclude=True,
        description="Raw gemtext content (server-side only; see `document`)",
    )
    charset: str = Field(default="utf-8", description="Character encoding")
    lang: str | None = Field(None, description="Language tag")
    size: int = Field(..., description="Content size in bytes")
    truncated: bool = Field(
        default=False,
        description="True if the page continues after this window. "
        "`next_offset` is where it continues -- at the last complete line, so "
        "windows abut exactly; `size` still reports the full original byte "
        "size (bytes are not the unit an offset counts in).",
    )
    partial_line: bool = Field(
        default=False,
        validation_alias=AliasChoices("partial_line", "partialLine"),
        serialization_alias="partial_line",
        description=(
            "True when this window both begins and ends inside a single line "
            "that is longer than the render limit. That line is delivered as a "
            "plain `text` line here and continues in the next window, so join "
            "it to the next window's first line rather than reading the two as "
            "separate lines. It is deliberately not parsed: half of a "
            "`=> url text` line would otherwise look like a complete link to a "
            "target the server never sent"
        ),
    )
    total_chars: _TotalChars = None
    next_offset: _NextOffset = None
    cached: _CachedFlag = False
    cached_at: _CachedAt = None
    cache_age_seconds: _CacheAgeSeconds = None
    request_info: _RequestInfo = _REQUEST_INFO


# Union type for all possible Gemini fetch responses
GeminiFetchResponse = (
    GeminiSuccessResult
    | GeminiBinaryResult
    | GeminiGemtextResult
    | GeminiInputResult
    | GeminiRedirectResult
    | GeminiErrorResult
    | GeminiCertificateResult
)


class GeminiFetchOutput(RootModel[Annotated[GeminiFetchResponse, _KIND]]):
    """One Gemini fetch result: gemtext, success, binary metadata, input,
    redirect, certificate, or an error."""


# Certificate and security models
class GeminiCertificateInfo(BaseModel):
    """Model for client certificate information.

    Records what a stored client certificate *is* and where it applies. It
    deliberately holds no key material and no filesystem path: the private key
    is the identity itself, and its location is operator state that must not
    reach a model through any tool result.
    """

    fingerprint: str = Field(..., description="Certificate SHA-256 fingerprint")
    subject: str = Field(..., description="Certificate subject")
    issuer: str = Field(..., description="Certificate issuer")
    not_before: str = Field(..., description="Certificate validity start")
    not_after: str = Field(..., description="Certificate validity end")
    host: str = Field(..., description="Associated hostname")
    port: int = Field(default=1965, description="Associated port")
    path: str = Field(default="/", description="Associated path scope")
    key_id: str | None = Field(
        default=None,
        description="Opaque per-certificate identifier naming this entry's key "
        "pair within the certificate store. Not a path, and not part of any "
        "tool result. Absent on entries written before it existed, whose files "
        "are named after the certificate's own common name",
    )

    def is_expired(self, current_time: float | None = None) -> bool:
        """Check if the certificate's validity window has ended.

        An unparseable ``not_after`` reports False rather than True: reporting a
        certificate expired is what prompts a user to destroy an unrecoverable
        private key, so an unreadable timestamp must not be the reason for it.
        A genuinely unusable certificate is rejected by the capsule anyway
        (status 62).

        Args:
            current_time: UNIX timestamp to compare against (default: now).

        Returns:
            True if the certificate is no longer valid.

        """
        try:
            expires = datetime.fromisoformat(self.not_after)
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        now = time.time() if current_time is None else current_time
        return expires.timestamp() <= now


class GeminiClientCertificateEntry(BaseModel):
    """A stored client certificate as reported by ``gemini_client_cert_list``.

    A deliberate projection of :class:`GeminiCertificateInfo` rather than a
    subclass of it: only what a model needs to act on an identity is reported.
    The certificate's own subject and issuer are left out because for a
    self-signed identity this server minted they say nothing about the capsule,
    and the subject doubles as the local name of the key pair on disk -- which
    the parent's rule keeps out of every tool result. The scope URL is carried
    ready-made so acting on an entry never means reassembling one.
    """

    url: str = Field(
        ...,
        description="The scope URL this identity covers. Pass it verbatim as "
        "gemini_client_cert_update's `url` to act on this entry",
    )
    host: str = Field(..., description="Host of the scope this identity covers")
    port: int = Field(default=1965, description="Port of the scope")
    path: str = Field(
        default="/",
        description="Path scope. The identity is sent for this path and every "
        "path below it",
    )
    fingerprint: str = Field(
        ...,
        description="SHA-256 fingerprint of the certificate. This is the value "
        "gemini_client_cert_update requires before it will destroy it",
    )
    not_before: str = Field(..., description="Start of the validity window")
    not_after: str = Field(..., description="End of the validity window")
    expired: bool = Field(
        ...,
        description="True if the certificate's validity window has ended, in "
        "which case the capsule will reject it (status 62)",
    )


class TOFUEntry(BaseModel):
    """Model for Trust-on-First-Use certificate storage.

    The on-disk record, kept in epoch seconds because that is what ``tofu.json``
    holds. What ``gemini_trust_list`` reports is :class:`TOFUTrustEntry`.
    """

    host: str = Field(..., description="Hostname")
    port: int = Field(default=1965, description="Port number")
    fingerprint: str = Field(..., description="Certificate SHA-256 fingerprint")
    first_seen: float = Field(..., description="Timestamp of first connection")
    last_seen: float = Field(..., description="Timestamp of last connection")
    expires: float | None = Field(None, description="Certificate expiry timestamp")

    def is_expired(self, current_time: float) -> bool:
        """Check if certificate is expired."""
        return self.expires is not None and current_time > self.expires


class TOFUTrustEntry(BaseModel):
    """A pinned certificate as reported by ``gemini_trust_list``.

    A result-side projection of :class:`TOFUEntry`, following the
    :class:`GeminiClientCertificateEntry` precedent: the store keeps epoch
    seconds, but the tool that explains a CERTIFICATE_CHANGED failure has to be
    read by a model, and epoch floats made it answer "was this reissue routine?"
    by arithmetic -- while the client-certificate tools reported the very same
    `expires` concept as an ISO-8601 string, so the two disagreed about what a
    timestamp looks like. ``expired`` is precomputed for the same reason.
    """

    host: str = Field(..., description="Host this certificate is pinned for")
    port: int = Field(default=1965, description="Port this certificate is pinned for")
    fingerprint: str = Field(
        ...,
        description="SHA-256 fingerprint of the pinned certificate. This is the "
        "value gemini_trust_update requires before it will drop the pin",
    )
    first_seen: str = Field(
        ...,
        description="ISO-8601 UTC time this certificate was first seen, i.e. "
        "when the pin was established",
    )
    last_seen: str = Field(
        ...,
        description="ISO-8601 UTC time this certificate was last presented",
    )
    expires: str | None = Field(
        None,
        description="ISO-8601 UTC end of the certificate's validity window. "
        "Null when the certificate carries no expiry",
    )
    expired: bool = Field(
        default=False,
        description="True if the validity window has ended, which makes a "
        "reissue -- and so a changed fingerprint -- the likely explanation",
    )

    @classmethod
    def from_entry(cls, entry: TOFUEntry, now: float | None = None) -> "TOFUTrustEntry":
        """Project a stored :class:`TOFUEntry` onto the reported shape.

        Args:
            entry: The stored trust-store record.
            now: UNIX timestamp to judge expiry against (default: now).

        Returns:
            The entry as ``gemini_trust_list`` reports it.

        """
        current_time = time.time() if now is None else now
        first_seen = iso_utc(entry.first_seen)
        last_seen = iso_utc(entry.last_seen)
        return cls(
            host=entry.host,
            port=entry.port,
            fingerprint=entry.fingerprint,
            # iso_utc only returns None for a None input, and both are floats.
            first_seen=first_seen or "",
            last_seen=last_seen or "",
            expires=iso_utc(entry.expires),
            expired=entry.is_expired(current_time),
        )


class TOFUTrustListResult(BaseModel):
    """Result model for a read-only inspection of the TOFU trust store.

    Only the entries the caller asked about are returned. The store's own
    filesystem path is deliberately absent: it is operator configuration that
    belongs in the server log, not in a payload handed to a model.
    """

    kind: Literal["trust_list"] = "trust_list"
    entries: list[TOFUTrustEntry] = Field(
        ...,
        description="Pinned certificates matching the request, ordered by host",
    )

    @field_validator("entries", mode="before")
    @classmethod
    def project_stored_entries(cls, v: Any) -> Any:
        """Accept stored :class:`TOFUEntry` records and project them.

        The projection happens here rather than at the call site so the store's
        epoch timestamps cannot reach the wire by anyone assembling this result
        from what the trust manager hands back.
        """
        if isinstance(v, list):
            return [
                TOFUTrustEntry.from_entry(item) if isinstance(item, TOFUEntry) else item
                for item in v
            ]
        return v

    request_info: _RequestInfo = _REQUEST_INFO


class TOFUTrustUpdateResult(BaseModel):
    """Result model for a change to the TOFU trust store.

    Reports only the host the caller named, so a modification can never become
    a way to enumerate the rest of the store.
    """

    kind: Literal["trust_update"] = "trust_update"
    action: Literal["remove", "pin"] = Field(
        ..., description="The change that was requested"
    )
    host: str = Field(..., description="Host whose pin was targeted")
    port: int = Field(..., ge=1, le=65535, description="Port whose pin was targeted")
    changed: bool = Field(
        ...,
        description="True if the trust store was actually modified. False means "
        "there was nothing to change (e.g. the host had no pin to remove)",
    )
    message: str = Field(..., description="Human-readable summary of the outcome")
    request_info: _RequestInfo = _REQUEST_INFO


class GeminiClientCertListResult(BaseModel):
    """Result model for a read-only inspection of the client certificate store.

    Only the certificates the caller asked about are returned, and each is
    reported through :class:`GeminiClientCertificateEntry`, which carries no
    private key and no path to one.
    """

    kind: Literal["client_cert_list"] = "client_cert_list"
    entries: list[GeminiClientCertificateEntry] = Field(
        ...,
        description="Stored client certificates matching the request, ordered "
        "by host, port and path scope",
    )
    request_info: _RequestInfo = _REQUEST_INFO


class GeminiClientCertUpdateResult(BaseModel):
    """Result model for a change to the client certificate store.

    Reports only the scope the caller named, so creating or removing an
    identity can never become a way to enumerate the others.
    """

    kind: Literal["client_cert_update"] = "client_cert_update"
    action: Literal["create", "remove"] = Field(
        ..., description="The change that was requested"
    )
    host: str = Field(..., description="Host of the scope acted on")
    port: int = Field(..., ge=1, le=65535, description="Port of the scope acted on")
    path: str = Field(
        ...,
        description="Path scope acted on. The certificate applies to this path "
        "and every path below it",
    )
    fingerprint: str | None = Field(
        None,
        description="SHA-256 fingerprint of the certificate created or removed. "
        "Null when nothing changed",
    )
    expires: str | None = Field(
        None,
        description="End of the created certificate's validity window. Null on "
        "removal and when nothing changed",
    )
    changed: bool = Field(
        ...,
        description="True if the certificate store was actually modified. False "
        "means there was nothing to change (e.g. no certificate covered the "
        "scope named for removal)",
    )
    message: str = Field(..., description="Human-readable summary of the outcome")
    request_info: _RequestInfo = _REQUEST_INFO


class GeminiCacheEntry(_BaseCacheEntry[GeminiFetchResponse]):
    """Model for Gemini cache entries."""
