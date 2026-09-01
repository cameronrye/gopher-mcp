# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `robots.txt` support for both protocols, **opt-in and off by default**: set
  `GOPHER_RESPECT_ROBOTS_TXT` or `GEMINI_RESPECT_ROBOTS_TXT` to `true` to enable
  it (both default to `false`, because it costs a round-trip per host). An
  upgraded deployment does not honour `robots.txt` until you set them. Gopher
  honours the `gopher-mcp` and generic `*` user-agents, per the Veronica-2
  convention; Gemini honours those plus the companion specification's
  `webproxy` and `indexer` virtual agents, so an existing
  `User-agent: indexer` group on a capsule now applies to this client.
  `GOPHER_ROBOTS_HONOR_AI_TOKENS` / `GEMINI_ROBOTS_HONOR_AI_TOKENS` (default
  `true` — the one robots-related default that is on) additionally honour rules
  aimed at named AI-crawler tokens such as `ClaudeBot`, `GPTBot` and `CCBot`,
  and `GOPHER_ROBOTS_CACHE_TTL_SECONDS` / `GEMINI_ROBOTS_CACHE_TTL_SECONDS`
  (default `86400`, the maximum RFC 9309 §2.4 permits) set how long a fetched
  policy stays valid. Gopher fails open when a policy cannot be retrieved;
  Gemini fails closed, per RFC 9309.
- New `error.code` values a client can now receive: `BLOCKED_BY_ROBOTS` on both
  protocols (only when `RESPECT_ROBOTS_TXT` is on), `CERTIFICATE_STORE_UNAVAILABLE`
  when a trust or certificate store cannot be read or is locked by another
  process, and — from the four new certificate tools — `TOFU_DISABLED`,
  `CLIENT_CERTS_DISABLED`, `FINGERPRINT_MISMATCH` and `CERTIFICATE_EXISTS`. A
  script switching on `error["code"]` needs a branch for each;
  `docs/api-reference.md` documents them all.
- Fetch results say whether they came from cache and when the copy was
  originally fetched, and `gopher_fetch` / `gemini_fetch` take a `refresh`
  argument that bypasses the cache for one request while still repopulating it.
  A model can no longer mistake a five-minute-old page for the current one.
- `gemini_trust_list` and `gemini_trust_update` tools make a legitimate
  certificate rotation recoverable. Self-signed Gemini certificates are
  reissued routinely, and until now a rotation produced a `CERTIFICATE_CHANGED`
  error whose only remedy was hand-editing the TOFU store on disk. Listing is
  read-only; removing a pin requires naming the fingerprint being replaced, so
  the tool cannot be used to wave away an unexpected certificate change.
- `gemini_client_cert_list` and `gemini_client_cert_update` tools make a
  capsule that replies status 60 reachable. The fetch path only ever looked up
  an existing client certificate and nothing generated one, so the model
  retried, got 60 again, and there was no supported way forward. A status-60
  result now also carries the next step, so the tools are discoverable at the
  moment they are needed. Creation is never automatic: a client certificate is
  a persistent pseudonymous identity attached to every in-scope request, so
  minting one because a server asked would let any capsule make the user
  identifiable. The scope is the URL that failed and everything below it,
  creation refuses to replace an identity whose private key is unrecoverable,
  and removal must name the fingerprint it destroys.

### Security

- A Gemini client certificate is no longer attached to requests outside its
  scope. Scope matching ran on the raw request path, so a certificate scoped to
  `/app` was sent with a request for `/app/../secret` — which the server
  resolves outside that scope — and a hostile capsule needed only to publish
  such a link to make the user's identity leak. Paths (including `%2e`-encoded
  dot segments) are now normalized before any scope decision.
- Two client certificates minted for the same host within one second no longer
  share a key pair. Certificate files were named from the host and a
  whole-second timestamp, so the second write destroyed the first identity's
  private key unrecoverably and left it reporting a fingerprint no server would
  ever present. Filenames are now unique per identity and a residual collision
  fails rather than truncating a key.
- Server-controlled text is stripped of control characters before it reaches
  the model. Gopher menu titles, selectors and hosts, Gemini text and gemtext
  bodies, and every status-meta string (input prompts, error and certificate
  messages) could previously carry ANSI/OSC escape sequences; only the Gopher
  text path was filtered. The latin-1 decode fallback could also synthesise C1
  control characters from high bytes.
- A sensitive `input` answer no longer reaches the logs. When the URL built
  from `url` plus the answer failed validation, the returned and logged
  pydantic error embedded the tail of the offending value — so the end of a
  password answered to a status-11 prompt was written to the log file.
- An allowlist that names no hosts (`" , "`, or `"$A,$B"` with empty shell
  interpolations) is now a startup error instead of silently meaning "no
  restriction at all". The same misconfiguration on ports already failed
  closed, so the two knobs behaved oppositely. The library API changed with it:
  an explicitly empty allowlist passed to a client constructor —
  `GopherClient(allowed_hosts=[])` or `GeminiClient(allowed_hosts=[])` — used to
  mean allow-all and now denies every host. Only `None` (the default) means "no
  restriction".
- DNS resolution runs on its own bounded thread pool. A cancelled lookup leaves
  its worker parked in the resolver, so a batch naming tarpit hosts could pin
  every thread in the event loop's shared executor and stall unrelated fetches
  on both protocols long past their deadlines.

### Fixed

- The `mcp` dependency is capped below 2.x, so `pip install gopher-mcp` yields
  a server that starts. mcp 2.x renamed `FastMCP` to `MCPServer`, so the
  unbounded `mcp>=1.0.0` resolved to a release this code cannot import against.
  CI never saw it, because `uv sync --locked` installs the locked 1.x; a user
  installing from PyPI got an immediate `ModuleNotFoundError`. Lifting the cap
  means migrating to the 2.x API.
- An empty value for an optional path setting is read as unset rather than as
  the current directory. `GOPHER_MCP_LOG_FILE_PATH=` — the natural way to write
  "leave this at the default", and how the shipped `config/example.env` had it
  — became `Path(".")`, which logging then tried to open as a file, so copying
  the example config stopped the server from starting.
- `GEMINI_DENIED_MIME_TYPES` in its documented comma-separated form crashed the
  server at startup: the field's annotation made pydantic-settings JSON-decode
  the value before the parsing validator could run. All three list-valued
  variables now accept both the comma-separated and JSON-array spellings.
- The Gemini request timeout is one budget for the whole exchange. It was
  applied independently to DNS, the handshake, the send and the read — and
  again to the `robots.txt` probe — so an adversarial server could hold a tool
  call for many times the configured value.
- TOFU trust-store persistence no longer runs on the event loop. A
  cross-process lock, a full store re-read and two `fsync` calls ran inline on
  every first contact with a host, stalling all in-flight requests; a wedged
  lock holder in another instance froze the process indefinitely. The lock wait
  is now bounded.
- An oversized `robots.txt` is truncated and parsed as RFC 9309 expects. Under
  Gemini's fail-closed policy it previously made an entire capsule permanently
  unreachable while re-downloading the file on every request.
- A bare two-digit Gemini failure status (`51`, valid per the ABNF for 4x/5x/6x
  replies) is no longer reported as a malformed response, which told the model
  the server misbehaved instead of that the page was missing.
- A menu item's type character survives the round trip into `next_url`. A `?`
  type turned a link into a search against the root selector, and a `#` type
  discarded the selector entirely.
- Gemtext links resolve against the request URL. Relative links are the norm in
  gemtext, so the model was handed targets it could not fetch.
- An SSRF-blocked target reports as blocked rather than as an unretrievable
  `robots.txt` that suggests turning robots checking off, and a connect timeout
  reports as a timeout rather than as a TLS failure.
- Neither transport can now return a truncated body as complete, or discard a
  complete response as a timeout, when a response lands exactly on the size cap.
- Gemini fails over across resolved addresses instead of trying only the first,
  so a dual-homed capsule whose first address is down is still reachable.
- A per-host `robots.txt` lock can no longer be swept while coroutines are
  still queued on it, which let two requests fetch the same policy at once.
- Extra `#` characters in a gemtext heading stay part of the heading text,
  bare-CR gemtext is normalised, the Gemini URL length cap no longer counts the
  CRLF against the spec's 1024 bytes, and text beginning `BM`, `MZ` or `ID3` is
  no longer classified as binary and withheld from the model.

### Changed

- **Per-host rate limiting and the concurrency cap are now on by default.**
  `GOPHER_REQUESTS_PER_MINUTE` and `GEMINI_REQUESTS_PER_MINUTE` now default to
  `60` (one request per second, per host) instead of `0`, and
  `GOPHER_MAX_CONCURRENT_REQUESTS` / `GEMINI_MAX_CONCURRENT_REQUESTS` to `5`
  instead of `0`. Both settings shipped in 0.4.0 and defaulted to
  off/unlimited through 0.5.1, so this is a change of default rather than a new
  feature — and it changes the throughput of every existing deployment without
  any configuration edit. Requests to the same host are paced, so a batch aimed
  at a single server is spaced out rather than parallel; batching across
  several hosts is where the speedup now comes from. Set all four variables to
  `0` to restore the 0.5.x behaviour.
- A short, malformed Gopher menu line now yields an info item instead of being
  dropped, so tool output visibly changes. A line with fewer than four
  tab-separated fields that begins with `i` and carries text — a bare
  `iBanner text`, common on real menus — becomes an info item with an empty
  selector, host and `nextUrl` and port `0`; any other short line is still
  discarded. `items` lists are therefore longer than before, which shifts item
  counts and where `GOPHER_MAX_MENU_ITEMS` truncation falls.
- A cache TTL of `0` disables caching, matching the "0 means off" convention of
  the neighbouring settings, instead of storing entries that expire before they
  can ever be served. A port outside 1-65535 in an allowlist is a startup error
  rather than a configuration that rejects every request at fetch time.
- The `gopher_fetch` and `gemini_fetch` tool descriptions now state how to
  submit a type-7 search, what batching does and does not parallelise, and that
  fetched content is untrusted third-party data.
- `ErrorResult` and `GeminiErrorResult` are one model; `GeminiErrorResult`
  remains as an alias. The split had already caused drift — Gopher errors could
  not carry the integer fields Gemini errors use.
- The Docker image is built on `python:3.13-slim` instead of `python:3.14-slim`,
  which was outside the tested matrix, and CI now builds and smoke-tests the
  image on every pull request — nothing did before, so breakage reached users
  first. Dependabot is pinned to patch bumps of the base image so it cannot
  reopen that gap.
- Release-pipeline changes: `pip-audit` is advisory in the pull-request and
  release paths, with a nightly audit that files a tracking issue, so an
  advisory published against a pinned dependency no longer turns unrelated
  pull requests red or blocks a release. The GitHub Release is created only
  after the PyPI upload succeeds, closing a window in which a declined approval
  left a public release advertising a version PyPI could not serve.

### Removed

- Helpers that no production code called: `guess_mime_type`,
  `format_gopher_url`, `sanitize_selector` (whose hardcoded 255-character cap
  contradicted the client's configurable 1024-character limit),
  `validate_gemini_url_components`, and `TOFUManager.cleanup_expired` /
  `ClientCertificateManager.cleanup_expired`. `sanitize_display_text` and
  `resolve_gemini_reference` are now exported from `gopher_mcp.utils`.
- Uncalled computed members of the result models, which raise `AttributeError`
  if read: `GeminiMimeType.is_image`, `.is_audio`, `.is_video`,
  `.is_application`, `.supports_charset()` and `.get_file_extension()`;
  `GemtextLink.is_external`; and `GemtextDocument.link_count`, `.has_headings`,
  `.line_count`, `.content_summary`, `.heading_hierarchy` and `.text_content`.
  None of them were ever serialized into `model_dump()`, so **MCP tool output
  is unchanged and no tool user is affected** — only code importing
  `gopher_mcp.models` directly.
- The `allowed_hosts` keyword parameter of `ssrf.validate_target`; passing it
  now raises `TypeError`. It duplicated a check the clients already perform in
  `_validate_security`, against a set normalized once at construction, and only
  the duplicate had test coverage. The `GOPHER_ALLOWED_HOSTS` /
  `GEMINI_ALLOWED_HOSTS` settings are unaffected.
- Embedders using the library directly should note that
  `ClientCertificateManager` now names certificate files by a random `key_id`
  rather than by subject, rolls a failed store write back instead of leaving
  the registry and the disk disagreeing, and raises when a private key survives
  its removal. `docs/migration-guide.md` covers these.

## [0.5.1] - 2026-06-22

### Security

- Upgraded runtime dependencies to clear the advisories that `pip-audit` was
  reporting against the 0.5.0 dependency set:
  - `starlette` 1.2.1 → 1.3.1 (CVE-2026-54283, CVE-2026-54282)
  - `cryptography` 48.0.0 → 48.0.1 (GHSA-537c-gmf6-5ccf)
  - `pydantic-settings` 2.12.0 → 2.14.2 (GHSA-4xgf-cpjx-pc3j)
  - `msgpack` 1.1.2 → 1.2.1 (GHSA-6v7p-g79w-8964)

### Changed

- Bumped CI workflow actions: `actions/checkout` 6 → 7 and
  `softprops/action-gh-release` 3.0.0 → 3.0.1. These affect the release/CI
  pipeline only and do not change the published package.

## [0.5.0] - 2026-06-11

### Security

- A malicious Gemini server can no longer hang the client with an unbounded
  status-44 (SLOW_DOWN) backoff. The server-supplied wait is now sanitized and
  clamped (a non-finite value such as `inf` is rejected/capped), so a single
  `44 inf` response can no longer make every later fetch to that host sleep
  forever while holding a concurrency-semaphore slot.
- The Gemini TLS close handshake is now time-bounded, so a peer that withholds
  `close_notify` can no longer tack the OS TCP timeout onto each request after
  the read deadline has already been met.

### Fixed

- Gopher menu items using the hURL web-link convention (a `URL:<target>`
  selector, typically on a type-`h` item) now expose the real destination as
  `next_url` instead of a `gopher://` URL pointing back at the gopher host, so
  web/gemini links on real-world menus are followable.
- Gopher text-mode un-dot-stuffing (`..` → `.`) is now applied only when the
  RFC 1436 `.` terminator is actually present. An unframed document (no
  terminator) is returned verbatim, so a literal leading `..` is no longer
  corrupted to `.`.
- A server-side Gemini protocol fault (missing CRLF, over-long meta, bad status
  line, empty response) now returns a distinct `PROTOCOL_ERROR` instead of
  `INVALID_REQUEST`, so the model is told the server misbehaved rather than that
  its own URL was malformed.
- A spec-valid comma-separated `lang` parameter (e.g. `lang=en,fr`) is no longer
  rejected; rejecting it previously discarded the whole MIME type, including the
  declared charset, producing mojibake or gemtext misclassification.
- A stray unprefixed `GOPHER` / `GEMINI` / `SERVER` environment variable set by
  unrelated tooling no longer crashes startup (it was misread as the nested
  config object).

### Changed

- Gemini binary success responses now return metadata only (size + detected
  MIME type) as a new `binary` result kind, instead of base64-inlining the full
  body into the model's context. This matches the Gopher binary path and the
  server's documented "binary bodies are returned as metadata only" contract; a
  1 MB body previously shipped ~1.4M base64 characters. Re-fetch the resource
  directly if the raw bytes are needed.
- Gemtext preformat (code-block) content lines no longer repeat a per-line
  metadata dict (plus duplicated `alt_text`/`language`); block-level metadata is
  kept on the opening ` ``` ` toggle line only. This roughly thirded the
  serialized size of code blocks sent to the model. Attribute access is
  unchanged; only the serialized output is leaner.
- The Gopher menu parser now stops once the item cap (`max_menu_items`) is
  reached instead of building the entire directory before slicing, so a 1 MB
  directory no longer materialises tens of thousands of model objects to keep a
  small slice. Truncation is still flagged on the result.
- Client-certificate Gemini requests now reuse a per-certificate TLS client
  (and its SSL context) instead of rebuilding it on every request, so the system
  CA bundle load and cert/key PEM reads — blocking work that ran on the event
  loop — happen once per certificate rather than per fetch.
- Release/CI hygiene: `prepare-release.py` now bumps the version with an anchored
  match (no longer corrupting `target-version` / `python_version` / `minversion`
  in `pyproject.toml`) and also updates `server.json`; GitHub release notes no
  longer drop the last line of each changelog section; all CI/release/publish
  jobs run `uv sync --locked` so a stale lockfile fails loudly; the
  manual-publish workflow no longer offers a no-op `pypi` target; Dependabot now
  covers the Docker base image; and the docs site redeploys on `src/**` changes
  so the mkdocstrings API reference can't drift.

## [0.4.3] - 2026-06-10

### Security

- The Gopher menu parser now stops at the RFC 1436 `.` terminator, so data a
  server appends after the terminator is no longer parsed into navigable items.
  The terminator check now also tolerates trailing whitespace (a `". "` line),
  so a non-conformant server can't slip later items past what reads as the end.
- Client certificates are now scoped on path-segment boundaries: a certificate
  for `/api` is no longer sent to a sibling path such as `/api_admin`, closing
  an identity-scope leak.
- A blocked SSRF target no longer echoes the resolved internal IP back to the
  caller (it is logged server-side only), so the error can't be used to map
  internal network topology.
- The Gemini request send is now bounded by the request deadline (the receive
  side already was), so a peer that completes the handshake then stops reading
  can't pin the request until the OS TCP timeout.

### Fixed

- A Gemini status-20 response with an absent/unparseable MIME now defaults to
  `text/gemini` (per the spec) instead of being content-sniffed and
  misclassified as binary; genuine binary content is still detected by
  signature.
- Client-certificate scope lookup now normalizes the host (case / trailing
  dot), matching TOFU and the SSRF/allowlist paths, so a host variant no longer
  silently misses a stored client identity.
- The client-certificate common name is now parsed via the cryptography
  library, so a CN containing an escaped comma is no longer truncated (which
  made the certificate unfindable on disk and silently unusable).
- IPv6 literal hosts are now bracketed in every constructed `gopher://` and
  `gemini://` URL (menu `nextUrl`, the URL formatters, the Gemini request line
  and the display/log helper), so the address colons no longer collide with the
  port separator and break re-parsing.
- A Gopher menu item with a numeric but out-of-range port (>65535) now degrades
  to the default port 70 instead of failing validation and dropping the whole
  item.
- The Gopher client no longer caches error responses, so a transient failure is
  no longer served stale for the cache TTL (matching the Gemini client).
- Response cache keys are now case-insensitive in the hostname, so the same
  resource requested with a different host case shares one cache entry.
- `GopherURL` rejects an empty host at the model boundary (symmetry with
  `GeminiURL`).

### Changed

- Documentation: corrected the API reference (fresh connection per request, no
  pooling), removed the non-existent `GOPHER_HTTP_HOST`/`GOPHER_HTTP_PORT` env
  vars (host/port are `--host`/`--port` CLI flags), and documented that the
  HTTP transports are unauthenticated and the Docker image binds `0.0.0.0:8000`
  by default.

- Supply-chain hygiene: added a `.dockerignore` (keeps `.git`/local `.env` out
  of the Docker build context), SHA-pinned the third-party GitHub Actions, and
  raised the `cryptography` floor to `>=43.0.0`.

## [0.4.2] - 2026-06-09

### Security

- Move the Gemini TLS transport to native asyncio (`asyncio.open_connection`
  with `ssl=`), so connect, handshake and every read are genuinely cancellable:
  a slow-loris or stalled peer is now cut off at the request deadline instead of
  parking a worker thread on a blocking `recv`. The previous design ran blocking
  socket I/O on a thread pool shared with DNS resolution (the SSRF guard for both
  protocols), so a handful of slow Gemini reads could stall DNS for every request
  and escalate one slow server into a whole-server denial of service.
- Stop leaking a Gemini status-11 (`SENSITIVE_INPUT`) answer: the percent-encoded
  query is no longer written to logs, reflected back to the model via
  `requestInfo`, or retained in a cache key.
- Reject not-yet-valid certificates on TOFU first use by default (previously
  pinned with only a warning unless `reject_expired` was set).
- Reject empty and self-referential Gemini redirects (`INVALID_REDIRECT`) so a
  malformed `3x` response cannot drive an unbounded client re-fetch loop.

### Added

- `GOPHER_MAX_MENU_ITEMS` (default 1000): caps the number of Gopher menu items
  returned to the model, mirroring the existing text/gemtext character cap.
- Optional positive port allowlist (`GOPHER_ALLOWED_PORTS` /
  `GEMINI_ALLOWED_PORTS`) to close the arbitrary-port port-scanning gap left by
  the dangerous-ports denylist.

### Changed

- Apply the `max_rendered_chars` cap to `text/gemini` responses (previously only
  `text/*`), so a large gemtext page no longer floods the model context; both
  gemtext and menu results now carry a `truncated` flag.
- Drop the over-strict hardcoded TLS 1.2 cipher allow-list in favour of Python's
  secure defaults, improving interop with conforming Gemini servers.
- De-duplicate the two batch-fetch tools (`gopher_batch_fetch` /
  `gemini_batch_fetch`) onto a single shared implementation so the batch
  error/contract behaviour has one source of truth (no behaviour change).

### Removed

- The unused `http`/`aiohttp` optional dependency, the never-read
  `development_mode` setting, and the test-only `create_tls_client` factory.
- The `GeminiGemtextResult.summary`, `.plain_text` and `.structured_content`
  helper properties: they were never serialized by `model_dump()` so the MCP
  tools never exposed them (dead LLM-facing API). The parsed `document` and
  `raw_content` carry the same information.

### Fixed

- Correct the LLM-facing server instructions, `gopher_fetch` parameter
  description, and AI Assistant Guide to reference the real serialized
  `next_url` menu field (not the `nextUrl`/`url` names that never appear in the
  output).
- Sync `server.json` to the released version and replace placeholder
  author/maintainer/copyright metadata with the real maintainer.

## [0.4.1] - 2026-06-08

### Added

- Serialization-contract tests that pin the public result models' `model_dump()`
  key sets, guarding the documented response shape against silent drift.

### Changed

- Made the published documentation site the single source of truth: consolidated
  six overlapping release/PyPI/testing docs into one `development/releasing`
  guide, surfaced the previously-orphaned Configuration and Architecture pages in
  the nav, added a general Troubleshooting page, and corrected the docs against
  the v0.4.0 source — all four MCP tools (plus the `gemini_fetch` `input`
  parameter and the batch-fetch tools) and PyPI install are now documented,
  server/logging environment variables carry the `GOPHER_MCP_` prefix, TOFU and
  certificate paths point to `~/.gemini`, and the Gemini specification is
  standardized to v0.24.1.
- Added an auto-generated Data Models reference page (via mkdocstrings) rendered
  directly from the Pydantic models, replacing the hand-written response-type
  interfaces in the API reference so they can no longer drift from the code.
- Enabled markdownlint on the `docs/` tree in pre-commit/CI.

### Removed

- Deleted the duplicate `wiki-content/` documentation tree (its unique
  general/Claude Desktop troubleshooting and per-OS config paths were migrated
  into `docs/`) and dropped the internal Gemini planning drafts (project
  timeline, API contracts, security architecture) from the public site.

### Fixed

- Removed fabricated `GEMINI_TLS_*`, `DEBUG_COMPONENTS`, and `MCP_SERVER_*`
  environment variables and stale single-tool / source-only / Pituophis /
  `tools.py` / `GopherMCPServer` claims from the documentation, and corrected the
  documented response-model fields to match the code.
- Corrected the documentation code examples to access the real serialized
  response keys (`title`, `text`/`bytes`, `note`, `new_url`, and the nested
  `error` object), so the examples run without raising `KeyError`.

## [0.4.0] - 2026-06-08

### Security

- Block CGNAT (`100.64.0.0/10`) and deprecated IPv6 site-local (`fec0::/10`) in
  the SSRF guard, with a `not is_global` catch-all so new non-public ranges are
  denied by default. Reject all C0 control characters (and raw spaces) in Gemini
  URLs and the full C0 range in Gopher selectors, so no unescaped control bytes
  can reach a remote server.
- Disabling TOFU now logs a prominent warning (it leaves Gemini connections
  unauthenticated under CERT_NONE TLS); a certificate already expired on first
  use is pinned but flagged; and a status-11 input answer is no longer logged.
- Bound DNS resolution by the request deadline in both clients, so a hostname
  pointing at a tarpit nameserver can no longer stall a worker (or tie up an
  event-loop executor thread) far past `timeout_seconds`.
- TOFU trust store hardening: certificate fingerprints are canonicalized (a pin
  pasted in the `openssl`/browser colon-uppercase form now matches the wire
  digest); cross-process writes take an advisory lock and merge with the on-disk
  store so two server instances can't silently drop each other's pins; and the
  store write is `fsync`'d for crash durability.
- Optional `GEMINI_TOFU_REJECT_EXPIRED` fails closed on a certificate outside
  its validity window (`notBefore` is enforced on first use), reported with a
  distinct `CERTIFICATE_EXPIRED` code rather than a misleading "certificate
  changed".
- Gopher URL parsing fails closed on percent-decoded control characters in the
  selector/search at parse time, not only via the client's re-check.
- Defensive fetch-error paths return a generic message to the model instead of
  echoing the raw internal exception string (full detail is still logged).
- Report a missing / unobtainable server certificate as a distinct
  `CERTIFICATE_UNVERIFIED` result rather than the misleading `CERTIFICATE_CHANGED`
  ("does not match"), since there is no certificate to compare against.

### Added

- Optional `input` argument to `gemini_fetch` that percent-encodes a status-10/11
  answer into the query string (no hand-built query strings; secrets not logged).
- Per-host outbound rate limiting (`GOPHER_/GEMINI_REQUESTS_PER_MINUTE`, default
  off) that also honours a Gemini status-44 SLOW_DOWN backoff.
- Opt-in Gemini MIME content filter (`GEMINI_DENIED_MIME_TYPES`, supports
  `type/*` wildcards).
- `GEMINI_TOFU_REJECT_EXPIRED` (default off) to fail closed on a Gemini
  certificate outside its validity window.
- `GOPHER_MAX_CONCURRENT_REQUESTS` / `GEMINI_MAX_CONCURRENT_REQUESTS` (default 0 =
  unlimited) — an opt-in cap on simultaneous in-flight fetches, a coarse bound on
  concurrent sockets/memory complementary to the per-host rate limit.
- LLM-facing text render cap (`GOPHER_/GEMINI_MAX_RENDERED_CHARS`, default 50000)
  with a `truncated` flag, distinct from the network byte cap.
- Rich tool input schemas (descriptions + examples), `readOnlyHint`/
  `openWorldHint` tool annotations, a FastMCP `instructions` string, and
  `--host`/`--port` flags for the sse/streamable-http transports.

### Changed

- Gemini gemtext results no longer serialize the always-null per-line fields,
  cutting a typical document's JSON by ~40%.
- Gopher `ErrorResult` carries a `kind="error"` discriminator; Gemini
  certificate results carry the 60/61/62 subcode (61/62 are rejections, not
  prompts); relative Gemini redirects are resolved to absolute URLs.
- `__version__` is single-sourced from the package metadata.
- The batch fetch tools return one error per input URL on an over-limit or
  client-setup failure, keeping responses index-aligned with the request list.
- The per-host rate limiter sweeps hosts whose reservation has elapsed, so a
  long-lived server no longer accumulates state for every distinct host visited.
- Collapsed the duplicate client-manager singleton so `cleanup()` fully resets
  it and the next call builds a fresh manager.

### Fixed

- Gopher text responses strip the RFC 1436 `.` terminator and un-dot-stuff
  lines; known-binary item types route to the binary processor instead of being
  decoded as text; interactive types (telnet/tn3270/CSO) short-circuit; the
  type-7 search field is only sent to search servers; menus split on CR/CRLF/LF;
  and generated `nextUrl`s percent-encode the selector.
- The Gemini 1024-byte request cap now covers the whole CRLF-terminated line.
- Replaced the deprecated in-coroutine `asyncio.get_event_loop()` with
  `get_running_loop()`.

## [0.3.0] - 2026-06-07

### Security

- Pin the SSRF-validated IP address for the actual connection so a hostname can
  no longer be re-resolved to an internal or rebinding address between the
  validation check and the connect (Gopher and Gemini).
- Add a denylist of dangerous service ports (SSH, SMTP, Redis, etc.) as
  defense-in-depth.
- Close the socket on every TLS connection/handshake failure (previously leaked
  file descriptors under repeated failures).
- Normalize TOFU trust-store host keys so a casing/trailing-dot variant cannot
  establish a second pin, and reject a non-valid TOFU result (fail closed).
- Fail closed on a corrupt client-certificate registry, and write the trust
  store, certificate registry, and private keys owner-only.
- Scan dependencies with `pip-audit` in CI (replacing the deprecated
  `safety check`) and pin the PyPI publish action to a commit SHA.

### Added

- Range constraints on model port/size fields and scheme-based classification of
  gemtext links (relative links are internal, not external).

### Changed

- Fetch tools now return structured error results instead of raising, so invalid
  input, batch limits, and client-setup failures no longer surface as raw tool
  errors.
- Server settings are read under the `GOPHER_MCP_` environment prefix (e.g.
  `GOPHER_MCP_LOG_LEVEL`) so common ambient variables no longer leak into
  configuration. **Update any `LOG_LEVEL`/`DEVELOPMENT_MODE`/`LOG_FILE_PATH`
  env vars to the prefixed names.**
- `--mount-path` is now rejected for transports that ignore it (was silently
  dropped for stdio/streamable-http).
- Per-request URL/query logging moved to DEBUG.
- Client connections are released on shutdown.

### Fixed

- Reject explicit invalid or zero ports in Gopher/Gemini URLs instead of
  silently coercing them to the default.
- Percent-decode Gopher selectors to their on-wire form.
- Parse gemtext on CRLF/LF only and preserve preformatted lines verbatim.
- Stop double-wrapping the Gemini response parser's own validation errors.
- Enforce the project's full ruff ruleset (it was silently shadowed by a stray
  config file) and clear a transitive `jaraco-context` advisory.

## [0.2.2] - 2025-01-16

### Added

- Enhanced test coverage with additional test cases

### Changed

- Updated dependency versions for consistency across tools
- Updated ruff version in pre-commit configuration
- Improved code formatting and style consistency
- Enhanced documentation with comprehensive GitHub Wiki content

### Fixed

- Fixed dependency version conflicts
- Fixed code formatting issues
- Fixed trailing whitespace in markdown and yaml files

## [0.2.1] - 2025-01-18

### Added

#### Gemini Protocol Support (NEW)

- Complete Gemini protocol v0.16.1 implementation
- `gemini_fetch` MCP tool for Gemini protocol access
- TLS 1.2+ client with mandatory SNI support
- TOFU (Trust-on-First-Use) certificate validation system
- Client certificate generation and management
- Gemtext parser with structured output for AI consumption
- Dual-protocol MCP server supporting both Gopher and Gemini
- Protocol-isolated caching systems
- Comprehensive security features and host allowlists

#### Security Features

- TOFU certificate fingerprint storage and validation
- Automatic client certificate generation per hostname/path scope
- TLS security configuration with minimum version enforcement
- Certificate validation error handling and recovery
- Host allowlists for both protocols
- Enhanced input validation and sanitization
- Security policy enforcement for connections

#### Documentation

- Comprehensive Gemini support documentation
- API reference for both protocols
- AI assistant usage guide
- Advanced features documentation
- Configuration reference with all environment variables
- Troubleshooting guide and FAQ
- Integration examples and best practices
- Migration guide for existing users

#### Testing and Quality Assurance

- Comprehensive test suite for Gemini protocol
- Security and penetration testing
- Performance and load testing
- Integration tests for dual-protocol operation
- Test coverage >95% for all new features

### Changed

- Updated package metadata to reflect dual-protocol support
- Enhanced error handling and logging across both protocols
- Improved configuration validation and defaults
- Updated dependencies to include cryptography for certificate management

### Security

- TLS 1.2+ enforcement for all Gemini connections
- Certificate fingerprint validation with TOFU
- Secure client certificate generation and storage
- Enhanced input validation for both protocols
- Connection timeout and size limit enforcement

## [0.1.0] - 2025-01-XX

### Added

- Initial release of Gopher MCP server
- Support for basic Gopher protocol operations
- MCP tool: `gopher.fetch` for retrieving Gopher resources
- Support for Gopher item types: 0 (text), 1 (menu), 7 (search), 9 (binary)
- Structured JSON responses optimized for LLM consumption
- Async implementation with connection pooling
- In-memory LRU cache with configurable TTL
- Comprehensive error handling and logging
- Security features: timeouts, size limits, input sanitization
- Cross-platform support (Linux, macOS, Windows)
- Both stdio and HTTP transport support
- Extensive test suite with >90% coverage
- Complete documentation and examples

[Unreleased]: https://github.com/cameronrye/gopher-mcp/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.3...v0.5.0
[0.4.3]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.3.0...v0.4.1
[0.4.0]: https://github.com/cameronrye/gopher-mcp/releases/tag/v0.4.1
[0.3.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/cameronrye/gopher-mcp/releases/tag/v0.1.0
