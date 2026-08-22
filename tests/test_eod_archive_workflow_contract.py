"""Publication contract for the weekly EOD CSV archive workflow."""
import re
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
