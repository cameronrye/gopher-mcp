# Unified Task Runner System

The gopher-mcp project uses a **unified Python-based task runner** that provides a consistent development experience across all platforms (Windows, macOS, Linux).

## Overview

Instead of maintaining separate platform-specific scripts, we now have:

- **`task.py`** - The main Python-based task runner (recommended)
- **`Makefile`** - Traditional make (delegates to task.py)

## Usage

### Recommended (All Platforms)

```bash
python task.py <command>
```

This is the recommended way to run tasks as it provides:

- ✅ Consistent behavior across all platforms
- ✅ Rich output with emojis and colored text
- ✅ Proper error handling and exit codes
- ✅ Automatic fallback to `uv run task` if needed
- ✅ Automatic color detection (disable with `NO_COLOR=1` or `TASK_NO_COLOR=1`)

### Alternative Options

```bash
# Unix/macOS/Linux
make <command>

# Universal fallback
uv run task <command>
```

## Available Commands

Run `python task.py help` to see all available commands, organized by category:

### Setup
- `dev-setup` - Set up development environment
- `install-hooks` - Install pre-commit hooks

### Code Quality
- `lint` - Run ruff linting
- `format` - Format code with ruff
- `typecheck` - Run mypy type checking
- `quality` - Run all quality checks
- `check` - Run lint + typecheck

### Testing
- `test` - Run all tests
- `test-cov` - Run tests with coverage
- `test-unit` - Run unit tests only
- `test-integration` - Run integration tests
- `test-slow` - Run slow tests

### Server
- `serve` - Run MCP server (stdio)
- `serve-http` - Run MCP server (HTTP)

### Documentation
- `docs-serve` - Serve docs locally
- `docs-build` - Build documentation

### Maintenance
- `clean` - Clean build artifacts
- `ci` - Run CI pipeline locally

## Implementation Details

### Task Definitions

All tasks are defined in the `TaskRunner` class in `task.py`, which mirrors the configuration in `pyproject.toml` under `[tool.taskipy.tasks]`.

### Platform-Specific Handling

The task runner automatically handles platform differences:

- **Windows**: Uses Windows-specific clean commands and proper shell execution
- **Unix/Linux/macOS**: Uses Unix-style commands and shell execution
- **Cross-platform**: Most commands use `uv run` for consistency

### Fallback Strategy

The system provides multiple fallback layers:

1. **Primary**: Python task runner (`task.py`)
2. **Secondary**: Direct taskipy via `uv run task`
3. **Legacy**: Platform-specific scripts that delegate to the above

### Error Handling

- Proper exit codes are returned for CI/CD integration
- Clear error messages when tasks fail
- Automatic detection of missing dependencies

## Migration from Legacy Scripts

If you were using the old system:

```bash
# Old way
make test                    # Unix/macOS
uv run task test            # Universal

# New way (recommended)
python task.py test         # All platforms
```

The old commands still work but now delegate to the unified Python runner.

## Benefits

1. **Consistency**: Same behavior across all platforms
2. **Maintainability**: Single source of truth for task definitions
3. **Extensibility**: Easy to add new tasks or modify existing ones
4. **User Experience**: Better output formatting and error messages
5. **Backward Compatibility**: Legacy commands still work

## Adding New Tasks

To add a new task:

1. Add the task definition to the `self.tasks` dictionary in `task.py`
2. Update the corresponding entry in `pyproject.toml` under `[tool.taskipy.tasks]`
3. Test with `python task.py <new-task>`

Example:

```python
"my-task": {
    "cmd": "echo 'Hello World'",
    "desc": "Print hello world",
    "category": "Examples"
},
```
