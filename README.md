# Gopher & Gemini MCP Server

[![CI](https://github.com/cameronrye/gopher-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/cameronrye/gopher-mcp/actions/workflows/ci.yml)
[![Documentation](https://github.com/cameronrye/gopher-mcp/actions/workflows/docs.yml/badge.svg)](https://github.com/cameronrye/gopher-mcp/actions/workflows/docs.yml)
[![PyPI version](https://badge.fury.io/py/gopher-mcp.svg)](https://badge.fury.io/py/gopher-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![codecov](https://codecov.io/gh/cameronrye/gopher-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/cameronrye/gopher-mcp)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Downloads](https://pepy.tech/badge/gopher-mcp)](https://pepy.tech/project/gopher-mcp)

A modern, cross-platform [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI assistants to
browse and interact with both [Gopher protocol](<https://en.wikipedia.org/wiki/Gopher_(protocol)>) and
[Gemini protocol](https://geminiprotocol.net/) resources safely and efficiently.

## Overview

The Gopher & Gemini MCP Server bridges vintage and modern alternative internet protocols with AI assistants, allowing LLMs like
Claude to explore the unique content and communities that thrive on both Gopherspace and Geminispace. Built with FastMCP and
modern Python practices, it provides secure, efficient gateways to these distinctive internet protocols.

**Key Benefits:**

- **Discover alternative internet content** - Access unique resources on both Gopher and Gemini protocols
- **Safe exploration** - Built-in security safeguards, TLS encryption, and content filtering
- **Modern implementation** - Uses FastMCP framework with async/await patterns
- **Developer-friendly** - Comprehensive testing, type hints, and documentation
- **Advanced security** - TOFU certificate validation and client certificate support for Gemini

## Features

- **Dual Protocol Support**: `gopher_fetch` and `gemini_fetch` tools for comprehensive protocol coverage
- **Comprehensive Gopher Support**: Handles menus (type 1), text files (type 0), search servers (type 7), and binary files
- **Full Gemini Implementation**: Native gemtext parsing, TLS security, and status code handling
- **Advanced Security**: TOFU certificate validation, client certificates, and secure TLS connections
- **Safety First**: Built-in timeouts, size limits, input sanitization, and host allowlists
- **LLM-Optimized**: Returns structured JSON responses designed for AI consumption
- **Cross-Platform**: Works seamlessly on Windows, macOS, and Linux
- **Modern Development**: Full type checking, linting, testing, and CI/CD pipeline
- **High Performance**: Async/await patterns with intelligent caching

## Documentation

Complete documentation is available at **[cameronrye.github.io/gopher-mcp](https://cameronrye.github.io/gopher-mcp)**

- [Installation Guide](https://cameronrye.github.io/gopher-mcp/installation/)
- [API Reference](https://cameronrye.github.io/gopher-mcp/api-reference/)
- [Advanced Features](https://cameronrye.github.io/gopher-mcp/advanced-features/)
- [AI Assistant Guide](https://cameronrye.github.io/gopher-mcp/ai-assistant-guide/)

## Quick Start

### Prerequisites

- **Python 3.11+** - [Download here](https://www.python.org/downloads/)
- **uv package manager** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation

#### Option 1: Development Installation (Recommended)

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

#### Option 2: PyPI Installation

```bash
# Install from PyPI (recommended for end users)
pip install gopher-mcp

# Or with uv
uv add gopher-mcp
```

#### Option 3: Development Installation

```bash
# Install directly from GitHub
uv add git+https://github.com/cameronrye/gopher-mcp.git

# Or install in development mode
git clone https://github.com/cameronrye/gopher-mcp.git
cd gopher-mcp
uv sync --all-extras
```

### Claude Desktop Integration

Add to your `claude_desktop_config.json`:

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

## Cross-Platform Development

This project includes a **unified Python-based task management system** that works across all platforms:

### Recommended (All Platforms)

```bash
python task.py <command>    # Unified Python task runner (recommended)
```

### Alternative Options

```bash
# Unix/macOS/Linux
make <command>              # Traditional make (delegates to task.py)

# Universal fallback
uv run task <command>       # Direct taskipy usage
```

### Available Commands

| Command            | Description                    |
| ------------------ | ------------------------------ |
| `dev-setup`        | Set up development environment |
| `install-hooks`    | Install pre-commit hooks       |
| `lint`             | Run ruff linting               |
| `format`           | Format code with ruff          |
| `typecheck`        | Run mypy type checking         |
| `quality`          | Run all quality checks         |
| `check`            | Run lint + typecheck           |
| `test`             | Run all tests                  |
| `test-cov`         | Run tests with coverage        |
| `test-unit`        | Run unit tests only            |
| `test-integration` | Run integration tests          |
| `serve`            | Run MCP server (stdio)         |
| `serve-http`       | Run MCP server (HTTP)          |
| `docs-serve`       | Serve docs locally             |
| `docs-build`       | Build documentation            |
| `clean`            | Clean build artifacts          |
| `ci`               | Run CI pipeline locally        |

## Usage

The server provides two powerful MCP tools for exploring alternative internet protocols:

### `gopher_fetch` Tool

Fetches Gopher menus, text files, or metadata by URL with comprehensive error handling and security safeguards.

**Parameters:**

- `url` (string, required): Full Gopher URL (e.g., `gopher://gopher.floodgap.com/1/`)

**Response Types:**

- **MenuResult**: For Gopher menus (type 1) and search results (type 7)
  - Contains structured menu items with type, display text, selector, host, and port
- **TextResult**: For text files (type 0)
  - Returns the full text content with metadata
- **BinaryResult**: Metadata only for binary files (types 4, 5, 6, 9, g, I)
  - Provides file information without downloading binary content
- **ErrorResult**: For errors or unsupported content
  - Includes detailed error messages and troubleshooting hints

### `gemini_fetch` Tool

Fetches Gemini content with full TLS security, TOFU certificate validation, and native gemtext parsing.

**Parameters:**

- `url` (string, required): Full Gemini URL (e.g., `gemini://geminiprotocol.net/`)

**Response Types:**

- **GeminiGemtextResult**: For gemtext content (text/gemini)
  - Parsed gemtext document with structured lines, links, and headings
- **GeminiSuccessResult**: For other text and binary content
  - Raw content with MIME type information
- **GeminiInputResult**: For input requests (status 10-11)
  - Prompts for user input with optional sensitive flag
- **GeminiRedirectResult**: For redirects (status 30-31)
  - New URL for temporary or permanent redirects
- **GeminiErrorResult**: For errors (status 40-69)
  - Detailed error information with status codes
- **GeminiCertificateResult**: For certificate requests (status 60-69)
  - Certificate requirement information

### Example URLs to Try

#### Gopher Protocol

```bash
# Classic Gopher menu
gopher://gopher.floodgap.com/1/

# Gopher news and information
gopher://gopher.floodgap.com/1/gopher

# Search example (type 7)
gopher://gopher.floodgap.com/7/v2/vs

# Text file example
gopher://gopher.floodgap.com/0/gopher/welcome
```

#### Gemini Protocol

```bash
# Gemini protocol homepage
gemini://geminiprotocol.net/

# Gemini software directory
gemini://geminiprotocol.net/software/

# Example personal gemlog
gemini://warmedal.se/~antenna/

# Gemini search aggregator
gemini://kennedy.gemi.dev/
```

### Example AI Interactions

Once configured, you can ask Claude:

**Gopher Exploration:**

- _"Browse the main Gopher menu at gopher.floodgap.com"_
- _"Search for 'python' on the Veronica-2 search server"_
- _"Show me the welcome text from Floodgap's Gopher server"_
- _"What's available in the Gopher community directory?"_

**Gemini Exploration:**

- _"Fetch the Gemini protocol homepage"_
- _"Show me the software directory on geminiprotocol.net"_
- _"Browse the latest posts from a gemlog"_
- _"What's the difference between Gopher and Gemini protocols?"_

## Development

### Project Structure

```text
gopher-mcp/
├── src/gopher_mcp/          # Main package
│   ├── __init__.py          # Package initialization
│   ├── server.py            # FastMCP server implementation
│   ├── gopher_client.py     # Gopher protocol client
│   ├── models.py            # Pydantic data models
│   ├── tools.py             # MCP tool definitions
│   └── utils.py             # Utility functions
├── tests/                   # Comprehensive test suite
│   ├── test_server.py       # Server tests
│   ├── test_gopher_client.py # Client tests
│   └── test_integration.py  # Integration tests
├── docs/                    # MkDocs documentation
├── scripts/                 # Development scripts
├── .github/workflows/       # CI/CD pipelines
├── Makefile                 # Unix/macOS task runner
├── task.bat                 # Windows task runner
└── pyproject.toml           # Modern Python project config
```

### Development Workflow

1. **Setup**: `uv run task dev-setup` - Install dependencies and pre-commit hooks
2. **Code**: Make your changes with full IDE support (type hints, linting)
3. **Quality**: `uv run task quality` - Run all quality checks (lint + typecheck + test)
4. **Test**: `uv run task test-cov` - Run tests with coverage reporting
5. **Commit**: Pre-commit hooks ensure code quality automatically

### Testing

```bash
# Run all tests
uv run task test

# Run with coverage
uv run task test-cov

# Run specific test types
uv run task test-unit
uv run task test-integration

# Run tests in watch mode during development
uv run pytest --watch
```

## Configuration

The server can be configured through environment variables for both protocols:

### Gopher Configuration

| Variable                   | Description                    | Default         | Example                |
| -------------------------- | ------------------------------ | --------------- | ---------------------- |
| `GOPHER_MAX_RESPONSE_SIZE` | Maximum response size in bytes | `1048576` (1MB) | `2097152`              |
| `GOPHER_TIMEOUT_SECONDS`   | Request timeout in seconds     | `30`            | `60`                   |
| `GOPHER_CACHE_ENABLED`     | Enable response caching        | `true`          | `false`                |
| `GOPHER_CACHE_TTL_SECONDS` | Cache time-to-live in seconds  | `300`           | `600`                  |
| `GOPHER_ALLOWED_HOSTS`     | Comma-separated allowed hosts  | `None` (all)    | `example.com,test.com` |

### Gemini Configuration

| Variable                      | Description                        | Default         | Example                |
| ----------------------------- | ---------------------------------- | --------------- | ---------------------- |
| `GEMINI_MAX_RESPONSE_SIZE`    | Maximum response size in bytes     | `1048576` (1MB) | `2097152`              |
| `GEMINI_TIMEOUT_SECONDS`      | Request timeout in seconds         | `30`            | `60`                   |
| `GEMINI_CACHE_ENABLED`        | Enable response caching            | `true`          | `false`                |
| `GEMINI_CACHE_TTL_SECONDS`    | Cache time-to-live in seconds      | `300`           | `600`                  |
| `GEMINI_ALLOWED_HOSTS`        | Comma-separated allowed hosts      | `None` (all)    | `example.org,test.org` |
| `GEMINI_TOFU_ENABLED`         | Enable TOFU certificate validation | `true`          | `false`                |
| `GEMINI_CLIENT_CERTS_ENABLED` | Enable client certificate support  | `true`          | `false`                |

### Example Configuration

```bash
# Gopher settings
export GOPHER_MAX_RESPONSE_SIZE=2097152
export GOPHER_TIMEOUT_SECONDS=60
export GOPHER_CACHE_ENABLED=true
export GOPHER_ALLOWED_HOSTS="gopher.floodgap.com,gopher.quux.org"

# Gemini settings
export GEMINI_MAX_RESPONSE_SIZE=2097152
export GEMINI_TIMEOUT_SECONDS=60
export GEMINI_TOFU_ENABLED=true
export GEMINI_CLIENT_CERTS_ENABLED=true
export GEMINI_ALLOWED_HOSTS="geminiprotocol.net,warmedal.se"

# Run with custom config
uv run task serve
```

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Quick Contribution Steps

1. **Fork** the repository on GitHub
2. **Clone** your fork: `git clone https://github.com/your-username/gopher-mcp.git`
3. **Setup** development environment: `uv run task dev-setup`
4. **Create** a feature branch: `git checkout -b feature/amazing-feature`
5. **Make** your changes with tests
6. **Quality** check: `uv run task quality`
7. **Commit** your changes: `git commit -m 'Add amazing feature'`
8. **Push** to your fork: `git push origin feature/amazing-feature`
9. **Submit** a pull request with a clear description

### Development Standards

- **Type hints** for all functions and methods
- **Comprehensive tests** with >90% coverage
- **Documentation** for all public APIs
- **Security** considerations for all network operations
- **Cross-platform** compatibility (Windows, macOS, Linux)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **[Model Context Protocol](https://modelcontextprotocol.io/)** by Anthropic - The foundation that makes this integration possible
- **[FastMCP](https://github.com/jlowin/fastmcp)** - High-level Python framework for building MCP servers
- **[Pituophis](https://github.com/dotcomboom/pituophis)** - Excellent Python Gopher client library
- **The Gopher Protocol Community** - Keeping the spirit of the early internet alive

## Related Projects

- [Model Context Protocol Servers](https://github.com/modelcontextprotocol/servers) - Official MCP server implementations
- [Awesome MCP Servers](https://github.com/punkpeye/awesome-mcp-servers) - Curated list of MCP servers
- [Claude Desktop](https://claude.ai/download) - AI assistant that supports MCP

## Support

- **Bug Reports**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Feature Requests**: [GitHub Discussions](https://github.com/cameronrye/gopher-mcp/discussions)
- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)
- **Community**: [MCP Discord](https://discord.gg/modelcontextprotocol)

---

<div align="center">

Made with ❤️ by [Cameron Rye](https://rye.dev/)

[Star this project](https://github.com/cameronrye/gopher-mcp) if you find it useful!

</div>
