# Gemini Protocol API Contracts Design

## Overview

This document defines the API contracts for Gemini protocol integration into the gopher-mcp project. The design follows established patterns from the Gopher implementation while accommodating Gemini-specific features.

## Core Design Principles

1. **Consistency**: Follow existing Gopher patterns for naming, structure, and behavior
2. **Protocol Isolation**: Gemini and Gopher operate independently with shared infrastructure
3. **Type Safety**: Comprehensive Pydantic models with validation
4. **Error Handling**: Graceful degradation with structured error responses
5. **Security First**: Built-in TLS, TOFU, and certificate management

## Tool Interface

### gemini_fetch Tool

**Function Signature:**

```python
@mcp.tool()
async def gemini_fetch(url: str) -> Dict[str, Any]:
    """Fetch Gemini content by URL.

    Supports all Gemini protocol features including gemtext parsing,
    input handling, redirections, and client certificates.
    Returns structured JSON responses optimized for LLM consumption.

    Args:
        url: Full Gemini URL to fetch (e.g., gemini://gemini.circumlunar.space/)
    """
```

**Input Validation:**

- URL must start with `gemini://`
- URL must not exceed 1024 bytes
- URL must not contain userinfo or fragment
- Host must be valid hostname or IP address
- Port must be in range 1-65535 (default: 1965)

**Response Types:**

1. **Success Response (Status 20)**

```json
{
  "kind": "success",
  "mimeType": {
    "type": "text",
    "subtype": "plain",
    "charset": "utf-8",
    "lang": null
  },
  "content": "Response content here",
  "size": 1234,
  "requestInfo": {
    "url": "gemini://example.org/",
    "timestamp": 1640995200.0
  }
}
```

2. **Gemtext Response (Status 20, text/gemini)**

```json
{
  "kind": "gemtext",
  "document": {
    "lines": [
      {
        "type": "heading1",
        "content": "Welcome to Gemini",
        "level": 1
      },
      {
        "type": "text",
        "content": "This is a gemtext document."
      },
      {
        "type": "link",
        "content": "=> /about About this site",
        "link": {
          "url": "/about",
          "text": "About this site"
        }
      }
    ],
    "links": [
      {
        "url": "/about",
        "text": "About this site"
      }
    ]
  },
  "rawContent": "# Welcome to Gemini\n\nThis is a gemtext document.\n\n=> /about About this site",
  "charset": "utf-8",
  "size": 1234,
  "requestInfo": {
    "url": "gemini://example.org/",
    "timestamp": 1640995200.0
  }
}
```

3. **Input Request Response (Status 10/11)**

```json
{
  "kind": "input",
  "prompt": "Enter search terms",
  "sensitive": false,
  "requestInfo": {
    "url": "gemini://example.org/search",
    "timestamp": 1640995200.0
  }
}
```

4. **Redirect Response (Status 30/31)**

```json
{
  "kind": "redirect",
  "newUrl": "/new-location",
  "permanent": true,
  "requestInfo": {
    "url": "gemini://example.org/old-path",
    "timestamp": 1640995200.0
  }
}
```

5. **Error Response (Status 40-59)**

```json
{
  "kind": "error",
  "error": {
    "code": "NOT_FOUND",
    "message": "The requested resource was not found",
    "status": 51
  },
  "requestInfo": {
    "url": "gemini://example.org/missing",
    "timestamp": 1640995200.0
  }
}
```

6. **Certificate Request Response (Status 60-62)**

```json
{
  "kind": "certificate",
  "message": "Certificate required for access",
  "required": true,
  "requestInfo": {
    "url": "gemini://example.org/private/",
    "timestamp": 1640995200.0
  }
}
```

## Client Interface

### GeminiClient Class

**Constructor:**

```python
class GeminiClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        cache_enabled: bool = True,
        cache_ttl_seconds: int = 300,
        max_cache_entries: int = 1000,
        allowed_hosts: Optional[List[str]] = None,
        cert_store_path: Optional[str] = None,
        tofu_enabled: bool = True,
        max_redirects: int = 5,
        tls_min_version: str = "TLSv1.2",
    ) -> None:
```

**Core Methods:**

```python
async def fetch(self, url: str) -> GeminiFetchResponse:
    """Fetch content from Gemini URL."""

async def close(self) -> None:
    """Close client and cleanup resources."""

def get_certificate_info(self, host: str, port: int = 1965) -> Optional[GeminiCertificateInfo]:
    """Get stored certificate information for host."""

async def generate_client_certificate(self, host: str, port: int = 1965, path: str = "/") -> str:
    """Generate client certificate for authentication."""
```

## Configuration Interface

### Environment Variables

```bash
# Core settings
GEMINI_TIMEOUT_SECONDS=30
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=300
GEMINI_MAX_CACHE_ENTRIES=1000
GEMINI_ALLOWED_HOSTS=host1.example.com,host2.example.com

# Security settings
GEMINI_CERT_STORE_PATH=/path/to/certificates
GEMINI_TOFU_ENABLED=true
GEMINI_TLS_MIN_VERSION=TLSv1.2
GEMINI_MAX_REDIRECTS=5

# Client certificate settings
GEMINI_CLIENT_CERT_PATH=/path/to/client/certs
GEMINI_AUTO_GENERATE_CERTS=false
```

### Configuration Validation

- Timeout must be positive number
- Cache TTL must be positive integer
- Max cache entries must be positive integer
- Allowed hosts must be valid hostnames
- Certificate paths must be accessible directories
- TLS version must be supported (TLSv1.2, TLSv1.3)
- Max redirects must be 1-10

## Security Interface

### TOFU (Trust-on-First-Use) System

**Certificate Storage:**

```python
class TOFUStore:
    async def store_certificate(self, host: str, port: int, fingerprint: str, expires: Optional[float]) -> None:
    async def get_certificate(self, host: str, port: int) -> Optional[TOFUEntry]:
    async def verify_certificate(self, host: str, port: int, fingerprint: str) -> bool:
    async def update_last_seen(self, host: str, port: int) -> None:
    async def cleanup_expired(self) -> int:
```

**Certificate Validation:**

- First connection: Accept any certificate, store fingerprint
- Subsequent connections: Verify fingerprint matches stored value
- Certificate change: Warn user, require explicit approval
- Expiry handling: Remove expired certificates, re-establish trust

### Client Certificate Management

**Certificate Generation:**

```python
async def generate_client_certificate(
    host: str,
    port: int = 1965,
    path: str = "/",
    key_size: int = 2048,
    validity_days: int = 365,
) -> Tuple[str, str]:  # Returns (cert_path, key_path)
```

**Certificate Scope:**

- Limited to specific host, port, and path
- Cannot be reused across different hosts
- User must approve certificate generation
- Automatic cleanup of expired certificates

## Error Handling Interface

### Error Categories

1. **Network Errors**: Connection failures, timeouts
2. **Protocol Errors**: Invalid responses, malformed data
3. **Security Errors**: Certificate validation failures, TLS errors
4. **Validation Errors**: Invalid URLs, parameter validation
5. **Application Errors**: Server-side errors (status 40-59)

### Error Response Format

```python
class GeminiError(Exception):
    def __init__(
        self,
        message: str,
        code: str,
        status: Optional[int] = None,
        url: Optional[str] = None,
    ):
        self.message = message
        self.code = code
        self.status = status
        self.url = url
```

**Error Codes:**

- `NETWORK_ERROR`: Connection or network issues
- `TLS_ERROR`: TLS handshake or certificate issues
- `PROTOCOL_ERROR`: Invalid protocol responses
- `VALIDATION_ERROR`: Input validation failures
- `TIMEOUT_ERROR`: Request timeout
- `REDIRECT_LOOP`: Too many redirects
- `CERTIFICATE_ERROR`: Certificate validation issues

## Integration Points

### MCP Server Integration

**Server Registration:**

```python
# In server.py
@mcp.tool()
async def gemini_fetch(url: str) -> Dict[str, Any]:
    """Gemini fetch tool implementation."""

def get_gemini_client() -> GeminiClient:
    """Get global Gemini client instance."""
```

### Shared Utilities

**URL Parsing:**

```python
def parse_gemini_url(url: str) -> GeminiURL:
    """Parse Gemini URL into components."""

def format_gemini_url(host: str, port: int = 1965, path: str = "/", query: Optional[str] = None) -> str:
    """Format Gemini URL from components."""
```

**Content Processing:**

```python
def parse_gemtext(content: str) -> GemtextDocument:
    """Parse gemtext content into structured format."""

def format_mime_type(mime_string: str) -> GeminiMimeType:
    """Parse MIME type string into structured format."""
```

This API contract ensures consistency with existing patterns while providing comprehensive Gemini protocol support with proper security, error handling, and type safety.
