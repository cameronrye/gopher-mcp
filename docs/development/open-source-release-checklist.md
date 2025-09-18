# Open Source Release Checklist

This document provides a comprehensive checklist for preparing the Gopher MCP Server for open source release.

## ✅ Pre-Release Checklist

### 📋 Repository Setup
- [x] **GitHub Pages Documentation**: Automated deployment configured
- [x] **PyPI Publishing**: OIDC trusted publishing workflow created
- [x] **Release Management**: Comprehensive release workflow implemented
- [x] **Issue Templates**: Bug reports, feature requests, and questions
- [x] **PR Template**: Standardized pull request template
- [x] **Branch Protection**: Documentation for recommended settings
- [x] **Dependabot**: Automated dependency updates configured
- [x] **CODEOWNERS**: Code ownership defined

### 🔒 Security & Compliance
- [x] **LICENSE**: MIT license present and properly formatted
- [x] **SECURITY.md**: Security policy documented
- [x] **Sensitive Data**: No secrets, API keys, or sensitive information in repository
- [x] **Dependencies**: All dependencies reviewed for security vulnerabilities
- [x] **Security Scanning**: Bandit and safety checks in CI/CD

### 📚 Documentation
- [x] **README.md**: Comprehensive, public-ready documentation
- [x] **CONTRIBUTING.md**: Clear contribution guidelines
- [x] **CHANGELOG.md**: Version history documented
- [x] **API Documentation**: Complete API reference
- [x] **Installation Guide**: Multiple installation methods documented
- [x] **GitHub Pages**: Documentation site configured and building

### 🧪 Quality Assurance
- [x] **Test Coverage**: Comprehensive test suite with good coverage
- [x] **CI/CD Pipeline**: All tests passing on multiple platforms
- [x] **Code Quality**: Linting, formatting, and type checking
- [x] **External Contributors**: CI/CD works for forks and external PRs
- [x] **Documentation Build**: MkDocs builds without errors

### 📦 Package Management
- [x] **pyproject.toml**: Properly configured with all metadata
- [x] **Version Management**: Semantic versioning strategy
- [x] **Build System**: Package builds correctly
- [x] **Distribution**: Both wheel and source distributions created

## 🚀 Release Process

### 1. Pre-Release Preparation

```bash
# Run comprehensive checks
python scripts/prepare-release.py --version 1.0.0

# Review and commit changes
git add .
git commit -m "Prepare release 1.0.0"
```

### 2. Repository Configuration

#### GitHub Repository Settings
1. **General Settings**:
   - ✅ Enable Issues, Wikis, Discussions
   - ✅ Configure default branch protection
   - ✅ Set up merge strategies

2. **Security Settings**:
   - ✅ Enable Dependabot alerts and updates
   - ✅ Enable secret scanning
   - ✅ Configure security advisories

3. **Pages Settings**:
   - ✅ Source: GitHub Actions
   - ✅ Custom domain (optional)
   - ✅ Enforce HTTPS

#### Branch Protection Rules
Configure for `main` branch:
- ✅ Require pull request reviews (1 reviewer)
- ✅ Require status checks:
  - `test` (all Python versions and platforms)
  - `lint` (code quality checks)
  - `security` (security scans)
  - `docs` (documentation build)
- ✅ Require branches to be up to date
- ✅ Include administrators
- ✅ Restrict force pushes and deletions

### 3. PyPI Setup

#### Trusted Publishing Configuration
1. **PyPI Account**:
   - Go to PyPI → Account Settings → Publishing
   - Add trusted publisher:
     - PyPI Project Name: `gopher-mcp`
     - Owner: `cameronrye`
     - Repository: `gopher-mcp`
     - Workflow: `release.yml`
     - Environment: `pypi`

2. **TestPyPI** (for testing):
   - Repeat above for TestPyPI
   - Environment: `testpypi`

### 4. Environment Setup

#### GitHub Environments
1. **Create `pypi` environment**:
   - Protection rules: Require reviewer
   - Deployment branches: Protected branches only

2. **Create `testpypi` environment**:
   - Protection rules: Require reviewer
   - Deployment branches: All branches

### 5. Release Execution

#### Create Release
```bash
# Create and push tag (triggers release workflow)
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

#### Monitor Release
1. **GitHub Actions**: Verify all workflows pass
2. **PyPI**: Confirm package is published
3. **Documentation**: Verify docs are deployed
4. **GitHub Release**: Check release notes and assets

## 🔍 Post-Release Verification

### Package Installation
```bash
# Test PyPI installation
pip install gopher-mcp

# Verify installation
gopher-mcp --help
```

### Documentation Access
- ✅ GitHub Pages site loads correctly
- ✅ All documentation links work
- ✅ API reference is complete
- ✅ Installation instructions are accurate

### Community Features
- ✅ Issue templates work correctly
- ✅ PR template appears for new PRs
- ✅ Discussions are enabled
- ✅ Security policy is accessible

## 📊 Success Metrics

### Technical Metrics
- ✅ All CI/CD workflows passing
- ✅ Test coverage > 80%
- ✅ Documentation builds without warnings
- ✅ Package installs successfully
- ✅ Security scans pass

### Community Metrics
- ✅ Clear contribution guidelines
- ✅ Responsive issue templates
- ✅ Professional README
- ✅ Comprehensive documentation
- ✅ Active maintenance signals

## 🛠️ Maintenance Tasks

### Regular Tasks (Weekly)
- Review and merge Dependabot PRs
- Monitor security alerts
- Review community contributions
- Update documentation as needed

### Periodic Tasks (Monthly)
- Review and update dependencies
- Analyze usage metrics
- Update documentation
- Plan feature roadmap

### Release Tasks (As Needed)
- Update version numbers
- Update changelog
- Create release notes
- Announce releases

## 🆘 Troubleshooting

### Common Issues

#### CI/CD Failures
- Check workflow logs in GitHub Actions
- Verify all required secrets are set
- Ensure branch protection rules are correct

#### PyPI Publishing Issues
- Verify trusted publishing is configured
- Check environment protection rules
- Ensure package metadata is correct

#### Documentation Issues
- Verify MkDocs configuration
- Check for broken links
- Ensure all files are included in navigation

### Getting Help
- Check GitHub Discussions
- Review existing issues
- Contact maintainers via issue tracker

## 📝 Notes

- This checklist should be updated as the project evolves
- All team members should be familiar with the release process
- Regular reviews of security and quality practices are essential
- Community feedback should be incorporated into future releases
