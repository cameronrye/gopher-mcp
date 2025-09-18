#!/usr/bin/env python3
"""
Release preparation script for Gopher & Gemini MCP Server.

This script performs pre-release checks and preparations:
- Validates configuration
- Runs comprehensive tests
- Checks code quality
- Validates documentation
- Prepares release artifacts
- Manages version updates
- Creates git tags
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


class ReleasePreparation:
    """Handles release preparation tasks."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def _get_current_version(self) -> str:
        """Get the current version from pyproject.toml."""
        pyproject_path = self.project_root / "pyproject.toml"
        if not pyproject_path.exists():
            raise FileNotFoundError("pyproject.toml not found!")

        content = pyproject_path.read_text()
        match = re.search(r'version = "([^"]+)"', content)
        if not match:
            raise ValueError("Version not found in pyproject.toml!")

        return match.group(1)

    def _validate_version_format(self, version: str) -> bool:
        """Validate version format (semantic versioning)."""
        pattern = r"^(\d+)\.(\d+)\.(\d+)(?:-([\w\.-]+))?(?:\+([\w\.-]+))?$"
        return bool(re.match(pattern, version))

    def _update_version(self, new_version: str) -> None:
        """Update version in pyproject.toml."""
        pyproject_path = self.project_root / "pyproject.toml"
        content = pyproject_path.read_text()

        # Update version
        content = re.sub(r'version = "[^"]+"', f'version = "{new_version}"', content)

        pyproject_path.write_text(content)
        print(f"✅ Updated version to {new_version} in pyproject.toml")

    def _update_changelog(self, version: str) -> None:
        """Update CHANGELOG.md with new version."""
        changelog_path = self.project_root / "CHANGELOG.md"
        if not changelog_path.exists():
            self.warnings.append("CHANGELOG.md not found!")
            return

        content = changelog_path.read_text()

        # Check if version already exists
        if f"## [{version}]" in content:
            print(f"ℹ️ Version {version} already exists in CHANGELOG.md")
            return

        # Find the unreleased section
        unreleased_pattern = r"## \[Unreleased\].*?\n(.*?)(?=\n## \[|\n\[unreleased\]|\Z)"
        match = re.search(unreleased_pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            unreleased_content = match.group(1).strip()
            if unreleased_content:
                # Add new version section
                import datetime
                today = datetime.date.today().strftime("%Y-%m-%d")
                new_section = f"\n## [{version}] - {today}\n\n{unreleased_content}\n"

                # Replace unreleased section
                content = re.sub(
                    r"(## \[Unreleased\].*?\n).*?(?=\n## \[|\n\[unreleased\]|\Z)",
                    r"\1\n" + new_section,
                    content,
                    flags=re.DOTALL | re.IGNORECASE
                )

                changelog_path.write_text(content)
                print(f"✅ Updated CHANGELOG.md with version {version}")
            else:
                self.warnings.append("No unreleased changes found in CHANGELOG.md")
        else:
            self.warnings.append("Could not find unreleased section in CHANGELOG.md")

    def _create_git_tag(self, version: str, message: Optional[str] = None) -> None:
        """Create and push git tag."""
        tag_name = f"v{version}"

        # Check if tag already exists
        result = subprocess.run(
            ["git", "tag", "-l", tag_name],
            capture_output=True, text=True, cwd=self.project_root
        )
        if result.stdout.strip():
            print(f"❌ Tag {tag_name} already exists!")
            return

        # Create tag
        cmd = ["git", "tag", "-a", tag_name]
        if message:
            cmd.extend(["-m", message])
        else:
            cmd.extend(["-m", f"Release {version}"])

        result = subprocess.run(cmd, cwd=self.project_root)
        if result.returncode == 0:
            print(f"✅ Created tag {tag_name}")

            # Ask if user wants to push
            response = input(f"Push tag {tag_name} to origin? (y/N): ")
            if response.lower() == 'y':
                push_result = subprocess.run(
                    ["git", "push", "origin", tag_name],
                    cwd=self.project_root
                )
                if push_result.returncode == 0:
                    print(f"✅ Pushed tag {tag_name} to origin")
                else:
                    print(f"❌ Failed to push tag {tag_name}")
        else:
            print(f"❌ Failed to create tag {tag_name}")

    def prepare_release(self, skip_tests: bool = False) -> bool:
        """Run all release preparation steps."""
        print("🚀 Preparing Gopher & Gemini MCP Server Release")
        print("=" * 60)
        print()

        steps = [
            ("🔍 Validating Configuration", self._validate_configuration),
        ]

        if not skip_tests:
            steps.extend([
                ("🧪 Running Tests", self._run_tests),
                ("📝 Checking Code Quality", self._check_code_quality),
                ("🔐 Security Scan", self._security_scan),
            ])

        steps.extend([
            ("📚 Validating Documentation", self._validate_documentation),
            ("🔧 Checking Dependencies", self._check_dependencies),
            ("📦 Building Package", self._build_package),
        ])

        for step_name, step_func in steps:
            print(f"{step_name}...")
            success = step_func()
            if success:
                print(f"✅ {step_name} - PASSED")
            else:
                print(f"❌ {step_name} - FAILED")
            print()

        self._report_results()
        return len(self.errors) == 0

    def _validate_configuration(self) -> bool:
        """Validate configuration settings."""
        try:
            result = subprocess.run(
                [sys.executable, "scripts/validate-config.py"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception as e:
            self.errors.append(f"Configuration validation failed: {e}")
            return False

    def _run_tests(self) -> bool:
        """Run comprehensive test suite."""
        try:
            # Run all tests with coverage
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/",
                    "-v",
                    "--cov=src/gopher_mcp",
                    "--cov-fail-under=50",
                ],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                self.errors.append("Test suite failed")
                return False

            # Check for specific test categories
            test_results = []

            # Unit tests
            unit_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/",
                    "-v",
                    "-m",
                    "not integration and not slow",
                ],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            test_results.append(("Unit tests", unit_result.returncode == 0))

            # Integration tests (if any)
            integration_result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v", "-m", "integration"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            test_results.append(
                ("Integration tests", integration_result.returncode == 0)
            )

            # Report test results
            for test_type, passed in test_results:
                if not passed:
                    self.warnings.append(f"{test_type} had failures")

            return True

        except Exception as e:
            self.errors.append(f"Test execution failed: {e}")
            return False

    def _check_code_quality(self) -> bool:
        """Check code quality with linting and formatting."""
        try:
            # Run ruff linting
            lint_result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "src/", "tests/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Run ruff formatting check
            format_result = subprocess.run(
                [sys.executable, "-m", "ruff", "format", "--check", "src/", "tests/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Run mypy type checking
            mypy_result = subprocess.run(
                [sys.executable, "-m", "mypy", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            success = True
            if lint_result.returncode != 0:
                self.errors.append("Linting issues found")
                success = False

            if format_result.returncode != 0:
                self.errors.append("Code formatting issues found")
                success = False

            if mypy_result.returncode != 0:
                self.warnings.append("Type checking issues found")

            return success

        except Exception as e:
            self.errors.append(f"Code quality check failed: {e}")
            return False

    def _validate_documentation(self) -> bool:
        """Validate documentation files."""
        try:
            required_docs = [
                "README.md",
                "docs/gemini-support.md",
                "docs/api-reference.md",
                "docs/ai-assistant-guide.md",
                "config/example.env",
            ]

            missing_docs = []
            for doc in required_docs:
                if not (self.project_root / doc).exists():
                    missing_docs.append(doc)

            if missing_docs:
                self.errors.append(
                    f"Missing documentation files: {', '.join(missing_docs)}"
                )
                return False

            # Check README for basic content
            readme_path = self.project_root / "README.md"
            readme_content = readme_path.read_text()

            required_sections = [
                "Gopher & Gemini MCP Server",
                "gopher_fetch",
                "gemini_fetch",
                "Configuration",
                "Installation",
            ]

            missing_sections = []
            for section in required_sections:
                if section not in readme_content:
                    missing_sections.append(section)

            if missing_sections:
                self.warnings.append(
                    f"README missing sections: {', '.join(missing_sections)}"
                )

            return True

        except Exception as e:
            self.errors.append(f"Documentation validation failed: {e}")
            return False

    def _check_dependencies(self) -> bool:
        """Check dependency status and security."""
        try:
            # Check for outdated dependencies
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--outdated"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            if result.stdout.strip():
                self.warnings.append("Some dependencies may be outdated")

            # Check pyproject.toml for version consistency
            pyproject_path = self.project_root / "pyproject.toml"
            if pyproject_path.exists():
                content = pyproject_path.read_text()
                if "version = " in content:
                    # Extract version
                    for line in content.split("\n"):
                        if line.strip().startswith("version = "):
                            version = line.split("=")[1].strip().strip("\"'")
                            print(f"📋 Package version: {version}")
                            break

            return True

        except Exception as e:
            self.warnings.append(f"Dependency check failed: {e}")
            return True  # Non-critical

    def _build_package(self) -> bool:
        """Build the package to verify it can be built."""
        try:
            # Clean previous builds
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "build"],
                cwd=self.project_root,
                capture_output=True,
            )

            # Build package
            result = subprocess.run(
                [sys.executable, "-m", "build"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                self.errors.append("Package build failed")
                return False

            # Check if build artifacts exist
            dist_dir = self.project_root / "dist"
            if not dist_dir.exists() or not list(dist_dir.glob("*.whl")):
                self.errors.append("Build artifacts not found")
                return False

            return True

        except Exception as e:
            self.errors.append(f"Package build failed: {e}")
            return False

    def _security_scan(self) -> bool:
        """Run security scans."""
        try:
            # Try to run bandit security scan
            result = subprocess.run(
                [sys.executable, "-m", "bandit", "-r", "src/", "-f", "json"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Bandit returns non-zero for issues, but we'll treat as warnings
            if result.returncode != 0:
                self.warnings.append("Security scan found potential issues")

            return True

        except FileNotFoundError:
            self.warnings.append("Bandit not installed, skipping security scan")
            return True
        except Exception as e:
            self.warnings.append(f"Security scan failed: {e}")
            return True  # Non-critical

    def _report_results(self):
        """Report final results."""
        print("=" * 60)
        print("📊 RELEASE PREPARATION RESULTS")
        print("=" * 60)

        if self.errors:
            print(f"❌ {len(self.errors)} ERROR(S) FOUND:")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")
            print()

        if self.warnings:
            print(f"⚠️  {len(self.warnings)} WARNING(S) FOUND:")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")
            print()

        if not self.errors and not self.warnings:
            print("✅ Release preparation completed successfully!")
            print("🎉 Ready for release!")
        elif not self.errors:
            print("✅ Release preparation completed with warnings")
            print("⚠️  Review warnings before proceeding with release")
        else:
            print("❌ Release preparation failed")
            print("🔧 Fix errors before attempting release")

        print()
        print("📋 Next steps:")
        if not self.errors:
            print("  1. Review any warnings above")
            print("  2. Update CHANGELOG.md with release notes")
            print("  3. Create and push git tag")
            print("  4. Upload to PyPI (if applicable)")
            print("  5. Create GitHub release")
        else:
            print("  1. Fix all errors listed above")
            print("  2. Re-run release preparation")
            print("  3. Proceed with release when all checks pass")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Prepare a new release")
    parser.add_argument("--version", help="New version number (e.g., 1.0.0)")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests")
    parser.add_argument("--skip-tag", action="store_true", help="Skip creating git tag")
    parser.add_argument("--tag-message", "-m", help="Tag message")

    args = parser.parse_args()

    prep = ReleasePreparation()

    # Handle version update if specified
    if args.version:
        if not prep._validate_version_format(args.version):
            print(f"❌ Invalid version format: {args.version}")
            print("Expected format: X.Y.Z or X.Y.Z-suffix")
            sys.exit(1)

        current_version = prep._get_current_version()
        print(f"Current version: {current_version}")
        print(f"New version: {args.version}")

        response = input("Update version? (y/N): ")
        if response.lower() == 'y':
            prep._update_version(args.version)
            prep._update_changelog(args.version)

    # Run release preparation
    success = prep.prepare_release(skip_tests=args.skip_tests)

    # Create git tag if requested and successful
    if success and args.version and not args.skip_tag:
        response = input(f"Create git tag v{args.version}? (y/N): ")
        if response.lower() == 'y':
            prep._create_git_tag(args.version, args.tag_message)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
