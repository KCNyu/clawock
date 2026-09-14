"""Publication contract for the off-host LLM weekly review workflow."""
from pathlib import Path

from workflow_contract_helpers import (
    assert_validator_step, step_block, step_run, steps, staged_paths)


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
    assert 'memory/weekly/${WEEK_ID}.md' in _step_run('Compose the commit target')
    # Moved to the clawock-commit composite (#806): exactly the reviewed week's
    # file, never the whole memory/weekly/ directory.
    assert staged == ['memory/weekly/${WEEK_ID}.md'], staged


def test_review_check_and_commit_name_the_one_resolved_week():
    """A backfill used to be impossible: the review, the check and the commit each
    computed "this week" on their own, so a Monday rerun of a failed Sunday would
    write, check and commit next week's file (2026-W37)."""
    names = [name for _, name in _steps()]
    assert names.index('Resolve the review week') < names.index('Run weekly review')
    resolve = _step_run('Resolve the review week')
    assert 'WEEK_ID=' in resolve and 'GITHUB_ENV' in resolve
    assert '--as-of "$AS_OF"' in _step_run('Run weekly review')
    assert 'WEEKLY_REVIEW_WEEK: ${{ env.WEEK_ID }}' in step_block(
        WORKFLOW, 'Validate generated review')
    assert 'date -u' not in _step_run('Compose the commit target')
