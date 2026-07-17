"""Publication contract for the off-host LLM weekly review workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'weekly-review.yml'


def _steps():
    return steps(WORKFLOW)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_weekly_review_is_validated_and_exactly_staged_before_publish():
    names = [name for _, name in _steps()]
    assert names.index('Run weekly review') < names.index('Validate generated review') < names.index('Commit + push')

    assert_validator_step(WORKFLOW, 'Validate generated review', 'weekly-review')

    commit_run = _step_run('Commit + push')
    assert 'review_path="memory/weekly/$(date -u +%G-W%V).md"' in commit_run
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^\s*git add(?:\s|$)', line)]
    assert add_lines == ['git add -- "$review_path"']
    assert not re.search(r'(?m)^\s*git add\s+(?:--\s+)?memory/weekly/?\s*$', commit_run)
