# Gopher & Gemini MCP Server

<!-- mcp-name: io.github.cameronrye/gopher-mcp -->

[![CI](https://github.com/cameronrye/gopher-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/cameronrye/gopher-mcp/actions/workflows/ci.yml)
[![Documentation](https://github.com/cameronrye/gopher-mcp/actions/workflows/docs.yml/badge.svg)](https://github.com/cameronrye/gopher-mcp/actions/workflows/docs.yml)
[![PyPI version](https://badge.fury.io/py/gopher-mcp.svg)](https://badge.fury.io/py/gopher-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Downloads](https://pepy.tech/badge/gopher-mcp)](https://pepy.tech/project/gopher-mcp)

A modern, cross-platform [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI assistants to
browse and interact with both [Gopher protocol](<https://en.wikipedia.org/wiki/Gopher_(protocol)>) and
[Gemini protocol](https://geminiprotocol.net/) resources safely and efficiently.

## Overview

The Gopher & Gemini MCP Server bridges vintage and modern alternative internet protocols with AI assistants, allowing LLMs like
Claude to explore the unique content and communities that thrive on both Gopherspace and Geminispace. Built with FastMCP and
modern Python practices, it provides secure, efficient gateways to these distinctive internet protocols.

**Key Benefits:**

- **Discover alternative internet content** - Access unique resources on both Gopher and Gemini protocols
- **Safe exploration** - Built-in security safeguards, TLS encryption, and content filtering
- **Modern implementation** - Uses FastMCP framework with async/await patterns
- **Developer-friendly** - Comprehensive testing, type hints, and documentation
- **Advanced security** - TOFU certificate validation and client certificate support for Gemini

## Features

- **Dual Protocol Support**: `gopher_fetch` and `gemini_fetch` tools for comprehensive protocol coverage
- **Comprehensive Gopher Support**: Every standard RFC 1436 item type — menus
  (`1`) and Index-Search servers (`7`) as structured menus, text (`0`), HTML
  (`h`), info (`i`) and error (`3`) lines as text, the fourteen binary types as
  metadata only, and the three interactive ones (`2`, `8`, `T`) refused without
  opening a connection. An unknown type is read as text, best-effort, and an
  hURL `URL:<target>` selector is followed to the destination the server
  actually stated
- **Full Gemini Implementation**: Native gemtext parsing, TLS security, and status code handling
- **Advanced Security**: TOFU certificate validation with dedicated inspection and recovery tools, scoped client certificates, and secure TLS connections
- **Safety First**: Built-in timeouts, size limits, input sanitization, SSRF protection, per-host rate limiting, and host allowlists
- **LLM-Optimized**: Returns structured JSON responses designed for AI consumption
- **Cross-Platform**: Works seamlessly on Windows, macOS, and Linux
- **Modern Development**: Full type checking, linting, testing, and CI/CD pipeline
- **High Performance**: Async/await patterns with intelligent caching — and cached results say so, with a per-request `refresh` bypass
- **Continuable Reads**: A menu or page cut at the render limit reports where it stops, so `offset` reads the rest instead of leaving a partial view

## Documentation

Complete documentation is available at **[cameronrye.github.io/gopher-mcp](https://cameronrye.github.io/gopher-mcp)**

- [Installation Guide](https://cameronrye.github.io/gopher-mcp/installation/)
- [Configuration Guide](https://cameronrye.github.io/gopher-mcp/configuration/)
- [API Reference](https://cameronrye.github.io/gopher-mcp/api-reference/)
- [AI Assistant Guide](https://cameronrye.github.io/gopher-mcp/ai-assistant-guide/)
- [Migration Guide](https://cameronrye.github.io/gopher-mcp/migration-guide/) and
  [Changelog](https://cameronrye.github.io/gopher-mcp/changelog/) — what changed,
  and what an upgrade asks of you

## Quick Start

### Prerequisites

- **Python 3.11+** - [Download here](https://www.python.org/downloads/)
- **uv package manager** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation

#### Option 1: Zero-install with uvx (Recommended)

No clone, no checkout — [uv](https://docs.astral.sh/uv/) fetches and runs the
published package on demand:

```bash
uvx gopher-mcp
```

#### Option 2: PyPI Installation

```bash
# Install from PyPI
pip install gopher-mcp

# Or with uv
uv add gopher-mcp
```

#### Option 3: Development Installation

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Set up development environment
./scripts/dev-setup.sh  # Unix/macOS
# or
scripts\dev-setup.bat   # Windows

# Run the server
uv run task serve
```

#### Option 4: Docker

Tagged releases publish a slim, non-root image to
`ghcr.io/cameronrye/gopher-mcp`, tagged with the release version plus `:latest`
for stable (non-pre-release) tags:

```bash
# The default CMD serves streamable-http on 0.0.0.0:8000
docker run --rm -p 8000:8000 \
  -v gopher-mcp-state:/home/app/.local/share/gopher-mcp \
  ghcr.io/cameronrye/gopher-mcp:latest

# Or run over stdio, e.g. for an MCP client
docker run --rm -i --no-healthcheck \
  -v gopher-mcp-state:/home/app/.local/share/gopher-mcp \
  ghcr.io/cameronrye/gopher-mcp:latest --transport stdio
```

Registry publishing is new, so the first image lands with the next tagged
release. Until then — or to run a modified tree — the repository ships the
`Dockerfile` it is built from: `docker build -t gopher-mcp .`

**Mount a volume, or Gemini trust is meaningless.** Without one, the TOFU pins
and the client certificates' private keys die with the container, so every start
re-arms blind trust-on-first-use — the pin is the only thing that authenticates
a Gemini capsule — and destroys any identity you minted, whose private key
cannot be recovered.

**Mount it at that exact path.** `/home/app/.local/share/gopher-mcp` is where
the server writes (`tofu.json` and `certs/`), and it is the one directory the
image pre-creates owned by the runtime user and mode `700` — which is what lets
a named volume come up writable instead of root-owned. Mounting anywhere else
persists an empty directory. `~/.gemini` is **not** the path: it is only a
read-in-place upgrade route for installs that pinned certificates before
gopher-mcp had a directory of its own, and it is honoured only when its store
file is already there, which it never is in a fresh image.

**Health checks.** The HTTP transports serve `GET /health`, which answers
`{"status": "ok", "version": "..."}` and nothing else — no configuration, no
allowlists, no store paths. It bypasses authorization by SDK design, which is
what makes it usable as a probe. The image's `HEALTHCHECK` polls it on the
hard-coded port `8000` to match the default `CMD`, so override the healthcheck
alongside `--port`, and pass `--no-healthcheck` when running stdio — a stdio
container serves no HTTP and would otherwise be reported unhealthy while working
perfectly.

> **Note:** the default `CMD` binds `0.0.0.0` so the container is reachable out
> of the box. A non-loopback `--host` also turns off FastMCP's DNS-rebinding
> `Host`/`Origin` check, matching what the SDK does when it is constructed with
> such a host — otherwise every client that was not on localhost got
> `421 Misdirected Request`. Keep the check on by naming the hostnames the
> deployment answers to with `--allowed-host NAME` (repeatable; a bare name
> matches any port). The HTTP transports are unauthenticated and have no TLS
> either — put the container behind a trusted reverse proxy, or use
> `--transport stdio`, before exposing it beyond your machine.

### MCP Client Integration

Every client below runs the server over **stdio** — no ports, no TLS, no
listening socket. The entry is the same three fields everywhere; only the file
and the top-level key change:

| Client         | Where the entry goes                                                                                                                                                                      | Top-level key     |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), `%APPDATA%\Claude\claude_desktop_config.json` (Windows), `~/.config/Claude/claude_desktop_config.json` (Linux) | `mcpServers`      |
| Claude Code    | `claude mcp add --scope user gopher -- uvx gopher-mcp`, or `.mcp.json` at the repository root for `--scope project`                                                                       | `mcpServers`      |
| Cursor         | `~/.cursor/mcp.json`, or `.cursor/mcp.json` for one project                                                                                                                               | `mcpServers`      |
| VS Code        | `.vscode/mcp.json` in the workspace, or **MCP: Open User Configuration**                                                                                                                  | `servers`         |
| Zed            | `settings.json` (**zed: open settings**)                                                                                                                                                  | `context_servers` |
| Windsurf       | `~/.codeium/windsurf/mcp_config.json`                                                                                                                                                     | `mcpServers`      |

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uvx",
      "args": ["gopher-mcp"]
    }
  }
}
```

That is the whole entry: every setting in [Configuration](#configuration) has a
working default, so add an `"env"` block only when you actually want to change
one. Installed with `pip` rather than `uvx`? Use `"command": "gopher-mcp"` and
`"args": []` instead.

The [Installation Guide](https://cameronrye.github.io/gopher-mcp/installation/#mcp-client-integration)
has the exact JSON for each client, including the two that do not use the
`mcpServers` key.

If a GUI client reports that the server failed to start, it is almost always
`PATH`: a GUI-launched application does not inherit your shell's, so `uvx` may
not be found. Use the absolute path (`which uvx`) as `"command"`, and restart
the application fully rather than reloading the window.

<details>
<summary>Alternative: run from a local checkout</summary>

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": ["--directory", "/path/to/gopher-mcp", "run", "task", "serve"]
    }
  }
}
```

On Windows use the absolute path with escaped backslashes
(`C:\\path\\to\\gopher-mcp`).

</details>

## Usage

The server registers eight MCP tools:

| Tool                        | Purpose                                                         |
| --------------------------- | --------------------------------------------------------------- |
| `gopher_fetch`              | Fetch one Gopher resource                                       |
| `gemini_fetch`              | Fetch one Gemini resource                                       |
| `gopher_batch_fetch`        | Fetch several Gopher URLs at once (bounded concurrency, max 50) |
| `gemini_batch_fetch`        | Fetch several Gemini URLs at once (bounded concurrency, max 50) |
| `gemini_trust_list`         | Inspect the Gemini TOFU trust store (read-only)                 |
| `gemini_trust_update`       | Remove or re-pin one host's certificate (**destructive**)       |
| `gemini_client_cert_list`   | Inspect the stored Gemini client identities (read-only)         |
| `gemini_client_cert_update` | Create or remove one client identity (**destructive**)          |

The four fetch tools are annotated read-only and open-world. The four
certificate tools never touch the network, and each pair is split read from
write so a client can gate the destructive one on its own.

Alongside them the server exposes one resource, `gopher-mcp://policy`, which
renders the fetch policy this process is actually running with — the allowlists,
caps and robots settings a refusal is decided from, with the two store paths
reduced to `<configured>` / `<default>`. There is deliberately no tool that
edits it: a fetched page talked into widening an allowlist would have widened it
for every later fetch. Two prompts, **Explore a capsule or Gopher hole** and
**Summarize a gemlog or phlog**, package the navigation and safety rules as a
one-click starting point.

### `gopher_fetch` Tool

Fetches Gopher menus, text files, or metadata by URL with comprehensive error handling and security safeguards.

**Parameters:**

- `url` (string, required): Full Gopher URL (e.g., `gopher://gopher.floodgap.com/1/`)
- `search` (string, optional): Terms for a type-7 (Index-Search) selector. They are
  percent-encoded and sent as the query string, so pass the user's words raw — a
  query holding `#`, `+`, `&` or non-ASCII is truncated or mangled when written
  into the URL by hand. RFC 1436 gives only type 7 a query field, so leave it
  unset for every other item type
- `refresh` (boolean, optional, default `false`): Skip the cached copy and re-fetch from the server
- `offset` (integer, optional, default `0`): Continue a truncated result — pass the
  previous result's `next_offset`, which counts menu items for a menu

**Response Types:**

- **MenuResult** (`kind: "menu"`): For Gopher menus (type 1) and search results (type 7)
  - Structured menu items with type, title, selector, host and port, each with a
    `next_url` to follow. An empty `next_url` marks a display-only info line
- **TextResult** (`kind: "text"`): For text files (type 0)
  - Returns the text content with metadata
- **BinaryResult** (`kind: "binary"`): Metadata only for the binary item types
  (`4`, `5`, `6`, `9`, `g`, `I`, `d`, `s`, `;`, `p`, `P`, `:`, `M`, `<`)
  - Provides `bytes` and `mime_type` without downloading binary content
- **ErrorResult** (`kind: "error"`): For errors and unfetchable content
  - `error.code` and `error.message`; nothing was fetched. The interactive types
    (`2` CSO, `8` telnet, `T` tn3270) have no fetchable body at all and answer
    `NOT_FETCHABLE` without opening a connection

### `gemini_fetch` Tool

Fetches Gemini content with full TLS security, TOFU certificate validation, and native gemtext parsing.

**Parameters:**

- `url` (string, required): Full Gemini URL (e.g., `gemini://geminiprotocol.net/`)
- `input` (string, optional): Text to answer a Gemini input prompt (status 10/11); it is percent-encoded into the query string
- `refresh` (boolean, optional, default `false`): Skip the cached copy and re-fetch from the server
- `offset` (integer, optional, default `0`): Continue a truncated result — pass the
  previous result's `next_offset`, which counts characters for a page body

**Response Types:** seven, one per `kind`.

- **GeminiGemtextResult** (`kind: "gemtext"`): For gemtext content (`text/gemini`)
  - Parsed document in `document.lines` and `document.links`, whose `url` fields
    are already resolved. A line carries its own `type`, `content` and whatever
    the marker cannot say (`text`, `level`, `alt_text`, `language`); there is no
    nested per-line object and no whole-document `raw_content` in the payload
- **GeminiSuccessResult** (`kind: "success"`): For other **text** content types
  - Decoded text in `content`, with MIME type information
- **GeminiBinaryResult** (`kind: "binary"`): For binary content
  - Metadata only — `size` and the detected `mime_type`, never the bytes. A 1 MB
    body would be ~350k tokens of base64 the model cannot render anyway
- **GeminiInputResult** (`kind: "input"`): For input requests (status 1x)
  - The capsule's `prompt`, with `sensitive: true` on status 11. Answer it by
    calling again with `input=`, never by hand-building a query string
- **GeminiRedirectResult** (`kind: "redirect"`): For redirects (status 3x, where
  31 is permanent)
  - `new_url` is the target. Redirects are **not**
    followed for you, so the result also carries `cross_host` (the target
    belongs to a different party than the one you asked for) and `scheme`
    (anything but `gemini` leaves Geminispace and cannot be fetched with this
    tool). Follow at most five in a row and stop on a URL already seen
- **GeminiErrorResult** (`kind: "error"`): For errors (status 40-59), and for
  failures raised on this side of the wire — SSRF and allowlist refusals, a
  robots block, a certificate mismatch, a timeout
  - `error.code` and `error.message`, where `message` is written by this server.
    The capsule's own untrusted `META` text is kept apart in `error.meta`, so a
    hostile `51 <instruction>` cannot be read as this server's guidance. Where a
    status has a defined remedy — the whole temporary 4x family included — that
    remedy is in `error.next_step`
- **GeminiCertificateResult** (`kind: "certificate"`): For certificate statuses (60-69)
  - Certificate requirement information, plus a `next_step` written by this
    server (`message` is the capsule's own text). A certificate that already
    exists for the host/port/path scope is attached automatically and the fetch
    path never creates one, so retrying unchanged returns status 60 again;
    `gemini_client_cert_update` mints one for that scope, but only once the user
    has agreed to hold a persistent identity on that capsule.

`GeminiErrorResult` is an alias for the same `ErrorResult` model `gopher_fetch`
returns, not a separate type — its `error` object simply carries the extra
`status`, `temporary` and `meta` keys when the capsule actually answered.

Gemini results name the content length `size` where the Gopher results name the
same fact `bytes`. One concept, two wire names, kept apart only because renaming
either would break every existing consumer.

### Cached Results and `refresh`

Successful bodies are cached per protocol for a few minutes. A result that came
from the cache says so, so a replay is never mistaken for the current state of a
resource:

- `cached` — `true` when the result was replayed from the local cache
- `cached_at` — when that copy was actually fetched, as an ISO-8601 UTC
  timestamp (`2026-09-02T12:00:00+00:00`)
- `cache_age_seconds` — how old the copy was when it was returned

These appear only on the kinds that are actually cached (Gopher `menu`, `text`,
`binary`; Gemini `gemtext`, `success`, `binary`). Errors, redirects and
input/certificate prompts are never cached.

Pass `refresh: true` when the user wants the current state — it skips the cache
for that one call and still stores the fresh response. All four fetch tools take
it, the batch pair included.

### Truncated Results and `offset`

Menus and page bodies are capped before they reach the model
(`*_MAX_RENDERED_CHARS`, `GOPHER_MAX_MENU_ITEMS`), but a cap is not a dead end.
A result cut short sets `truncated: true` and says where to resume:

- `next_offset` — where the part that was cut begins, or `null` when there is
  nothing more
- `total_items` (Gopher `menu`) / `total_chars` (`text`, `success`, `gemtext`) —
  how big the whole resource is. `total_items` is `null` when the directory was
  larger than the render cap, because the total is not counted in that case

Call the same tool again with `offset` set to the previous `next_offset` and keep
going until `next_offset` comes back `null`. The unit is items for a menu and
**characters** for a body; `bytes` and `size` are byte counts and are never
offsets. For gemtext, a window ends on the last complete line, so consecutive
windows abut exactly and half a link never parses as a whole one.

Neither batch tool takes `offset`: one offset cannot mean anything sensible
across a list of different URLs. Continue a truncated batch item with the
single-URL tool, which is where `next_offset` is answerable.

### Gemini Trust-Store Tools

Gemini has no certificate authorities: the first certificate seen for a host is
pinned, and every later connection must present the same one. When a host reissues
its certificate — routine for self-signed certs, usually at expiry — the fetch
fails with `CERTIFICATE_CHANGED`. Two tools handle that without hand-editing the
trust store on disk — `$XDG_DATA_HOME/gopher-mcp/tofu.json`, falling back to
`~/.local/share/gopher-mcp/`, `~/Library/Application Support/gopher-mcp/` on
macOS and `%LOCALAPPDATA%\gopher-mcp\` on Windows, and overridable with
`GEMINI_TOFU_STORAGE_PATH`. An install that already has `~/.gemini/tofu.json`
keeps using it exactly where it is, permanently: moving pins would lose them or,
worse, make a pinned host look unpinned. The full rules are in
[Where Gemini state is stored](https://cameronrye.github.io/gopher-mcp/configuration/#where-gemini-state-is-stored).

- **`gemini_trust_list`** (read-only) reports what is pinned, optionally for one
  `host`: fingerprint, port, first/last seen and expiry as ISO-8601 UTC, plus a
  precomputed `expired` — an ended validity window makes a routine reissue the
  likely explanation for a changed fingerprint.
- **`gemini_trust_update`** (destructive) removes (`action: "remove"`) or
  replaces (`action: "pin"`) the pin of one named `host`. There is no wildcard.

A fingerprint change is also exactly what an active machine-in-the-middle attack
looks like, and the two are indistinguishable from the client. So a pin is only
ever changed after the user confirms the new certificate is expected — checked
against the operator or another device, never on the say-so of a fetched page. To
enforce that, `action: "remove"` requires the fingerprint **currently** pinned
(as reported by `gemini_trust_list`); a mismatch returns `FINGERPRINT_MISMATCH`
and changes nothing.

### Gemini Client-Identity Tools

A client certificate is the other half of Gemini's certificate story, and the
opposite direction: it is the identity **this server presents to a capsule**,
not the one a capsule presents to us. Capsules with accounts ask for it with
**status 60 (certificate required)**. The fetch path attaches a certificate that
already covers the requested scope but never creates one, so answering a 60 is
an explicit call:

- **`gemini_client_cert_list`** (read-only) reports the scopes that hold an
  identity — each as a ready-to-use scope URL with its fingerprint, validity
  window and whether it has expired. Never a private key or its location.
- **`gemini_client_cert_update`** (destructive) creates the identity for the
  scope of a named `gemini://` URL, or removes the one covering it.

The certificate covers that URL's path and everything below it, so
`gemini://host/app/page.gmi` covers one page, `gemini://host/app/` the section,
and `gemini://host/` the whole capsule. While it exists, every request in that
scope carries it, which is what lets the capsule link those visits — so it is
the user's decision, never a reaction to a page or `META` string asking for one.
Creation refuses to replace a certificate already covering the scope, because
the private key cannot be recovered, and `action: "remove"` requires the
fingerprint being destroyed, exactly as the trust tools require the pinned one.

### Example URLs to Try

#### Gopher Protocol

```bash
# Classic Gopher menu
gopher://gopher.floodgap.com/1/

# Gopher news and information
gopher://gopher.floodgap.com/1/gopher

# Search example (type 7)
gopher://gopher.floodgap.com/7/v2/vs

# Text file example
gopher://gopher.floodgap.com/0/gopher/welcome
```

#### Gemini Protocol

```bash
# Gemini protocol homepage
gemini://geminiprotocol.net/

# Gemini software directory
gemini://geminiprotocol.net/software/

# Example personal capsule
gemini://skyjake.fi/

# A large, browsable aggregator capsule
gemini://kennedy.gemi.dev/
```

Geminispace has no search engine this tool can drive. Kennedy and `tlgs.one` are
worth browsing, but both `Disallow: /search` in their `robots.txt`, so a search
URL on either comes back `BLOCKED_BY_ROBOTS`. That is a stop, not a setting to
change: the operators asked automated clients to stay off those paths.

### Example AI Interactions

Once configured, you can ask Claude:

**Gopher Exploration:**

- _"Browse the main Gopher menu at gopher.floodgap.com"_
- _"Search for 'python' on the Veronica-2 search server"_
- _"Show me the welcome text from Floodgap's Gopher server"_
- _"What's available in the Gopher community directory?"_

**Gemini Exploration:**

- _"Fetch the Gemini protocol homepage"_
- _"Show me the software directory on geminiprotocol.net"_
- _"Browse the latest posts from a gemlog"_
- _"What's the difference between Gopher and Gemini protocols?"_

## Development

### Task Runner

Every development command is a task in `[tool.taskipy.tasks]` (pyproject.toml),
which is the single definition of each one — there is no second table to keep in
sync. Run them the same way on every platform:

```bash
uv run task dev-setup     # install dependencies and pre-commit hooks
uv run task quality       # lint + typecheck + test
uv run task ci            # what CI runs: check + test-cov
uv run task help          # list every task (alias for `task --list`)
```

On Unix and macOS, `make <command>` is a thin catch-all onto the same table, and
bare `make` runs `help`. `uv run task help` is the authoritative list; the tasks
and the reasoning behind the ones that are not obvious are described in
[CONTRIBUTING.md](CONTRIBUTING.md#the-task-runner).

### Project Structure

```text
gopher-mcp/
├── src/gopher_mcp/          # Main package
│   ├── __init__.py          # Package initialization
│   ├── __main__.py          # CLI entry point (--transport/--host/--port/--allowed-host)
│   ├── server.py            # FastMCP server + the eight MCP tool definitions
│   ├── client_base.py       # Shared fetch scaffolding for both clients
│   ├── gopher_client.py     # Gopher protocol client
│   ├── gopher_transport.py  # Low-level Gopher transport
│   ├── gopher_parse.py      # Gopher URL and menu parsing
│   ├── gemini_client.py     # Gemini protocol client
│   ├── gemini_tls.py        # Gemini TLS connection handling
│   ├── gemini_parse.py      # Gemini URL and response parsing
│   ├── gemtext.py           # Gemtext document parsing
│   ├── mime.py              # MIME type detection and filtering
│   ├── tofu.py              # Trust-on-First-Use certificate store
│   ├── client_certs.py      # Gemini client certificate storage
│   ├── identity.py          # Trust/identity decision and wording helpers
│   ├── ssrf.py              # SSRF protection / address filtering
│   ├── ratelimit.py         # Per-host rate limiting
│   ├── robots.py            # robots.txt fetching and policy gate
│   ├── cache.py             # Shared TTL + LRU response cache
│   ├── config.py            # Pydantic settings models
│   ├── models.py            # Pydantic data models
│   ├── helpers.py           # Shared URL/IO/sanitization helpers
│   └── utils.py             # Backward-compatible facade re-exporting the above
├── tests/                   # Comprehensive test suite
├── docs/                    # MkDocs documentation
├── scripts/                 # Development scripts
├── config/                  # Example configuration (example.env)
├── .github/workflows/       # CI/CD pipelines
├── Dockerfile               # Slim, non-root container image
├── Makefile                 # Unix/macOS shortcut onto the taskipy tasks
├── server.json              # MCP registry manifest
└── pyproject.toml           # Modern Python project config
```

### Development Workflow

1. **Setup**: `uv run task dev-setup` - Install dependencies and pre-commit hooks
2. **Code**: Make your changes with full IDE support (type hints, linting)
3. **Quality**: `uv run task quality` - Run all quality checks (lint + typecheck + test)
4. **Test**: `uv run task test-cov` - Run tests with coverage reporting
5. **Commit**: Pre-commit hooks ensure code quality automatically

### Testing

```bash
# Run all tests
uv run task test

# Run with coverage
uv run task test-cov

# Run specific test types
uv run task test-unit
uv run task test-integration

# Run one file
uv run pytest tests/test_server.py
```

## Configuration

The server can be configured through environment variables for both protocols:

### Gopher Configuration

| Variable                         | Description                     | Default         | Example                |
| -------------------------------- | ------------------------------- | --------------- | ---------------------- |
| `GOPHER_MAX_RESPONSE_SIZE`       | Maximum response size in bytes  | `1048576` (1MB) | `2097152`              |
| `GOPHER_TIMEOUT_SECONDS`         | Request timeout in seconds      | `30`            | `60`                   |
| `GOPHER_CACHE_ENABLED`           | Enable response caching         | `true`          | `false`                |
| `GOPHER_CACHE_TTL_SECONDS`       | Cache TTL in seconds; `0` = off | `300`           | `600`                  |
| `GOPHER_MAX_CACHE_ENTRIES`       | Max cached entries (LRU)        | `1000`          | `2000`                 |
| `GOPHER_ALLOWED_HOSTS`           | Allowed hosts (list)            | unset (all)     | `example.com,test.com` |
| `GOPHER_ALLOWED_PORTS`           | Allowed ports (list)            | unset (any)     | `70`                   |
| `GOPHER_ALLOW_LOCAL_HOSTS`       | Permit loopback/private hosts   | `false`         | `true`                 |
| `GOPHER_REQUESTS_PER_MINUTE`     | Per-host request cap (0 = off)  | `60`            | `30`                   |
| `GOPHER_MAX_CONCURRENT_REQUESTS` | Simultaneous fetches (0 = off)  | `5`             | `2`                    |
| `GOPHER_RESPECT_ROBOTS_TXT`      | Honour `/robots.txt`            | `true`          | `false`                |

### Gemini Configuration

| Variable                         | Description                        | Default         | Example                |
| -------------------------------- | ---------------------------------- | --------------- | ---------------------- |
| `GEMINI_MAX_RESPONSE_SIZE`       | Maximum response size in bytes     | `1048576` (1MB) | `2097152`              |
| `GEMINI_TIMEOUT_SECONDS`         | Whole-fetch wire-time budget       | `30`            | `60`                   |
| `GEMINI_CACHE_ENABLED`           | Enable response caching            | `true`          | `false`                |
| `GEMINI_CACHE_TTL_SECONDS`       | Cache TTL in seconds; `0` = off    | `300`           | `600`                  |
| `GEMINI_MAX_CACHE_ENTRIES`       | Max cached entries (LRU)           | `1000`          | `2000`                 |
| `GEMINI_ALLOWED_HOSTS`           | Allowed hosts (list)               | unset (all)     | `example.org,test.org` |
| `GEMINI_ALLOWED_PORTS`           | Allowed ports (list)               | unset (any)     | `1965`                 |
| `GEMINI_ALLOW_LOCAL_HOSTS`       | Permit loopback/private hosts      | `false`         | `true`                 |
| `GEMINI_TOFU_ENABLED`            | Enable TOFU certificate validation | `true`          | `false`                |
| `GEMINI_CLIENT_CERTS_ENABLED`    | Store and attach client certs      | `true`          | `false`                |
| `GEMINI_REQUESTS_PER_MINUTE`     | Per-host request cap (0 = off)     | `60`            | `30`                   |
| `GEMINI_MAX_CONCURRENT_REQUESTS` | Simultaneous fetches (0 = off)     | `5`             | `2`                    |
| `GEMINI_RESPECT_ROBOTS_TXT`      | Honour `/robots.txt`               | `true`          | `false`                |

> **SSRF protection:** by default both tools reject targets that resolve to loopback,
> link-local (including cloud metadata `169.254.169.254`), or private/RFC1918 addresses.
> Set `GOPHER_ALLOW_LOCAL_HOSTS` / `GEMINI_ALLOW_LOCAL_HOSTS` to `true` only when you
> deliberately need to reach local hosts (e.g. testing a server on localhost).

**Timeouts.** `*_TIMEOUT_SECONDS` is one overall deadline per fetch, not a
per-phase timeout. For Gemini, DNS, connect and TLS handshake, the trust-store
write, send and read all draw down the same budget, and when robots checking is
enabled the `/robots.txt` probe spends from it too — so a slow host cannot spend
the full value on each step in turn.

**List-valued variables.** `*_ALLOWED_HOSTS`, `*_ALLOWED_PORTS` and
`GEMINI_DENIED_MIME_TYPES` accept either the comma-separated form (`a,b`) or a
JSON array (`["a", "b"]`); whitespace around entries is stripped. Leave one
**unset** (or empty) to mean "no restriction". A value that is present but names
no entries — `" , "`, or `"$A,$B"` where both shell variables are empty — is a
**startup error**, because an empty allowlist cannot be told apart from an absent
one and would silently drop the restriction you meant to apply. A port outside
`1`–`65535` in an allowlist is a startup error for the same reason: it could
never match, so every fetch would be refused at runtime instead.

**Caching.** `*_CACHE_TTL_SECONDS=0` disables caching rather than storing entries
that expire the instant they are written.

The tables above cover the most common settings. Additional options include
robots policy caching and retry (`*_ROBOTS_CACHE_TTL_SECONDS`,
`*_ROBOTS_HONOR_AI_TOKENS`, `*_ROBOTS_FAILURE_BACKOFF_SECONDS`),
rendered-output limits (`*_MAX_RENDERED_CHARS`, `GOPHER_MAX_MENU_ITEMS`), Gemini
TOFU/certificate storage paths and expiry policy (`GEMINI_TOFU_STORAGE_PATH`,
`GEMINI_TOFU_REJECT_EXPIRED`, `GEMINI_CLIENT_CERTS_STORAGE_PATH`), MIME filtering
(`GEMINI_DENIED_MIME_TYPES`), and server/logging settings under the `GOPHER_MCP_`
prefix. See the full
[Configuration Guide](https://cameronrye.github.io/gopher-mcp/configuration/) for
every variable, its type, range, and default, or `config/example.env` for a
ready-to-edit starting point.

### Example Configuration

```bash
# Gopher settings
export GOPHER_MAX_RESPONSE_SIZE=2097152
export GOPHER_TIMEOUT_SECONDS=60
export GOPHER_CACHE_ENABLED=true
export GOPHER_ALLOWED_HOSTS="gopher.floodgap.com,gopher.quux.org"

# Gemini settings
export GEMINI_MAX_RESPONSE_SIZE=2097152
export GEMINI_TIMEOUT_SECONDS=60
export GEMINI_TOFU_ENABLED=true
export GEMINI_CLIENT_CERTS_ENABLED=true
export GEMINI_ALLOWED_HOSTS="geminiprotocol.net,skyjake.fi"

# Run with custom config
uv run task serve
```

## Network Etiquette

Gopherspace and Geminispace are served largely by individuals running small
machines. This server is built to be a guest there.

### What this tool does and does not do

`gopher-mcp` fetches a resource when someone asks their assistant for it, and
returns the content to that conversation. It does **not** train on what it
fetches, archive it, rehost it, or make it searchable. It does not follow links
on its own: every URL it retrieves was named by the caller.

Neither protocol has a user-agent field, so nothing identifies this client on
the wire and a server cannot recognise or block it by name. That is a property
of Gopher and Gemini, not a choice made here. What it does do, when robots
checking is enabled below, is honour rules written against the token
`gopher-mcp`, so an operator who wants to single it out has a way to.

### Rate limiting

Both clients space out requests to the same host and cap how many fetches run at
once. Unlike earlier versions, **these are on by default**: one request per
second per host (`*_REQUESTS_PER_MINUTE=60`) and five concurrent fetches
(`*_MAX_CONCURRENT_REQUESTS=5`). Set either to `0` to disable it. A Gemini server
answering `44 SLOW_DOWN` is always honoured regardless of these settings.

### Robot exclusion (`robots.txt`)

The server fetches `/robots.txt` from the host root and honours it before
retrieving anything. This is **on by default**: these are overwhelmingly
hobbyist-run servers, and ignoring a stated policy is not a reasonable default
for a tool an LLM drives unattended. Policies are cached per host for 24 hours
(`*_ROBOTS_CACHE_TTL_SECONDS`), so the extra round-trip is paid once per host,
not per fetch.

`GOPHER_RESPECT_ROBOTS_TXT=false` / `GEMINI_RESPECT_ROBOTS_TXT=false` turns it
off, but the override is for **a host you operate** — a blanket `Disallow: /` on
someone else's server is a decision, not a misconfiguration. The error messages
are written that way too, because they are read by the model, not by you: a
blocked fetch returns `BLOCKED_BY_ROBOTS` and says to stop and tell the user
rather than retry or try another spelling of the path. A fetch refused because
the policy could not be read at all returns `ROBOTS_UNAVAILABLE` instead — a
separate code because it is transient and means nothing disallowed you.

Which convention applies depends on the protocol:

- **Gemini** follows the official [companion specification][gemini-robots],
  which defines the virtual agents `archiver`, `indexer`, `researcher` and
  `webproxy`. This server matches `gopher-mcp`, `webproxy`, `indexer` and `*`.
  It does not claim `archiver` or `researcher`: nothing here retains content,
  and `researcher` is defined for tools that operate without surfacing what they
  fetch.
- **Gopher** follows the convention Veronica-2 documents at
  `gopher://gopher.floodgap.com/0/v2/help/indexer` (written out rather than
  linked, because a `gopher://` href does not survive PyPI's sanitizer). This
  server matches `gopher-mcp` and `*`. It does not claim `veronica`, which
  belongs to Floodgap's indexer.

Both use the original 1994 `robots.txt` grammar rather than RFC 9309, so only
`#`, `User-agent:` and `Disallow:` are recognised and every other field,
including `Allow:`, is ignored. This matters: an RFC 9309 parser would act on
`Allow:` lines that authors on these networks expect to be dropped, making it
_more_ permissive than intended.

By default the server also honours rules naming AI crawler tokens such as
`ClaudeBot`, `GPTBot` and `CCBot` (`*_ROBOTS_HONOR_AI_TOKENS`). These are not
part of either protocol's convention, but an operator who wrote one meant "no
LLM tooling", and that is the request being made.

When a policy cannot be retrieved at all, the host is left alone for a short
while before being probed again (`*_ROBOTS_FAILURE_BACKOFF_SECONDS`, 60s by
default) rather than paying a fresh connect timeout on every request. Set it to
`0` to re-probe immediately, or raise it if you routinely fetch from hosts that
are down. A Gemini capsule answering `44 SLOW_DOWN` is the exception: it named
its own retry period, so that is used instead.

Two known limitations, both documented rather than papered over:

- **Gopher fails open.** The protocol has no status codes, so a missing
  selector, an error document and an empty file are indistinguishable on the
  wire. RFC 9309 §2.3.1.4 would have an unreachable policy deny everything,
  which would block most of Gopherspace. Instead the parser is lenient: content
  that yields no `User-agent:` group imposes no rules. Gemini, which does have
  status codes, fails closed and treats `51 NOT FOUND` as "no policy". Note that
  failing closed covers more than a 4x status: a capsule that is unreachable —
  connection refused, TLS failure, timeout, malformed reply — also has no
  retrievable policy, so it is refused too — but under the separate
  `ROBOTS_UNAVAILABLE` code, since the capsule never disallowed anything. The
  message names the underlying cause, and turning robots checking off will not
  make such a capsule reachable.
- **Gopher path rules are best-effort.** A Gopher URI carries the item type as
  the first path character, so `gopher://host/1/archive` has the URI path
  `/1/archive` but the on-wire selector `/archive`. Rules are tested against both
  spellings, but `Disallow: /` is the only form guaranteed to behave the way its
  author expects.

There is no per-directory or per-user `robots.txt`. Neither protocol convention
nor RFC 9309 §2.3 defines one; on shared hosts the established pattern is a
single file at the root using path prefixes.

[gemini-robots]: https://geminiprotocol.net/docs/companion/robots.gmi

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](https://github.com/cameronrye/gopher-mcp/blob/main/CONTRIBUTING.md) for details.

### Quick Contribution Steps

1. **Fork** the repository on GitHub
2. **Clone** your fork: `git clone https://github.com/your-username/gopher-mcp.git`
3. **Setup** development environment: `uv run task dev-setup`
4. **Create** a feature branch: `git checkout -b feature/amazing-feature`
5. **Make** your changes with tests
6. **Quality** check: `uv run task quality`
7. **Commit** your changes: `git commit -m 'Add amazing feature'`
8. **Push** to your fork: `git push origin feature/amazing-feature`
9. **Submit** a pull request with a clear description

### Development Standards

- **Type hints** for all functions and methods
- **Comprehensive tests** (CI enforces a minimum of 95% coverage)
- **Documentation** for all public APIs
- **Security** considerations for all network operations
- **Cross-platform** compatibility (Windows, macOS, Linux)

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/cameronrye/gopher-mcp/blob/main/LICENSE) file for details.

## Acknowledgments

- **[Model Context Protocol](https://modelcontextprotocol.io/)** by Anthropic - The foundation that makes this integration possible
- **[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)** - Its bundled `FastMCP` (`mcp.server.fastmcp`) is what this server is built on, pinned to `mcp>=1.28.1,<2`
- **The Gopher Protocol Community** - Keeping the spirit of the early internet alive

## Related Projects

- [Model Context Protocol Servers](https://github.com/modelcontextprotocol/servers) - Official MCP server implementations
- [Awesome MCP Servers](https://github.com/punkpeye/awesome-mcp-servers) - Curated list of MCP servers
- [Claude Desktop](https://claude.ai/download) - AI assistant that supports MCP

## Support

- **Bug Reports**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Feature Requests**: [Open a feature request](https://github.com/cameronrye/gopher-mcp/issues/new?template=feature_request.yml)
- **Questions**: [Ask a question](https://github.com/cameronrye/gopher-mcp/issues/new?template=question.yml)
- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)
- **Community**: [MCP Discord](https://discord.gg/modelcontextprotocol)

Whichever you open, include the version: `gopher-mcp --version` reports it and
works for the `uvx` and Docker installs, where there is no checkout to import
the package from.

---

<div align="center">

Made with ❤️ by [Cameron Rye](https://rye.dev/)

[Star this project](https://github.com/cameronrye/gopher-mcp) if you find it useful!

</div>
