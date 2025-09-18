#!/usr/bin/env python3
"""
Setup verification script for open source release.
Checks that all required files and configurations are in place.
"""

import sys
from pathlib import Path
from typing import List


class SetupVerifier:
    """Verifies open source release setup."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.issues: List[str] = []
        self.warnings: List[str] = []

    def verify_setup(self) -> bool:
        """Run all verification checks."""
        print("🔍 Verifying Open Source Release Setup")
        print("=" * 50)
        print()

        checks = [
            ("📁 Required Files", self._check_required_files),
            ("⚙️ GitHub Workflows", self._check_workflows),
            ("📋 Templates", self._check_templates),
            ("📚 Documentation", self._check_documentation),
            ("📦 Package Configuration", self._check_package_config),
            ("🔧 Development Tools", self._check_dev_tools),
        ]

        for check_name, check_func in checks:
            print(f"{check_name}...")
            try:
                check_func()
                print(f"✅ {check_name} - OK")
            except Exception as e:
                self.issues.append(f"{check_name}: {e}")
                print(f"❌ {check_name} - FAILED: {e}")
            print()

        # Summary
        print("📊 Summary")
        print("-" * 20)
        if not self.issues:
            print("✅ All checks passed! Setup is ready for open source release.")
        else:
            print(f"❌ Found {len(self.issues)} issues:")
            for issue in self.issues:
                print(f"  • {issue}")

        if self.warnings:
            print(f"\n⚠️ {len(self.warnings)} warnings:")
            for warning in self.warnings:
                print(f"  • {warning}")

        return len(self.issues) == 0

    def _check_required_files(self) -> None:
        """Check that all required files exist."""
        required_files = [
            "README.md",
            "LICENSE",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CHANGELOG.md",
            "pyproject.toml",
            "mkdocs.yml",
            ".github/CODEOWNERS",
            ".github/dependabot.yml",
        ]

        for file_path in required_files:
            full_path = self.project_root / file_path
            if not full_path.exists():
                raise FileNotFoundError(f"Missing required file: {file_path}")

    def _check_workflows(self) -> None:
        """Check GitHub workflows."""
        workflow_dir = self.project_root / ".github" / "workflows"
        required_workflows = [
            "ci.yml",
            "docs.yml",
            "publish.yml",
            "release.yml",
            "pr-check.yml",
            "validate-pr.yml",
        ]

        for workflow in required_workflows:
            workflow_path = workflow_dir / workflow
            if not workflow_path.exists():
                raise FileNotFoundError(f"Missing workflow: {workflow}")

    def _check_templates(self) -> None:
        """Check issue and PR templates."""
        template_dir = self.project_root / ".github" / "ISSUE_TEMPLATE"
        required_templates = [
            "bug_report.yml",
            "feature_request.yml",
            "question.yml",
            "config.yml",
        ]

        for template in required_templates:
            template_path = template_dir / template
            if not template_path.exists():
                raise FileNotFoundError(f"Missing issue template: {template}")

        # Check PR template
        pr_template = self.project_root / ".github" / "pull_request_template.md"
        if not pr_template.exists():
            raise FileNotFoundError("Missing pull request template")

    def _check_documentation(self) -> None:
        """Check documentation setup."""
        docs_dir = self.project_root / "docs"
        required_docs = [
            "index.md",
            "installation.md",
            "api-reference.md",
            "development/repository-setup.md",
            "development/open-source-release-checklist.md",
        ]

        for doc in required_docs:
            doc_path = docs_dir / doc
            if not doc_path.exists():
                raise FileNotFoundError(f"Missing documentation: {doc}")

        # Check MkDocs config
        mkdocs_config = self.project_root / "mkdocs.yml"
        content = mkdocs_config.read_text()
        if "cameronrye.github.io/gopher-mcp" not in content:
            self.warnings.append(
                "MkDocs site_url may not be configured for GitHub Pages"
            )

    def _check_package_config(self) -> None:
        """Check package configuration."""
        pyproject_path = self.project_root / "pyproject.toml"
        content = pyproject_path.read_text()

        # Check required fields
        required_fields = [
            'name = "gopher-mcp"',
            'license = "MIT"',
            'requires-python = ">=3.11"',
        ]

        for field in required_fields:
            if field not in content:
                raise ValueError(f"Missing required field in pyproject.toml: {field}")

        # Check URLs
        if "cameronrye.github.io/gopher-mcp" not in content:
            self.warnings.append(
                "Documentation URL may not be updated for GitHub Pages"
            )

    def _check_dev_tools(self) -> None:
        """Check development tools configuration."""
        # Check if uv.lock exists
        if not (self.project_root / "uv.lock").exists():
            self.warnings.append("uv.lock not found - run 'uv sync' to generate")

        # Check scripts
        scripts_dir = self.project_root / "scripts"
        required_scripts = [
            "prepare-release.py",
            "verify-setup.py",
        ]

        for script in required_scripts:
            script_path = scripts_dir / script
            if not script_path.exists():
                raise FileNotFoundError(f"Missing script: {script}")


def main():
    """Main entry point."""
    verifier = SetupVerifier()
    success = verifier.verify_setup()

    if success:
        print("\n🎉 Setup verification complete! Ready for open source release.")
        print("\nNext steps:")
        print("1. Configure GitHub repository settings")
        print("2. Set up PyPI trusted publishing")
        print("3. Test the release process")
    else:
        print("\n❌ Setup verification failed. Please fix the issues above.")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
