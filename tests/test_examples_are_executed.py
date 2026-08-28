"""An example nobody runs is documentation that lies on a schedule.

`examples/cli/minimal-run/run.sh` is the acceptance check for #379 and the last
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
EXAMPLE = ROOT / 'examples' / 'cli' / 'minimal-run' / 'run.sh'
# The same discipline one level up: the *workflow* run, which is what the README
# actually sells (#1111). minimal-run proves the base loop; this one proves the
# investment-decision contract travels inside the wheel.
WORKFLOW_EXAMPLE = ROOT / 'examples' / 'cli' / 'workflow-run' / 'run.sh'
ISOLATED = (EXAMPLE, WORKFLOW_EXAMPLE)
RELEASE = ROOT / '.github' / 'workflows' / 'release.yml'
CI = ROOT / '.github' / 'workflows' / 'ci.yml'


def test_the_example_exists_and_is_executable():
    for path in ISOLATED:
        assert path.exists(), f'{path} is referenced by CI and by the README'
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, 'a proof a reader cannot run is not a proof'


def test_the_release_workflow_runs_the_example_rather_than_its_own_copy():
    """The drift this whole change exists to prevent: CI running one copy while
    the file a reader runs slowly stops working."""
    workflow = RELEASE.read_text()
    assert 'examples/cli/minimal-run/run.sh' in workflow, (
        'release.yml must invoke the example, not reimplement it')

    # And it must not have kept the inline version alongside it.
    isolated = workflow.split('Isolated install completes one real run', 1)[1]
    isolated = isolated.split('- uses:', 1)[0]
    assert 'clawock init' not in isolated, (
        'the inline copy is back; there must be exactly one set of steps')


def test_the_foreign_workspace_example_is_run_on_every_pull_request():
    """A release-time-only proof is a proof about the tag, not about the change
    that breaks it. Both isolated scripts now run in ci.yml, and the
    workflow-run one runs on every PR — including a docs-only PR, because the
    claim it backs ("Run it on your own book") is a README claim."""
    workflow = CI.read_text()
    block = workflow.split('\n  portable-workflow:', 1)
    assert len(block) == 2, 'ci.yml must carry the portable-workflow job'
    job = block[1].split('\n  analyze:', 1)[0]
    assert 'examples/cli/workflow-run/run.sh' in job
    assert 'examples/cli/minimal-run/run.sh' in job, (
        'the release-time isolated run belongs on the PR that would break it')
    assert "github.event_name == 'pull_request'" in job, (
        'a docs-only PR must still face the claim it is editing')
    assert job.count('dist/*.whl') == 2, (
        'both scripts must run against the wheel this job just built, not '
        'against whatever PyPI is serving today')


def test_the_foreign_workspace_example_asserts_both_directions():
    """Publishing a valid decision only shows the pack ships. The assertion that
    carries the weight is the refusal: the contract gate firing from an
    installed wheel, in a directory that has never seen this repository."""
    script = WORKFLOW_EXAMPLE.read_text()
    assert 'workflow install investment-decision' in script
    assert "status'] == 'published'" in script
    assert "status'] == 'rejected'" in script
    for code in ('insufficient_opposing_evidence', 'unsupported_bear_case'):
        assert code in script, f'the refusal must name {code}'
    assert '$status" -ne 0' in script, (
        'a rejected publish must also exit non-zero, or a caller that only '
        'reads the exit code treats a refusal as a success')
    # The example artifact has to come out of the installed pack. Copying it
    # from the checkout would reintroduce exactly the dependency under test.
    assert '.agents/skills/investment-decision/assets/decision.example.json' in script


def test_the_example_clears_the_environment_for_every_call():
    """`env -i` is the substance of the claim. Without it a pass can come from a
    variable the runner happens to export, which is exactly how "works on my
    box" survives to a user."""
    for path in ISOLATED:
        script = path.read_text()
        assert 'env -i' in script, path
        assert re.search(r'HOME="?\$\{?workdir', script), (
            f'{path.name}: HOME must be redirected too, or the run reads the '
            'caller dotfiles')


def test_the_example_does_not_reach_back_into_the_repository():
    """It proves the package works *without* this checkout, so referring to the
    source tree would make the proof circular."""
    for path in ISOLATED:
        script = path.read_text()
        for forbidden in ('src/clawock', 'pip install -e', 'git clone', '/root/'):
            assert forbidden not in script, (
                f'{path.name}: {forbidden!r} makes the proof circular')
        # PYTHONPATH may be *named* (workflow-run asserts the import did not
        # come from one), but never set.
        assert not re.search(r'PYTHONPATH=', script), (
            f'{path.name}: setting PYTHONPATH makes the proof circular')


def test_the_example_installs_from_the_index_when_given_no_artifact():
    """The default path is what a stranger runs after #379 lands. CI passes the
    wheel under test instead, and both have to keep working."""
    for path in ISOLATED:
        script = path.read_text()
        assert 'pip" install --quiet clawock' in script or \
               'pip install --quiet clawock' in script, (
            f'{path.name}: the no-argument path must install the published package')


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
