# Gemini Troubleshooting and FAQ

This document provides troubleshooting guidance and answers to frequently asked questions about the Gemini protocol implementation in the Gopher & Gemini MCP Server.

## Common Issues and Solutions

### TLS Connection Issues

#### Problem: TLS Handshake Failures

```
Error [TLS_ERROR]: TLS connection failed
```

That message is fixed and carries no detail on purpose. The OpenSSL specifics
(`TLS handshake failed: <ssl detail>`) go to the **server log**, not to the tool
reply, so raise `GOPHER_MCP_LOG_LEVEL=DEBUG` and read the log to find out which
of the causes below applies.

`TLS_ERROR` is narrower than it looks. It means an `ssl.SSLError` — the
handshake itself failed. A connection that was refused, unreachable or reset
never got that far and is reported as `FETCH_ERROR`; a certificate this client
declined to trust is one of the `CERTIFICATE_*` codes. If you are seeing
`TLS_ERROR`, the TCP connection succeeded and the TLS negotiation did not.

!!! note "You will never see `CERTIFICATE_VERIFY_FAILED` here"
    Gemini has no certificate authorities, so this client's TLS context runs with `verify_mode=CERT_NONE` and `check_hostname=False` and OpenSSL never validates a chain or a hostname. That is deliberate and fixed in code: server identity is established by the TOFU pin instead, *after* the handshake. An OpenSSL verification error is therefore not something this client can produce — if a page or another tool tells you to fix one, it is not describing this server.

**Causes and Solutions:**

1. **TLS Version Incompatibility**
   - **Cause**: The server cannot negotiate TLS 1.2 or 1.3
   - **Note**: The minimum TLS version is fixed in code at TLS 1.2 and is not configurable. A server that cannot negotiate TLS 1.2+ cannot be reached; this is intentional.

2. **SNI Issues**
   - **Cause**: Server requires SNI but client isn't sending it
   - **Solution**: Ensure hostname is properly set in URL. A non-ASCII hostname
     is IDNA-encoded before it is used, so the SNI and the request line always
     carry the same A-label.

3. **Cipher or extension incompatibility**
   - **Cause**: An old or unusual server implementation
   - **Solution**: Reproduce it outside this server with
     `openssl s_client -connect host:1965 -servername host`; if that fails too,
     the fault is on the capsule's side.

A **certificate the client refused to trust** is a different failure with a
different code — `CERTIFICATE_CHANGED`, `CERTIFICATE_EXPIRED`,
`CERTIFICATE_NOT_YET_VALID` or `CERTIFICATE_UNVERIFIED`, each covered below.

#### Problem: TOFU Fingerprint Mismatch

```
Error [CERTIFICATE_CHANGED]: Server certificate failed TOFU verification (it
does not match the previously trusted certificate). ...
```

The full message goes on to name the two tools below; the fingerprints
themselves and the store's path stay in the log.

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

!!! warning "Editing `tofu.json` by hand is no longer the way"
    The trust-store tools take the same cross-process lock the server does, so they cannot lose a concurrent writer's pins, and they act on exactly one host. Hand-editing (or `rm`-ing) the file takes no lock and makes it easy to clear far more trust than intended — deleting the file re-pins *every* host on next use, including any that was being intercepted. Reach for the file only when the server is not running and the tools are unavailable.

#### Problem: Certificate Not Yet Valid

```
Error [CERTIFICATE_NOT_YET_VALID]: Certificate for example.org:1965 is not yet
valid (notBefore is in the future); refusing to trust on first use
```

**Cause**: The certificate the capsule presented claims a validity window that
has not started yet, by more than five minutes. On a **first** visit that is
refused outright and nothing is pinned — a server has no legitimate reason to
present a certificate before its own `notBefore`, and doing so is a recognised
active-interception signal.

This code exists because the condition used to be reported as
`CERTIFICATE_EXPIRED`, which inverts the diagnosis and sends the reader after a
renewal that is not the problem.

**Solutions:**

1. **Check this machine's clock.** A client clock running *behind* the capsule's
   is the ordinary cause. The client already tolerates five minutes of
   disagreement — capsules routinely mint a self-signed certificate at startup
   with `notBefore=now` — so a refusal means the gap is larger than that.
   `timedatectl status` / `sntp -sS pool.ntp.org` will tell you.
2. **Wait, if the clock is right.** Once wall time passes the `notBefore` the
   certificate pins normally on the next request.
3. **Do not set `GEMINI_TOFU_REJECT_EXPIRED`** looking for a switch: it does not
   gate this check. Not-yet-valid is refused unconditionally; only the
   *already-expired* case is governed by that setting.

#### Problem: TOFU Trust Store Could Not Be Written

```
Error [CERTIFICATE_STORE_UNAVAILABLE]: The TOFU trust store could not be written
-- it is locked by another process, or the location is not writable -- so the
server certificate could not be recorded. This is a local problem, not a problem
with the capsule: check GEMINI_TOFU_STORAGE_PATH (and the HOME it defaults
under) rather than retrying.
```

**Cause**: One of two things, and the message no longer guesses between them.
Either another process — usually a second server instance sharing the same
`GEMINI_TOFU_STORAGE_PATH` — held the store's lock for longer than the wait
allows, or the store simply cannot be created or written where it is pointed.
The certificate itself was never in question; only recording the pin failed, and
the request is refused rather than continuing unpinned.

Nothing survives in memory either: a pin that could not be persisted is dropped,
so the next request re-enters the first-use path and retries the write. It is
not served as "already trusted" on a pin recorded nowhere.

The same code now covers a **client-certificate** store that cannot be created,
and the setup failure of either store — both of which used to be reported as
`FETCH_ERROR` / "Failed to initialize the fetch client", pointing at the network
for what is a local storage problem.

**Solutions:**

1. **Check the location is writable.** The store defaults into gopher-mcp's own
   data directory (`~/.local/share/gopher-mcp/` on Linux,
   `~/Library/Application Support/gopher-mcp/` on macOS), or stays at an
   existing `~/.gemini/tofu.json` on an install that predates the move. The
   concrete path is in the log, not in the reply.
2. **Read-only `HOME`, or a container with no writable home.** This is the most
   common non-lock cause. Point both stores somewhere the process can write and
   mount it:

   ```bash
   export GEMINI_TOFU_STORAGE_PATH=/data/gopher-mcp/tofu.json
   export GEMINI_CLIENT_CERTS_STORAGE_PATH=/data/gopher-mcp/certs
   ```

   Use a persistent volume: a store that is recreated on every run re-pins every
   host on first use, which is exactly the window TOFU exists to close. The
   parent directory must already exist and be writable by the server user.
3. **Retry** if — and only if — the log shows lock contention. Then give each
   instance its own store with `GEMINI_TOFU_STORAGE_PATH` if you run several
   servers concurrently.
4. **Check for a stale lock file** (`tofu.json.lock`, beside the store) left
   behind by a process that was killed, and remove it if no server is running.

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
     `registry.json` still exist in the certificate directory and are readable
     by the server user; an entry whose files are gone attaches nothing, and
     creating a replacement for that scope is allowed because there is no key
     left to lose

3. **Check directory permissions and space.** The default is `certs/` under
   gopher-mcp's data directory — `~/.local/share/gopher-mcp/certs` on Linux,
   `~/Library/Application Support/gopher-mcp/certs` on macOS — or an existing
   `~/.gemini/certs` on an install that predates the move.

   ```bash
   CERTS=${GEMINI_CLIENT_CERTS_STORAGE_PATH:-~/.local/share/gopher-mcp/certs}
   chmod 700 "$CERTS"
   df -h "$CERTS"
   ```

   Do not create the directory by hand to fix this: the certificate manager
   creates it owner-only when the first identity is minted, and a directory
   made with a looser umask leaves private keys more readable than intended.

#### Problem: `client_cert_warning` in the result

```
"request_info": {
  "tls_version": "TLSv1.2",
  "client_cert_warning": "Identity certificate was transmitted in the clear: the server negotiated TLS 1.2, which sends client certificates unencrypted"
}
```

**Cause**: The capsule negotiated TLS 1.2 while an in-scope client certificate
was attached. TLS 1.3 moved client certificates behind the handshake's
encryption; TLS 1.2 does not, so anyone on the path saw the user's persistent
identity for that scope. The fetch is **not** refused — refusing would lock the
user out of capsules that only speak 1.2 — but the Gemini specification makes
warning about it a client SHOULD, so the result says so and the server logs it.

**What to do:**

1. **Tell the user**, if the identity is one they care about. Nothing is
   retroactively fixable; the disclosure has already happened.
2. **Ask the operator to enable TLS 1.3.** This is the only real fix and it is
   on the capsule's side.
3. **Remove the identity** with `gemini_client_cert_update(action="remove", ...)`
   if the capsule does not actually need one — a scope with no certificate has
   nothing to leak. Removal destroys the private key permanently, so confirm
   first.

There is a second, unrelated exposure worth knowing about: a client certificate
is presented **during the handshake**, which finishes before the TOFU pin can be
checked. A server that TOFU then rejects with `CERTIFICATE_CHANGED` has still
received the identity. The request is withheld; the identity is not recoverable.

### Connection and Timeout Issues

#### Problem: Connection Timeouts

```
Error [FETCH_ERROR]: The request timed out
```

A refused, unreachable or reset connection comes back under the same
`FETCH_ERROR` code with a different message — the resolved IP address is never
echoed back, only the errno's canonical text, so `Connection refused by
example.org:1965` is as specific as it gets. A capsule with several addresses is
tried in turn: each gets its own share of what is left of the deadline, so a
black-holed first address falls through to the second rather than consuming the
whole budget.

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
Error [DNS_ERROR]: Could not resolve host: example.invalid
```

`DNS_ERROR` and `BLOCKED` are deliberately distinct: a name that does not
resolve was never *refused* by the SSRF policy — there was no address to
evaluate — so reporting a typo as a security block would send you hunting for an
allowlist problem that does not exist.

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
Error [PROTOCOL_ERROR]: The server sent a malformed Gemini response: Status code
out of range: 99
```

**Cause**: The *server* sent something that is not a Gemini response. This is
reported as `PROTOCOL_ERROR` rather than `INVALID_REQUEST` on purpose: the URL
was fine, so telling the caller to fix it would send them the wrong way. The
detail after the colon names the defect — a status line that is too short, a
missing space after the status, a non-numeric or out-of-range status, or a
missing CRLF.

Over-long `META` values are handled per family rather than uniformly:

- **2x and 3x** — the MIME type and the redirect target — still reject hard past
  1024 bytes. A truncated value in either place is worse than none: a half-URL
  is still a fetchable URL.
- **1x, 4x, 5x and 6x** are prose. Past 1024 bytes they are truncated with an
  explicit `[truncated]` marker rather than reported as malformed, because
  hiding a long 4x error message behind "the server sent a malformed Gemini
  response" loses the only thing that said what went wrong. The Gemini ABNF
  bounds the request URI, not these.

**Solutions:**

1. **Check Server Compliance**
   - Verify the server implements the Gemini protocol correctly
   - Try the same URL with a reference Gemini client

2. **Enable Debug Logging**

   ```bash
   export GOPHER_MCP_LOG_LEVEL=DEBUG
   ```

#### Problem: Gemtext looks wrong in the result

Gemtext parsing does not fail. Every line falls back to `type: "text"` if no
marker matches, so there is no "failed to parse" error to look for — if a
document looks wrong, it is a question about how a line was classified or how
the body was decoded.

**Things to check:**

1. **Encoding.** A body is decoded with the `charset` the capsule named,
   falling back when that fails; the charset actually used is reported back on
   the result, so compare it with what you expected.
2. **The shape of a line.** A parsed line is one object: `content` is the raw
   source line, and only what the marker cannot say is added beside it (`text`
   and `level` for a heading, `link` for a link line, `alt_text` and `language`
   for a preformat toggle). There is no nested `heading`/`list`/`quote`/
   `preformat` object any more, and no whole-document `raw_content` in the
   payload — `document.lines[*].content` already carries every line.
3. **Line endings are not the problem.** The parser splits on line boundaries
   and accepts CRLF and LF alike, so `lines[*].content` never carries a `\r`
   either way.
4. **A truncated document deliberately drops its trailing partial line**, so
   half a `=> url` never parses as a whole link. `next_offset` points at that
   cut; pass it back as `offset` to read on.

#### Problem: `ROBOTS_UNAVAILABLE` — refused, but nothing disallowed you

```
Error: Could not fetch robots.txt from example.org because the connection
timed out, so this request was refused ...
```

The robots gate has **two** error codes, and this is the one that is *not* a
policy decision:

| Code | What happened | What to do |
|------|---------------|------------|
| `BLOCKED_BY_ROBOTS` | The capsule published a policy and it forbids this path | Nothing to fix — the operator's decision, and it will not change on a retry or under a different spelling of the path. Say the resource is excluded and stop. `GEMINI_RESPECT_ROBOTS_TXT=false` overrides the check, but only for a host the user has said they operate |
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

#### Problem: Geminispace search is disallowed

```
Error [BLOCKED_BY_ROBOTS]: kennedy.gemi.dev disallows this resource in its
robots.txt. This is the capsule operator's decision and will not change on a
retry ...
```

**Cause**: Nothing is misconfigured. Both of Geminispace's search engines
publish a robots.txt that excludes their own query paths:

- `kennedy.gemi.dev` — `/search`, `/lucky`, `/image-search`,
  `/archive/history`, `/archive/search`, `/archive/cached`, `/page-info?`,
  `/reports/site-health?`, `/reports/domain-backlinks?`
- `tlgs.one` — `/search`, `/v/search`, `/search_jump`, `/v/search_jump`,
  `/add_seed`, `/backlinks`, `/api`

With `GEMINI_RESPECT_ROBOTS_TXT` at its default of `true`, a search URL there is
refused before anything reaches the network. Kennedy's own root page fetches
normally, and its very first link is `=> /search 🔍 Search`, so following the
advertised route walks straight into the block. **Searching Geminispace does not
work out of the box, and it is not meant to.** These are small, hobbyist-run
servers whose operators have asked automated clients not to query them.

**What actually works:**

1. **Browse rather than query.** Everything outside those paths is fetchable —
   fetch `gemini://kennedy.gemi.dev/robots.txt` yourself (it comes back as an
   ordinary `success` result) rather than guessing which paths are in scope.
2. **Follow links from a known starting point.** Geminispace is small enough
   that link-walking from an aggregator or a gemlog index is a realistic
   discovery strategy.
3. **Use Gopher for search.** Type-7 servers carry no equivalent exclusion:
   `gopher://gopher.floodgap.com/7/v2/vs` answers `gopher_fetch` searches
   normally, and `gopher_fetch` takes the terms directly in its `search`
   argument.

**What not to do:** reach for `GEMINI_RESPECT_ROBOTS_TXT=false`. It disables the
gate for *every* host, not the one in front of you, and it is a decision about a
host you operate — not a step in getting an answer. Turning it off to run a query
against someone else's server is doing the thing they asked you not to do.

#### Problem: `SLOW_DOWN` — the host is still backing off

```
Error [SLOW_DOWN]: example.org asked this client to slow down, and the backoff
has 142.0 seconds left to run. Nothing was sent.
```

**Cause**: The capsule answered a previous request with status 44 and named a
retry period, or the per-host rate limit is otherwise oversubscribed. The
remaining wait is longer than `GEMINI_TIMEOUT_SECONDS`, so the fetch reports it
instead of sleeping through it. A status-44 penalty can run to five minutes,
which would blow past the MCP client's own call timeout while holding one of the
`GEMINI_MAX_CONCURRENT_REQUESTS` slots.

`retry_after_seconds` on the error says exactly how long is left. Nothing was
sent, and the refused request does not push the next caller further back — the
refusal happens before a slot is reserved.

**What to do:**

1. **Wait it out, or do something else.** Retrying immediately returns the same
   answer with a slightly smaller number.
2. **Tell the user how long the wait is** rather than silently stalling.
3. **Do not raise `GEMINI_REQUESTS_PER_MINUTE` to get around it.** A status-44
   backoff is honoured regardless of that setting: the capsule asked, and the
   setting governs our own politeness floor, not its request.
4. **Raise `GEMINI_TIMEOUT_SECONDS`** only if you would rather short waits be
   slept through than reported. The threshold for reporting is that value.

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

- Mandatory TLS 1.2+ encryption, with no version or verification knobs to get
  wrong
- TOFU certificate validation, failing closed when a pin cannot be recorded
- SSRF guarding: loopback and private ranges are refused unless
  `GEMINI_ALLOW_LOCAL_HOSTS=true`, with optional host and port allowlists
- Robots exclusion honoured by default, failing closed when the policy cannot be
  retrieved
- Client certificate support that never mints an identity on its own

Two exposures are documented rather than eliminated, and are worth knowing
about: a client certificate is presented **before** the TOFU pin can be checked,
and over TLS 1.2 it is sent unencrypted. See
[`client_cert_warning`](#problem-client_cert_warning-in-the-result).

### Performance Questions

**Q: How does caching work?**

A: The server maintains separate caches for Gopher and Gemini responses. Cached responses are stored with TTL (time-to-live) and automatically expired. Cache size is limited to prevent memory issues. A result served from the cache says so: it carries `cached: true` along with `cached_at` (when the copy was actually fetched) and `cache_age_seconds`, so a replay is never mistaken for the current state of a resource.

**Q: How do I get a fresh copy without turning caching off?**

A: Pass `refresh: true` to `gemini_fetch` (or `gopher_fetch`) for that one call. It skips the cache lookup and re-fetches from the server; the fresh response still replaces the cached entry, so this bypasses the cache for a request rather than disabling it. `gemini_batch_fetch` and `gopher_batch_fetch` take `refresh` too and apply it to every URL in the list, so "has any of these five posted today" is one call rather than five.

**Q: Can I disable caching?**

A: Yes, set `GEMINI_CACHE_ENABLED=false` to disable Gemini caching. Gopher caching is controlled separately with `GOPHER_CACHE_ENABLED`. Setting `GEMINI_CACHE_TTL_SECONDS=0` has the same effect: a zero TTL disables caching rather than storing entries that expire the instant they are written.

**Q: What are the performance characteristics?**

A: Performance depends on network conditions and server responsiveness. Typical response times:

- Cached responses: < 1ms
- Local network: 10-50ms
- Internet connections: 100-2000ms

### Configuration Questions

**Q: Where are certificates stored?**

A: In gopher-mcp's own per-user data directory, as `tofu.json` and `certs/`.
The exact directory depends on the platform and on `XDG_DATA_HOME`, and an
install that already has `~/.gemini/tofu.json` or `~/.gemini/certs/` keeps using
those permanently — the full resolution order, the reason for the move away from
`~/.gemini/`, and the two override variables are in
[where Gemini state is stored](configuration.md#where-gemini-state-is-stored).

To find the file on this machine without guessing:

```bash
ls -la "${XDG_DATA_HOME:-$HOME/.local/share}/gopher-mcp/"   # Linux/BSD default
ls -la ~/Library/Application\ Support/gopher-mcp/           # macOS default
ls -la ~/.gemini/                                            # legacy location
```

**Q: How do I configure for production use?**

A: Start from the [Production preset](configuration.md#production) in the Configuration Guide, then add host allowlists (`GEMINI_ALLOWED_HOSTS`) and keep TOFU validation on; the [Hardened / Restricted Access preset](configuration.md#hardened-restricted-access) shows both.

**Q: Can I supply my own client certificate and key?**

A: No. There is no environment variable pointing the server at an external cert/key pair; certificates are managed per host/port/path scope under `GEMINI_CLIENT_CERTS_STORAGE_PATH` (defaulting to `certs/` in the data directory above), and one that exists for the requested scope is attached automatically when `GEMINI_CLIENT_CERTS_ENABLED=true`. The server mints its own on request — `gemini_client_cert_update` over MCP, or `GeminiClient.generate_client_certificate` in-process — and the store stays empty until something explicitly asks for one.

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
