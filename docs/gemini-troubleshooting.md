# Gemini Troubleshooting and FAQ

This document provides troubleshooting guidance and answers to frequently asked questions about the Gemini protocol implementation in the Gopher & Gemini MCP Server.

## Common Issues and Solutions

### TLS Connection Issues

#### Problem: TLS Handshake Failures
```
Error: TLS handshake failed: [SSL: CERTIFICATE_VERIFY_FAILED]
```

**Causes and Solutions:**
1. **TOFU Certificate Mismatch**
   - **Cause**: Server certificate has changed since first connection
   - **Solution**: Clear TOFU storage or manually update fingerprint
   ```bash
   rm ~/.gemini/tofu.json
   # Or edit the file to remove the specific host entry
   ```

2. **TLS Version Incompatibility**
   - **Cause**: Server doesn't support configured minimum TLS version
   - **Solution**: Lower TLS version requirement
   ```bash
   export GEMINI_TLS_VERSION=TLSv1.2
   ```

3. **SNI Issues**
   - **Cause**: Server requires SNI but client isn't sending it
   - **Solution**: Ensure hostname is properly set in URL

#### Problem: Certificate Validation Errors
```
Error: Certificate validation failed: hostname mismatch
```

**Solutions:**
1. **Disable Hostname Verification** (development only)
   ```bash
   export GEMINI_TLS_VERIFY_HOSTNAME=false
   ```

2. **Check URL Format**
   - Ensure URL uses correct hostname
   - Verify hostname matches certificate

### Client Certificate Issues

#### Problem: Client Certificate Generation Fails
```
Error: Failed to generate client certificate
```

**Solutions:**
1. **Check Directory Permissions**
   ```bash
   mkdir -p ~/.gemini/client_certs
   chmod 700 ~/.gemini/client_certs
   ```

2. **Verify OpenSSL Installation**
   ```bash
   openssl version
   # Should show OpenSSL version
   ```

3. **Check Disk Space**
   ```bash
   df -h ~/.gemini/
   ```

#### Problem: Client Certificate Not Sent
```
Error: Server requested client certificate but none available
```

**Solutions:**
1. **Enable Client Certificates**
   ```bash
   export GEMINI_CLIENT_CERTS_ENABLED=true
   ```

2. **Check Certificate Scope**
   - Verify certificate exists for the requested host/path
   - Generate new certificate if needed

### Connection and Timeout Issues

#### Problem: Connection Timeouts
```
Error: Connection timeout after 30 seconds
```

**Solutions:**
1. **Increase Timeout**
   ```bash
   export GEMINI_TIMEOUT_SECONDS=60
   ```

2. **Check Network Connectivity**
   ```bash
   ping geminiprotocol.net
   telnet geminiprotocol.net 1965
   ```

3. **Verify Server Availability**
   - Try connecting with another Gemini client
   - Check if server is temporarily down

#### Problem: DNS Resolution Failures
```
Error: Name or service not known
```

**Solutions:**
1. **Check DNS Configuration**
   ```bash
   nslookup geminiprotocol.net
   ```

2. **Try Alternative DNS**
   ```bash
   export DNS_SERVER=8.8.8.8
   ```

### Protocol and Content Issues

#### Problem: Invalid Gemini Response
```
Error: Invalid status code: 99
```

**Solutions:**
1. **Check Server Compliance**
   - Verify server implements Gemini protocol correctly
   - Try with reference Gemini client

2. **Enable Debug Logging**
   ```bash
   export LOG_LEVEL=DEBUG
   ```

#### Problem: Gemtext Parsing Errors
```
Error: Failed to parse gemtext content
```

**Solutions:**
1. **Check Content Encoding**
   - Verify content is UTF-8 encoded
   - Check for BOM or encoding issues

2. **Validate Gemtext Format**
   - Ensure proper line endings (CRLF)
   - Check for malformed link lines

### Configuration Issues

#### Problem: Invalid Configuration Values
```
Error: GEMINI_CACHE_TTL_SECONDS must be between 1 and 86400
```

**Solutions:**
1. **Use Configuration Validator**
   ```bash
   python scripts/validate-config.py
   ```

2. **Check Environment Variables**
   ```bash
   env | grep GEMINI_
   ```

3. **Reset to Defaults**
   ```bash
   unset GEMINI_CACHE_TTL_SECONDS
   # Will use default value
   ```

## Frequently Asked Questions

### General Questions

**Q: What is the difference between Gopher and Gemini protocols?**

A: Gopher is a legacy protocol from the early 1990s that uses plain text connections. Gemini is a modern protocol that requires TLS encryption and uses a lightweight markup format called gemtext.

**Q: Can I use both protocols simultaneously?**

A: Yes! The server provides both `gopher_fetch` and `gemini_fetch` tools that can be used together in the same session.

**Q: Which protocol should I use?**

A: Use Gemini for modern, secure connections with rich content formatting. Use Gopher for accessing legacy content or when simplicity is preferred.

### Security Questions

**Q: What is TOFU and why is it important?**

A: TOFU (Trust-on-First-Use) is a certificate validation system that stores the fingerprint of a server's certificate on first connection and validates it on subsequent connections. It protects against man-in-the-middle attacks.

**Q: Are client certificates required?**

A: No, client certificates are optional. They're only needed for servers that require client authentication. The server can automatically generate them when needed.

**Q: How secure is the Gemini implementation?**

A: The implementation follows security best practices:
- Mandatory TLS 1.2+ encryption
- TOFU certificate validation
- Client certificate support
- Host allowlists
- Input validation and sanitization

### Performance Questions

**Q: How does caching work?**

A: The server maintains separate caches for Gopher and Gemini responses. Cached responses are stored with TTL (time-to-live) and automatically expired. Cache size is limited to prevent memory issues.

**Q: Can I disable caching?**

A: Yes, set `GEMINI_CACHE_ENABLED=false` to disable Gemini caching. Gopher caching is controlled separately with `GOPHER_CACHE_ENABLED`.

**Q: What are the performance characteristics?**

A: Performance depends on network conditions and server responsiveness. Typical response times:
- Cached responses: < 1ms
- Local network: 10-50ms
- Internet connections: 100-2000ms

### Configuration Questions

**Q: Where are certificates stored?**

A: By default:
- TOFU fingerprints: `~/.gemini/tofu.json`
- Client certificates: `~/.gemini/client_certs/`

You can customize these paths with environment variables.

**Q: How do I configure for production use?**

A: Use the production configuration example in `docs/gemini-configuration.md` and enable security features like host allowlists and TOFU validation.

**Q: Can I use custom TLS certificates?**

A: Yes, you can specify custom client certificates using `GEMINI_TLS_CLIENT_CERT_PATH` and `GEMINI_TLS_CLIENT_KEY_PATH`.

## Diagnostic Tools

### Built-in Diagnostics

1. **Configuration Validator**
   ```bash
   python scripts/validate-config.py
   ```

2. **Connection Test**
   ```bash
   python -c "
   import asyncio
   from src.gopher_mcp.server import get_gemini_client

   async def test():
       client = get_gemini_client()
       print('Gemini client initialized successfully')
       await client.close()

   asyncio.run(test())
   "
   ```

### External Tools

1. **OpenSSL for TLS Testing**
   ```bash
   openssl s_client -connect geminiprotocol.net:1965 -servername geminiprotocol.net
   ```

2. **Network Connectivity**
   ```bash
   nc -zv geminiprotocol.net 1965
   ```

3. **Certificate Information**
   ```bash
   echo | openssl s_client -connect geminiprotocol.net:1965 -servername geminiprotocol.net 2>/dev/null | openssl x509 -noout -text
   ```

## Debug Logging

Enable detailed logging for troubleshooting:

```bash
export LOG_LEVEL=DEBUG
export DEBUG_COMPONENTS=gemini_client,gemini_tls,tofu
```

This will provide detailed information about:
- TLS handshake process
- Certificate validation steps
- Request/response details
- Cache operations
- Error conditions

## Getting Help

If you encounter issues not covered in this guide:

1. **Check the logs** with debug logging enabled
2. **Validate your configuration** using the validation script
3. **Test with minimal configuration** to isolate the issue
4. **Try with a different Gemini server** to verify client functionality
5. **Check the GitHub issues** for similar problems
6. **Create a new issue** with detailed error information and configuration

## Performance Optimization

### Memory Usage

Monitor memory usage with:
```bash
# Check cache memory usage
python -c "
from src.gopher_mcp.server import get_gemini_client
client = get_gemini_client()
print(f'Cache entries: {len(client.cache) if hasattr(client, \"cache\") else \"N/A\"}')
"
```

### Connection Optimization

For high-throughput scenarios:
```bash
export MAX_CONCURRENT_CONNECTIONS=20
export CONNECTION_POOL_SIZE=10
export CONNECTION_KEEP_ALIVE=true
```

### Cache Tuning

Optimize cache settings based on usage:
```bash
# For high-traffic scenarios
export GEMINI_MAX_CACHE_ENTRIES=5000
export GEMINI_CACHE_TTL_SECONDS=1800  # 30 minutes

# For memory-constrained environments
export GEMINI_MAX_CACHE_ENTRIES=100
export GEMINI_CACHE_TTL_SECONDS=300   # 5 minutes
```

This troubleshooting guide should help resolve most common issues with the Gemini protocol implementation.
