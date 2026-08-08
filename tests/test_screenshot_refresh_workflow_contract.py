"""Publication contract for the generated dashboard screenshots workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'screenshot-refresh.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_screenshots_are_validated_and_exactly_staged_before_publish():
    names = [name for _, name in _steps()]
    generate = 'Capture win-rate chart + social card'
    validate = 'Validate screenshots'
    commit = 'Commit if changed'
    assert names.index(generate) < names.index(validate) < names.index(commit)

    assert_validator_step(WORKFLOW, validate, 'screenshots')

    commit_run = _step_run(commit)
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^git add(?:\s|$)', line.strip())]
    assert add_lines == [
        'git add -- site/assets/shadow-backtest.png site/assets/social-card.png',
        'git add -- site/assets/dashboard.gif',
    ]
    assert not re.search(r'(?m)^\s*git add\s+(?:--\s+)?assets/?\s*$', commit_run)


def test_gif_is_validated_only_on_manual_dispatch_before_publish():
    names = [name for _, name in _steps()]
    assemble = 'Assemble tab-cycle GIF'
    validate = 'Validate tab-cycle GIF'
    commit = 'Commit if changed'
    assert names.index(assemble) < names.index(validate) < names.index(commit)

    validator_block = _step_block(validate)
    assert "if: github.event_name == 'workflow_dispatch'" in validator_block
    assert_validator_step(WORKFLOW, validate, 'gif')
