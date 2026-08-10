"""One version number, declared in one place.

`clawock_kcnyu.__version__` was a literal `"0.1.0"` that nothing compared
against `instances/kcnyu/pyproject.toml`. A second source of truth for a number
that only ever changes at release time is a drift that waits: the first bump
after it was written would ship a package reporting the previous version, and
nothing would have said so. Found by bumping to 0.1.1 — the literal stayed
behind.

The public `clawock` package deliberately exposes no `__version__`; consumers
read `importlib.metadata`, which cannot disagree with what was installed.
"""
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
