"""One version number, declared in one place.

`clawock_kcnyu.__version__` was a literal `"0.1.0"` that nothing compared
against `instances/kcnyu/pyproject.toml`. A second source of truth for a number
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

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _declared(pyproject: Path) -> str:
    return tomllib.loads(pyproject.read_text())["project"]["version"]


def test_the_two_distributions_ship_the_same_version():
    """They are released together from one tag, so a disagreement means one of
    them was bumped and the other forgotten."""
    public = _declared(ROOT / 'pyproject.toml')
    instance = _declared(ROOT / 'instances' / 'kcnyu' / 'pyproject.toml')
    assert public == instance, (
        f'clawock {public} but clawock-kcnyu {instance}; one bump was missed'
    )


def test_the_instance_version_is_not_restated_in_source():
    """The specific shape of the old bug: a literal that a bump does not reach."""
    source = (ROOT / 'instances' / 'kcnyu' / 'src' / 'clawock_kcnyu'
              / '__init__.py').read_text()
    declared = _declared(ROOT / 'instances' / 'kcnyu' / 'pyproject.toml')
    assert f'"{declared}"' not in source, (
        'the version is restated in __init__.py; read it from the installed '
        'distribution instead so a bump cannot leave it behind'
    )
    assert 'importlib.metadata' in source


def test_the_installed_module_reports_the_declared_version():
    """And when it IS installed, the two must actually agree — the assertion
    above only proves the literal is gone, not that the replacement works."""
    try:
        import clawock_kcnyu
    except ImportError:
        pytest.skip('clawock-kcnyu is not importable in this environment')
    if clawock_kcnyu.__version__ == '0.0.0+unknown':
        pytest.skip('running from a source tree, not an installed distribution')
    assert clawock_kcnyu.__version__ == _declared(
        ROOT / 'instances' / 'kcnyu' / 'pyproject.toml')


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


def test_the_dependency_pin_still_admits_the_current_version():
    """`clawock-kcnyu` depends on a range of `clawock`. A bump that leaves the
    range behind installs the wrong pair without failing anything."""
    data = tomllib.loads((ROOT / 'instances' / 'kcnyu' / 'pyproject.toml').read_text())
    pins = [d for d in data['project'].get('dependencies', []) if d.startswith('clawock')]
    assert pins, 'the instance must depend on the public package'

    public = _declared(ROOT / 'pyproject.toml')
    major_minor = '.'.join(public.split('.')[:2])
    for pin in pins:
        lower = pin.split('>=', 1)[1].split(',')[0] if '>=' in pin else None
        upper = pin.split('<', 1)[1] if '<' in pin else None
        if lower:
            assert tuple(int(p) for p in lower.split('.')) <= tuple(
                int(p) for p in public.split('.')), f'{pin} excludes {public}'
        if upper:
            assert major_minor < upper.rstrip(), f'{pin} excludes {public}'
