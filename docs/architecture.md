# Architecture Documentation

This document provides a comprehensive overview of the Gopher & Gemini MCP Server architecture, including component interactions, data flow, and security model.

## System Overview

The Gopher & Gemini MCP Server is a Model Context Protocol (MCP) server that enables Large Language Models (LLMs) to access content from two alternative internet protocols: Gopher (1991) and Gemini (2019).

### High-Level Architecture

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
│  │   ClientManager         │  │   ClientManager          │ │
│  │   (Singleton)           │  │   (Singleton)            │ │
│  │  • get_gopher_client()  │  │  • get_gemini_client()   │ │
│  └──────────────┬──────────┘  └───────┬──────────────────┘ │
└─────────────────┼──────────────────────┼────────────────────┘
                  │                      │
┌─────────────────▼──────────┐  ┌───────▼──────────────────────┐
│   GopherClient             │  │   GeminiClient               │
│   (gopher_client.py)       │  │   (gemini_client.py)         │
│                            │  │                              │
│  • fetch()                 │  │  • fetch()                   │
│  • _fetch_content()        │  │  • _fetch_content()          │
│  • _process_*_response()   │  │  • Response parsing          │
│  • Caching                 │  │  • Caching                   │
└─────────────┬──────────────┘  └───────┬──────────────────────┘
              │                         │
              │                         │
┌─────────────▼──────────────┐  ┌───────▼──────────────────────┐
│   Pituophis Library        │  │   Security Components        │
│   (External)               │  │                              │
│                            │  │  ┌──────────────────────────┐│
│  • Request()               │  │  │  GeminiTLSClient         ││
│  • Response parsing        │  │  │  (gemini_tls.py)         ││
│  • Protocol handling       │  │  │  • TLS 1.2+ connection   ││
└────────────────────────────┘  │  │  • Certificate handling  ││
                                │  └──────────────────────────┘│
                                │  ┌──────────────────────────┐│
                                │  │  TOFUManager             ││
                                │  │  (tofu.py)               ││
                                │  │  • Certificate storage   ││
                                │  │  • Fingerprint validation││
                                │  └──────────────────────────┘│
                                │  ┌──────────────────────────┐│
                                │  │  ClientCertificateManager││
                                │  │  (client_certs.py)       ││
                                │  │  • Auto-generation       ││
                                │  │  • Certificate storage   ││
                                │  └──────────────────────────┘│
                                └──────────────────────────────┘
```

## Core Components

### 1. MCP Server Layer (`server.py`)

**Responsibility**: Expose Gopher and Gemini functionality as MCP tools

**Key Functions**:
- `gopher_fetch(url: str)` - MCP tool for Gopher protocol
- `gemini_fetch(url: str)` - MCP tool for Gemini protocol
- Environment variable parsing and validation
- Client manager singleton access

**Dependencies**:
- FastMCP framework
- GopherClient
- GeminiClient
- ClientManager

### 2. Client Manager (`server.py`)

**Responsibility**: Singleton pattern for client lifecycle management

**Key Features**:
- Single instance per protocol client
- Lazy initialization
- Configuration from environment variables
- Thread-safe access

**Pattern**:
```python
class ClientManager:
    _instance = None
    _gopher_client = None
    _gemini_client = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

### 3. Gopher Client (`gopher_client.py`)

**Responsibility**: Gopher protocol implementation and response processing

**Key Methods**:
- `fetch(url)` - Main entry point
- `_fetch_content(url)` - Network communication
- `_process_menu_response()` - Parse Gopher menus
- `_process_text_response()` - Parse text content
- `_process_binary_response()` - Handle binary content
- `_get_cached_response()` - Cache retrieval
- `_cache_response()` - Cache storage

**Data Flow**:
```
URL → Parse → Check Cache → Fetch (if needed) → Process → Cache → Return
```

### 4. Gemini Client (`gemini_client.py`)

**Responsibility**: Gemini protocol implementation with TLS security

**Key Methods**:
- `fetch(url)` - Main entry point
- `_fetch_content(url)` - TLS connection and response handling
- Response parsing by status code (20, 30, 40, 60, etc.)
- `_get_cached_response()` - Cache retrieval
- `_cache_response()` - Cache storage

**Dependencies**:
- GeminiTLSClient
- TOFUManager
- ClientCertificateManager

### 5. Gemini TLS Client (`gemini_tls.py`)

**Responsibility**: Low-level TLS connection management

**Key Methods**:
- `connect(host, port)` - Establish TLS connection
- `send_data(data)` - Send request
- `receive_data()` - Receive response
- `close()` - Close connection

**Security Features**:
- TLS 1.2+ enforcement
- Certificate validation
- Cipher suite selection
- Connection timeout handling

### 6. TOFU Manager (`tofu.py`)

**Responsibility**: Trust-on-First-Use certificate validation

**Key Methods**:
- `validate_certificate(host, cert)` - Validate against stored fingerprint
- `store_certificate(host, cert)` - Store new certificate
- `load_certificates()` - Load from storage
- `save_certificates()` - Persist to storage

**Storage Format** (`~/.gemini/tofu.json`):
```json
{
  "example.com": {
    "fingerprint": "sha256:abc123...",
    "first_seen": "2025-01-15T10:30:00Z",
    "last_seen": "2025-01-15T10:30:00Z"
  }
}
```

### 7. Client Certificate Manager (`client_certs.py`)

**Responsibility**: Automatic client certificate generation and management

**Key Methods**:
- `get_certificate(host)` - Get or generate certificate for host
- `generate_certificate(host)` - Generate new certificate
- `load_certificates()` - Load from storage
- `save_certificate(host, cert, key)` - Persist certificate

**Storage Structure** (`~/.gemini/client_certs/`):
```
~/.gemini/client_certs/
├── example.com.crt
├── example.com.key
├── another.com.crt
└── another.com.key
```

## Data Flow

### Gopher Fetch Workflow

```
1. MCP Client → gopher_fetch(url)
   ↓
2. Parse and validate URL
   ↓
3. Check allowed hosts (if configured)
   ↓
4. Get GopherClient from ClientManager
   ↓
5. GopherClient.fetch(url)
   ↓
6. Check cache for existing response
   ↓
7. If cached and valid → Return cached response
   ↓
8. If not cached:
   a. Create Pituophis Request
   b. Execute request in thread pool
   c. Receive response
   d. Determine response type (menu, text, binary)
   e. Process response based on type
   f. Cache response
   ↓
9. Return formatted result to MCP client
```

### Gemini Fetch Workflow

```
1. MCP Client → gemini_fetch(url)
   ↓
2. Parse and validate URL
   ↓
3. Check allowed hosts (if configured)
   ↓
4. Get GeminiClient from ClientManager
   ↓
5. GeminiClient.fetch(url)
   ↓
6. Check cache for existing response
   ↓
7. If cached and valid → Return cached response
   ↓
8. If not cached:
   a. Get GeminiTLSClient
   b. Establish TLS connection
   c. Validate certificate with TOFUManager
   d. Get client certificate (if needed)
   e. Send request
   f. Receive response
   g. Parse status code
   h. Process response based on status
   i. Cache response (if successful)
   ↓
9. Return formatted result to MCP client
```

### Caching Flow

Both protocols use identical caching logic:

```
Request → Hash URL → Check Cache
                      ↓
                   Found?
                   ↙    ↘
                 Yes     No
                  ↓       ↓
            Check TTL   Fetch
                  ↓       ↓
            Valid?    Process
             ↙  ↘        ↓
           Yes  No     Cache
            ↓    ↓       ↓
         Return Fetch  Return
                  ↓
              Process
                  ↓
               Cache
                  ↓
               Return
```

**Cache Key**: `SHA256(protocol + url)`

**Cache Entry**:
```python
{
    "response": {...},      # Formatted response
    "timestamp": 1234567890, # Unix timestamp
    "ttl": 300              # Seconds
}
```

**Eviction Policy**: LRU (Least Recently Used) when max entries reached

## Security Model

### Gopher Security

**Threat Model**:
- No encryption (plaintext protocol)
- No authentication
- Potential for malicious content
- Network eavesdropping

**Mitigations**:
1. **Input Validation**
   - URL format validation
   - Selector sanitization
   - Response size limits

2. **Host Allowlisting**
   - Optional allowed hosts configuration
   - Blocks connections to non-allowed hosts

3. **Resource Limits**
   - Maximum response size (default: 1MB)
   - Request timeout (default: 30s)
   - Cache size limits

4. **Content Processing**
   - Safe parsing of menu items
   - Binary content metadata only
   - Error handling for malformed responses

### Gemini Security

**Threat Model**:
- Man-in-the-middle attacks
- Certificate spoofing
- Malicious content
- Privacy concerns

**Mitigations**:
1. **Transport Security**
   - Mandatory TLS 1.2+
   - Strong cipher suites only
   - Certificate validation

2. **TOFU (Trust-on-First-Use)**
   - Certificate fingerprint storage
   - Fingerprint validation on subsequent visits
   - Alert on certificate changes

3. **Client Certificates**
   - Automatic generation per host
   - Secure storage
   - Privacy-preserving (unique per host)

4. **Host Allowlisting**
   - Optional allowed hosts configuration
   - Blocks connections to non-allowed hosts

5. **Resource Limits**
   - Maximum response size (default: 1MB)
   - Request timeout (default: 30s)
   - Cache size limits

6. **Input Validation**
   - URL format validation
   - Status code validation
   - MIME type validation

### Security Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Security Layers                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Input Validation                                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • URL format validation                               │ │
│  │ • Protocol validation (gopher:// or gemini://)        │ │
│  │ • Host allowlist check                                │ │
│  │ • Parameter sanitization                              │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Layer 2: Transport Security (Gemini only)                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • TLS 1.2+ enforcement                                │ │
│  │ • Certificate validation                              │ │
│  │ • TOFU fingerprint verification                       │ │
│  │ • Client certificate management                       │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Layer 3: Resource Protection                              │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • Response size limits                                │ │
│  │ • Request timeouts                                    │ │
│  │ • Cache size limits                                   │ │
│  │ • Connection pooling                                  │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Layer 4: Content Processing                               │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ • Safe parsing                                        │ │
│  │ • Error handling                                      │ │
│  │ • Binary content restrictions                         │ │
│  │ • MIME type validation                                │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Component Interactions

### Initialization Sequence

```
1. MCP Server starts
   ↓
2. FastMCP framework initializes
   ↓
3. Register tools:
   - gopher_fetch
   - gemini_fetch
   ↓
4. ClientManager singleton created (lazy)
   ↓
5. Wait for MCP client connections
```

### Request Processing Sequence

```
MCP Client                Server              ClientManager        Protocol Client
    │                        │                      │                    │
    ├─ tool_call ────────────>│                      │                    │
    │                        ├─ get_client ─────────>│                    │
    │                        │                      ├─ create/return ────>│
    │                        │<─────────────────────┤                    │
    │                        ├─ fetch ──────────────────────────────────>│
    │                        │                      │                    ├─ check cache
    │                        │                      │                    ├─ fetch (if needed)
    │                        │                      │                    ├─ process
    │                        │                      │                    ├─ cache
    │                        │<──────────────────────────────────────────┤
    │<─ result ──────────────┤                      │                    │
```

### Error Handling Flow

```
Error Occurs
    ↓
Catch Exception
    ↓
Log Error (structlog)
    ↓
Format Error Response
    ↓
Include:
  - Error message
  - Error type
  - Suggestions (if available)
  - Request info
    ↓
Return to MCP Client
```

## Performance Considerations

### Caching Strategy

**Benefits**:
- Reduces network requests
- Improves response time
- Reduces server load

**Configuration**:
- `GOPHER_CACHE_ENABLED` / `GEMINI_CACHE_ENABLED`
- `GOPHER_CACHE_TTL_SECONDS` / `GEMINI_CACHE_TTL_SECONDS`
- `GOPHER_MAX_CACHE_ENTRIES` / `GEMINI_MAX_CACHE_ENTRIES`

**Trade-offs**:
- Memory usage vs. performance
- Freshness vs. speed
- Cache size vs. hit rate

### Concurrency Model

**Gopher**:
- Synchronous requests executed in thread pool
- `asyncio.get_event_loop().run_in_executor()`
- Non-blocking for async MCP server

**Gemini**:
- Asynchronous TLS connections
- Native async/await support
- Efficient connection handling

### Resource Management

**Connection Pooling**:
- Gemini: Connections closed after each request
- Gopher: Pituophis handles connection lifecycle

**Memory Management**:
- Response size limits prevent memory exhaustion
- Cache eviction prevents unbounded growth
- Streaming not supported (responses buffered)

## Extension Points

### Adding New Response Types

1. Define new response model in `models.py`
2. Add processing logic in client
3. Update type hints and documentation

### Adding New Security Features

1. Implement in appropriate security module
2. Add configuration options
3. Update security documentation

### Adding New Protocols

1. Create new client class (e.g., `FtpClient`)
2. Implement `fetch()` method
3. Add to `ClientManager`
4. Register MCP tool in `server.py`

## Testing Architecture

### Test Layers

```
┌─────────────────────────────────────────────────────────┐
│  Integration Tests (tests/test_integration.py)         │
│  • End-to-end workflows                                │
│  • Protocol integration                                │
│  • Error scenarios                                     │
│  • Concurrency                                         │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  Unit Tests (tests/test_*.py)                          │
│  • Individual components                               │
│  • Edge cases                                          │
│  • Error handling                                      │
│  • Data validation                                     │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│  Mocking Strategy                                       │
│  • Pituophis requests (Gopher)                         │
│  • TLS connections (Gemini)                            │
│  • File system operations                              │
│  • Network failures                                    │
└─────────────────────────────────────────────────────────┘
```

### Test Markers

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.asyncio` - Async tests

## Deployment Architecture

### Standalone Deployment

```
┌─────────────────────────────────────────┐
│  Host Machine                           │
│  ┌───────────────────────────────────┐  │
│  │  MCP Client (Claude Desktop)      │  │
│  └───────────┬───────────────────────┘  │
│              │ stdio                    │
│  ┌───────────▼───────────────────────┐  │
│  │  MCP Server Process               │  │
│  │  (uv run task serve)              │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Docker Deployment

```
┌─────────────────────────────────────────┐
│  Host Machine                           │
│  ┌───────────────────────────────────┐  │
│  │  MCP Client                       │  │
│  └───────────┬───────────────────────┘  │
│              │ stdio/network            │
│  ┌───────────▼───────────────────────┐  │
│  │  Docker Container                 │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  MCP Server                 │  │  │
│  │  └─────────────────────────────┘  │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Volume Mounts:             │  │  │
│  │  │  • ~/.gemini/tofu.json      │  │  │
│  │  │  • ~/.gemini/client_certs/  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

## Logging and Observability

### Structured Logging

**Framework**: structlog

**Log Levels**:
- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical failures

**Log Fields**:
```python
{
    "event": "gopher_fetch_successful",
    "url": "gopher://example.com/1/",
    "response_type": "menu",
    "response_size": 1234,
    "cached": false,
    "timestamp": "2025-01-15T10:30:00Z"
}
```

### Metrics

**Key Metrics**:
- Request count (per protocol)
- Response time (per protocol)
- Cache hit rate
- Error rate
- Response size distribution

## See Also

- [Configuration Guide](configuration.md) - Detailed configuration options
- [API Reference](api-reference.md) - API documentation
- [Gemini Configuration](gemini-configuration.md) - Gemini-specific configuration
- [Advanced Features](advanced-features.md) - Advanced usage patterns
