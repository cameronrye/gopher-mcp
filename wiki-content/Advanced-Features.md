# Advanced Features

Advanced configuration and features for power users and developers.

## Response Caching

### Overview

The server implements intelligent response caching to improve performance and reduce server load.

### Configuration

**Gopher Caching**

```bash
# Enable caching (default: true)
GOPHER_CACHE_ENABLED=true

# Cache TTL in seconds (default: 300)
GOPHER_CACHE_TTL_SECONDS=300

# Disable caching
GOPHER_CACHE_ENABLED=false
```

**Gemini Caching**

```bash
# Enable caching (default: true)
GEMINI_CACHE_ENABLED=true

# Cache TTL in seconds (default: 300)
GEMINI_CACHE_TTL_SECONDS=300

# Disable caching
GEMINI_CACHE_ENABLED=false
```

### Cache Behavior

**Cache Keys**

- Gopher: Full URL including selector and search
- Gemini: Full URL including path and query

**Cache Eviction**

- LRU (Least Recently Used) strategy
- TTL-based expiration
- Maximum cache size limits

**Cache Invalidation**

- Automatic after TTL expires
- Manual by restarting server
- Disabled by setting `CACHE_ENABLED=false`

## Client Certificates (Gemini)

### Overview

Client certificates enable authenticated access to restricted Gemini content.

### Generating Certificates

**Self-Signed Certificate**

```bash
# Generate certificate and key
openssl req -x509 -newkey rsa:4096 \
  -keyout client-key.pem \
  -out client-cert.pem \
  -days 365 \
  -nodes \
  -subj "/CN=Your Name"

# Combine into single file
cat client-cert.pem client-key.pem > client.pem
```

**Certificate with Passphrase**

```bash
# Generate with passphrase protection
openssl req -x509 -newkey rsa:4096 \
  -keyout client-key.pem \
  -out client-cert.pem \
  -days 365 \
  -subj "/CN=Your Name"
```

### Certificate Storage

**Default Location**

```
~/.local/share/gopher-mcp/certs/
```

**Per-Host Certificates**

```
~/.local/share/gopher-mcp/certs/example.com.pem
~/.local/share/gopher-mcp/certs/another.com.pem
```

**Default Certificate**

```
~/.local/share/gopher-mcp/certs/default.pem
```

### Configuration

```bash
# Enable client certificates (default: true)
GEMINI_CLIENT_CERTS_ENABLED=true

# Disable client certificates
GEMINI_CLIENT_CERTS_ENABLED=false
```

## TOFU Management

### Overview

Trust-On-First-Use (TOFU) certificate validation for Gemini connections.

### TOFU Database

**Location**

```
~/.local/share/gopher-mcp/tofu/tofu.json
```

**Format**

```json
{
  "geminiprotocol.net:1965": {
    "fingerprint": "sha256:abc123...",
    "first_seen": "2024-01-01T00:00:00Z",
    "last_seen": "2024-01-02T00:00:00Z",
    "certificate": {
      "subject": "CN=geminiprotocol.net",
      "issuer": "CN=geminiprotocol.net",
      "not_before": "2024-01-01T00:00:00Z",
      "not_after": "2025-01-01T00:00:00Z"
    }
  }
}
```

### Managing TOFU

**Clear All Certificates**

```bash
rm -rf ~/.local/share/gopher-mcp/tofu/
```

**Clear Specific Host**

```bash
# Edit tofu.json and remove the host entry
nano ~/.local/share/gopher-mcp/tofu/tofu.json
```

**Disable TOFU**

```bash
export GEMINI_TOFU_ENABLED=false
```

## Performance Tuning

### Optimal Settings

**High Performance**

```bash
# Gopher
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=900
GOPHER_MAX_RESPONSE_SIZE=5242880
GOPHER_TIMEOUT_SECONDS=60

# Gemini
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=900
GEMINI_MAX_RESPONSE_SIZE=5242880
GEMINI_TIMEOUT_SECONDS=60
```

**Low Latency**

```bash
# Gopher
GOPHER_TIMEOUT_SECONDS=10
GOPHER_MAX_RESPONSE_SIZE=524288

# Gemini
GEMINI_TIMEOUT_SECONDS=10
GEMINI_MAX_RESPONSE_SIZE=524288
```

**Memory Constrained**

```bash
# Gopher
GOPHER_CACHE_ENABLED=false
GOPHER_MAX_RESPONSE_SIZE=262144

# Gemini
GEMINI_CACHE_ENABLED=false
GEMINI_MAX_RESPONSE_SIZE=262144
```

## Custom Transport Modes

### STDIO Transport (Default)

```bash
uv run task serve
```

Used for Claude Desktop and other MCP clients.

### HTTP Transport

```bash
uv run task serve-http
```

Runs server over HTTP for web-based clients.

### SSE Transport

```bash
python -m gopher_mcp --transport sse
```

Server-Sent Events transport for streaming.

## Logging Configuration

### Log Levels

```bash
# Set log level
export LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Structured Logging

```bash
# Enable structured logging (default: true)
export STRUCTURED_LOGGING=true

# Disable structured logging
export STRUCTURED_LOGGING=false
```

### Log File

```bash
# Set log file path
export LOG_FILE_PATH=/path/to/logfile.log

# Log to stdout (default)
export LOG_FILE_PATH=
```

## Development Mode

### Enable Development Mode

```bash
export DEVELOPMENT_MODE=true
```

**Features:**

- Verbose logging
- Detailed error messages
- No caching
- Relaxed timeouts

## Environment File

### Using .env File

Create `.env` in project root:

```bash
# Gopher Configuration
GOPHER_MAX_RESPONSE_SIZE=2097152
GOPHER_TIMEOUT_SECONDS=60
GOPHER_CACHE_ENABLED=true
GOPHER_CACHE_TTL_SECONDS=600

# Gemini Configuration
GEMINI_MAX_RESPONSE_SIZE=2097152
GEMINI_TIMEOUT_SECONDS=60
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_SECONDS=600
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true

# Server Configuration
LOG_LEVEL=INFO
STRUCTURED_LOGGING=true
DEVELOPMENT_MODE=false
```

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
