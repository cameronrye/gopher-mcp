# Security Features

Comprehensive security features implemented in the Gopher & Gemini MCP Server.

## Overview

The server implements multiple layers of security to protect against various threats while accessing Gopher and Gemini resources.

## Gopher Security

### Input Validation

**URL Validation**

- Format verification (gopher://host:port/type/selector)
- Host validation
- Port range checking (1-65535)
- Type validation (valid Gopher types)

**Selector Validation**

- Maximum length: 1024 characters
- Character sanitization
- Path traversal prevention

**Search Query Validation**

- Maximum length: 256 characters
- Character sanitization
- Injection prevention

### Resource Limits

**Response Size Limits**

```bash
# Default: 1MB
GOPHER_MAX_RESPONSE_SIZE=1048576

# Increase for larger content
GOPHER_MAX_RESPONSE_SIZE=5242880
```

**Timeout Limits**

```bash
# Default: 30 seconds
GOPHER_TIMEOUT_SECONDS=30

# Increase for slow servers
GOPHER_TIMEOUT_SECONDS=60
```

### Host Allowlists

Restrict access to specific servers:

```bash
# Allow only specific hosts
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com,gopher.quux.org

# Allow all hosts (default)
GOPHER_ALLOWED_HOSTS=
```

### Binary File Protection

Binary files (types 4, 5, 6, 9, g, I) return metadata only:

- Prevents malicious file downloads
- Avoids memory exhaustion
- Reduces bandwidth usage

## Gemini Security

### TLS Encryption

**TLS Version Requirements**

- Minimum: TLS 1.2
- Recommended: TLS 1.3
- No fallback to older versions

**Cipher Suites**

- Strong cipher suites only
- Forward secrecy required
- No weak or deprecated ciphers

**Configuration**

```python
{
    "ssl_version": "TLS 1.2+",
    "verify_mode": "CERT_REQUIRED",
    "check_hostname": True
}
```

### TOFU (Trust-On-First-Use)

**How TOFU Works**

1. **First Connection**
   - Connect to server
   - Receive certificate
   - Store certificate fingerprint
   - Allow connection

2. **Subsequent Connections**
   - Connect to server
   - Receive certificate
   - Compare fingerprint with stored
   - Allow if match, reject if different

**TOFU Database**

Location: `~/.local/share/gopher-mcp/tofu/`

Format:

```json
{
  "host:port": {
    "fingerprint": "sha256:...",
    "first_seen": "2024-01-01T00:00:00Z",
    "last_seen": "2024-01-02T00:00:00Z"
  }
}
```

**Configuration**

```bash
# Enable TOFU (default)
GEMINI_TOFU_ENABLED=true

# Disable TOFU (not recommended)
GEMINI_TOFU_ENABLED=false
```

**Managing TOFU**

```bash
# Clear TOFU database
rm -rf ~/.local/share/gopher-mcp/tofu/

# Clear specific host
# Edit ~/.local/share/gopher-mcp/tofu/tofu.json
```

### Client Certificates

**Purpose**

- Authenticate to Gemini servers
- Access restricted content
- Maintain persistent identity

**Configuration**

```bash
# Enable client certificates (default)
GEMINI_CLIENT_CERTS_ENABLED=true

# Disable client certificates
GEMINI_CLIENT_CERTS_ENABLED=false
```

**Certificate Storage**

Location: `~/.local/share/gopher-mcp/certs/`

**Generating Certificates**

```bash
# Generate self-signed certificate
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Move to certificate directory
mv key.pem cert.pem ~/.local/share/gopher-mcp/certs/
```

### Input Validation

**URL Validation**

- Format verification (gemini://host:port/path?query)
- Host validation
- Port range checking (1-65535)
- Path sanitization

**Query Validation**

- Maximum length limits
- Character sanitization
- Injection prevention

### Resource Limits

**Response Size Limits**

```bash
# Default: 1MB
GEMINI_MAX_RESPONSE_SIZE=1048576

# Increase for larger content
GEMINI_MAX_RESPONSE_SIZE=5242880
```

**Timeout Limits**

```bash
# Default: 30 seconds
GEMINI_TIMEOUT_SECONDS=30

# Increase for slow servers
GEMINI_TIMEOUT_SECONDS=60
```

### Host Allowlists

Restrict access to specific servers:

```bash
# Allow only specific hosts
GEMINI_ALLOWED_HOSTS=geminiprotocol.net,warmedal.se

# Allow all hosts (default)
GEMINI_ALLOWED_HOSTS=
```

## Common Security Configurations

### High Security

```bash
# Gopher
GOPHER_ALLOWED_HOSTS=gopher.floodgap.com
GOPHER_MAX_RESPONSE_SIZE=524288
GOPHER_TIMEOUT_SECONDS=15

# Gemini
GEMINI_ALLOWED_HOSTS=geminiprotocol.net
GEMINI_MAX_RESPONSE_SIZE=524288
GEMINI_TIMEOUT_SECONDS=15
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
```

### Balanced Security

```bash
# Gopher
GOPHER_MAX_RESPONSE_SIZE=1048576
GOPHER_TIMEOUT_SECONDS=30

# Gemini
GEMINI_MAX_RESPONSE_SIZE=1048576
GEMINI_TIMEOUT_SECONDS=30
GEMINI_TOFU_ENABLED=true
GEMINI_CLIENT_CERTS_ENABLED=true
```

### Development Mode

```bash
# Gopher
GOPHER_TIMEOUT_SECONDS=120

# Gemini
GEMINI_TIMEOUT_SECONDS=120
GEMINI_TOFU_ENABLED=false
```

## Security Best Practices

1. **Keep TOFU Enabled**: Protects against MITM attacks
2. **Use Host Allowlists**: Restrict to trusted servers
3. **Set Appropriate Limits**: Prevent resource exhaustion
4. **Monitor Logs**: Watch for suspicious activity
5. **Update Regularly**: Keep dependencies current
6. **Use Client Certificates**: For authenticated access

## Threat Mitigation

| Threat              | Mitigation                           |
| ------------------- | ------------------------------------ |
| MITM Attacks        | TOFU validation, TLS encryption      |
| Resource Exhaustion | Size limits, timeouts                |
| Malicious Content   | Binary protection, input validation  |
| Unauthorized Access | Client certificates, host allowlists |
| Data Leakage        | TLS encryption, secure storage       |

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
