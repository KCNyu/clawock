"""Publication contract for the weekly EOD CSV archive workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'eod-archive.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_eod_archive_requires_current_snapshot_coverage_before_publish():
    names = [name for _, name in _steps()]
    validate = 'Validate EOD archive coverage'
    assert names.index('Append week-end snapshot') < names.index(validate) < names.index('Commit')

    validator_block = _step_block(validate)
    validator_run = _step_run(validate)
    assert 'continue-on-error' not in validator_block
    assert "Path('memory/archive/eod-history.csv')" in validator_run
    assert 'csv.DictReader' in validator_run
    assert "'date', 'ticker', 'name', 'currency', 'shares', 'cost_basis'," in validator_run
    assert "'current_price', 'pnl_pct', 'current_value'," in validator_run
    assert "today_rows = [row for row in rows if row['date'] == snapshot_date]" in validator_run
    assert "assert today_rows, f'EOD archive has no rows for {snapshot_date}'" in validator_run
    assert "if not isinstance(ticker, str) or not ticker.strip():" in validator_run
    assert "f'ASSERTION FAILED: EOD archive {path}: malformed row {index} '" in validator_run
    assert "len(keys) == len(set(keys))" in validator_run
    assert "for field in ('shares', 'cost_basis', 'current_price', 'current_value'):" in validator_run
    assert "assert finite_number(row[field]) and float(row[field]) > 0" in validator_run
    assert "assert finite_number(row['pnl_pct'])" in validator_run

    append_run = _step_run('Append week-end snapshot')
    assert "fpath = 'memory/archive/eod-history.csv'" in append_run
    commit_run = _step_run('Commit')
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^\s*git add(?:\s|$)', line)]
    assert add_lines == ['git add memory/archive/']
