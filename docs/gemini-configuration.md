# Gemini Configuration Reference

This document provides a comprehensive reference for all Gemini protocol configuration options in the Gopher & Gemini MCP Server.

## Environment Variables

### Core Configuration

#### `GEMINI_MAX_RESPONSE_SIZE`

- **Type**: Integer (bytes)
- **Default**: `1048576` (1MB)
- **Range**: `1024` - `104857600` (1KB - 100MB)
- **Description**: Maximum size of Gemini response content
- **Example**: `GEMINI_MAX_RESPONSE_SIZE=2097152`

#### `GEMINI_TIMEOUT_SECONDS`

- **Type**: Float (seconds)
- **Default**: `30.0`
- **Range**: greater than `0` up to `300.0`
- **Description**: One wire-time budget for an entire fetch, not a per-phase
  timeout: DNS resolution, connect and TLS handshake, the TOFU trust-store
  write, sending the request and reading the response all draw down the same
  deadline, so a slow server cannot spend the full value on each phase in turn.
  When `GEMINI_RESPECT_ROBOTS_TXT` is enabled, the `/robots.txt` probe shares
  that budget with the fetch it guards rather than getting one of its own.
- **Example**: `GEMINI_TIMEOUT_SECONDS=60.0`

### Caching Configuration

#### `GEMINI_CACHE_ENABLED`

- **Type**: Boolean
- **Default**: `true`
- **Values**: `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off`
- **Description**: Enable response caching for Gemini requests
- **Example**: `GEMINI_CACHE_ENABLED=true`

#### `GEMINI_CACHE_TTL_SECONDS`

- **Type**: Integer (seconds)
- **Default**: `300` (5 minutes)
- **Range**: `0` - `86400` (up to 24 hours)
- **Description**: Time-to-live for cached Gemini responses. `0` turns caching
  off entirely — every entry would expire the instant it was stored, so the
  cache is disabled rather than filled with unusable entries. A longer TTL does
  not hide staleness from the caller: every cacheable result reports `cached`,
  `cached_at` and `cache_age_seconds`, and `gemini_fetch` takes `refresh` to
  bypass the cache for one request.
- **Example**: `GEMINI_CACHE_TTL_SECONDS=600`

#### `GEMINI_MAX_CACHE_ENTRIES`

- **Type**: Integer
- **Default**: `1000`
- **Range**: `1` - `100000`
- **Description**: Maximum number of entries in Gemini cache
- **Example**: `GEMINI_MAX_CACHE_ENTRIES=2000`

### Security Configuration

#### `GEMINI_ALLOWED_HOSTS`

- **Type**: String (comma-separated, or a JSON array such as `["a", "b"]`)
- **Default**: Unset (all hosts allowed)
- **Description**: Hosts this client may connect to. Whitespace around each
  entry is ignored. A value that is set but names no hosts — `" , "`, or
  `"$A,$B"` with empty interpolations — is refused at startup rather than read
  as "no restriction"; unset the variable to allow all hosts.
- **Example**: `GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se,kennedy.gemi.dev`

#### `GEMINI_ALLOWED_PORTS`

- **Type**: String (comma-separated, or a JSON array such as `[1965, 1966]`)
- **Default**: Unset (any non-dangerous port)
- **Description**: Positive port allowlist. When set, only these ports may be
  connected to, closing the arbitrary-port port-scanning gap. As with the host
  allowlist, a value naming no ports is refused at startup; so is any port
  outside `1`–`65535`, which could never match a request and would otherwise
  reject every fetch at runtime.
- **Example**: `GEMINI_ALLOWED_PORTS=1965`

#### `GEMINI_ALLOW_LOCAL_HOSTS`

- **Type**: Boolean
- **Default**: `false`
- **Description**: Allow connections to loopback/private/internal addresses. Disabled by default to prevent SSRF.
- **Example**: `GEMINI_ALLOW_LOCAL_HOSTS=false`

#### `GEMINI_TOFU_ENABLED`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable Trust-on-First-Use certificate validation. Gemini TLS runs without CA-chain validation, so TOFU is the only peer authentication; disabling it leaves connections unauthenticated and MITM-able. With it off there is also no trust store, and the `gemini_trust_list` / `gemini_trust_update` tools return `TOFU_DISABLED`.
- **Example**: `GEMINI_TOFU_ENABLED=true`

#### `GEMINI_TOFU_REJECT_EXPIRED`

- **Type**: Boolean
- **Default**: `false`
- **Description**: Fail closed when a server certificate is outside its validity window (already expired, or not yet valid on first use) instead of pinning it with a warning. Off by default to match the conventional Gemini TOFU model, where the pinned fingerprint is the real authenticator.
- **Example**: `GEMINI_TOFU_REJECT_EXPIRED=true`

#### `GEMINI_CLIENT_CERTS_ENABLED`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable client certificate storage and automatic attachment. A certificate that already covers the requested host/port/path scope is attached to the connection; you do not supply cert/key files yourself. It does **not** create certificates: nothing in the MCP tool surface does, so a capsule answering status 60 cannot be satisfied through the tools (see [Client Certificate Issues](gemini-troubleshooting.md#client-certificate-issues)).
- **Example**: `GEMINI_CLIENT_CERTS_ENABLED=true`

### Storage Configuration

#### `GEMINI_TOFU_STORAGE_PATH`

- **Type**: String (file path)
- **Default**: `~/.gemini/tofu.json`
- **Description**: Path to TOFU certificate fingerprint storage file
- **Example**: `GEMINI_TOFU_STORAGE_PATH=/custom/path/tofu.json`

#### `GEMINI_CLIENT_CERTS_STORAGE_PATH`

- **Type**: String (directory path)
- **Default**: `~/.gemini/certs/`
- **Description**: Directory where client certificates and their private keys are stored, scoped per host/port/path. The directory is created with owner-only (`700`) permissions. Nothing in the MCP tool surface writes certificates here, so the directory stays empty unless an embedder calls `GeminiClient.generate_client_certificate()`.
- **Example**: `GEMINI_CLIENT_CERTS_STORAGE_PATH=/custom/path/certs/`

### Content and Rate Limiting

#### `GEMINI_MAX_RENDERED_CHARS`

- **Type**: Integer (characters)
- **Default**: `50000`
- **Range**: `0` - `10485760` (`0` = unlimited)
- **Description**: LLM-facing cap on the number of returned text characters, distinct from the network byte cap (`GEMINI_MAX_RESPONSE_SIZE`). Truncation is flagged on the result.
- **Example**: `GEMINI_MAX_RENDERED_CHARS=100000`

#### `GEMINI_REQUESTS_PER_MINUTE`

- **Type**: Float
- **Default**: `60` (one request per second, per host)
- **Range**: `0` - `6000` (`0` = unlimited)
- **Description**: Per-host outbound request rate cap, for politeness toward small Gemini servers. On by default. A status-44 `SLOW_DOWN` response is always honoured regardless of this setting.
- **Example**: `GEMINI_REQUESTS_PER_MINUTE=30`

#### `GEMINI_MAX_CONCURRENT_REQUESTS`

- **Type**: Integer
- **Default**: `5` (matches the batch tools' own concurrency)
- **Range**: `0` - `1000` (`0` = unlimited)
- **Description**: Cap on simultaneous in-flight fetches; a coarse bound on concurrent sockets and memory, complementary to the per-host rate limit. On by default.
- **Example**: `GEMINI_MAX_CONCURRENT_REQUESTS=2`

#### `GEMINI_DENIED_MIME_TYPES`

- **Type**: String (comma-separated, or a JSON array such as `["text/html"]`)
- **Default**: Empty (no content filtering)
- **Description**: MIME types, or `type/*` wildcards, to reject as filtered content. Empty means no content filtering.
- **Example**: `GEMINI_DENIED_MIME_TYPES=text/html,image/*`

### Robot Exclusion

#### `GEMINI_RESPECT_ROBOTS_TXT`

- **Type**: Boolean
- **Default**: `false`
- **Description**: Fetch and honour `/robots.txt` from the capsule root before retrieving a resource, following the [Gemini companion specification](https://geminiprotocol.net/docs/companion/robots.gmi) (virtual agents `webproxy` and `indexer`, plus `*`, alongside `gopher-mcp`). Off by default because it adds a round-trip per host, and the probe spends from the same `GEMINI_TIMEOUT_SECONDS` budget as the fetch it guards. **Fails closed** on a temporary (4x) robots fetch failure; `51 NOT FOUND` means "no policy". A policy larger than the 500 KB read cap is truncated at the last complete line and parsed (RFC 9309 section 2.5) rather than treated as unavailable. A target the SSRF guard refuses is reported as `BLOCKED`, not as an unreachable robots.txt — disabling robots checking would not make it reachable.
- **Example**: `GEMINI_RESPECT_ROBOTS_TXT=true`

#### `GEMINI_ROBOTS_CACHE_TTL_SECONDS`

- **Type**: Integer (seconds)
- **Default**: `86400` (24 hours)
- **Range**: `0` - `604800` (one week)
- **Description**: How long a fetched robots policy stays valid, per host.
- **Example**: `GEMINI_ROBOTS_CACHE_TTL_SECONDS=3600`

#### `GEMINI_ROBOTS_HONOR_AI_TOKENS`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Also honour `Disallow` rules aimed at named AI crawler tokens (`ClaudeBot`, `GPTBot`, `CCBot`, ...). Not part of the companion specification, but a capsule naming them meant "no LLM tooling". Only applies when `GEMINI_RESPECT_ROBOTS_TXT` is enabled.
- **Example**: `GEMINI_ROBOTS_HONOR_AI_TOKENS=false`

!!! note "TLS version and hostname verification are not configurable"
    The minimum TLS version is fixed in code at **TLS 1.2** (TLS 1.2 and 1.3 are supported); there is no environment variable to change it. Server certificates are trusted via TOFU rather than CA-chain/hostname verification, so there is no hostname-verification toggle either. Client certificates are generated and managed automatically (see `GEMINI_CLIENT_CERTS_ENABLED` / `GEMINI_CLIENT_CERTS_STORAGE_PATH`) — you do not point the server at a manual cert/key file.

## Configuration Examples

### Development Configuration

```bash
# Development settings - relaxed security, no caching
GEMINI_CACHE_ENABLED=false
GEMINI_TOFU_ENABLED=false
GEMINI_CLIENT_CERTS_ENABLED=false
GEMINI_TIMEOUT_SECONDS=60
GOPHER_MCP_LOG_LEVEL=DEBUG
```

### Production Configuration

```bash
# Production settings - high security, optimized performance
GEMINI_MAX_RESPONSE_SIZE=2097152
GEMINI_TIMEOUT_SECONDS=30
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=600
GEMINI_MAX_CACHE_ENTRIES=2000
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se
GEMINI_TOFU_ENABLED=true
GEMINI_TOFU_REJECT_EXPIRED=true
GEMINI_CLIENT_CERTS_ENABLED=true
```

### High Security Configuration

```bash
# Maximum security settings
GEMINI_ALLOWED_HOSTS=trusted-host1.example.org,trusted-host2.example.org
GEMINI_ALLOW_LOCAL_HOSTS=false
GEMINI_TOFU_ENABLED=true
GEMINI_TOFU_REJECT_EXPIRED=true
GEMINI_CLIENT_CERTS_ENABLED=true
GEMINI_DENIED_MIME_TYPES=text/html,image/*
```

### Performance Optimized Configuration

```bash
# Optimized for high performance
GEMINI_MAX_RESPONSE_SIZE=5242880  # 5MB
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=1800     # 30 minutes
GEMINI_MAX_CACHE_ENTRIES=5000
GEMINI_MAX_CONCURRENT_REQUESTS=20
```

## Configuration Validation

Use the built-in configuration validation script:

```bash
# Validate the configuration in the environment
python scripts/validate-config.py

# Or validate a specific env file without exporting it
python scripts/validate-config.py config/example.env
```

The validator checks:

- Value ranges and types, against the bounds the server itself enforces
- Boolean value formats
- List-valued variables in both spellings (comma-separated and JSON array),
  including the fail-closed rules: a value naming no entries, or a port outside
  `1`-`65535`, is a startup error
- Storage paths and log-file directories
- Variables that look like configuration but are **not** read by the server
  (unprefixed names, and settings that never existed such as `GEMINI_TLS_VERSION`)

## Security Considerations

### Certificate Storage

- **TOFU Storage**: Ensure the TOFU storage file has proper permissions (600)
- **Client Certificates**: The client-certificate directory is created with owner-only (700) permissions, and generated private keys are written 600 — keep those permissions intact
- **Custom Paths**: If you relocate `GEMINI_TOFU_STORAGE_PATH` or `GEMINI_CLIENT_CERTS_STORAGE_PATH`, place them on a filesystem only the server user can read

### Network Security

- **Host Allowlists**: Use restrictive host allowlists in production
- **TLS Version**: TLS 1.2 is the enforced minimum (TLS 1.2 and 1.3 supported); this is fixed in code and not configurable
- **Certificate Validation**: Always enable TOFU in production environments; consider `GEMINI_TOFU_REJECT_EXPIRED=true` to fail closed on certificates outside their validity window

### Content Security

- **Size Limits**: Set appropriate response size limits (`GEMINI_MAX_RESPONSE_SIZE`) and rendered-text caps (`GEMINI_MAX_RENDERED_CHARS`)
- **Timeout Protection**: Configure reasonable timeout values
- **Content Filtering**: Reject unwanted MIME types with `GEMINI_DENIED_MIME_TYPES` (supports `type/*` wildcards)

## Troubleshooting

### Common Configuration Issues

1. **Invalid Boolean Values**

   ```
   Error: GEMINI_CACHE_ENABLED must be a boolean value
   Solution: Use true/false, 1/0, yes/no, on/off
   ```

2. **Allowlist That Names Nothing**

   ```
   Error: GEMINI_ALLOWED_HOSTS is set to ' , ' but names no hosts; unset it to allow all hosts.
   Solution: Remove the variable, or give it at least one host
   ```

3. **File Path Issues**

   ```
   Error: TOFU storage directory not writable
   Solution: Check directory permissions and ownership
   ```

4. **TOFU Certificate Mismatch**

   ```
   Error [CERTIFICATE_CHANGED]: Server certificate failed TOFU verification
   Solution: Inspect the pin with the gemini_trust_list tool, confirm out of band
   that the server legitimately rotated its certificate, then drop or replace that
   one host's pin with gemini_trust_update
   ```

   A fingerprint change is routine at expiry and is also what an active
   machine-in-the-middle attack looks like — the two are indistinguishable from
   the client, so confirm before changing a pin. Full procedure:
   [Gemini Troubleshooting](gemini-troubleshooting.md#problem-tofu-fingerprint-mismatch).
   Editing `~/.gemini/tofu.json` by hand still works but takes no lock and makes
   it easy to clear more trust than intended; prefer the tools.

### Diagnostic Commands

```bash
# Verify the package is installed and importable
python -c "import gopher_mcp; print(gopher_mcp.__version__)"

# Validate the current configuration
python scripts/validate-config.py

# Check certificate storage
ls -la ~/.gemini/

# Inspect a server's TLS handshake directly
openssl s_client -connect geminiprotocol.net:1965 -servername geminiprotocol.net
```

## Best Practices

### Configuration Management

1. **Use Environment Files**: Store configuration in `.env` files
2. **Version Control**: Keep example configurations in version control
3. **Documentation**: Document custom configuration choices
4. **Validation**: Always validate configuration before deployment

### Security Best Practices

1. **Principle of Least Privilege**: Use restrictive host allowlists
2. **Defense in Depth**: Enable multiple security features
3. **Regular Audits**: Periodically review security configuration
4. **Certificate Monitoring**: Monitor certificate validation failures

### Performance Best Practices

1. **Cache Tuning**: Adjust cache settings based on usage patterns
2. **Connection Limits**: Set appropriate connection limits
3. **Timeout Optimization**: Balance responsiveness with reliability
4. **Resource Monitoring**: Monitor memory and CPU usage

This configuration reference provides comprehensive guidance for configuring the Gemini protocol features of the MCP server for various deployment scenarios.
