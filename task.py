#!/usr/bin/env python3
"""
Cross-platform task runner for gopher-mcp
Unified replacement for Makefile and task.bat
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


class Colors:
    """ANSI color codes for terminal output."""

    # Basic colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Styles
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Reset
    RESET = "\033[0m"

    @staticmethod
    def is_supported() -> bool:
        """Check if terminal supports colors."""
        # Allow disabling colors via environment variable
        if os.getenv("NO_COLOR") or os.getenv("TASK_NO_COLOR"):
            return False

        # Check if we're in a terminal and not redirected
        if not sys.stdout.isatty():
            return False

        # Windows terminal support
        if platform.system() == "Windows":
            # Enable ANSI colors on Windows 10+
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except Exception:
                return False

        # Unix-like systems usually support colors
        return True


class TaskRunner:
    """Cross-platform task runner using uv and taskipy."""

    def __init__(self) -> None:
        self.system = platform.system().lower()
        self.is_windows = self.system == "windows"
        self.project_root = Path(__file__).parent
        self.colors_enabled = Colors.is_supported()

        # Task definitions - mirrors pyproject.toml [tool.taskipy.tasks]
        self.tasks = {
            # Development setup
            "dev-setup": {
                "cmd": "bash scripts/dev-setup.sh"
                if not self.is_windows
                else "scripts\\dev-setup.bat",
                "desc": "Set up development environment",
                "category": "Setup",
            },
            "install-hooks": {
                "cmd": "pre-commit install",
                "desc": "Install pre-commit hooks",
                "category": "Setup",
            },
            # Code quality
            "lint": {
                "cmd": "ruff check src/ tests/",
                "desc": "Run ruff linting",
                "category": "Code Quality",
            },
            "format": {
                "cmd": "ruff format src/ tests/",
                "desc": "Format code with ruff",
                "category": "Code Quality",
            },
            "typecheck": {
                "cmd": "mypy src/ --ignore-missing-imports",
                "desc": "Run mypy type checking",
                "category": "Code Quality",
            },
            "quality": {
                "cmd": "uv run task lint && uv run task typecheck && uv run task test",
                "desc": "Run all quality checks",
                "category": "Code Quality",
            },
            "check": {
                "cmd": "uv run task lint && uv run task typecheck",
                "desc": "Run lint + typecheck",
                "category": "Code Quality",
            },
            # Testing
            "test": {
                "cmd": "pytest tests/ -v",
                "desc": "Run all tests",
                "category": "Testing",
            },
            "test-cov": {
                "cmd": "pytest tests/ -v --cov=src/gopher_mcp --cov-report=term-missing --cov-report=html",
                "desc": "Run tests with coverage",
                "category": "Testing",
            },
            "test-unit": {
                "cmd": "pytest tests/ -v -m 'not integration and not slow'",
                "desc": "Run unit tests only",
                "category": "Testing",
            },
            "test-integration": {
                "cmd": "pytest tests/ -v -m integration",
                "desc": "Run integration tests",
                "category": "Testing",
            },
            "test-slow": {
                "cmd": "pytest tests/ -v -m slow",
                "desc": "Run slow tests",
                "category": "Testing",
            },
            # Server operations
            "serve": {
                "cmd": "python -m gopher_mcp",
                "desc": "Run MCP server (stdio)",
                "category": "Server",
            },
            "serve-http": {
                "cmd": "python -m gopher_mcp.http_server",
                "desc": "Run MCP server (HTTP)",
                "category": "Server",
            },
            # Documentation
            "docs-serve": {
                "cmd": "mkdocs serve",
                "desc": "Serve docs locally",
                "category": "Documentation",
            },
            "docs-build": {
                "cmd": "mkdocs build",
                "desc": "Build documentation",
                "category": "Documentation",
            },
            # Maintenance
            "clean": {
                "cmd": self._get_clean_command(),
                "desc": "Clean build artifacts",
                "category": "Maintenance",
            },
            "ci": {
                "cmd": "uv run task check && uv run task test-cov",
                "desc": "Run CI pipeline locally",
                "category": "Maintenance",
            },
        }

    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are supported."""
        if self.colors_enabled:
            return f"{color}{text}{Colors.RESET}"
        return text

    def _get_clean_command(self) -> str:
        """Get platform-specific clean command."""
        if self.is_windows:
            return (
                "if exist .pytest_cache rmdir /s /q .pytest_cache && "
                "if exist .coverage del .coverage && "
                "if exist htmlcov rmdir /s /q htmlcov && "
                "if exist dist rmdir /s /q dist && "
                "if exist build rmdir /s /q build && "
                'for /d %%i in (*.egg-info) do rmdir /s /q "%%i" && '
                "if exist .mypy_cache rmdir /s /q .mypy_cache && "
                "if exist .ruff_cache rmdir /s /q .ruff_cache"
            )
        else:
            return (
                "rm -rf .pytest_cache .coverage htmlcov dist build "
                "*.egg-info .mypy_cache .ruff_cache"
            )

    def run_task(self, task_name: str, extra_args: Optional[List[str]] = None) -> int:
        """Run a specific task."""
        if task_name not in self.tasks:
            error_msg = self._colorize(
                f"❌ Unknown task: {task_name}", Colors.RED + Colors.BOLD
            )
            print(error_msg)
            available_tasks = self._colorize(
                ", ".join(sorted(self.tasks.keys())), Colors.YELLOW
            )
            print(f"Available tasks: {available_tasks}")
            return 1

        task = self.tasks[task_name]
        cmd = task["cmd"]

        # For most tasks, use uv run to ensure proper environment
        if not cmd.startswith(("bash ", "scripts\\", "uv run task")):
            cmd = f"uv run {cmd}"

        # Add extra arguments if provided
        if extra_args:
            cmd += " " + " ".join(extra_args)

        running_msg = self._colorize(
            f"🚀 Running: {task['desc']}", Colors.GREEN + Colors.BOLD
        )
        print(running_msg)
        command_msg = self._colorize(f"📝 Command: {cmd}", Colors.BLUE + Colors.DIM)
        print(command_msg)

        # Change to project root
        os.chdir(self.project_root)

        # Execute command
        if self.is_windows and not cmd.startswith("uv run"):
            # Use cmd for Windows-specific commands
            result = subprocess.run(cmd, shell=True)
        else:
            # Use shell for cross-platform commands
            result = subprocess.run(cmd, shell=True)

        return result.returncode

    def show_help(self) -> None:
        """Display help information."""
        title = self._colorize(
            "Gopher MCP Development Commands", Colors.BOLD + Colors.CYAN
        )
        separator = self._colorize("=" * 31, Colors.CYAN)
        print(title)
        print(separator)
        print()

        # Group tasks by category
        categories: Dict[str, List[tuple[str, str]]] = {}
        for task_name, task_info in self.tasks.items():
            category = task_info["category"]
            if category not in categories:
                categories[category] = []
            categories[category].append((task_name, task_info["desc"]))

        # Display tasks by category
        category_colors = {
            "Setup": Colors.GREEN,
            "Code Quality": Colors.YELLOW,
            "Testing": Colors.BLUE,
            "Server": Colors.MAGENTA,
            "Documentation": Colors.CYAN,
            "Maintenance": Colors.RED,
        }

        for category in [
            "Setup",
            "Code Quality",
            "Testing",
            "Server",
            "Documentation",
            "Maintenance",
        ]:
            if category in categories:
                category_header = self._colorize(
                    f"{category}:",
                    Colors.BOLD + category_colors.get(category, Colors.WHITE),
                )
                print(category_header)
                for task_name, desc in sorted(categories[category]):
                    colored_task = self._colorize(task_name, Colors.BOLD + Colors.WHITE)
                    colored_desc = self._colorize(desc, Colors.DIM)
                    # Use fixed spacing to account for ANSI codes
                    print(
                        f"  {colored_task} {' ' * (16 - len(task_name))} {colored_desc}"
                    )
                print()

        usage_header = self._colorize(
            "Cross-platform usage:", Colors.BOLD + Colors.CYAN
        )
        print(usage_header)
        python_cmd = self._colorize("python task.py <command>", Colors.GREEN)
        print(f"  {python_cmd}")
        example_cmd = self._colorize("python task.py test", Colors.GREEN)
        print(f"  Example: {example_cmd}")
        print()

        alt_header = self._colorize("Alternative options:", Colors.BOLD + Colors.CYAN)
        print(alt_header)
        make_cmd = self._colorize("make <command>", Colors.YELLOW)
        uv_cmd = self._colorize("uv run task <command>", Colors.YELLOW)
        print(f"  Unix/macOS:   {make_cmd}")
        print(f"  Universal:    {uv_cmd}")


def main() -> int:
    """Main entry point."""
    # Handle help case first
    if len(sys.argv) == 1 or (
        len(sys.argv) == 2 and sys.argv[1] in ["help", "-h", "--help"]
    ):
        runner = TaskRunner()
        runner.show_help()
        return 0

    # Parse task name and remaining arguments
    task_name = sys.argv[1]
    extra_args = sys.argv[2:] if len(sys.argv) > 2 else []

    runner = TaskRunner()
    return runner.run_task(task_name, extra_args)


if __name__ == "__main__":
    sys.exit(main())
