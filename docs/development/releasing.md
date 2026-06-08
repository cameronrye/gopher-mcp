# Releasing

This guide is for maintainers cutting a new release of `gopher-mcp` to
[PyPI](https://pypi.org/project/gopher-mcp/). It covers the one-time publishing
setup, the per-release steps, and how to test a release safely.

The canonical repository is
[`cameronrye/gopher-mcp`](https://github.com/cameronrye/gopher-mcp).

## Overview

- **Semantic Versioning** — releases follow [SemVer](https://semver.org/)
  (`X.Y.Z`): MAJOR for incompatible changes, MINOR for backward-compatible
  features, PATCH for backward-compatible fixes.
- **Tags trigger publishing** — pushing a Git tag matching `v*` (e.g. `v0.4.0`)
  runs [`.github/workflows/release.yml`](https://github.com/cameronrye/gopher-mcp/blob/main/.github/workflows/release.yml),
  which validates, tests, builds, creates a GitHub Release, and publishes to
  PyPI. Nothing publishes without a tag.
- **Trusted Publishing (OIDC)** — uploads to PyPI use GitHub's OpenID Connect
  identity, so there are **no API tokens** to manage. Packages are also signed
  and attested via Sigstore.
- **Pre-releases** — tags like `v0.4.0-rc.1`, `-beta.1`, or `-alpha.1` are
  detected automatically, marked as a pre-release on GitHub, and published to
  PyPI as a pre-release (so `pip install gopher-mcp` won't pick them up by
  default).

!!! note "Approval gate"
    The final PyPI publish step runs in the protected `pypi` GitHub environment
    and pauses for a manual approval from a maintainer before uploading. The
    rest of the workflow (validation, tests, build, GitHub Release) runs
    automatically.

## One-time setup

Trusted publishing must be configured once on PyPI (and, optionally, TestPyPI)
before the first release can succeed. This is the only manual publishing
configuration required.

### PyPI

1. Sign in to [PyPI](https://pypi.org/) with an account that has two-factor
   authentication enabled.
2. Go to the project's **Publishing** settings (or **Your projects →
   gopher-mcp → Settings → Publishing**). For a brand-new project, add a
   *pending* trusted publisher under **Account → Publishing** so the first
   upload can register the name.
3. Add a GitHub Actions trusted publisher with these exact values:

    | Setting           | Value         |
    | ----------------- | ------------- |
    | Repository owner  | `cameronrye`  |
    | Repository name   | `gopher-mcp`  |
    | Workflow filename | `release.yml` |
    | Environment name  | `pypi`        |

These must match the workflow exactly — the `publish-pypi` job in
`release.yml` runs in the `pypi` environment with `id-token: write`.

### TestPyPI (optional, recommended)

Repeat the same steps on [TestPyPI](https://test.pypi.org/) to enable safe
upload tests via the manual publish workflow:

| Setting           | Value         |
| ----------------- | ------------- |
| Repository owner  | `cameronrye`  |
| Repository name   | `gopher-mcp`  |
| Workflow filename | `publish.yml` |
| Environment name  | `testpypi`    |

### GitHub environments

Both `pypi` and `testpypi` environments should exist in **Settings →
Environments** with **required reviewers** so deployments pause for approval.
The `pypi` environment should be restricted to protected branches.

## Release steps

### 1. Bump the version

The version string lives in three places, but only one is the source of truth:

| Location                                  | What to do                                                                 |
| ----------------------------------------- | -------------------------------------------------------------------------- |
| `pyproject.toml` (`version = "X.Y.Z"`)    | **Source of truth.** Update this. The release workflow checks the tag against it. |
| `uv.lock` (the `gopher-mcp` package entry)| Regenerate by running `uv lock` (or any `uv sync`) so the lockfile records the new version. |
| `src/gopher_mcp/__init__.py`              | **No action needed** — `__version__` is derived at runtime from the installed package metadata, not hardcoded. |

The helper script `scripts/prepare-release.py` automates the
`pyproject.toml` bump and a CHANGELOG entry, but **does not** update `uv.lock`
— run `uv lock` yourself after bumping:

```bash
# Update pyproject.toml + CHANGELOG, then run the full preparation checks.
# Prompts interactively before editing the version and before creating a tag.
uv run python scripts/prepare-release.py --version 0.5.0

# Re-sync the lockfile so uv.lock records the new project version.
uv lock
```

!!! warning "Keep `uv.lock` in sync"
    The lockfile's `gopher-mcp` entry can silently lag behind `pyproject.toml`.
    Always run `uv lock` after a version bump and commit the result, or the
    package version in the lockfile will be stale.

You can also bump everything manually: edit `version` in `pyproject.toml`, run
`uv lock`, and add the CHANGELOG entry by hand.

### 2. Update the CHANGELOG

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/). Move the
items under `## [Unreleased]` into a new dated section. The release workflow
**requires** a matching `## [X.Y.Z]` heading and uses that section as the
GitHub Release notes.

```markdown
## [Unreleased]

## [0.5.0] - 2026-06-15

### Added
- ...

### Fixed
- ...
```

`prepare-release.py` creates this section automatically from the `[Unreleased]`
content, but review it for accuracy.

### 3. Validate locally

Run the validation script to mirror what CI will check (tests with ≥85%
coverage, lint, format, type-check, security scans, package build, docs build,
and a functionality smoke test):

```bash
uv run python scripts/validate-release.py
```

Equivalent individual checks:

```bash
uv run task quality     # ruff lint + mypy + tests
uv build                # build wheel + sdist
uv run python -m twine check dist/*
```

### 4. Commit, tag, and push

```bash
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "Prepare release v0.5.0"
git push origin main
```

The tag **must** be created from a commit on `main` (the workflow rejects tags
that aren't reachable from `main`) and the version **must** match
`pyproject.toml`.

```bash
git tag -a v0.5.0 -m "Release version 0.5.0"
git show v0.5.0            # sanity-check the tag
git push origin v0.5.0     # this starts the release
```

!!! warning
    Pushing the `v*` tag starts the automated release immediately.

### 5. Watch, approve, and verify

1. Open the [Actions tab](https://github.com/cameronrye/gopher-mcp/actions) and
   follow the **Release** run. It proceeds through: validate → test & build →
   create GitHub Release → publish to PyPI.
2. When the `Publish to PyPI` job pauses for the `pypi` environment, review the
   prior steps and **approve the deployment**.
3. Verify the results:
    - [GitHub Releases](https://github.com/cameronrye/gopher-mcp/releases) — notes
      and attached artifacts (`.whl` + `.tar.gz`), pre-release flag correct.
    - [PyPI project page](https://pypi.org/project/gopher-mcp/) — new version
      present, metadata renders.
    - Installation:

      ```bash
      pip install gopher-mcp==0.5.0
      gopher-mcp --help
      python -c "import gopher_mcp; print(gopher_mcp.__version__)"
      ```

## Pre-release checklist

Work through this before tagging. (Most items are also enforced by CI, but
checking locally avoids a failed release run.)

- [ ] Decide the version number per SemVer (major / minor / patch).
- [ ] All intended PRs are merged to `main`; no pending work that belongs in the release.
- [ ] Lint and format pass: `uv run ruff check .` and `uv run ruff format --check .`.
- [ ] Type checking passes: `uv run mypy src`.
- [ ] Tests pass with coverage ≥85%: `uv run pytest`.
- [ ] Security scans pass: `uv run bandit -r src/` and `uv run pip-audit`.
- [ ] Docs build cleanly: `uv run mkdocs build --strict`.
- [ ] `README.md` and configuration examples reflect any new behavior.
- [ ] `CHANGELOG.md` has a complete, dated `## [X.Y.Z]` section; breaking changes and any migration notes are called out.
- [ ] `version` in `pyproject.toml` matches the tag you will create.
- [ ] `uv.lock` regenerated (`uv lock`) and committed.
- [ ] Package builds and installs: `uv build && uv run python -m twine check dist/*`.
- [ ] `scripts/validate-release.py` passes.
- [ ] Trusted publishing and the `pypi`/`testpypi` GitHub environments are configured (see [One-time setup](#one-time-setup)).

## Testing a release safely

You don't have to risk a real publish to exercise the pipeline.

### Pre-release tags (recommended)

A pre-release version runs the complete `release.yml` workflow end to end and
publishes to PyPI flagged as a pre-release — safe because `pip` won't install
it by default, and it can be yanked if needed.

```bash
git tag -a v0.5.0-rc.1 -m "Release candidate 0.5.0-rc.1"
git push origin v0.5.0-rc.1
```

Remember to set the matching pre-release version in `pyproject.toml` and add a
`## [0.5.0-rc.1]` CHANGELOG entry first, since the consistency and changelog
checks still apply.

### TestPyPI

The separate [`publish.yml`](https://github.com/cameronrye/gopher-mcp/blob/main/.github/workflows/publish.yml)
workflow exists for upload tests against TestPyPI. Trigger it manually:

1. **Actions → Publish to PyPI → Run workflow**.
2. Choose `testpypi` as the target.
3. Approve the `testpypi` environment and watch the upload succeed.

This validates building and OIDC publishing without touching production PyPI,
but it does **not** exercise the GitHub Release or tag-based flow.

### Local dry run

Fast feedback with no external side effects:

```bash
# Skip the long test phase while you iterate on packaging
uv run python scripts/prepare-release.py --version 0.5.0-test --skip-tests

uv run python scripts/validate-release.py
uv build && uv run python -m twine check dist/*
pip install dist/*.whl
```

## After a release

- Watch GitHub Issues and Discussions for installation or regression reports.
- Update any version badges or external references if applicable.
- Move newly merged changes under `## [Unreleased]` in the CHANGELOG as work
  continues toward the next version.

## Rollback and yanking

If a published release has a serious problem:

1. **Yank the bad version** on PyPI (project page → Manage → the release →
   *Yank*). Yanking hides it from new installs without breaking pins that
   already reference it — it does not delete the files.
2. **Ship a patch** (e.g. `v0.5.1`): branch the fix from the release tag, follow
   the normal release steps, and note the issue in the CHANGELOG.
3. **Document** the problem and resolution in a GitHub issue.

To abort a release that is still in flight:

```bash
# Cancel the running workflow in the Actions tab, then remove the tag
git tag -d v0.5.0
git push origin :refs/tags/v0.5.0
```

Once the underlying issue is fixed, re-run the normal release steps with a new
tag.
