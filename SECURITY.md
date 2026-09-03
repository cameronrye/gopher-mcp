# Security Policy

## 🔒 Security Overview

The Gopher & Gemini MCP Server is designed with security as a primary concern. This document outlines our security practices,
how to report vulnerabilities, and the measures we take to protect users.

## 🛡️ Security Measures

### Network Security

- **Timeout Protection**: All network requests have configurable timeouts (default: 30 seconds)
- **Size Limits**: Response size limits prevent memory exhaustion attacks (default: 1MB)
- **URL Validation**: Input URLs are validated to prevent malicious requests
- **Protocol Restriction**: Only Gopher (`gopher://`) and Gemini (`gemini://`) URLs are accepted
- **SSRF Protection**: Requests to loopback, link-local, and private addresses are blocked by default
- **TLS for Gemini**: Gemini connections are encrypted and validated with Trust-on-First-Use (TOFU)
- **No Arbitrary Code Execution**: The server only fetches and parses Gopher/Gemini content

### Input Validation

- **URL Sanitization**: All URLs are parsed and validated before use
- **Content Type Checking**: Response content types are verified
- **Encoding Validation**: Text content encoding is validated and sanitized
- **Path Traversal Prevention**: Gopher selectors are validated to prevent path traversal

### Resource Protection

- **Memory Limits**: Response size limits prevent memory exhaustion
- **Connection Limits**: A concurrency cap bounds simultaneous in-flight
  fetches — `5` by default, set via `*_MAX_CONCURRENT_REQUESTS`, `0` for
  unlimited
- **Rate Limiting**: Outbound requests are paced per host — `60` per minute
  (one per second) by default, via `*_REQUESTS_PER_MINUTE`
- **Robot Exclusion**: `/robots.txt` is fetched and honoured before the first
  request on both protocols by default (`*_RESPECT_ROBOTS_TXT`), including
  rules naming AI crawler tokens
- **Cache Security**: Cached responses are isolated and have TTL limits
- **Error Handling**: Error messages don't leak sensitive system information

### Dependencies

- **Regular Updates**: Dependencies are regularly updated for security patches
- **Vulnerability Scanning**: Automated scanning with `pip-audit` and `bandit`
- **Minimal Dependencies**: Only essential dependencies are included
- **Trusted Sources**: All dependencies are from trusted PyPI sources

## 🚨 Supported Versions

<!-- Deliberately version-independent prose, not a table. The table that used to
be here named 0.4.x as the only supported line and was still saying so at
0.8.0, four minor releases later, because nothing in the release path touches
this file. If a table is ever wanted back, add a check to
scripts/validate-release.py that asserts it names the current minor from
pyproject.toml -- otherwise it will go stale again. -->

Only the latest release on PyPI receives security fixes. As a pre-1.0 project,
those fixes ship on the latest minor version; there are no maintained
backport branches for older lines.

## 📢 Reporting a Vulnerability

### How to Report

If you discover a security vulnerability, please report it responsibly:

1. **DO NOT** create a public GitHub issue
2. **Report privately** through GitHub Security Advisories:
   [Report a vulnerability](https://github.com/cameronrye/gopher-mcp/security/advisories/new)
3. **Include** detailed information about the vulnerability
4. **Provide** steps to reproduce if possible

### What to Include

Please include the following information in your report:

- **Description** of the vulnerability
- **Steps to reproduce** the issue
- **Potential impact** assessment
- **Suggested fix** if you have one
- **Your contact information** for follow-up

### Response Timeline

- **Initial Response**: Within 48 hours
- **Assessment**: Within 1 week
- **Fix Development**: Depends on severity
- **Public Disclosure**: After fix is released

### Responsible Disclosure

We follow responsible disclosure practices:

1. **Acknowledgment** of your report within 48 hours
2. **Assessment** and validation of the vulnerability
3. **Fix development** and testing
4. **Coordinated disclosure** after fix is available
5. **Credit** to the reporter (if desired)

## 🔍 Security Best Practices for Users

### Configuration

Settings are read with a `GOPHER_` or `GEMINI_` prefix (unprefixed names are
ignored). Set the equivalent `GEMINI_*` variables to apply the same limits to
Gemini.

```bash
# Set conservative limits (Gopher shown; mirror with GEMINI_ for Gemini)
export GOPHER_MAX_RESPONSE_SIZE=524288    # 512KB instead of 1MB
export GOPHER_TIMEOUT_SECONDS=15          # Shorter timeout
export GOPHER_CACHE_TTL_SECONDS=60        # Shorter cache TTL
# Keep SSRF protection on (the default) so internal hosts are unreachable
export GOPHER_ALLOW_LOCAL_HOSTS=false
```

### Network Environment

- **Firewall**: Run behind a firewall when possible
- **Network Isolation**: Consider network isolation for production use
- **Monitoring**: Monitor network traffic and resource usage
- **Logging**: Enable logging for security monitoring

### Access Control

- **Principle of Least Privilege**: Run with minimal required permissions
- **User Isolation**: Run as a non-privileged user
- **Container Security**: Use containers with security policies
- **Environment Isolation**: Isolate from sensitive systems

## 🔧 Security Configuration

### Environment Variables

Use the `GOPHER_` / `GEMINI_` prefix for each protocol.

| Variable                   | Security Impact              | Recommendation                                     |
| -------------------------- | ---------------------------- | -------------------------------------------------- |
| `GOPHER_MAX_RESPONSE_SIZE` | Prevents memory exhaustion   | Set to what you need; accepted range 1 KB – 100 MB |
| `GOPHER_TIMEOUT_SECONDS`   | Prevents hanging connections | 15-60 seconds recommended                          |
| `GOPHER_CACHE_ENABLED`     | Reduces network requests     | Enable for better security                         |
| `GOPHER_CACHE_TTL_SECONDS` | Limits stale data exposure   | 60-300 seconds recommended                         |
| `GOPHER_ALLOW_LOCAL_HOSTS` | SSRF protection (keep off)   | Leave `false` in production                        |
| `GEMINI_ALLOW_LOCAL_HOSTS` | SSRF protection (keep off)   | Leave `false` in production                        |

### Example Secure Configuration

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uvx",
      "args": ["gopher-mcp"],
      "env": {
        "GOPHER_MAX_RESPONSE_SIZE": "524288",
        "GOPHER_TIMEOUT_SECONDS": "15",
        "GOPHER_CACHE_ENABLED": "true",
        "GOPHER_CACHE_TTL_SECONDS": "60"
      }
    }
  }
}
```

## 🛠️ Security Testing

### Automated Security Checks

Our CI/CD pipeline includes:

- **Bandit**: Static security analysis for Python
- **pip-audit**: Dependency vulnerability scanning
- **Ruff**: Code quality and security linting
- **MyPy**: Type checking to prevent runtime errors

### Manual Security Testing

We recommend:

- **Input Fuzzing**: Test with malformed URLs and data
- **Resource Exhaustion**: Test with large responses and timeouts
- **Network Security**: Test in isolated network environments
- **Error Handling**: Verify error messages don't leak information

### Security Test Examples

The fetch tools never raise: a refusal comes back as a result whose `kind` is
`"error"`, carrying a machine-readable `error["code"]`. Assert on the code.

```python
import pytest
from gopher_mcp.server import gopher_fetch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://example.com/", "INVALID_REQUEST"),  # wrong scheme
        ("gopher://localhost:22/", "BLOCKED"),  # loopback + SSH port
        ("gopher://192.168.0.1/1/", "BLOCKED"),  # private range
    ],
)
async def test_malicious_url_refused(url: str, code: str) -> None:
    """A refused target is reported, not fetched and not raised."""
    result = await gopher_fetch(url)
    assert result["kind"] == "error"
    assert result["error"]["code"] == code
```

`BLOCKED` means the SSRF guard refused the target; `INVALID_REQUEST` means the
URL never passed validation. Both are answered without opening a connection.
See the [API Reference](https://cameronrye.github.io/gopher-mcp/api-reference/)
for the full error-code table.

## 🚨 Known Security Considerations

### Gopher Protocol Limitations

- **No Encryption**: Gopher protocol doesn't support encryption
- **No Authentication**: No built-in authentication mechanism
- **Plain Text**: All communication is in plain text
- **Legacy Protocol**: May have undiscovered vulnerabilities

### Gemini Protocol Security

- **TLS Encryption**: All Gemini traffic is encrypted (TLS 1.2+)
- **TOFU Validation**: Server certificates are pinned on first use; a changed fingerprint is rejected
- **Client Certificates**: Per-host client certificates are supported for Gemini identities
- **Expired Certificates**: Optionally reject certificates outside their validity window (`GEMINI_TOFU_REJECT_EXPIRED`)
- **MIME Filtering**: Optionally deny content types via `GEMINI_DENIED_MIME_TYPES`

### Mitigation Strategies

- **Network Monitoring**: Monitor Gopher and Gemini traffic
- **Content Filtering**: Filter potentially malicious content
- **Access Logging**: Log all access attempts
- **Regular Updates**: Keep the server updated

## 📋 Security Checklist

### For Developers

- [ ] Input validation for all user data
- [ ] Proper error handling without information leakage
- [ ] Resource limits and timeouts
- [ ] Security tests for new features
- [ ] Dependency updates and vulnerability scanning

### For Users

- [ ] Configure appropriate resource limits
- [ ] Run with minimal privileges
- [ ] Monitor network traffic and logs
- [ ] Keep the server updated
- [ ] Use in isolated network environments when possible

## 📚 Security Resources

### External Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.org/dev/security/)
- [Gopher Protocol Specification (RFC 1436)](https://datatracker.ietf.org/doc/html/rfc1436)
- [Gemini Protocol Specification](https://geminiprotocol.net/docs/specification.gmi)

### Internal Documentation

- [Contributing Guidelines](CONTRIBUTING.md) - Security requirements for contributors
- [Development Setup](README.md#development) - Secure development environment
- [Configuration Guide](https://cameronrye.github.io/gopher-mcp/configuration/) - Every setting, its range and its default
- [API Reference](https://cameronrye.github.io/gopher-mcp/api-reference/) - Security considerations for each tool

## 📞 Contact

For security-related questions or concerns:

- **Security Reports**: [GitHub Security Advisories](https://github.com/cameronrye/gopher-mcp/security/advisories/new)
- **General Issues**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)

## 🏆 Security Hall of Fame

We recognize security researchers who help improve our security:

<!-- Future security researchers will be listed here -->

Thank you for helping keep the Gopher & Gemini MCP Server secure! 🔒
