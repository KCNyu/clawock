"""Publication contract for the influencer sidecar workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'influencer-scan.yml'


def _steps():
    return steps(WORKFLOW)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_influencer_feed_requires_structural_coverage_before_exact_publish():
    names = [name for _, name in _steps()]
    fetch = 'Fetch Trump/Musk + LLM relevance filter'
    validate = 'Validate influencer coverage'
    assert names.index(fetch) < names.index(validate) < names.index('Commit + push')

    assert_validator_step(WORKFLOW, validate, 'influencer')

    commit_run = _step_run('Commit + push')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash ops/publish/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/influencer_feed\.json$', publish_lines[0])
