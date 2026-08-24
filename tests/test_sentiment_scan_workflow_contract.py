"""Publication contract for the sentiment sidecar workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import assert_validator_step, step_run, steps


ROOT = Path(__file__).resolve().parents[1]


def _logical_commit_command(commit_run):
    """Join backslash continuations so multi-path gha_commit_push calls read
    as one logical command (the snapshots slice added a second data path)."""
    logical, buf = [], ""
    for raw in commit_run.splitlines():
        line = raw.strip()
        if not line:
            continue
        buf = f"{buf} {line}".strip() if buf else line
        if buf.endswith("\\"):
            buf = buf[:-1].rstrip()
            continue
        logical.append(buf)
        buf = ""
    if buf:
        logical.append(buf)
    return [l for l in logical if l.startswith("bash ops/publish/gha_commit_push.sh")]
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
    publish_lines = _logical_commit_command(commit_run)
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
