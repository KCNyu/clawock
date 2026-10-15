"""Provider removal, price drift and missing metadata must never look like free admission."""
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pool_audit', ROOT / 'ops/host/agent-dispatch/audit-free-pool.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
MODEL = 'opencode/candidate-free'


def sources(cost=None):
    cost = {'input': 0, 'output': 0} if cost is None else cost
    return {'catalog': {MODEL: {'cost': cost}},
            'zen': {'data': [{'id': 'candidate-free', 'cost': cost}]},
            'prices': {'candidate-free': {'cost': cost}}}


@pytest.mark.parametrize('cost,expected', [
    (None, 'unknown'), ({}, 'unknown'), ({'input': 0}, 'unknown'),
    ({'input': False, 'output': 0}, 'unknown'),
    ({'input': 0, 'output': float('nan')}, 'unknown'),
    ({'input': -1, 'output': 0}, 'unknown'),
    ({'input': 0, 'output': 0, 'cache': {'read': 1}}, 'nonzero'),
    ({'input': 0, 'output': 0, 'cache': {'read': 0, 'write': 0}}, 'zero'),
])
def test_price_evidence_is_explicit(cost, expected):
    assert audit.cost_state(cost) == expected


def test_missing_zen_prices_cannot_be_replaced_by_zero_client_prices():
    s = sources()
    del s['zen']['data'][0]['cost']
    result = audit.assess([MODEL], s, set())
    assert not result['models'][0]['free_verified']
    assert result['models'][0]['catalog_cost'] == 'zero'
    assert result['issues'] == [f'{MODEL}: free status not verified']


def test_removal_and_price_drift_are_separate_from_source_failure():
    s = sources()
    s['zen']['data'] = [{'id': 'other-free'}]
    assert f'{MODEL}: missing from catalog' in audit.assess([MODEL], s, set())['issues']
    s = sources({'input': 1, 'output': 0})
    assert f'{MODEL}: nonzero cost' in audit.assess([MODEL], s, set())['issues']
    s = sources()
    del s['zen']
    row = audit.assess([MODEL], s, set())['models'][0]
    assert row['in_zen'] is None and not row['free_verified']


def test_discovery_keeps_retirement_and_does_not_claim_a_tool_probe():
    report = audit.assess([], sources(), {MODEL}, ['opencode/old-free'])
    assert report['added'] == [MODEL]
    assert report['removed'] == ['opencode/old-free']
    assert report['models'][0]['retired']
    assert report['models'][0]['tool_probe'] == 'not_run'


def test_cli_catalog_is_parsed_as_objects_not_brace_regex():
    value = {MODEL: {'cost': {'input': 0, 'output': 0}, 'name': 'brace } inside'}}
    assert audit.parse_catalog(MODEL + '\n' + json.dumps(value[MODEL]) + '\n') == value
    with pytest.raises(ValueError):
        audit.parse_catalog('')


def test_collect_keeps_independent_sources_when_opencode_hangs(monkeypatch):
    def hung(*args, **kwargs):
        raise subprocess.TimeoutExpired('opencode', 20)
    monkeypatch.setattr(audit.subprocess, 'run', hung)
    monkeypatch.setattr(audit, 'fetch_json', lambda url: sources()['zen'] if url == audit.ZEN
                        else {'opencode': {'models': sources()['prices']}})
    got, errors = audit.collect()
    assert set(got) == {'zen', 'prices'}
    assert errors == {'catalog': 'TimeoutExpired'}


def test_due_cache_pool_drift_failure_and_recovery(tmp_path, monkeypatch):
    pool = tmp_path / 'pool'
    repo = tmp_path / 'repo'
    report = tmp_path / 'report.json'
    pool.write_text(MODEL + '\n')
    repo.write_bytes(pool.read_bytes())
    monkeypatch.setattr('sys.argv', ['audit', '--due', '--pool', str(pool), '--repo-pool', str(repo),
                                    '--report', str(report)])
    calls = []
    def collect():
        calls.append(1)
        return sources(), {}
    monkeypatch.setattr(audit, 'collect', collect)
    assert audit.main() == 0
    assert audit.main() == 0 and len(calls) == 1
    repo.write_text(MODEL + '\n# changed\n')
    assert audit.main() == 2 and len(calls) == 2
    assert 'differ' in audit.read_report(report)['issues'][0]
    pool.write_bytes(repo.read_bytes())
    monkeypatch.setattr(audit, 'collect', lambda: ({}, {'catalog': 'TimeoutExpired'}))
    assert audit.main() == 2
    failed = audit.read_report(report)
    assert failed['last_catalog_names'] == [MODEL]
    assert failed['catalog_names'] is None
    monkeypatch.setattr(audit, 'collect', collect)
    monkeypatch.setattr(audit.time, 'time', lambda: failed['checked_at'] + audit.RETRY + 1)
    assert audit.main() == 0
    assert audit.read_report(report)['removed'] == []


def test_status_rejects_missing_stale_and_future_reports():
    now = time.time()
    assert audit.status({}, now) == 'stale'
    assert audit.status({'checked_at': now - audit.STALE - 1, 'status': 'ok'}, now) == 'stale'
    assert audit.status({'checked_at': now + 1, 'status': 'ok'}, now) == 'stale'


def test_supervisor_runs_audit_before_cooldown():
    text = (ROOT / 'ops/host/patrol.sh').read_text()
    loop = text.split('loop() {', 1)[1]
    assert loop.index('audit_free_pool') < loop.index('pool_cooldown_remaining')
    assert '--status --report "$STATE/free-pool-audit.json"' in text


def test_health_reads_audit_without_spawning_and_warns_on_stale(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('pool_health', ROOT / 'ops/system_check.py')
    health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health)
    pool = tmp_path / 'pool'
    pool.write_text(MODEL)
    report = tmp_path / 'audit.json'
    monkeypatch.setattr(health, 'FREE_POOL_INSTALLED', pool)
    monkeypatch.setattr(health, 'FREE_POOL_AUDIT', report)
    def forbidden(*args, **kwargs):
        raise AssertionError('health reader must not spawn')
    monkeypatch.setattr(health.subprocess, 'run', forbidden)
    result = health.Result()
    health.check_free_pool_audit(result)
    assert result.checks[0][1] == health.WARNING
    report.write_text(json.dumps({'checked_at': time.time(), 'status': 'attention',
                                 'issues': ['free status not verified'], 'source_errors': {}}))
    result = health.Result()
    health.check_free_pool_audit(result)
    assert result.checks[0][1:] == (health.WARNING, 'free status not verified')
    report.write_text(json.dumps({'checked_at': time.time() - audit.STALE - 1, 'status': 'ok',
                                 'issues': [], 'source_errors': {}}))
    result = health.Result()
    health.check_free_pool_audit(result)
    assert 'stale' in result.checks[0][2]

    report.write_text(json.dumps({'checked_at': time.time(), 'status': 'ok',
                                 'issues': [], 'source_errors': []}))
    result = health.Result()
    health.check_free_pool_audit(result)
    assert result.checks[0][1] == health.WARNING
