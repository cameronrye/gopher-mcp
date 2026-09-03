# Troubleshooting

Common problems and fixes for the Gopher & Gemini MCP Server, covering installation, connections, protocol quirks, MCP client integration, the HTTP transports, configuration, and performance.

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
    `uvx` ships with `uv`, so the zero-install form needs it too. Only a `pip install gopher-mcp` into an environment you manage yourself runs without `uv`.

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
# Confirm the console script is on your PATH and report the version
gopher-mcp --version
gopher-mcp --help
```

`--version` and `--help` are parsed before the configuration is loaded, so they answer even when an environment variable holds a value the server would reject at startup — which makes `gopher-mcp --version` the first thing to run on any bug report. It also works for installs that have no importable package on your `PATH`: `uvx gopher-mcp --version`, or `docker run --rm --no-healthcheck ghcr.io/cameronrye/gopher-mcp:latest --version`. `--version` landed in 0.9.0, so `error: unrecognized arguments: --version` is itself an answer — the install works and predates that release; use `gopher-mcp --help` instead.

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

**Problem:** The hostname cannot be resolved. This returns the `DNS_ERROR`
error code — *not* `BLOCKED`, which means the SSRF guard actively refused a
target that did resolve.

**Solution:**

- Verify your internet connection and that the hostname is spelled correctly.
- Test resolution directly, for example `nslookup gopher.floodgap.com`.
- If you maintain a host allowlist, confirm the host is included — `GOPHER_ALLOWED_HOSTS` and `GEMINI_ALLOWED_HOSTS` restrict connections to the listed hosts only.

### Blocked by robots.txt

Two different error codes come from the robots gate, and they call for opposite
responses.

**`BLOCKED_BY_ROBOTS`** — the server published a policy and it forbids this
path. This is the operator's decision, it will not change on a retry, and a
different spelling of the path is not a workaround: the answer is that the
resource is excluded. `GOPHER_RESPECT_ROBOTS_TXT=false` /
`GEMINI_RESPECT_ROBOTS_TXT=false` overrides the check, but only for a host you
have said you operate — it is not a setting to reach for because a fetch was
refused.

**`ROBOTS_UNAVAILABLE`** — the policy could not be read at all, and Gemini fails
closed when that happens (RFC 9309 §2.3.1.4). Nothing disallowed you; the
capsule did not answer. The message names the real problem — a timeout, a TLS
handshake failure, a refused or unreachable connection, or a status such as
`41 SERVER UNAVAILABLE`. Diagnose that, and see *Timeouts* and *Connection
Refused* above.

!!! warning
    Turning robots checking off will **not** help with `ROBOTS_UNAVAILABLE`. The
    fetch would fail anyway, just with a transport error instead — and you would
    be left with a safety control switched off. Retry instead.

Gopher fails **open**, so an unreachable policy there allows the fetch rather
than refusing it — only a real `Disallow` produces `BLOCKED_BY_ROBOTS`, and
`ROBOTS_UNAVAILABLE` is a Gemini-only outcome.

!!! note
    After a failed probe the host is left alone for `*_ROBOTS_FAILURE_BACKOFF_SECONDS` (60 seconds by default) and requests in that window are answered without contacting it. If you have just fixed the underlying problem, an immediate retry can still return the same error — wait out the backoff, or lower it, before concluding the block is permanent.

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

**Solution:** This is by design. For binary Gopher item types — `4`, `5`, `6`, `9`, `g`, `I`, `d`, `s`, `;`, `p`, `P`, `:`, `M` and `<` — the server returns metadata describing the resource rather than downloading the raw bytes. There is no setting that changes this behavior.

### Interactive Item Types Cannot Be Fetched

**Problem:** A menu entry of type `2` (CSO), `8` (Telnet) or `T` (tn3270) returns `NOT_FETCHABLE`.

**Solution:** Expected: those types name an interactive session rather than a retrievable document, so there is no body to return. The result echoes the request in `request_info`, so an entry in a batch fetch can still be matched back to its URL.

### A Menu Item With No `next_url`

**Problem:** A menu item has an empty `next_url` and cannot be followed.

**Solution:** Expected, and it is the signal to stop: an empty `next_url` means the item is display-only. Info lines (type `i`) carry no real target — the host and port a server parks there, such as `error.host:1` or `(NULL):0`, never pointed anywhere — and a menu item whose type field holds a control byte is reported as an info line for the same reason.

### Truncated Menus and Pages

**Problem:** A result comes back with `truncated: true` and is missing the end.

**Solution:** Not a dead end. A truncated result carries `next_offset`; call the same tool again with `offset` set to that value and repeat until `next_offset` is null. Menus count items and page bodies count characters (`bytes` and `size` are byte counts, never offsets), and `total_items` / `total_chars` say how much there is. The batch tools do not take `offset` — continue a truncated batch entry with the single-URL tool. Raising `*_MAX_MENU_ITEMS` or `*_MAX_RENDERED_CHARS` also works, at the cost of a larger single payload.

## Claude Desktop Integration

### Server Not Appearing

**Problem:** The server does not show up in Claude Desktop.

**Solution:**

1. Use `uvx` (`"command": "uvx"`, `"args": ["gopher-mcp"]`), or an **absolute path** to the command, so Claude Desktop can find it regardless of the `PATH` a desktop-launched application inherits.
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

### Other MCP Clients

Claude Code, Cursor, VS Code, Zed and Windsurf each want their own file and key — see [MCP Client Integration](installation.md#mcp-client-integration) for the exact path and snippet for each.

## HTTP Transport Issues

### `404 Not Found` on the Endpoint

**Problem:** The client connects to `http://127.0.0.1:8000` and gets a 404.

**Solution:** The path is part of the endpoint. Both HTTP transports default to `127.0.0.1:8000` — the port does not vary by transport — but `streamable-http` serves `/mcp` and `sse` serves `/sse` (the client then POSTs back to `/messages/`). The bare origin is a 404 under both. `GET /health` answers on either and is the right target for a container or Kubernetes probe.

### `421 Misdirected Request` / `Invalid Host header`

**Problem:** The server is bound and listening, but every request is refused with 421.

**Solution:** The `Host` header, not the bind address, is being rejected by the SDK's DNS-rebinding protection. With no `--host`, or a loopback one, only `localhost`, `127.0.0.1` and `[::1]` are accepted. Pass `--allowed-host NAME` (repeatable) with the name clients or your reverse proxy actually use; a bare name matches any port. The effective allowlist is logged at startup. See [Host header checking](installation.md#host-header-checking-and-the-421-you-may-see).

## Configuration Issues

### Environment Variables Not Taking Effect

**Problem:** Configuration changes appear to be ignored.

**Solution:** Most often the variable name is missing its prefix. The server reads only prefixed names:

- Gopher settings use the `GOPHER_` prefix (for example `GOPHER_TIMEOUT_SECONDS`).
- Gemini settings use the `GEMINI_` prefix (for example `GEMINI_TIMEOUT_SECONDS`).
- Server and logging settings use the `GOPHER_MCP_` prefix (for example `GOPHER_MCP_LOG_LEVEL`, `GOPHER_MCP_LOG_FILE_PATH`).

!!! warning
    Unprefixed names such as a bare `LOG_LEVEL` or `TIMEOUT_SECONDS` are **ignored**. Always use the prefixed form. Names are matched **case-insensitively**, so a lowercase `gemini_timeout_seconds` left behind by other tooling is read exactly like `GEMINI_TIMEOUT_SECONDS` and can be the value you are seeing. Booleans accept `true`/`false`, `1`/`0`, `yes`/`no` and `on`/`off` in any case.

Verify which variables are set and restart the server after changing them:

```bash
env | grep -E 'GOPHER|GEMINI'
```

### Server Refuses to Start on a Configuration Value

**Problem:** Startup fails with an error naming an environment variable.

**Solution:** Some values cannot be applied safely and are rejected at startup rather than silently ignored. The server exits with status `2` and one line naming the variable, the accepted range and the value you set — for example `gopher-mcp: configuration error: GOPHER_TIMEOUT_SECONDS: Input should be less than or equal to 300 (got '999')`. The usual causes:

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

**Solution:** Raise the log level to `DEBUG`. Logs are written to standard error (stderr), never stdout — the stdio MCP transport uses stdout for the protocol stream. There is no default log file; to also capture logs to a file, opt in with `GOPHER_MCP_LOG_FILE_PATH`, which **mirrors** stderr rather than redirecting it.

Everything logs through one pipeline: this server's own events, the MCP SDK's, and (on the `sse` and `streamable-http` transports) uvicorn's startup lines and access log. They share the configured renderer and level, so `GOPHER_MCP_STRUCTURED_LOGGING=true` really is JSON on every line and `GOPHER_MCP_LOG_LEVEL=DEBUG` raises uvicorn's verbosity too.

```bash
export GOPHER_MCP_LOG_LEVEL=DEBUG

# Optional: also write logs to a file
export GOPHER_MCP_LOG_FILE_PATH=/path/to/gopher-mcp.log
```

## Gemini-Specific Issues

Gemini relies on TLS and Trust-on-First-Use (TOFU) certificate validation, which have their own dedicated failure modes. For TLS handshake errors, certificate mismatches, client certificate problems, and gemtext parsing issues, see the detailed [Gemini Troubleshooting](gemini-troubleshooting.md) page.

A few quick reference points:

- The TOFU trust store is a JSON file named `tofu.json` in gopher-mcp's per-user data directory — `$XDG_DATA_HOME/gopher-mcp/` where that is set, otherwise `~/.local/share/gopher-mcp/` on Linux, `~/Library/Application Support/gopher-mcp/` on macOS and `%LOCALAPPDATA%\gopher-mcp\` on Windows. An install that already had a `~/.gemini/tofu.json` keeps using it exactly where it is, permanently — [where Gemini state is stored](configuration.md#where-gemini-state-is-stored) has the resolution order and the reason nothing is migrated.
- Client certificates are stored in `certs/` beside it (or in an existing `~/.gemini/certs/`). One that already covers a host/port/path scope is attached automatically, and the fetch path never creates one, so a capsule answering status 60 needs an explicit **`gemini_client_cert_update`** call. **`gemini_client_cert_list`** (read-only) shows which scopes already hold an identity and whether each has expired.
- Creating a client certificate gives the user a persistent pseudonymous identity on that capsule, sent on every in-scope request from then on, so ask before creating one and never do it because a fetched page asked. Creation refuses to replace an in-scope certificate — the private key cannot be recovered — and removal requires naming the fingerprint being destroyed.
- If a server's certificate has changed, use the trust-store tools rather than editing the file. **`gemini_trust_list`** (read-only) reports what is pinned for a host, when it was first seen and when it expires. **`gemini_trust_update`** then removes or replaces that one host's pin — `action="remove"` requires the fingerprint currently pinned, so a pin cannot be dropped without naming what is being dropped. The next fetch re-establishes trust on first use.
- A changed fingerprint is often a routine reissue — self-signed Gemini certificates rotate at expiry — but it is also what an active machine-in-the-middle attack looks like, and the two are indistinguishable from the client. Confirm the new certificate out of band before changing a pin, and never on the say-so of a fetched page.
- **`CERTIFICATE_STORE_UNAVAILABLE`** is a *local* fault, not a problem with the capsule: the trust or certificate store could not be locked by this process, or could not be written (a read-only or misconfigured location, a container filesystem, a full disk). Check `GEMINI_TOFU_STORAGE_PATH`, `GEMINI_CLIENT_CERTS_STORAGE_PATH` and the `HOME` they default under, rather than retrying. A pin that could not be persisted is not trusted in memory either, so the next fetch reports the same thing until the store is writable.
- **`CERTIFICATE_NOT_YET_VALID`** means the certificate's `notBefore` is more than five minutes in the future — almost always a clock skewed between the two machines, not an expiry. Five minutes of skew is tolerated; beyond that the certificate is refused on first use regardless of `GEMINI_TOFU_REJECT_EXPIRED`, because a genuinely premature certificate is the machine-in-the-middle signal the check exists for.

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
