# Contributing to the Gopher & Gemini MCP Server

Thank you for your interest in contributing to the Gopher & Gemini MCP Server! This document provides guidelines and information for contributors.

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

The project uses `uv` for dependency management and a cross-platform task runner:

```bash
# Set up development environment (installs dependencies and pre-commit hooks)
uv run task dev-setup

# Verify setup
uv run task quality
```

### The task runner

Project tasks — linting, tests, docs, the local CI pipeline — run through
[taskipy](https://github.com/taskipy/taskipy), whose task table lives in
`pyproject.toml` under `[tool.taskipy.tasks]`. That table is the single
definition of every task; there is nothing to keep in sync with it.

```bash
uv run task <command>
```

This works identically on Windows, macOS and Linux, and needs nothing installed
beyond `uv` and the project's dependency groups (`uv sync --all-groups`, which
`scripts/dev-setup.sh` / `scripts\dev-setup.bat` runs for you).

On Unix-like systems `make <command>` is a convenience wrapper: the `Makefile`
is a catch-all target that forwards straight to `uv run task <command>`, so the
two are interchangeable. `make` with no target runs the `help` task.

```bash
make test          # identical to: uv run task test
make               # identical to: uv run task help
```

To see the tasks that actually exist, ask the runner rather than this page:

```bash
uv run task help   # an alias for `task --list`
```

The tasks, grouped:

| Group         | Tasks                                                            |
| ------------- | ---------------------------------------------------------------- |
| Setup         | `dev-setup`, `dev-setup-win`, `install-hooks`                    |
| Code quality  | `lint`, `format`, `typecheck`, `check`, `quality`                |
| Testing       | `test`, `test-cov`, `test-unit`, `test-integration`, `test-slow` |
| Server        | `serve`, `serve-http`, `serve-sse`                               |
| Documentation | `docs-serve`, `docs-build`                                       |
| Maintenance   | `clean`, `clean-win`, `ci`, `help`                               |

A few of them are worth explaining:

- `lint` and `format` deliberately cover the whole repository rather than just
  `src/` and `tests/`, because CI runs `ruff check .`; scoping them down would
  hide violations in `scripts/` and other top-level Python that CI still fails
  on.
- `typecheck` matches CI's `mypy src` exactly, without a blanket
  `--ignore-missing-imports` that would let a new untyped import pass locally
  and fail in CI.
- `check` is `lint` then `typecheck`; `quality` is `lint`, `typecheck`, `test`;
  `ci` is `check` then `test-cov` — the local mirror of the CI pipeline.
- `dev-setup-win` and `clean-win` exist because Windows has no `bash` and
  taskipy cannot branch on the platform at runtime, so the platform is in the
  task name.

**Adding a task.** Add one entry under `[tool.taskipy.tasks]` and run it:

```toml
[tool.taskipy.tasks]
my-task = "echo 'Hello World'"
```

```bash
uv run task my-task
make my-task        # picked up automatically; the Makefile has no task list
```

Nothing else needs updating. There is no second copy of the task table: the
project used to ship a `task.py` holding a hand-maintained duplicate that
nothing compared against, and it had already drifted from `pyproject.toml` by
the time it was removed. If you are following an older document that says to run
`python task.py <command>`, the file no longer exists — use
`uv run task <command>`.

## Code Standards

### Code Quality

We maintain high code quality standards:

- **Type hints** for all functions and methods
- **Comprehensive tests** (CI enforces a minimum of 95% coverage)
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
├── test_server.py            # MCP server + tool tests
├── test_gopher_client.py     # Gopher client tests
├── test_gemini_client.py     # Gemini client tests
├── test_gemini_tls.py        # Gemini TLS / TOFU tests
├── test_client_certs.py      # Client certificate tests
├── test_config.py            # Configuration tests
├── test_security.py          # Security / SSRF tests
├── test_mcp_protocol.py      # The MCP wire envelope, over an in-memory session
├── test_integration.py       # Integration tests
├── conftest.py               # Pytest fixtures and configuration
└── ...                       # Additional protocol, model, and util tests
```

### Running Tests

```bash
# Run all tests
uv run task test

# Run with coverage report
uv run task test-cov

# Run specific test file
uv run pytest tests/test_server.py
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
from gopher_mcp.config import GopherConfig


def test_default_configuration():
    """The Gopher config exposes the documented defaults."""
    config = GopherConfig()
    assert config.max_response_size == 1048576
    assert config.timeout_seconds == 30.0


@pytest.mark.asyncio
async def test_gopher_fetch_returns_structured_result():
    """gopher_fetch returns a structured dict for a menu URL."""
    from gopher_mcp.server import gopher_fetch

    result = await gopher_fetch("gopher://gopher.floodgap.com/1/")
    assert isinstance(result, dict)
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
# Serve documentation locally, with live reload
uv run task docs-serve

# Build documentation
uv run task docs-build
```

CI builds the site with `mkdocs build --clean --strict`, so a broken relative
link, a missing anchor or an unresolved mkdocstrings reference fails the build
rather than shipping. Reproduce it before pushing:

```bash
uv run mkdocs build --clean --strict
./scripts/check-docs-render.sh site
```

`--strict` only proves that nothing _warned_, not that anything rendered:
`check-docs-render.sh` asserts the landing page's mermaid diagram came out as a
diagram, which is the regression that shipped as literal `graph TB` text for a
year while every strict build passed.

Two pages are one-line `--8<--` includes rather than second copies:
`docs/contributing.md` includes this file, and `docs/changelog.md` includes
`CHANGELOG.md`. Edit the root file; the page follows. Any further include of a
file outside `docs/` also belongs in the `paths:` filter of
`.github/workflows/docs.yml`, or an edit to it will not redeploy the site.

Three retired pages — `advanced-features.md`, `gemini-configuration.md` and
`task-runner.md` — keep answering through `mkdocs-redirects`, configured under
`plugins.redirects.redirect_maps` in `mkdocs.yml`. Removing or renaming a page
whose URL has been published means adding an entry there in the same change.

## Security Considerations

### Security Guidelines

- **Input validation** for all user-provided data
- **Timeout limits** for all network operations
- **Size limits** for response data
- **URL validation** to prevent malicious requests
- **Error handling** that doesn't leak sensitive information

### Security Testing

- Include security-focused tests
- Use `bandit` for security linting (runs automatically, and fails CI)
- Use `pip-audit` for dependency vulnerability checking. It runs on every PR but
  is **advisory only** — an advisory published against a pinned dependency is
  not a defect in your PR, so it annotates the run instead of failing it. A
  nightly audit workflow files them under the `security-audit` label instead.

## Bug Reports

Open one with the
[Bug Report template](https://github.com/cameronrye/gopher-mcp/issues/new?template=bug_report.yml),
which collects this information as a form. Blank issues are turned off, so the
[new-issue page](https://github.com/cameronrye/gopher-mcp/issues/new/choose)
always starts from a template.

### Before Submitting a Bug Report

1. **Search existing issues** to avoid duplicates
2. **Test with the latest version** from the main branch
3. **Gather relevant information**: your OS, your Python version, the exact
   error `code` and message from the tool result, and the package version —
   `gopher-mcp --version` reports it, and works for the `uvx` and Docker
   installs where importing the package is not an option

## Feature Requests

Open one with the
[Feature Request template](https://github.com/cameronrye/gopher-mcp/issues/new?template=feature_request.yml).
Questions that are not requests belong on the
[Question template](https://github.com/cameronrye/gopher-mcp/issues/new?template=question.yml).

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

1. Update version in `pyproject.toml` and `server.json` (which carries it
   twice), then run `uv lock`. `scripts/prepare-release.py` does all of this,
   and the release workflow fails the tag if the three disagree
2. Update `CHANGELOG.md`
3. Create release PR
4. Tag release after merge
5. Publish to PyPI (automated)

See the [Releasing guide](https://cameronrye.github.io/gopher-mcp/development/releasing/)
for the full process, trusted-publishing setup, and the complete pre-release checklist.

## Community Guidelines

### Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Maintain a welcoming environment

### Communication

- **GitHub Issues** - Bug reports, feature requests and questions, each with
  its own template on the [new-issue page](https://github.com/cameronrye/gopher-mcp/issues/new/choose)
- **Pull Requests** - Code contributions and reviews

## Getting Help

- **Documentation**: [Project Docs](https://cameronrye.github.io/gopher-mcp/)
- **Issues**: [GitHub Issues](https://github.com/cameronrye/gopher-mcp/issues)
- **Questions**: [Open a question issue](https://github.com/cameronrye/gopher-mcp/issues/new?template=question.yml)

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
