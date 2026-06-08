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
- **Range**: `1.0` - `300.0`
- **Description**: Request timeout for Gemini connections
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
- **Range**: `1` - `86400` (1 second - 24 hours)
- **Description**: Time-to-live for cached Gemini responses
- **Example**: `GEMINI_CACHE_TTL_SECONDS=600`

#### `GEMINI_MAX_CACHE_ENTRIES`
- **Type**: Integer
- **Default**: `1000`
- **Range**: `1` - `100000`
- **Description**: Maximum number of entries in Gemini cache
- **Example**: `GEMINI_MAX_CACHE_ENTRIES=2000`

### Security Configuration

#### `GEMINI_ALLOWED_HOSTS`
- **Type**: String (comma-separated)
- **Default**: Empty (all hosts allowed)
- **Description**: Comma-separated list of allowed Gemini hosts
- **Example**: `GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se,kennedy.gemi.dev`

#### `GEMINI_ALLOW_LOCAL_HOSTS`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Allow connections to loopback/private/internal addresses. Disabled by default to prevent SSRF.
- **Example**: `GEMINI_ALLOW_LOCAL_HOSTS=false`

#### `GEMINI_TOFU_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable Trust-on-First-Use certificate validation. Gemini TLS runs without CA-chain validation, so TOFU is the only peer authentication; disabling it leaves connections unauthenticated and MITM-able.
- **Example**: `GEMINI_TOFU_ENABLED=true`

#### `GEMINI_TOFU_REJECT_EXPIRED`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Fail closed when a server certificate is outside its validity window (already expired, or not yet valid on first use) instead of pinning it with a warning. Off by default to match the conventional Gemini TOFU model, where the pinned fingerprint is the real authenticator.
- **Example**: `GEMINI_TOFU_REJECT_EXPIRED=true`

#### `GEMINI_CLIENT_CERTS_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable automatic client certificate generation and management. Certificates are created and reused per host/path scope on demand; you do not supply cert/key files yourself.
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
- **Description**: Directory where automatically generated client certificates and their private keys are stored. The directory is created with owner-only (`700`) permissions.
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
- **Default**: `0` (unlimited)
- **Range**: `0` - `6000`
- **Description**: Per-host outbound request rate cap, for politeness toward small Gemini servers. A status-44 `SLOW_DOWN` response is always honoured regardless of this setting.
- **Example**: `GEMINI_REQUESTS_PER_MINUTE=60`

#### `GEMINI_MAX_CONCURRENT_REQUESTS`
- **Type**: Integer
- **Default**: `0` (unlimited)
- **Range**: `0` - `1000`
- **Description**: Cap on simultaneous in-flight fetches; a coarse bound on concurrent sockets and memory, complementary to the per-host rate limit. Off by default.
- **Example**: `GEMINI_MAX_CONCURRENT_REQUESTS=20`

#### `GEMINI_DENIED_MIME_TYPES`
- **Type**: String (comma-separated)
- **Default**: Empty (no content filtering)
- **Description**: MIME types, or `type/*` wildcards, to reject as filtered content. Empty means no content filtering.
- **Example**: `GEMINI_DENIED_MIME_TYPES=text/html,image/*`

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
GOPHER_MCP_DEVELOPMENT_MODE=true
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
# Validate current configuration
python scripts/validate-config.py

# Or use the task runner
uv run task validate-config
```

The validator checks:
- Value ranges and types
- File path existence
- Boolean value formats
- Host list formatting

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

2. **File Path Issues**
   ```
   Error: TOFU storage directory not writable
   Solution: Check directory permissions and ownership
   ```

3. **TOFU Certificate Mismatch**
   ```
   Error: TOFU validation failed: certificate fingerprint changed
   Solution: Confirm the server legitimately rotated its certificate, then remove the
   stale host entry from ~/.gemini/tofu.json (or delete the file to re-pin on next use)
   ```

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
