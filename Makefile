# Cross-platform Makefile for gopher-mcp
# Works on Unix-like systems (macOS, Linux)
# For Windows, use: uv run task <command>

.PHONY: help dev-setup install-hooks lint format typecheck quality test test-cov test-unit test-integration test-slow serve serve-http docs-serve docs-build clean check ci

# Default target
help:
	@echo "Gopher MCP Development Commands"
	@echo "==============================="
	@echo ""
	@echo "Setup:"
	@echo "  dev-setup      Set up development environment"
	@echo "  install-hooks  Install pre-commit hooks"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint          Run ruff linting"
	@echo "  format        Format code with ruff"
	@echo "  typecheck     Run mypy type checking"
	@echo "  quality       Run all quality checks"
	@echo "  check         Run lint + typecheck"
	@echo ""
	@echo "Testing:"
	@echo "  test          Run all tests"
	@echo "  test-cov      Run tests with coverage"
	@echo "  test-unit     Run unit tests only"
	@echo "  test-integration  Run integration tests"
	@echo "  test-slow     Run slow tests"
	@echo ""
	@echo "Server:"
	@echo "  serve         Run MCP server (stdio)"
	@echo "  serve-http    Run MCP server (HTTP)"
	@echo ""
	@echo "Documentation:"
	@echo "  docs-serve    Serve docs locally"
	@echo "  docs-build    Build documentation"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean         Clean build artifacts"
	@echo "  ci            Run CI pipeline locally"
	@echo ""
	@echo "Cross-platform usage:"
	@echo "  Unix/macOS:   make <command>"
	@echo "  Windows:      uv run task <command>"

# Development setup
dev-setup:
	@uv run task dev-setup

install-hooks:
	@uv run task install-hooks

# Code quality
lint:
	@uv run task lint

format:
	@uv run task format

typecheck:
	@uv run task typecheck

quality:
	@uv run task quality

check:
	@uv run task check

# Testing
test:
	@uv run task test

test-cov:
	@uv run task test-cov

test-unit:
	@uv run task test-unit

test-integration:
	@uv run task test-integration

test-slow:
	@uv run task test-slow

# Server operations
serve:
	@uv run task serve

serve-http:
	@uv run task serve-http

# Documentation
docs-serve:
	@uv run task docs-serve

docs-build:
	@uv run task docs-build

# Maintenance
clean:
	@uv run task clean

ci:
	@uv run task ci
