# Repository Setup for Open Source Release

This document outlines the recommended repository settings and branch protection rules for the Gopher MCP Server project.

## Branch Protection Rules

### Main Branch Protection

Configure the following settings for the `main` branch:

#### Required Status Checks
- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- Required checks:
  - `test` (Test Python 3.11 on ubuntu-latest)
  - `test` (Test Python 3.12 on ubuntu-latest)
  - `test` (Test Python 3.13 on ubuntu-latest)
  - `lint` (Lint and type check)
  - `security` (Security checks)
  - `docs` (Build documentation)

#### Pull Request Requirements
- ✅ Require a pull request before merging
- ✅ Require approvals: **1**
- ✅ Dismiss stale PR approvals when new commits are pushed
- ✅ Require review from code owners (when CODEOWNERS file is present)

#### Additional Restrictions
- ✅ Restrict pushes that create files larger than 100 MB
- ✅ Include administrators (recommended for consistency)
- ✅ Allow force pushes: **Disabled**
- ✅ Allow deletions: **Disabled**

## Repository Settings

### General Settings

#### Features
- ✅ Wikis: **Enabled** (for community documentation)
- ✅ Issues: **Enabled**
- ✅ Sponsorships: **Enabled** (if applicable)
- ✅ Preserve this repository: **Enabled**
- ✅ Discussions: **Enabled** (for community Q&A)

#### Pull Requests
- ✅ Allow merge commits: **Enabled**
- ✅ Allow squash merging: **Enabled** (default)
- ✅ Allow rebase merging: **Enabled**
- ✅ Always suggest updating pull request branches: **Enabled**
- ✅ Allow auto-merge: **Enabled**
- ✅ Automatically delete head branches: **Enabled**

### Security Settings

#### Security & Analysis
- ✅ Dependency graph: **Enabled**
- ✅ Dependabot alerts: **Enabled**
- ✅ Dependabot security updates: **Enabled**
- ✅ Dependabot version updates: **Enabled**
- ✅ Code scanning alerts: **Enabled**
- ✅ Secret scanning alerts: **Enabled**

#### Dependabot Configuration

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    reviewers:
      - "cameronrye"
    assignees:
      - "cameronrye"
    commit-message:
      prefix: "deps"
      include: "scope"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    reviewers:
      - "cameronrye"
    assignees:
      - "cameronrye"
    commit-message:
      prefix: "ci"
      include: "scope"
```

### Access & Permissions

#### Collaborators and Teams
- Repository owner: **cameronrye** (Admin)
- Consider adding trusted maintainers with **Maintain** permissions

#### Actions Permissions
- ✅ Allow all actions and reusable workflows
- ✅ Allow actions created by GitHub: **Enabled**
- ✅ Allow actions by Marketplace verified creators: **Enabled**
- ✅ Allow specified actions and reusable workflows

### Pages Settings

#### GitHub Pages
- ✅ Source: **GitHub Actions**
- ✅ Custom domain: (optional, configure if desired)
- ✅ Enforce HTTPS: **Enabled**

## Environment Protection Rules

### PyPI Environment
- Environment name: `pypi`
- Protection rules:
  - ✅ Required reviewers: Repository owner
  - ✅ Wait timer: 0 minutes
  - ✅ Deployment branches: Only protected branches

### TestPyPI Environment  
- Environment name: `testpypi`
- Protection rules:
  - ✅ Required reviewers: Repository owner
  - ✅ Wait timer: 0 minutes
  - ✅ Deployment branches: All branches

## Secrets and Variables

### Repository Secrets
- `CODECOV_TOKEN`: For code coverage reporting (if using Codecov)

### Environment Secrets
No secrets needed for OIDC-based PyPI publishing.

## Labels Configuration

### Default Labels to Add
- `good first issue` - Good for newcomers
- `help wanted` - Extra attention is needed
- `priority: high` - High priority
- `priority: medium` - Medium priority  
- `priority: low` - Low priority
- `type: bug` - Something isn't working
- `type: enhancement` - New feature or request
- `type: documentation` - Improvements or additions to documentation
- `type: security` - Security-related issue
- `status: needs-triage` - Needs initial review
- `status: blocked` - Blocked by external dependency
- `status: wontfix` - This will not be worked on

## Code Owners

Create `.github/CODEOWNERS`:

```
# Global owners
* @cameronrye

# Documentation
/docs/ @cameronrye
*.md @cameronrye

# CI/CD and workflows
/.github/ @cameronrye

# Core source code
/src/ @cameronrye

# Tests
/tests/ @cameronrye

# Configuration files
pyproject.toml @cameronrye
mkdocs.yml @cameronrye
```

## Automation Setup

### Required GitHub Apps/Integrations
1. **Codecov** (optional): For code coverage reporting
2. **Dependabot**: Already built into GitHub
3. **GitHub Actions**: Built-in CI/CD

### PyPI Trusted Publishing Setup

1. Go to PyPI account settings
2. Navigate to "Publishing" section
3. Add trusted publisher:
   - PyPI Project Name: `gopher-mcp`
   - Owner: `cameronrye`
   - Repository name: `gopher-mcp`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`

4. Repeat for TestPyPI with environment name: `testpypi`

## Post-Setup Verification

After configuring these settings:

1. ✅ Create a test PR to verify branch protection works
2. ✅ Verify CI/CD workflows run correctly
3. ✅ Test documentation deployment
4. ✅ Verify issue templates work
5. ✅ Test release workflow (with a pre-release tag)
6. ✅ Confirm PyPI publishing works with TestPyPI first

## Maintenance

### Regular Tasks
- Review and update dependencies monthly
- Monitor security alerts and address promptly
- Review and merge Dependabot PRs
- Update documentation as needed
- Review and update branch protection rules as project grows
