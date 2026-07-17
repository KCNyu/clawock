"""Publication contract for the weekly EOD CSV archive workflow."""
import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'eod-archive.yml'


def _steps():
    lines = WORKFLOW.read_text().splitlines()
    return [
        (i, line.strip().removeprefix('- name: '))
        for i, line in enumerate(lines)
        if line.lstrip().startswith('- name: ')
    ]


def _step_block(name):
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, step_name in _steps() if step_name == name)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].startswith(' ' * indent + '- ')),
        len(lines),
    )
    return '\n'.join(lines[start:end])


def _step_run(name):
    block = _step_block(name).splitlines()
    run_start = next(i for i, line in enumerate(block) if line.strip() == 'run: |')
    return textwrap.dedent('\n'.join(block[run_start + 1:]))


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
    assert "len(keys) == len(set(keys))" in validator_run

    append_run = _step_run('Append week-end snapshot')
    assert "fpath = 'memory/archive/eod-history.csv'" in append_run
    commit_run = _step_run('Commit')
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^\s*git add(?:\s|$)', line)]
    assert add_lines == ['git add memory/archive/']
