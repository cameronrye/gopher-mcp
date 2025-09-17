@echo off
REM Cross-platform task runner for Windows
REM Usage: task.bat <command>

if "%1"=="" goto help
if "%1"=="help" goto help

REM Run the task using uv
uv run task %*
goto end

:help
echo Gopher MCP Development Commands
echo ===============================
echo.
echo Setup:
echo   dev-setup      Set up development environment
echo   install-hooks  Install pre-commit hooks
echo.
echo Code Quality:
echo   lint          Run ruff linting
echo   format        Format code with ruff
echo   typecheck     Run mypy type checking
echo   quality       Run all quality checks
echo   check         Run lint + typecheck
echo.
echo Testing:
echo   test          Run all tests
echo   test-cov      Run tests with coverage
echo   test-unit     Run unit tests only
echo   test-integration  Run integration tests
echo   test-slow     Run slow tests
echo.
echo Server:
echo   serve         Run MCP server (stdio)
echo   serve-http    Run MCP server (HTTP)
echo.
echo Documentation:
echo   docs-serve    Serve docs locally
echo   docs-build    Build documentation
echo.
echo Maintenance:
echo   clean         Clean build artifacts
echo   ci            Run CI pipeline locally
echo.
echo Usage:
echo   task.bat ^<command^>
echo   Example: task.bat test

:end
