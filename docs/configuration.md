# Configuration Guide

This guide covers the configuration options for the Gopher & Gemini MCP Server.

## Overview

The server is configured entirely through environment variables, so you can
customize its behavior without modifying code. All settings are optional — the
server works out of the box with sensible defaults.

Settings are grouped into three namespaces, each with its own prefix:

| Prefix | Applies to |
|--------|------------|
| `GOPHER_` | Gopher protocol settings |
| `GEMINI_` | Gemini protocol settings |
| `GOPHER_MCP_` | Server, logging, and development settings |

!!! warning "The prefix is what matters, not the case"
    The prefix is required: an unprefixed name such as a bare `LOG_LEVEL` or
    `TIMEOUT_SECONDS` is **ignored**. Names are matched
    **case-insensitively**, so `gopher_timeout_seconds` and
    `Gopher_Timeout_Seconds` are read exactly like `GOPHER_TIMEOUT_SECONDS` —
    which matters when other tooling sets a lowercase name you did not expect.
    The upper-case spelling is the convention used throughout these docs, but it
    is not enforced. Booleans accept `true`/`false`, `1`/`0`, `yes`/`no` and
    `on`/`off` in any case; anything else is a startup error.

`config/example.env` in the repository lists every variable with its default and
is the most convenient starting point. As shipped it is a no-op: every value in
it is the default, so copying it to `.env` changes nothing until you edit it.

!!! note "An empty path variable selects the default"
    `GEMINI_TOFU_STORAGE_PATH=`, `GEMINI_CLIENT_CERTS_STORAGE_PATH=` and `GOPHER_MCP_LOG_FILE_PATH=` are read as **unset**, exactly as if the line were commented out, so either spelling selects the default. (Before 0.6.0 an empty value became the path `.`, which made the server try to open the current directory as its trust store or log file; that is fixed.) The same holds for the list-valued variables, where an empty value means "no restriction".

### List-valued variables

`*_ALLOWED_HOSTS`, `*_ALLOWED_PORTS` and `GEMINI_DENIED_MIME_TYPES` accept either
the comma-separated form (`a,b`) or a JSON array (`["a", "b"]`). Surrounding
whitespace on each entry is stripped, so `a, b` and `a,b` are equivalent.

Leave a list variable **unset** (or set it to the empty string) to mean "no
restriction". A value that is present but names no entries — `" , "`, or
`"$A,$B"` where both shell variables are empty — is a **startup error** naming
the variable, because an empty allowlist is indistinguishable from an absent one
and would silently drop the restriction you meant to apply. A port outside
`1`–`65535` in an allowlist is a startup error for the same reason: it could
never match a request, so every fetch would be refused at runtime instead.

## Configuration Methods

### 1. Environment Variables

Set variables in your shell:

```bash
export GOPHER_MAX_RESPONSE_SIZE=2097152
export GEMINI_TIMEOUT_SECONDS=60
```

### 2. Configuration File

Create a `.env` file in your working directory:

```bash
# Copy the example configuration
cp config/example.env .env

# Edit with your preferred settings
nano .env
```

### 3. MCP Client Configuration

Provide environment variables through your MCP client (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uvx",
      "args": ["gopher-mcp"],
      "env": {
        "GOPHER_MAX_RESPONSE_SIZE": "2097152",
        "GEMINI_TIMEOUT_SECONDS": "60",
        "GOPHER_MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### 4. In-process (Python)

Embedders that drive the clients directly pass the same settings as keyword
arguments; the environment is not consulted:

```python
from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.gemini_client import GeminiClient

gopher = GopherClient(
    max_response_size=2 * 1024 * 1024,
    timeout_seconds=60.0,
    cache_enabled=True,
    cache_ttl_seconds=600,
    max_cache_entries=2000,
    allowed_hosts=["gopher.floodgap.com"],
    max_selector_length=2048,
    max_search_length=512,
)

gemini = GeminiClient(
    max_response_size=2 * 1024 * 1024,
    timeout_seconds=60.0,
    allowed_hosts=["geminiprotocol.net", "skyjake.fi"],
    tofu_enabled=True,
    tofu_reject_expired=True,
    client_certs_enabled=True,
    client_certs_storage_path="/custom/path/certs/",
)
```

`allowed_hosts=[]` is an **empty allowlist**, which denies every host; pass
`None` (the default) for "no restriction". There is no TLS-version or
hostname-verification keyword — see the note below.

## Gopher Protocol Configuration (`GOPHER_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GOPHER_MAX_RESPONSE_SIZE` | Integer (bytes) | `1048576` (1 MB) | Maximum response size. Validated to 1 KB – 100 MB. |
| `GOPHER_TIMEOUT_SECONDS` | Float (seconds) | `30.0` | Overall deadline for one fetch, covering DNS, connect, send and read (max 300). |
| `GOPHER_CACHE_ENABLED` | Boolean | `true` | Enable response caching. |
| `GOPHER_CACHE_TTL_SECONDS` | Integer (seconds) | `300` | How long cached responses stay valid (max 86400). `0` disables caching, since every entry would expire the instant it was stored. |
| `GOPHER_MAX_CACHE_ENTRIES` | Integer | `1000` | Maximum cached entries, LRU eviction (range `1`–`100000`). |
| `GOPHER_ALLOWED_HOSTS` | Comma-separated or JSON array | unset (all) | Restrict connections to these hosts. A value naming no hosts is rejected at startup. |
| `GOPHER_ALLOW_LOCAL_HOSTS` | Boolean | `false` | Allow loopback/private hosts (disables SSRF protection). |
| `GOPHER_ALLOWED_PORTS` | Comma-separated or JSON array | unset (any) | Optional positive port allowlist. When set, only these ports may be connected to (closes the arbitrary-port port-scanning gap). A value naming no ports, or a port outside `1`–`65535`, is rejected at startup. |
| `GOPHER_MAX_SELECTOR_LENGTH` | Integer | `1024` | Maximum Gopher selector length (range `1`–`65536`). |
| `GOPHER_MAX_SEARCH_LENGTH` | Integer | `256` | Maximum search query length (range `1`–`4096`). |
| `GOPHER_MAX_RENDERED_CHARS` | Integer | `50000` | Maximum characters of rendered text returned to the model — the LLM-facing cap, distinct from the network byte cap `GOPHER_MAX_RESPONSE_SIZE` (`0` = unlimited, max `10485760`). Longer output is truncated, flagged with `truncated`, and continuable with the fetch tools' `offset` argument. |
| `GOPHER_MAX_MENU_ITEMS` | Integer | `1000` | Maximum Gopher menu items returned to the model (`0` = unlimited, max `1000000`). Larger menus are truncated, flagged, and continuable with `gopher_fetch`'s `offset` argument. |
| `GOPHER_REQUESTS_PER_MINUTE` | Float | `60` | Per-host outbound rate limit (max `6000`); `0` disables it. |
| `GOPHER_MAX_CONCURRENT_REQUESTS` | Integer | `5` | Maximum concurrent in-flight fetches, matching the batch tools' own concurrency (max `1000`); `0` is unlimited. |
| `GOPHER_RESPECT_ROBOTS_TXT` | Boolean | `true` | Fetch and honour `/robots.txt` from the host root, per the convention Veronica-2 documents. Fails open: Gopher has no status codes, so an unreachable policy cannot be distinguished from an absent one. A policy larger than the 500 KB cap is truncated at the last complete line and parsed (RFC 9309 section 2.5). |
| `GOPHER_ROBOTS_CACHE_TTL_SECONDS` | Integer | `86400` | Lifetime of a cached robots policy (max `604800`). |
| `GOPHER_ROBOTS_HONOR_AI_TOKENS` | Boolean | `true` | Also honour rules naming AI crawler tokens (`ClaudeBot`, `GPTBot`, `CCBot`, ...). |
| `GOPHER_ROBOTS_FAILURE_BACKOFF_SECONDS` | Float | `60` | How long a host whose `robots.txt` probe failed is left alone before being probed again (max `3600`). A failed probe is never cached for the full policy TTL, but without a backoff every request to an unreachable host pays a fresh connect timeout; `0` retries on the next request. |

## Gemini Protocol Configuration (`GEMINI_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GEMINI_MAX_RESPONSE_SIZE` | Integer (bytes) | `1048576` (1 MB) | Maximum response size. Validated to 1 KB – 100 MB. |
| `GEMINI_TIMEOUT_SECONDS` | Float (seconds) | `30.0` | One wire-time budget for the whole fetch — DNS, connect and handshake, trust-store write, send and read — not a per-phase timeout (max 300). When robots checking is on, the `/robots.txt` probe spends from the same budget. |
| `GEMINI_CACHE_ENABLED` | Boolean | `true` | Enable response caching. |
| `GEMINI_CACHE_TTL_SECONDS` | Integer (seconds) | `300` | How long cached responses stay valid (max 86400). `0` disables caching, since every entry would expire the instant it was stored. |
| `GEMINI_MAX_CACHE_ENTRIES` | Integer | `1000` | Maximum cached entries, LRU eviction (range `1`–`100000`). |
| `GEMINI_ALLOWED_HOSTS` | Comma-separated or JSON array | unset (all) | Restrict connections to these hosts. A value naming no hosts is rejected at startup. |
| `GEMINI_ALLOW_LOCAL_HOSTS` | Boolean | `false` | Allow loopback/private hosts (disables SSRF protection). |
| `GEMINI_ALLOWED_PORTS` | Comma-separated or JSON array | unset (any) | Optional positive port allowlist. When set, only these ports may be connected to (closes the arbitrary-port port-scanning gap). A value naming no ports, or a port outside `1`–`65535`, is rejected at startup. |
| `GEMINI_TOFU_ENABLED` | Boolean | `true` | Enable Trust-on-First-Use certificate validation. It is the only peer authentication Gemini has here, so turning it off leaves connections unauthenticated — and leaves the `gemini_trust_list` / `gemini_trust_update` tools with no store to act on (`TOFU_DISABLED`). |
| `GEMINI_TOFU_STORAGE_PATH` | File path | `tofu.json` in the state directory (see below) | TOFU trust-store location. Mutations take a `<path>.lock` sibling as a cross-process lock, so give each concurrent server instance its own file rather than sharing one. |
| `GEMINI_TOFU_REJECT_EXPIRED` | Boolean | `false` | Fail closed on a certificate outside its validity window instead of pinning it with a warning. Off by default to match the conventional Gemini TOFU model, where the pinned fingerprint is the real authenticator. |
| `GEMINI_CLIENT_CERTS_ENABLED` | Boolean | `true` | Store scoped client certificates and attach an in-scope one automatically. It never creates one on demand: answering a status-60 prompt takes an explicit `gemini_client_cert_update` call, because the certificate is a persistent identity for the user. Turning it off leaves the `gemini_client_cert_list` / `gemini_client_cert_update` tools with no store to act on (`CLIENT_CERTS_DISABLED`). |
| `GEMINI_CLIENT_CERTS_STORAGE_PATH` | Directory path | `certs/` in the state directory (see below) | Client-certificate storage directory, created `700` with private keys written `600`. It stays empty until an identity is explicitly created; neither the keys nor this path is ever reported back through a tool result. |
| `GEMINI_MAX_RENDERED_CHARS` | Integer | `50000` | Maximum characters of rendered text returned to the model — the LLM-facing cap, distinct from the network byte cap `GEMINI_MAX_RESPONSE_SIZE` (`0` = unlimited, max `10485760`). Longer output is truncated, flagged with `truncated`, and continuable with the fetch tools' `offset` argument. |
| `GEMINI_REQUESTS_PER_MINUTE` | Float | `60` | Per-host outbound rate limit (max `6000`); `0` disables it. Gemini status 44 SLOW_DOWN is always honoured. |
| `GEMINI_MAX_CONCURRENT_REQUESTS` | Integer | `5` | Maximum concurrent in-flight fetches, matching the batch tools' own concurrency (max `1000`); `0` is unlimited. |
| `GEMINI_RESPECT_ROBOTS_TXT` | Boolean | `true` | Fetch and honour `/robots.txt` from the capsule root, per the Gemini companion specification (virtual agents `webproxy` and `indexer`, plus `*`). Fails closed when the policy cannot be retrieved — a temporary (4x) status, but also a connection failure, TLS failure, timeout or malformed reply — so an unreachable capsule is refused with `ROBOTS_UNAVAILABLE` naming the cause (a real `Disallow` is `BLOCKED_BY_ROBOTS`). `51 NOT FOUND` means no policy. A policy larger than the 500 KB cap is truncated and parsed (RFC 9309 section 2.5). |
| `GEMINI_ROBOTS_CACHE_TTL_SECONDS` | Integer | `86400` | Lifetime of a cached robots policy (max `604800`). |
| `GEMINI_ROBOTS_HONOR_AI_TOKENS` | Boolean | `true` | Also honour rules naming AI crawler tokens (`ClaudeBot`, `GPTBot`, `CCBot`, ...). |
| `GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS` | Float | `60` | How long a capsule whose `robots.txt` probe failed is left alone before being probed again (max `3600`). A failed probe is never cached for the full policy TTL, but without a backoff every request to an unreachable capsule pays a fresh connect timeout — and because Gemini fails closed, is refused. `0` retries on the next request. |
| `GEMINI_DENIED_MIME_TYPES` | Comma-separated or JSON array | empty | MIME types to reject; supports wildcards like `image/*`. |

!!! warning "`*_RESPECT_ROBOTS_TXT` is one global switch"
    Turning robots checking off is a decision about your whole deployment, not a
    troubleshooting step for one host: there is no per-host form, so flipping it
    to reach one capsule drops the gate for every other one too. One consequence
    is worth knowing before you meet it — Geminispace's two search engines,
    `kennedy.gemi.dev` and `tlgs.one`, both disallow their own `/search` paths,
    so searching Geminispace does not work with the shipped defaults. That is
    the operators' decision about their own servers. See
    [Finding things in Geminispace](gemini-support.md#finding-things-in-geminispace)
    for what to do instead.

### Where Gemini state is stored

Unless you set the two path variables above, the trust store and client
identities live in gopher-mcp's own per-user data directory, created owner-only
(mode `700`):

| Platform | Default state directory |
|----------|-------------------------|
| Linux / BSD | `~/.local/share/gopher-mcp/` |
| macOS | `~/Library/Application Support/gopher-mcp/` |
| Windows | `%LOCALAPPDATA%\gopher-mcp\`, else `%APPDATA%\gopher-mcp\`, else `~\AppData\Local\gopher-mcp\` |

`XDG_DATA_HOME` overrides all three when it names an **absolute** path — on
every platform, not just Linux — giving `$XDG_DATA_HOME/gopher-mcp/`. Packagers
and anyone who has deliberately moved their data directory expect it honoured
rather than second-guessed.

Earlier versions kept both under `~/.gemini/`, which belongs to Google's Gemini
CLI — the same directory holding the `settings.json` a user edits to register
this server. New installs no longer touch it, but **an existing
`~/.gemini/tofu.json` or `~/.gemini/certs/` keeps being read and written exactly
where it is, permanently and with no deprecation window.** Relocating a trust
store behind the user's back would either lose every pin or make a pinned host
look unpinned, which is precisely the blind trust-on-first-use the store exists
to prevent. To move it deliberately, copy the files and set the two variables.

Put the store somewhere only the server's user can read, and somewhere
**writable**: a read-only location fails the fetch with
`CERTIFICATE_STORE_UNAVAILABLE` rather than continuing unpinned. In a container,
mount the state directory as a volume — otherwise every run re-establishes its
pins from scratch and a rotated certificate can never be told apart from an
interception. See [Docker](installation.md#method-5-docker) for the invocation
that does this.

!!! note "TLS and certificates are not env-configurable"
    Gemini always uses TLS 1.2+ (1.2 and 1.3 are supported) and establishes
    server identity from the TOFU pin, not a CA chain: the TLS context runs
    `verify_mode=CERT_NONE` with `check_hostname=False`, so OpenSSL never
    validates a chain or a hostname and no chain error can ever be raised. There
    is no environment variable for either. Client certificates are generated and
    managed through `gemini_client_cert_update`; you do not supply cert/key file
    paths. See [Gemini Support](gemini-support.md#security) for the trust model
    and [Gemini Troubleshooting](gemini-troubleshooting.md#tls-connection-issues)
    when a handshake fails.

## Server, Logging & Development Configuration (`GOPHER_MCP_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GOPHER_MCP_LOG_LEVEL` | String | `INFO` | Verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `GOPHER_MCP_STRUCTURED_LOGGING` | Boolean | `true` | Emit structured JSON logs instead of console-rendered output. |
| `GOPHER_MCP_LOG_FILE_PATH` | File path | empty | Optionally **mirror** logs to a file. This is a tee, not a redirect: logs always go to **stderr** (never stdout, which carries the MCP protocol stream) and the file receives a copy of the same records. |

Every record reaching that stream goes through the same pipeline, whichever
library emitted it: this server's own events, the MCP SDK's, and — on the
`sse` and `streamable-http` transports — uvicorn's startup lines and access log.
So `GOPHER_MCP_STRUCTURED_LOGGING=true` really does produce line-delimited JSON
on every line, uvicorn's records land in the log file too, and they obey
`GOPHER_MCP_LOG_LEVEL` rather than a separate uvicorn log level.

## Configuration Presets

### Minimal (Defaults)

```bash
# No configuration needed — the defaults suit testing and basic usage.
```

### Development

```bash
# Verbose logging, caching off for fresh results
GOPHER_MCP_LOG_LEVEL=DEBUG
GOPHER_CACHE_ENABLED=false
GEMINI_CACHE_ENABLED=false
```

For a one-off fresh read you do not need to disable caching at all: pass
`refresh: true` to `gopher_fetch`, `gemini_fetch`, `gopher_batch_fetch` or
`gemini_batch_fetch`, and check the `cached` / `cache_age_seconds` fields a
cacheable result carries.

### Production

```bash
# Balanced limits and caching
GOPHER_MAX_RESPONSE_SIZE=2097152
GOPHER_TIMEOUT_SECONDS=30
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=600
GOPHER_MAX_CACHE_ENTRIES=2000

GEMINI_MAX_RESPONSE_SIZE=2097152
GEMINI_TIMEOUT_SECONDS=30
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=600
GEMINI_MAX_CACHE_ENTRIES=2000
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true

GOPHER_MCP_LOG_LEVEL=INFO
GOPHER_MCP_STRUCTURED_LOGGING=true
```

### High Performance

```bash
# Larger, longer-lived caches
GOPHER_CACHE_TTL_SECONDS=1800
GOPHER_MAX_CACHE_ENTRIES=5000
GEMINI_CACHE_TTL_SECONDS=1800
GEMINI_MAX_CACHE_ENTRIES=5000

GOPHER_MCP_LOG_LEVEL=WARNING
```

### Hardened / Restricted Access

```bash
# Allow only specific trusted hosts and rate-limit outbound requests
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,skyjake.fi,kennedy.gemi.dev
GOPHER_ALLOW_LOCAL_HOSTS=false
GEMINI_ALLOW_LOCAL_HOSTS=false
GEMINI_TOFU_ENABLED=true
GEMINI_TOFU_REJECT_EXPIRED=true
GOPHER_REQUESTS_PER_MINUTE=30
GEMINI_REQUESTS_PER_MINUTE=30
GOPHER_RESPECT_ROBOTS_TXT=true
GEMINI_RESPECT_ROBOTS_TXT=true
GOPHER_MCP_LOG_LEVEL=INFO
```

## Configuration Validation

Use the built-in validation script to check your configuration. It validates the
variables the server actually reads, against the bounds the server actually
enforces, and exits non-zero when it finds an error:

```bash
# Validate the environment (and ./.env, if present)
python scripts/validate-config.py

# Or validate a specific env file without exporting it
python scripts/validate-config.py config/example.env
```

Common validation errors:

1. **Invalid size values** — must be integers within range
2. **Invalid timeout values** — must be floats greater than `0`, up to `300`
3. **Invalid boolean values** — `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`
4. **Empty allowlists** — a `*_ALLOWED_HOSTS` or `*_ALLOWED_PORTS` value that
   names no entries is refused at startup; unset the variable instead
5. **Out-of-range ports** — every entry in a `*_ALLOWED_PORTS` list must be
   between `1` and `65535`

An empty value for a path variable is **not** an error: it means "use the
default", and the validator accepts it for the same reason the server does.

It also warns about variables that look like settings but are ignored — an
unprefixed `LOG_LEVEL`, or settings that never existed such as
`GEMINI_TLS_VERSION`.

The server applies the same bounds at startup. A value it cannot accept is not
silently dropped: startup stops with exit status `2` and a single line naming the
environment variable, the accepted range and the value you set, for example

```text
gopher-mcp: configuration error: GOPHER_TIMEOUT_SECONDS: Input should be less than or equal to 300 (got '999')
```

## Environment Variable Precedence

Configuration is resolved in this order (later overrides earlier):

1. Default values (defined in the source)
2. A `.env` file in the working directory
3. Process environment variables (including those set by your MCP client)

## Troubleshooting

### Configuration Not Applied

1. Confirm the variable name includes its prefix (`GOPHER_`, `GEMINI_`, or `GOPHER_MCP_`) — unprefixed names are ignored.
2. Check the spelling of the rest of the name. Case is not the problem: names are matched case-insensitively, so a stray lowercase copy set by other tooling **will** be picked up and can be the value you are seeing.
3. Check the value is in range for the setting. An out-of-range or unparseable value is not ignored — it stops the server at startup with one line naming the variable, the accepted range and the value you set.
4. Restart the server after changing configuration.

### Performance Issues

1. Increase cache size: `GOPHER_MAX_CACHE_ENTRIES`, `GEMINI_MAX_CACHE_ENTRIES`
2. Increase cache TTL: `GOPHER_CACHE_TTL_SECONDS`, `GEMINI_CACHE_TTL_SECONDS`
3. Increase timeouts if needed: `GOPHER_TIMEOUT_SECONDS`, `GEMINI_TIMEOUT_SECONDS`

### Security Concerns

1. Keep TOFU enabled: `GEMINI_TOFU_ENABLED=true`
2. Restrict hosts: `GOPHER_ALLOWED_HOSTS`, `GEMINI_ALLOWED_HOSTS`
3. Keep local-host access off: `GOPHER_ALLOW_LOCAL_HOSTS=false`, `GEMINI_ALLOW_LOCAL_HOSTS=false`
4. Set an appropriate log level: `GOPHER_MCP_LOG_LEVEL=INFO` or `WARNING`

## See Also

- [Installation Guide](installation.md) — initial setup and MCP client wiring
- [Gemini Support and Trust Model](gemini-support.md) — what the TOFU and
  client-certificate settings above actually do
- [Troubleshooting](troubleshooting.md) — diagnosing common problems
- [API Reference](api-reference.md) — the tools these settings bound
