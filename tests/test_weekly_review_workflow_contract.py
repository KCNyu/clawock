"""Publication contract for the off-host LLM weekly review workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'weekly-review.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_weekly_review_is_validated_and_exactly_staged_before_publish():
    names = [name for _, name in _steps()]
    assert names.index('Run weekly review') < names.index('Validate generated review') < names.index('Commit + push')

    validator_block = _step_block('Validate generated review')
    validator_run = _step_run('Validate generated review')
    assert 'continue-on-error' not in validator_block
    assert "Path(f'memory/weekly/{week_id}.md')" in validator_run
    assert 'path.is_file()' in validator_run
    assert "metadata.get('layout') == 'default'" in validator_run
    assert "metadata.get('title') == f'周复盘 · {week_id}'" in validator_run
    assert 'len(body) >= 1000' in validator_run
    for section in ('本周净值', 'Brier', '风险演变', '下周关注'):
        assert section in validator_run
    assert "assert not missing, f'weekly review missing required sections: {missing}'" in validator_run
    assert '决策兑现' not in validator_run

    commit_run = _step_run('Commit + push')
    assert 'review_path="memory/weekly/$(date -u +%G-W%V).md"' in commit_run
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^\s*git add(?:\s|$)', line)]
    assert add_lines == ['git add -- "$review_path"']
    assert not re.search(r'(?m)^\s*git add\s+(?:--\s+)?memory/weekly/?\s*$', commit_run)
