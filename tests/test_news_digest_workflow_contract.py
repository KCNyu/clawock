"""Publication contract for the off-host LLM news digest workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps


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

    assert_validator_step(WORKFLOW, 'Validate generated digest', 'news-digest')

    commit_run = _step_run('Commit + push')
    assert 'git add assets/data/us_news_digest.json' in commit_run
    assert not re.search(r'(?m)^\s*git add\s+assets/data/?\s*$', commit_run)
