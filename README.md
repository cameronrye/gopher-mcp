# MCP Server for the **Gopher** Protocol

> Goal: a cross‑platform **Model Context Protocol (MCP)** server that lets LLMs browse Gopher resources safely and efficiently.

---

## 1) What you need to read first

* **MCP (spec + concepts)**
  * MCP spec (latest revisions, server features, messages, etc.).
    • Overview & base protocol → JSON‑RPC, lifecycle, capabilities. ([Model Context Protocol][1])
    • **Tools** (how tools are defined, listed, invoked). ([Model Context Protocol][2])
    • **Transports** (stdio and Streamable HTTP; choose per deployment). ([Model Context Protocol][3])
    • Architecture: clients discover primitives via `*/list` and execute with `tools/call`. ([Model Context Protocol][4])
* **Gopher (protocol + URI scheme)**
  * **RFC0-1436** (protocol): client sends selector + `CRLF`, server returns text; menus are lines ending CRLF and responses terminate with a `.` line. ([RFC Editor][5])
  * **RFC-4266** (URI scheme): `gopher://host:port/<gophertype><selector>[%09<search>…]`; default port **70**; type is a **one‑character** prefix; search strings follow a **tab** (`%09`). ([IETF Datatracker][6])
* **Reference MCP servers for inspiration** (patterns, ergonomics)
  * Model Context Protocol **reference servers**: includes **Fetch** (HTML→text conversion patterns) and **Filesystem** (safe, read‑only operations). ([GitHub][7])
* **SDKs**
  * **Go SDK (official)** — great for single‑binary, cross‑platform builds. ([GitHub][8])
  * **Python SDK (official)** — rapid iteration; stdio & HTTP transports supported. ([GitHub][9])
  * **TypeScript SDK (official)** — if you prefer Node runtimes. ([GitHub][10])

---

## 2) Suggested stack (portable + simple)

**Option A — Go (recommended for production)**

* *Why*: strong stdlib networking, easy concurrency, single static binary for macOS/Windows/Linux.
* *Pieces*:
  • **modelcontextprotocol/go-sdk** for MCP;
  • **go‑gopher** lib for RFC-1436 client ops. ([GitHub][8])

**Option B — Python (fastest to prototype)**

* *Why*: batteries‑included sockets, rich SDK, easy packaging via `uv`/`pipx`.
* *Pieces*:
  • **mcp (Python SDK)**;
  • **Pituophis** for Gopher client utilities. ([GitHub][9])

> Transport: prefer **stdio** for local/desktop hosts (Claude Desktop, IDE clients), add **Streamable HTTP** if you want remote usage. ([Model Context Protocol][3])

---

## 3) Minimal server design (MVP)

**Expose one tool** (name it `gopher.fetch`):

* **Input (JSON Schema)**

  * `url` *(string, required)* — full `gopher://…` URL per RFC 4266; or
  * Advanced form: `{ host, port=70, type, selector, search? }`. ([IETF Datatracker][6])
* **Behavior**

  1. Parse URL: extract `host`, `port` (default 70), `gophertype`, `selector`, optional `search` (tab‑separated). ([IETF Datatracker][6])
  2. Open TCP → send `selector` (and, for type `7`, append `\t<search>`) + **`\r\n`**. ([RFC Editor][5])
  3. Read until close; for menus: stop on a line `.`. ([RFC Editor][5])
* **Output (LLM‑friendly)**

  * If **menu** (type `1`): return **structured JSON** list of items:
    `{ type, title, selector, host, port }` (the five tab‑separated fields from each line). ([RFC Editor][5])
  * If **text** (type `0`): return `text` as UTF‑8.
  * If **binary/unknown**: return `{ kind:"binary", bytes:N, note:"not returned" }`.

> Tool lifecycle and discovery: implement `tools/list` and `tools/call` per spec so clients can discover and invoke `gopher.fetch`. ([Model Context Protocol][2])

---

## 4) Gopher implementation notes (hardening)

* **Menu format**: first char is item **type** (`0` text, `1` menu, `7` search, etc.); fields are **tab‑separated**; lines end **CRLF**; response ends with a line `.`. ([RFC Editor][5])
* **Search (type `7`)**: send `selector`, **tab**, `search`, then `CRLF`. Handle URL `%09` decoding. ([IETF Datatracker][6])
* **URL parsing**: if path is empty, type defaults to `1` (directory). Mind the leading type char in the path. ([IETF Datatracker][6])
* **Libraries**:
  • Go: `github.com/prologic/go-gopher` (client & server helpers). ([Go Packages][11])
  • Python: **Pituophis** (simple `get(host, port, path, query)` APIs). ([PyPI][12])

---

## 5) Features that matter to **LLMs**

* **Structured menus**: always parse menus into JSON objects (not raw text). This improves planning (“pick item titled *FAQ* next”). (Pattern borrowed from the **Fetch** server’s HTML→text shaping.) ([GitHub][13])
* **Deterministic output shapes**: define a stable schema for `MenuResult` and `TextResult` so the host can render or chain calls.
* **Type‑aware follow‑ups**: include `nextUrl` (fully formed `gopher://…`) for each item to make recursive navigation trivial for the model.
* **Search support**: accept `search` input to drive Veronica‑style indices (type `7`). ([RFC Editor][5])
* **Result size controls**: `maxBytes`, `maxItems`, `timeoutMs` to protect model context.
* **Caching**: in‑memory LRU keyed by `host|port|selector|search` (Gopher content is mostly static).
* **Binary guardrails**: detect non‑text; return metadata only (size, guessed MIME) to avoid polluting context.
* **Provenance**: echo back the exact request (`host`, `port`, `selector`, `type`) in the result so models can cite or retry.

---

## 6) Security & reliability checklist

* **Transport choice**: prefer **stdio** for local hosts; use **Streamable HTTP** only when you need remote connectivity. ([Model Context Protocol][3])
* **Sanitize & bound**: cap line length, item count, and total bytes per fetch; reject selectors containing tab/CR/LF in violation of RFC rules. ([IETF Datatracker][6])
* **Time/outbound limits**: set connection/read timeouts; optional allow‑list of Gopher hosts.
* **Credentials**: RFC-4266 notes Gopher has **no privacy** and **plaintext auth** (if used); treat it as public‑data only. ([IETF][14])
* **Observability**: structured logs per call (host, selector, size, duration).
* **Permission model**: expose a single read‑only tool; no file writes or command exec (use Filesystem server patterns as inspiration). ([GitHub][15])

---

## 7) Development flow (quick)

1. **Scaffold** an MCP server (Go/Python SDK quickstarts). ([GitHub][8])
2. **Add `gopher.fetch`** tool definition (schema + handler). ([Model Context Protocol][2])
3. **Implement**: RFC-4266 URL parse → RFC-1436 request/response → menu parser. ([IETF Datatracker][6])
4. **Test** with an MCP client/inspector and a few public Gopher holes (e.g., menus & text retrieval).
5. **Polish**: caching, size limits, error taxonomy, structured outputs.

---

## 8) “Competition” & inspiration

* **Gopher‑specific MCP servers**: none clearly discovered in public listings/repositories at time of writing (searched GitHub + MCP server directories). That’s an opportunity to be first. ([GitHub][7])
* **Inspiration**: study **Fetch** (document shaping) and **Filesystem** (defensive IO & safe scopes) reference servers. ([GitHub][13])

*(Search notes: looked for “Gopher MCP server / Model Context Protocol gopher”; results surfaced general MCP repos and a “GopherSecurity/gopher‑mcp” **C++ SDK**, which is unrelated to the Gopher protocol.)* ([GitHub][16])

---

## 9) Language/tech recommendation (summary)

* **Go + go‑sdk + go‑gopher** → best portability/perf; single binary, easy CI/CD. ([GitHub][8])
* **Python + mcp + Pituophis** → fastest to build; great for experimentation and richer text processing. ([GitHub][9])

---

## 10) Handy links

* **MCP**
  • Spec overview · server features · tools · transports. ([Model Context Protocol][1])
  • Reference servers (Fetch, Filesystem, etc.). ([GitHub][7])
  • Go SDK · Python SDK · TypeScript SDK. ([GitHub][8])
* **Gopher**
  • **RFC-1436** (protocol). ([RFC Editor][5])
  • **RFC-4266** (URI scheme). ([IETF Datatracker][6])
  • Python **Pituophis** · Go **go‑gopher**. ([PyPI][12])

---

## 11) Example I/O shapes (keep it this small)

### tools/list -> define once
```json
{
  "name": "gopher.fetch",
  "description": "Fetch Gopher menus or text by URL.",
  "inputSchema": {
    "type": "object",
    "required": ["url"],
    "properties": { "url": { "type": "string", "format": "uri" } }
  }
}
```

### Success: menu
```json
{
  "kind": "menu",
  "items": [
    { "type": "1", "title": "Floodgap Home", "selector": "/home", "host": "gopher.floodgap.com", "port": 70, "nextUrl": "gopher://gopher.floodgap.com:70/1/home" }
  ]
}
```

### Success: text
```json
{ "kind": "text", "charset": "utf-8", "bytes": 2314, "text": "..." }
```

### Error
```json
{ "error": { "code": "ECONN", "message": "dial tcp 203.0.113.1:70: i/o timeout" } }
```

---

### Final tips

* Keep the **tool surface small**, the **outputs structured**, and the **timeouts strict**.
* Document limits (max bytes/items), and surface provenance for every fetch.
* Use the reference servers’ ergonomics to make it “automatic” for LLMs to chain calls. ([GitHub][13])

[1]: https://modelcontextprotocol.io/specification/2025-06-18 "Specification - Model Context Protocol"
[2]: https://modelcontextprotocol.io/specification/2025-06-18/server/tools "Tools - Model Context Protocol"
[3]: https://modelcontextprotocol.io/docs/concepts/transports "Transports - Model Context Protocol"
[4]: https://modelcontextprotocol.io/docs/learn/architecture "Architecture overview - Model Context Protocol"
[5]: https://www.rfc-editor.org/rfc/rfc1436 "RFC 1436:  The Internet Gopher Protocol (a distributed document search and retrieval protocol) "
[6]: https://datatracker.ietf.org/doc/html/rfc4266 "RFC 4266 - The gopher URI Scheme"
[7]: https://github.com/modelcontextprotocol/servers "GitHub - modelcontextprotocol/servers: Model Context Protocol Servers"
[8]: https://github.com/modelcontextprotocol/go-sdk "GitHub - modelcontextprotocol/go-sdk: The official Go SDK for Model ..."
[9]: https://github.com/modelcontextprotocol/python-sdk "GitHub - modelcontextprotocol/python-sdk: The official Python SDK for ..."
[10]: https://github.com/modelcontextprotocol/typescript-sdk "GitHub - modelcontextprotocol/typescript-sdk: The official TypeScript ..."
[11]: https://pkg.go.dev/github.com/prologic/go-gopher "gopher package - github.com/prologic/go-gopher - Go Packages"
[12]: https://pypi.org/project/Pituophis/ "Pituophis · PyPI"
[13]: https://github.com/modelcontextprotocol/servers/blob/main/src/fetch "servers/src/fetch at main · modelcontextprotocol/servers · GitHub"
[14]: https://www.ietf.org/rfc/rfc4266.txt "www.ietf.org"
[15]: https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem "servers/src/filesystem at main · modelcontextprotocol/servers · GitHub"
[16]: https://github.com/GopherSecurity/gopher-mcp "GitHub - GopherSecurity/gopher-mcp: MCP C++ SDK - Model Context ..."
