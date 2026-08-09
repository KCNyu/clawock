"""One definition of "bad bar", shared by every fetcher.

The defect this guards: `fetch_daily_bars.sane()` — the gate on the canonical
store the decision ledger settles against — accepted `open == high == low ==
close` without comment, while `fetch_us_stocks` has alarmed on exactly that
shape since the 2026-05-29 stale-quote swap. The strongest detector guarded the
live path; the weakest one guarded the store that settles trigger verdicts.

Run: python3 -m pytest tests/test_bar_checks.py -q
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'scripts' / 'data'
sys.path.insert(0, str(DATA))

from clawock.market_data import integrity as bar_checks  # noqa: E402


def _bar(o, h, l, c, **extra):
    return {'open': o, 'high': h, 'low': l, 'close': c, **extra}


# ── structural checks ───────────────────────────────────────────────────────

def test_a_healthy_bar_has_no_findings():
    assert bar_checks.check_bar(_bar(10, 12, 9, 11)) == {'fatal': [], 'flags': []}


@pytest.mark.parametrize('bar, needle', [
    (_bar(10, 9, 11, 10), 'above high'),          # low > high
    (_bar(13, 12, 9, 11), 'open 13.0 outside'),   # open above high
    (_bar(10, 12, 9, 8), 'close 8.0 outside'),    # close below low
    (_bar(0, 0, 0, 0), 'non-positive'),
    (_bar(10, 12, -1, 11), 'non-positive'),
])
def test_impossible_bars_are_fatal(bar, needle):
    fatal = bar_checks.check_bar(bar)['fatal']
    assert fatal, f'{bar} was accepted'
    assert any(needle in reason for reason in fatal), fatal


@pytest.mark.parametrize('value', [None, 'n/a', float('nan'), float('inf')])
def test_a_missing_or_non_finite_price_is_fatal(value):
    assert bar_checks.check_bar(_bar(10, 12, 9, value))['fatal']


# ── the gap this issue is about ─────────────────────────────────────────────

def test_a_degenerate_bar_is_flagged_not_silently_accepted():
    """o==h==l==c passes every ordering rule. That is exactly why the old
    `sane()` let it into the canonical store without a word."""
    verdict = bar_checks.check_bar(_bar(4.2, 4.2, 4.2, 4.2))

    assert verdict['fatal'] == [], 'a halted session is not an impossible bar'
    assert 'degenerate_range' in verdict['flags']


def test_the_old_ordering_predicate_still_accepts_a_degenerate_bar():
    """Pins why the flag had to be added: the structural predicate cannot see
    this shape, so anything relying on it alone stays blind."""
    assert bar_checks.is_structurally_sane(_bar(4.2, 4.2, 4.2, 4.2))


def test_a_flagged_bar_is_never_reported_as_fatal():
    """Detection must not become suppression: a halted session is real data and
    the caller still needs its close to settle against."""
    for bar in (_bar(4.2, 4.2, 4.2, 4.2), _bar(10, 12, 9, 20.0, )):
        verdict = bar_checks.check_bar(bar, prev_close=10.0)
        assert not (verdict['flags'] and verdict['fatal']), verdict


def test_an_implausible_move_is_flagged_but_allowed():
    verdict = bar_checks.check_bar(_bar(10, 21, 10, 20), prev_close=10.0)

    assert verdict['fatal'] == []
    assert any(f.startswith('implausible_move') for f in verdict['flags'])


def test_an_ordinary_move_is_not_flagged():
    assert bar_checks.check_bar(_bar(10, 11, 10, 10.8), prev_close=10.0)['flags'] == []


def test_a_bar_dated_after_the_last_closed_session_is_flagged():
    verdict = bar_checks.check_bar(
        _bar(10, 12, 9, 11, date='2026-08-02'), last_closed='2026-08-01')

    assert any('unfinished_session' in f for f in verdict['flags'])


def test_a_bar_dated_to_another_session_is_flagged():
    verdict = bar_checks.check_bar(
        _bar(10, 12, 9, 11, date='2026-07-30'), session_date='2026-07-31')

    assert any('session_mismatch' in f for f in verdict['flags'])


# ── the HK live-quote rule, now shared ──────────────────────────────────────

def test_a_price_below_its_own_quoted_range_is_named():
    # The 2026-06-15 03033 bad tick: 4.5 printed against a [4.644, 4.696] range.
    assert bar_checks.price_outside_quoted_range(4.5, 4.644, 4.696)


def test_a_price_inside_the_range_or_within_tolerance_is_clean():
    assert bar_checks.price_outside_quoted_range(4.67, 4.644, 4.696) is None
    # Rounding must not manufacture a bad tick.
    assert bar_checks.price_outside_quoted_range(4.6939, 4.644, 4.694) is None


def test_an_incomplete_quote_cannot_produce_a_verdict():
    assert bar_checks.price_outside_quoted_range(4.5, None, 4.696) is None
    assert bar_checks.price_outside_quoted_range(4.5, 0, 0) is None


# ── gap-safe returns ────────────────────────────────────────────────────────

def test_a_halted_session_produces_no_return_instead_of_a_zero():
    bars = [
        _bar(10, 10.5, 9.8, 10.0, date='2026-01-02'),
        _bar(4.2, 4.2, 4.2, 4.2, date='2026-01-03'),   # halted
        _bar(10.2, 11.0, 10.1, 11.0, date='2026-01-06'),
    ]

    out = bar_checks.gap_safe_returns(bars)

    assert [d for d, _ in out] == ['2026-01-06']
    # The surviving return spans the gap, so it is still a true close-to-close move.
    assert out[0][1] == pytest.approx(11.0 / 10.0 - 1)


def test_treating_a_halt_as_a_zero_return_deflates_realised_volatility():
    """The reason this matters: volatility feeds the leverage dial, so a
    forward-filled halt does not just add a harmless row — it lowers the number
    the dial is compared against."""
    np = pytest.importorskip('numpy')
    traded = [10.0, 10.6, 9.9, 10.4, 10.1, 10.9]
    bars = []
    for i, close in enumerate(traded):
        bars.append(_bar(close, close * 1.01, close * 0.99, close,
                         date=f'2026-01-{i + 1:02d}'))
    # Insert three halted sessions in the middle.
    for j in range(3):
        flat = traded[2]
        bars.insert(3 + j, _bar(flat, flat, flat, flat, date=f'2026-02-{j + 1:02d}'))

    gap_safe = [r for _, r in bar_checks.gap_safe_returns(bars)]
    forward_filled = [r for _, r in bar_checks.gap_safe_returns(
        bars, skip_degenerate=False)]

    assert len(forward_filled) > len(gap_safe)
    assert np.std(forward_filled, ddof=1) < np.std(gap_safe, ddof=1), (
        'zero-return halt days must deflate measured volatility — if they do '
        'not, this fixture no longer demonstrates the defect')


def test_gap_safe_returns_accept_a_date_keyed_store():
    """`memory/bars/*.json` stores `{date: bar}`, not a list."""
    store = {
        '2026-01-02': _bar(10, 10.5, 9.8, 10.0),
        '2026-01-03': _bar(10.1, 11.0, 10.0, 11.0),
    }

    assert bar_checks.gap_safe_returns(store) == [('2026-01-03', pytest.approx(0.1))]


def test_a_zero_or_missing_close_cannot_enter_the_return_series():
    bars = [
        _bar(10, 10.5, 9.8, 10.0, date='2026-01-02'),
        _bar(0, 0, 0, 0, date='2026-01-03'),
        _bar(10.1, 11.0, 10.0, 11.0, date='2026-01-06'),
    ]

    assert [d for d, _ in bar_checks.gap_safe_returns(bars)] == ['2026-01-06']


# ── the flag has to reach the store, not just the checker ───────────────────

def _bars_module(tmp_path, monkeypatch):
    from clawock.market_data import bars as fetch_daily_bars

    monkeypatch.setattr(fetch_daily_bars, 'BARS_DIR', tmp_path)
    monkeypatch.setitem(
        fetch_daily_bars.MANIFEST, 'TEST',
        {'leg': 'hk', 'tencent': 'hkTEST', 'em': None, 'retired': False})
    monkeypatch.setattr(fetch_daily_bars, '_last_closed_session',
                        lambda leg: '2026-01-31')
    return fetch_daily_bars


def test_a_degenerate_bar_reaches_the_canonical_store_carrying_its_flag(
        tmp_path, monkeypatch):
    """It must be stored — settlement needs the close — but never as a bar with
    a range, because a trigger that "fired" inside a zero-width range is not
    evidence of anything."""
    mod = _bars_module(tmp_path, monkeypatch)
    fresh = [
        {'date': '2026-01-05', 'open': 10, 'high': 11, 'low': 9.5, 'close': 10.5},
        {'date': '2026-01-06', 'open': 4.2, 'high': 4.2, 'low': 4.2, 'close': 4.2},
    ]

    added, revised, conflicts = mod.merge('TEST', fresh, repair=False)

    assert (added, revised, conflicts) == (2, 0, [])
    stored = mod.load_bars('TEST')['bars']
    assert stored['2026-01-06']['degenerate'] is True
    assert 'degenerate' not in stored['2026-01-05']


def test_an_impossible_bar_is_still_refused_with_the_reason_named(
        tmp_path, monkeypatch):
    mod = _bars_module(tmp_path, monkeypatch)
    fresh = [{'date': '2026-01-05', 'open': 10, 'high': 9, 'low': 11, 'close': 10}]

    added, _, conflicts = mod.merge('TEST', fresh, repair=False)

    assert added == 0
    assert conflicts and 'above high' in conflicts[0]


# ── the structural gate: nobody re-grows a private copy ─────────────────────

def test_packaged_daily_bar_store_uses_the_shared_contract():
    from clawock.market_data import bars as fetch_daily_bars

    assert fetch_daily_bars.bar_checks is bar_checks


def test_no_script_re_implements_the_degenerate_check_privately():
    """The failure this whole module exists to prevent: three files, three
    definitions, and the weakest one guarding the canonical store."""
    # A chained `a == b == c == d` is the shape of a hand-rolled degenerate-range
    # test. Matched through the AST, not the text: the prose in these files
    # legitimately quotes `o == h == l == c` when explaining the bug it caused.
    offenders = []
    for path in sorted(DATA.glob('*.py')):
        if path.name == 'bar_checks.py':
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - the import check owns this
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or len(node.ops) < 3:
                continue
            if all(isinstance(op, ast.Eq) for op in node.ops):
                offenders.append(f'{path.name}:{node.lineno}')

    assert not offenders, (
        'private degenerate-range check(s) outside bar_checks.py:\n'
        + '\n'.join(offenders))
