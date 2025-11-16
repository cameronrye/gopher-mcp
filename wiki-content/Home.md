# Gopher & Gemini MCP Server Wiki

Welcome to the **Gopher & Gemini MCP Server** wiki! This wiki provides comprehensive documentation, guides, and resources for using and contributing to the project.

## What is Gopher & Gemini MCP Server?

A modern, cross-platform [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI assistants to browse and interact with both [Gopher protocol](<https://en.wikipedia.org/wiki/Gopher_(protocol)>) and [Gemini protocol](https://geminiprotocol.net/) resources safely and efficiently.

## Quick Links

- [Installation Guide](Installation)
- [Configuration](Configuration)
- [API Reference](API-Reference)
- [Advanced Features](Advanced-Features)
- [Contributing Guide](Contributing)
- [Troubleshooting](Troubleshooting)

## Getting Started

### Prerequisites

- **Python 3.11+** - [Download here](https://www.python.org/downloads/)
- **uv package manager** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

### Quick Installation

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

## Documentation

### User Guides

- **[Installation](Installation)** - Complete installation instructions for all platforms
- **[Configuration](Configuration)** - Environment variables and settings
- **[Usage Examples](Usage-Examples)** - Common use cases and examples
- **[AI Assistant Guide](AI-Assistant-Guide)** - How to use with Claude and other LLMs

### Developer Guides

- **[Architecture](Architecture)** - System design and component overview
- **[API Reference](API-Reference)** - Complete API documentation
- **[Contributing](Contributing)** - How to contribute to the project
- **[Development Setup](Development-Setup)** - Setting up your development environment
- **[Testing Guide](Testing-Guide)** - Writing and running tests

### Protocol Guides

- **[Gopher Protocol](Gopher-Protocol)** - Understanding the Gopher protocol
- **[Gemini Protocol](Gemini-Protocol)** - Understanding the Gemini protocol
- **[Security Features](Security-Features)** - TOFU, TLS, and security best practices

### Advanced Topics

- **[Advanced Features](Advanced-Features)** - Caching, client certificates, and more
- **[Performance Tuning](Performance-Tuning)** - Optimization tips and best practices
- **[Troubleshooting](Troubleshooting)** - Common issues and solutions
- **[Migration Guide](Migration-Guide)** - Upgrading between versions

## Features

- **Dual Protocol Support**: `gopher_fetch` and `gemini_fetch` tools
- **Comprehensive Gopher Support**: Menus, text files, search servers, and binary files
- **Full Gemini Implementation**: Native gemtext parsing, TLS security, status codes
- **Advanced Security**: TOFU certificate validation, client certificates, secure TLS
- **Safety First**: Built-in timeouts, size limits, input sanitization, host allowlists
- **LLM-Optimized**: Structured JSON responses designed for AI consumption
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Modern Development**: Full type checking, linting, testing, and CI/CD

## Community

- **GitHub Repository**: [cameronrye/gopher-mcp](https://github.com/cameronrye/gopher-mcp)
- **Documentation**: [cameronrye.github.io/gopher-mcp](https://cameronrye.github.io/gopher-mcp)
- **Bug Reports**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Feature Requests**: [GitHub Discussions](https://github.com/cameronrye/gopher-mcp/discussions)
- **MCP Community**: [MCP Discord](https://discord.gg/modelcontextprotocol)

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/cameronrye/gopher-mcp/blob/main/LICENSE) file for details.

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
