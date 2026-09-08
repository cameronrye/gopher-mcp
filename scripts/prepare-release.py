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


class ReleasePreparation:
    """Handles release preparation tasks."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def _get_current_version(self) -> str:
        """Get the current version from pyproject.toml."""
        pyproject_path = self.project_root / "pyproject.toml"
        if not pyproject_path.exists():
            raise FileNotFoundError("pyproject.toml not found!")

        content = pyproject_path.read_text()
        # Anchor to the start of a line so we read [project].version and not a
        # substring of target-version / python_version / minversion.
        match = re.search(r'^version = "([^"]+)"', content, flags=re.MULTILINE)
        if not match:
            raise ValueError("Version not found in pyproject.toml!")

        return match.group(1)

    def _validate_version_format(self, version: str) -> bool:
        """Validate version format (semantic versioning)."""
        pattern = r"^(\d+)\.(\d+)\.(\d+)(?:-([\w\.-]+))?(?:\+([\w\.-]+))?$"
        return bool(re.match(pattern, version))

    def _update_version(self, new_version: str) -> None:
        """Update the version in pyproject.toml and server.json.

        The release workflow validates that pyproject.toml AND server.json (its
        top-level version, each package version, and the image tag inside the
        OCI package's identifier) all match the tag, so every one must be bumped
        here -- a pyproject-only bump produces a tag push that fails at
        validate-release.
        """
        # pyproject.toml: anchor to the start of a line and replace only the
        # first match, so we don't rewrite target-version / python_version /
        # minversion (which an unanchored substring match would clobber, breaking
        # ruff/mypy/pytest config).
        pyproject_path = self.project_root / "pyproject.toml"
        content = pyproject_path.read_text()
        content, n = re.subn(
            r'^version = "[^"]+"',
            f'version = "{new_version}"',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise ValueError("Could not locate [project].version in pyproject.toml")
        pyproject_path.write_text(content)
        print(f"✅ Updated version to {new_version} in pyproject.toml")

        # server.json: the MCP registry manifest carries the version in three
        # shapes, not two. The top-level field and each package's `version` key
        # are the obvious ones; the third is the image tag inside the OCI
        # package's `identifier`, because the registry REJECTS a `version` key
        # on an OCI package ("include version in identifier instead") -- so for
        # that entry the tag is the version.
        #
        # Missing it fails the tag run at validate-release, which reads the tag
        # out of the identifier and compares it -- but only after the tag is
        # pushed, so the cost is the delete-and-re-push dance rather than a bad
        # artifact. That gate is why this is safe; it is not why it is here.
        # Before the gate existed, a stale tag published silently: publish-image
        # pushed the new tag while publish-registry verified the old one, found
        # a real image left over from the previous release, and published a
        # registry entry pointing every client at the wrong container. Use json
        # load/dump so we touch only version fields and preserve formatting
        # elsewhere.
        server_json_path = self.project_root / "server.json"
        if server_json_path.exists():
            import json

            data = json.loads(server_json_path.read_text())
            data["version"] = new_version
            for package in data.get("packages", []):
                if "version" in package:
                    package["version"] = new_version
                identifier = package.get("identifier", "")
                if package.get("registryType") == "oci" and ":" in identifier:
                    # rsplit: the registry host may carry a :port, and only the
                    # last colon introduces the tag.
                    package["identifier"] = (
                        f"{identifier.rsplit(':', 1)[0]}:{new_version}"
                    )
            server_json_path.write_text(json.dumps(data, indent=2) + "\n")
            print(f"✅ Updated version to {new_version} in server.json")

    def _update_changelog(self, version: str) -> None:
        """Update CHANGELOG.md with new version."""
        changelog_path = self.project_root / "CHANGELOG.md"
        if not changelog_path.exists():
            self.warnings.append("CHANGELOG.md not found!")
            return

        content = changelog_path.read_text()

        # Check if version already exists
        if f"## [{version}]" in content:
            print(f"Version {version} already exists in CHANGELOG.md")
            return

        # Find the unreleased section
        unreleased_pattern = (
            r"## \[Unreleased\].*?\n(.*?)(?=\n## \[|\n\[unreleased\]|\Z)"
        )
        match = re.search(unreleased_pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            unreleased_content = match.group(1).strip()
            if unreleased_content:
                # Add new version section
                import datetime

                today = datetime.date.today().strftime("%Y-%m-%d")
                new_section = f"\n## [{version}] - {today}\n\n{unreleased_content}\n"

                # Replace unreleased section. The replacement is group 1 plus a
                # section that already opens with a newline -- an extra `\n`
                # here puts TWO blank lines under the `## [Unreleased]` heading,
                # which prettier does not collapse and every release then had to
                # tidy by hand before committing.
                #
                # A callable, not a replacement string: `re.sub` interprets
                # backslashes in a replacement as escapes, and the notes are
                # arbitrary prose. `C:\docs` reads as the group reference `\d`
                # and aborts the bump -- after `_update_version` has already
                # rewritten pyproject.toml and all three server.json versions,
                # so the tree is left half-bumped. A valid-but-wrong escape is
                # worse than the crash: `\n` in a code span expands to a real
                # newline, and this section becomes the GitHub Release body
                # verbatim, so it ships a control character with nothing red.
                # A callable's return value is used literally.
                content = re.sub(
                    r"(## \[Unreleased\].*?\n).*?(?=\n## \[|\n\[unreleased\]|\Z)",
                    lambda m: m.group(1) + new_section,
                    content,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                content = self._update_changelog_links(content, version)

                changelog_path.write_text(content)
                print(f"✅ Updated CHANGELOG.md with version {version}")
            else:
                self.warnings.append("No unreleased changes found in CHANGELOG.md")
        else:
            self.warnings.append("Could not find unreleased section in CHANGELOG.md")

    #: The `[Unreleased]` link definition, which names the tag it compares
    #: against and so tells us what the previous release was. `[ \t]*$` rather
    #: than `\s*$`: with MULTILINE, `\s` would swallow the newline and the
    #: definitions below it, and the replacement would eat the rest of the block.
    _UNRELEASED_LINK = re.compile(
        r"^\[unreleased\]:[ \t]*(?P<url>\S+/compare/)v(?P<prev>\S+?)\.\.\.HEAD[ \t]*$",
        re.IGNORECASE | re.MULTILINE,
    )

    def _update_changelog_links(self, content: str, version: str) -> str:
        """Point `[Unreleased]` at the new tag and give the release its own link.

        Promoting the section is only half the job. The link definitions at the
        foot of the file are what make `## [0.10.1]` a link at all -- Markdown
        renders an undefined reference as literal text, so a release whose
        definition is missing shows a bare `[0.10.1]` on the GitHub release page
        and the docs site. And `[Unreleased]` keeps comparing against the
        PREVIOUS tag, so the "unreleased changes" link shows the release that
        just shipped as though it were still pending.

        Neither failure stops a release or trips any check, which is why this
        belongs in code rather than in the checklist: the repo's history carries
        more than one commit repairing these by hand afterwards.

        The previous version is read out of the `[Unreleased]` link rather than
        passed in, because that link is the one place already required to name
        it -- deriving it from a sorted tag list or from the section headings
        would be a second source that can disagree with this one.
        """
        match = self._UNRELEASED_LINK.search(content)
        if match is None:
            self.warnings.append(
                "CHANGELOG.md has no [Unreleased] compare link, so the link "
                f"definition for {version} was not added -- add it by hand."
            )
            return content

        if re.search(rf"^\[{re.escape(version)}\]:", content, flags=re.MULTILINE):
            return content

        url, previous = match.group("url"), match.group("prev")
        replacement = (
            f"[Unreleased]: {url}v{version}...HEAD\n"
            f"[{version}]: {url}v{previous}...v{version}"
        )
        print(f"✅ Updated CHANGELOG.md compare links for {version}")
        return content[: match.start()] + replacement + content[match.end() :]

    def _create_git_tag(self, version: str, message: str | None = None) -> None:
        """Create and push git tag."""
        tag_name = f"v{version}"

        # Check if tag already exists
        result = subprocess.run(
            ["git", "tag", "-l", tag_name],
            check=False,
            capture_output=True,
            text=True,
            cwd=self.project_root,
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

        result = subprocess.run(cmd, check=False, cwd=self.project_root)
        if result.returncode == 0:
            print(f"✅ Created tag {tag_name}")

            # Ask if user wants to push
            response = input(f"Push tag {tag_name} to origin? (y/N): ")
            if response.lower() == "y":
                push_result = subprocess.run(
                    ["git", "push", "origin", tag_name],
                    check=False,
                    cwd=self.project_root,
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
            ("📋 Validating Changelog", self._validate_changelog),
            ("🔢 Checking Version Consistency", self._check_version_consistency),
        ]

        if not skip_tests:
            steps.extend(
                [
                    ("🧪 Running Tests", self._run_tests),
                    ("📝 Checking Code Quality", self._check_code_quality),
                    ("🔐 Security Scan", self._security_scan),
                ]
            )

        steps.extend(
            [
                ("📚 Validating Documentation", self._validate_documentation),
                ("🔧 Checking Dependencies", self._check_dependencies),
                ("📦 Building Package", self._build_package),
            ]
        )

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
                check=False,
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Record it, don't just return False. `prepare_release` reports
                # success on `len(self.errors) == 0`, not on the step results,
                # so a bare `return False` printed FAILED for the step and then
                # "Ready for release!" with exit 0 -- inverting the first gate
                # in the list. Carry the child's output too: it holds the only
                # statement of what actually failed, and it is captured.
                detail = (result.stderr or result.stdout or "").strip()
                self.errors.append(
                    "Configuration validation failed"
                    + (f":\n{detail}" if detail else " (no output)")
                )
                return False
            return True
        except Exception as e:
            self.errors.append(f"Configuration validation failed: {e}")
            return False

    def _validate_changelog(self) -> bool:
        """Validate changelog has entry for current version."""
        try:
            changelog_path = self.project_root / "CHANGELOG.md"
            if not changelog_path.exists():
                self.errors.append("CHANGELOG.md not found")
                return False

            current_version = self._get_current_version()
            content = changelog_path.read_text()

            # Check if version entry exists
            version_pattern = rf"## \[{re.escape(current_version)}\]"
            if not re.search(version_pattern, content):
                self.errors.append(
                    f"No changelog entry found for version {current_version}"
                )
                return False

            # Check if the entry has content
            section_pattern = (
                rf"## \[{re.escape(current_version)}\].*?\n(.*?)(?=\n## \[|\Z)"
            )
            match = re.search(section_pattern, content, re.DOTALL)
            if match:
                section_content = match.group(1).strip()
                if not section_content or section_content == "- TBD":
                    self.errors.append(
                        f"Changelog entry for version {current_version} is empty or placeholder"
                    )
                    return False

            print(f"✅ Changelog entry found for version {current_version}")
            return True

        except Exception as e:
            self.errors.append(f"Changelog validation failed: {e}")
            return False

    def _declared_versions(self) -> "list[tuple[str, str | None]]":
        """Every version in server.json, as (human-readable location, value).

        Three shapes, matching `_update_version`: the top-level field, each
        package's `version` key, and the image tag inside an OCI package's
        `identifier` -- the registry rejects a `version` key on an OCI package,
        so for that entry the tag IS the version. An absent server.json yields
        nothing to compare rather than an error; it is optional to the bump.

        A value of `None` means the field is missing or unreadable, which is a
        mismatch rather than something to skip -- this has to fail exactly what
        `release.yml`'s validate-release job fails, or it passes manifests the
        tag run will reject.
        """
        server_json_path = self.project_root / "server.json"
        if not server_json_path.exists():
            return []

        import json

        data = json.loads(server_json_path.read_text())
        found = [("server.json version", data.get("version"))]
        for i, package in enumerate(data.get("packages", [])):
            registry = package.get("registryType")
            where = f"server.json packages[{i}] ({registry})"
            if registry == "oci":
                # A canonical reference is registry[:port]/path:tag, so the tag
                # is what follows the LAST colon -- and only if no '/' follows
                # it, which is what tells "ghcr.io/o/n:1.2.3" from a bare
                # "localhost:5000/o/n" that carries no tag at all.
                identifier = package.get("identifier", "")
                repository, separator, tag = identifier.rpartition(":")
                if not separator or not repository or "/" in tag:
                    found.append((f"{where} image tag", None))
                else:
                    found.append((f"{where} image tag", tag))
            else:
                # ``.get``, not an ``in`` guard: an absent key is a MISSING
                # version, which release.yml compares as None and fails. Skipping
                # the package instead made this check pass every manifest CI
                # would reject -- a local gate looser than the one it stands in
                # for is worse than no local gate.
                found.append((where, package.get("version")))
        return found

    def _check_version_consistency(self) -> bool:
        """Check version consistency across files."""
        try:
            current_version = self._get_current_version()

            # Check if version format is valid
            if not self._validate_version_format(current_version):
                self.errors.append(f"Invalid version format: {current_version}")
                return False

            # Compare pyproject's version against every other place it is
            # written. The step was named for consistency but only checked the
            # format and looked for a colliding tag -- it never opened
            # server.json, so the one failure it exists to catch (a hand-edited
            # bump that missed a field) passed here and failed in CI *after* the
            # tag was pushed, which costs the delete-and-re-push-the-tag dance.
            # Same three shapes `_update_version` writes, and the same
            # comparison release.yml's validate-release job makes.
            mismatches = [
                f"{where} carries no image tag"
                if found is None and where.endswith("image tag")
                else f"{where} is {found!r}, expected {current_version!r}"
                for where, found in self._declared_versions()
                if found != current_version
            ]
            if mismatches:
                self.errors.append(
                    "Version is inconsistent with pyproject.toml: "
                    + "; ".join(mismatches)
                )
                return False

            # Check for any git tags that might conflict
            try:
                result = subprocess.run(
                    ["git", "tag", "-l", f"v{current_version}"],
                    check=False,
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                )
                if result.stdout.strip():
                    self.warnings.append(f"Git tag v{current_version} already exists")

            except subprocess.CalledProcessError:
                # Git not available or not a git repo, skip tag check
                pass

            print(f"✅ Version {current_version} is consistent and well-formed")
            return True

        except Exception as e:
            self.errors.append(f"Version consistency check failed: {e}")
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
                    # Must track [tool.pytest.ini_options] addopts in
                    # pyproject.toml. Hard-coding a lower number here would
                    # validate a release against a gate the project no longer
                    # uses, so a release could be blessed while CI would fail
                    # it.
                    "--cov-fail-under=95",
                ],
                check=False,
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                self.errors.append("Test suite failed")
                return False

            # Check for specific test categories
            test_results = []

            # There is deliberately no separate "unit tests" run here: the full
            # run above already executes every non-integration test, so a third
            # pytest invocation only tripled the wall-clock cost of preparing a
            # release without being able to fail on anything new.

            # Integration tests (if any). --no-cov because this is a SUBSET of
            # the suite: the 95% gate in pyproject.toml is a whole-suite figure,
            # so running ~19 integration tests against it always fails on
            # coverage and reported "Integration tests had failures" on every
            # release even when all of them passed. Coverage is measured by the
            # unit run above.
            integration_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/",
                    "-v",
                    "-m",
                    "integration",
                    "--no-cov",
                ],
                check=False,
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
            # Whole-repo scope, matching ci.yml's `ruff check .` and the
            # rationale in pyproject.toml: scoping to src/tests hides
            # violations in scripts/ and the repo root that CI still fails on,
            # so a release could pass here and go red the moment the tag lands.
            lint_result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "."],
                check=False,
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Run ruff formatting check (same whole-repo scope as CI)
            format_result = subprocess.run(
                [sys.executable, "-m", "ruff", "format", "--check", "."],
                check=False,
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )

            # Run mypy type checking
            mypy_result = subprocess.run(
                [sys.executable, "-m", "mypy", "src/"],
                check=False,
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
            # No `pip list --outdated` here: it warns on every transitive
            # package the lockfile deliberately pins, so it fired on every
            # release and meant nothing. Dependabot and the nightly
            # security-audit workflow own dependency freshness.

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
            # `uv build`, not `pip install --upgrade build` + `python -m build`:
            # `build` is not a declared dependency, so the old code silently
            # mutated the developer's virtualenv with an undeclared package --
            # and it built with a different frontend than CI, releasing.md and
            # scripts/validate-release.py, all of which use `uv build`. A
            # release check must exercise the path that actually ships.
            result = subprocess.run(
                ["uv", "build"],
                check=False,
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
                check=False,
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
        if response.lower() == "y":
            prep._update_version(args.version)
            prep._update_changelog(args.version)

    # Run release preparation
    success = prep.prepare_release(skip_tests=args.skip_tests)

    # Create git tag if requested and successful
    if success and args.version and not args.skip_tag:
        response = input(f"Create git tag v{args.version}? (y/N): ")
        if response.lower() == "y":
            prep._create_git_tag(args.version, args.tag_message)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
