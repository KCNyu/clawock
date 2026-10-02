"""Publication contract for the weekly EOD CSV archive workflow."""
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps, staged_paths


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'eod-archive.yml'


def _steps():
    return steps(WORKFLOW)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_eod_archive_requires_current_snapshot_coverage_before_publish():
    names = [name for _, name in _steps()]
    validate = 'Validate EOD archive coverage'
    assert names.index('Append week-end snapshot') < names.index(validate) < names.index('Commit')

    assert_validator_step(WORKFLOW, validate, 'eod-archive')

    append_run = _step_run('Append week-end snapshot')
    assert "fpath = 'memory/archive/eod-history.csv'" in append_run
    # The step moved to the clawock-commit composite (#806); the contract is
    # unchanged — exactly this path, and only after the validator.
    assert staged_paths(WORKFLOW, 'Commit') == ['memory/archive/']


def test_a_late_scheduled_run_still_stamps_the_friday_it_was_scheduled_for():
    # #2279: two runs crossed midnight UTC and filed the week's close as a Saturday.
    from datetime import datetime, timezone

    from clawock.publish.artifacts import eod_snapshot_date

    friday = datetime(2026, 9, 25, 22, 30, tzinfo=timezone.utc)
    late = datetime(2026, 9, 26, 1, 10, tzinfo=timezone.utc)
    wednesday = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
    assert eod_snapshot_date(friday, 'schedule') == '2026-09-25'
    assert eod_snapshot_date(late, 'schedule') == '2026-09-25'
    assert eod_snapshot_date(wednesday, 'workflow_dispatch') == '2026-09-30'

    # Writer and validator read the same function, and neither reads the clock itself.
    append_run = _step_run('Append week-end snapshot')
    assert 'snapshot_date = eod_snapshot_date()' in append_run
    assert "'date': snapshot_date," in append_run
