"""Executable mutation tests for hardened workflow validators."""
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from workflow_contract_helpers import step_run, strip_hash_comments


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'

JSON_VALIDATORS = (
    ('macro-scan.yml', 'Validate macro coverage', 'assets/data/macro.json', 'macro snapshot'),
    ('sentiment-scan.yml', 'Validate sentiment coverage', 'assets/data/sentiment.json', 'sentiment snapshot'),
    ('influencer-scan.yml', 'Validate influencer coverage', 'assets/data/influencer_feed.json', 'influencer feed'),
    ('news-digest.yml', 'Validate generated digest', 'assets/data/us_news_digest.json', 'news digest'),
)


def run_validator(tmp_path: Path, workflow: str, step: str, artifact: str, content: bytes):
    artifact_path = tmp_path / artifact
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(content)
    run = step_run(WORKFLOWS / workflow, step)
    return subprocess.run(
        ['bash', '-eu', '-o', 'pipefail', '-c', run],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize('workflow,step,artifact,label', JSON_VALIDATORS)
@pytest.mark.parametrize(
    'content,problem',
    ((b'', 'file is empty'), (b'[]', 'top-level JSON must be an object'),
     (b'\xff\xfe', 'file is not valid UTF-8')),
)
def test_malformed_json_artifacts_fail_clearly_without_traceback(
        tmp_path, workflow, step, artifact, label, content, problem):
    result = run_validator(tmp_path, workflow, step, artifact, content)

    assert result.returncode != 0
    assert f'ASSERTION FAILED: {label} {artifact}:' in result.stderr
    assert problem in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('invalid_count', ('1', None))
def test_news_counts_reject_non_integer_before_sum(tmp_path, invalid_count):
    payload = {
        'generated_at': '2026-07-17T00:00:00+00:00',
        'tickers': ['AAPL'],
        'raw_news_counts': {'AAPL': invalid_count},
        'digest_markdown': '### AAPL\n' + 'x' * 120,
    }
    result = run_validator(
        tmp_path, 'news-digest.yml', 'Validate generated digest',
        'assets/data/us_news_digest.json', json.dumps(payload).encode(),
    )

    assert result.returncode != 0
    assert 'raw_news_counts values must be integers' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('field,value', (('author', None), ('author', 7),
                                         ('text', None), ('text', 7)))
def test_influencer_items_require_real_nonempty_strings(tmp_path, field, value):
    item = {'author': 'Trump', 'text': 'market statement', 'relevance': 0.5}
    item[field] = value
    payload = {
        'generated_at': '2026-07-17T00:00:00+00:00',
        'items': [item],
        'counts': {'held_hits': 0, 'new_ideas': 0, 'sector_hits': 0, 'total': 1},
        'held_hits': [], 'new_ideas': [], 'sector_hits': [],
    }
    result = run_validator(
        tmp_path, 'influencer-scan.yml', 'Validate influencer coverage',
        'assets/data/influencer_feed.json', json.dumps(payload).encode(),
    )

    assert result.returncode != 0
    assert f'item 0 missing {field}' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize(
    'quote',
    ({'price': 0, 'source': 'yahoo'}, {'price': 1, 'source': 'placeholder'}),
)
def test_macro_quote_failure_markers_do_not_count_as_coverage(tmp_path, quote):
    payload = {
        'generated_at': '2026-07-17T00:00:00+00:00',
        'vix': quote,
        'fear_greed': None,
        'fed_press': None,
    }
    result = run_validator(
        tmp_path, 'macro-scan.yml', 'Validate macro coverage',
        'assets/data/macro.json', json.dumps(payload).encode(),
    )

    assert result.returncode != 0
    assert 'snapshot has zero successfully populated fields' in result.stderr


def test_eod_short_row_reports_malformed_ticker(tmp_path):
    artifact = 'memory/archive/eod-history.csv'
    header = (
        'date,ticker,name,currency,shares,cost_basis,current_price,pnl_pct,current_value\n'
    )
    result = run_validator(
        tmp_path, 'eod-archive.yml', 'Validate EOD archive coverage', artifact,
        (header + f'{date.today()}\n').encode(),
    )

    assert result.returncode != 0
    assert f'ASSERTION FAILED: EOD archive {artifact}: malformed row 1' in result.stderr
    assert 'ticker missing' in result.stderr
    assert 'Traceback' not in result.stderr


def test_run_extraction_removes_comments_but_keeps_quoted_hashes():
    run = strip_hash_comments(
        "assert successful  # executable assertion\n"
        "# assert not missing\n"
        "assert '### ' in digest\n"
    )

    assert 'executable assertion' not in run
    assert 'assert not missing' not in run
    assert "assert '### ' in digest" in run
