"""Publication contract for the off-host LLM weekly review workflow."""
import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'weekly-review.yml'


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
    assert '决策兑现' not in validator_run

    commit_run = _step_run('Commit + push')
    assert 'review_path="memory/weekly/$(date -u +%G-W%V).md"' in commit_run
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^\s*git add(?:\s|$)', line)]
    assert add_lines == ['git add -- "$review_path"']
    assert not re.search(r'(?m)^\s*git add\s+(?:--\s+)?memory/weekly/?\s*$', commit_run)
