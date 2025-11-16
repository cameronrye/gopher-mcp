# Contributing Guide

Thank you for your interest in contributing to the Gopher & Gemini MCP Server! This guide will help you get started.

## Quick Start

1. **Fork** the repository on GitHub
2. **Clone** your fork locally
3. **Set up** the development environment
4. **Create** a feature branch
5. **Make** your changes
6. **Test** your changes
7. **Submit** a pull request

## Development Setup

### Prerequisites

- **Python 3.11+** - [Download here](https://www.python.org/downloads/)
- **uv package manager** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Git** - [Install Git](https://git-scm.com/downloads)

### Setup Steps

```bash
# Clone your fork
git clone https://github.com/your-username/gopher-mcp.git
cd gopher-mcp

# Set up development environment
uv run task dev-setup

# Verify setup
uv run task quality
```

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. Make Your Changes

- Write clean, well-documented code
- Follow the project's code style
- Add tests for new functionality
- Update documentation as needed

### 3. Run Quality Checks

```bash
# Run all quality checks
uv run task quality

# Or run individually
uv run task lint      # Linting
uv run task format    # Code formatting
uv run task typecheck # Type checking
uv run task test      # Tests
```

### 4. Commit Your Changes

```bash
git add .
git commit -m "Add amazing feature"
```

### 5. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 6. Submit a Pull Request

- Go to the original repository on GitHub
- Click "New Pull Request"
- Select your feature branch
- Fill out the PR template
- Submit the PR

## Code Standards

### Code Quality

- **Type hints** for all functions and methods
- **Comprehensive tests** with >90% coverage
- **Documentation** for all public APIs
- **Security** considerations for all network operations
- **Cross-platform** compatibility (Windows, macOS, Linux)

### Code Style

- **Formatter**: [Ruff](https://docs.astral.sh/ruff/)
- **Linter**: [Ruff](https://docs.astral.sh/ruff/) with strict settings
- **Type Checker**: [mypy](https://mypy.readthedocs.io/) with strict mode

### Documentation

Use Google-style docstrings:

```python
def fetch_resource(url: str, timeout: int = 30) -> Result:
    """Fetch a resource from a server.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds

    Returns:
        A Result containing the fetched data

    Raises:
        FetchError: If the request fails or times out
    """
```

## Testing

### Running Tests

```bash
# Run all tests
uv run task test

# Run with coverage
uv run task test-cov

# Run specific test file
uv run pytest tests/test_server.py

# Run in watch mode
uv run pytest --watch
```

### Writing Tests

- Use **pytest** for all tests
- Include **type hints** in test functions
- Use **descriptive test names**
- Mock external dependencies

Example:

```python
import pytest

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

## Pull Request Guidelines

### Before Submitting

- [ ] Create an issue to discuss major changes
- [ ] Write tests for new functionality
- [ ] Update documentation as needed
- [ ] Run quality checks: `uv run task quality`
- [ ] Test cross-platform if possible

### PR Template

```markdown
**Description**
Brief description of changes.

**Type of change**

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

**Testing**

- [ ] Tests pass locally
- [ ] New tests added
- [ ] Manual testing completed

**Checklist**

- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new security vulnerabilities
```

## Community Guidelines

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Maintain a welcoming environment

## Getting Help

- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)
- **Issues**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/cameronrye/gopher-mcp/discussions)

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
