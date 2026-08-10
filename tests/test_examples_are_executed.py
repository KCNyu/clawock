"""An example nobody runs is documentation that lies on a schedule.

`examples/minimal-run/run.sh` is the acceptance check for #379 and the last
unchecked box of #420: a clean environment installs the wheel and finishes one
complete run with no checkout, no Git and no OpenClaw. It used to live inline in
`release.yml`, which proved the package worked for GitHub and for nobody else —
a reader could not execute it.

Moving it into a file only helps if the file is the one CI runs. These tests pin
that: the workflow must invoke the script, and the script must not quietly grow
a dependency on the checkout it exists to prove is unnecessary.
"""
import os
import re
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples' / 'minimal-run' / 'run.sh'
RELEASE = ROOT / '.github' / 'workflows' / 'release.yml'


def test_the_example_exists_and_is_executable():
    assert EXAMPLE.exists(), 'the blueprint lists examples/; this is the first one'
    mode = EXAMPLE.stat().st_mode
    assert mode & stat.S_IXUSR, 'a proof a reader cannot run is not a proof'


def test_the_release_workflow_runs_the_example_rather_than_its_own_copy():
    """The drift this whole change exists to prevent: CI running one copy while
    the file a reader runs slowly stops working."""
    workflow = RELEASE.read_text()
    assert 'examples/minimal-run/run.sh' in workflow, (
        'release.yml must invoke the example, not reimplement it')

    # And it must not have kept the inline version alongside it.
    isolated = workflow.split('Isolated install completes one real run', 1)[1]
    isolated = isolated.split('- uses:', 1)[0]
    assert 'clawock init' not in isolated, (
        'the inline copy is back; there must be exactly one set of steps')


def test_the_example_clears_the_environment_for_every_call():
    """`env -i` is the substance of the claim. Without it a pass can come from a
    variable the runner happens to export, which is exactly how "works on my
    box" survives to a user."""
    script = EXAMPLE.read_text()
    assert 'env -i' in script
    assert re.search(r'HOME="?\$\{?workdir', script), (
        'HOME must be redirected too, or the run reads the caller dotfiles')


def test_the_example_does_not_reach_back_into_the_repository():
    """It proves the package works *without* this checkout, so referring to the
    source tree would make the proof circular."""
    script = EXAMPLE.read_text()
    for forbidden in ('src/clawock', 'instances/', 'PYTHONPATH', 'pip install -e',
                      'git clone', '/root/'):
        assert forbidden not in script, f'{forbidden!r} makes the proof circular'


def test_the_example_installs_from_the_index_when_given_no_artifact():
    """The default path is what a stranger runs after #379 lands. CI passes the
    wheel under test instead, and both have to keep working."""
    script = EXAMPLE.read_text()
    assert 'pip" install --quiet clawock' in script or \
           'pip install --quiet clawock' in script, (
        'the no-argument path must install the published package')


def test_every_example_directory_is_listed_in_the_readme():
    """Keeps the index honest as examples are added — the same discovery rule the
    root allowlist applies one level up."""
    listed = (ROOT / 'examples' / 'README.md').read_text()
    present = sorted(p.name for p in (ROOT / 'examples').iterdir() if p.is_dir())
    assert present, 'no example directories found — this test would pass on an empty tree'
    for name in present:
        assert f'{name}/' in listed, f'examples/{name} is not in examples/README.md'


def test_examples_has_an_owner_in_the_root_allowlist():
    """`ops/system_check.py` raises a CRITICAL for any unexplained top-level
    path, so a new directory must arrive with its owner or it breaks the live
    health check."""
    import json

    entries = json.loads((ROOT / 'config' / 'root-allowlist.json').read_text())['entries']
    assert 'examples' in entries, 'a new root path must declare an owner'
    assert entries['examples']['owner'] and entries['examples']['consumer']
