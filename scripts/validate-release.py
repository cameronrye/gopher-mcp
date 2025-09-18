#!/usr/bin/env python3
"""
Release validation script for Gopher & Gemini MCP Server.

This script automates the validation process before releasing a new version.
It checks code quality, tests, security, and functionality.
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple


class ReleaseValidator:
    """Validates release readiness."""

    def __init__(self) -> None:
        self.project_root = Path(__file__).parent.parent
        self.passed_checks: List[str] = []
        self.failed_checks: List[str] = []

    def run_command(self, command: str, description: str) -> Tuple[bool, str]:
        """Run a shell command and return success status and output."""
        print(f"🔍 {description}...")
        try:
            # Split command into list for safer execution
            import shlex

            command_list = shlex.split(command)
            result = subprocess.run(
                command_list,
                shell=False,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode == 0:
                print(f"✅ {description} - PASSED")
                self.passed_checks.append(description)
                return True, result.stdout
            else:
                print(f"❌ {description} - FAILED")
                print(f"Error: {result.stderr}")
                self.failed_checks.append(description)
                return False, result.stderr

        except subprocess.TimeoutExpired:
            print(f"⏰ {description} - TIMEOUT")
            self.failed_checks.append(f"{description} (timeout)")
            return False, "Command timed out"
        except Exception as e:
            print(f"💥 {description} - ERROR: {e}")
            self.failed_checks.append(f"{description} (error)")
            return False, str(e)

    def validate_tests(self) -> bool:
        """Validate test suite."""
        print("\n📋 TESTING VALIDATION")
        print("=" * 50)

        # Run test suite
        success, _ = self.run_command(
            "python -m pytest tests/ -v --tb=short", "Test suite execution"
        )

        # Check test coverage
        coverage_success, coverage_output = self.run_command(
            "python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=80",
            "Test coverage check",
        )

        return success and coverage_success

    def validate_code_quality(self) -> bool:
        """Validate code quality."""
        print("\n🔧 CODE QUALITY VALIDATION")
        print("=" * 50)

        # Linting
        lint_success, _ = self.run_command("uv run ruff check .", "Ruff linting")

        # Formatting
        format_success, _ = self.run_command(
            "uv run ruff format --check .", "Ruff formatting check"
        )

        # Type checking
        type_success, _ = self.run_command("uv run mypy src", "MyPy type checking")

        return lint_success and format_success and type_success

    def validate_security(self) -> bool:
        """Validate security."""
        print("\n🔒 SECURITY VALIDATION")
        print("=" * 50)

        # Security linting
        bandit_success, _ = self.run_command(
            "uv run bandit -r src/ -f json", "Bandit security check"
        )

        # Dependency security
        safety_success, _ = self.run_command(
            "uv run safety check --json", "Safety dependency check"
        )

        return bandit_success and safety_success

    def validate_build(self) -> bool:
        """Validate package build."""
        print("\n📦 BUILD VALIDATION")
        print("=" * 50)

        # Clean previous builds
        self.run_command("rm -rf dist/", "Clean previous builds")

        # Build package
        build_success, _ = self.run_command("uv build", "Package build")

        # Check build artifacts
        dist_path = self.project_root / "dist"
        if dist_path.exists():
            files = list(dist_path.glob("*"))
            if len(files) >= 2:  # Should have wheel and sdist
                print(f"✅ Build artifacts created: {[f.name for f in files]}")
                return build_success

        print("❌ Build artifacts missing")
        self.failed_checks.append("Build artifacts validation")
        return False

    async def validate_functionality(self) -> bool:
        """Validate core functionality."""
        print("\n⚙️  FUNCTIONALITY VALIDATION")
        print("=" * 50)

        try:
            # Test client creation
            print("🔍 Testing client creation...")
            from src.gopher_mcp.server import get_gopher_client, get_gemini_client

            gopher_client = get_gopher_client()
            gemini_client = get_gemini_client()

            print("✅ Both clients created successfully")

            # Test configuration
            print("🔍 Testing configuration...")
            assert gopher_client.cache_enabled is not None
            assert gemini_client.cache_enabled is not None
            assert gemini_client.tofu_enabled is not None
            assert gemini_client.client_certs_enabled is not None

            print("✅ Configuration validation passed")

            # Cleanup
            await gopher_client.close()
            await gemini_client.close()

            print("✅ Client cleanup successful")
            self.passed_checks.append("Functionality validation")
            return True

        except Exception as e:
            print(f"❌ Functionality validation failed: {e}")
            self.failed_checks.append("Functionality validation")
            return False

    def validate_configuration(self) -> bool:
        """Validate configuration system."""
        print("\n⚙️  CONFIGURATION VALIDATION")
        print("=" * 50)

        # Check if validation script exists and works
        config_script = self.project_root / "scripts" / "validate-config.py"
        if config_script.exists():
            return self.run_command(
                "python scripts/validate-config.py", "Configuration validation script"
            )[0]
        else:
            print("⚠️  Configuration validation script not found")
            return True  # Not critical for release

    def validate_documentation(self) -> bool:
        """Validate documentation."""
        print("\n📚 DOCUMENTATION VALIDATION")
        print("=" * 50)

        # Check if docs build
        docs_success, _ = self.run_command("uv run mkdocs build", "Documentation build")

        # Check key documentation files exist
        required_docs = [
            "README.md",
            "CHANGELOG.md",
            "docs/migration-guide.md",
            "docs/release-checklist.md",
        ]

        missing_docs = []
        for doc in required_docs:
            if not (self.project_root / doc).exists():
                missing_docs.append(doc)

        if missing_docs:
            print(f"❌ Missing documentation files: {missing_docs}")
            self.failed_checks.append("Documentation files check")
            return False

        print("✅ All required documentation files present")
        self.passed_checks.append("Documentation files check")
        return docs_success

    def print_summary(self) -> bool:
        """Print validation summary."""
        print("\n" + "=" * 60)
        print("🎯 RELEASE VALIDATION SUMMARY")
        print("=" * 60)

        print(f"\n✅ PASSED CHECKS ({len(self.passed_checks)}):")
        for check in self.passed_checks:
            print(f"   • {check}")

        if self.failed_checks:
            print(f"\n❌ FAILED CHECKS ({len(self.failed_checks)}):")
            for check in self.failed_checks:
                print(f"   • {check}")

        total_checks = len(self.passed_checks) + len(self.failed_checks)
        success_rate = (
            len(self.passed_checks) / total_checks * 100 if total_checks > 0 else 0
        )

        print(
            f"\n📊 SUCCESS RATE: {success_rate:.1f}% ({len(self.passed_checks)}/{total_checks})"
        )

        if self.failed_checks:
            print("\n🚨 RELEASE NOT READY - Please fix failed checks before releasing")
            return False
        else:
            print("\n🎉 RELEASE READY - All validations passed!")
            return True

    async def run_all_validations(self) -> bool:
        """Run all validation checks."""
        print("🚀 Starting Release Validation")
        print("=" * 60)

        start_time = time.time()

        # Run all validation steps
        validations = [
            ("Code Quality", self.validate_code_quality),
            ("Security", self.validate_security),
            ("Tests", self.validate_tests),
            ("Build", self.validate_build),
            ("Configuration", self.validate_configuration),
            ("Documentation", self.validate_documentation),
            ("Functionality", self.validate_functionality),
        ]

        all_passed = True
        for name, validation_func in validations:
            try:
                if asyncio.iscoroutinefunction(validation_func):
                    result = await validation_func()
                else:
                    result = validation_func()

                if not result:
                    all_passed = False

            except Exception as e:
                print(f"💥 {name} validation failed with exception: {e}")
                self.failed_checks.append(f"{name} (exception)")
                all_passed = False

        end_time = time.time()
        duration = end_time - start_time

        print(f"\n⏱️  Total validation time: {duration:.1f} seconds")

        return self.print_summary() and all_passed


async def main() -> None:
    """Main entry point."""
    validator = ReleaseValidator()

    try:
        success = await validator.run_all_validations()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n💥 Validation failed with unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
