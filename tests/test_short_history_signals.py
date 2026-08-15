"""Short-history (20–29 bar) view boundaries and the listing-date gate (#608).

The mature 30-bar gate is a deliberate data-quality threshold. The short view
exists only for genuinely-new listings — a partial-feed mature name must stay
on the strict gate, or it enters the universe with half a signal set.
"""
import json
from datetime import date, timedelta

from clawock.decision import signals


def _bars(n, start='2026-07-10'):
    """n synthetic daily bars (calendar-day steps; fine for these computations)."""
    rows = []
    d = date.fromisoformat(start)
    for i in range(n):
        dt = d + timedelta(days=i)
        rows.append({
            'date': dt.isoformat(),
            'open': 10.0,
            'high': 11.0 + (i % 2) * 0.1,
            'low': 9.0 - (i % 2) * 0.1,
            'close': 10.0 + (i % 5) * 0.2,
        })
    return rows


def test_short_view_boundaries():
    """19 bars is not computable; 20/21/29 are; mature factors stay None."""
    assert signals.compute_short_history_signals(_bars(19)) is None
    for n in (20, 21, 29):
        sig = signals.compute_short_history_signals(_bars(n))
        assert sig is not None, f'{n} bars should compute the short view'
        assert sig.get('close') is not None
    sig = signals.compute_short_history_signals(_bars(25))
    # A short name can never masquerade as a mature factor row.
    assert sig.get('ma50') is None
    assert sig.get('ma200') is None
    assert sig.get('vol20') is None


def test_candidate_gate_uses_registry_listing_date():
    run = date(2026, 8, 14)
    # SKHY listed 2026-07-10 → 35 days: genuinely short.
    assert signals.is_short_history_candidate(
        {'listing_date': '2026-07-10'}, run) is True
    # One day ago — still short.
    assert signals.is_short_history_candidate(
        {'listing_date': '2026-08-13'}, run) is True
    # Listed more than the window ago: the 30-bar gate should have been reachable.
    assert signals.is_short_history_candidate(
        {'listing_date': '2026-05-01'}, run) is False
    # Absent / unparseable listing_date means "not known to be new".
    assert signals.is_short_history_candidate({}, run) is False
    assert signals.is_short_history_candidate(
        {'listing_date': 'not-a-date'}, run) is False
    assert signals.is_short_history_candidate(None, run) is False


def test_provisional_setups_fallback_only_for_new_listings(monkeypatch):
    """A 25-bar mature name (or one without a listing date) must NOT get the
    short view — it surfaces as insufficient_bars instead (#608)."""
    new_detail = {'label': 'SKHY', 'code': 'x', 'region': 'US',
                  'listing_date': '2026-07-10'}
    mature = {'label': 'NVDA', 'code': 'y', 'region': 'US',
              'listing_date': '1999-01-22'}
    no_date = {'label': 'ZZZ', 'code': 'z', 'region': 'US'}
    bars25 = _bars(25)

    monkeypatch.setattr(signals, 'compute_signals', lambda bars: None)
    monkeypatch.setattr(
        signals, 'compute_short_history_signals',
        lambda bars: {'close': 10.0, 'technical_setups': [
            {'setup_id': 'ma20_reclaim', 'label': 'SKHY', 'close': 10.0}]})

    out = signals.provisional_setups(
        universe=[new_detail, mature, no_date], region='US',
        fetch=lambda code, cnt: bars25)

    labels = [r.get('label') for r in out.get('rows')]
    assert labels == ['SKHY'], labels
    errs = {e.get('label') for e in out.get('errors')}
    assert {'NVDA', 'ZZZ'} <= errs, errs


def test_universe_details_tolerates_one_bad_holding(monkeypatch, tmp_path):
    """#612: a registry gap must not blank the whole universe; it lands in
    errors and the row carries the listing_date for the short-history gate."""
    port = {'portfolios': {'us_stocks': {'holdings': [
        {'ticker': 'NVDA', 'shares': 10},
        {'ticker': 'NOT_A_TICKER', 'shares': 5},
        {'ticker': 'SKHY', 'shares': 3},
    ]}}}
    pf = tmp_path / 'portfolio.json'
    pf.write_text(json.dumps(port))
    monkeypatch.setattr(signals, 'PORTFOLIO', pf)

    errors = []
    rows = signals.universe_details(errors=errors)

    labels = {r['label'] for r in rows}
    assert 'NVDA' in labels and 'SKHY' in labels
    assert len(errors) == 1 and errors[0]['label'] == 'NOT_A_TICKER'
    skhy = next(r for r in rows if r['label'] == 'SKHY')
    assert skhy.get('listing_date') == '2026-07-10'
