"""Publication contract for the sentiment sidecar workflow."""
import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'sentiment-scan.yml'


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
    assert "assert successful, 'sentiment snapshot has zero populated source results'" in validator_run

    commit_run = _step_run('Commit')
    publish_lines = [line.strip() for line in commit_run.splitlines()
                     if line.strip().startswith('bash scripts/data/gha_commit_push.sh')]
    assert len(publish_lines) == 1
    assert re.search(r'\sassets/data/sentiment\.json$', publish_lines[0])
    assert 'assets/data/' not in publish_lines[0].removesuffix('assets/data/sentiment.json')
