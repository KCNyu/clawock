"""Publication contract for the influencer sidecar workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'influencer-scan.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


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
    assert "assert items, 'feed has zero populated items'" in validator_run
    assert 'for index, item in enumerate(items):' in validator_run
    assert "isinstance(author, str) and author.strip()" in validator_run
    assert "isinstance(text, str) and text.strip()" in validator_run
    assert "summary_lists = ('held_hits', 'new_ideas', 'sector_hits')" in validator_run
    assert "total >= len(items) > 0" in validator_run

    commit_run = _step_run('Commit + push')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash scripts/data/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/influencer_feed\.json$', publish_lines[0])
