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

Common Gopher errors include:

- **Connection timeout**: Server not responding
- **Invalid URL**: Malformed Gopher URL
- **Unsupported type**: Unknown item type
- **Server error**: Server returned error response
- **Content too large**: Response exceeds size limit

### Gemini Errors

Common Gemini errors include:

- **TLS handshake failure**: Certificate or TLS issues
- **TOFU validation failure**: Certificate fingerprint mismatch
- **Invalid status code**: Malformed server response
- **Content too large**: Response exceeds size limit
- **Host not allowed**: Server not in allowlist

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
