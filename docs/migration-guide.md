# Migration Guide

This guide is the upgrade path between releases of the Gopher & Gemini MCP
Server: what breaks, what a client has to change, and what is merely additive.
It runs newest release first. Read down from the version you are upgrading to
until you reach the one you are coming from, and stop there — an upgrade that
crosses three releases means reading three sections.

| Version | Why you have to read it |
|---------|-------------------------|
| [0.9.0](#v090) | Result payload shapes, four new or widened error codes, where trust state lives on disk, and the project's own tooling |
| [0.8.0](#error-code-changes-in-080) | Four error codes split or renamed — anything switching on `error["code"]` |
| [0.7.0](#changed-defaults-in-070) | `robots.txt` is honoured by default; a fetch that used to succeed can now be refused |
| [0.6.0](#public-api-changes-in-060) | Rate limits on by default, an empty allowlist flipped meaning, public Python API removed |
| [0.2.0](#the-v020-gemini-addition) | Gemini added alongside Gopher; nothing that already worked changed |

There is no need to migrate stored data at any version. Caches are rebuilt on
demand, and the one on-disk format that moved (see
[Where trust state lives](#where-trust-state-lives)) keeps reading its old
location permanently.

## v0.9.0

The largest upgrade since 0.2.0: twenty-two breaking changes, most of them in
the shape of what a tool returns rather than in what you may call. No tool was
renamed or removed and no existing argument changed meaning — the new ones are
all optional — so a client that fetches a URL and branches on `kind` needs no
change at all. Everything below matters to code that reads a *particular
field*, switches on an *error code*, keeps *trust state* on disk, or imports
`gopher_mcp` directly.

### Result payloads

**Gemtext lines are flat.** A parsed line used to nest a second object beside
its own text, and every one of those objects repeated the line's raw text under
a different name; the whole page then arrived a third time in the result's
`raw_content`. A line now carries only what its `type` and `content` cannot
already say:

| Was | Now |
|-----|-----|
| `line["heading"]["text"]`, `line["heading"]["level"]` | `line["text"]`, `line["level"]` |
| `line["list_item"]["text"]` | `line["text"]` |
| `line["quote"]["text"]` | `line["text"]` |
| `line["preformat"]["alt_text"]`, `["language"]` | `line["alt_text"]`, `line["language"]` |
| `line[...]["raw_content"]` | `line["content"]` |
| `result["raw_content"]` | gone — join `document["lines"][*]["content"]` |

`line["link"]` (`url`, `text`) and `document["links"]` are unchanged, and
`content` is still the line exactly as the server sent it, leading marker
included. Fields that do not apply to a line are omitted rather than sent as
`null`, so read them with `.get()`. A preformatted block's `alt_text` and
`language` sit on the opening ` ``` ` toggle only; they are no longer repeated
on every line inside the block. `GemtextHeading`, `GemtextList`, `GemtextQuote`
and `GemtextPreformat` are deleted from `gopher_mcp.models`.

On a 233-byte sample page this takes the tool payload from 2,325 to 1,419 JSON
bytes. Context is the scarce resource for the model reading the page, which is
why the duplication went rather than being kept for compatibility.

**Timestamps are ISO-8601 UTC strings, not epoch seconds.** `cached_at` on
every cacheable result changed from a float to a string like
`2026-09-02T14:03:11Z`. `gemini_trust_list` entries now report `first_seen`,
`last_seen` and `expires` the same way — matching what the client-certificate
tools already did — plus a precomputed `expired` boolean, so "was this reissue
routine?" is answered by reading a field rather than by epoch arithmetic. The
`tofu.json` file on disk keeps its epoch format; only the wire changed.

**A Gopher info line no longer carries a `next_url`.** Servers park placeholder
values (`error.host`, port `1`, `(NULL)`) in the unused host and port fields of
an `i` line, and those were being assembled into a URL that never pointed
anywhere — two thirds of the links in a typical menu. `next_url` on an info
item is now `""`, which means *display-only, do not fetch*. The item's `type`,
`title`, `selector`, `host` and `port` are still returned so the banner text
reads. An explicit `URL:<target>` selector is still honoured. Navigation code
must skip an item whose `next_url` is empty rather than fetching it.

Relatedly, a menu item whose type field holds a control byte (ESC, NUL) is now
reported as an info line — that was the one server-controlled field that never
passed through display sanitization — so it too arrives with an empty
`next_url`.

**Gopher text results use LF line endings.** `\r\n` and lone `\r` are
normalised to `\n` after sanitization and before truncation, matching the
parsed gemtext lines. Byte counts in `bytes` still describe the response as
served.

**A Gemini failure separates the capsule's words from ours.** `error.message`
is now written by this server ("The capsule answered status 51 (NOT FOUND) for
this request…"), and the capsule's own `META` string moved to `error.meta`,
where it is labelled untrusted. Temporary statuses (41, 42, 43, 44) also carry
`error.next_step`, this server's instruction for that status, mirroring what
the certificate results already did. Code that displayed `error["message"]` as
the capsule's explanation should read `error["meta"]` instead — and should not
treat it as an instruction, which is the point of the split.

**Redirect results describe the target.** `GeminiRedirectResult` gained
`cross_host` (true when `new_url` names a host other than the one requested;
`null` when the two could not be compared) and `scheme` (anything other than
`gemini` leaves Geminispace and cannot be fetched with `gemini_fetch` at all).
This server still does not follow redirects, so the five-hop limit and the
repeat-URL check are the caller's to enforce.

**Tool failures set the MCP `isError` flag.** The six single-result tools
(`gopher_fetch`, `gemini_fetch`, `gemini_trust_list`, `gemini_trust_update`,
`gemini_client_cert_list`, `gemini_client_cert_update`) now set `isError` on
the `CallToolResult` whenever the payload's `kind` is `error`, so a blocked,
DNS-failed or rejected call no longer looks like a success to a host that reads
the flag rather than the body. The body itself is byte-for-byte what it was.
The two batch tools deliberately do **not** set it: failure there is per item,
and there is no single flag to set honestly.

**`gopher_fetch` and `gemini_fetch` advertise a real `outputSchema`** — a
`oneOf` over the result models discriminated by `kind`, in place of the open
`{"additionalProperties": true}` that a `dict` return produced. The field names
in the schema are the snake_case ones the payload has always used (`next_url`,
`request_info`, `mime_type`, `new_url`). The camelCase spellings are still
accepted on input. One consequence worth knowing: the SDK now validates the
returned `structuredContent` against that schema, so a hand-built fragment that
was never a valid result (a `{"kind": "text", "text": "hi"}` test double, say)
is rejected where it used to pass.

### Error codes

Nothing was renamed this time; the changes are new codes and one widened
meaning. Anything switching on `error["code"]` needs these branches:

| Code | What changed |
|------|--------------|
| `CERTIFICATE_NOT_YET_VALID` | **New.** A certificate whose `notBefore` is more than five minutes ahead of our clock is refused on first use. This case used to be reported as `CERTIFICATE_EXPIRED`, which inverted the diagnosis and sent the reader after a renewal that was not the problem. Unlike `CERTIFICATE_EXPIRED` it does not depend on `GEMINI_TOFU_REJECT_EXPIRED`. Under five minutes of skew is now tolerated rather than failed. |
| `SLOW_DOWN` | **New.** A host that answered `44 SLOW_DOWN` is still inside its backoff. The result carries `error.retry_after_seconds`; nothing was sent. The client used to sleep out the wait inside the call. |
| `CERTIFICATE_STORE_UNAVAILABLE` | **Widened.** It used to mean only "the store is locked by another process". It now also covers a store that cannot be *written* — a read-only disk, a misdirected `GEMINI_TOFU_STORAGE_PATH`. That `OSError` previously escaped into the robots probe's transport handler and was reported as an unreachable capsule whose stated remedy was to retry, advice that could never succeed. The trust and client-certificate tools return this code too, where they used to return `FETCH_ERROR`. |
| `BLOCKED` | **Widened.** A non-ASCII hostname that cannot be IDNA-encoded is refused here rather than being passed through raw. |
| `INVALID_REQUEST` | **Narrowed.** A `#fragment` on a Gemini URL is now stripped instead of refused, so a gemtext link or redirect target this server emitted is one the tool will follow. A negative `offset` is rejected with this code. |
| `NOT_FETCHABLE` | Unchanged in meaning, but the result now echoes the request in `request_info`, so a batch entry for an interactive item can be matched to the URL that produced it. |

`error.code` on a `SLOW_DOWN` or a widened `CERTIFICATE_STORE_UNAVAILABLE` is
the whole answer: neither is worth an immediate retry, and the second is a
local fault, not the capsule's.

### Where trust state lives

New installs keep TOFU pins and client identities in gopher-mcp's own data
directory instead of `~/.gemini/`:

| Platform | Default location |
|----------|------------------|
| Linux and other Unix | `$XDG_DATA_HOME/gopher-mcp/` when `XDG_DATA_HOME` is an absolute path, otherwise `~/.local/share/gopher-mcp/` |
| macOS | `~/Library/Application Support/gopher-mcp/` |
| Windows | `%LOCALAPPDATA%\gopher-mcp\` |

giving `tofu.json` and `certs/` inside it. `~/.gemini/` belongs to Google's
Gemini CLI and holds the very `settings.json` a user edits to register this
server, so writing generically named state into it — and tightening its
permissions — reached into another product's configuration.

**No existing install has to move anything.** An existing `~/.gemini/tofu.json`
or `~/.gemini/certs/` continues to be read and written in place, permanently
and with no deprecation: relocating a trust store behind the user's back would
either lose every pin or make a pinned host look unpinned, and a client
certificate's private key cannot be regenerated. `GEMINI_TOFU_STORAGE_PATH` and
`GEMINI_CLIENT_CERTS_STORAGE_PATH` override both, as before. The
[Configuration Guide](configuration.md#where-gemini-state-is-stored) carries the
same rules as ongoing reference, once the upgrade is behind you.

Two further changes to trust state:

- **Internationalized hostnames are pinned under one spelling.** A host is now
  IDNA-encoded when it is normalized, so `exämple.org` and `xn--exmple-cua.org`
  share one pin, one client-certificate scope and one robots policy instead of
  each quietly getting its own — which let a link using the Unicode spelling of
  an already-pinned capsule take a fresh trust-on-first-use rather than raising
  `CERTIFICATE_CHANGED`. Any store entry written under a Unicode spelling is
  orphaned by this and re-pinned under the A-label on the next visit.
- **A pin that fails to persist is no longer trusted in memory.** The retry
  after a `CERTIFICATE_STORE_UNAVAILABLE` used to be served as "already
  trusted" against a pin written nowhere, which re-opened the first-use window
  the fail-closed error exists to deny. Failed pin changes and removals are
  rolled back the same way.

### Python API

For code that imports `gopher_mcp` rather than calling the tools:

| Change | What to do |
|--------|------------|
| `GemtextHeading`, `GemtextList`, `GemtextQuote`, `GemtextPreformat` removed from `gopher_mcp.models` | Read the flat `GemtextLine` fields; see [Result payloads](#result-payloads) above |
| `TOFUTrustEntry` added | The result-side projection of `TOFUEntry` that `TOFUTrustListResult.entries` now holds; stored `TOFUEntry` records are projected automatically |
| `GeminiGemtextResult.raw_content` is `exclude=True` | Still readable in process, no longer serialized |
| `TOFUNotYetValidError` added (subclass of `TOFUExpiredError`) | Catch it *before* `TOFUExpiredError`, or a not-yet-valid certificate reports as expired |
| `ClientCertificateStorageError` added (subclass of `ClientCertificateError`) | An unwritable certificate store raises this rather than a bare `OSError` |
| `RateLimited` added; `RateLimiter` takes `max_wait_seconds` | Past that wait `acquire` raises instead of sleeping |
| `helpers.describe_oserror` added | Use it instead of `str(exc)` on a connect failure: asyncio puts the resolved IP address inside `OSError.strerror`, and that address must not reach the caller |

Dependency floors moved, which matters to anything resolving alongside this
package: `mcp>=1.28.1,<2` (was `>=1.10.0`), `cryptography>=50.0.0` (was
`>=43.0.0`), `pydantic>=2.11.0` (was `>=2.5.0`). `anyio` is gone as a declared
runtime dependency and `uvicorn>=0.31.1` is now a declared one. The `mcp` floor
is a security floor: below 1.28.1 the SDK left DNS-rebinding protection off by
default, and that is the protection the HTTP transports rely on.

### Server, CLI and transports

All additive — nothing here breaks an existing invocation:

- `gopher_fetch` takes `search`, which percent-encodes the user's terms into a
  type-7 query. A query written into the URL by hand loses everything after a
  `#` and turns a literal `+` into a space, so the server answers a search that
  was never asked. The URL form still works, since menu `next_url` values carry
  one.
- `gopher_fetch` and `gemini_fetch` take `offset`, and truncated results carry
  `next_offset` plus `total_items` (menus) or `total_chars` (bodies), so a
  result cut at the render limit can be read to the end. The batch tools
  deliberately do not take `offset`: one offset cannot mean anything across a
  list of URLs.
- `gopher_batch_fetch` and `gemini_batch_fetch` take `refresh`, which they
  previously accepted at the protocol level and silently discarded.
- The server registers its first resource, `gopher-mcp://policy`, which renders
  the effective fetch policy for both protocols, and two prompts,
  `explore_capsule(url)` and `summarize_gemlog(url, posts)`.
- The HTTP transports answer `GET /health` with `{"status": "ok", "version":
  …}`. It bypasses authorization by SDK design and exposes no configuration.
- `gopher-mcp --version` exists, and `--allowed-host HOST[:PORT]` (repeatable)
  is new. A non-loopback `--host` now turns FastMCP's DNS-rebinding Host check
  off, matching what the SDK does when it is constructed with such a host;
  `--allowed-host` keeps the check on for a named proxy or container hostname.
  Without either, a request arriving under an unexpected `Host` was refused
  with a bare `421 Misdirected Request`.
- An invalid environment value now fails at startup with one line naming the
  variable, instead of a pydantic dump.
- Under `sse` and `streamable-http`, uvicorn's startup and access logs now go
  through this project's logging pipeline, so they honour
  `GOPHER_MCP_LOG_LEVEL`, reach `GOPHER_MCP_LOG_FILE_PATH`, and never land on
  stdout.

### Project tooling

Only for contributors and anyone building from a checkout:

- **`task.py` is gone.** `uv run task <cmd>` is the way to run a project task,
  and `make <cmd>` delegates straight to it. `python task.py <cmd>` no longer
  exists. `make` with no target now prints the task list. The two task tables
  had already drifted once, and nothing compared them.
- **The `dev`, `docs` and `test` extras are now PEP 735 dependency groups.**
  The wheel carries no `Provides-Extra` at all, so `pip install gopher-mcp[dev]`
  installs the base package and *no tooling* — it does not fail, it quietly
  gives you nothing. `uv sync --all-extras` is the same trap: it succeeds and
  installs no tooling whatsoever, so a script left on the old flag goes green
  while checking nothing. Use `uv sync --all-groups`, or
  `uv sync --no-default-groups --group docs` for one group.
- The package now ships the `py.typed` marker its `Typing :: Typed` classifier
  has promised since 0.1.0, so `mypy` sees its annotations from an installed
  copy.
- Python 3.14 is covered by CI and advertised in the trove classifiers.

## Error-code changes in 0.8.0

Four error codes changed meaning. If you switch on `error["code"]`, these are
the branches to update.

| Was | Now | Why |
|-----|-----|-----|
| `BLOCKED_BY_ROBOTS` for an unretrievable `robots.txt` | `ROBOTS_UNAVAILABLE` | A capsule that never answered has not disallowed anything. Match **both** codes wherever you previously matched `BLOCKED_BY_ROBOTS`, and retry only `ROBOTS_UNAVAILABLE`: a `Disallow` is permanent, an unreachable policy is transient. Gopher fails open and so does not currently emit the new code. |
| `BLOCKED` for a hostname that will not resolve | `DNS_ERROR` | `BLOCKED` means the SSRF guard refused the target. A name that does not resolve was never refused — there was no address to evaluate — so a typo was being reported as a security block. `HostResolutionError` still subclasses `SSRFError`, so a handler catching the base is unaffected. |
| `TLS_ERROR` for an oversize response or a refused, unreachable or reset connection | `FETCH_ERROR` | Neither is a handshake fault. `TLS_ERROR` now means an actual `ssl.SSLError`. The oversize message names the cap instead of discarding it. |
| `INVALID_REQUEST` for a `3x` redirect whose target will not parse | `INVALID_REDIRECT` | The caller's URL was never wrong; the capsule's redirect target was. |

Also in 0.8.0: `GOPHER_ROBOTS_FAILURE_BACKOFF_SECONDS` and
`GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS` (default `60`, range `0`–`3600`) make
the robots.txt failure backoff configurable; `0` restores the pre-0.7.0
behaviour of re-probing on the very next request.

## Changed defaults in 0.7.0

**`robots.txt` is honoured by default on both protocols.**
`GOPHER_RESPECT_ROBOTS_TXT` and `GEMINI_RESPECT_ROBOTS_TXT` both default to
`true`; set either to `false` to restore the previous behaviour. The policy is
cached per host for 24 hours, so the cost is one probe per host rather than one
per fetch — and defaulting to ignoring an operator's stated policy is not a
reasonable default for a tool an LLM drives unattended.

Two consequences to plan for:

- **A fetch that previously succeeded can now be refused**, if the host
  disallows it. Geminispace search is the case most people hit:
  `kennedy.gemi.dev` and `tlgs.one` both `Disallow: /search`.
- **Gemini fails closed.** Per RFC 9309 §2.3.1.4, a capsule whose `robots.txt`
  cannot be retrieved at all — including during a plain network or TLS outage —
  is refused rather than fetched. In 0.7.0 that was reported as
  `BLOCKED_BY_ROBOTS`; 0.8.0 split it out as `ROBOTS_UNAVAILABLE` (above).
  Gopher fails open, since it has no status codes to distinguish an absent
  policy from an unreachable one.

A `User-agent: gopher-mcp` group is honoured by name on both protocols, so an
operator can exclude this tool specifically without excluding anything else.

## Public API changes in 0.6.0

These affect code that imports from `gopher_mcp` directly. Nothing in this
section changes the MCP tool surface, so MCP clients are unaffected.

### Removed as unused

Importing any of these now raises `ImportError` (or `AttributeError` for the
attributes and methods):

| Removed | Was in |
|---------|--------|
| `guess_mime_type` | `gopher_mcp.utils` |
| `format_gopher_url` | `gopher_mcp.utils` |
| `validate_gemini_url_components` | `gopher_mcp.utils` |
| `sanitize_selector` | `gopher_mcp.utils` |
| `TOFUManager.cleanup_expired` | `gopher_mcp.tofu` |
| `ClientCertificateManager.cleanup_expired` | `gopher_mcp.client_certs` |
| `GeminiMimeType.is_image` / `.is_audio` / `.is_video` / `.is_application` | `gopher_mcp.models` |
| `GeminiMimeType.supports_charset()` / `.get_file_extension()` | `gopher_mcp.models` |
| `GemtextLink.is_external` | `gopher_mcp.models` |
| `GemtextDocument.link_count` / `.has_headings` / `.line_count` | `gopher_mcp.models` |
| `GemtextDocument.content_summary` / `.heading_hierarchy` / `.text_content` | `gopher_mcp.models` |
| the `allowed_hosts` keyword of `validate_target` | `gopher_mcp.ssrf` |

The `gopher_mcp.models` entries were all computed properties and methods over
data the model already carries. None of them was ever included in
`model_dump()`, so **MCP tool output was byte-for-byte unaffected** — this
broke an embedder that reads `doc.text_content` or `mime.get_file_extension()`,
not a tool user. Recompute what you need from the model's own fields.

`validate_target(..., allowed_hosts=...)` now raises `TypeError`. The clients
apply their own host allowlist in `_validate_security` against a set normalized
once at construction, so the parameter was a second, redundant copy of that
check; `GopherClient`/`GeminiClient` and the `*_ALLOWED_HOSTS` settings behave
as before.

### Changed defaults in 0.6.0

Two settings that shipped in 0.4.0 defaulting to off are now on. No
configuration file changes, but throughput does:

| Setting | Was | Now |
|---------|-----|-----|
| `GOPHER_REQUESTS_PER_MINUTE` / `GEMINI_REQUESTS_PER_MINUTE` | `0` (unlimited) | `60` (one request per second, per host) |
| `GOPHER_MAX_CONCURRENT_REQUESTS` / `GEMINI_MAX_CONCURRENT_REQUESTS` | `0` (unlimited) | `5` |

Requests to one host are now paced, so a batch aimed at a single server is
spaced out rather than parallel. Set all four to `0` to restore the 0.5.x
behaviour.

Separately, an explicitly empty host allowlist flipped meaning:
`GopherClient(allowed_hosts=[])` and `GeminiClient(allowed_hosts=[])` used to
mean allow-all and now deny every host. Pass `None` (the default) for "no
restriction". The equivalent misconfiguration via `GOPHER_ALLOWED_HOSTS` /
`GEMINI_ALLOWED_HOSTS` is now a startup error.

### Added to `gopher_mcp.utils`

| Added | Purpose |
|-------|---------|
| `sanitize_display_text` | Strip dangerous invisible characters from server-controlled text before returning it |
| `resolve_gemini_reference` | Resolve a gemtext link or redirect target against the URL it was fetched from |

`gopher_mcp.utils` is now purely a backward-compatibility facade for external
importers: no module inside the package imports it any more, and a test
enforces that.

### `GeminiErrorResult` is now `ErrorResult`

The two error models were merged. `gopher_mcp.models.GeminiErrorResult` is an
alias for `ErrorResult`, so `isinstance(x, ErrorResult)` is now true for a Gemini
error and both spellings import fine. The merged model's `error` field is
`dict[str, Any]` rather than the old Gopher-only `dict[str, str]` — which is what
lets a Gemini failure carry the numeric `status` and boolean `temporary`
alongside `code` and `message`. Code that assumed `dict[str, str]` should read
`error["code"]` and use `error.get("status")` / `error.get("temporary")`.

### New tools and result fields

- Two tools were added: `gemini_trust_list` and `gemini_trust_update`, with the
  result models `TOFUTrustListResult` and `TOFUTrustUpdateResult`.
- Two more were added for client identities: `gemini_client_cert_list` and
  `gemini_client_cert_update`, with the result models
  `GeminiClientCertListResult` and `GeminiClientCertUpdateResult`. They make a
  status-60 (certificate required) capsule reachable, which it previously was
  not — deliberately, only on an explicit call, never automatically on a
  status-60 response.
- Cacheable result models grew `cached`, `cached_at` and `cache_age_seconds`;
  `gopher_fetch` and `gemini_fetch` grew an optional `refresh` argument, and
  `GopherClient.fetch` / `GeminiClient.fetch` grew a keyword-only `refresh`.
  Both are additive.
- `GeminiCertificateResult` grew `next_step`: this server's own instruction for
  that status (60, 61 and 62 need different answers), beside the capsule's
  untrusted `message`.

### Client-certificate store changes

Embedders driving `ClientCertificateManager` directly should know three things:

- Certificate and key files are now named after a random per-certificate
  `key_id`, recorded in `registry.json`, instead of the certificate's common
  name — two identities on one host could share that name and so share one key
  pair. Existing entries have no `key_id` and keep resolving to their
  common-name filenames, so no store needs migrating.
- `generate_certificate` and `remove_certificate` roll back their in-memory
  change if the registry cannot be persisted, so a raised error now always
  means the store is unchanged.
- `remove_certificate` raises `ClientCertificateKeyRetainedError` (a
  `ClientCertificateError`) when the registry entry was removed but the private
  key file survived its unlink, rather than returning True as though the key
  had been destroyed.
- `ClientCertificateManager.get_certificate_info_for_scope` is new: the same
  resolution `get_certificate_for_scope` performs, returning the registry entry
  instead of file paths.

## The v0.2.0 Gemini addition

v0.2.0 added comprehensive Gemini protocol support alongside the existing
Gopher functionality:

- **Gemini Protocol Support**: Full implementation of Gemini v0.24.1
- **`gemini_fetch` Tool**: New MCP tool for Gemini protocol access
- **TLS Security**: Mandatory TLS with TOFU certificate validation
- **Client Certificates**: Scoped storage, attached automatically when present
- **Gemtext Parser**: Native gemtext parsing with structured output
- **Dual Caching**: Separate cache systems for each protocol

Adding Gemini alongside Gopher changed nothing that already worked:

- ✅ All existing `gopher_fetch` functionality preserved
- ✅ Existing configuration variables unchanged
- ✅ Existing scripts and integrations continue to work

That statement is scoped to the v0.2.0 addition and is **not** a standing
guarantee about every later release — see the sections above for the ones that
do break things.

The rest of this page is the step-by-step for that upgrade: coming from a
Gopher-only install, this is what to do.

## Migration Steps

### 1. Update Dependencies

If you're using pip:

```bash
pip install --upgrade gopher-mcp
```

If you're using uv:

```bash
uv sync
```

### 2. Review New Configuration Options

The server now supports additional environment variables for Gemini:

```bash
# Optional Gemini configuration (all have sensible defaults)
GEMINI_MAX_RESPONSE_SIZE=1048576
GEMINI_TIMEOUT_SECONDS=30
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=300
GEMINI_MAX_CACHE_ENTRIES=1000
GEMINI_ALLOWED_HOSTS=
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
```

**Important**: You don't need to set these variables. The server will use sensible defaults.

### 3. Test Existing Functionality

Verify your existing Gopher functionality still works:

```python
# This should work exactly as before
result = await gopher_fetch("gopher://gopher.floodgap.com/1/")
print(result["kind"])  # Should be "menu" or "text"
```

### 4. Try New Gemini Features

Test the new Gemini functionality:

```python
# New Gemini support
result = await gemini_fetch("gemini://geminiprotocol.net/")
# One of "gemtext", "success", "binary", "input", "redirect", "certificate"
# or "error".
print(result["kind"])
```

## Configuration Migration

### Existing Configuration

Your existing configuration continues to work unchanged:

```bash
# These variables work exactly as before
GOPHER_MAX_RESPONSE_SIZE=1048576
GOPHER_TIMEOUT_SECONDS=30
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=300
GOPHER_MAX_CACHE_ENTRIES=1000
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org
```

### New Optional Configuration

You can optionally add Gemini configuration:

```bash
# Add these if you want to customize Gemini behavior
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,skyjake.fi
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CACHE_TTL_SECONDS=600
```

### Configuration Validation

Use the new validation script to check your configuration:

```bash
python scripts/validate-config.py
```

## Feature Comparison

| Feature | Gopher | Gemini | Notes |
|---------|--------|--------|-------|
| Protocol | Plain text | TLS encrypted | Gemini requires TLS |
| Content Format | Plain text/binary | Gemtext/binary | Gemini has rich text format |
| Caching | ✅ | ✅ | Separate cache systems |
| Host Allowlists | ✅ | ✅ | Independent configuration |
| Timeout Configuration | ✅ | ✅ | Independent settings |
| Certificate Validation | N/A | ✅ TOFU | Gemini-specific security; inspect and recover with `gemini_trust_list` / `gemini_trust_update` |
| Client Certificates | N/A | ✅ Scoped storage | Attached automatically when one exists; create or remove one deliberately with `gemini_client_cert_update` |

## Common Migration Scenarios

### Scenario 1: Basic User (No Custom Configuration)

**Before**: Using default Gopher settings
**After**: Everything works the same, plus Gemini is available

**Action Required**: None! Just update and start using `gemini_fetch` when needed.

### Scenario 2: Custom Gopher Configuration

**Before**: Custom timeout, cache, or host allowlist settings
**After**: Gopher settings unchanged, can optionally configure Gemini

**Action Required**:

1. Keep existing configuration
2. Optionally add Gemini-specific settings if desired

### Scenario 3: Security-Conscious User

**Before**: Using Gopher host allowlists for security
**After**: Same Gopher security, plus enhanced Gemini security

**Recommended Actions**:

```bash
# Keep existing Gopher allowlist
GOPHER_ALLOWED_HOSTS=trusted-gopher-hosts.com

# Add Gemini allowlist for consistency
GEMINI_ALLOWED_HOSTS=trusted-gemini-hosts.org

# Ensure TOFU is enabled (default)
GEMINI_TOFU_ENABLED=true
```

### Scenario 4: High-Performance User

**Before**: Optimized cache settings for Gopher
**After**: Can optimize both protocols independently

**Recommended Actions**:

```bash
# Keep existing Gopher optimization
GOPHER_CACHE_TTL_SECONDS=1800
GOPHER_MAX_CACHE_ENTRIES=5000

# Add similar Gemini optimization
GEMINI_CACHE_TTL_SECONDS=1800
GEMINI_MAX_CACHE_ENTRIES=5000
```

## Troubleshooting Migration Issues

### Issue: "Module not found" errors

**Cause**: Incomplete installation or environment issues
**Solution**:

```bash
# Reinstall completely
pip uninstall gopher-mcp
pip install gopher-mcp

# Or with uv
uv sync --reinstall
```

### Issue: Configuration validation errors

**Cause**: Invalid configuration values
**Solution**:

```bash
# Run validation to see specific issues
python scripts/validate-config.py

# Reset problematic variables to defaults
unset PROBLEMATIC_VARIABLE
```

### Issue: Gemini connections fail

**Cause**: Network or TLS configuration issues
**Solution**:

```bash
# Test with relaxed security (development only)
export GEMINI_TOFU_ENABLED=false

# Check network connectivity
ping geminiprotocol.net
```

### Issue: Certificate storage errors

**Cause**: The trust store or certificate store cannot be locked or written —
a read-only home directory, a container filesystem, a misdirected
`GEMINI_TOFU_STORAGE_PATH`, or no disk space. This is reported as
`CERTIFICATE_STORE_UNAVAILABLE`, and it is a local fault, not the capsule's, so
retrying does not help.

**Solution**: find out which directory is in use and fix its permissions. New
installs store state under `$XDG_DATA_HOME/gopher-mcp/` (or
`~/Library/Application Support/gopher-mcp/` on macOS,
`%LOCALAPPDATA%\gopher-mcp\` on Windows); an install that already had
`~/.gemini/tofu.json` or `~/.gemini/certs/` keeps using that. See
[Where trust state lives](#where-trust-state-lives).

```bash
# Linux/BSD default, or wherever GEMINI_TOFU_STORAGE_PATH points
STATE="${XDG_DATA_HOME:-$HOME/.local/share}/gopher-mcp"

mkdir -p "$STATE"
chmod 700 "$STATE"
df -h "$STATE"
```

The server never returns the store path in an error — it is logged, not
reported — so read the log rather than the tool result to find out which path
it tried.

## Best Practices for Migration

### 1. Gradual Adoption

- Start with existing Gopher functionality
- Gradually introduce Gemini features
- Test both protocols in development first

### 2. Configuration Management

- Use the provided `config/example.env` as a template
- Validate configuration before deployment
- Document any custom settings

### 3. Security Considerations

- Enable TOFU for Gemini in production
- Use host allowlists for both protocols
- Monitor certificate validation logs

### 4. Performance Optimization

- Monitor cache hit rates for both protocols
- Adjust cache settings based on usage patterns
- Consider separate timeout values for each protocol

## Testing Your Migration

### 1. Functional Testing

```bash
# Test Gopher functionality
python -c "
import asyncio
from gopher_mcp.server import gopher_fetch

async def test():
    result = await gopher_fetch('gopher://gopher.floodgap.com/1/')
    print(f'Gopher test: {result[\"kind\"]}')

asyncio.run(test())
"

# Test Gemini functionality
python -c "
import asyncio
from gopher_mcp.server import gemini_fetch

async def test():
    result = await gemini_fetch('gemini://geminiprotocol.net/')
    print(f'Gemini test: {result[\"kind\"]}')

asyncio.run(test())
"
```

### 2. Configuration Testing

```bash
# Validate all configuration
python scripts/validate-config.py

# Test with your specific configuration
export YOUR_CONFIG_VARS=values
python scripts/validate-config.py
```

### 3. Integration Testing

```bash
# Run the full test suite
python -m pytest tests/ -v

# Run only integration tests
python -m pytest tests/test_server.py -v
```

## Getting Help

If you encounter issues during migration:

1. **Check the logs** with debug logging enabled:

   ```bash
   export GOPHER_MCP_LOG_LEVEL=DEBUG
   ```

2. **Validate your configuration**:

   ```bash
   python scripts/validate-config.py
   ```

3. **Review the troubleshooting guide**:
   See `docs/gemini-troubleshooting.md`

4. **Test with minimal configuration**:
   Remove all custom environment variables and test with defaults

5. **Check GitHub issues**:
   Look for similar migration issues

6. **Create a new issue**:
   Include your configuration and error details

## Summary

The v0.2.0 step covered above — Gopher-only to dual-protocol — was seamless:

- ✅ **Zero breaking changes** to what already worked
- ✅ **Optional new features** available when needed
- ✅ **Independent configuration** for each protocol

That is a statement about v0.2.0 and nothing later. Releases since have broken
things deliberately, each for a stated reason:

- **0.6.0** removed public Python API and turned rate limiting on.
- **0.7.0** made `robots.txt` binding by default, so a fetch that used to
  succeed can now be refused.
- **0.8.0** renamed or split four error codes.
- **0.9.0** reshapes gemtext lines, the Gemini error payload and result
  timestamps, empties an info line's `next_url`, moves the default trust store,
  and drops `task.py` and the published extras.

If you switch on `error["code"]`, read a named result field, or drive the
Python API, work back through the version sections above from the release you
are moving to.
