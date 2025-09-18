# PyPI Configuration and Setup

This document provides comprehensive guidance for setting up PyPI publishing with trusted publishing (OIDC) for the Gopher & Gemini MCP Server project.

## Overview

The project uses **Trusted Publishing** with OpenID Connect (OIDC) for secure, token-free publishing to PyPI. This eliminates the need for API tokens and provides enhanced security through GitHub's OIDC identity provider.

## Current Configuration Status

### ✅ Configured Components

1. **GitHub Workflows**: Release and publish workflows are configured with OIDC
2. **GitHub Environments**: `pypi` and `testpypi` environments are set up
3. **Workflow Permissions**: Correct `id-token: write` permissions are configured
4. **Package Metadata**: `pyproject.toml` is properly configured

### ⚠️ Required Manual Setup

The following must be configured manually on PyPI:

1. **PyPI Project Registration**: Project must exist on PyPI
2. **Trusted Publisher Configuration**: OIDC publisher must be configured
3. **TestPyPI Configuration**: Optional but recommended for testing

## PyPI Project Setup

### 1. Create PyPI Account

If you don't have a PyPI account:

1. Visit [PyPI Registration](https://pypi.org/account/register/)
2. Create account with strong password
3. Enable two-factor authentication (required for publishing)
4. Verify email address

### 2. Register Project on PyPI

#### Option A: Manual Registration (Recommended)

1. **Visit PyPI**: Go to [PyPI](https://pypi.org/)
2. **Search for Project**: Verify `gopher-mcp` is available
3. **Reserve Name**: Create a placeholder project if needed

#### Option B: First Release Registration

The project will be automatically registered on first successful upload.

### 3. Configure Trusted Publishing

#### Step 1: Access Project Settings

1. **Login to PyPI**: Visit [PyPI](https://pypi.org/) and login
2. **Navigate to Project**: Go to the `gopher-mcp` project page
3. **Access Settings**: Click "Manage" → "Settings"
4. **Find Publishing**: Scroll to "Trusted publishing"

#### Step 2: Add GitHub Publisher

Configure the trusted publisher with these exact settings:

```
Repository owner: cameronrye
Repository name: gopher-mcp
Workflow filename: release.yml
Environment name: pypi
```

**Important**: These values must match exactly what's in the GitHub workflow.

#### Step 3: Verify Configuration

After adding the publisher, verify:
- ✅ Repository owner is `cameronrye`
- ✅ Repository name is `gopher-mcp`
- ✅ Workflow filename is `release.yml`
- ✅ Environment name is `pypi`

## TestPyPI Setup (Optional but Recommended)

### 1. Create TestPyPI Account

1. Visit [TestPyPI Registration](https://test.pypi.org/account/register/)
2. Create separate account (can use same email)
3. Enable two-factor authentication
4. Verify email address

### 2. Configure TestPyPI Trusted Publishing

Follow the same steps as PyPI, but use these settings:

```
Repository owner: cameronrye
Repository name: gopher-mcp
Workflow filename: publish.yml
Environment name: testpypi
```

## Verification Steps

### 1. Check GitHub Configuration

Verify the workflow configuration:

<augment_code_snippet path=".github/workflows/release.yml" mode="EXCERPT">
````yaml
  publish-pypi:
    name: Publish to PyPI
    environment:
      name: pypi
      url: https://pypi.org/p/gopher-mcp
    permissions:
      id-token: write  # IMPORTANT: this permission is mandatory for trusted publishing
      attestations: write  # For artifact attestation
````
</augment_code_snippet>

### 2. Test Configuration

#### Test with TestPyPI (Recommended)

1. **Trigger Publish Workflow**: Use manual workflow dispatch
2. **Select TestPyPI**: Choose `testpypi` as target
3. **Monitor Execution**: Watch for OIDC authentication success
4. **Verify Upload**: Check package appears on TestPyPI

#### Test with Pre-release

1. **Create Pre-release Tag**: `git tag -a v0.1.0-rc.1 -m "Test release"`
2. **Push Tag**: `git push origin v0.1.0-rc.1`
3. **Monitor Workflow**: Watch release workflow execution
4. **Verify PyPI Upload**: Check package appears on PyPI as pre-release

## Troubleshooting

### Common Issues

#### "Trusted publisher not configured"

**Error**: `HTTPError: 403 Forbidden from https://upload.pypi.org/legacy/`

**Solution**:
1. Verify trusted publisher is configured on PyPI
2. Check all configuration values match exactly
3. Ensure project exists on PyPI

#### "Invalid OIDC token"

**Error**: `OIDC token verification failed`

**Solution**:
1. Check workflow permissions include `id-token: write`
2. Verify environment name matches PyPI configuration
3. Ensure workflow filename matches PyPI configuration

#### "Environment not found"

**Error**: `Environment 'pypi' not found`

**Solution**:
1. Create environment in GitHub repository settings
2. Configure environment protection rules
3. Add required reviewers

#### "Package already exists"

**Error**: `File already exists`

**Solution**:
1. Increment version number
2. Use pre-release versions for testing
3. Check if version was already published

### Debug Steps

#### 1. Verify OIDC Token

Add debug step to workflow (temporarily):

```yaml
- name: Debug OIDC
  run: |
    echo "OIDC Token available: ${{ secrets.GITHUB_TOKEN != '' }}"
    echo "Environment: ${{ github.environment }}"
    echo "Repository: ${{ github.repository }}"
    echo "Workflow: ${{ github.workflow }}"
```

#### 2. Check PyPI Configuration

1. **Login to PyPI**: Visit project settings
2. **Check Trusted Publishers**: Verify configuration is active
3. **Review Logs**: Check PyPI activity logs

#### 3. Test Locally

```bash
# Build package locally
uv build

# Check package
twine check dist/*

# Test upload to TestPyPI (requires API token for local testing)
# twine upload --repository testpypi dist/*
```

## Security Considerations

### Best Practices

1. **Environment Protection**: Use GitHub environments with required reviewers
2. **Branch Protection**: Only allow releases from protected branches
3. **Minimal Permissions**: Use least-privilege principle
4. **Regular Audits**: Review trusted publisher configurations regularly

### Security Features

- **No API Tokens**: Eliminates token management and rotation
- **Short-lived Tokens**: OIDC tokens expire quickly
- **Scoped Access**: Tokens are scoped to specific repositories and workflows
- **Audit Trail**: All publishing actions are logged

## Maintenance

### Regular Tasks

#### Monthly
- [ ] Review PyPI project settings
- [ ] Check for security updates
- [ ] Verify trusted publisher configuration

#### Quarterly
- [ ] Test complete release process
- [ ] Review and update documentation
- [ ] Audit access permissions

#### Annually
- [ ] Rotate any remaining API tokens
- [ ] Review security configuration
- [ ] Update trusted publisher settings if needed

### Configuration Changes

If you need to change the configuration:

1. **Update GitHub Workflow**: Modify workflow files
2. **Update PyPI Settings**: Change trusted publisher configuration
3. **Test Changes**: Use TestPyPI or pre-release versions
4. **Document Changes**: Update this documentation

## Support and Resources

### Official Documentation

- [PyPI Trusted Publishing Guide](https://docs.pypi.org/trusted-publishers/)
- [GitHub OIDC Documentation](https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-pypi)
- [Python Packaging Guide](https://packaging.python.org/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)

### Getting Help

- **PyPI Support**: [PyPI Help](https://pypi.org/help/)
- **GitHub Support**: [GitHub Actions Documentation](https://docs.github.com/actions)
- **Community**: [Python Packaging Discourse](https://discuss.python.org/c/packaging/)

### Project-Specific Support

- **Issues**: Create GitHub issue for configuration problems
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Update this guide based on experience

---

**Next Steps**:
1. Complete PyPI trusted publisher configuration
2. Test with TestPyPI
3. Perform test release with pre-release version
4. Document any issues or additional setup required

**Last Updated**: 2025-01-18
**Version**: 1.0
