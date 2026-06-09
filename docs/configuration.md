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
is the most convenient starting point.

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
| `GOPHER_TIMEOUT_SECONDS` | Float (seconds) | `30.0` | Request timeout (max 300). |
| `GOPHER_CACHE_ENABLED` | Boolean | `true` | Enable response caching. |
| `GOPHER_CACHE_TTL_SECONDS` | Integer (seconds) | `300` | How long cached responses stay valid (max 86400). |
| `GOPHER_MAX_CACHE_ENTRIES` | Integer | `1000` | Maximum cached entries (LRU eviction). |
| `GOPHER_ALLOWED_HOSTS` | Comma-separated | empty (all) | Restrict connections to these hosts. |
| `GOPHER_ALLOW_LOCAL_HOSTS` | Boolean | `false` | Allow loopback/private hosts (disables SSRF protection). |
| `GOPHER_ALLOWED_PORTS` | Comma-separated | empty (any) | Optional positive port allowlist. When set, only these ports may be connected to (closes the arbitrary-port port-scanning gap). |
| `GOPHER_MAX_SELECTOR_LENGTH` | Integer | `1024` | Maximum Gopher selector length. |
| `GOPHER_MAX_SEARCH_LENGTH` | Integer | `256` | Maximum search query length. |
| `GOPHER_MAX_RENDERED_CHARS` | Integer | `50000` | Maximum characters of rendered text returned to the model (longer output is truncated and flagged). |
| `GOPHER_MAX_MENU_ITEMS` | Integer | `1000` | Maximum Gopher menu items returned to the model (`0` = unlimited; larger menus are truncated and flagged). |
| `GOPHER_REQUESTS_PER_MINUTE` | Float | `0` (off) | Per-host outbound rate limit. |
| `GOPHER_MAX_CONCURRENT_REQUESTS` | Integer | `0` (unlimited) | Maximum concurrent requests. |

## Gemini Protocol Configuration (`GEMINI_`)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GEMINI_MAX_RESPONSE_SIZE` | Integer (bytes) | `1048576` (1 MB) | Maximum response size. Validated to 1 KB – 100 MB. |
| `GEMINI_TIMEOUT_SECONDS` | Float (seconds) | `30.0` | Request timeout (max 300). |
| `GEMINI_CACHE_ENABLED` | Boolean | `true` | Enable response caching. |
| `GEMINI_CACHE_TTL_SECONDS` | Integer (seconds) | `300` | How long cached responses stay valid (max 86400). |
| `GEMINI_MAX_CACHE_ENTRIES` | Integer | `1000` | Maximum cached entries (LRU eviction). |
| `GEMINI_ALLOWED_HOSTS` | Comma-separated | empty (all) | Restrict connections to these hosts. |
| `GEMINI_ALLOW_LOCAL_HOSTS` | Boolean | `false` | Allow loopback/private hosts (disables SSRF protection). |
| `GEMINI_ALLOWED_PORTS` | Comma-separated | empty (any) | Optional positive port allowlist. When set, only these ports may be connected to (closes the arbitrary-port port-scanning gap). |
| `GEMINI_TOFU_ENABLED` | Boolean | `true` | Enable Trust-on-First-Use certificate validation. |
| `GEMINI_TOFU_STORAGE_PATH` | File path | `~/.gemini/tofu.json` | TOFU trust-store location. |
| `GEMINI_TOFU_REJECT_EXPIRED` | Boolean | `false` | Fail closed on a certificate outside its validity window. |
| `GEMINI_CLIENT_CERTS_ENABLED` | Boolean | `true` | Enable automatic per-host client certificates. |
| `GEMINI_CLIENT_CERTS_STORAGE_PATH` | Directory path | `~/.gemini/certs/` | Client-certificate storage directory. |
| `GEMINI_MAX_RENDERED_CHARS` | Integer | `50000` | Maximum characters of rendered text returned to the model (longer output is truncated and flagged). |
| `GEMINI_REQUESTS_PER_MINUTE` | Float | `0` (off) | Per-host outbound rate limit. Gemini status 44 SLOW_DOWN is always honoured. |
| `GEMINI_MAX_CONCURRENT_REQUESTS` | Integer | `0` (unlimited) | Maximum concurrent requests. |
| `GEMINI_DENIED_MIME_TYPES` | Comma-separated | empty | MIME types to reject; supports wildcards like `image/*`. |

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
GOPHER_REQUESTS_PER_MINUTE=60
GEMINI_REQUESTS_PER_MINUTE=60
GOPHER_MCP_LOG_LEVEL=INFO
```

## Configuration Validation

Use the built-in validation script to check your configuration:

```bash
python scripts/validate-config.py
```

Common validation errors:

1. **Invalid size values** — must be positive integers within range
2. **Invalid timeout values** — must be positive floats within range
3. **Invalid boolean values** — only `true` or `false` are accepted
4. **Invalid host lists** — comma-separated, without spaces

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
