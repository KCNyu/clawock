"""The canonical bar store must have a live writer, and the check must use the calendar.

`memory/bars/` is what decision_v2 settles against and settling only ever reads it.
It was backfilled once (8aad505) and then had no writer at all — no cron, no
contract entry, no workflow ran fetch_daily_bars.py — so every session after the
backfill was invisible to the ledger, 28 decisions sat at `pending`, and the
published win rate quietly stopped being able to move while the dashboard kept
refreshing around it. Nothing failed; that is what made it survive.

Run: python3 -m pytest tests/test_bars_freshness.py -q
"""
import inspect
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))

from clawock_kcnyu.harness import brief_preflight
from clawock import trading_calendar


def test_brief_actually_calls_the_installed_bar_fetcher(monkeypatch):
    """The whole defect was that nobody called the canonical store writer."""
    calls = []
    monkeypatch.setattr(
        brief_preflight.subprocess, 'run',
        lambda argv, **kwargs: calls.append((argv, kwargs)) or type(
            'Done', (), {'returncode': 0, 'stdout': '0 bars added, 0 revised',
                         'stderr': ''})(),
    )
    monkeypatch.setattr(brief_preflight, 'bars_staleness', lambda: {})

    result = brief_preflight.refresh_daily_bars()

    assert result['ok'] is True
    assert calls[0][0] == ['clawock', 'daily-bars']
    assert calls[0][1]['cwd'] == brief_preflight.WS


def test_bars_are_fetched_before_the_ledger_settles():
    """Settling only reads the store, so a fetch after it lands a day late."""
    body = inspect.getsource(brief_preflight.main)
    fetch_at = body.index('refresh_daily_bars()')
    settle_at = body.index('compute_decision_metrics()')
    assert fetch_at < settle_at, (
        'bars are refreshed after the ledger settles; the fetch would only take '
        'effect on the following run.')


def test_staleness_uses_the_trading_calendar_not_a_weekday_guess():
    """A missing bar is not a closed market. Conflating the two already deleted 10
    live US rows once. On a Monday, "yesterday" is Sunday — a naive cutoff would
    report the weekend as missing sessions every week."""
    for market in ('hk', 'us'):
        d = brief_preflight._last_closed_session(market)
        assert d is not None, f'{market}: no closed session found within 14 days'
        assert trading_calendar.is_trading_day(market, d), (
            f'{market}: reported {d} as the last closed session, but the calendar '
            f'says the market did not trade that day')


def test_stored_bars_are_raw_and_never_hold_an_open_session():
    """Two contract invariants the ledger depends on. An adjusted series would
    silently re-price every past trigger; a live bar is the exact defect this store
    was built to remove."""
    bars_dir = ROOT / 'memory' / 'bars'
    docs = list(bars_dir.glob('*.json'))
    assert docs, 'no bar files at all'
    for p in docs:
        doc = json.loads(p.read_text())
        assert doc.get('adjustment') == 'raw', f'{p.name}: not a raw series'
        leg = 'hk' if doc.get('leg') == 'HK' else 'us'
        last_closed = brief_preflight._last_closed_session(leg)
        for d, bar in doc.get('bars', {}).items():
            assert date.fromisoformat(d) <= last_closed, (
                f'{p.name}: stores {d}, which has not closed yet in {leg.upper()}')
            assert bar['low'] <= bar['open'] <= bar['high'], f'{p.name} {d}: open outside range'
            assert bar['low'] <= bar['close'] <= bar['high'], f'{p.name} {d}: close outside range'


def _write_store(root, docs):
    """Build a throwaway bar store: {ticker: (leg, [dates])}."""
    d = root / 'memory' / 'bars'
    d.mkdir(parents=True)
    for ticker, (leg, dates) in docs.items():
        (d / f'{ticker}.json').write_text(json.dumps({
            'schema_version': 1, 'ticker': ticker, 'leg': leg, 'adjustment': 'raw',
            'bars': {x: {'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0} for x in dates},
        }))
    return root


def test_staleness_reports_a_per_ticker_hole(tmp_path, monkeypatch):
    """One frozen ticker must stay visible behind a healthy leg.

    The leg reducer is max(), so a fresh sibling hides a frozen ticker completely —
    an earlier version of this test only asserted `laggards` was a dict, which passed
    even with the value hardcoded to {} and never actually created a hole. This one
    builds a store with a real hole and asserts the frozen ticker is named.
    """
    fresh = brief_preflight._last_closed_session('hk').isoformat()
    _write_store(tmp_path, {
        'HEALTHY': ('HK', [fresh]),
        'FROZEN': ('HK', ['2026-06-01']),
    })
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    hk = brief_preflight.bars_staleness()['HK']

    assert hk['newest_bar'] == fresh
    assert hk['missing_sessions'] == [], 'a healthy leg must not report leg-level gaps'
    assert hk['laggards'] == {'FROZEN': '2026-06-01'}, (
        'a frozen ticker vanished behind its healthy sibling — this is exactly the '
        'outage the laggard list exists to surface')


def test_retirement_is_declared_never_inferred(tmp_path, monkeypatch):
    """A frozen writer and a retired instrument look identical from the bars alone.

    Settling used to decide it with `sess > max(bars)`, which is also the exact
    signature of a ticker whose writer stopped: its decisions would be filed
    `instrument_inactive` and drop out of the denominator with nothing reported. Only
    a declaration in fetch_daily_bars' MANIFEST may say an instrument is retired.
    """
    from clawock import decision_v2

    d = tmp_path / 'memory' / 'bars'
    d.mkdir(parents=True)
    for ticker, retired in (('RETIRED', True), ('FROZEN', False)):
        (d / f'{ticker}.json').write_text(json.dumps({
            'ticker': ticker, 'leg': 'US', 'adjustment': 'raw', 'retired': retired,
            'bars': {'2026-06-01': {'open': 1.0, 'high': 1.0, 'low': 1.0, 'close': 1.0}},
        }))
    monkeypatch.setattr(decision_v2, 'BARS_DIR', d)

    assert decision_v2.ticker_retired('RETIRED') is True
    assert decision_v2.ticker_retired('FROZEN') is False, (
        'a ticker whose bars merely stop early was reported as retired — that is a '
        'data outage being laundered into a fact about the instrument')
    assert decision_v2.ticker_retired('NEVER_HEARD_OF') is False


def test_no_active_instrument_is_declared_retired():
    """`retired` is a hand-pinned fact, never inferred; no live line may carry it."""
    from clawock import fetch_daily_bars
    assert not any(m.get('retired') for m in fetch_daily_bars.MANIFEST.values()), \
        'an active instrument is declared retired'


def test_retirement_declaration_survives_an_empty_fetch(tmp_path, monkeypatch):
    """The one case `retired` exists for — a delisted line the provider no longer
    returns — must still reach the bar JSON, which settlement reads. merge() writes it
    on a non-empty fetch; the empty-fetch path must sync it too, or a newly declared
    retirement is silently lost and the decision settles as bar_missing forever."""
    from clawock import fetch_daily_bars as fdb
    # and the helper must flip an existing store's flag to match the manifest.
    monkeypatch.setattr(fdb, 'BARS_DIR', tmp_path)
    (tmp_path / 'FOO.json').write_text(json.dumps({'ticker': 'FOO', 'retired': False, 'bars': {}}))
    monkeypatch.setitem(fdb.MANIFEST, 'FOO',
                        {'leg': 'US', 'tencent': 'usFOO', 'em': '105.FOO', 'retired': True})
    fdb._sync_manifest_flags('FOO')
    assert json.loads((tmp_path / 'FOO.json').read_text())['retired'] is True


def test_incremental_fetch_anchors_to_each_tickers_own_newest_bar(tmp_path, monkeypatch):
    """A fixed window off today turns any outage longer than it into a permanent
    hole: the writer resumes, appends the tail, and the middle is never refetched
    while freshness — which only looks after the newest bar — reads as current."""
    from clawock import fetch_daily_bars
    monkeypatch.setattr(fetch_daily_bars, 'BARS_DIR', tmp_path)
    monkeypatch.setattr(fetch_daily_bars, 'MANIFEST', {
        'FOO': {'leg': 'US', 'tencent': 'usFOO.OQ', 'em': '105.FOO',
                'retired': False},
    })
    (tmp_path / 'FOO.json').write_text(json.dumps({
        'ticker': 'FOO', 'leg': 'US', 'adjustment': 'raw',
        'bars': {'2026-06-01': {'open': 1, 'high': 1, 'low': 1, 'close': 1}},
    }))
    seen = []
    monkeypatch.setattr(
        fetch_daily_bars, 'fetch_tencent',
        lambda symbol, begin, end: seen.append((symbol, begin, end)) or [],
    )

    assert fetch_daily_bars.main(['--ticker', 'FOO']) == 0
    assert seen[0][1] == '2026-05-30'


def test_staleness_flags_a_whole_leg_falling_behind(tmp_path, monkeypatch):
    """The leg-level alarm: every ticker stale means the writer itself is dead,
    which is the condition that went unnoticed for a month."""
    _write_store(tmp_path, {'A': ('HK', ['2026-06-01']), 'B': ('HK', ['2026-06-01'])})
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    hk = brief_preflight.bars_staleness()['HK']

    assert hk['missing_sessions'], 'a leg stuck at 2026-06-01 reported no missing sessions'
    assert hk['laggards'] == {}, 'uniformly stale is a leg outage, not a laggard'
    # Real sessions only — a naive date walk would list weekends and holidays.
    for d in hk['missing_sessions']:
        assert trading_calendar.is_trading_day('hk', date.fromisoformat(d)), (
            f'{d} is not an HK trading day but was reported as a missing session')
