# Configuration Guide

The Gopher & Gemini MCP Server can be configured through environment variables for both protocols.

## Gopher Configuration

| Variable                   | Description                    | Default         | Example                |
| -------------------------- | ------------------------------ | --------------- | ---------------------- |
| `GOPHER_MAX_RESPONSE_SIZE` | Maximum response size in bytes | `1048576` (1MB) | `2097152`              |
| `GOPHER_TIMEOUT_SECONDS`   | Request timeout in seconds     | `30`            | `60`                   |
| `GOPHER_CACHE_ENABLED`     | Enable response caching        | `true`          | `false`                |
| `GOPHER_CACHE_TTL_SECONDS` | Cache time-to-live in seconds  | `300`           | `600`                  |
| `GOPHER_ALLOWED_HOSTS`     | Comma-separated allowed hosts  | `None` (all)    | `example.com,test.com` |

## Gemini Configuration

| Variable                      | Description                        | Default         | Example                |
| ----------------------------- | ---------------------------------- | --------------- | ---------------------- |
| `GEMINI_MAX_RESPONSE_SIZE`    | Maximum response size in bytes     | `1048576` (1MB) | `2097152`              |
| `GEMINI_TIMEOUT_SECONDS`      | Request timeout in seconds         | `30`            | `60`                   |
| `GEMINI_CACHE_ENABLED`        | Enable response caching            | `true`          | `false`                |
| `GEMINI_CACHE_TTL_SECONDS`    | Cache time-to-live in seconds      | `300`           | `600`                  |
| `GEMINI_ALLOWED_HOSTS`        | Comma-separated allowed hosts      | `None` (all)    | `example.org,test.org` |
| `GEMINI_TOFU_ENABLED`         | Enable TOFU certificate validation | `true`          | `false`                |
| `GEMINI_CLIENT_CERTS_ENABLED` | Enable client certificate support  | `true`          | `false`                |

## Configuration Methods

### Method 1: Environment Variables

Set environment variables in your shell:

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
export GEMINI_ALLOWED_HOSTS="geminiprotocol.net,warmedal.se"

# Run with custom config
uv run task serve
```

### Method 2: .env File

Create a `.env` file in the project root:

```bash
# Gopher Configuration
GOPHER_MAX_RESPONSE_SIZE=2097152
GOPHER_TIMEOUT_SECONDS=60
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=600
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org

# Gemini Configuration
GEMINI_MAX_RESPONSE_SIZE=2097152
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=600
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se
```

### Method 3: Claude Desktop Config

Add environment variables to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": ["--directory", "/path/to/gopher-mcp", "run", "task", "serve"],
      "env": {
        "GOPHER_MAX_RESPONSE_SIZE": "2097152",
        "GOPHER_TIMEOUT_SECONDS": "60",
        "GOPHER_CACHE_ENABLED": "true",
        "GEMINI_MAX_RESPONSE_SIZE": "2097152",
        "GEMINI_TIMEOUT_SECONDS": "60",
        "GEMINI_TOFU_ENABLED": "true"
      }
    }
  }
}
```

## Configuration Examples

### High Security Configuration

```bash
# Strict security settings
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com
GOPHER_MAX_RESPONSE_SIZE=524288
GOPHER_TIMEOUT_SECONDS=15

GEMINI_ALLOWED_HOSTS=geminiprotocol.net
GEMINI_MAX_RESPONSE_SIZE=524288
GEMINI_TIMEOUT_SECONDS=15
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
```

### Performance Configuration

```bash
# Optimized for performance
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=900
GOPHER_MAX_RESPONSE_SIZE=5242880
GOPHER_TIMEOUT_SECONDS=60

GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=900
GEMINI_MAX_RESPONSE_SIZE=5242880
GEMINI_TIMEOUT_SECONDS=60
```

### Development Configuration

```bash
# Development settings
GOPHER_CACHE_ENABLED=false
GOPHER_TIMEOUT_SECONDS=120
GEMINI_CACHE_ENABLED=false
GEMINI_TIMEOUT_SECONDS=120
GEMINI_TOFU_ENABLED=false
```

## Security Considerations

- **Host Allowlists**: Use `ALLOWED_HOSTS` to restrict which servers can be accessed
- **Response Size Limits**: Set appropriate `MAX_RESPONSE_SIZE` to prevent memory issues
- **Timeouts**: Configure `TIMEOUT_SECONDS` to prevent hanging requests
- **TOFU Validation**: Keep `GEMINI_TOFU_ENABLED=true` for certificate security
- **Client Certificates**: Enable `GEMINI_CLIENT_CERTS_ENABLED` for authenticated access

## Next Steps

- [Security Features](Security-Features) - Learn about security features
- [Advanced Features](Advanced-Features) - Explore advanced configuration
- [Troubleshooting](Troubleshooting) - Common configuration issues

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
