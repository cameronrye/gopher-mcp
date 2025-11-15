# Release Checklist

Use this checklist to ensure consistent, high-quality releases of the Gopher & Gemini MCP Server.

## Pre-Release Checklist

### Planning Phase

- [ ] **Version Planning**
  - [ ] Determine version number following [SemVer](https://semver.org/)
  - [ ] Identify if this is a major, minor, or patch release
  - [ ] Review breaking changes (for major releases)
  - [ ] Plan release timeline

- [ ] **Feature Freeze**
  - [ ] All planned features are complete
  - [ ] No new features will be added to this release
  - [ ] All feature branches are merged to main
  - [ ] Code review process is complete

### Quality Assurance

- [ ] **Code Quality**
  - [ ] All linting checks pass (`uv run ruff check .`)
  - [ ] Code formatting is consistent (`uv run ruff format --check .`)
  - [ ] Type checking passes (`uv run mypy src`)
  - [ ] No TODO/FIXME comments for critical issues

- [ ] **Testing**
  - [ ] All unit tests pass (`uv run pytest`)
  - [ ] Integration tests pass
  - [ ] Test coverage meets requirements (≥80%)
  - [ ] Manual testing of key features completed
  - [ ] Performance regression testing (if applicable)

- [ ] **Security**
  - [ ] Security scan passes (`uv run bandit -r src/`)
  - [ ] Dependency vulnerability scan passes (`uv run safety check`)
  - [ ] No known security vulnerabilities
  - [ ] Security-sensitive changes reviewed

### Documentation

- [ ] **Documentation Updates**
  - [ ] README.md is current
  - [ ] API documentation is updated
  - [ ] Installation instructions are accurate
  - [ ] Configuration examples are current
  - [ ] Breaking changes are documented

- [ ] **Changelog**
  - [ ] CHANGELOG.md updated with new version
  - [ ] All changes since last release are documented
  - [ ] Breaking changes are clearly marked
  - [ ] Migration guide provided (if needed)
  - [ ] Release date is set

### Technical Preparation

- [ ] **Version Management**
  - [ ] Version updated in `pyproject.toml`
  - [ ] Version matches planned release tag
  - [ ] All version references are consistent

- [ ] **Dependencies**
  - [ ] Dependencies are up to date
  - [ ] No conflicting dependency versions
  - [ ] Lock file is current (`uv.lock`)
  - [ ] Optional dependencies work correctly

- [ ] **Build System**
  - [ ] Package builds successfully (`uv build`)
  - [ ] Built packages pass validation (`twine check dist/*`)
  - [ ] Installation from built package works
  - [ ] Entry points function correctly

### Release Preparation

- [ ] **Environment Setup**
  - [ ] GitHub environments are configured
  - [ ] PyPI trusted publishing is set up
  - [ ] Required secrets are available
  - [ ] Deployment permissions are correct

- [ ] **Final Validation**
  - [ ] Run full validation script (`python scripts/validate-release.py`)
  - [ ] All CI checks pass on main branch
  - [ ] No pending pull requests that should be included
  - [ ] Release branch is clean and up to date

## Release Execution Checklist

### Tag Creation

- [ ] **Create Release Tag**
  - [ ] Ensure you're on the main branch
  - [ ] Create annotated tag: `git tag -a vX.Y.Z -m "Release version X.Y.Z"`
  - [ ] Verify tag is correct: `git show vX.Y.Z`
  - [ ] Push tag: `git push origin vX.Y.Z`

### Workflow Monitoring

- [ ] **Monitor Release Workflow**
  - [ ] Navigate to [GitHub Actions](https://github.com/cameronrye/gopher-mcp/actions)
  - [ ] Find the triggered release workflow
  - [ ] Monitor validation phase completion
  - [ ] Monitor test and build phase completion
  - [ ] Monitor GitHub release creation

- [ ] **Approve PyPI Deployment**
  - [ ] Wait for PyPI environment approval request
  - [ ] Review workflow results before approval
  - [ ] Approve PyPI deployment
  - [ ] Monitor PyPI publication completion

## Post-Release Checklist

### Verification

- [ ] **GitHub Release**
  - [ ] Visit [Releases page](https://github.com/cameronrye/gopher-mcp/releases)
  - [ ] Verify release is created with correct version
  - [ ] Check release notes are complete and accurate
  - [ ] Confirm artifacts are attached
  - [ ] Verify pre-release flag is correct

- [ ] **PyPI Publication**
  - [ ] Visit [PyPI project page](https://pypi.org/project/gopher-mcp/)
  - [ ] Confirm new version is available
  - [ ] Check package metadata is correct
  - [ ] Verify description renders properly
  - [ ] Confirm download links work

- [ ] **Installation Testing**
  - [ ] Test installation: `pip install gopher-mcp==X.Y.Z`
  - [ ] Test CLI functionality: `gopher-mcp --help`
  - [ ] Test import: `python -c "import gopher_mcp"`
  - [ ] Test basic functionality
  - [ ] Test on different platforms (if possible)

### Communication

- [ ] **Announcements**
  - [ ] Update project documentation
  - [ ] Notify team members
  - [ ] Update any external documentation
  - [ ] Consider social media announcement (if applicable)

- [ ] **Monitoring**
  - [ ] Monitor for installation issues
  - [ ] Watch for bug reports
  - [ ] Check download statistics
  - [ ] Monitor community feedback

### Post-Release Tasks

- [ ] **Repository Maintenance**
  - [ ] Update development version in pyproject.toml (if using dev versions)
  - [ ] Create milestone for next release
  - [ ] Update project roadmap
  - [ ] Close completed issues and milestones

- [ ] **Documentation**
  - [ ] Update documentation site
  - [ ] Refresh installation guides
  - [ ] Update version badges
  - [ ] Archive old documentation versions (if applicable)

## Emergency Procedures

### Release Cancellation

If you need to cancel a release in progress:

- [ ] **Immediate Actions**
  - [ ] Cancel running GitHub workflow
  - [ ] Delete the release tag: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`
  - [ ] Document the reason for cancellation

- [ ] **Follow-up**
  - [ ] Fix the issues that caused cancellation
  - [ ] Update version number if needed
  - [ ] Re-run pre-release checklist
  - [ ] Create new release when ready

### Release Rollback

If a release was published but has critical issues:

- [ ] **Immediate Response**
  - [ ] Assess severity of the issue
  - [ ] Yank problematic version from PyPI (if necessary)
  - [ ] Create GitHub issue documenting the problem
  - [ ] Notify users through appropriate channels

- [ ] **Hotfix Process**
  - [ ] Create hotfix branch from release tag
  - [ ] Implement minimal fix
  - [ ] Follow expedited release process for patch version
  - [ ] Update documentation with fix details

## Release Types

### Version Guidelines

- **Major Release (X.0.0)**
  - [ ] Breaking changes present
  - [ ] Migration guide provided
  - [ ] Extended testing period
  - [ ] Community notification

- **Minor Release (X.Y.0)**
  - [ ] New features added
  - [ ] Backward compatibility maintained
  - [ ] Feature documentation complete
  - [ ] Standard testing process

- **Patch Release (X.Y.Z)**
  - [ ] Bug fixes only
  - [ ] No new features
  - [ ] Minimal risk changes
  - [ ] Expedited process allowed

### Pre-Release Guidelines

- **Alpha (X.Y.Z-alpha.N)**
  - [ ] Early development version
  - [ ] Major features incomplete
  - [ ] Internal testing only
  - [ ] Frequent releases expected

- **Beta (X.Y.Z-beta.N)**
  - [ ] Feature complete
  - [ ] External testing welcome
  - [ ] API may still change
  - [ ] Documentation mostly complete

- **Release Candidate (X.Y.Z-rc.N)**
  - [ ] Production ready candidate
  - [ ] No new features
  - [ ] Final testing phase
  - [ ] Documentation complete

---

**Remember**: This checklist ensures quality and consistency. Don't skip steps, even for urgent releases. If you need to expedite a release, document which steps were modified and why.

**Last Updated**: 2025-01-18
**Version**: 1.0
