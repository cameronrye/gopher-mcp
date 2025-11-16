# Installation Guide

This guide covers all installation methods for the Gopher & Gemini MCP Server across different platforms.

## Prerequisites

- **Python 3.11+** - [Download here](https://www.python.org/downloads/)
- **uv package manager** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

## Installation Methods

### Option 1: Development Installation (Recommended)

Best for developers and contributors who want to modify the code or stay on the latest version.

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Set up development environment
./scripts/dev-setup.sh  # Unix/macOS
# or
scripts\dev-setup.bat   # Windows

# Run the server
uv run task serve
```

### Option 2: PyPI Installation

Best for end users who want a stable release.

```bash
# Install from PyPI
pip install gopher-mcp

# Or with uv
uv add gopher-mcp
```

### Option 3: GitHub Installation

Install directly from the GitHub repository.

```bash
# Install from GitHub
uv add git+https://github.com/cameronrye/gopher-mcp.git

# Or install in development mode
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp
uv sync --all-extras
```

## Platform-Specific Instructions

### Windows

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Run the setup script
scripts\dev-setup.bat

# Run the server
uv run task serve
```

### macOS

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Run the setup script
./scripts/dev-setup.sh

# Run the server
uv run task serve
```

### Linux

```bash
# Clone the repository
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp

# Run the setup script
./scripts/dev-setup.sh

# Run the server
uv run task serve
```

## Claude Desktop Integration

### Configuration File Location

**macOS:**

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Windows:**

```
%APPDATA%\Claude\claude_desktop_config.json
```

**Linux:**

```
~/.config/Claude/claude_desktop_config.json
```

### Configuration

Add the following to your `claude_desktop_config.json`:

**Unix/macOS/Linux:**

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": ["--directory", "/path/to/gopher-mcp", "run", "task", "serve"],
      "env": {
        "MAX_RESPONSE_SIZE": "1048576",
        "TIMEOUT_SECONDS": "30"
      }
    }
  }
}
```

**Windows:**

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\gopher-mcp",
        "run",
        "task",
        "serve"
      ],
      "env": {
        "MAX_RESPONSE_SIZE": "1048576",
        "TIMEOUT_SECONDS": "30"
      }
    }
  }
}
```

## Verification

After installation, verify the setup:

```bash
# Run quality checks
uv run task quality

# Run tests
uv run task test

# Start the server
uv run task serve
```

## Next Steps

- [Configuration](Configuration) - Configure the server for your needs
- [Usage Examples](Usage-Examples) - Learn how to use the server
- [Troubleshooting](Troubleshooting) - Common issues and solutions

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
