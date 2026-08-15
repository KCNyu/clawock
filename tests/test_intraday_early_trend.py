"""Intraday early-trend lane: the 08:00 candidate is re-evaluated on the open bar (#543).

The daily brief classifies `wait_pullback_rebreak` once on completed bars. A CRCL
pullback at 11:00 is therefore invisible to every 30-minute slot unless the
early-trend classifier is re-run intraday. The price view is the only input that
changes intraday; peer / information / policy are the daily payloads, reused.
"""
import json

from clawock.harness import intraday_preflight as P


def _wire(tmp_path, monkeypatch, *, residual=0.09, dispersion=0.03, peers=5,
          zscore=2.5, close=10.0, prior_high=9.0, leveraged_holdings=False,
          region='HK'):
    monkeypatch.setattr(P, 'WS', tmp_path)
    (tmp_path / 'assets' / 'data').mkdir(parents=True)
    (tmp_path / 'config').mkdir(parents=True)
    (tmp_path / 'assets' / 'data' / 'peer_residual.json').write_text(json.dumps({
        'live': {'CRCL': {
            'residual_blend_5d': residual,
            'peer_dispersion_5d': dispersion,
            'available_peer_count': peers,
        }},
    }))
    (tmp_path / 'assets' / 'data' / 'news_evidence_graph.json').write_text(
        json.dumps({'information_overlay': {'tickers': {}}, 'events': []}))
    (tmp_path / 'config' / 'add-alpha-policy.json').write_text(json.dumps({}))
    monkeypatch.setattr(
        P.quant_signals, 'universe_details',
        lambda errors=None: [{'label': 'CRCL', 'code': 'hkCRCL',
                              'region': region,
                              'source_holdings': ['CRCL']}],
    )
    monkeypatch.setattr(P.quant_signals, 'fetch_bars', lambda code, cnt: [])
    monkeypatch.setattr(P.quant_signals, 'compute_signals', lambda bars: {
        'close': close, 'prior_20d_high': prior_high, 'prior_5d_low': 8.0,
        'ma20': 9.0, 'chandelier_stop': 8.5, 'zscore20': zscore,
    })


def test_collect_reports_wait_pullback_rebreak_candidate(monkeypatch, tmp_path):
    """Breakout + peer leadership + overheated z => wait_pullback_rebreak."""
    _wire(tmp_path, monkeypatch)

    out = P.collect_early_trend_candidates('hk')

    assert [row['label'] for row in out['rows']] == ['CRCL']
    row = out['rows'][0]
    assert row['state'] == 'wait_pullback_rebreak'
    assert row['setup_id'] == 'early_trend:wait_pullback_rebreak'
    assert row['state_zh'] == '候选·等回踩再突破'


def test_collect_omits_names_without_a_breakout(monkeypatch, tmp_path):
    """A name under its prior 20d high is not a price candidate."""
    _wire(tmp_path, monkeypatch, close=8.5, prior_high=9.0)

    out = P.collect_early_trend_candidates('hk')

    assert out['rows'] == []


def test_collect_fails_soft_when_universe_is_unavailable(monkeypatch, tmp_path):
    """A broken portfolio/registry must return no candidates, not red the cron."""
    monkeypatch.setattr(P, 'WS', tmp_path)

    def boom(**kwargs):
        raise ValueError('no tencent symbol')
    monkeypatch.setattr(P.quant_signals, 'universe_details', boom)

    out = P.collect_early_trend_candidates('hk')
    assert out['rows'] == []
    assert out['errors'] == [{'label': None,
                              'error': 'ValueError: no tencent symbol'}]


def test_append_early_trend_section_is_additive():
    """No candidates => byte-identical block; a candidate adds exactly one section."""
    block = '🇭🇰 港股盯盘 | 08/14 15:30 HKT'

    assert P.append_early_trend_section(block, {'rows': []}) == block

    candidates = {'rows': [{
        'label': 'CRCL', 'setup_id': 'early_trend:wait_pullback_rebreak',
        'state': 'wait_pullback_rebreak', 'state_zh': '候选·等回踩再突破',
        'holdings': ['CRCL'], 'close': 10.0, 'prior_20d_high': 9.0,
    }]}
    rendered = P.append_early_trend_section(block, candidates)
    assert '🕯️ 早期趋势候选' in rendered
    assert '候选·等回踩再突破' in rendered
    assert '现价 10 / 前高 9' in rendered
