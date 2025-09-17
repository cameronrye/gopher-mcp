#!/bin/bash
# Development environment setup script for gopher-mcp
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Main setup function
main() {
    log_info "Setting up gopher-mcp development environment..."

    # Check Python version
    if ! command_exists python3; then
        log_error "Python 3 is not installed. Please install Python 3.11 or later."
        exit 1
    fi

    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python $python_version"

    if [[ $(echo "$python_version 3.11" | awk '{print ($1 >= $2)}') -eq 0 ]]; then
        log_error "Python 3.11 or later is required. Found Python $python_version"
        exit 1
    fi

    # Install uv if not present
    if ! command_exists uv; then
        log_info "Installing uv package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
        log_success "uv installed successfully"
    else
        log_info "uv is already installed"
    fi

    # Install dependencies
    log_info "Installing project dependencies..."
    uv sync --all-extras
    log_success "Dependencies installed"

    # Install pre-commit hooks
    log_info "Installing pre-commit hooks..."
    uv run pre-commit install
    uv run pre-commit install --hook-type commit-msg
    log_success "Pre-commit hooks installed"

    # Skip secrets baseline creation (detect-secrets not installed)
    # This can be enabled later if needed

    # Run initial checks
    log_info "Running initial code quality checks..."

    # Format code
    log_info "Formatting code with ruff..."
    uv run ruff format .

    # Lint code
    log_info "Linting code with ruff..."
    uv run ruff check . --fix

    # Type check
    log_info "Type checking with mypy..."
    if [[ -d src ]]; then
        uv run mypy src || log_warning "Type checking found issues (this is normal for initial setup)"
    fi

    # Run tests if they exist
    if [[ -d tests ]] && [[ -n "$(find tests -name "*.py" -type f)" ]]; then
        log_info "Running tests..."
        uv run pytest || log_warning "Some tests failed (this is normal for initial setup)"
    else
        log_info "No tests found yet"
    fi

    # Setup VS Code configuration if .vscode doesn't exist
    if [[ ! -d .vscode ]]; then
        log_info "Creating VS Code configuration..."
        mkdir -p .vscode

        # Create settings.json
        cat > .vscode/settings.json << 'EOF'
{
    "python.defaultInterpreterPath": "./.venv/bin/python",
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.formatting.provider": "none",
    "python.linting.mypyEnabled": true,
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests"],
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": true,
        "source.fixAll": true
    },
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        ".mypy_cache": true,
        ".pytest_cache": true,
        ".ruff_cache": true,
        "htmlcov": true,
        ".coverage": true
    }
}
EOF

        # Create extensions.json
        cat > .vscode/extensions.json << 'EOF'
{
    "recommendations": [
        "ms-python.python",
        "ms-python.mypy-type-checker",
        "charliermarsh.ruff",
        "ms-python.pytest",
        "ms-vscode.vscode-json",
        "redhat.vscode-yaml",
        "yzhang.markdown-all-in-one",
        "davidanson.vscode-markdownlint"
    ]
}
EOF
        log_success "VS Code configuration created"
    fi

    # Print success message and next steps
    echo
    log_success "Development environment setup complete!"
    echo
    log_info "Next steps:"
    echo "  1. Activate the virtual environment: source .venv/bin/activate"
    echo "  2. Run tests: uv run pytest"
    echo "  3. Start developing: code ."
    echo "  4. Build docs: uv run mkdocs serve"
    echo
    log_info "Available commands:"
    echo "  uv run pytest                 # Run tests"
    echo "  uv run ruff check .           # Lint code"
    echo "  uv run ruff format .          # Format code"
    echo "  uv run mypy src               # Type check"
    echo "  uv run pre-commit run --all   # Run all pre-commit hooks"
    echo "  uv run mkdocs serve           # Serve documentation"
    echo
}

# Run main function
main "$@"
