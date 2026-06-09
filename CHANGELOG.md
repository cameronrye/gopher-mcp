# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- The Gopher menu parser now stops at the RFC 1436 `.` terminator, so data a
  server appends after the terminator is no longer parsed into navigable items.

### Fixed

- A Gemini status-20 response with an absent/unparseable MIME now defaults to
  `text/gemini` (per the spec) instead of being content-sniffed and
  misclassified as binary; genuine binary content is still detected by
  signature.
- Client-certificate scope lookup now normalizes the host (case / trailing
  dot), matching TOFU and the SSRF/allowlist paths, so a host variant no longer
  silently misses a stored client identity.
- `GopherURL` rejects an empty host at the model boundary (symmetry with
  `GeminiURL`).

### Changed

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

[Unreleased]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/cameronrye/gopher-mcp/releases/tag/v0.1.0
