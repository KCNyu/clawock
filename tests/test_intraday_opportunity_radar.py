"""Intraday opportunity radar: price-surface candidates visible every slot (#551).

The daily decision surface only says hold/cut/trim for held names. The radar
adds a price-surface view — breakthrough / wait-rebreak / near-breakout — so an
00100 that breaks its 20d high at 11:00 is visible at 11:30 instead of the next
morning. Radar rows are observations, never entry authorization.
"""
from clawock.harness import intraday_preflight as P


def _wire(tmp_path, monkeypatch, sig_rows):
    """One universe entry per sig row, controlled technical output."""
    monkeypatch.setattr(P, 'WS', tmp_path)
    universe = [
        {'label': label, 'code': f'hk{label}', 'region': 'HK',
         'source_holdings': [label]}
        for label in sig_rows
    ]
    monkeypatch.setattr(P.quant_signals, '_universe_details', lambda: universe)
    monkeypatch.setattr(P.quant_signals, 'fetch_bars', lambda code, cnt: [])

    def compute(bars, _row=iter(sig_rows.items())):
        return None

    def short_history(bars):
        return None
    # Each label maps to its own sig via closure over the dict
    def make_compute():
        def _c(bars):
            # fetch_bars returns [] — the label is recoverable from the universe
            # order; simpler: return the single configured sig per call order.
            return sigs.pop(0) if sigs else None
        return _c
    sigs = list(sig_rows.values())
    monkeypatch.setattr(P.quant_signals, 'compute_signals', make_compute())
    monkeypatch.setattr(P.quant_signals, 'compute_short_history_signals', short_history)
    return universe


def test_radar_classifies_breakout_wait_and_near(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {
        'BO':  {'close': 110.0, 'prior_20d_high': 100.0, 'zscore20': 1.0},
        'WB':  {'close': 110.0, 'prior_20d_high': 100.0, 'zscore20': 2.5},
        'NEAR': {'close': 98.0, 'prior_20d_high': 100.0, 'zscore20': 0.5},
        'FAR': {'close': 90.0, 'prior_20d_high': 100.0, 'zscore20': 0.5},
    })

    out = P.collect_opportunity_radar('hk')

    by_label = {row['label']: row for row in out['rows']}
    assert by_label['BO']['state'] == 'breakout'
    assert by_label['WB']['state'] == 'wait_rebreak'
    assert by_label['NEAR']['state'] == 'near_breakout'
    assert 'FAR' not in by_label
    # sorted by pct_from_high desc: BO/WB first, NEAR last
    assert out['rows'][0]['label'] in ('BO', 'WB')


def test_radar_fails_soft_when_universe_breaks(monkeypatch, tmp_path):
    monkeypatch.setattr(P, 'WS', tmp_path)

    def boom():
        raise ValueError('no tencent symbol')
    monkeypatch.setattr(P.quant_signals, '_universe_details', boom)

    assert P.collect_opportunity_radar('us') == {'rows': []}


def test_radar_section_is_additive():
    block = '🇭🇰 港股盯盘 | 08/14 15:30 HKT'

    assert P.append_opportunity_radar_section(block, {'rows': []}) == block

    radar = {'rows': [{
        'label': '00100', 'setup_id': 'opportunity:breakout',
        'state': 'breakout', 'state_zh': '机会·突破',
        'holdings': ['00100'], 'close': 390.0, 'prior_20d_high': 374.4,
        'pct_from_high': 4.2, 'zscore20': 1.9,
    }]}
    rendered = P.append_opportunity_radar_section(block, radar)
    assert '🎯 机会雷达' in rendered
    assert '机会·突破' in rendered
    assert '现价 390 / 前高 374.4' in rendered
    assert 'z 1.90' in rendered
