# Architecture

System design and component overview for the Gopher & Gemini MCP Server.

## System Overview

The Gopher & Gemini MCP Server is a Model Context Protocol (MCP) server that enables Large Language Models (LLMs) to access content from two alternative internet protocols: Gopher (1991) and Gemini (2019).

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Client (LLM)                       │
│                    (e.g., Claude Desktop)                   │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP Protocol (JSON-RPC)
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    MCP Server (FastMCP)                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Tool Handlers (server.py)               │  │
│  │  • gopher_fetch()      • gemini_fetch()             │  │
│  └──────────────┬──────────────────────┬─────────────────┘  │
│                 │                      │                    │
│  ┌──────────────▼──────────┐  ┌───────▼──────────────────┐ │
│  │   GopherClient          │  │   GeminiClient           │ │
│  │   (gopher_client.py)    │  │   (gemini_client.py)     │ │
│  │                         │  │                          │ │
│  │  • URL parsing          │  │  • URL parsing           │ │
│  │  • Request handling     │  │  • TLS connections       │ │
│  │  • Response parsing     │  │  • TOFU validation       │ │
│  │  • Caching              │  │  • Gemtext parsing       │ │
│  └──────────────┬──────────┘  │  • Client certificates   │ │
│                 │              │  • Caching               │ │
│                 │              └───────┬──────────────────┘ │
└─────────────────┼──────────────────────┼────────────────────┘
                  │                      │
                  │                      │
┌─────────────────▼──────────┐  ┌───────▼──────────────────┐
│   Gopher Servers           │  │   Gemini Servers         │
│   (Port 70, TCP)           │  │   (Port 1965, TLS)       │
└────────────────────────────┘  └──────────────────────────┘
```

## Core Components

### MCP Server (server.py)

The main server implementation using FastMCP framework.

**Responsibilities:**

- Initialize MCP server
- Register tools (`gopher_fetch`, `gemini_fetch`)
- Handle tool invocations
- Manage client lifecycle
- Error handling and logging

### Gopher Client (gopher_client.py)

Handles all Gopher protocol operations.

**Features:**

- URL parsing and validation
- TCP connection management
- Menu parsing (type 1)
- Text file handling (type 0)
- Search support (type 7)
- Binary file metadata (types 4, 5, 6, 9, g, I)
- Response caching
- Timeout handling
- Size limits

### Gemini Client (gemini_client.py)

Handles all Gemini protocol operations.

**Features:**

- URL parsing and validation
- TLS 1.2+ connections
- TOFU certificate validation
- Client certificate support
- Gemtext parsing
- Status code handling (10-69)
- Response caching
- Timeout handling
- Size limits

### Data Models (models.py)

Pydantic models for type-safe data handling.

**Model Categories:**

- Request models (GopherFetchRequest, GeminiFetchRequest)
- Response models (MenuResult, TextResult, GeminiGemtextResult, etc.)
- URL models (GopherURL, GeminiURL)
- Cache models (CacheEntry, GeminiCacheEntry)
- Security models (TOFUEntry, CertificateInfo)

### Configuration (config.py)

Centralized configuration management.

**Configuration Sections:**

- Gopher settings (timeouts, size limits, caching)
- Gemini settings (TLS, TOFU, client certs)
- Server settings (logging, development mode)

### Utilities (utils.py)

Helper functions for common operations.

**Functions:**

- URL parsing (parse_gopher_url, parse_gemini_url)
- Response parsing (parse_gemini_response)
- Content processing (process_gemini_response)
- Validation helpers

## Data Flow

### Gopher Request Flow

```
1. MCP Client sends gopher_fetch request
   ↓
2. Server validates URL
   ↓
3. Check cache (if enabled)
   ↓
4. GopherClient parses URL
   ↓
5. Establish TCP connection
   ↓
6. Send selector + CRLF
   ↓
7. Receive response
   ↓
8. Parse based on type (menu/text/binary)
   ↓
9. Cache response (if enabled)
   ↓
10. Return structured result to MCP Client
```

### Gemini Request Flow

```
1. MCP Client sends gemini_fetch request
   ↓
2. Server validates URL
   ↓
3. Check cache (if enabled)
   ↓
4. GeminiClient parses URL
   ↓
5. Establish TLS connection
   ↓
6. Validate certificate (TOFU)
   ↓
7. Send URL + CRLF
   ↓
8. Receive response header
   ↓
9. Parse status code
   ↓
10. Handle based on status (success/redirect/error/input)
    ↓
11. Parse gemtext (if applicable)
    ↓
12. Cache response (if enabled)
    ↓
13. Return structured result to MCP Client
```

## Security Architecture

### Gopher Security

- **Input Validation**: URL and selector validation
- **Size Limits**: Maximum response size enforcement
- **Timeouts**: Connection and read timeouts
- **Host Allowlists**: Optional host restrictions
- **Binary Protection**: Metadata-only for binary files

### Gemini Security

- **TLS 1.2+**: Encrypted connections only
- **TOFU Validation**: Trust-On-First-Use certificate validation
- **Client Certificates**: Optional client authentication
- **Input Validation**: URL and query validation
- **Size Limits**: Maximum response size enforcement
- **Timeouts**: Connection and read timeouts
- **Host Allowlists**: Optional host restrictions

## Caching Strategy

### Cache Implementation

- **LRU Cache**: Least Recently Used eviction
- **TTL-based**: Time-to-live expiration
- **Per-Protocol**: Separate caches for Gopher and Gemini
- **Configurable**: Enable/disable per protocol

### Cache Keys

- **Gopher**: Full URL including selector and search
- **Gemini**: Full URL including path and query

## Error Handling

### Error Categories

1. **Network Errors**: Connection failures, timeouts
2. **Protocol Errors**: Invalid responses, parsing failures
3. **Security Errors**: Certificate validation, TOFU failures
4. **Configuration Errors**: Invalid settings, missing dependencies

### Error Responses

All errors return structured error results with:

- Error code
- Error message
- Request information
- Timestamp

## Performance Considerations

### Optimization Strategies

- **Async/Await**: Non-blocking I/O operations
- **Connection Pooling**: Reuse connections where possible
- **Response Caching**: Reduce redundant requests
- **Size Limits**: Prevent memory exhaustion
- **Timeouts**: Prevent hanging requests

### Scalability

- **Stateless Design**: No server-side session state
- **Resource Limits**: Configurable limits per request
- **Concurrent Requests**: Async handling of multiple requests

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
