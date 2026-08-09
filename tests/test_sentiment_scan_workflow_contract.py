"""Publication contract for the sentiment sidecar workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'sentiment-scan.yml'


def _steps():
    return steps(WORKFLOW)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_sentiment_snapshot_requires_coverage_before_exact_publish():
    names = [name for _, name in _steps()]
    assert names.index('Scan sentiment (Reddit + Google News)') < names.index('Validate sentiment coverage') < names.index('Commit')

    assert_validator_step(WORKFLOW, 'Validate sentiment coverage', 'sentiment')

    commit_run = _step_run('Commit')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash ops/publish/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/sentiment\.json$', publish_lines[0])
    assert 'assets/data/' not in publish_lines[0].removesuffix('assets/data/sentiment.json')
