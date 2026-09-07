"""Tests for the release helper in ``scripts/``.

``scripts/`` is outside the coverage target and had no tests at all, which is
survivable for most of it -- a release script fails loudly, in front of a human,
before anything is published. The exception is version bumping: every place the
version is written has to move together, and a place that is silently left
behind does not fail the run. It produces a manifest that disagrees with the tag,
and the disagreement is only caught later (or, for the container tag, published).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_prepare_release():
    """Import ``scripts/prepare-release.py``, whose name is not an identifier."""
    path = PROJECT_ROOT / "scripts" / "prepare-release.py"
    spec = importlib.util.spec_from_file_location("prepare_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["prepare_release"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prep(tmp_path):
    """A preparer pointed at a throwaway copy of the two files it rewrites."""
    module = _load_prepare_release()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "gopher-mcp"\nversion = "0.9.0"\n\n'
        '[tool.ruff]\ntarget-version = "py311"\n'
    )
    (tmp_path / "server.json").write_text(
        json.dumps(
            {
                "name": "io.github.cameronrye/gopher-mcp",
                "version": "0.9.0",
                "packages": [
                    {
                        "registryType": "pypi",
                        "identifier": "gopher-mcp",
                        "version": "0.9.0",
                    },
                    {
                        "registryType": "oci",
                        "identifier": "ghcr.io/cameronrye/gopher-mcp:0.9.0",
                    },
                ],
            },
            indent=2,
        )
        + "\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_BEFORE)
    preparer = module.ReleasePreparation.__new__(module.ReleasePreparation)
    preparer.project_root = tmp_path
    preparer.errors = []
    preparer.warnings = []
    return preparer


_COMPARE = "https://github.com/cameronrye/gopher-mcp/compare"

CHANGELOG_BEFORE = f"""# Changelog

## [Unreleased]

### Fixed

- Something worth releasing.

## [0.9.0] - 2026-01-01

### Added

- The previous release.

[Unreleased]: {_COMPARE}/v0.9.0...HEAD
[0.9.0]: {_COMPARE}/v0.8.0...v0.9.0
"""


class TestVersionBumpReachesEveryVersion:
    """Every version in the manifest must move, including the ones in a tag."""

    def test_the_oci_image_tag_is_bumped(self, prep, tmp_path):
        """The container tag is a version that lives inside an identifier.

        The MCP registry forbids a `version` key on an OCI package -- the tag in
        `identifier` IS the version -- so a bumper that only rewrites `version`
        keys leaves it pointing at the previous release. That does not fail
        loudly: publish-image pushes the new tag, publish-registry verifies the
        stale one, finds a real image from the last release, and publishes a
        registry entry telling clients to pull the wrong container.
        """
        prep._update_version("0.9.1")

        data = json.loads((tmp_path / "server.json").read_text())
        oci = next(p for p in data["packages"] if p["registryType"] == "oci")
        assert oci["identifier"] == "ghcr.io/cameronrye/gopher-mcp:0.9.1"

    def test_the_top_level_and_pypi_versions_are_bumped(self, prep, tmp_path):
        """The two that already worked, pinned so the fix does not break them."""
        prep._update_version("0.9.1")

        data = json.loads((tmp_path / "server.json").read_text())
        assert data["version"] == "0.9.1"
        pypi = next(p for p in data["packages"] if p["registryType"] == "pypi")
        assert pypi["version"] == "0.9.1"

    def test_an_oci_package_keeps_having_no_version_key(self, prep, tmp_path):
        """Bumping must not "helpfully" add the key the registry rejects."""
        prep._update_version("0.9.1")

        data = json.loads((tmp_path / "server.json").read_text())
        oci = next(p for p in data["packages"] if p["registryType"] == "oci")
        assert "version" not in oci

    def test_only_the_project_version_moves_in_pyproject(self, prep, tmp_path):
        """An unanchored match would clobber target-version and friends."""
        prep._update_version("0.9.1")

        content = (tmp_path / "pyproject.toml").read_text()
        assert 'version = "0.9.1"' in content
        assert 'target-version = "py311"' in content


class TestChangelogLinksFollowTheRelease:
    """The compare links at the foot of the changelog must move with the bump.

    ``_update_changelog`` promoted the ``[Unreleased]`` section into a dated one
    but left the link definitions untouched, so every release shipped with
    ``[Unreleased]`` still comparing against the PREVIOUS tag and no link at all
    for the version just cut. Markdown renders an undefined reference as literal
    text, so the new heading came out as a bare ``[0.10.1]`` on the GitHub
    release page and the docs site -- and the repo's history carries at least two
    commits doing this fix up by hand afterwards.
    """

    def test_the_unreleased_link_moves_to_the_new_tag(self, prep, tmp_path):
        prep._update_changelog("0.9.1")

        content = (tmp_path / "CHANGELOG.md").read_text()
        assert f"[Unreleased]: {_COMPARE}/v0.9.1...HEAD" in content
        assert f"[Unreleased]: {_COMPARE}/v0.9.0...HEAD" not in content

    def test_the_new_release_gets_its_own_compare_link(self, prep, tmp_path):
        """Spanning the previous tag to this one -- the range the section covers."""
        prep._update_changelog("0.9.1")

        content = (tmp_path / "CHANGELOG.md").read_text()
        assert f"[0.9.1]: {_COMPARE}/v0.9.0...v0.9.1" in content

    def test_the_new_link_sits_directly_below_unreleased(self, prep, tmp_path):
        """The block is newest-first, matching the sections above it."""
        prep._update_changelog("0.9.1")

        lines = (tmp_path / "CHANGELOG.md").read_text().splitlines()
        keys = [ln.split(":")[0] for ln in lines if ln.startswith("[")]
        assert keys == ["[Unreleased]", "[0.9.1]", "[0.9.0]"]

    def test_the_promoted_section_keeps_its_content(self, prep, tmp_path):
        """The links are a side effect; the promotion still has to work."""
        prep._update_changelog("0.9.1")

        content = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [0.9.1] - " in content
        assert "- Something worth releasing." in content
        # The old section survives untouched below the new one.
        assert "## [0.9.0] - 2026-01-01" in content

    def test_no_blank_line_is_left_under_the_unreleased_heading(self, prep, tmp_path):
        """A promoted section used to land two blank lines below ``[Unreleased]``,
        which every release then had to tidy by hand before committing."""
        prep._update_changelog("0.9.1")

        content = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [Unreleased]\n\n## [0.9.1]" in content

    def test_a_changelog_without_links_is_warned_about_not_crashed(
        self, prep, tmp_path
    ):
        """Not every changelog carries a link block, and a release must not die
        on its absence -- the sections are the content, the links are polish."""
        (tmp_path / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n- Something.\n"
        )

        prep._update_changelog("0.9.1")

        content = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [0.9.1] - " in content
        assert any("link" in w.lower() for w in prep.warnings)

    def test_rerunning_does_not_duplicate_the_link(self, prep, tmp_path):
        """`_update_changelog` returns early when the section already exists;
        the links must not be appended a second time by a repeated run."""
        prep._update_changelog("0.9.1")
        prep._update_changelog("0.9.1")

        content = (tmp_path / "CHANGELOG.md").read_text()
        assert content.count(f"[0.9.1]: {_COMPARE}") == 1
