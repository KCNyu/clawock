"""Contracts for the cheap dashboard-only master-push validation lane."""
from pathlib import Path
import re

from workflow_contract_helpers import (
    assert_validator_step,
    case_patterns,
    push_paths,
    step_block,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'
HARNESS = WORKFLOWS / 'harness-regression.yml'
GATE = WORKFLOWS / 'dashboard-artifact-gate.yml'
DASHBOARD = 'assets/data/dashboard.json'
OVERVIEW = 'assets/data/overview.json'
CORE_OUTPUTS = [OVERVIEW, DASHBOARD]


def test_dashboard_commits_leave_the_heavy_master_push_lane():
    assert all(path not in push_paths(HARNESS) for path in CORE_OUTPUTS)
    harness = HARNESS.read_text(encoding='utf-8')
    assert re.search(r'^  pull_request:\s*$', harness, re.MULTILINE), (
        'required validate context must still report for every PR')
    assert all(path in case_patterns(HARNESS) for path in CORE_OUTPUTS), (
        'core projection changes in a PR must still run the full regression suite')


def test_dashboard_gate_is_master_only_and_path_exact():
    text = GATE.read_text(encoding='utf-8')
    trigger = text.split('on:', 1)[1].split('permissions:', 1)[0]
    assert 'branches: [master]' in trigger
    assert re.findall(r"^\s*-\s*'([^']+)'", trigger, re.MULTILINE) == CORE_OUTPUTS
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
    assert_validator_step(GATE, 'Validate committed dashboard payload', 'dashboard')
    assert 'continue-on-error' not in step_block(
        GATE, 'Validate committed dashboard payload')


def test_dashboard_gate_failure_is_visible_and_documented():
    for readme_name in ('README.md', 'README.zh.md'):
        readme = (ROOT / readme_name).read_text(encoding='utf-8')
        assert 'dashboard-artifact-gate.yml?label=DATA' in readme
        assert '/actions/workflows/dashboard-artifact-gate.yml' in readme
    tools = (ROOT / 'TOOLS.md').read_text(encoding='utf-8')
    assert '`dashboard-artifact-gate.yml`' in tools
