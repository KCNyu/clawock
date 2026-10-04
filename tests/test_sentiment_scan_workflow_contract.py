"""Publication contract for the sentiment sidecar workflow."""
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps, logical_commit_commands


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
    publish_lines = logical_commit_commands(commit_run)
    assert len(publish_lines) == 1
    tokens = publish_lines[0].split()
    data_paths = [t for t in tokens if t.startswith('assets/data/')]
    # This job commits exactly its own sidecar plus its dated snapshot
    # bucket (#936) — nothing else may ride along.
    assert data_paths == [
        'assets/data/sentiment.json',
        'assets/data/factor-snapshots/sentiment',
    ]
    names = [n for n in names]
    assert names.index('Snapshot point-in-time copy') == len(names) - 2
