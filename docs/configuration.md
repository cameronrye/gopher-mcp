# Configuration Guide

This comprehensive guide covers all configuration options for the Gopher & Gemini MCP Server.

## Overview

The server is configured entirely through environment variables, making it easy to customize behavior without modifying code. All configuration is optional - the server works out of the box with sensible defaults.

## Configuration Methods

### 1. Environment Variables

Set environment variables in your shell:

```bash
export GOPHER_MAX_RESPONSE_SIZE=2097152
export GEMINI_TIMEOUT_SECONDS=60
```

### 2. Configuration File

Create a `.env` file in your project directory:

```bash
# Copy the example configuration
cp config/example.env .env

# Edit with your preferred settings
nano .env
```

### 3. MCP Client Configuration

Configure in your MCP client (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": ["--directory", "/path/to/gopher-mcp", "run", "task", "serve"],
      "env": {
        "GOPHER_MAX_RESPONSE_SIZE": "2097152",
        "GEMINI_TIMEOUT_SECONDS": "60",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Gopher Protocol Configuration

### Core Settings

#### `GOPHER_MAX_RESPONSE_SIZE`
- **Type**: Integer (bytes)
- **Default**: `1048576` (1MB)
- **Range**: `1024` - `104857600` (1KB - 100MB)
- **Description**: Maximum size of Gopher response content
- **Example**: `GOPHER_MAX_RESPONSE_SIZE=2097152`

#### `GOPHER_TIMEOUT_SECONDS`
- **Type**: Float (seconds)
- **Default**: `30.0`
- **Range**: `1.0` - `300.0`
- **Description**: Request timeout for Gopher connections
- **Example**: `GOPHER_TIMEOUT_SECONDS=60.0`

### Caching Configuration

#### `GOPHER_CACHE_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true`, `false`
- **Description**: Enable/disable response caching
- **Example**: `GOPHER_CACHE_ENABLED=true`

#### `GOPHER_CACHE_TTL_SECONDS`
- **Type**: Integer (seconds)
- **Default**: `300` (5 minutes)
- **Range**: `1` - `86400` (1 second - 24 hours)
- **Description**: How long cached responses remain valid
- **Example**: `GOPHER_CACHE_TTL_SECONDS=600`

#### `GOPHER_MAX_CACHE_ENTRIES`
- **Type**: Integer
- **Default**: `1000`
- **Range**: `1` - `10000`
- **Description**: Maximum number of cached responses
- **Example**: `GOPHER_MAX_CACHE_ENTRIES=2000`

### Security Settings

#### `GOPHER_ALLOWED_HOSTS`
- **Type**: Comma-separated list
- **Default**: Empty (all hosts allowed)
- **Description**: Restrict connections to specific hosts
- **Example**: `GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org`

## Gemini Protocol Configuration

### Core Settings

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
- **Values**: `true`, `false`
- **Description**: Enable/disable response caching
- **Example**: `GEMINI_CACHE_ENABLED=true`

#### `GEMINI_CACHE_TTL_SECONDS`
- **Type**: Integer (seconds)
- **Default**: `300` (5 minutes)
- **Range**: `1` - `86400`
- **Description**: How long cached responses remain valid
- **Example**: `GEMINI_CACHE_TTL_SECONDS=600`

#### `GEMINI_MAX_CACHE_ENTRIES`
- **Type**: Integer
- **Default**: `1000`
- **Range**: `1` - `10000`
- **Description**: Maximum number of cached responses
- **Example**: `GEMINI_MAX_CACHE_ENTRIES=2000`

### Security Settings

#### `GEMINI_ALLOWED_HOSTS`
- **Type**: Comma-separated list
- **Default**: Empty (all hosts allowed)
- **Description**: Restrict connections to specific hosts
- **Example**: `GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se`

#### `GEMINI_TOFU_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true`, `false`
- **Description**: Enable Trust-on-First-Use certificate validation
- **Example**: `GEMINI_TOFU_ENABLED=true`

#### `GEMINI_TOFU_STORAGE_PATH`
- **Type**: File path
- **Default**: `~/.gemini/tofu.json`
- **Description**: Path to TOFU certificate storage
- **Example**: `GEMINI_TOFU_STORAGE_PATH=/custom/path/tofu.json`

#### `GEMINI_CLIENT_CERTS_ENABLED`
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true`, `false`
- **Description**: Enable automatic client certificate generation
- **Example**: `GEMINI_CLIENT_CERTS_ENABLED=true`

#### `GEMINI_CLIENT_CERTS_STORAGE_PATH`
- **Type**: Directory path
- **Default**: `~/.gemini/client_certs`
- **Description**: Path to client certificate storage directory
- **Example**: `GEMINI_CLIENT_CERTS_STORAGE_PATH=/custom/path/certs`

## Logging Configuration

### `LOG_LEVEL`
- **Type**: String
- **Default**: `INFO`
- **Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Description**: Logging verbosity level
- **Example**: `LOG_LEVEL=DEBUG`

### `STRUCTURED_LOGGING`
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true`, `false`
- **Description**: Enable structured JSON logging
- **Example**: `STRUCTURED_LOGGING=true`

### `LOG_FILE_PATH`
- **Type**: File path
- **Default**: Empty (logs to stdout)
- **Description**: Optional file path for log output
- **Example**: `LOG_FILE_PATH=/var/log/gopher-mcp.log`

## MCP Server Configuration

### `MCP_SERVER_NAME`
- **Type**: String
- **Default**: `gopher-gemini-mcp`
- **Description**: Server name for MCP identification
- **Example**: `MCP_SERVER_NAME=my-custom-server`

### `MCP_SERVER_VERSION`
- **Type**: String
- **Default**: Auto-detected from package
- **Description**: Server version for MCP identification
- **Example**: `MCP_SERVER_VERSION=1.0.0`

## Development Configuration

### `DEVELOPMENT_MODE`
- **Type**: Boolean
- **Default**: `false`
- **Values**: `true`, `false`
- **Description**: Enable development mode with relaxed security
- **Example**: `DEVELOPMENT_MODE=true`

### `DEBUG_COMPONENTS`
- **Type**: Comma-separated list
- **Default**: Empty
- **Values**: `gopher_client`, `gemini_client`, `gemini_tls`, `tofu`, `client_certs`
- **Description**: Enable debug logging for specific components
- **Example**: `DEBUG_COMPONENTS=gemini_client,gemini_tls`

## Configuration Presets

### Minimal Configuration (Defaults)

```bash
# No configuration needed - uses all defaults
# Suitable for: Testing, basic usage
```

### Development Configuration

```bash
# Relaxed security, verbose logging, no caching
DEVELOPMENT_MODE=true
LOG_LEVEL=DEBUG
DEBUG_COMPONENTS=gopher_client,gemini_client,gemini_tls
GOPHER_CACHE_ENABLED=false
GEMINI_CACHE_ENABLED=false
GEMINI_TOFU_ENABLED=false
GEMINI_CLIENT_CERTS_ENABLED=false
```

### Production Configuration

```bash
# High security, optimized performance
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

LOG_LEVEL=INFO
STRUCTURED_LOGGING=true
```

### High Performance Configuration

```bash
# Optimized for speed with larger caches
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=1800
GOPHER_MAX_CACHE_ENTRIES=5000

GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=1800
GEMINI_MAX_CACHE_ENTRIES=5000

LOG_LEVEL=WARNING
```

### Privacy-Focused Configuration

```bash
# No caching, minimal logging
GOPHER_CACHE_ENABLED=false
GEMINI_CACHE_ENABLED=false
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=false
STRUCTURED_LOGGING=false
LOG_LEVEL=ERROR
```

### Restricted Access Configuration

```bash
# Only allow specific trusted hosts
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se,kennedy.gemi.dev
GEMINI_TOFU_ENABLED=true
LOG_LEVEL=INFO
```

## Configuration Validation

### Validation Script

Use the built-in validation script to check your configuration:

```bash
python scripts/validate-config.py
```

### Common Validation Errors

1. **Invalid size values**: Must be positive integers within range
2. **Invalid timeout values**: Must be positive floats within range
3. **Invalid boolean values**: Only `true` or `false` accepted
4. **Invalid paths**: Must be valid file system paths
5. **Invalid host lists**: Must be comma-separated without spaces

## Environment Variable Precedence

Configuration is loaded in this order (later overrides earlier):

1. Default values (hardcoded in source)
2. Configuration file (`.env`)
3. Environment variables
4. MCP client configuration

## Troubleshooting

### Configuration Not Applied

1. Check environment variable names (case-sensitive)
2. Verify boolean values are exactly `true` or `false`
3. Ensure numeric values are within valid ranges
4. Restart the server after configuration changes

### Performance Issues

1. Increase cache size: `GOPHER_MAX_CACHE_ENTRIES`, `GEMINI_MAX_CACHE_ENTRIES`
2. Increase cache TTL: `GOPHER_CACHE_TTL_SECONDS`, `GEMINI_CACHE_TTL_SECONDS`
3. Increase timeouts if needed: `GOPHER_TIMEOUT_SECONDS`, `GEMINI_TIMEOUT_SECONDS`

### Security Concerns

1. Enable TOFU: `GEMINI_TOFU_ENABLED=true`
2. Restrict hosts: `GOPHER_ALLOWED_HOSTS`, `GEMINI_ALLOWED_HOSTS`
3. Disable development mode: `DEVELOPMENT_MODE=false`
4. Set appropriate log level: `LOG_LEVEL=INFO` or `WARNING`

## See Also

- [Gemini Configuration Reference](gemini-configuration.md) - Detailed Gemini-specific configuration
- [Advanced Features](advanced-features.md) - Advanced configuration scenarios
- [Installation Guide](installation.md) - Initial setup and configuration
- [API Reference](api-reference.md) - API documentation
