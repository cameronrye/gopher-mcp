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
    preparer = module.ReleasePreparation.__new__(module.ReleasePreparation)
    preparer.project_root = tmp_path
    return preparer


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
