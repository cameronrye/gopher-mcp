# Gopher MCP - Implementation

A cross-platform Model Context Protocol (MCP) server for browsing Gopher
resources safely and efficiently.

## Overview

This project implements an MCP server that enables LLMs to browse Gopher
protocol resources through a single `gopher.fetch` tool. The server provides
structured, LLM-friendly JSON responses for Gopher menus, text files, search
results, and binary content metadata.

## Features

- **Single Tool Interface**: `gopher.fetch` tool for all Gopher operations
- **Comprehensive Support**: Handles menus (type 1), text files (type 0),
  search servers (type 7), and binary files
- **Real Gopher Protocol**: Uses the Pituophis library for authentic Gopher communication
- **Safety First**: Built-in timeouts, size limits, and input sanitization
- **LLM-Optimized**: Returns structured JSON responses optimized for
  language model consumption
- **Cross-Platform**: Works on Windows, macOS, and Linux with unified task management
- **Modern Development**: Full type checking, linting, testing, and CI/CD pipeline

## Quick Start

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/gopher-mcp.git
cd gopher-mcp

# Set up development environment
./scripts/dev-setup.sh  # Unix/macOS
# or
scripts\dev-setup.bat   # Windows

# Run the server
uv run task serve
```

## Cross-Platform Development

This project includes a unified task management system that works across all platforms:

### Unix/macOS/Linux

```bash
make <command>              # Traditional make
uv run task <command>       # Cross-platform alternative
```

### Windows

```batch
task.bat <command>          # Windows batch file
uv run task <command>       # Cross-platform alternative
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

The server provides a single MCP tool:

### `gopher.fetch`

Fetches Gopher menus or text by URL.

**Parameters:**

- `url` (string): Full Gopher URL (e.g., `gopher://gopher.floodgap.com/1/`)

**Returns:**

- **MenuResult**: For Gopher menus (type 1) and search results (type 7)
- **TextResult**: For text files (type 0)
- **BinaryResult**: Metadata only for binary files (types 4, 5, 6, 9, g, I)
- **ErrorResult**: For errors or unsupported content

### Example Usage with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gopher": {
      "command": "uv",
      "args": ["--directory", "/path/to/gopher-mcp", "run", "task", "serve"]
    }
  }
}
```

## Development

### Project Structure

```text
gopher-mcp/
├── src/gopher_mcp/          # Main package
│   ├── __init__.py
│   ├── server.py            # MCP server implementation
│   ├── gopher_client.py     # Gopher protocol client
│   ├── models.py            # Pydantic data models
│   ├── tools.py             # MCP tool definitions
│   └── utils.py             # Utility functions
├── tests/                   # Test suite
├── docs/                    # Documentation
├── scripts/                 # Development scripts
├── .github/workflows/       # CI/CD pipelines
├── Makefile                 # Unix/macOS task runner
├── task.bat                 # Windows task runner
└── pyproject.toml           # Project configuration
```

### Development Workflow

1. **Setup**: `uv run task dev-setup`
2. **Code**: Make your changes
3. **Quality**: `uv run task quality` (lint + typecheck + test)
4. **Test**: `uv run task test-cov`
5. **Commit**: Pre-commit hooks run automatically

## Configuration

The server can be configured through environment variables or initialization parameters:

- `MAX_RESPONSE_SIZE`: Maximum response size in bytes (default: 1MB)
- `TIMEOUT_SECONDS`: Request timeout (default: 30s)
- `CACHE_ENABLED`: Enable response caching (default: true)
- `CACHE_TTL_SECONDS`: Cache TTL (default: 300s)

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Set up development environment: `uv run task dev-setup`
4. Make your changes
5. Run quality checks: `uv run task quality`
6. Commit your changes: `git commit -m 'Add amazing feature'`
7. Push to the branch: `git push origin feature/amazing-feature`
8. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE)
file for details.

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) by Anthropic
- [Pituophis](https://github.com/dotcomboom/pituophis) Gopher client library
- The Gopher protocol community
