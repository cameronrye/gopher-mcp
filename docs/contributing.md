# Contributing to Gopher MCP Server

Thank you for your interest in contributing to the Gopher MCP Server! This document provides guidelines and information for contributors.

## Quick Start for Contributors

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:

   ```bash
   git clone https://github.com/your-username/gopher-mcp.git
   cd gopher-mcp
   ```

3. **Set up** the development environment:

   ```bash
   uv run task dev-setup
   ```

4. **Create** a feature branch:

   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Environment

### Prerequisites

- **Python 3.11+** - [Download here](https://www.python.org/downloads/)
- **uv package manager** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Git** - [Install Git](https://git-scm.com/downloads)

### Setup

The project uses `uv` for dependency management and includes cross-platform task runners:

```bash
# Set up development environment (installs dependencies and pre-commit hooks)
uv run task dev-setup

# Verify setup
uv run task quality
```

### Available Development Commands

**Recommended (Unified Python Task Runner):**

| Command                     | Description                    |
| --------------------------- | ------------------------------ |
| `python task.py dev-setup`  | Set up development environment |
| `python task.py quality`    | Run all quality checks         |
| `python task.py test`       | Run all tests                  |
| `python task.py test-cov`   | Run tests with coverage        |
| `python task.py lint`       | Run ruff linting               |
| `python task.py format`     | Format code with ruff          |
| `python task.py typecheck`  | Run mypy type checking         |
| `python task.py serve`      | Run MCP server locally         |
| `python task.py docs-serve` | Serve documentation locally    |

**Alternative Commands:**

| Command                 | Description                       |
| ----------------------- | --------------------------------- |
| `make <command>`        | Unix/macOS (delegates to task.py) |
| `uv run task <command>` | Direct taskipy usage (fallback)   |

## Code Standards

### Code Quality

We maintain high code quality standards:

- **Type hints** for all functions and methods
- **Comprehensive tests** with >90% coverage
- **Documentation** for all public APIs
- **Security** considerations for all network operations
- **Cross-platform** compatibility (Windows, macOS, Linux)

### Code Style

- **Formatter**: [Ruff](https://docs.astral.sh/ruff/) (automatically applied)
- **Linter**: [Ruff](https://docs.astral.sh/ruff/) with strict settings
- **Type Checker**: [mypy](https://mypy.readthedocs.io/) with strict mode
- **Import Sorting**: Handled by Ruff

### Pre-commit Hooks

Pre-commit hooks automatically run on every commit to ensure code quality:

```bash
# Install hooks (done automatically by dev-setup)
uv run task install-hooks

# Run hooks manually
pre-commit run --all-files
```

## Testing

### Test Structure

```text
tests/
├── test_server.py           # MCP server tests
├── test_gopher_client.py    # Gopher client tests
├── test_integration.py      # Integration tests
└── conftest.py              # Pytest configuration
```

### Running Tests

```bash
# Run all tests
uv run task test

# Run with coverage report
uv run task test-cov

# Run specific test file
uv run pytest tests/test_server.py

# Run tests in watch mode during development
uv run pytest --watch
```

### Writing Tests

- Use **pytest** for all tests
- Include **type hints** in test functions
- Use **descriptive test names** that explain what is being tested
- Include **docstrings** for complex test scenarios
- Mock external dependencies (network calls, file system)

Example test structure:

```python
import pytest
from gopher_mcp.server import GopherMCPServer

def test_server_initialization():
    """Test that the server initializes with default configuration."""
    server = GopherMCPServer()
    assert server.max_response_size == 1048576
    assert server.timeout_seconds == 30

@pytest.mark.asyncio
async def test_gopher_fetch_menu():
    """Test fetching a Gopher menu returns structured data."""
    # Test implementation here
    pass
```

## Documentation

### Documentation Standards

- **Docstrings** for all public functions, classes, and modules
- **Type hints** for all function parameters and return values
- **Examples** in docstrings for complex functions
- **README updates** for new features or configuration options

### Documentation Format

We use Google-style docstrings:

```python
def fetch_gopher_resource(url: str, timeout: int = 30) -> GopherResult:
    """Fetch a resource from a Gopher server.

    Args:
        url: The Gopher URL to fetch
        timeout: Request timeout in seconds

    Returns:
        A GopherResult containing the fetched data

    Raises:
        GopherError: If the request fails or times out

    Example:
        >>> result = fetch_gopher_resource("gopher://example.com/1/")
        >>> print(result.content)
    """
```

### Building Documentation

```bash
# Serve documentation locally
uv run task docs-serve

# Build documentation
uv run task docs-build
```

## Security Considerations

### Security Guidelines

- **Input validation** for all user-provided data
- **Timeout limits** for all network operations
- **Size limits** for response data
- **URL validation** to prevent malicious requests
- **Error handling** that doesn't leak sensitive information

### Security Testing

- Include security-focused tests
- Use `bandit` for security linting (runs automatically)
- Use `safety` for dependency vulnerability checking

## Bug Reports

### Before Submitting a Bug Report

1. **Search existing issues** to avoid duplicates
2. **Test with the latest version** from the main branch
3. **Gather relevant information** (OS, Python version, error messages)

### Bug Report Template

```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:

1. Configure server with '...'
2. Send request to '...'
3. See error

**Expected behavior**
What you expected to happen.

**Environment:**

- OS: [e.g., Windows 11, macOS 14, Ubuntu 22.04]
- Python version: [e.g., 3.11.5]
- Package version: [e.g., 1.0.0]

**Additional context**
Any other context about the problem.
```

## Feature Requests

### Feature Request Guidelines

- **Clear use case** - Explain why this feature would be valuable
- **Detailed description** - Provide specific implementation ideas
- **Backward compatibility** - Consider impact on existing users
- **Security implications** - Consider any security aspects

## Pull Request Process

### Before Submitting a Pull Request

1. **Create an issue** to discuss major changes
2. **Write tests** for new functionality
3. **Update documentation** as needed
4. **Run quality checks**: `uv run task quality`
5. **Test cross-platform** if possible

### Pull Request Template

```markdown
**Description**
Brief description of changes.

**Type of change**

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

**Testing**

- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Manual testing completed

**Checklist**

- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new security vulnerabilities introduced
```

### Review Process

1. **Automated checks** must pass (CI/CD pipeline)
2. **Code review** by maintainers
3. **Testing** on multiple platforms if needed
4. **Documentation review** for user-facing changes

## Release Process

### Versioning

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** version for incompatible API changes
- **MINOR** version for backward-compatible functionality additions
- **PATCH** version for backward-compatible bug fixes

### Release Checklist

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create release PR
4. Tag release after merge
5. Publish to PyPI (automated)

## Community Guidelines

### Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Maintain a welcoming environment

### Communication

- **GitHub Issues** - Bug reports and feature requests
- **GitHub Discussions** - General questions and ideas
- **Pull Requests** - Code contributions and reviews

## Getting Help

- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)
- **Issues**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/cameronrye/gopher-mcp/discussions)

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
