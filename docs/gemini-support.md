# Gemini Protocol Support

This document provides comprehensive information about the Gemini protocol support in the Gopher & Gemini MCP Server.

## Overview

The Gemini protocol is a modern, lightweight internet protocol that sits between Gopher and the Web. It features:

- **Mandatory TLS encryption** for all connections
- **Simple text-based markup** (gemtext) for content
- **Privacy-focused design** with minimal client tracking
- **Certificate-based authentication** for enhanced security

## Features

### Core Protocol Support

- ✅ **Full Gemini 0.16.1 specification compliance**
- ✅ **TLS 1.2+ with SNI support**
- ✅ **All status codes (10-69) handled**
- ✅ **Native gemtext parsing and structured output**
- ✅ **Binary content detection and handling**
- ✅ **URL validation and normalization**

### Security Features

- ✅ **TOFU (Trust-on-First-Use) certificate validation**
- ✅ **Client certificate generation and management**
- ✅ **Scope-based certificate isolation**
- ✅ **Certificate fingerprint verification**
- ✅ **Secure certificate storage**
- ✅ **Host allowlist support**

### Performance Features

- ✅ **Intelligent response caching**
- ✅ **Async/await architecture**
- ✅ **Connection pooling and reuse**
- ✅ **Configurable timeouts and limits**
- ✅ **Memory-efficient streaming**

## Usage

### Basic Fetching

```python
# Fetch a Gemini page
result = await gemini_fetch("gemini://geminiprotocol.net/")

# The result will be one of:
# - GeminiGemtextResult: For gemtext content
# - GeminiSuccessResult: For other content types
# - GeminiInputResult: For input requests
# - GeminiRedirectResult: For redirects
# - GeminiErrorResult: For errors
# - GeminiCertificateResult: For certificate requests
```

### Response Types

#### GeminiGemtextResult

For `text/gemini` content, returns a structured document:

```json
{
  "kind": "gemtext",
  "document": {
    "lines": [
      {"type": "heading1", "text": "Welcome to Gemini"},
      {"type": "text", "text": "This is a paragraph."},
      {"type": "link", "url": "gemini://example.org/", "text": "Example Link"}
    ],
    "links": [
      {"url": "gemini://example.org/", "text": "Example Link", "line_number": 3}
    ],
    "headings": [
      {"level": 1, "text": "Welcome to Gemini", "line_number": 1}
    ]
  },
  "raw_content": "# Welcome to Gemini\nThis is a paragraph.\n=> gemini://example.org/ Example Link",
  "charset": "utf-8",
  "size": 67
}
```

#### GeminiSuccessResult

For other content types (text, binary, etc.):

```json
{
  "kind": "success",
  "mime_type": {
    "full_type": "text/plain",
    "main_type": "text",
    "sub_type": "plain",
    "charset": "utf-8",
    "is_text": true,
    "is_gemtext": false
  },
  "content": "Plain text content here",
  "size": 23
}
```

#### GeminiInputResult

For input requests (status 10-11):

```json
{
  "kind": "input",
  "prompt": "Enter your search query:",
  "sensitive": false
}
```

#### GeminiRedirectResult

For redirects (status 30-31):

```json
{
  "kind": "redirect",
  "url": "gemini://newlocation.example.org/",
  "permanent": false
}
```

#### GeminiErrorResult

For errors (status 40-69):

```json
{
  "kind": "error",
  "status": 51,
  "message": "Not found",
  "is_temporary": false,
  "is_server_error": true
}
```

## Security

### TOFU Certificate Validation

The client implements Trust-on-First-Use (TOFU) certificate validation:

1. **First connection**: Certificate fingerprint is stored
2. **Subsequent connections**: Fingerprint is verified against stored value
3. **Certificate changes**: User intervention required (in MCP context, this means an error)

TOFU data is stored in `~/.gemini/tofu.json` by default.

### Client Certificates

The client supports automatic client certificate generation and management:

1. **Scope-based isolation**: Certificates are generated per hostname or path scope
2. **Automatic generation**: Certificates are created on-demand when requested
3. **Secure storage**: Private keys are stored securely in `~/.gemini/client_certs/`
4. **Certificate reuse**: Same certificate is used for the same scope

### Host Allowlists

Configure allowed hosts for additional security:

```bash
export GEMINI_ALLOWED_HOSTS="geminiprotocol.net,warmedal.se,kennedy.gemi.dev"
```

## Configuration

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `GEMINI_MAX_RESPONSE_SIZE` | Maximum response size in bytes | `1048576` | `2097152` |
| `GEMINI_TIMEOUT_SECONDS` | Request timeout in seconds | `30` | `60` |
| `GEMINI_CACHE_ENABLED` | Enable response caching | `true` | `false` |
| `GEMINI_CACHE_TTL_SECONDS` | Cache time-to-live in seconds | `300` | `600` |
| `GEMINI_MAX_CACHE_ENTRIES` | Maximum cache entries | `1000` | `2000` |
| `GEMINI_ALLOWED_HOSTS` | Comma-separated allowed hosts | `None` | `example.org,test.org` |
| `GEMINI_TOFU_ENABLED` | Enable TOFU certificate validation | `true` | `false` |
| `GEMINI_CLIENT_CERTS_ENABLED` | Enable client certificate support | `true` | `false` |
| `GEMINI_TOFU_STORAGE_PATH` | TOFU storage file path | `~/.gemini/tofu.json` | `/custom/path/tofu.json` |
| `GEMINI_CLIENT_CERT_STORAGE_PATH` | Client cert storage directory | `~/.gemini/client_certs/` | `/custom/path/certs/` |

### Advanced Configuration

```python
from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.gemini_tls import TLSConfig

# Custom TLS configuration
tls_config = TLSConfig(
    tls_version="TLSv1.3",
    timeout_seconds=60.0,
    verify_hostname=True,
    client_cert_path="/path/to/cert.pem",
    client_key_path="/path/to/key.pem"
)

# Custom client configuration
client = GeminiClient(
    max_response_size=2 * 1024 * 1024,  # 2MB
    timeout_seconds=60.0,
    cache_enabled=True,
    cache_ttl_seconds=600,
    max_cache_entries=2000,
    allowed_hosts={"geminiprotocol.net", "warmedal.se"},
    tofu_enabled=True,
    client_certs_enabled=True,
    tls_config=tls_config
)
```

## Error Handling

The Gemini client provides comprehensive error handling:

### Connection Errors

- **DNS resolution failures**
- **Connection timeouts**
- **TLS handshake failures**
- **Certificate validation errors**

### Protocol Errors

- **Invalid status codes**
- **Malformed responses**
- **Content too large**
- **Invalid URLs**

### Security Errors

- **TOFU validation failures**
- **Certificate verification errors**
- **Host not allowed**
- **TLS version mismatches**

## Best Practices

### For AI Assistants

1. **Handle all response types**: Be prepared for input requests, redirects, and errors
2. **Respect certificate requirements**: Some sites require client certificates
3. **Follow redirects carefully**: Check for redirect loops
4. **Parse gemtext properly**: Use the structured document format for better understanding
5. **Handle errors gracefully**: Provide helpful error messages to users

### For Developers

1. **Enable TOFU**: Always use TOFU certificate validation in production
2. **Configure timeouts**: Set appropriate timeouts for your use case
3. **Use caching**: Enable caching for better performance
4. **Monitor certificate changes**: Log TOFU validation failures
5. **Implement host allowlists**: Restrict access to trusted hosts when needed

## Troubleshooting

### Common Issues

1. **Certificate validation failures**
   - Check TOFU storage permissions
   - Verify certificate hasn't changed unexpectedly
   - Ensure system time is correct

2. **Connection timeouts**
   - Increase timeout values
   - Check network connectivity
   - Verify server is responding

3. **TLS handshake failures**
   - Ensure TLS 1.2+ support
   - Check cipher suite compatibility
   - Verify SNI support

4. **Client certificate issues**
   - Check certificate storage permissions
   - Verify certificate generation
   - Ensure proper scope configuration

### Debug Logging

Enable debug logging for troubleshooting:

```python
import logging
logging.getLogger("gopher_mcp.gemini_client").setLevel(logging.DEBUG)
logging.getLogger("gopher_mcp.gemini_tls").setLevel(logging.DEBUG)
```

## Standards Compliance

The implementation follows these specifications:

- **[Gemini Protocol Specification v0.16.1](https://geminiprotocol.net/docs/specification.gmi)**
- **[RFC 5246 - TLS 1.2](https://tools.ietf.org/html/rfc5246)**
- **[RFC 8446 - TLS 1.3](https://tools.ietf.org/html/rfc8446)**
- **[RFC 6066 - TLS Extensions (SNI)](https://tools.ietf.org/html/rfc6066)**
- **[RFC 5280 - X.509 Certificates](https://tools.ietf.org/html/rfc5280)**

## Resources

- **[Gemini Protocol Homepage](gemini://geminiprotocol.net/)**
- **[Gemini Software Directory](gemini://geminiprotocol.net/software/)**
- **[Awesome Gemini List](https://github.com/kr1sp1n/awesome-gemini)**
- **[Gemini FAQ](gemini://geminiprotocol.net/docs/faq.gmi)**
