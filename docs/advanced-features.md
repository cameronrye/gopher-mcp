# Advanced Features

This document describes the advanced features of the Gopher & Gemini MCP Server, including security safeguards, performance optimizations, and configuration options for both protocols.

## Security Safeguards

The Gopher client includes comprehensive security features to protect against malicious content and ensure safe operation:

### Input Validation

- **Selector Length Limits**: Configurable maximum selector string length (default: 1024 characters)
- **Search Query Limits**: Configurable maximum search query length (default: 256 characters)
- **Control Character Filtering**: Rejects selectors and search queries containing dangerous control characters (CR, LF, TAB)
- **Port Validation**: Ensures port numbers are within valid range (1-65535)

### Host Allowlisting

Configure allowed Gopher hosts to restrict access to trusted servers:

```python
client = GopherClient(
    allowed_hosts=["gopher.floodgap.com", "gopher.quux.org"]
)
```

Environment variable configuration:
```bash
export GOPHER_ALLOWED_HOSTS="gopher.floodgap.com,gopher.quux.org"
```

### Size and Timeout Limits

- **Response Size Limits**: Maximum response size (default: 1MB)
- **Request Timeouts**: Configurable timeout for Gopher requests (default: 30 seconds)
- **Cache Size Limits**: Maximum number of cached entries (default: 1000)

## Caching System

The client implements an intelligent LRU (Least Recently Used) caching system:

### Features

- **TTL-based Expiration**: Configurable time-to-live for cached responses (default: 5 minutes)
- **LRU Eviction**: Automatically removes oldest entries when cache is full
- **Cache Hit/Miss Tracking**: Structured logging for cache performance monitoring
- **Memory Efficient**: Stores only essential response data

### Configuration

```python
client = GopherClient(
    cache_enabled=True,
    cache_ttl_seconds=300,  # 5 minutes
    max_cache_entries=1000
)
```

Environment variables:
```bash
export GOPHER_CACHE_ENABLED=true
export GOPHER_CACHE_TTL_SECONDS=300
export GOPHER_MAX_CACHE_ENTRIES=1000
```

## Transport Support

The MCP server supports both stdio and HTTP transports for maximum flexibility:

### Stdio Transport (Default)

Best for local desktop applications like Claude Desktop:

```bash
uv run task serve
```

### HTTP Transport

Ideal for remote access and web-based integrations:

```bash
# Install HTTP dependencies
uv add --optional-group http

# Start HTTP server
uv run task serve-http
```

Configuration:
```bash
export GOPHER_HTTP_HOST=localhost
export GOPHER_HTTP_PORT=8000
```

### HTTP API

The HTTP transport provides a JSON-RPC 2.0 API:

**Endpoint**: `POST /mcp`
**Health Check**: `GET /health`

Example request:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "gopher_fetch",
    "arguments": {
      "url": "gopher://gopher.floodgap.com/1/"
    }
  }
}
```

## Structured Logging

Comprehensive logging with structured data for monitoring and debugging:

### Log Fields

- **Request Details**: URL, host, port, gopher type, selector, search query
- **Response Metadata**: Type, size, cache status
- **Performance Metrics**: Request duration, cache hit/miss ratios
- **Error Information**: Error type, message, stack traces

### Example Log Output

```json
{
  "event": "Gopher fetch successful",
  "url": "gopher://gopher.floodgap.com/1/",
  "host": "gopher.floodgap.com",
  "port": 70,
  "gopher_type": "1",
  "selector": "",
  "search": null,
  "response_type": "menu",
  "response_size": 2048,
  "cached": false,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Search Functionality

Full support for Gopher search servers (type 7):

### URL Formats

Standard query parameter:
```
gopher://veronica.example.com/7/search?python
```

Tab-encoded format:
```
gopher://veronica.example.com/7/search%09python
```

### Search Processing

- Automatic detection of search servers
- Proper tab-separated query encoding
- Search results returned as structured menu data
- Support for complex search queries

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GOPHER_MAX_RESPONSE_SIZE` | 1048576 | Maximum response size in bytes |
| `GOPHER_TIMEOUT_SECONDS` | 30.0 | Request timeout in seconds |
| `GOPHER_CACHE_ENABLED` | true | Enable response caching |
| `GOPHER_CACHE_TTL_SECONDS` | 300 | Cache TTL in seconds |
| `GOPHER_MAX_CACHE_ENTRIES` | 1000 | Maximum cache entries |
| `GOPHER_ALLOWED_HOSTS` | - | Comma-separated list of allowed hosts |
| `GOPHER_MAX_SELECTOR_LENGTH` | 1024 | Maximum selector length |
| `GOPHER_MAX_SEARCH_LENGTH` | 256 | Maximum search query length |
| `GOPHER_HTTP_HOST` | localhost | HTTP server host |
| `GOPHER_HTTP_PORT` | 8000 | HTTP server port |

### Programmatic Configuration

```python
from gopher_mcp.gopher_client import GopherClient

client = GopherClient(
    max_response_size=2 * 1024 * 1024,  # 2MB
    timeout_seconds=60.0,
    cache_enabled=True,
    cache_ttl_seconds=600,  # 10 minutes
    max_cache_entries=2000,
    allowed_hosts=["trusted.gopher.site"],
    max_selector_length=2048,
    max_search_length=512,
)
```

## Performance Considerations

- **Caching**: Significantly reduces response times for repeated requests
- **Connection Reuse**: Pituophis handles connection pooling efficiently
- **Async Processing**: Non-blocking I/O for concurrent requests
- **Memory Management**: Automatic cache eviction prevents memory leaks
- **Size Limits**: Prevents resource exhaustion from large responses

## Gemini Protocol Advanced Features

### TOFU Certificate Validation

The Gemini client implements Trust-on-First-Use (TOFU) certificate validation:

```bash
# Enable TOFU validation
GEMINI_TOFU_ENABLED=true

# Custom TOFU storage location
GEMINI_TOFU_STORAGE_PATH=/custom/path/tofu.json
```

**TOFU Workflow:**
- First connection stores certificate fingerprint
- Subsequent connections verify against stored fingerprint
- Certificate changes trigger validation errors
- Manual intervention required for certificate updates

### Client Certificate Management

Automatic client certificate generation and management:

```bash
# Enable client certificate support
GEMINI_CLIENT_CERTS_ENABLED=true

# Custom certificate storage directory
GEMINI_CLIENT_CERT_STORAGE_PATH=/custom/path/certs/
```

**Features:**
- Automatic certificate generation per hostname/path scope
- Secure private key storage with proper permissions
- Certificate reuse within the same scope
- Scope-based certificate isolation

### TLS Security Configuration

Advanced TLS settings for enhanced security:

```bash
# Minimum TLS version
GEMINI_TLS_VERSION=TLSv1.3

# Hostname verification
GEMINI_TLS_VERIFY_HOSTNAME=true

# Custom client certificates
GEMINI_TLS_CLIENT_CERT_PATH=/path/to/cert.pem
GEMINI_TLS_CLIENT_KEY_PATH=/path/to/key.pem
```

### Gemini Caching System

Intelligent caching for Gemini responses:

```bash
# Gemini cache configuration
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=600
GEMINI_MAX_CACHE_ENTRIES=2000
```

**Cache Features:**
- Protocol-isolated caching (separate from Gopher cache)
- TTL-based expiration
- LRU eviction when cache is full
- Cache key generation for gemini:// URLs

### Gemini Host Allowlists

Restrict access to trusted Gemini servers:

```bash
# Comma-separated list of allowed Gemini hosts
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se,kennedy.gemi.dev
```

## Security Best Practices

### Gopher Protocol
1. **Use Host Allowlists**: Restrict access to trusted Gopher servers
2. **Set Reasonable Limits**: Configure appropriate size and timeout limits
3. **Monitor Logs**: Use structured logging for security monitoring

### Gemini Protocol
1. **Enable TOFU**: Always use TOFU certificate validation in production
2. **Use TLS 1.3**: Configure minimum TLS version for enhanced security
3. **Client Certificates**: Enable client certificate support for authenticated access
4. **Host Allowlists**: Restrict access to trusted Gemini servers
5. **Certificate Monitoring**: Monitor certificate validation failures

### General
1. **Regular Updates**: Keep dependencies updated for security patches
2. **Network Isolation**: Consider running in isolated network environments
3. **Structured Logging**: Use structured logging for security monitoring
4. **Configuration Validation**: Use the configuration validation script
