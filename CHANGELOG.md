# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- A continuation window no longer invents markup. `parse_gemtext` classified
  from the top of whatever string it was handed, but a window resumes
  mid-document, so a cut inside a ` ``` ` block read the block's contents as live
  markup: a fenced `=> url text` line came back as a resolved link in
  `document.links`, the closing fence was read as an opening toggle, and every
  line after it was typed wrong. `partial_line` stays false on both windows, so
  nothing flagged it, and it needs no hostile capsule -- any page with a code
  block longer than the render cap does it. The tail of an over-long line had
  the same defect from the other side: 0.9.0 declines to parse the window that
  _ends_ mid-line, but the window that _starts_ mid-line was still parsed from
  the top, so a `=>` just past the cap boundary arrived as a complete link to a
  target the capsule never offered. Both are one missing bit of state, and both
  contradicted what `models.py` and the API reference promise the model on every
  call.
- The install docs no longer deny that the container image exists. README,
  `docs/installation.md` and `docs/troubleshooting.md` all said registry
  publishing was still to come and that the release on PyPI predated
  `--version`; both stopped being true when 0.9.0 published the image to
  `ghcr.io/cameronrye/gopher-mcp` and shipped the flag. The PyPI long
  description is immutable per release, so 0.9.0's copy keeps the old text and
  only a new release replaces it.
- The changelog's own pre-0.3 tail. `0.2.1` and `0.2.2` carried January dates
  that were 8-11 months off their tags, `0.1.0` was dated `2025-01-XX`, and the
  link definitions for `0.1.0` and `0.4.0` pointed at `v0.1.0` and `v0.4.1` tags
  in ways that 404'd or misnamed the release. Neither version was ever tagged,
  which is now stated rather than papered over.

### Changed

- The container image is built for `linux/arm64` as well as `linux/amd64`. The
  0.9.0 image was a single-platform amd64 manifest because the publish step
  declared no platforms at all, so every Apple Silicon and ARM-server user ran
  it under emulation.
- The release path runs the image before pushing it. `publish-image` built and
  pushed in one step and never started the container; the image it pushes is
  also not the one CI smoke-tested, because the Dockerfile resolves its
  dependency closure fresh from PyPI at build time. It now builds the host
  architecture, asserts `--version` matches the tag being released and that the
  registry annotation is present, and only then builds and pushes both
  platforms.
- `server.json` advertises the container as an `oci` package, so the MCP
  registry lists it alongside the PyPI one. This needed three things that were
  all missing: the image carries the `io.modelcontextprotocol.server.name`
  annotation the registry verifies ownership with, `publish-registry` now waits
  for `publish-image` instead of racing it, and `scripts/prepare-release.py`
  bumps the version inside the image tag -- the registry forbids a `version`
  key on an OCI package, so the tag is the version, and nothing was moving it.
- The container base image moves to `python:3.14-slim`, the top of the test
  matrix, now that the 3.14 legs have been green on CI.
- The minimum-versions CI job runs on Python 3.14 as well as 3.11. The declared
  floors are not one set of versions: `mcp` markers its pydantic requirement by
  interpreter, so `pydantic==2.11.0` is not merely untested on 3.14, it is
  unsolvable there.
- **Dependabot can propose a base-image minor bump again**, reversing what 0.9.0
  said. The old rule ignored both major and minor updates for `python`, and the
  Dockerfile's tag has no patch component -- so no update of any kind could ever
  be proposed and the entry was structurally inert rather than conservative.
  Major stays ignored. What now protects the "base image must stay on an
  interpreter the matrix covers" rule is review rather than configuration, so
  check the matrix before merging one.
- `pyproject.toml` records what should end the `mcp<2` hold instead of leaving
  it open-ended, and notes that the first condition has already fired:
  `llama-index-tools-mcp` requires `mcp>=2` as of 0.5.0, so installing it beside
  this package is already unsatisfiable. It also corrects which advisory sets
  the `mcp>=1.28.1` floor -- the DNS-rebinding one was fixed in 1.23.0 and is
  not it -- and stops citing the container as the deployment the SDK's rebinding
  default protects, since the container's own `CMD` disables that check.
- The release checklist no longer tells you to run a bare `pre-commit
autoupdate`. Two hook revs deliberately track `uv.lock`, and a bare
  `autoupdate` bumps them out from under it; the checklist now scopes the
  update to the revs with no lockfile counterpart.
- `docs/development/repository-setup.md` describes the branch protection that
  actually exists -- the `main` ruleset lists the admin role as an
  always-bypass actor -- and carries the API calls to re-check every claim on
  the page.

## [0.9.0] - 2026-09-03

Everything below applies the findings of a full review of the code, the
packaging and the documentation site. Each finding was independently verified
against the code, or by running it, before it was applied.

This is the largest set of breaking changes the project has made. Almost all of
them are in what a tool result looks like, so a client that reads only `kind`
and the fields it needs will be unaffected, while one that switches on error
codes, parses timestamps, or reads gemtext line internals will need the
migration notes below. See the
[Migration Guide](https://cameronrye.github.io/gopher-mcp/migration-guide/).

### Added

- `gopher_fetch` and `gemini_fetch` take an `offset`, and a truncated result
  carries `next_offset`, plus `total_items` for a menu and `total_chars` for a
  body. Truncation used to be a dead end: the result said it had been cut and
  offered no way to read the rest, so anything past the configured cap was
  unreachable. A menu larger than the cap reports a null total rather than
  parsing the whole directory to count it, which is the work the cap exists to
  avoid.
- Both fetch tools advertise a real `outputSchema`, a discriminated union over
  the `kind` values, instead of an unconstrained object.
- `gopher_fetch` takes the search terms directly, so a Veronica-2 query
  containing `#`, `+` or non-ASCII is no longer mangled on its way to the
  server. This is what `input` already does for Gemini.
- The batch fetch tools accept `refresh`, which the server instructions already
  told the model to use.
- The server registers MCP resources and prompts: the effective fetch policy is
  readable over the protocol, and the navigation and safety rules are available
  as prompts rather than only as prose in the instructions.
- The HTTP transports answer `GET /health`, and the container declares a
  `HEALTHCHECK` against it.
- `partial_line` on a gemtext result, for the one case where a window cannot end
  on a line boundary because a single line is longer than the render limit.
- `gopher-mcp --version`, and help text that mentions Gemini and points at the
  environment variables everything else is configured through. The version was
  previously readable only by importing the package, which neither the
  recommended `uvx` install nor the container can do.
- A redirect result says whether the target leaves the capsule or the `gemini`
  scheme, and states the five-hop limit the caller has to enforce, since this
  server deliberately does not follow redirects itself.
- A warning when a client certificate is sent over TLS 1.2, which transmits it
  where a passive observer can read it.
- Python 3.14 is covered by the CI matrix on Linux, macOS and Windows, and
  advertised on PyPI.
- The MCP registry manifest is published on a tagged release, and the container
  image is published to `ghcr.io/cameronrye/gopher-mcp` with a signed
  provenance attestation. The manifest had been gated on every tag for four
  releases and uploaded on none of them.

### Changed

- **Breaking:** a gemtext line is serialized once. Each parsed line used to
  appear two and three times, as `content`, inside a nested per-type object
  that repeated the same text under another name, and again in a
  whole-document `rawContent` field that is now gone. A 487-byte page produced
  3,526 bytes of JSON. If you read `line.heading.text`, read `line.text`.
- **Breaking:** timestamps in tool results are ISO-8601 UTC strings rather than
  epoch seconds. `cached_at` and `request_info.timestamp` previously disagreed
  about what a timestamp looks like, and the certificate tools already used
  ISO. Stored values keep their epoch format, so `tofu.json` is unchanged.
- **Breaking:** a Gemini 4x/5x failure reports the capsule's own text in
  `error.meta`, and `error.message` now carries only this server's explanation.
  A hostile capsule could previously answer `51 <instruction>` and have its
  text read as guidance from us. If you display `error.message`, you may want
  `error.meta` as well, clearly marked as remote content.
- **Breaking:** a tool failure sets the protocol's `isError` flag. A blocked,
  DNS-failed or rejected call used to look like a success to any host that
  reads the flag rather than the body. The documented no-raise contract is
  unchanged: no tool raises.
- **Breaking:** info lines in a Gopher menu no longer carry a fabricated
  `nextUrl`. The host and port a server parks in those fields never pointed
  anywhere, and on a real Floodgap menu those unfollowable URLs were roughly
  two thirds of the payload the model was told to navigate by.
- **Breaking:** a hostname is IDNA-encoded when it is normalized, so the
  Unicode and punycode spellings of an internationalized host share one trust
  pin, one certificate scope and one robots policy. A link using the Unicode
  spelling of an already-pinned capsule previously got a fresh trust-on-first-
  use, letting an on-path certificate through with only a "trusted on first
  use" note instead of `CERTIFICATE_CHANGED`. Any pin stored under a Unicode
  spelling is re-pinned under the encoded form on the next visit.
- **Breaking:** trust pins and client identities default to this project's own
  data directory rather than `~/.gemini/`, which belongs to Google's Gemini CLI
  and holds the `settings.json` a user edits to register this server. Writing
  generically named state there, and tightening its mode, reached into another
  product's configuration. An existing `~/.gemini/tofu.json` or `~/.gemini/certs/`
  keeps being read and written where it is, permanently, because relocating a
  trust store silently would either lose every pin or make a pinned host look
  unpinned.
- **Breaking:** Gopher text results report LF line endings. The carriage return
  of a CRLF-served page carried no information and spent an escaped `\r` on
  every line of the JSON handed to the model.
- **Breaking:** the dev, test and docs extras are PEP 735 dependency groups.
  `pip install gopher-mcp[dev]` was a published, versioned install surface that
  nothing documented and nobody supported. Contributors use
  `uv sync --all-groups`.
- **Breaking:** `task.py` is removed. The task table existed twice, in that
  file and in taskipy, they had already drifted, and nothing compared them.
  `uv run task <cmd>` is the one way to run project tasks, and `make <cmd>`
  delegates to it.
- A mistyped or wrong-scheme URL answers with the one sentence that corrects
  it, and names the sibling tool, instead of a pydantic dump of internals.
- An invalid environment value fails with one line naming the variable, the
  value and the accepted range, instead of a 26-line traceback pointing at an
  internal field. It no longer takes `--help` down with it.
- Both fetch tools accept an uppercase or mixed-case scheme and canonicalise
  it, which RFC 3986 requires. The tools previously rejected URLs their own
  parsers accept, including gemtext links this server had just handed back.
- The robots refusal no longer tells the model to switch robots checking off,
  and the documentation no longer points at a Geminispace search engine without
  saying that it refuses automated queries.
- All four fetch tools say in their own description that what comes back is
  untrusted remote content, rather than relying on server instructions a client
  may drop.
- Settings are handed to the clients as a whole rather than one keyword at a
  time, so a new setting cannot be added to the configuration and silently
  forgotten at the call site.
- The coverage gate rises from 85% to 95%, matching the suite's measured 97%.
  The old gate had roughly 350 statements of slack for a regression to hide in.
- Dependabot updates `uv.lock` on its weekly run. The Python entry was on the
  `pip` ecosystem, which can only edit version floors and structurally cannot
  touch the lockfile every CI job installs, so scheduled lock updates never
  arrived and only security advisories moved it.
- A release tag is refused unless the full nine-way CI matrix passed on that
  exact commit. Releases previously re-tested Ubuntu on 3.11 only, so a
  Windows-only regression could publish behind a green Release run.

### Fixed

- A gemtext line longer than the render limit no longer costs its whole window.
  There was no complete line to end the window on, so the window was returned
  empty while `next_offset` advanced past it, which put those characters beyond
  reach at every later offset: a caller following the documented continuation
  loop assembled a fragment and was told nothing was wrong. On a real capsule
  page at a 200-character limit, more than half the windows were affected. The
  span now arrives as a plain `text` line with `partial_line: true`, so it is
  never parsed as half a link and the characters still reach the caller.
- **Breaking:** `--host` on the HTTP transports makes the server reachable
  under that host. The container binds `0.0.0.0` precisely to be reachable and
  answered `421 Misdirected Request` to every client that was not on localhost,
  because the SDK fixes a loopback-only Host allowlist when it is constructed.
  A new repeatable `--allowed-host` narrows the accepted headers rather than
  turning the check off.
- **Breaking:** a trust or certificate store that cannot be written reports
  `CERTIFICATE_STORE_UNAVAILABLE` and names the setting to check. The raw
  `OSError` used to reach the robots probe's transport handler, so a read-only
  disk was described to the model as a transient network failure whose stated
  remedy was to retry, which could never succeed.
- **Breaking:** a trust-on-first-use pin that fails to persist is no longer
  trusted in memory. The retry after a storage error was served as "already
  trusted" on a pin written nowhere, so a restart re-opened the first-use
  window that error exists to deny.
- **Breaking:** Gopher item types `P` and `:` are handled as binary rather than
  decoded as latin-1 and handed to the model as up to 50,000 characters of
  mojibake.
- **Breaking:** one damaged byte no longer re-reads a whole UTF-8 page as
  latin-1. Only the bad bytes become U+FFFD, and pervasively 8-bit bodies still
  decode as latin-1. The mojibake was previously cached for the full TTL.
- **Breaking:** a latin-1 server's menu links are followable again. A non-ASCII
  selector byte is preserved through `nextUrl` and put back on the wire
  unchanged, instead of being re-encoded as UTF-8 into a selector the server
  has never heard of.
- **Breaking:** a `#fragment` is stripped from a Gemini URL rather than
  refused, so a link or redirect target this server emitted is one it will
  follow.
- **Breaking:** an internationalized Gemini host is sent as its punycode form
  and non-ASCII path bytes are percent-encoded, so the request line conforms to
  RFC 3986 and matches the name the TLS layer already sends.
- **Breaking:** an empty answer to a status 10 or 11 prompt is preserved.
  `gemini_fetch(url, input="")` reached the capsule as the bare URL it had just
  answered with a 10, so a prompt that accepts an empty value could not be
  answered.
- **Breaking:** a Gopher menu item whose type field holds a control byte is
  reported as an info line, so a raw escape can no longer reach the model
  through the one field that was never sanitized.
- Failing over to the next resolved address now happens when the first one
  black-holes the connection, not only when it refuses it. The advertised
  dual-homed fail-over previously helped only in the rare refused case.
- A batch of URLs on one unreachable host costs one `robots.txt` probe rather
  than one per URL. The lock that exists to make it a single request re-checked
  the policy cache but not the failure backoff, so every waiter paid a fresh
  connect timeout, serially, inside that lock.
- A first fetch to a cold host no longer sleeps a full rate-limit interval, or
  resolves the same name twice, because the `robots.txt` probe and the fetch it
  guards each paid separately for one user request.
- A long status 44 backoff answers with a structured "retry in N seconds"
  instead of sleeping up to five minutes inside the tool call while holding a
  batch concurrency slot.
- A certificate whose validity starts up to five minutes ahead of our clock is
  pinned on first contact rather than refused. Capsules mint self-signed
  certificates at startup, so seconds of clock skew used to fail the connection
  and leave nothing pinned to recover with. Beyond that window the refusal is
  now `CERTIFICATE_NOT_YET_VALID` rather than being reported as an expiry.
- Server-supplied text is no longer stripped of characters that are visible.
  The sanitizer removed every space separator except U+0020 and every format
  character, so a non-breaking space and the CJK ideographic space were deleted
  outright, fusing the words either side, and a family emoji came back as three
  separate people. Controls, surrogates, private-use and separator characters
  are still removed.
- A failed connection no longer echoes the resolved IP address back to the
  caller, which the transport's own comment already claimed it did not.
- ANSI escapes are stripped from the Gemini redirect target, MIME type and
  malformed-status message, the three server-controlled strings that still
  reached the model raw.
- The Gemini cache is keyed on the request that actually goes on the wire, so
  a bare host, a trailing slash, an explicit `:1965` and an encoded dot segment
  stop re-fetching identical content into separate entries.
- A Gopher timeout names the configured deadline rather than the fraction of it
  left when the transport was called, which read as an 18-digit number.
- `NOT_FETCHABLE` results echo the request they refused, like every other
  Gopher error.
- A `?query` on a non-type-7 Gopher URL is still dropped, but the response says
  so rather than returning an unrelated page silently.
- Standard-library and MCP SDK log records go through the same pipeline as
  ours, and the HTTP transports route uvicorn's startup and access logs through
  it too, so a stream configured as JSON is JSON on every line, the optional
  log file mirrors those records, and nothing reaches stdout. For a stdio
  server, stdout carries the protocol stream.
- The `py.typed` marker ships. The `Typing :: Typed` classifier has promised it
  since 0.1.0, and without it every downstream type checker skipped this
  package as untyped, discarding its strict-typing work at the import boundary.
- The documentation site's architecture diagram renders. It had shipped as a
  wall of literal `graph TB` text for a year, because the superfence format was
  quoted as a string, and a strict build never noticed.
- The documentation site no longer loads a script from `polyfill.io`, a domain
  seized after a supply-chain attack, nor a megabyte of MathJax for pages that
  contain no mathematics.
- The release scripts enforce the same coverage gate as the project, rather
  than a threshold retired several releases ago, and `scripts/verify-setup.py`
  no longer fails on a workflow that was deleted a year ago.
- Documentation that described a different program: the Gemini error tables,
  the Gopher item-type coverage, the response-type lists, the configuration
  reference, a troubleshooting example the code cannot produce, and a dozen
  references to an example host whose domain no longer exists.

### Security

- **Breaking:** the `mcp` floor rises to 1.28.1 and `cryptography` to 50.0.0.
  The old floors admitted SDK versions with DNS-rebinding protection off by
  default, the one protection the HTTP transports rely on, and the
  minimum-versions job proved that set importable while never proving it safe.

## [0.8.0] - 2026-09-02

### Added

- `GOPHER_ROBOTS_FAILURE_BACKOFF_SECONDS` and
  `GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS` (default `60`, range `0`-`3600`) make
  the robots.txt failure backoff configurable. 0.7.0 introduced the backoff as a
  fixed 60 seconds, which is a judgement call rather than a fact about either
  protocol: the right value depends on how often the hosts you fetch from are
  down and, on Gemini, on how long you are willing to be refused while one is.
  Setting `0` restores the pre-0.7.0 behaviour of re-probing on the very next
  request. The ceiling is an hour — past that the failure path would be caching
  the outage rather than retrying it, which is the one thing it is documented
  not to do.

### Changed

- **Breaking:** a fetch refused because `robots.txt` could not be _retrieved_
  now returns a new error code, `ROBOTS_UNAVAILABLE`, instead of
  `BLOCKED_BY_ROBOTS`. The latter now means only what it says: the host
  published a policy and that policy forbids this path.

  0.7.0 routed both outcomes to `BLOCKED_BY_ROBOTS`, because RFC 9309 §2.3.1.4
  makes an unretrievable policy deny. That is correct as a _decision_ and wrong
  as a _name_ — a capsule that never answered has not disallowed anything, and
  reporting it as a robots block claims the operator wrote a rule they did not
  write. The two also want opposite handling: a `Disallow` is permanent and
  should not be retried, while an unretrievable policy is transient and should
  be. That is precisely the distinction an error code exists to carry, and it is
  the same one `CERTIFICATE_STORE_UNAVAILABLE` already draws beside
  `CERTIFICATE_UNVERIFIED` — "the check could not happen" is a different answer
  from "the check says no", not a variant of it.

  If you switch on `error["code"]`, match both codes wherever you previously
  matched `BLOCKED_BY_ROBOTS`, and retry only `ROBOTS_UNAVAILABLE`. Gopher fails
  open and so does not currently emit the new code; the branch exists there so
  that flipping that choice cannot silently start claiming disallows that never
  happened.

- **Breaking:** a hostname that cannot be resolved now returns `DNS_ERROR`
  instead of `BLOCKED`. `BLOCKED` is documented as "the SSRF guard refused the
  target (loopback, private range, or a disallowed port)", and a name that does
  not resolve was never refused — nothing was evaluated, because there was no
  address to evaluate. A typo'd hostname was therefore reported as a security
  block, sending the reader to hunt for an allowlist problem that did not exist.

  `HostResolutionError` subclasses `SSRFError`, so any handler catching the base
  still catches it and the fail-closed behaviour is unchanged; only the reported
  code differs. A genuine policy refusal is still `BLOCKED`, and there is now a
  test pinning that `DNS_ERROR` does not swallow it — that distinction is a
  security signal and must not blur.

- A robots refusal now says _why_. When the policy could not be retrieved, the
  message names the underlying failure — `the connection timed out`, `the TLS
connection failed`, `the reply was not a valid Gemini response`, or the status
  by name (`41 SERVER UNAVAILABLE`, not `status 41`) — and says plainly that
  this is not a rule the capsule wrote.

  The remedy offered in that case has also changed. It previously suggested
  `GEMINI_RESPECT_ROBOTS_TXT=false`, which is the right advice for a real
  `Disallow` and the wrong advice here: disabling robots checking does not make
  an unreachable capsule reachable, it just exchanges this error for the
  transport one — while leaving a safety control switched off. It now says to
  retry instead.

- **Breaking:** three more error codes now describe what actually happened.
  These were found by auditing every error path after the robots work, on the
  principle that a code naming a plausible neighbour is worse than no code:

  - A response over `GEMINI_MAX_RESPONSE_SIZE`, or one that hit the cap without
    the peer closing, returned `TLS_ERROR` "TLS connection failed". A size cap is
    this server's own policy, not a handshake fault. It is now `FETCH_ERROR`, and
    the message names the cap instead of being discarded.
  - A refused, unreachable or reset TCP connection returned `TLS_ERROR` too,
    sending the reader to inspect certificates for a connection that never
    reached a handshake. It is now `FETCH_ERROR` with the real reason. `TLS_ERROR`
    now means an actual `ssl.SSLError`. This completes the correction 0.6.1 began
    for connect timeouts.
  - A `3x` redirect whose target will not parse (`31 //[::1`) escaped as a bare
    `ValueError` into the `INVALID_REQUEST` arm — telling the model to fix a URL
    that was never wrong. It is now `INVALID_REDIRECT`, alongside the empty-target
    and redirect-loop cases it belongs with.

  `GeminiConnectionError` and `GeminiResponseTooLargeError` both subclass
  `TLSConnectionError`, so handlers catching the base are unaffected.

### Fixed

- **A truncated gemtext page could hand back a link URL the server never sent.**
  The LLM-facing character cap sliced the raw gemtext mid-line and then parsed
  it, so a cut landing inside a `=> gemini://host/some/long/path Title` line
  produced a _complete_ link whose target was the surviving prefix — a fabricated
  URL the caller could not distinguish from a real one, and would follow. The cut
  is now taken at the last complete line, which is the same rule the `robots.txt`
  reader already applied for the same reason.

- **A Gemini query string could be reflected back in link URLs.** A query is the
  user's INPUT response and may be a secret (status 11 `SENSITIVE_INPUT`), which
  is why it is kept out of logs, error URLs and `requestInfo`. But RFC 3986
  §5.3 has an empty or fragment-only reference inherit the base's query, so a
  capsule serving `=> ` or `=> #anchor` on a page fetched with a password in the
  query got that password handed straight back in a resolved link URL. The base's
  query is now dropped before resolution. A reference supplying its own query
  (`?x`) replaces rather than inherits and is unaffected.

- **A hostname that fails to resolve no longer reports as an SSRF block.** See
  `DNS_ERROR` above.

- **`GOPHER_TIMEOUT_SECONDS` is now the single deadline it is documented to be.**
  `docs/configuration.md` and `config/example.env` both promise it covers "DNS,
  connect, send and read", but the DNS lookup and the transport were each handed
  the full value, and with robots checking on by default the probe spent two more
  full-length phases of its own — so one call could occupy four multiples of the
  configured deadline against a server answering each phase just under the limit.
  All four phases now draw down one budget, matching the Gemini client.

- A Gemini `44 SLOW_DOWN` during a robots probe no longer costs two penalties.
  The status was folded into the generic failure backoff on top of the
  rate-limiter penalty it already triggers, so being asked to wait five seconds
  refused every request for sixty. The capsule's own retry period is now used as
  the robots backoff, since it already said when it would be ready. That period
  is attacker-controlled, so it is clamped by the same bound the rate limiter
  applies rather than being trusted as given.

## [0.7.0] - 2026-09-01

### Changed

- **Breaking:** `robots.txt` is now honoured by **default** on both protocols.
  `GOPHER_RESPECT_ROBOTS_TXT` and `GEMINI_RESPECT_ROBOTS_TXT` both default to
  `true`; set either to `false` to restore the previous behaviour. 0.6.0 shipped
  this opt-in on the grounds that it costs a round-trip per host, but the policy
  is cached per host for 24 hours, so the cost is one probe per host rather than
  one per fetch — and defaulting to ignoring an operator's stated policy is not
  a reasonable default for a tool an LLM drives unattended. A blocked fetch
  returns the existing `BLOCKED_BY_ROBOTS` error code.

  Two consequences worth planning for. A fetch that previously succeeded can now
  be refused, if the host disallows it. And because Gemini fails **closed** per
  RFC 9309 §2.3.1.4, a capsule whose `robots.txt` cannot be retrieved at all —
  including during a plain network or TLS outage — is now reported as
  `BLOCKED_BY_ROBOTS` rather than as a transport error. Gopher fails open, since
  it has no status codes to distinguish an absent policy from an unreachable one.

  A `User-agent: gopher-mcp` group is honoured by name on both protocols, so an
  operator can exclude this tool specifically without excluding anything else.

### Fixed

- An interactive Gopher item (telnet `8`, tn3270 `T`, CSO `2`) no longer
  resolves DNS and opens a TCP connection before being refused. These items have
  no Gopher-fetchable body and are answered from the item type alone, but the
  robots gate ran ahead of that check, so enabling robots by default would have
  had every such item probe `/robots.txt` on a host it never needed to contact.
- An unreachable `robots.txt` is no longer re-probed on every single request. A
  failed probe is deliberately not cached for the full policy TTL — a transient
  outage should be retried — but with no backoff at all, every request to a host
  whose `robots.txt` could not be retrieved paid a fresh connect timeout,
  including requests that would otherwise have been served entirely from the
  response cache (the gate runs ahead of that lookup so a `Disallow` also
  withholds previously cached content). On Gopher the gate then failed open and
  proceeded anyway, so the wait bought nothing. Such a host is now left alone for
  60 seconds before being probed again, which keeps the retry without the
  per-request cost.

## [0.6.1] - 2026-09-01

### Fixed

- Two declared dependency floors admitted versions this package cannot import.
  `pydantic-settings` is now `>=2.7.0` (`config.py` imports `NoDecode`, added in
  2.7.0) and `mcp` is now `>=1.10.0` (the first release whose `FastMCP.tool()`
  accepts `title=`, which every tool here passes). Both failures were
  resolver-invisible: `pip install gopher-mcp` into an environment already
  holding an older pin succeeded, `pip check` reported no broken requirements,
  and the crash arrived at import. The `mcp<2` cap added in 0.6.0 gave no cover
  for the `pydantic-settings` case — mcp itself only requires `>=2.5.2`, so
  2.5.2–2.6.1 resolved cleanly alongside the newest permitted mcp. A fresh
  install into a clean environment was never affected, since every such path
  resolves highest.
- The server advertised the MCP SDK's version as its own in the `initialize`
  handshake — clients saw `gopher-mcp 1.29.1`, so a bug reported against that
  number named the wrong project. FastMCP accepts no `version` argument and its
  lowlevel server falls back to the SDK's own version when none is set; the
  package version is now set explicitly.

### Removed

- **Breaking (CLI):** the `--mount-path` flag. It never worked: FastMCP rewrote
  only the endpoint advertised over the SSE stream, while the Starlette routes
  stayed unprefixed, so a client that honoured the advertised
  `/<mount>/messages/` POSTed to a 404 and the session was dead on arrival.
  Passing it now fails with an unrecognized-argument error rather than
  producing a silently broken transport. `--transport sse` without it is
  unaffected.

### Added

- A `minimum-versions` CI job resolves the declared floors with
  `uv sync --resolution lowest-direct`, then imports the package, runs the
  console script and runs the suite against them. Every other install in the
  repo resolves highest — `uv sync --locked` pins the lockfile and the Docker
  image pip-installs into a clean image — so nothing had ever executed this
  package against the floors it publishes, which is how both floors above
  drifted unnoticed. The resolution step alone would not have caught them; the
  job has to run the code.

## [0.6.0] - 2026-09-01

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

## [0.2.2] - 2025-11-15

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

## [0.2.1] - 2025-09-18

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

## [0.1.0] - 2025-09-16

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

<!--
Link definitions. 0.1.0 and 0.4.0 were never tagged -- `git ls-remote --tags`
starts at v0.2.0 -- so neither can have a `compare/vX...vY` range of its own and
both definitions used to 404. They point instead at the history that actually
carries their changes: everything up to the first tag for 0.1.0, and the range
ending at v0.4.1 for 0.4.0, which shipped them together. Dates come from the tag
they were cut at (`git log -1 --format=%ai vX.Y.Z`); the pre-0.3 tail carried
January placeholders that were wrong by 8-11 months.
-->

[Unreleased]: https://github.com/cameronrye/gopher-mcp/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.3...v0.5.0
[0.4.3]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/cameronrye/gopher-mcp/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.3.0...v0.4.1
[0.4.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.3.0...v0.4.1
[0.3.0]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.0...v0.2.1
[0.1.0]: https://github.com/cameronrye/gopher-mcp/commits/v0.2.0
