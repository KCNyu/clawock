"""Publication contract for the off-host LLM news digest workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'news-digest.yml'


def _steps():
    return steps(WORKFLOW)


def _step_run(name):
    return step_run(WORKFLOW, name)


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
    assert 'json.loads' in validator_run
    assert 'if generated.tzinfo is None:' in validator_run
    assert 'generated.replace(tzinfo=timezone.utc)' in validator_run
    assert 'generated.astimezone(timezone.utc)' in validator_run
    assert 'freshness_limit = timedelta(hours=18)' in validator_run
    assert 'assert age <= freshness_limit' in validator_run
    assert 'generated_at is stale:' in validator_run
    assert "data.get('digest_markdown')" in validator_run
    assert "assert isinstance(counts, dict), 'raw_news_counts must be an object'" in validator_run
    assert 'invalid_counts = [key for key, value in counts.items()' in validator_run
    assert 'total_news = sum(counts.values())' in validator_run
    assert 'len(digest.strip()) >= 100' in validator_run
    assert "'### ' in digest" in validator_run

    commit_run = _step_run('Commit + push')
    assert 'git add assets/data/us_news_digest.json' in commit_run
    assert not re.search(r'(?m)^\s*git add\s+assets/data/?\s*$', commit_run)
