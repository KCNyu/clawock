"""The artifact gate reads every manifest member of a dashboard generation."""
import json
from pathlib import Path

import pytest
from clawock.publish.artifacts import validate_dashboard_companions


@pytest.fixture
def generation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    names = ['dashboard', 'overview', 'decision_audit', 'shadow_portfolio', 'decision_trail']
    root = tmp_path / 'assets/data'
    root.mkdir(parents=True)
    manifest = tmp_path / 'outputs.json'
    manifest.write_text(json.dumps({'outputs': {f'assets/data/{n}.json': {} for n in names}}))
    stamp = '2026-10-03T12:00:00+08:00'
    payloads = {
        'decision_audit': {'schema_version': 1, 'as_of': stamp, 'episode_backtest': {'horizons': {'t1': {}}}, 'timing_diagnostic': {}},
        'shadow_portfolio': {'schema_version': 1, 'as_of': stamp, 'curves': {}, 'coverage': {}},
        'decision_trail': {'as_of': stamp, 'decision_traces': [], 'decision_trace_scope': {'fillsShown': 0}, 'plan_timeline': []},
    }
    for name, data in payloads.items():
        (root / f'{name}.json').write_text(json.dumps(data))
    return manifest


@pytest.mark.parametrize('name', ['decision_audit', 'shadow_portfolio', 'decision_trail'])
def test_empty_companion_is_rejected(generation, name):
    validate_dashboard_companions(generation)
    Path(f'assets/data/{name}.json').write_text('{}')
    with pytest.raises(AssertionError, match=name):
        validate_dashboard_companions(generation)


def test_explicit_shadow_failure_is_visible_and_allowed(generation):
    Path('assets/data/shadow_portfolio.json').write_text(json.dumps({'computed': False, 'error': 'bars unavailable'}))
    validate_dashboard_companions(generation)


def test_trace_count_must_reconcile(generation):
    path = Path('assets/data/decision_trail.json')
    data = json.loads(path.read_text())
    data['decision_trace_scope']['fillsShown'] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match='fillsShown'):
        validate_dashboard_companions(generation)
