# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project structure and foundation
- Modern Python development environment with uv, ruff, mypy
- Comprehensive testing framework with pytest
- Pre-commit hooks for code quality
- GitHub Actions CI/CD pipeline
- MkDocs documentation site
- Basic MCP server implementation
- Gopher protocol client foundation
- Pydantic models for data validation
- Structured logging with structlog
- Caching system for Gopher responses
- Security safeguards and input validation

### Changed

- N/A (initial release)

### Deprecated

- N/A (initial release)

### Removed

- N/A (initial release)

### Fixed

- N/A (initial release)

### Security

- Input validation for Gopher URLs and selectors
- Response size limits to prevent DoS attacks
- Timeout handling for network requests
- Secure defaults for all configuration options

## [0.1.0] - 2025-01-XX

### Added

- Initial release of Gopher MCP server
- Support for basic Gopher protocol operations
- MCP tool: `gopher.fetch` for retrieving Gopher resources
- Support for Gopher item types: 0 (text), 1 (menu), 7 (search), 9 (binary)
- Structured JSON responses optimized for LLM consumption
- Async implementation with connection pooling
- In-memory LRU cache with configurable TTL
- Comprehensive error handling and logging
- Security features: timeouts, size limits, input sanitization
- Cross-platform support (Linux, macOS, Windows)
- Both stdio and HTTP transport support
- Extensive test suite with >90% coverage
- Complete documentation and examples

[Unreleased]: https://github.com/cameronrye/gopher-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cameronrye/gopher-mcp/releases/tag/v0.1.0
