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

#### `GEMINI_TOFU_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable Trust-on-First-Use certificate validation
- **Example**: `GEMINI_TOFU_ENABLED=true`

#### `GEMINI_CLIENT_CERTS_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable client certificate support
- **Example**: `GEMINI_CLIENT_CERTS_ENABLED=true`

### Storage Configuration

#### `GEMINI_TOFU_STORAGE_PATH`
- **Type**: String (file path)
- **Default**: `~/.gemini/tofu.json`
- **Description**: Path to TOFU certificate fingerprint storage file
- **Example**: `GEMINI_TOFU_STORAGE_PATH=/custom/path/tofu.json`

#### `GEMINI_CLIENT_CERT_STORAGE_PATH`
- **Type**: String (directory path)
- **Default**: `~/.gemini/client_certs/`
- **Description**: Directory for client certificate storage
- **Example**: `GEMINI_CLIENT_CERT_STORAGE_PATH=/custom/path/certs/`

### TLS Configuration

#### `GEMINI_TLS_VERSION`
- **Type**: String
- **Default**: `TLSv1.2`
- **Values**: `TLSv1.2`, `TLSv1.3`
- **Description**: Minimum TLS version for Gemini connections
- **Example**: `GEMINI_TLS_VERSION=TLSv1.3`

#### `GEMINI_TLS_VERIFY_HOSTNAME`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Verify hostname in TLS certificates
- **Example**: `GEMINI_TLS_VERIFY_HOSTNAME=true`

#### `GEMINI_TLS_CLIENT_CERT_PATH`
- **Type**: String (file path)
- **Default**: Empty
- **Description**: Path to custom client certificate file
- **Example**: `GEMINI_TLS_CLIENT_CERT_PATH=/path/to/cert.pem`

#### `GEMINI_TLS_CLIENT_KEY_PATH`
- **Type**: String (file path)
- **Default**: Empty
- **Description**: Path to custom client private key file
- **Example**: `GEMINI_TLS_CLIENT_KEY_PATH=/path/to/key.pem`

## Configuration Examples

### Development Configuration

```bash
# Development settings - relaxed security, no caching
GEMINI_CACHE_ENABLED=false
GEMINI_TOFU_ENABLED=false
GEMINI_CLIENT_CERTS_ENABLED=false
GEMINI_TIMEOUT_SECONDS=60
LOG_LEVEL=DEBUG
DEVELOPMENT_MODE=true
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
GEMINI_CLIENT_CERTS_ENABLED=true
GEMINI_TLS_VERSION=TLSv1.3
STRICT_HOST_VALIDATION=true
```

### High Security Configuration

```bash
# Maximum security settings
GEMINI_ALLOWED_HOSTS=trusted-host1.example.org,trusted-host2.example.org
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
GEMINI_TLS_VERSION=TLSv1.3
GEMINI_TLS_VERIFY_HOSTNAME=true
STRICT_HOST_VALIDATION=true
VALIDATE_CONTENT_TYPES=true
MAX_REDIRECTS=3
```

### Performance Optimized Configuration

```bash
# Optimized for high performance
GEMINI_MAX_RESPONSE_SIZE=5242880  # 5MB
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=1800     # 30 minutes
GEMINI_MAX_CACHE_ENTRIES=5000
MAX_CONCURRENT_CONNECTIONS=20
CONNECTION_POOL_SIZE=10
CONNECTION_KEEP_ALIVE=true
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
- TLS configuration consistency

## Security Considerations

### Certificate Storage

- **TOFU Storage**: Ensure TOFU storage file has proper permissions (600)
- **Client Certificates**: Store client certificates in protected directory (700)
- **Private Keys**: Protect private key files with restrictive permissions (600)

### Network Security

- **Host Allowlists**: Use restrictive host allowlists in production
- **TLS Version**: Use TLS 1.3 when possible for enhanced security
- **Certificate Validation**: Always enable TOFU in production environments

### Content Security

- **Size Limits**: Set appropriate response size limits
- **Timeout Protection**: Configure reasonable timeout values
- **Content Validation**: Enable content type validation

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

3. **TLS Configuration Conflicts**
   ```
   Error: Client cert specified without private key
   Solution: Provide both GEMINI_TLS_CLIENT_CERT_PATH and GEMINI_TLS_CLIENT_KEY_PATH
   ```

### Diagnostic Commands

```bash
# Test Gemini client initialization
python -c "from src.gopher_mcp.server import get_gemini_client; print('OK')"

# Check certificate storage
ls -la ~/.gemini/

# Validate TLS configuration
openssl version -a
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
