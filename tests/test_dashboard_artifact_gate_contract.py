"""Contracts for the cheap dashboard-only master-push validation lane."""
from pathlib import Path
import re
import sys

from workflow_contract_helpers import (
    assert_validator_step,
    push_paths,
    step_block,
    step_run,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'
CI = WORKFLOWS / 'ci.yml'
GATE = WORKFLOWS / 'dashboard-artifact-gate.yml'
DASHBOARD = 'assets/data/dashboard.json'
OVERVIEW = 'assets/data/overview.json'
CORE_OUTPUTS = [OVERVIEW, DASHBOARD]

sys.path.insert(0, str(ROOT / 'ops' / 'ci'))
import push_scope  # noqa: E402


def test_dashboard_commits_leave_the_heavy_master_push_lane():
    assert all(path not in push_paths(CI) for path in CORE_OUTPUTS)
    text = CI.read_text(encoding='utf-8')
    assert re.search(r'^  pull_request:\s*$', text, re.MULTILINE), (
        'required validate context must still report for every PR')
    assert all(path in push_scope.CODE_GLOBS for path in CORE_OUTPUTS), (
        'core projection changes in a PR must still run the full regression suite')


def test_dashboard_gate_fires_on_the_event_that_publishes_a_generation():
    """The gate triggered on `push: paths:` for the two core outputs. Those paths
    stopped appearing in a master push when #314 moved the outputs to the data
    branch, so that trigger would have fired never again — no red, no signal, a
    validation gate switched off by a change somewhere else entirely.

    It now shares the publisher's `repository_dispatch`, so it validates exactly
    the generations that reach the site, and it cannot silently stop firing
    without the site deploy stopping with it.
    """
    text = GATE.read_text(encoding='utf-8')
    block = text.split('on:', 1)[1].split('permissions:', 1)[0]
    trigger = '\n'.join(line for line in block.splitlines()
                        if not line.strip().startswith('#'))
    assert 'repository_dispatch:' in trigger
    assert 'types: [data-plane-published]' in trigger
    assert 'push:' not in trigger, (
        'the outputs are not committed; a push trigger could only be dead')
    assert 'pull_request:' not in trigger


def test_dashboard_gate_is_read_only_stdlib_validation():
    text = GATE.read_text(encoding='utf-8')
    assert 'contents: read' in text
    assert 'contents: write' not in text
    assert 'pip install' not in text
    assert 'actions/setup-python' not in text
    assert 'safe_push.sh' not in text
    assert 'gha_commit_push.sh' not in text
    assert 'CLAWOCK_PUBLISH_SSH_KEY' not in text
    assert step_run(GATE, 'Validate published dashboard payload') == (
        'PYTHONPATH=src python3 -m clawock validate-sidecar dashboard')
    assert 'continue-on-error' not in step_block(
        GATE, 'Validate published dashboard payload')
    # It must validate what was PUBLISHED. The checkout no longer carries the
    # payload, and a rebuild here would validate this runner's output rather than
    # the generation the site serves.
    assert 'fetch_data_plane.py' in text
    assert 'build_dashboard.py' not in text


def test_dashboard_gate_failure_is_visible_and_documented():
    for readme_name in ('README.md', 'README.zh.md'):
        readme = (ROOT / readme_name).read_text(encoding='utf-8')
        assert 'dashboard-artifact-gate.yml?label=DATA' in readme
        assert '/actions/workflows/dashboard-artifact-gate.yml' in readme
    tools = (ROOT / 'TOOLS.md').read_text(encoding='utf-8')
    assert '`dashboard-artifact-gate.yml`' in tools
