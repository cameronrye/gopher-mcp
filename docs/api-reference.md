# API Reference

This document provides a comprehensive reference for the Gopher & Gemini MCP Server API.

## MCP Tools

The server provides two main tools for fetching content from alternative internet protocols.

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
        print(f"  {item['display_text']} ({item['type']})")
```

##### Fetching a Text File

```python
# Fetch a text document
result = await gopher_fetch("gopher://gopher.floodgap.com/0/gopher/tech/history.txt")

if result["kind"] == "text":
    print(f"Content ({result['size']} bytes):")
    print(result["content"])
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
    print(f"Binary file: {result['description']}")
    print(f"Type: {result['item_type']}")
    if result.get("size"):
        print(f"Size: {result['size']} bytes")
```

##### Error Handling

```python
# Handle errors gracefully
result = await gopher_fetch("gopher://invalid.example.com/1/")

if result["kind"] == "error":
    print(f"Error: {result['error']}")
    if result.get("details"):
        print(f"Details: {result['details']}")
    if result.get("suggestions"):
        print("Suggestions:")
        for suggestion in result["suggestions"]:
            print(f"  - {suggestion}")
```

#### Response Types

##### MenuResult

Returned for Gopher menus (type 1) and search results (type 7).

```typescript
interface MenuResult {
  kind: "menu";
  items: MenuItem[];
  server_info: ServerInfo;
  request_info: RequestInfo;
}

interface MenuItem {
  type: string;           // Gopher item type (0, 1, 7, etc.)
  display_text: string;   // Human-readable text
  selector: string;       // Gopher selector
  host: string;          // Server hostname
  port: number;          // Server port
  url?: string;          // Full URL if constructible
}
```

##### TextResult

Returned for text files (type 0).

```typescript
interface TextResult {
  kind: "text";
  content: string;        // Text content
  encoding: string;       // Character encoding
  size: number;          // Content size in bytes
  server_info: ServerInfo;
  request_info: RequestInfo;
}
```

##### BinaryResult

Returned for binary files (types 4, 5, 6, 9, g, I). Contains metadata only.

```typescript
interface BinaryResult {
  kind: "binary";
  item_type: string;      // Gopher item type
  description: string;    // File description
  size?: number;         // File size if available
  server_info: ServerInfo;
  request_info: RequestInfo;
}
```

##### ErrorResult

Returned for errors or unsupported content.

```typescript
interface ErrorResult {
  kind: "error";
  error: string;          // Error message
  details?: string;       // Additional details
  suggestions?: string[]; // Troubleshooting suggestions
  server_info?: ServerInfo;
  request_info: RequestInfo;
}
```

### `gemini_fetch`

Fetches content from Gemini protocol servers with full TLS security.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Full Gemini URL (e.g., `gemini://geminiprotocol.net/`) |

#### Examples

##### Fetching Gemtext Content

```python
from gopher_mcp.server import gemini_fetch

# Fetch a gemtext page
result = await gemini_fetch("gemini://geminiprotocol.net/")

if result["kind"] == "gemtext":
    print(f"Document has {len(result['document']['lines'])} lines")
    print(f"Found {len(result['document']['links'])} links")
    print(f"Found {len(result['document']['headings'])} headings")

    # Print all headings
    for heading in result["document"]["headings"]:
        print(f"{'#' * heading['level']} {heading['text']}")
```

##### Fetching Plain Text

```python
# Fetch plain text content
result = await gemini_fetch("gemini://example.com/document.txt")

if result["kind"] == "success":
    print(f"MIME type: {result['mime_type']['full_type']}")
    if result["mime_type"]["is_text"]:
        print(f"Content:\n{result['content']}")
```

##### Handling Redirects

```python
# Handle redirect responses
result = await gemini_fetch("gemini://example.com/old-page")

if result["kind"] == "redirect":
    print(f"Redirected to: {result['url']}")
    print(f"Permanent: {result['permanent']}")

    # Follow the redirect
    new_result = await gemini_fetch(result["url"])
```

##### Handling Input Requests

```python
# Handle input requests
result = await gemini_fetch("gemini://example.com/search")

if result["kind"] == "input":
    print(f"Server requests input: {result['prompt']}")
    print(f"Sensitive: {result['sensitive']}")

    # Provide input by appending to URL
    user_input = "search query"
    new_url = f"{result['request_info']['url']}?{user_input}"
    new_result = await gemini_fetch(new_url)
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
    print(f"Error {result['status']}: {result['message']}")

    if result["is_temporary"]:
        print("This is a temporary error - retry may succeed")
    elif result["is_server_error"]:
        print("Server error - contact server administrator")
    elif result["is_client_error"]:
        print("Client error - check your request")
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
        print(f"  Line: {link['line_number']}")
```

#### Response Types

##### GeminiGemtextResult

Returned for gemtext content (text/gemini MIME type).

```typescript
interface GeminiGemtextResult {
  kind: "gemtext";
  document: GemtextDocument;
  raw_content: string;    // Original gemtext source
  charset: string;        // Character encoding
  size: number;          // Content size in bytes
  request_info: RequestInfo;
}

interface GemtextDocument {
  lines: GemtextLine[];
  links: GemtextLink[];
  headings: GemtextHeading[];
}

interface GemtextLine {
  type: "text" | "link" | "heading1" | "heading2" | "heading3" |
        "list_item" | "quote" | "preformat_toggle" | "preformat";
  text: string;
  url?: string;           // For link lines
  alt_text?: string;      // For preformat blocks
}

interface GemtextLink {
  url: string;
  text?: string;          // Link text (optional)
  line_number: number;    // Line number in document
}

interface GemtextHeading {
  level: 1 | 2 | 3;      // Heading level
  text: string;          // Heading text
  line_number: number;   // Line number in document
}
```

##### GeminiSuccessResult

Returned for non-gemtext content (text, binary, etc.).

```typescript
interface GeminiSuccessResult {
  kind: "success";
  mime_type: GeminiMimeType;
  content: string | bytes; // Text content or binary data
  size: number;           // Content size in bytes
  request_info: RequestInfo;
}

interface GeminiMimeType {
  full_type: string;      // Complete MIME type
  main_type: string;      // Main type (text, image, etc.)
  sub_type: string;       // Sub type (plain, html, etc.)
  charset?: string;       // Character encoding
  language?: string;      // Content language
  is_text: boolean;       // Whether content is text
  is_gemtext: boolean;    // Whether content is gemtext
  is_binary: boolean;     // Whether content is binary
}
```

##### GeminiInputResult

Returned for input requests (status codes 10-11).

```typescript
interface GeminiInputResult {
  kind: "input";
  prompt: string;         // Input prompt text
  sensitive: boolean;     // Whether input is sensitive (password)
  request_info: RequestInfo;
}
```

##### GeminiRedirectResult

Returned for redirects (status codes 30-31).

```typescript
interface GeminiRedirectResult {
  kind: "redirect";
  url: string;           // New URL to redirect to
  permanent: boolean;    // Whether redirect is permanent
  request_info: RequestInfo;
}
```

##### GeminiErrorResult

Returned for errors (status codes 40-69).

```typescript
interface GeminiErrorResult {
  kind: "error";
  status: number;        // Gemini status code
  message: string;       // Error message
  is_temporary: boolean; // Whether error is temporary
  is_server_error: boolean; // Whether error is server-side
  is_client_error: boolean; // Whether error is client-side
  request_info: RequestInfo;
}
```

##### GeminiCertificateResult

Returned for certificate requests (status codes 60-69).

```typescript
interface GeminiCertificateResult {
  kind: "certificate";
  status: number;        // Gemini status code
  message: string;       // Certificate requirement message
  request_info: RequestInfo;
}
```

## Common Types

### ServerInfo

Information about the Gopher server.

```typescript
interface ServerInfo {
  host: string;          // Server hostname
  port: number;          // Server port
  protocol: "gopher";    // Protocol name
}
```

### RequestInfo

Information about the request.

```typescript
interface RequestInfo {
  url: string;           // Original request URL
  timestamp: number;     // Unix timestamp
  protocol: "gopher" | "gemini"; // Protocol used
  cached?: boolean;      // Whether response was cached
}
```

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
if result["kind"] == "error" and "timeout" in result["error"].lower():
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
if result["kind"] == "error" and "unsupported" in result["error"].lower():
    print("This content type is not supported")
    if result.get("suggestions"):
        print("Try:", result["suggestions"])
```

#### Content Too Large

**Error**: `"Response exceeds maximum size limit"`

**Cause**: Response size exceeds configured maximum

**Solution**:
```python
# Increase size limit in configuration
# GOPHER_MAX_RESPONSE_SIZE=2097152

result = await gopher_fetch("gopher://example.com/0/large-file.txt")
if result["kind"] == "error" and "size" in result["error"].lower():
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
{
    "kind": "error",
    "error": {
        "message": "Human-readable error message",
        "type": "ErrorType",  # Exception class name
        "details": "Additional technical details"
    },
    "suggestions": [  # Optional troubleshooting suggestions
        "Try increasing timeout",
        "Check server availability"
    ],
    "request_info": {
        "url": "original://request/url",
        "timestamp": 1234567890,
        "protocol": "gopher" or "gemini"
    }
}
```

## Rate Limiting

Both protocols implement rate limiting to prevent abuse:

- **Request timeout**: Configurable per protocol
- **Response size limit**: Configurable maximum response size
- **Connection limits**: Automatic connection pooling and reuse
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
