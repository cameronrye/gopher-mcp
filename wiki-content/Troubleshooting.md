# Troubleshooting Guide

Common issues and solutions for the Gopher & Gemini MCP Server.

## Installation Issues

### Python Version Error

**Problem:** Error about Python version being too old.

**Solution:**

```bash
# Check Python version
python --version

# Install Python 3.11 or higher
# Download from https://www.python.org/downloads/
```

### uv Not Found

**Problem:** `uv: command not found`

**Solution:**

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or on Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Permission Denied

**Problem:** Permission errors during installation.

**Solution:**

```bash
# On Unix/macOS
chmod +x scripts/dev-setup.sh
./scripts/dev-setup.sh

# Or use sudo if needed
sudo uv run task dev-setup
```

## Connection Issues

### Timeout Errors

**Problem:** Requests timing out.

**Solution:**

```bash
# Increase timeout in configuration
export GOPHER_TIMEOUT_SECONDS=60
export GEMINI_TIMEOUT_SECONDS=60

# Or in .env file
GOPHER_TIMEOUT_SECONDS=60
GEMINI_TIMEOUT_SECONDS=60
```

### Connection Refused

**Problem:** "Connection refused" errors.

**Solution:**

- Check if the server is online
- Verify the URL is correct
- Check firewall settings
- Try a different server

### DNS Resolution Errors

**Problem:** Cannot resolve hostname.

**Solution:**

- Check internet connection
- Verify hostname is correct
- Try using IP address instead
- Check DNS settings

## Gopher-Specific Issues

### Invalid Gopher URL

**Problem:** "Invalid Gopher URL" error.

**Solution:**

```bash
# Correct format: gopher://host:port/type/selector
# Examples:
gopher://gopher.floodgap.com/1/
gopher://gopher.floodgap.com:70/0/gopher/welcome
```

### Empty Menu Response

**Problem:** Gopher menu returns empty.

**Solution:**

- Server may be down
- Menu may actually be empty
- Try a different selector path
- Check server logs

### Binary File Issues

**Problem:** Binary files not downloading.

**Solution:**
Binary files return metadata only by design. The server doesn't download binary content for security reasons.

## Gemini-Specific Issues

### Certificate Validation Errors

**Problem:** TOFU certificate validation fails.

**Solution:**

```bash
# Disable TOFU temporarily for testing
export GEMINI_TOFU_ENABLED=false

# Or clear TOFU database
rm -rf ~/.local/share/gopher-mcp/tofu/
```

### TLS Connection Errors

**Problem:** TLS handshake failures.

**Solution:**

- Server may not support TLS 1.2+
- Certificate may be invalid
- Check server is actually a Gemini server
- Try a different server

### Client Certificate Required

**Problem:** Server requires client certificate.

**Solution:**

```bash
# Enable client certificates
export GEMINI_CLIENT_CERTS_ENABLED=true

# Generate client certificate
# See Advanced Features guide
```

### Invalid Gemini URL

**Problem:** "Invalid Gemini URL" error.

**Solution:**

```bash
# Correct format: gemini://host:port/path?query
# Examples:
gemini://geminiprotocol.net/
gemini://example.com:1965/page
gemini://example.com/search?query
```

## Configuration Issues

### Environment Variables Not Working

**Problem:** Configuration changes not taking effect.

**Solution:**

```bash
# Verify environment variables are set
env | grep GOPHER
env | grep GEMINI

# Restart the server after changes
uv run task serve
```

### Cache Issues

**Problem:** Getting stale cached responses.

**Solution:**

```bash
# Disable cache temporarily
export GOPHER_CACHE_ENABLED=false
export GEMINI_CACHE_ENABLED=false

# Or reduce cache TTL
export GOPHER_CACHE_TTL_SECONDS=60
export GEMINI_CACHE_TTL_SECONDS=60
```

## Claude Desktop Integration Issues

### Server Not Appearing

**Problem:** Server doesn't show up in Claude Desktop.

**Solution:**

1. Check `claude_desktop_config.json` syntax
2. Verify file path is correct
3. Restart Claude Desktop
4. Check Claude Desktop logs

### Server Crashes

**Problem:** Server crashes when used with Claude.

**Solution:**

```bash
# Check server logs
tail -f ~/.local/share/gopher-mcp/logs/server.log

# Run server manually to see errors
uv run task serve
```

### Path Issues

**Problem:** Claude can't find the server.

**Solution:**

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/gopher-mcp",
        "run",
        "task",
        "serve"
      ]
    }
  }
}
```

## Performance Issues

### Slow Responses

**Problem:** Server responds slowly.

**Solution:**

```bash
# Enable caching
export GOPHER_CACHE_ENABLED=true
export GEMINI_CACHE_ENABLED=true

# Increase cache TTL
export GOPHER_CACHE_TTL_SECONDS=900
export GEMINI_CACHE_TTL_SECONDS=900
```

### High Memory Usage

**Problem:** Server using too much memory.

**Solution:**

```bash
# Reduce max response size
export GOPHER_MAX_RESPONSE_SIZE=524288
export GEMINI_MAX_RESPONSE_SIZE=524288

# Reduce cache size
export GOPHER_CACHE_TTL_SECONDS=60
export GEMINI_CACHE_TTL_SECONDS=60
```

## Getting Help

If you can't resolve your issue:

1. **Check Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)
2. **Search Issues**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
3. **Ask Questions**: [GitHub Discussions](https://github.com/cameronrye/gopher-mcp/discussions)
4. **Report Bugs**: [New Issue](https://github.com/cameronrye/gopher-mcp/issues/new)

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
