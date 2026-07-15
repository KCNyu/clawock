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
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))

import brief_preflight
import trading_calendar


def test_brief_actually_calls_the_bar_fetcher():
    """The whole defect was that nobody called it, so this is the load-bearing test.

    It asserts against the function's own source and the script on disk, never
    against module text: an earlier version of this test searched the whole file for
    the string 'fetch_daily_bars.py' and happily passed while the call was renamed
    away, because the docstrings above mention the filename in prose.
    """
    src = inspect.getsource(brief_preflight.refresh_daily_bars)
    m = re.search(r"'(fetch_daily_bars\.py)'", src)
    assert m, ('refresh_daily_bars no longer invokes fetch_daily_bars.py — the bar '
               'store has no writer again and every new decision stays pending.')
    assert (ROOT / 'scripts' / 'data' / m.group(1)).exists(), (
        f'refresh_daily_bars runs {m.group(1)}, which does not exist')


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


def test_staleness_reports_a_per_ticker_hole():
    """The leg reducer is max(), so one frozen ticker hides behind the others — the
    first version of this check passed a store with 00100's newest bar removed.
    Laggards are what make a single-ticker outage visible."""
    real = brief_preflight.bars_staleness()
    assert real, 'staleness returned nothing — the store is unreadable'
    for leg, st in real.items():
        assert st['newest_bar'] <= (st['last_closed_session'] or '9999'), (
            f'{leg}: newest bar is ahead of the last closed session')
        assert isinstance(st.get('laggards'), dict), f'{leg}: laggards missing'
