"""One version number, declared in one place.

An adapter-local version was a literal `"0.1.0"` that nothing compared
against the root `pyproject.toml`. A second source of truth for a number
that only ever changes at release time is a drift that waits: the first bump
after it was written would ship a package reporting the previous version, and
nothing would have said so. Found by bumping to 0.1.1 — the literal stayed
behind.

The public `clawock` package deliberately exposes no `__version__`; consumers
read `importlib.metadata`, which cannot disagree with what was installed. The
CLI's `--version` reads the same place (`tests/test_version_flag.py`).

The changelog checks live here for the same reason: a version number and the
description of what it contains are one release decision, and separating them is
how a package ends up on PyPI announcing a version nobody wrote an entry for.
"""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _declared(pyproject: Path) -> str:
    return tomllib.loads(pyproject.read_text())["project"]["version"]


def _changelog_versions() -> list[str]:
    """Released versions, newest first. `[Unreleased]` is not one."""
    headings = re.findall(r'^## \[([^\]]+)\]', (ROOT / 'CHANGELOG.md').read_text(),
                          re.MULTILINE)
    return [h for h in headings if h.lower() != 'unreleased']


def test_the_changelog_describes_the_version_being_shipped():
    """A changelog nobody is required to update is a changelog that stops at the
    release someone last remembered.

    `docs/operations/release.md` already tells the releaser that a mismatched
    tag "publishes a version nobody asked for under a name the changelog already
    uses for something else" — written before there was a changelog to use. This
    is the check that sentence assumed: the newest entry has to be the version
    in `pyproject.toml`, so the entry gets written in the same PR as the bump
    rather than after the artifact is already on PyPI and unchangeable.
    """
    released = _changelog_versions()
    assert released, 'CHANGELOG.md lists no released version'
    declared = _declared(ROOT / 'pyproject.toml')
    assert released[0] == declared, (
        f'pyproject ships {declared} but the newest CHANGELOG entry is '
        f'{released[0]}; write the entry in the PR that bumps the version'
    )


def test_the_changelog_lists_each_version_once_newest_first():
    """Order and uniqueness are the two things a reader assumes without checking,
    which is what makes a silent duplicate or an out-of-order insert expensive."""
    released = _changelog_versions()
    assert len(released) == len(set(released)), f'duplicate entries: {released}'
    keys = [tuple(int(part) for part in v.split('.')) for v in released]
    assert keys == sorted(keys, reverse=True), f'not newest-first: {released}'


def test_the_changelog_is_reachable_from_the_package_metadata():
    """The file only does its job if PyPI links to it; a changelog nobody can
    find from the project page is a file in a repository."""
    urls = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['urls']
    assert 'Changelog' in urls, 'declare a Changelog URL so PyPI renders the link'
    assert urls['Changelog'].endswith('/CHANGELOG.md')
