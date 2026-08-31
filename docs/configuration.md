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

!!! warning
    Variable names are **case-sensitive** and the prefix is required. An
    unprefixed name such as a bare `LOG_LEVEL` or `TIMEOUT_SECONDS` is **ignored**.
    Boolean values must be exactly `true` or `false`.

`config/example.env` in the repository lists every variable with its default and
is the most convenient starting point. As shipped it is a no-op: every value in
it is the default, so copying it to `.env` changes nothing until you edit it.

!!! warning "Path variables must be commented out, not left empty"
    `GEMINI_TOFU_STORAGE_PATH=`, `GEMINI_CLIENT_CERTS_STORAGE_PATH=` and `GOPHER_MCP_LOG_FILE_PATH=` are read as the path `.`, **not** as "unset" — the server would then treat the current directory as the trust store, the certificate directory, or the log file. Comment those three variables out to use their defaults. This does not apply to the list-valued variables, where an empty value correctly means "no restriction".

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

## Gopher Protocol Configuration (`GOPHER_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GOPHER_MAX_RESPONSE_SIZE` | Integer (bytes) | `1048576` (1 MB) | Maximum response size. Validated to 1 KB – 100 MB. |
| `GOPHER_TIMEOUT_SECONDS` | Float (seconds) | `30.0` | Overall deadline for one fetch, covering DNS, connect, send and read (max 300). |
| `GOPHER_CACHE_ENABLED` | Boolean | `true` | Enable response caching. |
| `GOPHER_CACHE_TTL_SECONDS` | Integer (seconds) | `300` | How long cached responses stay valid (max 86400). `0` disables caching, since every entry would expire the instant it was stored. |
| `GOPHER_MAX_CACHE_ENTRIES` | Integer | `1000` | Maximum cached entries (LRU eviction). |
| `GOPHER_ALLOWED_HOSTS` | Comma-separated or JSON array | unset (all) | Restrict connections to these hosts. A value naming no hosts is rejected at startup. |
| `GOPHER_ALLOW_LOCAL_HOSTS` | Boolean | `false` | Allow loopback/private hosts (disables SSRF protection). |
| `GOPHER_ALLOWED_PORTS` | Comma-separated or JSON array | unset (any) | Optional positive port allowlist. When set, only these ports may be connected to (closes the arbitrary-port port-scanning gap). A value naming no ports, or a port outside `1`–`65535`, is rejected at startup. |
| `GOPHER_MAX_SELECTOR_LENGTH` | Integer | `1024` | Maximum Gopher selector length. |
| `GOPHER_MAX_SEARCH_LENGTH` | Integer | `256` | Maximum search query length. |
| `GOPHER_MAX_RENDERED_CHARS` | Integer | `50000` | Maximum characters of rendered text returned to the model (longer output is truncated and flagged). |
| `GOPHER_MAX_MENU_ITEMS` | Integer | `1000` | Maximum Gopher menu items returned to the model (`0` = unlimited; larger menus are truncated and flagged). |
| `GOPHER_REQUESTS_PER_MINUTE` | Float | `60` | Per-host outbound rate limit; `0` disables it. |
| `GOPHER_MAX_CONCURRENT_REQUESTS` | Integer | `5` | Maximum concurrent requests; `0` is unlimited. |
| `GOPHER_RESPECT_ROBOTS_TXT` | Boolean | `false` | Fetch and honour `/robots.txt` from the host root, per the convention Veronica-2 documents. Fails open: Gopher has no status codes, so an unreachable policy cannot be distinguished from an absent one. A policy larger than the 500 KB cap is truncated at the last complete line and parsed (RFC 9309 section 2.5). |
| `GOPHER_ROBOTS_CACHE_TTL_SECONDS` | Integer | `86400` | Lifetime of a cached robots policy (max `604800`). |
| `GOPHER_ROBOTS_HONOR_AI_TOKENS` | Boolean | `true` | Also honour rules naming AI crawler tokens (`ClaudeBot`, `GPTBot`, `CCBot`, ...). |

## Gemini Protocol Configuration (`GEMINI_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GEMINI_MAX_RESPONSE_SIZE` | Integer (bytes) | `1048576` (1 MB) | Maximum response size. Validated to 1 KB – 100 MB. |
| `GEMINI_TIMEOUT_SECONDS` | Float (seconds) | `30.0` | One wire-time budget for the whole fetch — DNS, connect and handshake, trust-store write, send and read — not a per-phase timeout (max 300). When robots checking is on, the `/robots.txt` probe spends from the same budget. |
| `GEMINI_CACHE_ENABLED` | Boolean | `true` | Enable response caching. |
| `GEMINI_CACHE_TTL_SECONDS` | Integer (seconds) | `300` | How long cached responses stay valid (max 86400). `0` disables caching, since every entry would expire the instant it was stored. |
| `GEMINI_MAX_CACHE_ENTRIES` | Integer | `1000` | Maximum cached entries (LRU eviction). |
| `GEMINI_ALLOWED_HOSTS` | Comma-separated or JSON array | unset (all) | Restrict connections to these hosts. A value naming no hosts is rejected at startup. |
| `GEMINI_ALLOW_LOCAL_HOSTS` | Boolean | `false` | Allow loopback/private hosts (disables SSRF protection). |
| `GEMINI_ALLOWED_PORTS` | Comma-separated or JSON array | unset (any) | Optional positive port allowlist. When set, only these ports may be connected to (closes the arbitrary-port port-scanning gap). A value naming no ports, or a port outside `1`–`65535`, is rejected at startup. |
| `GEMINI_TOFU_ENABLED` | Boolean | `true` | Enable Trust-on-First-Use certificate validation. It is the only peer authentication Gemini has here, so turning it off leaves connections unauthenticated — and leaves the `gemini_trust_list` / `gemini_trust_update` tools with no store to act on (`TOFU_DISABLED`). |
| `GEMINI_TOFU_STORAGE_PATH` | File path | `~/.gemini/tofu.json` | TOFU trust-store location. |
| `GEMINI_TOFU_REJECT_EXPIRED` | Boolean | `false` | Fail closed on a certificate outside its validity window. |
| `GEMINI_CLIENT_CERTS_ENABLED` | Boolean | `true` | Enable automatic per-host client certificates. |
| `GEMINI_CLIENT_CERTS_STORAGE_PATH` | Directory path | `~/.gemini/certs/` | Client-certificate storage directory. |
| `GEMINI_MAX_RENDERED_CHARS` | Integer | `50000` | Maximum characters of rendered text returned to the model (longer output is truncated and flagged). |
| `GEMINI_REQUESTS_PER_MINUTE` | Float | `60` | Per-host outbound rate limit; `0` disables it. Gemini status 44 SLOW_DOWN is always honoured. |
| `GEMINI_MAX_CONCURRENT_REQUESTS` | Integer | `5` | Maximum concurrent requests; `0` is unlimited. |
| `GEMINI_RESPECT_ROBOTS_TXT` | Boolean | `false` | Fetch and honour `/robots.txt` from the capsule root, per the Gemini companion specification (virtual agents `webproxy` and `indexer`, plus `*`). Fails closed on a temporary (4x) failure; `51 NOT FOUND` means no policy. A policy larger than the 500 KB cap is truncated and parsed (RFC 9309 section 2.5). |
| `GEMINI_ROBOTS_CACHE_TTL_SECONDS` | Integer | `86400` | Lifetime of a cached robots policy (max `604800`). |
| `GEMINI_ROBOTS_HONOR_AI_TOKENS` | Boolean | `true` | Also honour rules naming AI crawler tokens (`ClaudeBot`, `GPTBot`, `CCBot`, ...). |
| `GEMINI_DENIED_MIME_TYPES` | Comma-separated or JSON array | empty | MIME types to reject; supports wildcards like `image/*`. |

!!! note "TLS and certificates are not env-configurable"
    Gemini always uses TLS 1.2+ and verifies the server identity via TOFU (the
    pinned-fingerprint model), not CA-chain/hostname checks — there is no env var
    to change the TLS version or toggle hostname verification. Client certificates
    are generated and managed automatically; you do not supply cert/key file
    paths. See [Gemini Configuration](gemini-configuration.md) for details.

## Server, Logging & Development Configuration (`GOPHER_MCP_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GOPHER_MCP_LOG_LEVEL` | String | `INFO` | Verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `GOPHER_MCP_STRUCTURED_LOGGING` | Boolean | `true` | Emit structured JSON logs instead of console-rendered output. |
| `GOPHER_MCP_LOG_FILE_PATH` | File path | empty | Optionally tee logs to a file. Logs always go to **stderr** (never stdout, which carries the MCP protocol stream). |

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
`refresh: true` to `gopher_fetch` or `gemini_fetch`, and check the `cached` /
`cache_age_seconds` fields a cacheable result carries.

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
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se,kennedy.gemi.dev
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
6. **Empty path values** — `GEMINI_TOFU_STORAGE_PATH=`,
   `GEMINI_CLIENT_CERTS_STORAGE_PATH=` and `GOPHER_MCP_LOG_FILE_PATH=` are read
   as the path `.`; comment them out instead

It also warns about variables that look like settings but are ignored — an
unprefixed `LOG_LEVEL`, or settings that never existed such as
`GEMINI_TLS_VERSION`.

## Environment Variable Precedence

Configuration is resolved in this order (later overrides earlier):

1. Default values (defined in the source)
2. A `.env` file in the working directory
3. Process environment variables (including those set by your MCP client)

## Troubleshooting

### Configuration Not Applied

1. Confirm the variable name includes its prefix (`GOPHER_`, `GEMINI_`, or `GOPHER_MCP_`) — unprefixed names are ignored.
2. Check that names are spelled exactly and are case-sensitive.
3. Verify boolean values are exactly `true` or `false` and numeric values are within range.
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

- [Gemini Configuration Reference](gemini-configuration.md) — detailed Gemini-specific configuration
- [Advanced Features](advanced-features.md) — advanced configuration scenarios
- [Installation Guide](installation.md) — initial setup
- [Troubleshooting](troubleshooting.md) — diagnosing common problems
