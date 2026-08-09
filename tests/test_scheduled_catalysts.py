"""The hand-maintained scheduled-catalyst store must not be able to lie quietly.

Company events with a known future date (Stock Connect effective dates, lockup
expiries, mainnet launches) have no vendor feed, so they live in a file a human
edits. Before it existed those dates lived only in brief prose, and on
2026-08-06 one brief gave three contradictory dates for the same MiniMax Stock
Connect event (下周一 / next month / 9月) while using that date to size a trim.

Both failure modes below are silent by nature — a wrong date reads exactly like
a right one — which is what earns them a test.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))

from clawock import fetch_catalysts


def _store(tmp_path, events):
    path = tmp_path / 'scheduled_catalysts.json'
    path.write_text(json.dumps({'events': events}), encoding='utf-8')
    return str(path)


def test_an_undated_event_cannot_claim_a_confirmed_date(tmp_path):
    """`date: null` must force `unconfirmed`, whatever the file says.

    The brief is allowed to print a date only for confirmed/estimated entries, so
    a stray "confirmed" on a dateless row would license it to state a certainty
    nobody ever established — the exact failure the store was built to end.
    """
    path = _store(tmp_path, [{
        'ticker': '00100', 'type': 'stock_connect_inclusion',
        'date': None, 'date_confidence': 'confirmed',
    }])
    events, error = fetch_catalysts.scheduled_in_window('2026-08-06', '2026-09-06', path=path)
    assert error is None
    assert events[0]['date'] is None
    assert events[0]['date_confidence'] == 'unconfirmed'


def test_a_broken_store_reports_instead_of_emptying_silently(tmp_path):
    """A JSON typo must surface, not drop every scheduled event without a word."""
    path = tmp_path / 'broken.json'
    path.write_text('{ not json', encoding='utf-8')
    events, error = fetch_catalysts.scheduled_in_window(
        '2026-08-06', '2026-09-06', path=str(path))
    assert events == []
    assert error and 'JSONDecodeError' in error


def test_undated_events_survive_the_window_filter(tmp_path):
    """A dateless event is pending, not expired — the window must not drop it."""
    path = _store(tmp_path, [
        {'ticker': 'AAA', 'date': None},
        {'ticker': 'BBB', 'date': '2027-01-01'},  # far outside the window
    ])
    events, _ = fetch_catalysts.scheduled_in_window('2026-08-06', '2026-09-06', path=path)
    assert [e['ticker'] for e in events] == ['AAA']
