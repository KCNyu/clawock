"""Invalid source fields degrade locally; publication keeps strict JSON."""
import json
from datetime import date

import pytest

from clawock import history_store
from clawock.decision import ledger, setups
from clawock.evidence.news_evidence_graph import normalize_timestamp
from clawock.harness import brief_postflight, report
from clawock.portfolio.guardrail import _holding_pnl_pct
from clawock.publish import artifacts, decision_map


@pytest.mark.parametrize('value', ['1e999', 'inf', float('inf'), float('nan')])
def test_plan_numeric_readers_refuse_nonfinite(value):
    assert ledger._int(value) is None
    assert ledger._float(value) is None


@pytest.mark.parametrize('value', [1763000000000, '1763000000000', '²²²²²²²²²', float('inf')])
def test_unusable_epoch_does_not_abort_news_evidence(value):
    assert normalize_timestamp(value) == {'iso': None, 'precision': 'unknown'}


def test_invalid_timestamp_can_still_use_an_explicit_fallback():
    assert normalize_timestamp(1e100, fallback='2026-01-02')['iso'].startswith('2026-01-02')
    assert normalize_timestamp(1763000000)['precision'] == 'second'


def test_guardrail_reads_numeric_cost_without_mutating_the_book():
    holding = {'ticker': 'X', 'shares': 10, 'cost_basis': '11.5', 'current_value': 100}
    assert _holding_pnl_pct(holding) == -13.0
    assert holding['cost_basis'] == '11.5'


def test_required_risk_section_is_a_hard_delivery_failure():
    body = '▎情绪面\nok\n▎技术面\nok\n▎操作建议\nok'
    ctx = dict(status='ok', raw_wechat_block='block', title='t', commit_msg='c',
               context_id='abc', needs_risk_section=True, anomalies=[])
    assert report.categorize(report.validate(body, ctx, body)) == 'fail'
    ctx['needs_risk_section'] = False
    assert report.categorize(report.validate(body, ctx, body)) == 'pass'


def test_jsonl_hot_and_cold_segments_sanitize_nonfinite(tmp_path):
    path = tmp_path / 'history.jsonl'
    history_store.write_series(path, [
        {'as_of': '2020-01-01', 'score': float('nan')},
        {'as_of': '2026-01-01', 'score': float('inf')},
    ], today=date(2026, 1, 1))
    assert [r['score'] for r in history_store.load_series(path)] == [None, None]
    for segment in (path, history_store.archive_path(path)):
        assert 'NaN' not in segment.read_text() and 'Infinity' not in segment.read_text()


def test_setup_history_sanitizes_nested_numbers(tmp_path, monkeypatch):
    path = tmp_path / 'setups.jsonl'
    monkeypatch.setattr(setups, 'HIST', path)
    setups.persist_history({'rows': {'ABC': {'current': 10, 'range_pos': float('nan')}}})
    assert json.loads(path.read_text())['rows']['ABC']['range_pos'] is None


def test_decision_map_encoding_keeps_valid_json_and_size_basis():
    assert json.loads(decision_map.encode({'rows': [float('nan')]})) == {'rows': [None]}


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity', '1e999'])
def test_companion_gate_rejects_invalid_json_numbers(tmp_path, monkeypatch, number):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'assets/data/shadow_portfolio.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version":1,"as_of":"2026-01-01T00:00:00Z",'
                    '"curves":{"x":' + number + '},"coverage":{}}')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'outputs': ['assets/data/shadow_portfolio.json']}))
    with pytest.raises(AssertionError, match='non-finite JSON number'):
        artifacts.validate_dashboard_companions(manifest)


def test_absent_or_unreadable_plan_cannot_pass_the_commit_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_postflight, 'WS', tmp_path)
    assert brief_postflight.log_decisions('2026-01-01') is False
    path = tmp_path / 'memory/2026-01-01-plan.json'
    path.parent.mkdir()
    path.write_text('{bad')
    assert brief_postflight.log_decisions('2026-01-01') is False
