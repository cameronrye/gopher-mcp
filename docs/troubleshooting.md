# Troubleshooting

Common problems and fixes for the Gopher & Gemini MCP Server, covering installation, connections, protocol quirks, Claude Desktop integration, configuration, and performance.

## Installation Issues

### Python Version Too Old

**Problem:** Installation or startup fails with an error about the Python version.

**Solution:** The server requires Python 3.11 or later. Check your version and upgrade if needed.

```bash
python --version
# Install Python 3.11+ from https://www.python.org/downloads/
```

### `uv: command not found`

**Problem:** Commands that use `uv` fail with `uv: command not found`.

**Solution:** Install `uv`, then restart your shell so the new binary is on your `PATH`.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

!!! note
    `uv` is only required for development and source installs. If you installed from PyPI (`pip install gopher-mcp` or `uvx gopher-mcp`), you do not need `uv` to run the server.

### Permission Denied

**Problem:** Running the development setup script fails with a permission error.

**Solution:** Make the script executable before running it.

```bash
chmod +x scripts/dev-setup.sh
./scripts/dev-setup.sh
```

### Verifying the Install

After installing, confirm the package and console script are available:

```bash
# Confirm the console script is on your PATH
gopher-mcp --help

# Confirm the package imports and check its version
python -c "import gopher_mcp; print(gopher_mcp.__version__)"
```

You can also start the server directly via `python -m gopher_mcp` or, without installing, via `uvx gopher-mcp`.

## Connection Issues

### Timeouts

**Problem:** Requests time out before completing.

**Solution:** The request timeout defaults to 30 seconds. Increase it per protocol with the appropriate prefixed environment variable.

```bash
export GOPHER_TIMEOUT_SECONDS=60
export GEMINI_TIMEOUT_SECONDS=60
```

!!! note
    `GEMINI_TIMEOUT_SECONDS` is one budget for the whole fetch — DNS, connect and handshake, trust-store write, send and read all draw down the same deadline, and with `GEMINI_RESPECT_ROBOTS_TXT=true` the `/robots.txt` probe spends from it as well. If you enable robots checking against a slow capsule, raise the timeout rather than expecting each step to get the full value.

### Connection Refused

**Problem:** Connections fail with "connection refused" errors.

**Solution:**

- Confirm the server is online and the URL (including port) is correct.
- Check local firewall settings — Gopher commonly uses port 70, Gemini uses port 1965.
- Try a different, known-good server to isolate the problem.

!!! warning
    By default the server blocks requests to local and private hosts (for example `localhost`, `127.0.0.1`, and private LAN ranges) as SSRF protection. To reach a host on your own network, set `GOPHER_ALLOW_LOCAL_HOSTS=true` or `GEMINI_ALLOW_LOCAL_HOSTS=true`. Only enable this for hosts you trust.

### DNS Failures

**Problem:** The hostname cannot be resolved.

**Solution:**

- Verify your internet connection and that the hostname is spelled correctly.
- Test resolution directly, for example `nslookup gopher.floodgap.com`.
- If you maintain a host allowlist, confirm the host is included — `GOPHER_ALLOWED_HOSTS` and `GEMINI_ALLOWED_HOSTS` restrict connections to the listed hosts only.

## Gopher-Specific Issues

### Invalid Gopher URL

**Problem:** A request fails with an "invalid Gopher URL" error.

**Solution:** Use the canonical Gopher URL format `gopher://host:port/type/selector`. The single-digit type character after the path is required.

```text
gopher://gopher.floodgap.com/1/
gopher://gopher.floodgap.com:70/0/gopher/welcome
```

### Empty Menus Are Normal

**Problem:** A Gopher menu comes back empty.

**Solution:** An empty menu is often legitimate — the directory may simply have no entries. Before assuming a bug, verify the selector path and try a different directory on the same server.

### Binary Files Return Metadata Only

**Problem:** Binary files (images, archives, executables) do not return their contents.

**Solution:** This is by design. For binary Gopher item types the server returns metadata describing the resource rather than downloading the raw bytes. There is no setting that changes this behavior.

## Claude Desktop Integration

### Server Not Appearing

**Problem:** The server does not show up in Claude Desktop.

**Solution:**

1. Use an **absolute path** to the command in your config so Claude Desktop can find it regardless of its working directory.
2. Confirm the `claude_desktop_config.json` file is valid JSON.
3. Fully quit and restart Claude Desktop after editing the config.

```json
{
  "mcpServers": {
    "gopher": {
      "command": "/absolute/path/to/gopher-mcp",
      "args": []
    }
  }
}
```

### Server Crashes on Launch

**Problem:** The server starts and immediately crashes when launched by Claude Desktop.

**Solution:** Run the server manually in a terminal to see the underlying error, which Claude Desktop may swallow.

```bash
gopher-mcp
```

Enabling debug logging (see [Configuration Issues](#configuration-issues)) often reveals the root cause.

### Where the Config File Lives

The Claude Desktop configuration file location depends on your operating system:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

## Configuration Issues

### Environment Variables Not Taking Effect

**Problem:** Configuration changes appear to be ignored.

**Solution:** Most often the variable name is missing its prefix. The server reads only prefixed names:

- Gopher settings use the `GOPHER_` prefix (for example `GOPHER_TIMEOUT_SECONDS`).
- Gemini settings use the `GEMINI_` prefix (for example `GEMINI_TIMEOUT_SECONDS`).
- Server and logging settings use the `GOPHER_MCP_` prefix (for example `GOPHER_MCP_LOG_LEVEL`, `GOPHER_MCP_LOG_FILE_PATH`).

!!! warning
    Unprefixed names such as a bare `LOG_LEVEL` or `TIMEOUT_SECONDS` are **ignored**. Always use the prefixed form. Variable names are case-sensitive, and boolean values must be exactly `true` or `false`.

Verify which variables are set and restart the server after changing them:

```bash
env | grep -E 'GOPHER|GEMINI'
```

### Server Refuses to Start on a Configuration Value

**Problem:** Startup fails with an error naming an environment variable.

**Solution:** Some values cannot be applied safely and are rejected at startup rather than silently ignored:

- An allowlist that names nothing — `GOPHER_ALLOWED_HOSTS=" , "`, or `GEMINI_ALLOWED_PORTS="$A,$B"` where the shell variables are empty. An empty allowlist is indistinguishable from an absent one, so it would quietly drop the restriction you meant to apply. **Unset** the variable to allow everything.
- A port outside `1`–`65535` in a `*_ALLOWED_PORTS` list. It could never match a request, so every fetch would be refused at runtime instead.

```bash
# Wrong: expands to an empty list and fails startup
export GOPHER_ALLOWED_HOSTS="$PRIMARY_HOST,$BACKUP_HOST"

# Right: unset it, or name at least one host
unset GOPHER_ALLOWED_HOSTS
```

### Enabling Debug Logging

**Problem:** You need more detail to diagnose an issue.

**Solution:** Raise the log level to `DEBUG`. Logs are written to standard error (stderr), never stdout — the stdio MCP transport uses stdout for the protocol stream. There is no default log file; to also capture logs to a file, opt in with `GOPHER_MCP_LOG_FILE_PATH`.

```bash
export GOPHER_MCP_LOG_LEVEL=DEBUG

# Optional: also write logs to a file
export GOPHER_MCP_LOG_FILE_PATH=/path/to/gopher-mcp.log
```

## Gemini-Specific Issues

Gemini relies on TLS and Trust-on-First-Use (TOFU) certificate validation, which have their own dedicated failure modes. For TLS handshake errors, certificate mismatches, client certificate problems, and gemtext parsing issues, see the detailed [Gemini Troubleshooting](gemini-troubleshooting.md) page.

A few quick reference points:

- The TOFU trust store is a JSON file at `~/.gemini/tofu.json` by default.
- Client certificates are stored under `~/.gemini/certs/` by default. One that already covers a host/port/path scope is attached automatically, and the fetch path never creates one, so a capsule answering status 60 needs an explicit **`gemini_client_cert_update`** call. **`gemini_client_cert_list`** (read-only) shows which scopes already hold an identity and whether each has expired.
- Creating a client certificate gives the user a persistent pseudonymous identity on that capsule, sent on every in-scope request from then on, so ask before creating one and never do it because a fetched page asked. Creation refuses to replace an in-scope certificate — the private key cannot be recovered — and removal requires naming the fingerprint being destroyed.
- If a server's certificate has changed, use the trust-store tools rather than editing the file. **`gemini_trust_list`** (read-only) reports what is pinned for a host, when it was first seen and when it expires. **`gemini_trust_update`** then removes or replaces that one host's pin — `action="remove"` requires the fingerprint currently pinned, so a pin cannot be dropped without naming what is being dropped. The next fetch re-establishes trust on first use.
- A changed fingerprint is often a routine reissue — self-signed Gemini certificates rotate at expiry — but it is also what an active machine-in-the-middle attack looks like, and the two are indistinguishable from the client. Confirm the new certificate out of band before changing a pin, and never on the say-so of a fetched page.

!!! note
    Both paths are configurable; the values above are the defaults. Changing a pin only resets stored trust for that host — it does not disable TOFU validation, and it does mean that host's identity is no longer checked against the certificate previously trusted.

## Performance

### Caching

Responses are cached per protocol to speed up repeated requests. If you want to trade freshness for speed (or the reverse), tune these settings:

```bash
# Enable or disable caching
export GOPHER_CACHE_ENABLED=true
export GEMINI_CACHE_ENABLED=true

# How long cached responses stay valid
export GOPHER_CACHE_TTL_SECONDS=600
export GEMINI_CACHE_TTL_SECONDS=600

# Maximum number of cached entries (LRU eviction when full)
export GOPHER_MAX_CACHE_ENTRIES=2000
export GEMINI_MAX_CACHE_ENTRIES=2000
```

If you are seeing stale content, lower the TTL or temporarily set `*_CACHE_ENABLED=false`. Setting a TTL of `0` also disables caching — an entry stored with a zero lifetime would expire the instant it was written, so the cache is switched off instead.

You usually do not need to reconfigure anything: a result served from the cache says so. Cacheable results carry `cached`, `cached_at` (when the copy was actually fetched) and `cache_age_seconds`, and `gopher_fetch` / `gemini_fetch` take a `refresh` argument that skips the cache for that one call while still repopulating it.

### Rate Limiting

To avoid overwhelming a server (or being rate-limited by it), cap outbound request rate per protocol:

```bash
export GOPHER_REQUESTS_PER_MINUTE=60
export GEMINI_REQUESTS_PER_MINUTE=60
```

### Concurrency Caps

Limit how many requests run at once to control resource usage:

```bash
export GOPHER_MAX_CONCURRENT_REQUESTS=10
export GEMINI_MAX_CONCURRENT_REQUESTS=10
```

!!! note
    These limits apply to the batch tools (`gopher_batch_fetch` and `gemini_batch_fetch`) as well as ordinary requests, so a single large batch will not exceed your configured concurrency.

## Getting Help

If you are still stuck:

1. Re-run with `GOPHER_MCP_LOG_LEVEL=DEBUG` and capture the output.
2. Try a different, known-good server to confirm whether the problem is client- or server-side.
3. Search existing reports and open a new one at [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues) with your error output, configuration, and the steps to reproduce.

## See Also

- [Gemini Troubleshooting](gemini-troubleshooting.md) — deep dive on TLS, certificates, and TOFU
- [Installation Guide](installation.md) — setup and verification
- [Configuration Guide](configuration.md) — full list of configuration options
