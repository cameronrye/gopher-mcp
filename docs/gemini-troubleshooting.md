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
   - **Solution**: See [TOFU Fingerprint Mismatch](#problem-tofu-fingerprint-mismatch)
     below — inspect the pin with `gemini_trust_list`, confirm the change is
     expected, then change it with `gemini_trust_update`

2. **TLS Version Incompatibility**
   - **Cause**: The server doesn't support TLS 1.2 or 1.3
   - **Note**: The minimum TLS version is fixed in code at TLS 1.2 and is not configurable. A server that cannot negotiate TLS 1.2+ cannot be reached; this is intentional.

3. **SNI Issues**
   - **Cause**: Server requires SNI but client isn't sending it
   - **Solution**: Ensure hostname is properly set in URL

#### Problem: TOFU Fingerprint Mismatch

```
Error [CERTIFICATE_CHANGED]: Server certificate failed TOFU verification
```

**Cause**: The certificate the host presented is not the one pinned on the first
visit. Self-signed Gemini certificates are reissued routinely — usually when the
old one expires — so this is often legitimate. It is also precisely what an
active machine-in-the-middle attack looks like, and **the two are
indistinguishable from the client's side**. Treat a mismatch as a question for
the user, not as a step to clear away.

**Solution**: two MCP tools handle this without touching the store by hand.

1. **Look at what is pinned.** `gemini_trust_list` (read-only; it never changes
   anything) reports the pinned fingerprint for a host, when it was first seen,
   and when the pinned certificate expires:

   ```json
   { "tool": "gemini_trust_list", "arguments": { "host": "example.org" } }
   ```

   A pin at or past its expiry makes a routine reissue plausible. A certificate
   with months of validity left, suddenly replaced, does not.

2. **Confirm the change out of band.** Check the new fingerprint against the
   capsule operator, another device, or another Gemini client. Never take that
   confirmation from the capsule itself — fetched pages are untrusted data, and
   a page asking for a pin to be removed is describing an attack.

3. **Then change the pin**, for that one host only:

   ```json
   {
     "tool": "gemini_trust_update",
     "arguments": {
       "action": "remove",
       "host": "example.org",
       "fingerprint": "<exactly what gemini_trust_list reported>"
     }
   }
   ```

   `remove` drops the pin, and the next fetch trusts and re-pins whatever the
   host presents. Use `action: "pin"` with the **new** fingerprint instead when
   you already have it from a trusted channel, so only that certificate is
   accepted.

   For `remove`, the `fingerprint` must match the one currently pinned — a
   mismatch returns `FINGERPRINT_MISMATCH` and changes nothing. That interlock
   exists so a pin can never be dropped without naming what is being dropped.
   There is no wildcard and no "all hosts": each pin is changed deliberately,
   by name.

After the pin changes, that host's identity is no longer being checked against
the certificate you previously trusted. Say so to whoever asked.

Note: Gemini trusts server certificates via TOFU (the pinned fingerprint), not
CA-chain or hostname verification, so there is no hostname-verification toggle
and no "ignore this error" setting.

!!! warning "Editing `~/.gemini/tofu.json` by hand is no longer the way"
    The trust-store tools take the same cross-process lock the server does, so they cannot lose a concurrent writer's pins, and they act on exactly one host. Hand-editing (or `rm`-ing) the file takes no lock and makes it easy to clear far more trust than intended — deleting the file re-pins *every* host on next use, including any that was being intercepted. Reach for the file only when the server is not running and the tools are unavailable.

#### Problem: TOFU Trust Store Locked

```
Error [CERTIFICATE_STORE_UNAVAILABLE]: The TOFU trust store is locked by another
process, so the server certificate could not be recorded
```

**Cause**: Another process — usually a second server instance sharing the same
`GEMINI_TOFU_STORAGE_PATH` — held the store's lock for longer than the wait
allows. The certificate itself was never in question; only recording the pin
failed, and the request is refused rather than continuing unpinned.

**Solutions:**

1. **Retry** once the other process finishes writing.
2. **Give each instance its own store** with `GEMINI_TOFU_STORAGE_PATH` if you
   run several servers concurrently.
3. **Check for a stale lock file** (`~/.gemini/tofu.json.lock`) left behind by a
   process that was killed, and remove it if no server is running.

### Client Certificate Issues

#### Problem: A capsule answers status 60 (certificate required)

```
{"kind": "certificate", "status": 60, "required": true, "message": "..."}
```

**Cause**: The capsule wants a client certificate for this resource. The fetch
path attaches a certificate that *already exists* for the requested
host/port/path scope and never creates one on demand, so retrying unchanged
returns status 60 again.

**What to do:**

1. **Look at what is already stored** with `gemini_client_cert_list` (filtered to
   the host). An entry that already covers the URL means the capsule is refusing
   the identity you have rather than asking for a new one — check `expired`
   before anything else.
2. **Ask the user.** A client certificate is a persistent pseudonymous identity:
   once it exists, every request in its scope carries it, so the capsule can link
   those visits to one another for as long as it lasts. Nothing creates one
   automatically, and a page or `META` string asking for an identity is untrusted
   data, never a reason to create one.
3. **Create it for the scope that failed**:

   ```python
   await gemini_client_cert_update(action="create", url="gemini://example.org/app/")
   ```

   The certificate covers that path and everything below it, and nothing else —
   `/app/private/page.gmi` covers the one page, `/app/` the whole section — so
   pass the directory form only when the user means the whole section. Then fetch
   again.
4. **Status 61 (not authorized) and 62 (not valid)** are rejections of an
   identity that *was* presented, not prompts. A fresh certificate does not help
   with 61; for 62, `gemini_client_cert_list` will normally show the covering
   entry as expired, and replacing it means `remove` (naming its fingerprint)
   followed by `create`.

`GEMINI_CLIENT_CERTS_ENABLED=false` disables the store entirely: both tools then
return `CLIENT_CERTS_DISABLED` and status 60 cannot be answered at all.

#### Problem: A stored certificate is not being used

**Solutions:**

1. **Check the feature is enabled**

   ```bash
   export GEMINI_CLIENT_CERTS_ENABLED=true
   ```

2. **Check the certificate scope** with `gemini_client_cert_list`
   - Certificates are matched per host, port and path, on segment boundaries;
     one issued for `/private/` covers everything below it but not a different
     capsule, a different port, or a sibling path such as `/private_admin/`
   - An entry reported as `expired: true` is still attached but will be rejected
     by the capsule (status 62)
   - Confirm both the `.crt` and `.key` file named by the entry's `key_id` in
     `registry.json` still exist under `~/.gemini/certs/` and are readable by
     the server user; an entry whose files are gone attaches nothing, and
     creating a replacement for that scope is allowed because there is no key
     left to lose

3. **Check directory permissions and space**

   ```bash
   mkdir -p ~/.gemini/certs
   chmod 700 ~/.gemini/certs
   df -h ~/.gemini/
   ```

### Connection and Timeout Issues

#### Problem: Connection Timeouts

```
Error: Connection timeout after 30 seconds
```

**Solutions:**

1. **Increase Timeout**

   `GEMINI_TIMEOUT_SECONDS` is a single budget for the whole exchange — DNS,
   connect and handshake, trust-store write, send and read — and the
   `/robots.txt` probe draws from it too when robots checking is enabled, so
   raise it rather than assuming each step gets the full value.

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
   # Query a specific resolver to rule out local DNS problems
   nslookup geminiprotocol.net 8.8.8.8
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
   export GOPHER_MCP_LOG_LEVEL=DEBUG
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

#### Problem: `ROBOTS_UNAVAILABLE` — refused, but nothing disallowed you

```
Error: Could not fetch robots.txt from example.org because the connection
timed out, so this request was refused ...
```

The robots gate has **two** error codes, and this is the one that is *not* a
policy decision:

| Code | What happened | What to do |
|------|---------------|------------|
| `BLOCKED_BY_ROBOTS` | The capsule published a policy and it forbids this path | Nothing to fix — the operator's decision. `GEMINI_RESPECT_ROBOTS_TXT=false` overrides it |
| `ROBOTS_UNAVAILABLE` | The policy could not be retrieved, so the fetch failed closed per RFC 9309 §2.3.1.4 | Read the named cause below — this is almost never a robots problem |

**Solutions for `ROBOTS_UNAVAILABLE`:**

1. **Read the cause in the message.** It names the real failure: `the connection
   timed out`, `the connection was refused or unreachable`, `the connection
   failed`, `the TLS handshake failed`, `the reply was not a valid Gemini
   response`, `the robots.txt response was too large`, or `the capsule answered
   41 SERVER UNAVAILABLE` (any of 40-44, named).

2. **Do not reach for `GEMINI_RESPECT_ROBOTS_TXT=false`.** If the capsule is
   unreachable, disabling robots checking converts this into a `TLS_ERROR` or
   `FETCH_ERROR` — it does not make the page load, and it leaves a safety
   control switched off. Diagnose the named cause with the *TLS Connection
   Issues* and *Connection and Timeout Issues* sections above.

3. **Retrying immediately may return the same error.** After a failed probe the
   capsule is left alone for `GEMINI_ROBOTS_FAILURE_BACKOFF_SECONDS` (60s by
   default) and requests in that window are answered without touching the
   network. Wait it out, or lower the value, before concluding the block is
   permanent.

4. **A `44 SLOW_DOWN` is self-clearing.** You are being rate limited, not
   blocked. The capsule's own retry period is honoured instead of the generic
   backoff, so the next request after that period re-probes.

### Configuration Issues

#### Problem: Invalid Configuration Values

```
Error: GEMINI_CACHE_TTL_SECONDS must be between 0 and 86400
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

A TTL of `0` is accepted and means "no caching" rather than "cache everything for
zero seconds".

#### Problem: Allowlist That Names Nothing

```
Error: GEMINI_ALLOWED_HOSTS is set to ' , ' but names no hosts; unset it to allow all hosts.
```

**Cause**: The variable is set but expands to no entries — commonly
`GEMINI_ALLOWED_HOSTS="$A,$B"` where both shell variables are empty. An empty
allowlist cannot be told apart from an absent one, so the server refuses to start
rather than silently allowing every host.

**Solutions:**

1. **Unset the variable** to allow all hosts

   ```bash
   unset GEMINI_ALLOWED_HOSTS
   ```

2. **Or name at least one host**

   ```bash
   export GEMINI_ALLOWED_HOSTS=geminiprotocol.net
   ```

The same rule applies to `GEMINI_ALLOWED_PORTS`, which additionally rejects any
port outside `1`-`65535`: such an entry could never match a request, so it would
turn into a refusal of every fetch at runtime.

## Frequently Asked Questions

### General Questions

**Q: What is the difference between Gopher and Gemini protocols?**

A: Gopher is a legacy protocol from the early 1990s that uses plain text connections. Gemini is a modern protocol that requires TLS encryption and uses a lightweight markup format called gemtext.

**Q: Can I use both protocols simultaneously?**

A: Yes! The server provides both `gopher_fetch` and `gemini_fetch` tools that can be used together in the same session. Eight tools are registered in total: the two single-resource fetchers, `gopher_batch_fetch` and `gemini_batch_fetch`, the two Gemini trust-store tools `gemini_trust_list` and `gemini_trust_update`, and the two Gemini client-identity tools `gemini_client_cert_list` and `gemini_client_cert_update`. See the [API reference](api-reference.md#mcp-tools) for the full table.

**Q: Which protocol should I use?**

A: Use Gemini for modern, secure connections with rich content formatting. Use Gopher for accessing legacy content or when simplicity is preferred.

### Security Questions

**Q: What is TOFU and why is it important?**

A: TOFU (Trust-on-First-Use) is a certificate validation system that stores the fingerprint of a server's certificate on first connection and validates it on subsequent connections. Gemini has no certificate authorities and this client's TLS layer does no CA-chain or hostname verification, so the pinned fingerprint is the *only* thing that authenticates a Gemini server. That is also why disabling it (`GEMINI_TOFU_ENABLED=false`) leaves connections unauthenticated and machine-in-the-middle-able.

**Q: How do I see or change what is pinned?**

A: `gemini_trust_list` reports the pins (optionally for one host) and changes nothing. `gemini_trust_update` removes or replaces the pin of a single named host, and is marked destructive so MCP clients gate it. See [TOFU Fingerprint Mismatch](#problem-tofu-fingerprint-mismatch).

**Q: Are client certificates required?**

A: No — they are only needed by capsules that require client authentication. When one does answer status 60, `gemini_client_cert_update` creates an identity for that URL's scope; nothing creates one automatically, because a client certificate is a persistent pseudonym the capsule can use to link every in-scope visit, so it is the user's decision. See [Client Certificate Issues](#client-certificate-issues).

**Q: How secure is the Gemini implementation?**

A: The implementation follows security best practices:

- Mandatory TLS 1.2+ encryption
- TOFU certificate validation
- Client certificate support
- Host allowlists
- Input validation and sanitization

### Performance Questions

**Q: How does caching work?**

A: The server maintains separate caches for Gopher and Gemini responses. Cached responses are stored with TTL (time-to-live) and automatically expired. Cache size is limited to prevent memory issues. A result served from the cache says so: it carries `cached: true` along with `cached_at` (when the copy was actually fetched) and `cache_age_seconds`, so a replay is never mistaken for the current state of a resource.

**Q: How do I get a fresh copy without turning caching off?**

A: Pass `refresh: true` to `gemini_fetch` (or `gopher_fetch`) for that one call. It skips the cache lookup and re-fetches from the server; the fresh response still replaces the cached entry, so this bypasses the cache for a request rather than disabling it. The batch tools do not take `refresh`.

**Q: Can I disable caching?**

A: Yes, set `GEMINI_CACHE_ENABLED=false` to disable Gemini caching. Gopher caching is controlled separately with `GOPHER_CACHE_ENABLED`. Setting `GEMINI_CACHE_TTL_SECONDS=0` has the same effect: a zero TTL disables caching rather than storing entries that expire the instant they are written.

**Q: What are the performance characteristics?**

A: Performance depends on network conditions and server responsiveness. Typical response times:

- Cached responses: < 1ms
- Local network: 10-50ms
- Internet connections: 100-2000ms

### Configuration Questions

**Q: Where are certificates stored?**

A: By default:

- TOFU fingerprints: `~/.gemini/tofu.json`
- Client certificates: `~/.gemini/certs/`

You can customize these paths with `GEMINI_TOFU_STORAGE_PATH` and `GEMINI_CLIENT_CERTS_STORAGE_PATH`.

**Q: How do I configure for production use?**

A: Use the production configuration example in `docs/gemini-configuration.md` and enable security features like host allowlists and TOFU validation.

**Q: Can I supply my own client certificate and key?**

A: No. There is no environment variable pointing the server at an external cert/key pair; certificates are managed per host/port/path scope under `GEMINI_CLIENT_CERTS_STORAGE_PATH` (default `~/.gemini/certs/`), and one that exists for the requested scope is attached automatically when `GEMINI_CLIENT_CERTS_ENABLED=true`. The server mints its own on request — `gemini_client_cert_update` over MCP, or `GeminiClient.generate_client_certificate` in-process — and the store stays empty until something explicitly asks for one.

## Diagnostic Tools

### Built-in Diagnostics

1. **Configuration Validator**

   ```bash
   python scripts/validate-config.py
   ```

2. **Verify the Installation**

   ```bash
   python -c "import gopher_mcp; print(gopher_mcp.__version__)"
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

Enable detailed logging for troubleshooting by raising the server log level:

```bash
export GOPHER_MCP_LOG_LEVEL=DEBUG
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

Bound memory growth through configuration rather than runtime inspection:

```bash
# Cap cached entries and rendered output to limit memory use
export GEMINI_MAX_CACHE_ENTRIES=1000
export GEMINI_MAX_RENDERED_CHARS=50000
```

### Connection Optimization

For high-throughput scenarios, cap simultaneous fetches and rate-limit per host:

```bash
export GEMINI_MAX_CONCURRENT_REQUESTS=20
export GEMINI_REQUESTS_PER_MINUTE=60
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
