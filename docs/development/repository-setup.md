# Repository Setup for Open Source Release

This document outlines the recommended repository settings and branch protection rules for the Gopher & Gemini MCP Server project.

## Branch Protection Rules

### Main Branch Protection

Configure the following settings for the `main` branch:

#### Required Status Checks

- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- Required checks (the context names come from the `name:` of each job in
  `.github/workflows/ci.yml`; keep them in step with that file):
  - `test` (Test Python 3.11 on ubuntu-latest)
  - `test` (Test Python 3.12 on ubuntu-latest)
  - `test` (Test Python 3.13 on ubuntu-latest)
  - `test` (Test Python 3.14 on ubuntu-latest)
  - `lint` (Lint, type check and package)
  - `security` (Security checks)
  - `minimum-versions` (Declared minimum dependencies)
  - `docker` (Build Docker image)
  - `docs` (Build documentation)

The `test` job runs a 12-way matrix — 3.11 through 3.14 on ubuntu, windows and
macos — so the four contexts above cover only the Linux leg. Add the
`windows-latest` and `macos-latest` contexts too if you want branch protection
to catch a platform-specific regression; the release gate below is what
currently catches one.

Two names to watch for when reviewing an existing configuration:

- `Lint and type check` was renamed to `Lint, type check and package` when the
  distribution build and `twine check` moved into that job.
- `Validate PR` / `Packaging` no longer exists. `.github/workflows/validate-pr.yml`
  was deleted and its work folded into `lint`, so a required check by either
  name will never report and must be removed.

#### The release gate

Branch protection is not the only thing that reads CI. `validate-release` in
`.github/workflows/release.yml` refuses a tag unless a **completed, successful
CI run exists for that exact commit**, polling for up to fifteen minutes so a
tag pushed straight behind its commit waits rather than false-failing. This
exists because `ci.yml` never triggers on tags and the release workflow's own
`test-and-build` job is a single ubuntu-latest/3.11 leg: without the gate, a
Windows- or macOS-only regression could publish to PyPI with a fully green
Release run. Push the tag at a commit whose CI matrix is green, or the release
stops before it validates anything else.

#### Pull Request Requirements

- ✅ Require a pull request before merging
- ✅ Require approvals: **1**
- ✅ Dismiss stale PR approvals when new commits are pushed
- ✅ Require review from code owners (when CODEOWNERS file is present)

#### Additional Restrictions

- ✅ Restrict pushes that create files larger than 100 MB
- Include administrators: **not in effect** — the `main` ruleset lists the
  `admin` repository role as a bypass actor with `bypass_mode: always`, so every
  rule in this section is advisory for the owner. That is deliberate for a
  single-maintainer repo, where the release flow pushes tags and the occasional
  docs commit straight to `main`; it does mean these rules catch a mistake
  rather than stop a determined push. Drop the bypass actor if a second
  maintainer joins
- ✅ Allow force pushes: **Disabled**
- ✅ Allow deletions: **Disabled**

## Repository Settings

### General Settings

#### Features

- ✅ Issues: **Enabled** — required: `security-audit.yml` files its findings as
  an issue, and has nowhere to report if this is off
- ✅ Sponsorships: **Enabled** (if applicable)
- ✅ Preserve this repository: **Enabled**
- Wikis: **Disabled** — documentation lives in `docs/` and is published to
  GitHub Pages, so a wiki would be a second, unversioned copy
- Discussions: **Disabled** — issues carry the traffic this project gets

#### Pull Requests

- ✅ Allow merge commits: **Enabled**
- ✅ Allow squash merging: **Enabled** (default)
- ✅ Allow rebase merging: **Enabled**
- ✅ Always suggest updating pull request branches: **Enabled**
- ✅ Allow auto-merge: **Enabled**
- ✅ Automatically delete head branches: **Enabled**

#### Checking this page against the repository

This page is a runbook, and a runbook drifts silently — every line above was
true when written and several had stopped being true within a few releases.
Each claim is one API call, so verify rather than assume:

```bash
# The Pull Requests settings above
gh api repos/cameronrye/gopher-mcp \
  --jq '{allow_update_branch, allow_auto_merge, delete_branch_on_merge,
         allow_squash_merge, allow_merge_commit, allow_rebase_merge}'

# Branch protection: a ruleset that exists but reads "disabled" enforces nothing
gh api repos/cameronrye/gopher-mcp/rulesets --jq '.[] | {name, enforcement}'
gh api repos/cameronrye/gopher-mcp/rulesets/8224458 \
  --jq '{enforcement, bypass_actors, rules: [.rules[].type]}'
```

### Security Settings

#### Security & Analysis

- ✅ Dependency graph: **Enabled**
- ✅ Dependabot alerts: **Enabled**
- ✅ Dependabot security updates: **Enabled**
- ✅ Dependabot version updates: **Enabled**
- ✅ Code scanning alerts: **Enabled**
- ✅ Secret scanning alerts: **Enabled**

#### Dependabot Configuration

`.github/dependabot.yml` is committed in the repository and covers three
ecosystems on a weekly (Monday) schedule: `uv` (Python dependencies, with minor
and patch updates grouped), `github-actions`, and `docker` (the `Dockerfile`
base image). Edit that file rather than reproducing it here.

The Python ecosystem must stay `uv`, not `pip`, and the file says why at
length: the `pip` ecosystem edits only the version ranges in `pyproject.toml`,
which are deliberately open floors, so it had almost nothing to propose — while
`uv.lock`, the file every CI job installs from with `uv sync --locked`, never
moved on a schedule at all. There is no `pre-commit` ecosystem, so the hook
revisions in `.pre-commit-config.yaml` are hand-maintained; refreshing them is a
step in the [release checklist](releasing.md#pre-release-checklist), which scopes
the update so the two revs that track `uv.lock` are not bumped out from under it.

#### Dependency advisories

Dependabot only runs weekly, so an advisory published mid-week would otherwise
go unnoticed until Monday. `pip-audit` therefore runs **advisory-only** in
`ci.yml`, `release.yml` and `publish.yml` — it annotates the run but never
fails it, so a new advisory against a pinned dependency cannot turn an
unrelated PR red or block a tag. The nightly
`.github/workflows/security-audit.yml` run is the blocking signal: it opens (or
updates) a single issue labelled `security-audit`, and closes it once the audit
is clean. Its `audit` job declares `issues: write` on the built-in
`GITHUB_TOKEN`, which is all it needs — **Issues** must stay enabled on the
repository for it to file anything.

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

None required.

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

1. **Dependabot**: Already built into GitHub
2. **GitHub Actions**: Built-in CI/CD

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
