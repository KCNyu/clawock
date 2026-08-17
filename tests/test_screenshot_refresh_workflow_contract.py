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
    # The staged set is a contract: the two PNGs always, the GIF only on manual
    # dispatch, and exactly the README metrics files. No other `git add` may
    # creep in (this was relaxed to any(...) once and had to be pinned back).
    assert add_lines == [
        'git add -- site/assets/shadow-backtest.png site/assets/social-card.png',
        'git add -- site/assets/dashboard.gif',
        'git add README.zh.md README.md assets/data/readme_metrics.json',
    ], add_lines


def test_metrics_step_tolerates_only_the_no_change_exit_code():
    """refresh_readme_metrics.py exits 0 = changed / 1 = no change / 2 = error.

    A quiet week (exit 1) is normal and must not fail the workflow; any other
    failure must still fail the step loudly instead of being masked.
    """
    metrics_run = _step_run('Recompute README metrics')
    assert '|| [ $? -eq 1 ]' in metrics_run, metrics_run


def test_gif_is_validated_only_on_manual_dispatch_before_publish():
    names = [name for _, name in _steps()]
    assemble = 'Assemble tab-cycle GIF'
    validate = 'Validate tab-cycle GIF'
    commit = 'Commit if changed'
    assert names.index(assemble) < names.index(validate) < names.index(commit)

    validator_block = _step_block(validate)
    assert "if: github.event_name == 'workflow_dispatch'" in validator_block
    assert_validator_step(WORKFLOW, validate, 'gif')


def _refresh_module():
    """Load ops/growth/refresh_readme_metrics.py without installing it."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'ops' / 'growth' / 'refresh_readme_metrics.py'
    spec = importlib.util.spec_from_file_location('refresh_readme_metrics', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_earliest_stamp_accepts_decision_mind_conversation_rows():
    """A conversation row carries `decided_at`, never `created_at` (#718).

    `memory/decisions.jsonl` holds two row shapes. Decision Mind writes
    `schema_version: 0, source: "conversation"` rows stamped with `decided_at`.
    The metrics refresh used a bare `r["created_at"]`, so the first such row
    (2026-08-16) turned the nightly README workflow red with `KeyError` and
    kept it red. Reverting to a bare subscript must fail this test.
    """
    earliest = _refresh_module()._earliest_stamp
    plan_row = {'created_at': '2026-05-17T08:00:00+08:00'}
    conversation_row = {
        'schema_version': 0, 'source': 'conversation',
        'decided_at': '2026-08-16T14:30:50+08:00',
    }

    # The shape that broke it, alone and mixed in.
    assert earliest([conversation_row]) == '2026-08-16T14:30:50+08:00'
    assert earliest([plan_row, conversation_row]) == '2026-05-17T08:00:00+08:00'
    assert earliest([conversation_row, plan_row]) == '2026-05-17T08:00:00+08:00'

    # A future row shape with neither stamp degrades the metric, never the run.
    assert earliest([{'decision_id': 'x'}, plan_row]) == '2026-05-17T08:00:00+08:00'


def test_earliest_stamp_is_explicit_when_no_row_has_a_stamp():
    """An empty result must raise, not return '' for datetime.fromisoformat."""
    import pytest
    with pytest.raises(ValueError):
        _refresh_module()._earliest_stamp([{'decision_id': 'x'}])
