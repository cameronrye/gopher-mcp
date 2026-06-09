# API Reference

This document provides a comprehensive reference for the Gopher & Gemini MCP Server API.

For the exhaustive, always-in-sync field definitions of every result type, see
the auto-generated [Data Models](reference/models.md) page.

## MCP Tools

The server provides four tools: `gopher_fetch` and `gemini_fetch` for single
resources, plus `gopher_batch_fetch` and `gemini_batch_fetch` for fetching
multiple URLs in a single call.

### `gopher_fetch`

Fetches content from Gopher protocol servers.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Full Gopher URL (e.g., `gopher://gopher.floodgap.com/1/`) |

#### Examples

##### Fetching a Gopher Menu

```python
from gopher_mcp.server import gopher_fetch

# Fetch a directory listing
result = await gopher_fetch("gopher://gopher.floodgap.com/1/")

if result["kind"] == "menu":
    print(f"Found {len(result['items'])} menu items")
    for item in result["items"]:
        print(f"  {item['title']} ({item['type']})")
```

##### Fetching a Text File

```python
# Fetch a text document
result = await gopher_fetch("gopher://gopher.floodgap.com/0/gopher/tech/history.txt")

if result["kind"] == "text":
    print(f"Content ({result['bytes']} bytes):")
    print(result["text"])
```

##### Performing a Gopher Search

```python
# Search using a Gopher search server (type 7)
result = await gopher_fetch("gopher://gopher.floodgap.com/7/v2/vs?search+query")

if result["kind"] == "menu":
    print(f"Search returned {len(result['items'])} results")
```

##### Handling Binary Content

```python
# Fetch binary file metadata
result = await gopher_fetch("gopher://gopher.floodgap.com/9/file.zip")

if result["kind"] == "binary":
    print(f"Binary file: {result['note']}")
    print(f"Type: {result['mime_type']}")
    print(f"Size: {result['bytes']} bytes")
```

##### Error Handling

```python
# Handle errors gracefully
result = await gopher_fetch("gopher://invalid.example.com/1/")

if result["kind"] == "error":
    print(f"Error [{result['error']['code']}]: {result['error']['message']}")
```

#### Response Types

`gopher_fetch` returns one of these result objects, distinguished by the `kind`
field. See [Data Models](reference/models.md) for the complete, always-in-sync
field definitions generated from the source.

| `kind` | Type | Returned for |
|--------|------|--------------|
| `menu` | [`MenuResult`][gopher_mcp.models.MenuResult] | Gopher menus (type 1) and search results (type 7); the `items` are [`GopherMenuItem`][gopher_mcp.models.GopherMenuItem] entries |
| `text` | [`TextResult`][gopher_mcp.models.TextResult] | Text files (type 0) |
| `binary` | [`BinaryResult`][gopher_mcp.models.BinaryResult] | Binary item types (4, 5, 6, 9, g, I) — metadata only |
| `error` | [`ErrorResult`][gopher_mcp.models.ErrorResult] | Errors and unsupported content |

Every result also carries a `request_info` object (request URL, host, port, and
timing metadata).

### `gemini_fetch`

Fetches content from Gemini protocol servers with full TLS security.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Full Gemini URL (e.g., `gemini://geminiprotocol.net/`) |
| `input` | string | No | Text to answer a Gemini input prompt (status 10/11); it is percent-encoded into the query string |

#### Examples

##### Fetching Gemtext Content

```python
from gopher_mcp.server import gemini_fetch

# Fetch a gemtext page
result = await gemini_fetch("gemini://geminiprotocol.net/")

if result["kind"] == "gemtext":
    lines = result["document"]["lines"]
    headings = [ln for ln in lines if ln["type"].startswith("heading")]
    print(f"Document has {len(lines)} lines")
    print(f"Found {len(result['document']['links'])} links")
    print(f"Found {len(headings)} headings")

    # Print all headings
    for heading in headings:
        print(f"{'#' * heading['level']} {heading['heading']['text']}")
```

##### Fetching Plain Text

```python
# Fetch plain text content
result = await gemini_fetch("gemini://example.com/document.txt")

if result["kind"] == "success":
    mime = result["mime_type"]
    print(f"MIME type: {mime['type']}/{mime['subtype']}")
    if mime["type"] == "text":
        print(f"Content:\n{result['content']}")
```

##### Handling Redirects

```python
# Handle redirect responses
result = await gemini_fetch("gemini://example.com/old-page")

if result["kind"] == "redirect":
    print(f"Redirected to: {result['new_url']}")
    print(f"Permanent: {result['permanent']}")

    # Follow the redirect
    new_result = await gemini_fetch(result["new_url"])
```

##### Handling Input Requests

```python
# Handle input requests
result = await gemini_fetch("gemini://example.com/search")

if result["kind"] == "input":
    print(f"Server requests input: {result['prompt']}")
    print(f"Sensitive: {result['sensitive']}")

    # Answer the prompt with the gemini_fetch input parameter
    new_result = await gemini_fetch("gemini://example.com/search", input="search query")
```

##### Handling Certificate Requests

```python
# Handle client certificate requests
result = await gemini_fetch("gemini://example.com/private")

if result["kind"] == "certificate":
    print(f"Certificate required: {result['message']}")
    print(f"Status code: {result['status']}")
    # Client certificates are automatically managed by the server
```

##### Error Handling

```python
# Handle various error types
result = await gemini_fetch("gemini://example.com/notfound")

if result["kind"] == "error":
    err = result["error"]
    print(f"Error {err['status']}: {err['message']}")

    if err["temporary"]:
        print("This is a temporary error - retry may succeed")
    else:
        print("Permanent error - do not retry")
```

##### Working with Links

```python
# Extract and process all links from a gemtext page
result = await gemini_fetch("gemini://example.com/links")

if result["kind"] == "gemtext":
    for link in result["document"]["links"]:
        print(f"Link: {link['url']}")
        if link.get("text"):
            print(f"  Text: {link['text']}")
```

#### Response Types

`gemini_fetch` returns one of these result objects, distinguished by the `kind`
field. See [Data Models](reference/models.md) for the complete field definitions.

| `kind` | Type | Returned for |
|--------|------|--------------|
| `gemtext` | [`GeminiGemtextResult`][gopher_mcp.models.GeminiGemtextResult] | `text/gemini` content, parsed into a [`GemtextDocument`][gopher_mcp.models.GemtextDocument] of [`GemtextLine`][gopher_mcp.models.GemtextLine] items |
| `success` | [`GeminiSuccessResult`][gopher_mcp.models.GeminiSuccessResult] | Other success responses (status 20-29); the MIME type is a [`GeminiMimeType`][gopher_mcp.models.GeminiMimeType] |
| `input` | [`GeminiInputResult`][gopher_mcp.models.GeminiInputResult] | Input prompts (status 10-11) — answer with the `gemini_fetch` `input` parameter |
| `redirect` | [`GeminiRedirectResult`][gopher_mcp.models.GeminiRedirectResult] | Redirects (status 30-31) |
| `error` | [`GeminiErrorResult`][gopher_mcp.models.GeminiErrorResult] | Errors (status 40-59) |
| `certificate` | [`GeminiCertificateResult`][gopher_mcp.models.GeminiCertificateResult] | Client-certificate requests (status 60-69) |

### `gopher_batch_fetch`

Fetches several Gopher resources in a single call.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `urls` | string[] | Yes | List of full Gopher URLs (maximum 50) |

#### Behavior

- Returns a list of results aligned by index with the input `urls`.
- Each element has the same shape as a `gopher_fetch` response (`MenuResult`, `TextResult`, `BinaryResult`, or `ErrorResult`).
- Requests run with bounded concurrency (up to 5 at a time). Passing more than 50 URLs returns one `ErrorResult` per URL instead of fetching.

```python
from gopher_mcp.server import gopher_batch_fetch

results = await gopher_batch_fetch([
    "gopher://gopher.floodgap.com/1/",
    "gopher://gopher.floodgap.com/0/gopher/welcome",
])
for result in results:
    print(result["kind"])
```

### `gemini_batch_fetch`

Fetches several Gemini resources in a single call.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `urls` | string[] | Yes | List of full Gemini URLs (maximum 50) |

#### Behavior

- Returns a list of results aligned by index with the input `urls`.
- Each element has the same shape as a `gemini_fetch` response (gemtext, success, input, redirect, error, or certificate).
- Requests run with bounded concurrency (up to 5 at a time). Passing more than 50 URLs returns one error result per URL instead of fetching.

```python
from gopher_mcp.server import gemini_batch_fetch

results = await gemini_batch_fetch([
    "gemini://geminiprotocol.net/",
    "gemini://geminiprotocol.net/docs/",
])
for result in results:
    print(result["kind"])
```

## Common Types

### `request_info`

Every result includes a `request_info` field — a free-form object
(`dict[str, Any]`) carrying metadata about the request, such as the requested
URL, host, port, and timing. It is not a fixed schema, so treat its keys as
best-effort metadata rather than a guaranteed contract.

## Status Codes

### Gopher Protocol

Gopher uses item types rather than status codes:

| Type | Description |
|------|-------------|
| `0` | Text file |
| `1` | Menu/directory |
| `4` | BinHex file |
| `5` | DOS binary |
| `6` | UUEncoded file |
| `7` | Search server |
| `9` | Binary file |
| `g` | GIF image |
| `I` | Image file |
| `h` | HTML file |
| `i` | Informational text |
| `s` | Sound file |

### Gemini Protocol

Gemini uses two-digit status codes:

#### Input (10-19)

| Code | Description |
|------|-------------|
| `10` | Input required |
| `11` | Sensitive input required |

#### Success (20-29)

| Code | Description |
|------|-------------|
| `20` | Success |

#### Redirect (30-39)

| Code | Description |
|------|-------------|
| `30` | Temporary redirect |
| `31` | Permanent redirect |

#### Temporary Failure (40-49)

| Code | Description |
|------|-------------|
| `40` | Temporary failure |
| `41` | Server unavailable |
| `42` | CGI error |
| `43` | Proxy error |
| `44` | Slow down |

#### Permanent Failure (50-59)

| Code | Description |
|------|-------------|
| `50` | Permanent failure |
| `51` | Not found |
| `52` | Gone |
| `53` | Proxy request refused |
| `59` | Bad request |

#### Client Certificate Required (60-69)

| Code | Description |
|------|-------------|
| `60` | Client certificate required |
| `61` | Certificate not authorized |
| `62` | Certificate not valid |

## Error Handling

### Gopher Errors

Common Gopher errors and how to handle them:

#### Connection Timeout

**Error**: `"Connection timeout: Server not responding"`

**Cause**: Server is unreachable or slow to respond

**Solution**:

```python
# Increase timeout in configuration
# GOPHER_TIMEOUT_SECONDS=60

result = await gopher_fetch("gopher://slow-server.example.com/1/")
if result["kind"] == "error" and "timeout" in result["error"]["message"].lower():
    print("Server is slow or unreachable - try again later")
```

#### Invalid URL

**Error**: `"Invalid Gopher URL format"`

**Cause**: Malformed URL structure

**Solution**:

```python
# Ensure URL follows gopher://host[:port]/type/selector format
valid_url = "gopher://gopher.floodgap.com/1/"
invalid_url = "gopher://gopher.floodgap.com"  # Missing type and selector

result = await gopher_fetch(valid_url)
```

#### Unsupported Type

**Error**: `"Unsupported Gopher item type: X"`

**Cause**: Server returned unknown or unsupported item type

**Solution**:

```python
result = await gopher_fetch("gopher://example.com/X/unknown")
if result["kind"] == "error" and "unsupported" in result["error"]["message"].lower():
    print("This content type is not supported")
```

#### Content Too Large

**Error**: `"Response exceeds maximum size limit"`

**Cause**: Response size exceeds configured maximum

**Solution**:

```python
# Increase size limit in configuration
# GOPHER_MAX_RESPONSE_SIZE=2097152

result = await gopher_fetch("gopher://example.com/0/large-file.txt")
if result["kind"] == "error" and "size" in result["error"]["message"].lower():
    print("File is too large - increase GOPHER_MAX_RESPONSE_SIZE")
```

### Gemini Errors

Common Gemini errors and how to handle them:

#### TLS Handshake Failure

**Error**: `"TLS connection failed: Handshake error"`

**Cause**: Certificate or TLS configuration issues

**Solution**:

```python
result = await gemini_fetch("gemini://tls-error.example.com/")
if result["kind"] == "error" and "tls" in result["error"]["message"].lower():
    print("TLS connection failed - server may have invalid certificate")
    print("Check server TLS configuration")
```

#### TOFU Validation Failure

**Error**: `"TOFU validation failed: Certificate fingerprint mismatch"`

**Cause**: Server certificate changed since first visit

**Solution**:

```python
# Certificate changed - manual intervention required
# 1. Verify the change is legitimate
# 2. Remove old certificate from TOFU storage
# 3. Retry the request

# TOFU storage location: ~/.gemini/tofu.json
result = await gemini_fetch("gemini://changed-cert.example.com/")
if result["kind"] == "error" and "tofu" in result["error"]["message"].lower():
    print("Certificate changed - verify this is expected")
    print("Remove old entry from TOFU storage if legitimate")
```

#### Invalid Status Code

**Error**: `"Invalid Gemini status code: XX"`

**Cause**: Server returned malformed or invalid status code

**Solution**:

```python
result = await gemini_fetch("gemini://broken-server.example.com/")
if result["kind"] == "error" and "status" in result["error"]["message"].lower():
    print("Server returned invalid response - contact server admin")
```

#### Content Too Large

**Error**: `"Response exceeds maximum size limit"`

**Cause**: Response size exceeds configured maximum

**Solution**:

```python
# Increase size limit in configuration
# GEMINI_MAX_RESPONSE_SIZE=2097152

result = await gemini_fetch("gemini://example.com/large-document")
if result["kind"] == "error" and "size" in result["error"]["message"].lower():
    print("Content too large - increase GEMINI_MAX_RESPONSE_SIZE")
```

#### Host Not Allowed

**Error**: `"Host not in allowed hosts list"`

**Cause**: Server not in configured allowlist

**Solution**:

```python
# Add host to allowlist in configuration
# GEMINI_ALLOWED_HOSTS=geminiprotocol.net,example.com

result = await gemini_fetch("gemini://blocked.example.com/")
if result["kind"] == "error" and "allowed" in result["error"]["message"].lower():
    print("Host not allowed - add to GEMINI_ALLOWED_HOSTS")
```

### Error Response Structure

All error responses include:

```python
# Gopher error
{
    "kind": "error",
    "error": {
        "code": "ERROR_CODE",  # Machine-readable error code
        "message": "Human-readable error message",
    },
    "request_info": { ... },  # Free-form request metadata
}

# Gemini error (also carries status / temporary)
{
    "kind": "error",
    "error": {
        "code": "TEMPORARY_ERROR",  # or "PERMANENT_ERROR", etc.
        "message": "Human-readable error message",
        "status": 51,  # Gemini status code
        "temporary": False,
    },
    "request_info": { ... },
}
```

## Rate Limiting

Both protocols implement rate limiting to prevent abuse:

- **Request timeout**: Configurable per protocol (covers DNS, connect and read)
- **Response size limit**: Configurable maximum response size, enforced
  incrementally during the read
- **Concurrency cap**: Optional limit on simultaneous in-flight fetches
  (`*_MAX_CONCURRENT_REQUESTS`, off by default). Each fetch opens a fresh
  connection; there is no connection pooling/reuse.
- **Cache TTL**: Configurable cache time-to-live

## Security Considerations

### Gopher Security

- **No encryption**: Gopher traffic is unencrypted
- **Input sanitization**: All inputs are validated
- **Size limits**: Responses are limited in size
- **Timeout protection**: Requests have configurable timeouts

### Gemini Security

- **Mandatory TLS**: All connections use TLS 1.2+
- **TOFU validation**: Certificate fingerprints are verified
- **Client certificates**: Automatic generation and management
- **Host allowlists**: Configurable allowed hosts
- **Input validation**: URLs and responses are validated

## Performance

### Caching

Both protocols support intelligent caching:

- **Response caching**: Successful responses are cached
- **TTL-based expiration**: Configurable cache lifetime
- **Size-based eviction**: LRU eviction when cache is full
- **Cache bypass**: Option to disable caching per protocol

### Connection Management

- **Connection pooling**: Automatic connection reuse
- **Async/await**: Non-blocking I/O operations
- **Streaming**: Memory-efficient content handling
- **Resource cleanup**: Automatic connection cleanup

## Configuration

See the main README.md for complete configuration options for both protocols.
