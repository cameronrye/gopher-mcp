# Security Policy

## 🔒 Security Overview

The Gopher MCP Server is designed with security as a primary concern. This document outlines our security practices, how to
report vulnerabilities, and the measures we take to protect users.

## 🛡️ Security Measures

### Network Security

- **Timeout Protection**: All network requests have configurable timeouts (default: 30 seconds)
- **Size Limits**: Response size limits prevent memory exhaustion attacks (default: 1MB)
- **URL Validation**: Input URLs are validated to prevent malicious requests
- **Protocol Restriction**: Only Gopher protocol (gopher://) URLs are accepted
- **No Arbitrary Code Execution**: The server only fetches and parses Gopher content

### Input Validation

- **URL Sanitization**: All URLs are parsed and validated before use
- **Content Type Checking**: Response content types are verified
- **Encoding Validation**: Text content encoding is validated and sanitized
- **Path Traversal Prevention**: Gopher selectors are validated to prevent path traversal

### Resource Protection

- **Memory Limits**: Response size limits prevent memory exhaustion
- **Connection Limits**: Concurrent connection limits prevent resource exhaustion
- **Cache Security**: Cached responses are isolated and have TTL limits
- **Error Handling**: Error messages don't leak sensitive system information

### Dependencies

- **Regular Updates**: Dependencies are regularly updated for security patches
- **Vulnerability Scanning**: Automated scanning with `safety` and `bandit`
- **Minimal Dependencies**: Only essential dependencies are included
- **Trusted Sources**: All dependencies are from trusted PyPI sources

## 🚨 Supported Versions

We provide security updates for the following versions:

| Version | Supported |
| ------- | --------- |
| 1.x.x   | ✅ Yes    |
| < 1.0   | ❌ No     |

## 📢 Reporting a Vulnerability

### How to Report

If you discover a security vulnerability, please report it responsibly:

1. **DO NOT** create a public GitHub issue
2. **Email** security reports to: [security@example.com](mailto:security@example.com)
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

```bash
# Set conservative limits
export MAX_RESPONSE_SIZE=524288    # 512KB instead of 1MB
export TIMEOUT_SECONDS=15          # Shorter timeout
export CACHE_TTL_SECONDS=60        # Shorter cache TTL
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

| Variable            | Security Impact              | Recommendation                    |
| ------------------- | ---------------------------- | --------------------------------- |
| `MAX_RESPONSE_SIZE` | Prevents memory exhaustion   | Set based on your needs, max 10MB |
| `TIMEOUT_SECONDS`   | Prevents hanging connections | 15-60 seconds recommended         |
| `CACHE_ENABLED`     | Reduces network requests     | Enable for better security        |
| `CACHE_TTL_SECONDS` | Limits stale data exposure   | 60-300 seconds recommended        |

### Example Secure Configuration

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": ["--directory", "/path/to/gopher-mcp", "run", "task", "serve"],
      "env": {
        "MAX_RESPONSE_SIZE": "524288",
        "TIMEOUT_SECONDS": "15",
        "CACHE_ENABLED": "true",
        "CACHE_TTL_SECONDS": "60"
      }
    }
  }
}
```

## 🛠️ Security Testing

### Automated Security Checks

Our CI/CD pipeline includes:

- **Bandit**: Static security analysis for Python
- **Safety**: Dependency vulnerability scanning
- **Ruff**: Code quality and security linting
- **MyPy**: Type checking to prevent runtime errors

### Manual Security Testing

We recommend:

- **Input Fuzzing**: Test with malformed URLs and data
- **Resource Exhaustion**: Test with large responses and timeouts
- **Network Security**: Test in isolated network environments
- **Error Handling**: Verify error messages don't leak information

### Security Test Examples

```python
# Test URL validation
def test_malicious_url_rejection():
    """Test that malicious URLs are rejected."""
    malicious_urls = [
        "http://example.com/",  # Wrong protocol
        "gopher://localhost:22/",  # SSH port
        "gopher://internal.network/",  # Internal network
    ]
    for url in malicious_urls:
        with pytest.raises(ValidationError):
            validate_gopher_url(url)

# Test resource limits
def test_response_size_limit():
    """Test that oversized responses are rejected."""
    # Implementation would test actual size limits
    pass
```

## 🚨 Known Security Considerations

### Gopher Protocol Limitations

- **No Encryption**: Gopher protocol doesn't support encryption
- **No Authentication**: No built-in authentication mechanism
- **Plain Text**: All communication is in plain text
- **Legacy Protocol**: May have undiscovered vulnerabilities

### Mitigation Strategies

- **Network Monitoring**: Monitor all Gopher traffic
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
- [Gopher Protocol Specification](https://tools.ietf.org/html/rfc1436)

### Internal Documentation

- [Contributing Guidelines](CONTRIBUTING.md) - Security requirements for contributors
- [Development Setup](README.md#development) - Secure development environment
- [API Documentation](docs/) - Security considerations for each API

## 📞 Contact

For security-related questions or concerns:

- **Security Email**: [security@example.com](mailto:security@example.com)
- **General Issues**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)

## 🏆 Security Hall of Fame

We recognize security researchers who help improve our security:

<!-- Future security researchers will be listed here -->

Thank you for helping keep the Gopher MCP Server secure! 🔒
