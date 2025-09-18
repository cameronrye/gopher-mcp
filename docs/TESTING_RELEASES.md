# Testing Release Workflows

This document provides comprehensive guidance for safely testing the release workflow without affecting production systems.

## Overview

Testing the release workflow is crucial to ensure:
- The automation works correctly
- All validation steps function properly
- PyPI publishing works as expected
- GitHub releases are created correctly
- No production systems are affected during testing

## Testing Strategies

### 1. Pre-release Testing (Recommended)

Use pre-release versions to test the complete workflow safely.

#### Create a Pre-release Tag

```bash
# Example: Release candidate
git tag -a v0.2.0-rc.1 -m "Release candidate 0.2.0-rc.1"
git push origin v0.2.0-rc.1

# Example: Beta release
git tag -a v0.2.0-beta.1 -m "Beta release 0.2.0-beta.1"
git push origin v0.2.0-beta.1

# Example: Alpha release
git tag -a v0.2.0-alpha.1 -m "Alpha release 0.2.0-alpha.1"
git push origin v0.2.0-alpha.1
```

#### Benefits
- ✅ Tests complete release workflow
- ✅ Publishes to PyPI as pre-release
- ✅ Creates GitHub release marked as pre-release
- ✅ Safe for production (users won't install by default)
- ✅ Can be yanked from PyPI if needed

### 2. TestPyPI Testing

Use the separate `publish.yml` workflow to test PyPI publishing.

#### Manual Workflow Dispatch

1. **Navigate to Actions**: Go to [GitHub Actions](https://github.com/cameronrye/gopher-mcp/actions)
2. **Select Publish Workflow**: Click on "Publish to PyPI"
3. **Run Workflow**: Click "Run workflow"
4. **Select TestPyPI**: Choose "testpypi" as the target
5. **Monitor Execution**: Watch the workflow complete

#### Benefits
- ✅ Tests PyPI publishing process
- ✅ Uses TestPyPI (separate from production)
- ✅ Validates package building and uploading
- ✅ No impact on production PyPI
- ❌ Doesn't test complete release workflow

### 3. Fork Testing

Create a fork to test the complete workflow in isolation.

#### Setup Fork Testing

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/gopher-mcp.git
cd gopher-mcp

# Configure for testing
# 1. Update package name in pyproject.toml to avoid conflicts
# 2. Set up your own PyPI test project
# 3. Configure GitHub environments in your fork
```

#### Benefits
- ✅ Complete isolation from production
- ✅ Tests entire workflow
- ✅ Can test multiple scenarios
- ❌ Requires additional setup
- ❌ Need separate PyPI project

### 4. Dry Run Testing

Test individual components without triggering the full workflow.

#### Local Testing

```bash
# Test release preparation
python scripts/prepare-release.py --version 0.2.0-test --skip-tests

# Test validation
python scripts/validate-release.py

# Test package building
uv build
twine check dist/*

# Test package installation
pip install dist/*.whl
```

#### Benefits
- ✅ Quick feedback
- ✅ No external dependencies
- ✅ Safe for development
- ❌ Doesn't test GitHub Actions
- ❌ Doesn't test PyPI publishing

## Testing Scenarios

### Scenario 1: First Release Test

**Objective**: Test the complete release process for the first time.

**Steps**:
1. Create a pre-release version (e.g., `v0.1.0-rc.1`)
2. Update `pyproject.toml` with the pre-release version
3. Add changelog entry for the pre-release
4. Create and push the tag
5. Monitor the complete workflow
6. Verify GitHub release creation
7. Verify PyPI publication (marked as pre-release)
8. Test installation: `pip install gopher-mcp==0.1.0rc1`

### Scenario 2: Patch Release Test

**Objective**: Test a patch release workflow.

**Steps**:
1. Create a patch pre-release (e.g., `v0.1.1-rc.1`)
2. Ensure minimal changes since last release
3. Test that changelog validation works
4. Verify version consistency checks
5. Confirm patch-level changes don't break anything

### Scenario 3: Major Release Test

**Objective**: Test a major release with breaking changes.

**Steps**:
1. Create a major pre-release (e.g., `v1.0.0-rc.1`)
2. Test with significant changelog entries
3. Verify documentation updates
4. Test migration scenarios
5. Confirm breaking change documentation

### Scenario 4: Error Handling Test

**Objective**: Test workflow error handling and validation.

**Steps**:
1. **Test version mismatch**: Create tag that doesn't match `pyproject.toml`
2. **Test missing changelog**: Create tag without changelog entry
3. **Test failing tests**: Introduce a failing test and create tag
4. **Test security issues**: Introduce a security warning and test handling

## Validation Checklist

### Before Testing
- [ ] Backup current state
- [ ] Ensure you're on a test branch or using pre-release versions
- [ ] Verify GitHub environments are configured
- [ ] Confirm PyPI trusted publishing is set up

### During Testing
- [ ] Monitor workflow execution in real-time
- [ ] Check each step completes successfully
- [ ] Verify validation steps catch intended errors
- [ ] Confirm approval processes work correctly

### After Testing
- [ ] Verify GitHub release was created correctly
- [ ] Check PyPI publication (TestPyPI or pre-release)
- [ ] Test package installation
- [ ] Verify all artifacts are present
- [ ] Clean up test releases if needed

## Common Testing Issues

### Issue: "Version already exists on PyPI"
**Solution**: Use pre-release versions or increment version number

### Issue: "GitHub environment not found"
**Solution**: Ensure environments are configured in repository settings

### Issue: "Trusted publishing not configured"
**Solution**: Set up OIDC trusted publishing on PyPI

### Issue: "Workflow permissions denied"
**Solution**: Check repository permissions and environment settings

### Issue: "Tag already exists"
**Solution**: Delete existing tag or use different version number

## Cleanup After Testing

### Remove Test Tags
```bash
# Delete local tag
git tag -d v0.2.0-rc.1

# Delete remote tag
git push origin :refs/tags/v0.2.0-rc.1
```

### Remove Test Releases
1. Go to [Releases page](https://github.com/cameronrye/gopher-mcp/releases)
2. Delete test releases
3. Clean up any test artifacts

### Remove Test PyPI Packages
1. Visit [TestPyPI project](https://test.pypi.org/project/gopher-mcp/)
2. Delete test versions if needed
3. Or let them expire naturally

## Best Practices

### Testing Frequency
- **Before major releases**: Always test with pre-release
- **After workflow changes**: Test any modifications to GitHub Actions
- **Quarterly**: Regular testing to ensure everything still works
- **Before first use**: Comprehensive testing of the entire process

### Documentation
- Document any issues found during testing
- Update this guide based on testing experience
- Share testing results with the team
- Keep testing logs for reference

### Safety Measures
- Always use pre-release versions for testing
- Never test with production version numbers
- Use TestPyPI when possible
- Have rollback plans ready

## Emergency Testing

If you need to test the release process urgently:

### Quick Pre-release Test
```bash
# Create immediate pre-release
git tag -a v$(date +%Y%m%d)-test -m "Emergency test release"
git push origin v$(date +%Y%m%d)-test
```

### Minimal Validation
```bash
# Quick local validation
python scripts/validate-release.py --quick
uv build && twine check dist/*
```

## Monitoring and Alerts

### What to Monitor
- Workflow execution time
- Success/failure rates
- PyPI publication status
- GitHub release creation
- Package installation success

### Setting Up Alerts
- Configure GitHub notifications for workflow failures
- Monitor PyPI project for unexpected publications
- Set up alerts for security scan failures
- Track download statistics for anomalies

---

**Remember**: Testing is crucial for reliable releases. Always test changes to the release process before using them in production.

**Last Updated**: 2025-01-18
**Version**: 1.0
