# Installation Guide

This guide covers different ways to install and set up Gopher MCP.

## Requirements

- Python 3.11 or later
- Operating System: Linux, macOS, or Windows

## Installation Methods

### Method 1: PyPI (Recommended)

```bash
pip install gopher-mcp
```

### Method 2: From Source

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

### Method 3: Development Installation

For contributors and developers:

```bash
# Clone and set up development environment
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Run the development setup script
./scripts/dev-setup.sh
```

## Verification

Verify your installation:

```bash
# Confirm the console script is available
gopher-mcp --help

# Check the installed version
python -c "import gopher_mcp; print(gopher_mcp.__version__)"
```

## Configuration

### MCP Client Integration

#### Claude Desktop

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "gopher": {
      "command": "gopher-mcp",
      "args": []
    }
  }
}
```

The configuration file is located at:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

If `gopher-mcp` is not on Claude Desktop's `PATH`, use the absolute path to the
command (find it with `which gopher-mcp`). Fully restart Claude Desktop after
editing the file. Zero-install via `uvx` also works — set `"command": "uvx"` and
`"args": ["gopher-mcp"]`.

#### Other MCP Clients

For HTTP transport, first start the server:

```bash
# Start with streamable HTTP transport
gopher-mcp --transport streamable-http

# Or with SSE transport
gopher-mcp --transport sse
```

Then configure your MCP client to connect to the HTTP endpoint (default port varies by transport).

## Troubleshooting

### Common Issues

**Import Error**: Ensure Python 3.11+ is installed

```bash
python --version
```

**Permission Error**: Use virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install gopher-mcp
```

**Network Issues**: Check firewall settings for Gopher port 70

### Getting Help

- Check the [Troubleshooting Guide](troubleshooting.md)
- Open an issue on [GitHub](https://github.com/cameronrye/gopher-mcp/issues)
- Review the [API Reference](api-reference.md) for detailed usage information
