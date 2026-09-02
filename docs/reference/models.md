# Data Models

Authoritative, auto-generated reference for the Pydantic models that define tool
inputs and outputs. These are generated directly from
[`gopher_mcp.models`](https://github.com/cameronrye/gopher-mcp/blob/main/src/gopher_mcp/models.py),
so they never drift from the code. For usage examples and error-handling
recipes, see the [API Reference](../api-reference.md).

## Conventions

Three rules run through every result model, and knowing them saves reading each
one in turn.

**Every result carries a `kind`.** It is the discriminator of a tagged union, so
branch on it rather than probing for fields. `gopher_fetch` returns one of
`menu`, `text`, `binary` or `error`; `gemini_fetch` returns one of `gemtext`,
`success`, `binary`, `input`, `redirect`, `certificate` or `error`. Both tools
advertise that union as a real `outputSchema` (a `oneOf` keyed on `kind`)
through the `RootModel` wrappers documented under
[Tool Output Wrappers](#tool-output-wrappers).

**Every instant is an ISO-8601 UTC string**, never epoch seconds — `cached_at`,
the trust store's `first_seen`/`last_seen`/`expires`, and the `timestamp` inside
every result's `request_info`. Times the server *computes with* rather than
reports stay floats (cache TTLs, `cache_age_seconds`, the rate limiter, the
on-disk `tofu.json` format); only the wire changed.

::: gopher_mcp.models.iso_utc

**Sizes are bytes and offsets are characters.** They are different units and are
never interchangeable — see [Reading a truncated result](#reading-a-truncated-result).

## Request Models

::: gopher_mcp.models.GopherFetchRequest

::: gopher_mcp.models.GeminiFetchRequest

## Tool Output Wrappers

These exist so `gopher_fetch` and `gemini_fetch` can declare a real
`outputSchema` without changing the payload. A `RootModel` is a `BaseModel`, so
the MCP SDK uses it unwrapped: the result keeps the exact shape it has always
had, while the advertised schema becomes a `oneOf` over the result kinds instead
of an open `{"additionalProperties": true}` object.

::: gopher_mcp.models.GopherFetchOutput

::: gopher_mcp.models.GeminiFetchOutput

## Gopher Result Models

::: gopher_mcp.models.GopherMenuItem

::: gopher_mcp.models.MenuResult

::: gopher_mcp.models.TextResult

::: gopher_mcp.models.BinaryResult

::: gopher_mcp.models.ErrorResult

!!! note "What `error` holds"
    `error` is an open dict because the two protocols report different things
    in it. Both always carry `code` and `message`, where `message` is written by
    this server. A Gemini 4x/5x failure adds the numeric `status`, the boolean
    `temporary`, and `meta` — the capsule's own text, which is untrusted and is
    deliberately kept out of `message` so a hostile capsule cannot have a
    kilobyte of its own prose read as this server's guidance. A temporary
    failure also carries `next_step`, which this server writes. A host that is
    still serving out a status-44 backoff answers with code `SLOW_DOWN` and a
    `retry_after_seconds` float rather than sleeping inside the tool call.

## Reading a truncated result

`truncated: true` means *there is more after this window*, not *content was
discarded*. The result that carries it also carries `next_offset`: pass it back
as the fetch tool's `offset` argument to read the next window, and keep going
until `next_offset` is null.

| Field | On | Counts |
|-------|----|--------|
| `total_items`, `next_offset` | `MenuResult` | menu items |
| `total_chars`, `next_offset` | `TextResult`, `GeminiSuccessResult`, `GeminiGemtextResult` | characters |

A total is null when it was not counted — a directory larger than the render cap
does not get walked twice to total it. For gemtext, `next_offset` lands on the
last complete line, so consecutive windows abut exactly. Neither batch tool
accepts `offset`; continue a truncated batch item with the single-URL tool.

`bytes` (Gopher) and `size` (Gemini) are **byte** counts of the whole original
resource and are never offsets — a byte offset cannot be expressed without the
risk of splitting a UTF-8 sequence.

## Gemini Result Models

Gemini results name the content length `size` where Gopher results name it
`bytes`. Same concept, two wire names, kept distinct because both are published
tool output that renaming would break for every existing consumer. Code that
needs it protocol-agnostically goes through `FetchClientBase._response_size`,
which is the single place that knows which protocol says which.

::: gopher_mcp.models.GeminiSuccessResult

::: gopher_mcp.models.GeminiBinaryResult

::: gopher_mcp.models.GeminiGemtextResult

::: gopher_mcp.models.GeminiInputResult

::: gopher_mcp.models.GeminiRedirectResult

::: gopher_mcp.models.GeminiCertificateResult

!!! note "`GeminiErrorResult` is `ErrorResult`"
    There is no separate Gemini error model: `GeminiErrorResult` is an alias for the `ErrorResult` documented under [Gopher Result Models](#gopher-result-models) above, which both protocols return. Its `error` field is `dict[str, Any]` precisely so a Gemini failure can carry the numeric `status`, the boolean `temporary` and the capsule's own `meta` beside the `code` and `message`; a Gopher failure omits those keys.

## Trust-Store Tool Results

Returned by the `gemini_trust_list` and `gemini_trust_update` tools. See the
[API Reference](../api-reference.md#gemini_trust_list) for the recovery
procedure they support. `gemini_trust_list` reports
`TOFUTrustEntry`, a projection of the stored
[`TOFUEntry`](#caching-and-security-models): the store keeps epoch seconds,
but a tool whose whole job is explaining a `CERTIFICATE_CHANGED` failure has to
be readable without arithmetic, so the projection renders the three timestamps
as ISO-8601 UTC and precomputes `expired`.

::: gopher_mcp.models.TOFUTrustEntry

::: gopher_mcp.models.TOFUTrustListResult

::: gopher_mcp.models.TOFUTrustUpdateResult

## Client-Certificate Tool Results

Returned by the `gemini_client_cert_list` and `gemini_client_cert_update` tools.
See the [API Reference](../api-reference.md#gemini_client_cert_list) for the
status-60 procedure they support. None of these models carries key material or
the certificate store's filesystem path. `GeminiClientCertificateEntry` is a
projection of the stored `GeminiCertificateInfo` (under
[Caching and Security Models](#caching-and-security-models)): it adds the scope
as a ready-to-use URL and the expiry resolved against the current time, and
leaves out the certificate's subject and issuer, which this server generated and
under which it stores the key pair.

::: gopher_mcp.models.GeminiClientCertificateEntry

::: gopher_mcp.models.GeminiClientCertListResult

::: gopher_mcp.models.GeminiClientCertUpdateResult

## Gemtext Document Models

One parsed line is one `GemtextLine`. There are no per-type nested models: a
heading, list item, quote or preformatted line used to nest a second object that
repeated the line's own text under another name, so a page serialized each of
its lines two or three times. `GemtextLine` now carries `type` and `content` —
the line exactly as the server sent it, marker included — plus only what the
marker cannot say: the marker-stripped `text`, a heading `level`, the resolved
`link`, and a preformatted block's `alt_text` and detected `language`. Fields a
line does not use are omitted from the payload rather than serialized as null.

For the same reason `GeminiGemtextResult.raw_content` is no longer serialized at
all. It remains readable in-process (the robots.txt reader parses it), but every
line of it is already in `document.lines[*].content`, and shipping the whole
page a second time was a third of the payload.

::: gopher_mcp.models.GemtextDocument

::: gopher_mcp.models.GemtextLine

::: gopher_mcp.models.GemtextLink

::: gopher_mcp.models.GemtextLineType

## MIME and Protocol Types

::: gopher_mcp.models.GeminiMimeType

::: gopher_mcp.models.GeminiStatusCode

::: gopher_mcp.models.GeminiResponse

## URL Models

::: gopher_mcp.models.GopherURL

::: gopher_mcp.models.GeminiURL

## Caching and Security Models

::: gopher_mcp.models.CacheEntry

::: gopher_mcp.models.GeminiCacheEntry

::: gopher_mcp.models.GeminiCertificateInfo

::: gopher_mcp.models.TOFUEntry
