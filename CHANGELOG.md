# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- TBD

### Changed

- TBD

### Fixed

- TBD

## [0.2.1] - 2025-01-18

### Added

#### Gemini Protocol Support (NEW)

- Complete Gemini protocol v0.16.1 implementation
- `gemini_fetch` MCP tool for Gemini protocol access
- TLS 1.2+ client with mandatory SNI support
- TOFU (Trust-on-First-Use) certificate validation system
- Client certificate generation and management
- Gemtext parser with structured output for AI consumption
- Dual-protocol MCP server supporting both Gopher and Gemini
- Protocol-isolated caching systems
- Comprehensive security features and host allowlists

#### Security Features

- TOFU certificate fingerprint storage and validation
- Automatic client certificate generation per hostname/path scope
- TLS security configuration with minimum version enforcement
- Certificate validation error handling and recovery
- Host allowlists for both protocols
- Enhanced input validation and sanitization
- Security policy enforcement for connections

#### Documentation

- Comprehensive Gemini support documentation
- API reference for both protocols
- AI assistant usage guide
- Advanced features documentation
- Configuration reference with all environment variables
- Troubleshooting guide and FAQ
- Integration examples and best practices
- Migration guide for existing users

#### Testing and Quality Assurance

- Comprehensive test suite for Gemini protocol
- Security and penetration testing
- Performance and load testing
- Integration tests for dual-protocol operation
- Test coverage >95% for all new features

### Changed

- Updated package metadata to reflect dual-protocol support
- Enhanced error handling and logging across both protocols
- Improved configuration validation and defaults
- Updated dependencies to include cryptography for certificate management

### Security

- TLS 1.2+ enforcement for all Gemini connections
- Certificate fingerprint validation with TOFU
- Secure client certificate generation and storage
- Enhanced input validation for both protocols
- Connection timeout and size limit enforcement

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

[Unreleased]: https://github.com/cameronrye/gopher-mcp/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/cameronrye/gopher-mcp/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/cameronrye/gopher-mcp/releases/tag/v0.1.0
