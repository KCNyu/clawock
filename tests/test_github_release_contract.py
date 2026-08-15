"""A PyPI version must leave a matching, honest first-party release page."""
from pathlib import Path

import pytest

from ops.publish.release_notes import changelog_section, release_notes


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_notes_use_only_the_matching_public_changelog_section():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = release_notes(text, "0.1.1")

    assert "https://pypi.org/project/clawock/0.1.1/" in notes
    assert "python -m pip install clawock==0.1.1" in notes
    assert "six broken images" in notes
    assert "https://github.com/KCNyu/clawock/pull/468" in notes
    assert "First release" not in notes
    assert "[Unreleased]" not in notes
    assert "compare/v0.1.1...HEAD" not in notes


@pytest.mark.parametrize("text", [
    "## [Unreleased]\nNothing yet.\n",
    "## [1.2.3]\none\n\n## [1.2.3]\ntwo\n",
    "## [1.2.3] — 2026-08-11\n\n## [1.2.2]\nolder\n",
])
def test_missing_ambiguous_or_empty_changelog_sections_fail(text):
    with pytest.raises(ValueError):
        changelog_section(text, "1.2.3")


def test_github_release_is_downstream_of_real_pypi_and_attaches_artifacts():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    release_job = workflow.split("\n  github-release:\n", 1)[1]

    # Both publishers must have accepted before the GitHub Release exists —
    # pinned exact, not `needs: publish`-or-anything (#607: it was relaxed once
    # and a regression to the PyPI-only dependency would not have failed).
    assert "needs: [publish, npm]" in release_job
    assert "if: startsWith(github.ref, 'refs/tags/v')" in release_job
    assert "contents: write" in release_job
    assert "ops/publish/release_notes.py" in release_job
    assert "actions/download-artifact" in release_job
    assert 'gh release create "$GITHUB_REF_NAME" dist/*' in release_job
    assert workflow.count("contents: write") == 1


def test_npm_version_bump_is_idempotent_in_both_publish_paths():
    """#617: `npm version <same>` exits non-zero; once package.json syncs to
    the tag version, the next release would fail both the npm job and the
    github-release pack step. Both paths must skip the bump when versions
    already match."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "already at" in workflow, workflow
    assert '"$current" != "$target"' in workflow

    script = (ROOT / "ops" / "publish" / "publish_dsh_plugin.sh").read_text(encoding="utf-8")
    assert '"$current" != "$version"' in script
    assert "skipping bump" in script
