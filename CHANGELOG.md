# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Block CGNAT (`100.64.0.0/10`) and deprecated IPv6 site-local (`fec0::/10`) in
  the SSRF guard, with a `not is_global` catch-all so new non-public ranges are
  denied by default. Reject all C0 control characters (and raw spaces) in Gemini
  URLs and the full C0 range in Gopher selectors, so no unescaped control bytes
  can reach a remote server.
- Disabling TOFU now logs a prominent warning (it leaves Gemini connections
  unauthenticated under CERT_NONE TLS); a certificate already expired on first
  use is pinned but flagged; and a status-11 input answer is no longer logged.

### Added

- Optional `input` argument to `gemini_fetch` that percent-encodes a status-10/11
  answer into the query string (no hand-built query strings; secrets not logged).
- Per-host outbound rate limiting (`GOPHER_/GEMINI_REQUESTS_PER_MINUTE`, default
  off) that also honours a Gemini status-44 SLOW_DOWN backoff.
- Opt-in Gemini MIME content filter (`GEMINI_DENIED_MIME_TYPES`, supports
  `type/*` wildcards).
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

[Unreleased]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/cameronrye/gopher-mcp/releases/tag/v0.1.0
