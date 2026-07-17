"""Publication contract for the sentiment sidecar workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'sentiment-scan.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_sentiment_snapshot_requires_coverage_before_exact_publish():
    names = [name for _, name in _steps()]
    assert names.index('Scan sentiment (Reddit + Google News)') < names.index('Validate sentiment coverage') < names.index('Commit')

    validator_block = _step_block('Validate sentiment coverage')
    validator_run = _step_run('Validate sentiment coverage')
    assert 'continue-on-error' not in validator_block
    assert "Path('assets/data/sentiment.json')" in validator_run
    assert 'json.loads' in validator_run
    assert "result_fields = ('reddit_posts', 'google_news_en', 'google_news_zh')" in validator_run
    assert 'mentions > 0' in validator_run
    assert "assert successful, 'snapshot has zero populated source results'" in validator_run

    commit_run = _step_run('Commit')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash scripts/data/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/sentiment\.json$', publish_lines[0])
    assert 'assets/data/' not in publish_lines[0].removesuffix('assets/data/sentiment.json')
