# Architecture Documentation

This document provides a comprehensive overview of the Gopher & Gemini MCP Server architecture, including component interactions, data flow, and security model.

## System Overview

The Gopher & Gemini MCP Server is a Model Context Protocol (MCP) server that enables Large Language Models (LLMs) to access content from two alternative internet protocols: Gopher (1991) and Gemini (2019).

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Client (LLM)                       │
│                    (e.g., Claude Desktop)                   │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP Protocol (JSON-RPC)
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    MCP Server (FastMCP)                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Tool Handlers (server.py)               │  │
│  │  • gopher_fetch()            • gemini_fetch()       │  │
│  │  • gopher_batch_fetch()      • gemini_batch_fetch() │  │
│  │  • gemini_trust_list()       • gemini_trust_update()│  │
│  │  • gemini_client_cert_list() • gemini_client_cert_  │  │
│  │                                 update()            │  │
│  │  GET /health (HTTP transports only)                 │  │
│  └──────────────┬──────────────────────┬─────────────────┘  │
│                 │                      │                    │
│  ┌──────────────▼──────────┐  ┌───────▼──────────────────┐ │
│  │   ClientManager         │  │   ClientManager          │ │
│  │   (Singleton)           │  │   (Singleton)            │ │
│  │  • get_gopher_client()  │  │  • get_gemini_client()   │ │
│  └──────────────┬──────────┘  └───────┬──────────────────┘ │
└─────────────────┼──────────────────────┼────────────────────┘
                  │                      │
┌─────────────────▼──────────┐  ┌───────▼──────────────────────┐
│   GopherClient             │  │   GeminiClient               │
│   (gopher_client.py)       │  │   (gemini_client.py)         │
│                            │  │                              │
│  • fetch()                 │  │  • fetch()                   │
│  • _fetch_content()        │  │  • _fetch_content()          │
│  • _process_*_response()   │  │  • Response parsing          │
│  • Caching                 │  │  • Caching                   │
└─────────────┬──────────────┘  └───────┬──────────────────────┘
              │                         │
              │                         │
┌─────────────▼──────────────┐  ┌───────▼──────────────────────┐
│   Gopher Transport         │  │   Security Components        │
│   (gopher_transport.py)    │  │                              │
│                            │  │  ┌──────────────────────────┐│
│  • fetch_gopher()          │  │  │  GeminiTLSClient         ││
│  • asyncio TCP client      │  │  │  (gemini_tls.py)         ││
│  • bounded read + deadline │  │  │  • TLS 1.2+ connection   ││
└────────────────────────────┘  │  │  • Certificate handling  ││
                                │  └──────────────────────────┘│
                                │  ┌──────────────────────────┐│
                                │  │  TOFUManager             ││
                                │  │  (tofu.py)               ││
                                │  │  • Certificate storage   ││
                                │  │  • Fingerprint validation││
                                │  └──────────────────────────┘│
                                │  ┌──────────────────────────┐│
                                │  │  ClientCertificateManager││
                                │  │  (client_certs.py)       ││
                                │  │  • Explicit creation only││
                                │  │  • Scoped cert storage   ││
                                │  └──────────────────────────┘│
                                └──────────────────────────────┘
```

## Core Components

### 1. MCP Server Layer (`server.py`)

**Responsibility**: Expose Gopher and Gemini functionality as MCP tools

**Key Functions** — eight registered tools:

- `gopher_fetch(url, search=None, refresh=False, offset=0)` - one Gopher resource
- `gemini_fetch(url, input=None, refresh=False, offset=0)` - one Gemini resource
- `gopher_batch_fetch(urls, refresh=False)` /
  `gemini_batch_fetch(urls, refresh=False)` - several URLs at once, with bounded
  concurrency and a 50-URL cap, returning one result per input URL in order.
  Neither takes `offset`: one offset means nothing across a list of different
  URLs, so a truncated item is continued with the single-URL tool
- `gemini_trust_list(host=None)` - read-only inspection of the TOFU trust store
- `gemini_trust_update(action, host, fingerprint, port=1965)` - remove or replace
  one host's certificate pin
- `gemini_client_cert_list(host=None)` - read-only inspection of the stored
  client identities, without key material or storage paths
- `gemini_client_cert_update(action, url, fingerprint=None)` - create or remove
  the client identity covering one URL scope

Plus environment variable parsing and validation, and client manager singleton
access.

**Tool annotations**: the four fetch tools are `readOnlyHint` + `openWorldHint`
(they reach arbitrary external hosts but change nothing). The certificate tools
are `openWorldHint=false` — local state only — and each pair splits read from
write so the hints can be honest: `gemini_trust_list` and
`gemini_client_cert_list` are `readOnlyHint`, while `gemini_trust_update` is
`destructiveHint` + `idempotentHint` and `gemini_client_cert_update` is
`destructiveHint` and explicitly *not* idempotent (a second create is refused,
and a second remove cannot bring the deleted key back). One combined tool behind
an `action` argument could only have carried one of those, misinforming the
client either way.

**No-raise contract**: every tool returns a serialized result. Invalid input,
client-setup failure, network error and an unwritable trust store all become
sanitized structured errors rather than exceptions FastMCP would surface as a raw
`ToolError`. Internal exception text is logged server-side and replaced with a
generic message in the reply, so local paths and library internals never reach
the model.

**The `isError` flag, and why it does not contradict that**: the no-raise
contract governs how a failure is *carried* — as a payload, never as an
exception — not whether the protocol is told it was a failure. `_flag_errors`
wraps each single-result tool so it returns a `CallToolResult` whose `isError`
comes from the payload's own `kind`, which is the same fact the body already
states; nothing new is raised and the text block is byte-for-byte what FastMCP
produced before. Registration goes through `_tool`, which hands FastMCP the
wrapped form while leaving the module-level name the plain coroutine every
caller and test uses. The two batch tools are exempt (`flag_errors=False`):
failure there is per item, and one flag cannot honestly describe a list where
three URLs succeeded and two did not.

**Advertised output**: `_tool` also takes the payload model to publish as the
tool's `outputSchema`. The two fetch tools pass `GopherFetchOutput` /
`GeminiFetchOutput`, `RootModel` wrappers over their result unions with `kind`
as the discriminator, so what they advertise is a real `oneOf` over the four (or
seven) kinds instead of an open object — and FastMCP validates the returned
`structuredContent` against it. A `RootModel` is used rather than a bare union
because the SDK wraps any non-`BaseModel` return in `{"result": ...}`, which
would have changed the payload every client already reads. Every camelCase
`alias` on a result model became `validation_alias` + `serialization_alias`
pinned to the snake_case field name for the same reason: the SDK dumps
`by_alias=True` once a tool declares an output model, so a plain alias would
have silently renamed half the payload.

**Dependencies**:

- FastMCP framework
- GopherClient
- GeminiClient
- ClientManager

### 2. Client Manager (`server.py`)

**Responsibility**: Singleton pattern for client lifecycle management

**Key Features**:

- Single instance per protocol client
- Lazy initialization
- Configuration from environment variables
- Thread-safe access

**Pattern**:

```python
class ClientManager:
    _instance = None
    _gopher_client = None
    _gemini_client = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

### 3. Gopher Client (`gopher_client.py`)

**Responsibility**: Gopher protocol implementation and response processing

**Key Methods**:

- `fetch(url)` - Main entry point
- `_fetch_content(url)` - Network communication
- `_process_menu_response()` - Parse Gopher menus
- `_process_text_response()` - Parse text content
- `_process_binary_response()` - Handle binary content
- `_get_cached_response()` - Cache retrieval
- `_cache_response()` - Cache storage

**Data Flow**:

```
URL → Parse → Check Cache → Fetch (if needed) → Process → Cache → Return
```

### 4. Gemini Client (`gemini_client.py`)

**Responsibility**: Gemini protocol implementation with TLS security

**Key Methods**:

- `fetch(url)` - Main entry point
- `_fetch_content(url)` - TLS connection and response handling
- Response parsing by status code (20, 30, 40, 60, etc.)
- `_get_cached_response()` - Cache retrieval
- `_cache_response()` - Cache storage

**Dependencies**:

- GeminiTLSClient
- TOFUManager
- ClientCertificateManager

### 5. Gemini TLS Client (`gemini_tls.py`)

**Responsibility**: Low-level TLS connection management

**Key Methods**:

- `connect(host, port)` - Establish TLS connection
- `send_data(data)` - Send request
- `receive_data()` - Receive response
- `close()` - Close connection

**Security Features**:

- TLS 1.2+ enforcement
- Certificate validation (TOFU, not CA chain — see below)
- Python's default cipher suites, **deliberately not narrowed**. Peer
  authentication here is the TOFU fingerprint, not the negotiated cipher, so
  restricting to a handful of AEAD-only ECDHE suites would buy no security
  while dropping the ECDHE-CBC and DHE suites some conforming capsules are the
  only ones to offer — causing spurious TLS 1.2 handshake failures.
  `ssl.create_default_context()` already excludes the weak ciphers
- A client certificate is presented during the handshake, so it is sent
  **before** the TOFU pin can be checked; when the negotiated version is TLS
  1.2 it is sent unencrypted, and the result says so in
  `request_info.client_cert_warning`
- Connection timeout handling, with each resolved address getting its own share
  of what is left of the deadline so a black-holed first address fails over to
  the second instead of burning the whole budget

### 6. TOFU Manager (`tofu.py`)

**Responsibility**: Trust-on-First-Use certificate validation

**Key Methods**:

- `validate_certificate(host, cert)` - Validate against stored fingerprint
- `store_certificate(host, cert)` - Store new certificate
- `load_certificates()` - Load from storage
- `save_certificates()` - Persist to storage

**Storage location**: `tofu.json` in gopher-mcp's own per-user data directory —
`$XDG_DATA_HOME/gopher-mcp/` when that names an absolute path, otherwise
`%LOCALAPPDATA%\gopher-mcp\` on Windows, `~/Library/Application
Support/gopher-mcp/` on macOS and `~/.local/share/gopher-mcp/` elsewhere. The
directory is created owner-only (0700). An install that already has
`~/.gemini/tofu.json` keeps using it **in place, permanently** — see
[where Gemini state is stored](configuration.md#where-gemini-state-is-stored)
for the resolution order and why the legacy path is never migrated.

**Storage Format**: entries are keyed by normalized `host:port`, so one capsule
reached on two ports is pinned twice, and an internationalized host is keyed by
its IDNA A-label so the Unicode and punycode spellings cannot get separate pins.
Fingerprints are stored as bare lowercase SHA-256 hex (a pasted
`sha256:AB:CD:...` form is canonicalized on load), and timestamps are Unix epoch
seconds — which is a *storage* format: `gemini_trust_list` projects each record
through `TOFUTrustEntry`, reporting ISO-8601 UTC strings and a precomputed
`expired`, so the store's floats never reach the wire.

```json
{
  "example.com:1965": {
    "host": "example.com",
    "port": 1965,
    "fingerprint": "abc123...",
    "first_seen": 1736937000.0,
    "last_seen": 1736937000.0,
    "expires": 1768473000.0
  }
}
```

Writes take a cross-process lock (`tofu.json.lock` beside the store) and go
through an atomic replace, so two instances sharing a store cannot lose each
other's pins. A store that cannot be locked **or written** — a read-only disk, a
full one, a misconfigured path — fails the request with
`CERTIFICATE_STORE_UNAVAILABLE` rather than proceeding with the pin unrecorded.
Those write failures are wrapped in `TOFUStorageError` rather than escaping as a
bare `OSError`: an `OSError` reached the robots probe's blanket transport
handler and was described to the model as an unreachable capsule with
retry-forever advice, which could never succeed.

A first-use pin that fails to persist is also rolled back out of memory, so the
retry re-enters the first-use path and attempts the write again instead of being
served "already trusted" on a pin recorded nowhere — which would reopen the very
first-use window the fail-closed error exists to deny. `update_certificate` and
`remove_certificate` roll back the same way.

A certificate whose `notBefore` is in the future is tolerated for five minutes
(`NOT_BEFORE_SKEW_SECONDS`), because capsules routinely mint a self-signed
certificate at startup with `notBefore=now`; beyond that window the refusal
raises `TOFUNotYetValidError` and is reported as `CERTIFICATE_NOT_YET_VALID`,
not as an expiry.

### 7. Client Certificate Manager (`client_certs.py`)

**Responsibility**: Client certificate storage, scope matching, and generation

Generation exists here (`generate_certificate`) and is reachable from
`GeminiClient.generate_client_certificate()`, which the `gemini_client_cert_update`
tool drives — off the event loop, since RSA keygen is CPU-bound and the key,
certificate and registry are all written to disk. The fetch path calls
`get_certificate_for_scope` alone, so the store is only ever *read* during a
fetch: a status-60 response never mints an identity by itself.

**Key Methods**:

- `generate_certificate(host, port, path)` - Mint and store one identity
- `get_certificate_for_scope(host, port, path)` - The cert/key paths a request
  would present, or None
- `get_certificate_info_for_scope(host, port, path)` - The same resolution
  reported as the registry entry, so a caller can name the identity in play
  without learning where it is kept
- `list_certificates()` - Every stored entry
- `remove_certificate(host, port, path)` - Drop one entry and its files

Both scope lookups require the certificate *and* key file to still exist: an
entry whose files are gone authenticates nothing, and treating it as live would
make a status-60 capsule permanently unanswerable.

**Storage Structure**: a `certs/` directory beside `tofu.json` in the same data
directory (with the same permanent
[legacy exception](configuration.md#where-gemini-state-is-stored) for an
existing `~/.gemini/certs/`), where
`registry.json` records which host/port/path scope each certificate belongs to,
and each entry's `key_id` names its files:

```
<data dir>/gopher-mcp/certs/
├── registry.json
├── 2f8c1e0b4a7d9c6e5b3a1f0d8c7e6b5a.crt
├── 2f8c1e0b4a7d9c6e5b3a1f0d8c7e6b5a.key
├── 9b1d3c5e7f0a2b4c6d8e0f1a3b5c7d9e.crt
└── 9b1d3c5e7f0a2b4c6d8e0f1a3b5c7d9e.key
```

The filenames are random per certificate rather than derived from the host or
the certificate's subject: two identities on one host can share a subject, and a
shared filename would mean the second write destroyed the first private key
while both registry entries still resolved to the survivor.

### 8. Shared Safety Layer (`ssrf.py`, `ratelimit.py`, `robots.py`)

**Responsibility**: Protocol-agnostic guards both clients apply to every fetch

**Key Pieces**:

- `validate_target(host, port)` — resolves the name, rejects loopback, private,
  link-local and otherwise dangerous targets, enforces `*_ALLOWED_PORTS`, and
  returns the vetted IPs so the connection is pinned to them (closing the
  DNS-rebinding window)
- `normalize_host(host)` — lowercases, strips a trailing dot, and IDNA-encodes,
  so `exämple.org`, `EXÄMPLE.ORG.` and `xn--exmple-cua.org` collapse to the one
  A-label `socket.getaddrinfo` and `ssl` already use. That is what makes a TOFU
  pin, a client-certificate scope, a robots policy and a rate-limit bucket
  survive a spelling change: a link using the U-label form of an already-pinned
  capsule would otherwise get a fresh trust-on-first-use and bypass the pin. A
  non-ASCII host the codec rejects raises `SSRFError` rather than passing the
  raw U-label through. All-ASCII hosts are returned untouched
- `RateLimiter` — per-host request spacing, plus the backoff a Gemini status-44
  `SLOW_DOWN` demands. Past `max_wait_seconds` (the Gemini client sets it to
  `timeout_seconds`) it raises `RateLimited` instead of sleeping, and refuses
  *before* reserving so the dead request does not push the next caller back
- `RobotsGate` — per-host `/robots.txt` lookup, cached for its TTL, with one
  in-flight fetch per host. Fails **open** for Gopher (which cannot distinguish
  a missing selector from an unreachable server) and **closed** for Gemini
  (whose status codes can tell those apart). The failure backoff is re-checked
  *inside* the per-host lock as well as outside it, so a batch aimed at a dead
  host costs one probe rather than one serial connect timeout per queued URL

The robots probe and the fetch it guards share one rate-limit token and one DNS
resolution: a `_ProbeCredit` ContextVar records the slot the probe took and the
addresses it vetted, and each client's `_bounded_fetch` skips the second
acquire. A first fetch to a cold host previously slept a full rate-limit interval
and resolved the same name twice for what is one user request.

### 9. Shared Client Scaffolding (`client_base.py`, `cache.py`)

**Responsibility**: the one implementation of everything wrapped *around* a
protocol-specific fetch

`FetchClientBase` holds the rate limiting, concurrency bounding, host allowlist,
robots wiring, cache setup and sanitized error builder that both clients need;
`TTLCacheMixin` holds the LRU + TTL get/put. Each client supplies only
`_fetch_content` and `_fetch_robots`, plus a few class attributes (log label,
robots agent tokens, and the fail-open/fail-closed choice). Both halves were
previously duplicated character-for-character, so every fix had to be applied
twice.

`client_base` also owns the one implementation of the per-fetch wire-time
deadline — `_FetchBudget`, the `_FETCH_BUDGET` ContextVar, `_BudgetExhausted`
(a `TimeoutError` subclass, parameterized so each client keeps its own
error-mapping lineage) and the `_spend_budget` context manager — so a change to
how wire time is charged cannot be made correctly in one client and missed in
the other.

`FetchClientBase._response_size` is the protocol-agnostic accessor over the one
field the two protocols name differently: a Gopher result reports content length
as `bytes`, a Gemini one as `size`. Same meaning, kept distinct for backwards
compatibility; neither is an offset (`next_offset` and `total_chars` count
characters). Members of the union that carry no body at all — menus, errors,
redirects, input prompts — read as 0, which is what the log lines want.

### 10. Utility Facade (`utils.py`)

**Responsibility**: keep `from gopher_mcp.utils import X` working for importers
**outside** the package

The real code is in `helpers` (shared URL/IO helpers), `mime` (MIME
guessing/detection), `gemtext` (gemtext parsing), `gopher_parse` (Gopher URL and
menu parsing) and `gemini_parse` (Gemini URL and response parsing). `utils`
re-exports every public name from those modules.

Nothing inside the package imports it any more — `gopher_client`,
`gemini_client`, `tofu` and `client_certs` all import the owning submodule
directly, and a test enforces that. So this is now purely an external
compatibility surface and can be deprecated on its own schedule, and a reader
looking for the bottom of the import graph finds `helpers` rather than the
identically generic-sounding `utils`. `__init__.py` no longer imports `.server`
eagerly either: the five re-exported server names resolve through a PEP 562
module-level `__getattr__`, so importing a leaf module such as
`gopher_mcp.gemtext` no longer drags in FastMCP, cryptography and the whole MCP
SDK.

**Recently removed** as unused — importing them will now fail:

| Removed | Was in |
|---------|--------|
| `guess_mime_type` | `gopher_mcp.utils` / `mime` |
| `format_gopher_url` | `gopher_mcp.utils` / `gopher_parse` |
| `validate_gemini_url_components` | `gopher_mcp.utils` / `gemini_parse` |
| `sanitize_selector` | `gopher_mcp.utils` / `gopher_parse` |
| `TOFUManager.cleanup_expired` | `gopher_mcp.tofu` |
| `ClientCertificateManager.cleanup_expired` | `gopher_mcp.client_certs` |

**Recently added** to the facade:

| Added | Purpose |
|-------|---------|
| `sanitize_display_text` | Strip dangerous invisible characters (Cc, Cf, Cs, Co, Zl, Zp — but not the space separators, ZWJ or ZWNJ) from server-controlled text before it is returned |
| `resolve_gemini_reference` | Resolve a gemtext link or redirect target against the URL it was fetched from |

### 11. MCP Resources and Prompts (`server.py`)

Tools are not the whole protocol surface. The server also registers:

- `gopher-mcp://policy` — a read-only resource rendering the effective fetch
  policy for both protocols (allowlists, ports, timeouts, caps, robots and TOFU
  flags), with the two store paths reduced to `<configured>` / `<default>`.
  Until it existed, a `BLOCKED` or `BLOCKED_BY_ROBOTS` error named the host and
  nothing else, so explaining *why* a fetch was refused needed shell access to
  the operator's environment. There is deliberately no tool that edits it:
  fetched pages are untrusted, and one that talked the model into widening an
  allowlist would have widened it for every later fetch.
- `explore_capsule(url)` and `summarize_gemlog(url, posts=5)` — prompts encoding
  the navigation, batching, redirect-bound and untrusted-content rules that
  otherwise live only in `SERVER_INSTRUCTIONS`, which some clients drop. The
  same reasoning put the untrusted-content sentence into all four fetch tool
  descriptions.

## Data Flow

### Gopher Fetch Workflow

```
1. MCP Client → gopher_fetch(url)
   ↓
2. Parse and validate URL
   ↓
3. Check allowed hosts (if configured)
   ↓
4. Get GopherClient from ClientManager
   ↓
5. GopherClient.fetch(url)
   ↓
6. Consult /robots.txt (if enabled) — BEFORE the cache, so a Disallow also
   withholds content cached from an earlier, permitted run
   ↓
7. Check cache for existing response
   ↓
8. If cached and valid → Return cached response
   ↓
9. If not cached:
   a. Wait out the per-host rate limit, then take a concurrency slot
   b. Validate the target (SSRF guard) and pin the vetted IPs
   c. Open an async TCP connection (gopher_transport.fetch_gopher)
   d. Send the selector and stream the response
   e. Receive response (bounded by size cap and request deadline)
   f. Determine response type from the item type (menu / text / binary /
      interactive), per `_GOPHER_TYPE_CATEGORY`
   g. Process response: strip control characters, normalize line endings to LF,
      apply the render caps and record where the next window starts
   h. Cache response (errors are not cached)
   ↓
10. Return formatted result to MCP client
```

### Gemini Fetch Workflow

```
1. MCP Client → gemini_fetch(url)
   ↓
2. Parse and validate URL
   ↓
3. Check allowed hosts (if configured)
   ↓
4. Get GeminiClient from ClientManager
   ↓
5. GeminiClient.fetch(url) — opens ONE wire-time budget for everything below
   ↓
6. Consult /robots.txt (if enabled), spending from that same budget — BEFORE the
   cache, so a Disallow also withholds previously cached content
   ↓
7. Check cache for existing response
   ↓
8. If cached and valid → Return cached response
   ↓
9. If not cached:
   a. Wait out the per-host rate limit, then take a concurrency slot
   b. Validate the target (SSRF guard) and pin the vetted IPs
   c. Get GeminiTLSClient (client-cert-bound if one covers this scope)
   d. Establish TLS connection
   e. Validate certificate with TOFUManager (off the event loop)
   f. Send request
   g. Receive response
   h. Parse status code
   i. Process response based on status, stripping control characters, applying
      the render caps and recording where the next window starts
   j. Cache response (successful, query-less responses only)
   ↓
10. Return formatted result to MCP client
```

### Caching Flow

Both protocols use identical caching logic:

```
Request → Hash URL → Check Cache
                      ↓
                   Found?
                   ↙    ↘
                 Yes     No
                  ↓       ↓
            Check TTL   Fetch
                  ↓       ↓
            Valid?    Process
             ↙  ↘        ↓
           Yes  No     Cache
            ↓    ↓       ↓
         Return Fetch  Return
                  ↓
              Process
                  ↓
               Cache
                  ↓
               Return
```

**Cache Key**: for Gopher, the request URL with its authority lowercased (host
names are case-insensitive; path and query are left byte-for-byte intact, since
selectors and queries are not). For Gemini it is the URL rebuilt from the
*parsed* request — `format_gemini_url(host, port, path, query)` — so every
spelling that produces the same wire request shares one entry: `gemini://h`,
`gemini://h/`, an explicit `:1965`, a `%2e` segment and a `#fragment` no longer
re-fetch identical content into separate entries. Each protocol has its own
cache, so the scheme never needs to be part of the key.

A non-zero `offset` is appended to the key (`\x00offset=N`). What the cache
stores is the **rendered window**, not the whole body, so serving window 0 to a
request for window 200 would answer the wrong question; caching the full body
instead would put full-size bodies in a cache whose entry cap exists to bound
memory. Window 0 keeps its existing key and stays a hit.

**Cache Entry**:

```python
{
    "key": "gopher://example.com/1/",  # the normalized URL
    "value": {...},  # the parsed response model
    "timestamp": 1234567890.0,  # Unix timestamp when stored
    "ttl": 300,  # seconds; 0 disables caching entirely
}
```

**Eviction Policy**: LRU (Least Recently Used) when max entries reached

**Not cached**: error results in both protocols, plus Gemini redirects, input
prompts, certificate prompts, and any request carrying a query string (whose
answer may be a secret).

**Cache provenance**: a cache hit does not hand back the stored object. The
client copies it and stamps `cached=True`, `cached_at` (the entry's own
`timestamp` — when the copy was actually fetched) and `cache_age_seconds`. The
entry keeps epoch seconds because the TTL and the age are arithmetic; the
reported `cached_at` is rendered as an ISO-8601 UTC string, like every other
instant a result reports. The
copy matters: tagging in place would also mark the stored entry, and with it the
response already returned by the fetch that populated it. Only the cacheable
result kinds declare these fields, so an error or prompt never carries three
permanently-null keys.

**Cache bypass**: `fetch(url, refresh=True)` — reached from the `refresh`
argument of `gopher_fetch` / `gemini_fetch` — skips the lookup and goes to the
server. The response still populates the entry, so `refresh` bypasses the cache
for one read rather than disabling it. The robots gate is consulted *before* the
cache either way, so a `Disallow` also withholds content cached from an earlier,
permitted run.

**Zero TTL**: `cache_ttl_seconds=0` is treated as caching disabled, in two
places. The config layer clears `cache_enabled` when the TTL is zero, and the
client applies `cache_enabled and cache_ttl_seconds > 0` again at construction,
so a client built directly in Python behaves the same as one built from the
environment. Storing entries that are already expired when read back is all of
the bookkeeping and none of the hits.

## Security Model

### Gopher Security

**Threat Model**:

- No encryption (plaintext protocol)
- No authentication
- Potential for malicious content
- Network eavesdropping

**Mitigations**:

1. **Input Validation**
   - URL format validation
   - Selector sanitization
   - Response size limits

2. **Host Allowlisting**
   - Optional allowed hosts configuration
   - Blocks connections to non-allowed hosts
   - An allowlist that names nothing is refused at startup, so the restriction
     can never be dropped silently

3. **SSRF Protection**
   - Loopback, private and link-local targets refused unless explicitly allowed
   - Connections pinned to the vetted IPs

4. **Resource Limits**
   - Maximum response size (default: 1MB)
   - Request timeout (default: 30s)
   - Cache size limits
   - Per-host rate limit and concurrency cap

5. **Content Processing**
   - Safe parsing of menu items
   - Binary content metadata only
   - Error handling for malformed responses
   - Control characters stripped from server-supplied titles, selectors and text

### Gemini Security

**Threat Model**:

- Man-in-the-middle attacks
- Certificate spoofing
- Malicious content
- Privacy concerns

**Mitigations**:

1. **Transport Security**
   - Mandatory TLS 1.2+
   - Python's default (secure) cipher suites, not narrowed further — the pin,
     not the cipher, is what authenticates the peer
   - Certificate validation by TOFU fingerprint

2. **TOFU (Trust-on-First-Use)**
   - Certificate fingerprint storage; the pin is the only peer authentication,
     since the TLS layer does no CA-chain or hostname verification
   - Fingerprint validation on subsequent visits
   - A change fails the fetch with `CERTIFICATE_CHANGED`
   - Recovery runs through `gemini_trust_list` / `gemini_trust_update` rather
     than hand-editing the store. A removal must name the fingerprint currently
     pinned (compared constant-time), so a pin cannot be dropped blindly, and
     only one named host is ever affected or reported

3. **Client Certificates**
   - Scoped per host, port and path; secure storage with owner-only permissions
   - Privacy-preserving (unique per scope)
   - Attached automatically when one exists for the requested scope. **Never
     created by the fetch path**: a status-60 prompt is answered by an explicit
     `gemini_client_cert_update` call, because a certificate minted because a
     remote server asked for it is a persistent identity the user never chose
   - Creation refuses to replace an in-scope certificate (the private key is
     unrecoverable) and removal must name the fingerprint being destroyed, so
     an identity is never lost blindly. Key generation and the store writes run
     off the event loop

4. **Host Allowlisting**
   - Optional allowed hosts configuration
   - Blocks connections to non-allowed hosts

5. **Resource Limits**
   - Maximum response size (default: 1MB)
   - One wire-time budget per fetch (default: 30s), shared with the robots probe
   - Cache size limits
   - Per-host rate limit and concurrency cap

6. **Input Validation**
   - URL format validation
   - Status code validation
   - MIME type validation
   - Control characters stripped from bodies, link labels and `META` strings

### Security Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Security Layers                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Input Validation                                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • URL format validation                               │ │
│  │ • Protocol validation (gopher:// or gemini://)        │ │
│  │ • Host allowlist check                                │ │
│  │ • Parameter sanitization                              │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Layer 2: Transport Security (Gemini only)                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • TLS 1.2+ enforcement                                │ │
│  │ • Certificate validation                              │ │
│  │ • TOFU fingerprint verification                       │ │
│  │ • Client certificate management                       │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Layer 3: Resource Protection                              │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • Response size limits                                │ │
│  │ • Request timeouts                                    │ │
│  │ • Cache size limits                                   │ │
│  │ • Per-host rate limit + concurrency cap               │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Layer 4: Content Processing                               │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • Safe parsing                                        │ │
│  │ • Error handling                                      │ │
│  │ • Binary content restrictions                         │ │
│  │ • MIME type validation                                │ │
│  │ • Control-character stripping on server-supplied text │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Component Interactions

### Initialization Sequence

```
1. MCP Server starts
   ↓
2. FastMCP framework initializes
   ↓
3. Register tools:
   - gopher_fetch            - gemini_fetch
   - gopher_batch_fetch      - gemini_batch_fetch
   - gemini_trust_list       - gemini_trust_update
   - gemini_client_cert_list - gemini_client_cert_update
   ↓
4. Register the `GET /health` custom route (HTTP transports only)
   ↓
5. ClientManager singleton created (lazy)
   ↓
6. Wait for MCP client connections
```

### HTTP transports and logging

`mcp.run(transport=...)` remains the one way this server is started, but the
`FastMCP` object is a subclass, `_GopherMCP`, whose HTTP runners build
`uvicorn.Config(..., log_config=None)`. The SDK's own runners pass no
`log_config`, so uvicorn applies its default `dictConfig`, which gives the
`uvicorn` loggers handlers of their own with `propagate = False`: on the HTTP
transports every startup line then bypassed the JSON renderer and the
`GOPHER_MCP_LOG_FILE_PATH` tee, and the access log went to **stdout** —
contradicting the "logs always go to stderr, never stdout" guarantee that exists
because the stdio transport puts the MCP protocol stream on stdout. Passing
`log_config=None` skips that dictConfig, so uvicorn's records reach the root
handler like any other stdlib record. `log_level` is deliberately left unset, so
`GOPHER_MCP_LOG_LEVEL` governs every line the process emits rather than
FastMCP's own `FASTMCP_LOG_LEVEL` pinning uvicorn's.

Subclassing rather than serving the app from `__main__` is what keeps
`mcp.run(transport=...)` the single entry path.

### Host-header policy

The MCP SDK decides DNS-rebinding protection in the `FastMCP` constructor, and
`server.py` constructs it without a `host`, so the SDK installs its loopback-only
`Host` allowlist. Assigning `settings.host` afterwards — the only route a CLI
flag has — skips that decision entirely, which is why `--host 0.0.0.0` used to
leave the loopback allowlist in place and the container answered 421 Misdirected
Request to every non-localhost client. `__main__._transport_security` now
reproduces the constructor's decision after the fact: a routable `--host` turns
the check off (matching what the SDK does when constructed with one), and
`--allowed-host` keeps it on, widened to the named proxy or container hostnames
plus the loopback names, with what is enforced logged at startup. The `/health`
route, being a custom route, is outside the check by design.

### Request Processing Sequence

```
MCP Client                Server              ClientManager        Protocol Client
    │                        │                      │                    │
    ├─ tool_call ────────────>│                      │                    │
    │                        ├─ get_client ─────────>│                    │
    │                        │                      ├─ create/return ────>│
    │                        │<─────────────────────┤                    │
    │                        ├─ fetch ──────────────────────────────────>│
    │                        │                      │                    ├─ check cache
    │                        │                      │                    ├─ fetch (if needed)
    │                        │                      │                    ├─ process
    │                        │                      │                    ├─ cache
    │                        │<──────────────────────────────────────────┤
    │<─ result ──────────────┤                      │                    │
```

### Error Handling Flow

```
Error Occurs
    ↓
Catch Exception
    ↓
Log Error (structlog)
    ↓
Format Error Response
    ↓
Include:
  - error.code       (machine-readable)
  - error.message    (written by THIS server)
  - error.meta       (Gemini: the capsule's own text, untrusted)
  - error.next_step  (Gemini: our advice for that status)
  - request_info     (echoes the request)
    ↓
Set isError (single-result tools only)
    ↓
Return to MCP Client
```

The `message` / `meta` split is load-bearing rather than cosmetic. Every other
result type uses `error["message"]` for this server's own explanation and
remedy — a TOFU mismatch names its recovery tool there, so does a robots
refusal — so passing a capsule's `51 <instruction>` through in the same slot let
up to a kilobyte of attacker-chosen text be read as our guidance. It is the same
reasoning that keeps a certificate response's untrusted `message` apart from its
server-authored `next_step`.

## Performance Considerations

### Caching Strategy

**Benefits**:

- Reduces network requests
- Improves response time
- Reduces server load

**Configuration**:

- `GOPHER_CACHE_ENABLED` / `GEMINI_CACHE_ENABLED`
- `GOPHER_CACHE_TTL_SECONDS` / `GEMINI_CACHE_TTL_SECONDS`
- `GOPHER_MAX_CACHE_ENTRIES` / `GEMINI_MAX_CACHE_ENTRIES`

**Trade-offs**:

- Memory usage vs. performance
- Freshness vs. speed
- Cache size vs. hit rate

### Concurrency Model

**Gopher**:

- Native asyncio TCP transport (`asyncio.open_connection`)
- No thread pool: only DNS resolution runs off the loop, in its own bounded
  executor so a tarpit nameserver cannot stall unrelated fetches
- Bounded read plus an overall request deadline

**Gemini**:

- Asynchronous TLS connections
- Native async/await support
- Trust-store reads and writes run off the loop, since a pin involves a
  cross-process lock, a full re-read and an fsync'd rewrite

Both clients apply the same two limits before opening a connection: a per-host
rate limit (waited out *before* a concurrency slot is taken, so one throttled
host cannot occupy every slot) and a cap on simultaneous in-flight fetches.

### Resource Management

**Connections**:

- Every fetch opens a fresh connection and closes it afterwards; there is no
  pooling or reuse in either protocol

**Memory Management**:

- Response size limits prevent memory exhaustion
- Cache eviction prevents unbounded growth
- Streaming not supported (responses buffered)

## Extension Points

### Adding New Response Types

1. Define new response model in `models.py`
2. Add processing logic in client
3. Update type hints and documentation

### Adding New Security Features

1. Implement in appropriate security module
2. Add configuration options
3. Update security documentation

### Adding New Protocols

1. Create new client class (e.g., `FtpClient`)
2. Implement `fetch()` method
3. Add to `ClientManager`
4. Register MCP tool in `server.py`

## Testing Architecture

### Test Layers

```
┌─────────────────────────────────────────────────────────┐
│  Protocol Tests (tests/test_mcp_protocol.py)           │
│  • Tool list and outputSchema                          │
│  • structuredContent and isError                       │
│  • The batch tools' `result` wrapper                   │
│  • Continuation fields on the wire                     │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  Integration Tests (tests/test_integration.py)         │
│  • End-to-end workflows                                │
│  • Protocol integration                                │
│  • Error scenarios                                     │
│  • Concurrency                                         │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  Unit Tests (tests/test_*.py)                          │
│  • Individual components                               │
│  • Edge cases                                          │
│  • Error handling                                      │
│  • Data validation                                     │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  Mocking Strategy                                       │
│  • Async TCP requests (Gopher)                         │
│  • TLS connections (Gemini)                            │
│  • File system operations                              │
│  • Network failures                                    │
└─────────────────────────────────────────────────────────┘
```

The protocol layer is tested separately because every other test calls the tool
coroutines directly, which skips the FastMCP layer that builds the result
envelope from each tool's return annotation — so that layer can break silently
(a dropped return annotation makes `structuredContent` `None` with the whole
suite still green). These tests drive the real server object over an in-memory
client session via `mcp.shared.memory.create_connected_server_and_client_session`.
They are also the automated guard for the deferred `mcp` 2.x port, which last
time had to be checked by hand-diffing raw JSON-RPC bytes.

### Test Markers

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.asyncio` - Async tests

## Deployment Architecture

### Standalone Deployment

```
┌─────────────────────────────────────────┐
│  Host Machine                           │
│  ┌───────────────────────────────────┐  │
│  │  MCP Client (Claude Desktop)      │  │
│  └───────────┬───────────────────────┘  │
│              │ stdio                    │
│  ┌───────────▼───────────────────────┐  │
│  │  MCP Server Process               │  │
│  │  (uv run task serve)              │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Docker Deployment

```
┌─────────────────────────────────────────┐
│  Host Machine                           │
│  ┌───────────────────────────────────┐  │
│  │  MCP Client                       │  │
│  └───────────┬───────────────────────┘  │
│              │ stdio/network            │
│  ┌───────────▼───────────────────────┐  │
│  │  Docker Container                 │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  MCP Server                 │  │  │
│  │  └─────────────────────────────┘  │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  State (needs a volume):    │  │  │
│  │  │  /home/app/.local/share/    │  │  │
│  │  │      gopher-mcp/tofu.json   │  │  │
│  │  │      gopher-mcp/certs/      │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

Those are in-container paths, and nothing is persisted without an explicit `-v`.
Without one, every `docker run --rm` starts with an empty trust store — so each
start re-arms blind trust-on-first-use — and destroys any minted client identity,
whose private key the rest of these docs correctly call unrecoverable.

The mount point has to be exact: `/home/app/.local/share/gopher-mcp`, which the
image pre-creates owned by the runtime user and mode 700 so a named volume comes
up writable rather than root-owned. A volume mounted anywhere else leaves the
store on the container's own filesystem and persists an empty directory.
`~/.gemini` is not an alternative — the resolver treats it as authoritative only
when the store file is already there, which it is not in a fresh image, and
pointing `XDG_DATA_HOME` back at it would put state into Google's Gemini CLI
configuration directory, which is what moving out of there was for. See
[Installation](installation.md#method-5-docker) for the exact commands.

There is deliberately no bare `VOLUME` instruction: an anonymous volume is
recreated per `docker run` and deleted by `--rm`, so it would persist nothing
while making the image look as though it did.

## Logging and Observability

### Structured Logging

**Framework**: structlog

**Log Levels**:

- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical failures

**Log Fields**: request detail (URL, host, port, Gopher type, selector, search
terms), response metadata (kind, size, cache status), timing, and — on a
failure — the error code and exception type. A record looks like this:

```json
{
  "event": "Gopher fetch successful",
  "url": "gopher://gopher.floodgap.com/1/",
  "host": "gopher.floodgap.com",
  "port": 70,
  "gopher_type": "1",
  "selector": "",
  "search": null,
  "response_type": "menu",
  "response_size": 2048,
  "cached": false,
  "timestamp": "2026-09-02T10:30:00Z"
}
```

### Metrics

**Key Metrics**:

- Request count (per protocol)
- Response time (per protocol)
- Cache hit rate
- Error rate
- Response size distribution

## See Also

- [Configuration Guide](configuration.md) - Detailed configuration options
- [API Reference](api-reference.md) - API documentation
- [Gemini Support and Trust Model](gemini-support.md) - TOFU, client
  certificates and the Gemini result kinds
