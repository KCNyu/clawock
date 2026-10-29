"""A delayed fallback must not re-fetch live data after a successful publication."""
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from workflow_contract_helpers import step_block, steps

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('skip_scan', ROOT / 'ops/ci/skip_completed_scan.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
NOW = datetime.fromisoformat('2026-10-29T01:18:13+00:00')


def macro(tmp_path, stamp='2026-10-28T23:20:21+00:00'):
    path = tmp_path / 'macro.json'
    path.write_text(json.dumps({'generated_at': stamp,
                               'dxy': {'price': 102.247, 'source': 'yahoo'}}))
    return path


def test_host_success_suppresses_both_late_legs_even_if_live_dxy_would_move(tmp_path):
    source = macro(tmp_path)
    for at in ('2026-10-29T01:13:48+00:00', '2026-10-29T01:18:13+00:00'):
        assert gate.should_skip(source, 'schedule', datetime.fromisoformat(at))[0]
    assert not gate.should_skip(source, 'workflow_dispatch', NOW)[0]


def test_first_fallback_success_suppresses_second_before_host_dispatch(tmp_path):
    source = macro(tmp_path, '2026-10-28T21:46:00+00:00')
    assert gate.should_skip(source, 'schedule',
                            datetime.fromisoformat('2026-10-28T21:56:00+00:00'))[0]
    assert not gate.should_skip(source, 'schedule',
                                datetime.fromisoformat('2026-10-29T21:46:00+00:00'))[0]


@pytest.mark.parametrize('stamp', ['2026-10-27T23:20:00+00:00',
                                    '2026-10-29T02:00:00+00:00',
                                    '2026-10-28T23:20:00', None, 'bad'])
def test_unusable_timestamp_does_not_block_recovery(tmp_path, stamp):
    assert not gate.should_skip(macro(tmp_path, stamp), 'schedule', NOW)[0]


@pytest.mark.parametrize('content', [None, '{', '[]', '{}',
                                    '{"generated_at":"2026-10-28T23:20:00Z"}'])
def test_missing_invalid_or_failed_coverage_does_not_block_retry(tmp_path, content):
    source = tmp_path / 'macro.json'
    if content is not None:
        source.write_text(content)
    assert not gate.should_skip(source, 'schedule', NOW)[0]


def test_sentiment_uses_existing_coverage_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('portfolio.json').write_text(json.dumps({'portfolios': {}}))
    source = Path('sentiment.json')
    source.write_text(json.dumps({'generated_at': '2026-10-28T23:23:00Z',
                                  'sources': ['Google News'], 'tickers': []}))
    assert gate.should_skip(source, 'schedule', NOW)[0]
    # A portfolio change requires coverage for the newly active ticker.
    Path('portfolio.json').write_text(json.dumps({'portfolios': {
        'us_stocks': {'holdings': [{'ticker': 'SPY', 'shares': 1}]}}}))
    assert not gate.should_skip(source, 'schedule', NOW)[0]



@pytest.mark.parametrize('kind', ['macro', 'sentiment'])
def test_queued_runs_read_latest_master_and_gate_every_side_effect(kind):
    path = ROOT / '.github/workflows' / f'{kind}-scan.yml'
    assert "ref: ${{ github.event_name == 'schedule' && 'master' || github.ref }}" in path.read_text()
    assert 'group: data-write' in path.read_text()
    names = [name for _, name in steps(path)]
    index = names.index('Check whether the fallback is still needed')
    for name in names[index + 1:]:
        assert "if: steps.cycle.outputs.skip != 'true'" in step_block(path, name)
    assert 'Fetch' in names[index + 1] or 'Scan' in names[index + 1]
