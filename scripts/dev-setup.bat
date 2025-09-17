@echo off
REM Development environment setup script for gopher-mcp (Windows)
setlocal enabledelayedexpansion

REM Colors for output (using echo with color codes)
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "NC=[0m"

REM Logging functions
:log_info
echo %BLUE%[INFO]%NC% %~1
goto :eof

:log_success
echo %GREEN%[SUCCESS]%NC% %~1
goto :eof

:log_warning
echo %YELLOW%[WARNING]%NC% %~1
goto :eof

:log_error
echo %RED%[ERROR]%NC% %~1
goto :eof

REM Check if command exists
:command_exists
where %1 >nul 2>&1
goto :eof

REM Main setup function
:main
call :log_info "Setting up gopher-mcp development environment..."

REM Check Python version
call :command_exists python
if errorlevel 1 (
    call :log_error "Python is not installed. Please install Python 3.11 or later."
    exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set python_version=%%i
call :log_info "Found Python !python_version!"

REM Simple version check (assumes 3.11+ format)
if "!python_version!" LSS "3.11" (
    call :log_error "Python 3.11 or later is required. Found Python !python_version!"
    exit /b 1
)

REM Install uv if not present
call :command_exists uv
if errorlevel 1 (
    call :log_info "Installing uv package manager..."
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    call :log_success "uv installed successfully"
) else (
    call :log_info "uv is already installed"
)

REM Install dependencies
call :log_info "Installing project dependencies..."
uv sync --all-extras
if errorlevel 1 (
    call :log_error "Failed to install dependencies"
    exit /b 1
)
call :log_success "Dependencies installed"

REM Install pre-commit hooks
call :log_info "Installing pre-commit hooks..."
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
call :log_success "Pre-commit hooks installed"

REM Run initial checks
call :log_info "Running initial code quality checks..."

REM Format code
call :log_info "Formatting code with ruff..."
uv run ruff format .

REM Lint code
call :log_info "Linting code with ruff..."
uv run ruff check . --fix

REM Type check
call :log_info "Type checking with mypy..."
if exist src (
    uv run mypy src || call :log_warning "Type checking found issues (this is normal for initial setup)"
)

REM Run tests if they exist
if exist tests (
    call :log_info "Running tests..."
    uv run pytest || call :log_warning "Some tests failed (this is normal for initial setup)"
) else (
    call :log_info "No tests found yet"
)

REM Setup VS Code configuration if .vscode doesn't exist
if not exist .vscode (
    call :log_info "Creating VS Code configuration..."
    mkdir .vscode

    REM Create settings.json
    (
        echo {
        echo     "python.defaultInterpreterPath": "./.venv/Scripts/python.exe",
        echo     "python.linting.enabled": true,
        echo     "python.linting.ruffEnabled": true,
        echo     "python.formatting.provider": "none",
        echo     "python.linting.mypyEnabled": true,
        echo     "python.testing.pytestEnabled": true,
        echo     "python.testing.pytestArgs": ["tests"],
        echo     "editor.formatOnSave": true,
        echo     "editor.codeActionsOnSave": {
        echo         "source.organizeImports": true,
        echo         "source.fixAll": true
        echo     },
        echo     "files.exclude": {
        echo         "**/__pycache__": true,
        echo         "**/*.pyc": true,
        echo         ".mypy_cache": true,
        echo         ".pytest_cache": true,
        echo         ".ruff_cache": true,
        echo         "htmlcov": true,
        echo         ".coverage": true
        echo     }
        echo }
    ) > .vscode\settings.json

    REM Create extensions.json
    (
        echo {
        echo     "recommendations": [
        echo         "ms-python.python",
        echo         "ms-python.mypy-type-checker",
        echo         "charliermarsh.ruff",
        echo         "ms-python.pytest",
        echo         "ms-vscode.vscode-json",
        echo         "redhat.vscode-yaml",
        echo         "yzhang.markdown-all-in-one",
        echo         "davidanson.vscode-markdownlint"
        echo     ]
        echo }
    ) > .vscode\extensions.json
    call :log_success "VS Code configuration created"
)

REM Print success message and next steps
echo.
call :log_success "Development environment setup complete!"
echo.
call :log_info "Next steps:"
echo   1. Activate the virtual environment: .venv\Scripts\activate
echo   2. Run tests: uv run pytest
echo   3. Start developing: code .
echo   4. Build docs: uv run mkdocs serve
echo.
call :log_info "Available commands:"
echo   uv run pytest                 # Run tests
echo   uv run ruff check .           # Lint code
echo   uv run ruff format .          # Format code
echo   uv run mypy src               # Type check
echo   uv run pre-commit run --all   # Run all pre-commit hooks
echo   uv run mkdocs serve           # Serve documentation
echo.

goto :eof

REM Run main function
call :main %*
