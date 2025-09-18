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
# Check version
gopher-mcp --version

# Run basic health check
gopher-mcp --help
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

#### Other MCP Clients

For HTTP transport:

```json
{
  "mcpServers": {
    "gopher": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

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

- Check the [Troubleshooting Guide](gemini-troubleshooting.md)
- Open an issue on [GitHub](https://github.com/cameronrye/gopher-mcp/issues)
- Review the [API Reference](api-reference.md) for detailed usage information
