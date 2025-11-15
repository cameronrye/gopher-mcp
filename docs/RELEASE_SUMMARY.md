# Release System Setup Summary

This document provides a comprehensive overview of the production-ready release system for the Gopher & Gemini MCP Server project.

## What's Been Completed

### 1. Enhanced Release Workflow (`.github/workflows/release.yml`)

**Improvements Made**:
- **Version Validation**: Ensures tag matches `pyproject.toml` version
- **Changelog Validation**: Requires changelog entry for each release
- **Branch Verification**: Only allows releases from `main` branch
- **Enhanced Security**: Added artifact attestation and improved validation
- **Better Release Notes**: Improved generation with metadata and installation instructions
- **Package Testing**: Tests package installation before publishing
- **Comprehensive Validation**: Multiple validation steps before any publishing

**Key Features**:
- Semantic versioning validation
- Pre-release detection and handling
- Full test suite execution
- Security scanning (Bandit, Safety)
- Code quality checks (Ruff, MyPy)
- Documentation building
- Package building and validation
- GitHub release creation with detailed notes
- PyPI publishing with trusted publishing and attestation

### 2. Comprehensive Documentation

**Created Documents**:

#### `docs/RELEASE_PROCESS.md`
- Complete step-by-step release process
- Prerequisites and preparation steps
- Workflow monitoring guidance
- Verification procedures
- Troubleshooting guide
- Emergency procedures

#### `docs/RELEASE_CHECKLIST.md`
- Pre-release checklist (planning, QA, documentation, technical prep)
- Release execution checklist
- Post-release verification checklist
- Emergency procedures (cancellation, rollback)
- Version-specific guidelines (major, minor, patch, pre-release)

#### `docs/TESTING_RELEASES.md`
- Safe testing strategies
- Pre-release testing methods
- TestPyPI testing procedures
- Fork testing setup
- Dry run testing
- Common issues and solutions
- Cleanup procedures

#### `docs/PYPI_SETUP.md`
- PyPI account and project setup
- Trusted publishing configuration
- TestPyPI setup
- Verification steps
- Troubleshooting guide
- Security considerations
- Maintenance procedures

### 3. Enhanced Release Preparation Script

**Improvements to `scripts/prepare-release.py`**:
- **Changelog Validation**: Ensures changelog entries exist and have content
- **Version Consistency**: Validates version format and checks for conflicts
- **Better Error Handling**: More descriptive error messages and warnings
- **Git Tag Checking**: Warns about existing tags

### 4. GitHub Environment Configuration

**Verified Setup**:
- `pypi` environment with required reviewers and branch protection
- `testpypi` environment for testing
- Proper permissions and protection rules

## How to Trigger a Production Release

### Quick Start

```bash
# 1. Prepare the release
python scripts/prepare-release.py --version 0.2.0

# 2. Create and push the tag
git tag -a v0.2.0 -m "Release version 0.2.0"
git push origin v0.2.0

# 3. Monitor workflow and approve PyPI deployment when prompted
```

### Detailed Process

1. **Preparation Phase**:
   - Update version in `pyproject.toml`
   - Update `CHANGELOG.md` with release notes
   - Run validation: `python scripts/validate-release.py`
   - Commit changes: `git commit -m "chore: prepare release v0.2.0"`

2. **Release Execution**:
   - Create annotated tag: `git tag -a v0.2.0 -m "Release version 0.2.0"`
   - Push tag: `git push origin v0.2.0`
   - Monitor workflow at [GitHub Actions](https://github.com/cameronrye/gopher-mcp/actions)

3. **Approval and Verification**:
   - Approve PyPI deployment when prompted
   - Verify GitHub release creation
   - Verify PyPI publication
   - Test installation: `pip install gopher-mcp==0.2.0`

## What Happens During the Release Process

### Automatic Steps

1. **Validation Phase** (2-3 minutes):
   - Branch verification (must be `main`)
   - Version format validation
   - Version consistency check (tag vs `pyproject.toml`)
   - Changelog validation

2. **Test and Build Phase** (5-10 minutes):
   - Full test suite execution
   - Security scans (Bandit, Safety)
   - Code quality checks (Ruff, MyPy)
   - Documentation building
   - Package building and validation
   - Package installation testing

3. **GitHub Release Creation** (1-2 minutes):
   - Extract changelog content
   - Generate enhanced release notes
   - Create GitHub release with artifacts
   - Mark as pre-release if applicable

4. **PyPI Publishing** (Manual approval required):
   - Pauses for manual approval
   - Generate artifact attestation
   - Publish to PyPI with trusted publishing
   - Verify publication success

### Manual Steps Required

- **PyPI Deployment Approval**: Required for production releases
- **Initial PyPI Setup**: One-time trusted publishing configuration

## Security and Safety Features

### Built-in Protections

- **Trusted Publishing**: No API tokens required, uses OIDC
- **Environment Protection**: Manual approval required for PyPI
- **Branch Protection**: Only releases from `main` branch
- **Artifact Attestation**: Cryptographic proof of build provenance
- **Comprehensive Validation**: Multiple checks before publishing
- **Pre-release Support**: Safe testing with pre-release versions

### Rollback Capabilities

- **Tag Deletion**: Can cancel releases by deleting tags
- **PyPI Yanking**: Can yank problematic releases from PyPI
- **Hotfix Process**: Documented procedure for emergency fixes

## Manual Steps and Approvals Required

### One-Time Setup (Required)

1. **PyPI Trusted Publishing Configuration**:
   - Login to [PyPI](https://pypi.org/)
   - Navigate to project settings
   - Add trusted publisher with these exact settings:
     ```
     Repository owner: cameronrye
     Repository name: gopher-mcp
     Workflow filename: release.yml
     Environment name: pypi
     ```

2. **TestPyPI Setup** (Optional but recommended):
   - Same process on [TestPyPI](https://test.pypi.org/)
   - Use `publish.yml` workflow and `testpypi` environment

### Per-Release Approvals

1. **PyPI Deployment**: Manual approval required in GitHub Actions
2. **Pre-release Review**: Verify all checks pass before approval

## Monitoring and Verification

### What to Monitor

1. **GitHub Actions**: [Workflow runs](https://github.com/cameronrye/gopher-mcp/actions)
2. **GitHub Releases**: [Releases page](https://github.com/cameronrye/gopher-mcp/releases)
3. **PyPI Project**: [PyPI page](https://pypi.org/project/gopher-mcp/)
4. **Package Installation**: Test with `pip install gopher-mcp==X.Y.Z`

### Success Indicators

- All workflow steps complete successfully
- GitHub release created with correct version and notes
- PyPI shows new version available
- Package installs and imports correctly
- CLI command works: `gopher-mcp --help`

## How to Test Safely

### Recommended Testing Method

Use pre-release versions:

```bash
# Create pre-release
git tag -a v0.2.0-rc.1 -m "Release candidate 0.2.0-rc.1"
git push origin v0.2.0-rc.1

# This will:
# - Run complete workflow
# - Publish to PyPI as pre-release
# - Create GitHub release marked as pre-release
# - Safe for production (users won't install by default)
```

### Alternative Testing

- **TestPyPI**: Use `publish.yml` workflow with manual dispatch
- **Fork Testing**: Test on personal fork with separate PyPI project
- **Local Testing**: Use `scripts/validate-release.py` and `uv build`

## Emergency Procedures

### Cancel a Release

```bash
# Cancel workflow in GitHub Actions
# Delete the tag
git tag -d v0.2.0
git push origin :refs/tags/v0.2.0
```

### Rollback a Release

1. **Yank from PyPI**: Use PyPI web interface
2. **Create hotfix**: Prepare patch release (e.g., v0.2.1)
3. **Document issue**: Update changelog and create GitHub issue

## Next Steps

### Immediate Actions Required

1. **Complete PyPI Setup**:
   - Configure trusted publishing on PyPI
   - Test with TestPyPI or pre-release

2. **Test the System**:
   - Create a pre-release to test the complete workflow
   - Verify all steps work as expected

3. **First Production Release**:
   - Follow the release process for version 0.2.0
   - Monitor and document any issues

### Ongoing Maintenance

- **Regular Testing**: Test release process quarterly
- **Documentation Updates**: Keep guides current
- **Security Reviews**: Review configuration annually
- **Process Improvements**: Update based on experience

---

**The release system is now production-ready!**

All workflows, documentation, and safety measures are in place. The only remaining step is to complete the PyPI trusted publishing configuration and perform the first test release.

**Last Updated**: 2025-01-18
**Version**: 1.0
