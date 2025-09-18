# Release Process Documentation

This document outlines the complete release process for the Gopher & Gemini MCP Server project.

## Overview

The release process is fully automated through GitHub Actions and follows these key principles:

- **Semantic Versioning**: All releases follow [SemVer](https://semver.org/) (X.Y.Z format)
- **Automated Testing**: Comprehensive test suite runs before any release
- **Security First**: Security scans, code quality checks, and artifact attestation
- **Trusted Publishing**: Uses OpenID Connect for secure PyPI publishing
- **Changelog Driven**: All releases must have corresponding changelog entries

## Release Types

### Stable Releases (X.Y.Z)
- Production-ready releases
- Require manual approval in the `pypi` environment
- Published to PyPI with full documentation
- Create GitHub releases with detailed release notes

### Pre-releases (X.Y.Z-alpha.N, X.Y.Z-beta.N, X.Y.Z-rc.N)
- Development and testing releases
- Marked as pre-release on GitHub
- Published to PyPI but flagged as pre-release
- Useful for testing before stable release

## Prerequisites

Before creating a release, ensure:

1. **All tests pass** on the main branch
2. **Code quality checks** pass (linting, type checking)
3. **Security scans** are clean
4. **Documentation** is up to date
5. **Changelog** has been updated with the new version
6. **Version** in `pyproject.toml` matches the intended release version

## Step-by-Step Release Process

### 1. Prepare the Release

#### Update Version and Changelog

```bash
# Use the prepare-release script
python scripts/prepare-release.py --version 0.2.0

# Or manually update:
# 1. Update version in pyproject.toml
# 2. Update CHANGELOG.md with new version section
# 3. Commit changes
git add pyproject.toml CHANGELOG.md
git commit -m "chore: prepare release v0.2.0"
git push origin main
```

#### Run Pre-release Validation

```bash
# Run comprehensive validation
python scripts/validate-release.py

# Or run individual checks
uv run task quality  # Code quality
uv run task test     # Test suite
uv build            # Build packages
```

### 2. Create and Push the Release Tag

```bash
# Create annotated tag
git tag -a v0.2.0 -m "Release version 0.2.0"

# Push tag to trigger release workflow
git push origin v0.2.0
```

**⚠️ Important**: Once you push the tag, the release process begins automatically!

### 3. Monitor the Release Workflow

1. **Go to GitHub Actions**: Navigate to the [Actions tab](https://github.com/cameronrye/gopher-mcp/actions)
2. **Find the Release workflow**: Look for the workflow triggered by your tag
3. **Monitor progress**: The workflow has several stages:
   - ✅ **Validate Release**: Version validation, changelog check, branch verification
   - ✅ **Test and Build**: Full test suite, security scans, package building
   - ✅ **Create GitHub Release**: Generate release notes and create GitHub release
   - ⏳ **Publish to PyPI**: Requires manual approval, then publishes to PyPI

### 4. Approve PyPI Publication

1. **Wait for approval request**: The workflow will pause at the PyPI publishing step
2. **Review the release**: Check that all previous steps completed successfully
3. **Approve deployment**: Go to the workflow run and approve the PyPI environment deployment
4. **Monitor publication**: Watch the final step complete

### 5. Verify the Release

After the workflow completes:

#### Check GitHub Release
- Visit [Releases page](https://github.com/cameronrye/gopher-mcp/releases)
- Verify release notes are correct
- Confirm artifacts are attached

#### Check PyPI Publication
- Visit [PyPI project page](https://pypi.org/project/gopher-mcp/)
- Verify new version is available
- Check that description and metadata are correct

#### Test Installation
```bash
# Test installation from PyPI
pip install gopher-mcp==0.2.0

# Verify it works
gopher-mcp --help
python -c "import gopher_mcp; print('Success!')"
```

## Workflow Details

### Validation Steps

The release workflow performs these validations:

1. **Branch Verification**: Ensures release is from `main` branch
2. **Version Format**: Validates semantic versioning format
3. **Version Consistency**: Checks tag matches `pyproject.toml` version
4. **Changelog Validation**: Ensures changelog entry exists for the version
5. **Test Suite**: Runs complete test suite with coverage
6. **Security Scans**: Bandit and Safety security analysis
7. **Code Quality**: Ruff linting and MyPy type checking
8. **Documentation**: Builds documentation to ensure it's valid
9. **Package Building**: Creates wheel and source distributions
10. **Package Validation**: Validates packages with Twine
11. **Installation Test**: Tests package installation in clean environment

### Security Features

- **Trusted Publishing**: Uses OpenID Connect instead of API tokens
- **Artifact Attestation**: Generates cryptographic attestation for packages
- **Environment Protection**: PyPI environment requires manual approval
- **Branch Protection**: Only releases from protected main branch
- **Signature Verification**: All packages are signed with Sigstore

### Environments

The project uses GitHub Environments for deployment protection:

- **`pypi`**: Production PyPI deployment
  - Requires manual approval from repository maintainers
  - Protected branches only
  - Trusted publishing configured

- **`testpypi`**: Test PyPI deployment (via publish workflow)
  - Used for testing releases
  - Requires manual approval
  - Separate from production releases

## Troubleshooting

### Common Issues

#### "Version mismatch" Error
**Problem**: Tag version doesn't match `pyproject.toml` version
**Solution**: Update `pyproject.toml` version to match your tag, or create a new tag

#### "Changelog missing entry" Error
**Problem**: No changelog entry found for the release version
**Solution**: Add a section to `CHANGELOG.md` with the format `## [X.Y.Z] - YYYY-MM-DD`

#### "Tests failing" Error
**Problem**: Test suite fails during release
**Solution**: Fix failing tests on main branch before creating release tag

#### "Security scan failures" Error
**Problem**: Bandit or Safety finds security issues
**Solution**: Address security issues or add exceptions if false positives

### Emergency Procedures

#### Cancel a Release
If you need to cancel a release in progress:

1. **Cancel the workflow**: Go to Actions and cancel the running workflow
2. **Delete the tag**: `git tag -d v0.2.0 && git push origin :refs/tags/v0.2.0`
3. **Fix issues**: Address whatever caused the need to cancel
4. **Create new tag**: Follow the normal release process with a new version

#### Rollback a Release
If a release was published but has critical issues:

1. **Yank from PyPI**: Use PyPI web interface to yank the problematic version
2. **Create hotfix**: Prepare a patch release (e.g., 0.2.1)
3. **Release hotfix**: Follow normal release process for the fix
4. **Update documentation**: Document the issue and resolution

## Testing the Release Process

### Safe Testing Methods

#### 1. Test with Pre-release Versions
```bash
# Create a pre-release tag
git tag -a v0.2.0-rc.1 -m "Release candidate 0.2.0-rc.1"
git push origin v0.2.0-rc.1
```

#### 2. Test with TestPyPI
Use the `publish.yml` workflow for testing:
```bash
# Trigger manual workflow dispatch
# Go to Actions > Publish to PyPI > Run workflow
# Select "testpypi" as target
```

#### 3. Fork Testing
- Create a fork of the repository
- Test the release process on your fork
- Verify all steps work before applying to main repository

### Validation Checklist

Before releasing to production, verify:

- [ ] All tests pass locally and in CI
- [ ] Version number is correct in all files
- [ ] Changelog is updated and formatted correctly
- [ ] Documentation builds without errors
- [ ] Security scans are clean
- [ ] Package builds and installs correctly
- [ ] All required approvals are in place

## Next Steps After Release

1. **Monitor for Issues**: Watch for bug reports or installation problems
2. **Update Documentation**: Ensure all docs reflect the new version
3. **Announce Release**: Consider announcing on relevant channels
4. **Plan Next Release**: Update project roadmap and version planning

## Support

For questions about the release process:

- **Documentation**: Check this guide and workflow comments
- **Issues**: Create a GitHub issue for process improvements
- **Discussions**: Use GitHub Discussions for questions

---

**Last Updated**: 2025-01-18
**Version**: 1.0
