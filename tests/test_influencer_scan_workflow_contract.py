"""Publication contract for the influencer sidecar workflow."""
import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'influencer-scan.yml'


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


def test_influencer_feed_requires_populated_coverage_before_exact_publish():
    names = [name for _, name in _steps()]
    fetch = 'Fetch Trump/Musk + LLM relevance filter'
    validate = 'Validate influencer coverage'
    assert names.index(fetch) < names.index(validate) < names.index('Commit + push')

    validator_block = _step_block(validate)
    validator_run = _step_run(validate)
    assert 'continue-on-error' not in validator_block
    assert "Path('assets/data/influencer_feed.json')" in validator_run
    assert 'json.loads' in validator_run
    assert "assert items, 'influencer feed has zero populated items'" in validator_run
    assert "summary_lists = ('held_hits', 'new_ideas', 'sector_hits')" in validator_run
    assert "total >= len(items) > 0" in validator_run

    commit_run = _step_run('Commit + push')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash scripts/data/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/influencer_feed\.json$', publish_lines[0])

