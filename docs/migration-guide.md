# Migration Guide

This guide helps existing users migrate from the Gopher-only version to the new dual-protocol Gopher & Gemini MCP Server.

## Overview

The server added comprehensive Gemini protocol support (introduced in v0.2.0) alongside the existing Gopher functionality. This was a **backward-compatible** change — all existing Gopher functionality remains unchanged.

## What's New

### New Features

- **Gemini Protocol Support**: Full implementation of Gemini v0.24.1
- **`gemini_fetch` Tool**: New MCP tool for Gemini protocol access
- **TLS Security**: Mandatory TLS with TOFU certificate validation
- **Client Certificates**: Scoped storage, attached automatically when present
- **Gemtext Parser**: Native gemtext parsing with structured output
- **Dual Caching**: Separate cache systems for each protocol

### Backward Compatibility

- ✅ All existing `gopher_fetch` functionality preserved
- ✅ Existing configuration variables unchanged
- ✅ No breaking changes to API or behavior
- ✅ Existing scripts and integrations continue to work

## Public API Changes

These affect code that imports from `gopher_mcp` directly. Nothing here changes
the MCP tool surface, so MCP clients are unaffected.

### Removed as unused

Importing any of these now raises `ImportError` (or `AttributeError` for the
methods):

| Removed | Was in |
|---------|--------|
| `guess_mime_type` | `gopher_mcp.utils` |
| `format_gopher_url` | `gopher_mcp.utils` |
| `validate_gemini_url_components` | `gopher_mcp.utils` |
| `sanitize_selector` | `gopher_mcp.utils` |
| `TOFUManager.cleanup_expired` | `gopher_mcp.tofu` |
| `ClientCertificateManager.cleanup_expired` | `gopher_mcp.client_certs` |

### Added to `gopher_mcp.utils`

| Added | Purpose |
|-------|---------|
| `sanitize_display_text` | Strip non-printable characters from server-controlled text before returning it |
| `resolve_gemini_reference` | Resolve a gemtext link or redirect target against the URL it was fetched from |

### `GeminiErrorResult` is now `ErrorResult`

The two error models were merged. `gopher_mcp.models.GeminiErrorResult` is an
alias for `ErrorResult`, so `isinstance(x, ErrorResult)` is now true for a Gemini
error and both spellings import fine. The merged model's `error` field is
`dict[str, Any]` rather than the old Gopher-only `dict[str, str]` — which is what
lets a Gemini failure carry the numeric `status` and boolean `temporary`
alongside `code` and `message`. Code that assumed `dict[str, str]` should read
`error["code"]` and use `error.get("status")` / `error.get("temporary")`.

### New tools and result fields

- Two tools were added: `gemini_trust_list` and `gemini_trust_update`, with the
  result models `TOFUTrustListResult` and `TOFUTrustUpdateResult`.
- Two more were added for client identities: `gemini_client_cert_list` and
  `gemini_client_cert_update`, with the result models
  `GeminiClientCertListResult` and `GeminiClientCertUpdateResult`. They make a
  status-60 (certificate required) capsule reachable, which it previously was
  not — deliberately, only on an explicit call, never automatically on a
  status-60 response.
- Cacheable result models grew `cached`, `cached_at` and `cache_age_seconds`;
  `gopher_fetch` and `gemini_fetch` grew an optional `refresh` argument, and
  `GopherClient.fetch` / `GeminiClient.fetch` grew a keyword-only `refresh`.
  Both are additive.
- `GeminiCertificateResult` grew `next_step`: this server's own instruction for
  that status (60, 61 and 62 need different answers), beside the capsule's
  untrusted `message`.

### Client-certificate store changes

Embedders driving `ClientCertificateManager` directly should know three things:

- Certificate and key files are now named after a random per-certificate
  `key_id`, recorded in `registry.json`, instead of the certificate's common
  name — two identities on one host could share that name and so share one key
  pair. Existing entries have no `key_id` and keep resolving to their
  common-name filenames, so no store needs migrating.
- `generate_certificate` and `remove_certificate` roll back their in-memory
  change if the registry cannot be persisted, so a raised error now always
  means the store is unchanged.
- `remove_certificate` raises `ClientCertificateKeyRetainedError` (a
  `ClientCertificateError`) when the registry entry was removed but the private
  key file survived its unlink, rather than returning True as though the key
  had been destroyed.
- `ClientCertificateManager.get_certificate_info_for_scope` is new: the same
  resolution `get_certificate_for_scope` performs, returning the registry entry
  instead of file paths.

## Migration Steps

### 1. Update Dependencies

If you're using pip:

```bash
pip install --upgrade gopher-mcp
```

If you're using uv:

```bash
uv sync
```

### 2. Review New Configuration Options

The server now supports additional environment variables for Gemini:

```bash
# Optional Gemini configuration (all have sensible defaults)
GEMINI_MAX_RESPONSE_SIZE=1048576
GEMINI_TIMEOUT_SECONDS=30
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=300
GEMINI_MAX_CACHE_ENTRIES=1000
GEMINI_ALLOWED_HOSTS=
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
```

**Important**: You don't need to set these variables. The server will use sensible defaults.

### 3. Test Existing Functionality

Verify your existing Gopher functionality still works:

```python
# This should work exactly as before
result = await gopher_fetch("gopher://gopher.floodgap.com/1/")
print(result["kind"])  # Should be "menu" or "text"
```

### 4. Try New Gemini Features

Test the new Gemini functionality:

```python
# New Gemini support
result = await gemini_fetch("gemini://geminiprotocol.net/")
print(result["kind"])  # Should be "gemtext", "text", or other types
```

## Configuration Migration

### Existing Configuration

Your existing configuration continues to work unchanged:

```bash
# These variables work exactly as before
GOPHER_MAX_RESPONSE_SIZE=1048576
GOPHER_TIMEOUT_SECONDS=30
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=300
GOPHER_MAX_CACHE_ENTRIES=1000
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org
```

### New Optional Configuration

You can optionally add Gemini configuration:

```bash
# Add these if you want to customize Gemini behavior
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CACHE_TTL_SECONDS=600
```

### Configuration Validation

Use the new validation script to check your configuration:

```bash
python scripts/validate-config.py
```

## Feature Comparison

| Feature | Gopher | Gemini | Notes |
|---------|--------|--------|-------|
| Protocol | Plain text | TLS encrypted | Gemini requires TLS |
| Content Format | Plain text/binary | Gemtext/binary | Gemini has rich text format |
| Caching | ✅ | ✅ | Separate cache systems |
| Host Allowlists | ✅ | ✅ | Independent configuration |
| Timeout Configuration | ✅ | ✅ | Independent settings |
| Certificate Validation | N/A | ✅ TOFU | Gemini-specific security; inspect and recover with `gemini_trust_list` / `gemini_trust_update` |
| Client Certificates | N/A | ✅ Scoped storage | Attached automatically when one exists; create or remove one deliberately with `gemini_client_cert_update` |

## Common Migration Scenarios

### Scenario 1: Basic User (No Custom Configuration)

**Before**: Using default Gopher settings
**After**: Everything works the same, plus Gemini is available

**Action Required**: None! Just update and start using `gemini_fetch` when needed.

### Scenario 2: Custom Gopher Configuration

**Before**: Custom timeout, cache, or host allowlist settings
**After**: Gopher settings unchanged, can optionally configure Gemini

**Action Required**:

1. Keep existing configuration
2. Optionally add Gemini-specific settings if desired

### Scenario 3: Security-Conscious User

**Before**: Using Gopher host allowlists for security
**After**: Same Gopher security, plus enhanced Gemini security

**Recommended Actions**:

```bash
# Keep existing Gopher allowlist
GOPHER_ALLOWED_HOSTS=trusted-gopher-hosts.com

# Add Gemini allowlist for consistency
GEMINI_ALLOWED_HOSTS=trusted-gemini-hosts.org

# Ensure TOFU is enabled (default)
GEMINI_TOFU_ENABLED=true
```

### Scenario 4: High-Performance User

**Before**: Optimized cache settings for Gopher
**After**: Can optimize both protocols independently

**Recommended Actions**:

```bash
# Keep existing Gopher optimization
GOPHER_CACHE_TTL_SECONDS=1800
GOPHER_MAX_CACHE_ENTRIES=5000

# Add similar Gemini optimization
GEMINI_CACHE_TTL_SECONDS=1800
GEMINI_MAX_CACHE_ENTRIES=5000
```

## Troubleshooting Migration Issues

### Issue: "Module not found" errors

**Cause**: Incomplete installation or environment issues
**Solution**:

```bash
# Reinstall completely
pip uninstall gopher-mcp
pip install gopher-mcp

# Or with uv
uv sync --reinstall
```

### Issue: Configuration validation errors

**Cause**: Invalid configuration values
**Solution**:

```bash
# Run validation to see specific issues
python scripts/validate-config.py

# Reset problematic variables to defaults
unset PROBLEMATIC_VARIABLE
```

### Issue: Gemini connections fail

**Cause**: Network or TLS configuration issues
**Solution**:

```bash
# Test with relaxed security (development only)
export GEMINI_TOFU_ENABLED=false

# Check network connectivity
ping geminiprotocol.net
```

### Issue: Certificate storage errors

**Cause**: Permission or disk space issues
**Solution**:

```bash
# Check and fix permissions
mkdir -p ~/.gemini
chmod 700 ~/.gemini

# Check disk space
df -h ~/.gemini
```

## Best Practices for Migration

### 1. Gradual Adoption

- Start with existing Gopher functionality
- Gradually introduce Gemini features
- Test both protocols in development first

### 2. Configuration Management

- Use the provided `config/example.env` as a template
- Validate configuration before deployment
- Document any custom settings

### 3. Security Considerations

- Enable TOFU for Gemini in production
- Use host allowlists for both protocols
- Monitor certificate validation logs

### 4. Performance Optimization

- Monitor cache hit rates for both protocols
- Adjust cache settings based on usage patterns
- Consider separate timeout values for each protocol

## Testing Your Migration

### 1. Functional Testing

```bash
# Test Gopher functionality
python -c "
import asyncio
from gopher_mcp.server import gopher_fetch

async def test():
    result = await gopher_fetch('gopher://gopher.floodgap.com/1/')
    print(f'Gopher test: {result[\"kind\"]}')

asyncio.run(test())
"

# Test Gemini functionality
python -c "
import asyncio
from gopher_mcp.server import gemini_fetch

async def test():
    result = await gemini_fetch('gemini://geminiprotocol.net/')
    print(f'Gemini test: {result[\"kind\"]}')

asyncio.run(test())
"
```

### 2. Configuration Testing

```bash
# Validate all configuration
python scripts/validate-config.py

# Test with your specific configuration
export YOUR_CONFIG_VARS=values
python scripts/validate-config.py
```

### 3. Integration Testing

```bash
# Run the full test suite
python -m pytest tests/ -v

# Run only integration tests
python -m pytest tests/test_server.py -v
```

## Getting Help

If you encounter issues during migration:

1. **Check the logs** with debug logging enabled:

   ```bash
   export GOPHER_MCP_LOG_LEVEL=DEBUG
   ```

2. **Validate your configuration**:

   ```bash
   python scripts/validate-config.py
   ```

3. **Review the troubleshooting guide**:
   See `docs/gemini-troubleshooting.md`

4. **Test with minimal configuration**:
   Remove all custom environment variables and test with defaults

5. **Check GitHub issues**:
   Look for similar migration issues

6. **Create a new issue**:
   Include your configuration and error details

## Summary

The migration to the dual-protocol server is designed to be seamless:

- ✅ **Zero breaking changes** to existing functionality
- ✅ **Backward compatibility** maintained
- ✅ **Optional new features** available when needed
- ✅ **Independent configuration** for each protocol
- ✅ **Comprehensive documentation** and tooling

You can migrate at your own pace, starting with the update and gradually exploring the new Gemini features as needed.
