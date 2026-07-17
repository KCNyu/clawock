"""Publication contract for the macro sidecar workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'macro-scan.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


def test_macro_snapshot_requires_coverage_before_exact_publish():
    names = [name for _, name in _steps()]
    assert names.index('Fetch macro') < names.index('Validate macro coverage') < names.index('Commit')

    validator_block = _step_block('Validate macro coverage')
    validator_run = _step_run('Validate macro coverage')
    assert 'continue-on-error' not in validator_block
    assert "Path('assets/data/macro.json')" in validator_run
    assert 'json.loads' in validator_run
    assert 'if generated.tzinfo is None:' in validator_run
    assert 'generated.replace(tzinfo=timezone.utc)' in validator_run
    assert 'generated.astimezone(timezone.utc)' in validator_run
    assert 'freshness_limit = timedelta(hours=18)' in validator_run
    assert 'assert age <= freshness_limit' in validator_run
    assert 'generated_at is stale:' in validator_run
    assert "quote_fields = ('vix', 'treasury_10y', 'dxy', 'hsi', 'hstech', 'spx', 'nasdaq')" in validator_run
    assert "quote_sources = ('stooq', 'tencent', 'yahoo')" in validator_run
    assert "data[field]['price'] > 0" in validator_run
    assert "data[field].get('source') in quote_sources" in validator_run
    assert "successful.append('fear_greed')" in validator_run
    assert "successful.append('fed_press')" in validator_run
    assert "assert successful, 'snapshot has zero successfully populated fields'" in validator_run

    commit_run = _step_run('Commit')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash scripts/data/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/macro\.json$', publish_lines[0])
    assert 'assets/data/' not in publish_lines[0].removesuffix('assets/data/macro.json')
