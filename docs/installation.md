# Installation Guide

This guide covers different ways to install and set up the Gopher & Gemini MCP Server.

## Requirements

- Python 3.11 or later
- Operating System: Linux, macOS, or Windows
- [`uv`](https://docs.astral.sh/uv/) for the zero-install (`uvx`) and
  from-source workflows. A plain `pip install` does not need it.

## Installation Methods

### Method 1: Zero-install with uvx (Recommended)

```bash
uvx gopher-mcp --version
```

`uvx` downloads the package into a throwaway environment and runs it, so there
is nothing to install and nothing to keep up to date. This is also the form
every MCP client configuration below uses: `uvx` is a single well-known binary,
whereas a `pip`-installed `gopher-mcp` has to be on the `PATH` of whatever
launched the client — which a GUI application started from the desktop usually
does not inherit.

### Method 2: PyPI

```bash
pip install gopher-mcp
```

This puts a `gopher-mcp` console script in the active environment. Use it when
you want a pinned, resolvable install (in a container image, or a virtualenv you
manage yourself) rather than a fresh resolve on every launch.

### Method 3: From Source

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

### Method 4: Development Installation

For contributors and developers:

```bash
# Clone and set up development environment
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Run the development setup script
./scripts/dev-setup.sh          # Windows: scripts\dev-setup.bat
```

Project tasks then run through `uv run task <command>` — see
[the task runner](contributing.md#the-task-runner) in the Contributing guide.

### Method 5: Docker

Tagged releases publish an image to `ghcr.io/cameronrye/gopher-mcp`, tagged with
the release version, plus `:latest` for stable (non-pre-release) tags:

```bash
# Default CMD: streamable-http on 0.0.0.0:8000
docker run --rm -p 8000:8000 \
  -v gopher-mcp-state:/home/app/.local/share/gopher-mcp \
  ghcr.io/cameronrye/gopher-mcp:latest

# Or stdio, for an MCP client that spawns the process
docker run --rm -i --no-healthcheck \
  -v gopher-mcp-state:/home/app/.local/share/gopher-mcp \
  ghcr.io/cameronrye/gopher-mcp:latest --transport stdio
```

To run a modified tree, build from a checkout — the repository ships the
`Dockerfile` the published image is built from:

```bash
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp
docker build -t gopher-mcp .
```

Three things about the container are worth knowing before you run it:

- **Mount a volume for Gemini state, or it is discarded on every run.** The TOFU
  certificate pins and any client-certificate private keys live in the server's
  per-user data directory. Without a volume, each start re-arms blind
  trust-on-first-use — the pinned fingerprint is the only thing authenticating a
  Gemini server — and destroys any minted client identity, whose private key
  cannot be recovered. There is deliberately no `VOLUME` instruction in the
  image: an anonymous volume is recreated per `docker run` and deleted again by
  `--rm`, so it would persist nothing while looking as though it did.

    The mount path in those commands is exact, not illustrative.
    `/home/app/.local/share/gopher-mcp` is where the code writes `tofu.json`
    and `certs/` — the container's
    [per-user data directory](configuration.md#where-gemini-state-is-stored),
    with `XDG_DATA_HOME` unset as it is in the image — and it is the one
    directory the image pre-creates owned by the runtime user and mode `700`,
    which is what lets a named volume come up writable rather than root-owned.
    Mount anywhere else and the store still goes to that path *inside* the
    container, so the volume persists an empty directory.

    `~/.gemini` is not it. That location is only a read-in-place upgrade route
    for installs that pinned certificates before gopher-mcp had a directory of
    its own, and the resolver honours it only when the store *file* is already
    there — which it never is in a fresh image. Redirecting `XDG_DATA_HOME`
    back at it would work, and would put the state straight back into Google's
    Gemini CLI configuration directory, which is what moving out of there was
    for.
- **The `HEALTHCHECK` probes `GET /health` on port 8000**, matching the default
  `CMD`. Override it alongside `--port`, and pass `--no-healthcheck` for a
  `stdio` container — stdio serves no HTTP, so the probe would report a working
  container as unhealthy.
- **The `ENTRYPOINT` is `gopher-mcp`**, so anything after the image name is
  passed straight to the CLI.

CI builds this image and smoke-tests `gopher-mcp --help` on every pull request,
so it stays in step with the project's supported Python versions.

## Verification

Verify your installation:

```bash
# Confirm the console script is available and report the version
gopher-mcp --version
gopher-mcp --help

# For a uvx install (nothing is on the PATH)
uvx gopher-mcp --version

# For the container
docker run --rm --no-healthcheck ghcr.io/cameronrye/gopher-mcp:latest --version
```

`--version` and `--help` are answered before the configuration is loaded, so
they still work when an environment variable holds a value the server would
reject at startup.

!!! note "`--version` needs 0.9.0 or newer"
    The flag landed in 0.9.0. An install predating it answers `error:
    unrecognized arguments: --version` instead — which means the install worked
    and is simply older; `gopher-mcp --help` verifies it either way. The same
    applies to `--allowed-host` and to `GET /health`.

## Configuration

### MCP Client Integration

Every client below runs the server over **stdio**, which needs no ports, no TLS
and no listening socket. Use the HTTP transports only for a client that can talk
to a URL and nothing else — see [HTTP transports](#http-transports).

If you installed with `pip` rather than `uvx`, replace `"command": "uvx"` /
`"args": ["gopher-mcp"]` with `"command": "gopher-mcp"` and `"args": []`, using
the absolute path from `which gopher-mcp` when the client does not inherit your
shell `PATH`.

#### Claude Desktop

Edit `claude_desktop_config.json`:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uvx",
      "args": ["gopher-mcp"]
    }
  }
}
```

Fully quit and restart Claude Desktop after editing the file; reloading the
window is not enough.

#### Claude Code

Add it from the CLI — `--` separates Claude Code's own options from the command
it should run:

```bash
# Available in every project on this machine
claude mcp add --scope user gopher -- uvx gopher-mcp

# Or check it into one repository, for the whole team
claude mcp add --scope project gopher -- uvx gopher-mcp
```

Project scope writes `.mcp.json` at the repository root, which you can also
create by hand:

```json
{
  "mcpServers": {
    "gopher": {
      "type": "stdio",
      "command": "uvx",
      "args": ["gopher-mcp"]
    }
  }
}
```

#### Cursor

`~/.cursor/mcp.json` for every project, or `.cursor/mcp.json` in a repository for
that project only:

```json
{
  "mcpServers": {
    "gopher": {
      "type": "stdio",
      "command": "uvx",
      "args": ["gopher-mcp"]
    }
  }
}
```

#### VS Code

`.vscode/mcp.json` in the workspace — note the top-level key is `servers`, not
`mcpServers`:

```json
{
  "servers": {
    "gopher": {
      "type": "stdio",
      "command": "uvx",
      "args": ["gopher-mcp"]
    }
  }
}
```

To enable it for every workspace instead, run **MCP: Open User Configuration**
from the Command Palette and add the same entry there.

#### Zed

Zed's `settings.json` (**zed: open settings**), under `context_servers`:

```json
{
  "context_servers": {
    "gopher": {
      "command": "uvx",
      "args": ["gopher-mcp"],
      "env": {}
    }
  }
}
```

#### Windsurf

`~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uvx",
      "args": ["gopher-mcp"],
      "env": {}
    }
  }
}
```

Any of these entries can carry an `env` object to set the server's
configuration variables — see the
[Configuration Guide](configuration.md#3-mcp-client-configuration).

### HTTP transports

For a client that connects to a URL rather than spawning a process, start the
server on an HTTP transport:

```bash
# Streamable HTTP (the current MCP HTTP transport)
gopher-mcp --transport streamable-http

# Or the older SSE transport
gopher-mcp --transport sse
```

Both transports default to the **same** address, `127.0.0.1:8000`; only the
endpoint path differs. `--host` and `--port` change the bind address.

| Transport | Endpoint to configure | Also served |
|-----------|----------------------|-------------|
| `streamable-http` | `http://127.0.0.1:8000/mcp` | `GET /health` |
| `sse` | `http://127.0.0.1:8000/sse` | client POSTs to `/messages/`; `GET /health` |

The path matters: `http://127.0.0.1:8000/` is a 404 under both transports, so a
client configured with the bare origin never connects. `GET /health` answers on
either transport and is the right target for a container or Kubernetes probe.

Both transports speak JSON-RPC 2.0, so a tool call posted to the endpoint has
this shape:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "gopher_fetch",
    "arguments": { "url": "gopher://gopher.floodgap.com/1/" }
  }
}
```

In a client that takes a URL, the streamable-http entry looks like this:

```json
{
  "mcpServers": {
    "gopher": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

`GET /health` returns `{"status": "ok", "version": "..."}` and is what the
container's `HEALTHCHECK`, a compose healthcheck or a Kubernetes probe should
read — `/mcp` rejects anything short of a real session handshake (`406` without
the right `Accept` header, `400` with it), so a wedged process is
indistinguishable from a healthy one there, and `/` is a plain 404. The route bypasses
authorization by SDK design and reports nothing but liveness and the version: no
configuration, no host allowlists, no store paths.

!!! warning "Securing the HTTP transport"
    The HTTP-based transports (`streamable-http`, `sse`) expose an
    **unauthenticated** endpoint with no built-in TLS. By default they bind to
    loopback (`127.0.0.1:8000`), which is safe for local use. Binding to
    `0.0.0.0` exposes the server on **all interfaces** and should only be done
    behind a trusted reverse proxy that terminates TLS and handles
    authentication. The provided **Dockerfile** defaults its `CMD` to
    `--transport streamable-http --host 0.0.0.0 --port 8000` so the container is
    reachable out of the box — override it for production (bind `127.0.0.1`, or
    use the `stdio` transport) unless it sits behind such a proxy.

#### Host header checking, and the 421 you may see

The MCP SDK enables DNS-rebinding protection — an allowlist of acceptable `Host`
headers — whenever the server is built for loopback, and disables it when the
operator asks to be reachable on a routable address. `gopher-mcp` reproduces that
decision for the CLI flags: with no `--host`, or a loopback one, only
`localhost`, `127.0.0.1` and `[::1]` are accepted as `Host`; a non-loopback
`--host` (including the container's `0.0.0.0`) turns the check **off**, because
there is no way to guess the name clients will use for a routable bind.

To keep the check on for a named proxy or container hostname, pass
`--allowed-host NAME`, repeatable:

```bash
gopher-mcp --transport streamable-http --host 0.0.0.0 \
  --allowed-host mcp.internal.example --allowed-host gopher-mcp:8000
```

Loopback stays accepted, and a bare name matches any port. A request arriving
under a name that is not on the list is refused with **`421 Misdirected
Request`** and the body `Invalid Host header` — if you see that, the bind address
is fine and the `Host` header is the thing to fix. Whatever is enforced is logged
at startup.

## Troubleshooting

### Common Issues

**Import Error**: Ensure Python 3.11+ is installed

```bash
python --version
```

**Permission Error**: Use a virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install gopher-mcp
```

**Network Issues**: Check firewall settings for Gopher port 70 and Gemini port
1965

### Getting Help

- Check the [Troubleshooting Guide](troubleshooting.md)
- Open an issue on [GitHub](https://github.com/cameronrye/gopher-mcp/issues)
- Review the [API Reference](api-reference.md) for detailed usage information
