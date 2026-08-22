"""Publication contract for the off-host LLM weekly review workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps, staged_paths


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

    staged = staged_paths(WORKFLOW, 'Commit + push')
    assert 'memory/weekly/$(date -u +%G-W%V).md' in _step_run('Compose the commit target')
    # Moved to the clawock-commit composite (#806): exactly this week's file,
    # never the whole memory/weekly/ directory.
    assert staged == ['memory/weekly/$(date -u +%G-W%V).md'], staged
