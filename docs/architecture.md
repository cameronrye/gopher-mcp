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
│  │  • gopher_fetch()        • gemini_fetch()           │  │
│  │  • gopher_batch_fetch()  • gemini_batch_fetch()     │  │
│  │  • gemini_trust_list()   • gemini_trust_update()    │  │
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

- `gopher_fetch(url, refresh=False)` - one Gopher resource
- `gemini_fetch(url, input=None, refresh=False)` - one Gemini resource
- `gopher_batch_fetch(urls)` / `gemini_batch_fetch(urls)` - several URLs at once,
  with bounded concurrency and a 50-URL cap, returning one result per input URL
  in order
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
client-setup failure, network error and a locked trust store all become sanitized
structured errors rather than exceptions FastMCP would surface as a raw
`ToolError`. Internal exception text is logged server-side and replaced with a
generic message in the reply, so local paths and library internals never reach
the model.

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
- Certificate validation
- Cipher suite selection
- Connection timeout handling

### 6. TOFU Manager (`tofu.py`)

**Responsibility**: Trust-on-First-Use certificate validation

**Key Methods**:

- `validate_certificate(host, cert)` - Validate against stored fingerprint
- `store_certificate(host, cert)` - Store new certificate
- `load_certificates()` - Load from storage
- `save_certificates()` - Persist to storage

**Storage Format** (`~/.gemini/tofu.json`): entries are keyed by normalized
`host:port`, so one capsule reached on two ports is pinned twice. Fingerprints
are stored as bare lowercase SHA-256 hex (a pasted `sha256:AB:CD:...` form is
canonicalized on load), and timestamps are Unix epoch seconds.

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

Writes take a cross-process lock (`~/.gemini/tofu.json.lock`) and go through an
atomic replace, so two instances sharing a store cannot lose each other's pins. A
store that cannot be locked fails the request with `CERTIFICATE_STORE_UNAVAILABLE`
rather than proceeding with the pin unrecorded.

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

**Storage Structure** (`~/.gemini/certs/`), where `registry.json` records which
host/port/path scope each certificate belongs to, and each entry's `key_id`
names its files:

```
~/.gemini/certs/
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
- `RateLimiter` — per-host request spacing, plus the backoff a Gemini status-44
  `SLOW_DOWN` demands
- `RobotsGate` — per-host `/robots.txt` lookup, cached for its TTL, with one
  in-flight fetch per host. Fails **open** for Gopher (which cannot distinguish
  a missing selector from an unreachable server) and **closed** for Gemini
  (whose status codes can tell those apart)

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

### 10. Utility Facade (`utils.py`)

**Responsibility**: keep `from gopher_mcp.utils import X` working while the
implementations live in focused modules

The real code is in `helpers` (shared URL/IO helpers), `mime` (MIME
guessing/detection), `gemtext` (gemtext parsing), `gopher_parse` (Gopher URL and
menu parsing) and `gemini_parse` (Gemini URL and response parsing). `utils`
re-exports every public name from those modules.

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
| `sanitize_display_text` | Strip non-printable characters from server-controlled text before it is returned |
| `resolve_gemini_reference` | Resolve a gemtext link or redirect target against the URL it was fetched from |

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
   f. Determine response type (menu, text, binary)
   g. Process response: strip control characters, apply the render caps
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
   i. Process response based on status, stripping control characters
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

**Cache Key**: the request URL with its authority lowercased (host names are
case-insensitive; path and query are left byte-for-byte intact, since selectors
and queries are not). Each protocol has its own cache, so the scheme never needs
to be part of the key.

**Cache Entry**:

```python
{
    "key": "gopher://example.com/1/",  # the normalized URL
    "value": {...},                     # the parsed response model
    "timestamp": 1234567890.0,          # Unix timestamp when stored
    "ttl": 300,                         # seconds; 0 disables caching entirely
}
```

**Eviction Policy**: LRU (Least Recently Used) when max entries reached

**Not cached**: error results in both protocols, plus Gemini redirects, input
prompts, certificate prompts, and any request carrying a query string (whose
answer may be a secret).

**Cache provenance**: a cache hit does not hand back the stored object. The
client copies it and stamps `cached=True`, `cached_at` (the entry's own
`timestamp` — when the copy was actually fetched) and `cache_age_seconds`. The
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
   - Strong cipher suites only
   - Certificate validation

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
4. ClientManager singleton created (lazy)
   ↓
5. Wait for MCP client connections
```

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
  - Error message
  - Error type
  - Suggestions (if available)
  - Request info
    ↓
Return to MCP Client
```

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
│  │  │  Volume Mounts:             │  │  │
│  │  │  • ~/.gemini/tofu.json      │  │  │
│  │  │  • ~/.gemini/certs/         │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

## Logging and Observability

### Structured Logging

**Framework**: structlog

**Log Levels**:

- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical failures

**Log Fields**:

```python
{
    "event": "gopher_fetch_successful",
    "url": "gopher://example.com/1/",
    "response_type": "menu",
    "response_size": 1234,
    "cached": false,
    "timestamp": "2025-01-15T10:30:00Z"
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
- [Gemini Configuration](gemini-configuration.md) - Gemini-specific configuration
- [Advanced Features](advanced-features.md) - Advanced usage patterns
