"""Publication contract for the off-host LLM news digest workflow."""
import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'news-digest.yml'


def _steps():
    lines = WORKFLOW.read_text().splitlines()
    return [
        (i, line.strip().removeprefix('- name: '))
        for i, line in enumerate(lines)
        if line.lstrip().startswith('- name: ')
    ]


def _step_run(name):
    lines = WORKFLOW.read_text().splitlines()
    starts = [i for i, step_name in _steps() if step_name == name]
    assert starts, f'workflow step missing: {name}'
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].startswith(' ' * indent + '- ')),
        len(lines),
    )
    run_start = next(
        (i for i in range(start + 1, end) if lines[i].strip() == 'run: |'),
        None,
    )
    assert run_start is not None, f'{name} has no multiline run block'
    return textwrap.dedent('\n'.join(lines[run_start + 1:end]))


def test_news_digest_is_validated_before_publish():
    names = [name for _, name in _steps()]
    producer = names.index('Fetch news + LLM distill')
    validator = names.index('Validate generated digest')
    publisher = names.index('Commit + push')
    assert producer < validator < publisher, 'digest validator must run between generation and publish'

    workflow = WORKFLOW.read_text()
    validator_run = _step_run('Validate generated digest')
    assert 'continue-on-error' not in workflow.split('- name: Validate generated digest', 1)[1].split('- name:', 1)[0]
    assert "assets/data/us_news_digest.json" in validator_run
    assert 'json.load' in validator_run
    assert "data.get('digest_markdown')" in validator_run
    assert 'len(digest.strip()) >= 100' in validator_run
    assert "'### ' in digest" in validator_run

    commit_run = _step_run('Commit + push')
    assert 'git add assets/data/us_news_digest.json' in commit_run
    assert not re.search(r'(?m)^\s*git add\s+assets/data/?\s*$', commit_run)
