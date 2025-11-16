# Gemini Protocol Guide

Understanding the Gemini protocol and how it's implemented in the MCP server.

## What is Gemini?

The Gemini protocol is a modern, lightweight internet protocol designed in 2019 as an alternative to HTTP and Gopher. It emphasizes privacy, simplicity, and user control while providing a richer experience than Gopher.

## Protocol Basics

### Connection

- **Protocol**: TLS (required)
- **Default Port**: 1965
- **TLS Version**: 1.2 or higher
- **Encryption**: Always encrypted

### Request Format

```
<URL><CR><LF>
```

Simple one-line request with the full URL.

Example:

```
gemini://geminiprotocol.net/\r\n
```

### Response Format

```
<status><space><meta><CR><LF>
[<body>]
```

- Status: Two-digit status code
- Meta: MIME type or additional information
- Body: Optional response body

## Status Codes

### Input (10-19)

| Code | Description              |
| ---- | ------------------------ |
| 10   | Input required           |
| 11   | Sensitive input required |

### Success (20-29)

| Code | Description |
| ---- | ----------- |
| 20   | Success     |

### Redirect (30-39)

| Code | Description        |
| ---- | ------------------ |
| 30   | Temporary redirect |
| 31   | Permanent redirect |

### Temporary Failure (40-49)

| Code | Description        |
| ---- | ------------------ |
| 40   | Temporary failure  |
| 41   | Server unavailable |
| 42   | CGI error          |
| 43   | Proxy error        |
| 44   | Slow down          |

### Permanent Failure (50-59)

| Code | Description           |
| ---- | --------------------- |
| 50   | Permanent failure     |
| 51   | Not found             |
| 52   | Gone                  |
| 53   | Proxy request refused |
| 59   | Bad request           |

### Client Certificate (60-69)

| Code | Description                 |
| ---- | --------------------------- |
| 60   | Client certificate required |
| 61   | Certificate not authorized  |
| 62   | Certificate not valid       |

## Gemtext Format

Gemini uses a lightweight markup format called "gemtext".

### Line Types

```
# Heading 1
## Heading 2
### Heading 3

=> gemini://example.com Link text
=> /relative/path Another link

* List item
* Another item

> Quote text

```

Preformatted text

```

Regular paragraph text
```

## URL Format

Gemini URLs follow this format:

```
gemini://<host>[:<port>]/<path>[?<query>]
```

Examples:

```
gemini://geminiprotocol.net/
gemini://example.com:1965/page
gemini://example.com/search?query
```

## Implementation in MCP Server

### Supported Features

- **TLS Connections**: Secure TLS 1.2+ connections
- **TOFU Validation**: Trust-On-First-Use certificate validation
- **Client Certificates**: Optional client authentication
- **Gemtext Parsing**: Native gemtext document parsing
- **Status Handling**: Complete status code handling (10-69)
- **Response Caching**: Intelligent response caching

### TLS Security

The server implements strict TLS security:

```python
{
    "tls_version": "TLSv1.2+",
    "verify_mode": "CERT_REQUIRED",
    "check_hostname": True,
    "tofu_enabled": True
}
```

### TOFU (Trust-On-First-Use)

Certificate validation strategy:

1. First connection: Store certificate fingerprint
2. Subsequent connections: Verify fingerprint matches
3. Changed certificate: Reject connection (security)

### Response Processing

#### Gemtext Response (Status 20, text/gemini)

Returns parsed gemtext:

```json
{
  "kind": "gemtext",
  "lines": [
    {
      "type": "heading",
      "level": 1,
      "text": "Page Title"
    },
    {
      "type": "link",
      "url": "gemini://example.com/page",
      "text": "Link text"
    },
    {
      "type": "text",
      "text": "Regular paragraph"
    }
  ]
}
```

#### Success Response (Status 20, other MIME)

Returns raw content:

```json
{
  "kind": "success",
  "content": "Content here...",
  "metadata": {
    "mime_type": "text/plain",
    "size": 1234
  }
}
```

#### Input Response (Status 10-11)

Prompts for input:

```json
{
  "kind": "input",
  "prompt": "Enter search query:",
  "sensitive": false
}
```

#### Redirect Response (Status 30-31)

Provides new URL:

```json
{
  "kind": "redirect",
  "url": "gemini://new-location.com/",
  "permanent": false
}
```

## Security Features

### TLS Encryption

All connections use TLS 1.2 or higher with strong cipher suites.

### TOFU Certificate Validation

Prevents man-in-the-middle attacks by tracking certificate changes.

### Client Certificates

Optional client authentication for restricted content.

### Input Validation

- URL format validation
- Query length limits
- Host allowlist support

### Resource Limits

- Maximum response size (default 1MB)
- Connection timeout (default 30 seconds)
- TLS handshake timeout

## Popular Gemini Servers

### Gemini Protocol

```
gemini://geminiprotocol.net/
```

Official Gemini protocol documentation and resources.

### Antenna

```
gemini://warmedal.se/~antenna/
```

Gemlog aggregator showing recent posts from across Geminispace.

### Kennedy

```
gemini://kennedy.gemi.dev/
```

Gemini search engine for discovering content.

## Best Practices

### For Users

1. Understand TOFU certificate validation
2. Use client certificates when needed
3. Respect input prompts
4. Follow redirects appropriately

### For Developers

1. Always use TLS 1.2 or higher
2. Implement TOFU validation
3. Handle all status codes
4. Parse gemtext correctly
5. Respect server resources

## Common Issues

### Certificate Validation Errors

TOFU validation may fail if server certificate changes. This is a security feature.

### TLS Handshake Failures

Some servers may not support TLS 1.2+. This is a protocol requirement.

### Client Certificate Required

Some content requires client certificates for access.

## Further Reading

- [Gemini Protocol Specification](https://geminiprotocol.net/docs/specification.gmi)
- [Gemini FAQ](https://geminiprotocol.net/docs/faq.gmi)
- [Awesome Gemini](https://github.com/kr1sp1n/awesome-gemini)

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
