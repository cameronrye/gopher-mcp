# API Reference

Complete API documentation for the Gopher & Gemini MCP Server tools.

## MCP Tools

The server provides two powerful MCP tools for exploring alternative internet protocols.

### `gopher_fetch` Tool

Fetches Gopher menus, text files, or metadata by URL with comprehensive error handling and security safeguards.

#### Parameters

| Parameter | Type   | Required | Description                                               |
| --------- | ------ | -------- | --------------------------------------------------------- |
| `url`     | string | Yes      | Full Gopher URL (e.g., `gopher://gopher.floodgap.com/1/`) |

#### Response Types

##### MenuResult

For Gopher menus (type 1) and search results (type 7).

```json
{
  "kind": "menu",
  "items": [
    {
      "type": "1",
      "title": "Directory Name",
      "selector": "/path/to/directory",
      "host": "gopher.example.com",
      "port": 70,
      "nextUrl": "gopher://gopher.example.com:70/1/path/to/directory"
    }
  ]
}
```

##### TextResult

For text files (type 0).

```json
{
  "kind": "text",
  "content": "File content here...",
  "metadata": {
    "size": 1234,
    "encoding": "utf-8"
  }
}
```

##### BinaryResult

Metadata only for binary files (types 4, 5, 6, 9, g, I).

```json
{
  "kind": "binary",
  "metadata": {
    "type": "9",
    "size": 5678,
    "description": "Binary file"
  }
}
```

##### ErrorResult

For errors or unsupported content.

```json
{
  "kind": "error",
  "error": {
    "code": "FETCH_ERROR",
    "message": "Connection timeout"
  },
  "requestInfo": {
    "url": "gopher://example.com/1/",
    "timestamp": 1234567890
  }
}
```

### `gemini_fetch` Tool

Fetches Gemini content with full TLS security, TOFU certificate validation, and native gemtext parsing.

#### Parameters

| Parameter | Type   | Required | Description                                            |
| --------- | ------ | -------- | ------------------------------------------------------ |
| `url`     | string | Yes      | Full Gemini URL (e.g., `gemini://geminiprotocol.net/`) |

#### Response Types

##### GeminiGemtextResult

For gemtext content (text/gemini).

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
      "text": "Regular paragraph text"
    }
  ],
  "metadata": {
    "mime_type": "text/gemini",
    "charset": "utf-8"
  }
}
```

##### GeminiSuccessResult

For other text and binary content.

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

##### GeminiInputResult

For input requests (status 10-11).

```json
{
  "kind": "input",
  "prompt": "Enter search query:",
  "sensitive": false
}
```

##### GeminiRedirectResult

For redirects (status 30-31).

```json
{
  "kind": "redirect",
  "url": "gemini://new-location.com/",
  "permanent": false
}
```

##### GeminiErrorResult

For errors (status 40-69).

```json
{
  "kind": "error",
  "status": 51,
  "message": "Not found",
  "error": {
    "code": "NOT_FOUND",
    "details": "The requested resource was not found"
  }
}
```

##### GeminiCertificateResult

For certificate requests (status 60-69).

```json
{
  "kind": "certificate",
  "required": true,
  "message": "Client certificate required"
}
```

## Example Usage

### Gopher Examples

```python
# Fetch a Gopher menu
result = await gopher_fetch("gopher://gopher.floodgap.com/1/")

# Fetch a text file
result = await gopher_fetch("gopher://gopher.floodgap.com/0/gopher/welcome")

# Perform a search
result = await gopher_fetch("gopher://gopher.floodgap.com/7/v2/vs?python")
```

### Gemini Examples

```python
# Fetch a Gemini page
result = await gemini_fetch("gemini://geminiprotocol.net/")

# Fetch with query
result = await gemini_fetch("gemini://example.com/search?query")
```

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
