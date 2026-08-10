"""The trade list must replay to the shares actually held — or say why it cannot.

#456: eight holdings record a sell with no matching buy, so replaying
`holdings[].trades[]` drives the share balance negative. Realized P&L is
unaffected and the money gate is right to be green; the cost is that the trade
list cannot be replayed as a share ledger, and every consumer that tries gets a
number wrong by a constant nobody can recover. #455 hit exactly that and had to
clamp the balance at zero locally.

This file pins the check that stops the set growing silently.

Two things are deliberately stronger than the issue's framing:

`shares - net_from_trades` is the invariant, not "the balance goes negative".
Negative balance is a symptom that only appears when the unrecorded opening lot
is smaller than a later sell. 07226 holds 6,200 shares against +1,000 of
recorded trades — 5,200 opening shares missing, never once negative, and the
issue's own table missed it for that reason. The deficit is also the stable
number: it survives further selling, while the negative low-water mark deepens.

An entry that no longer reproduces must be removed. A known-issue list that
outlives its issue is how a gate quietly stops gating.
"""
import json

import pytest

from clawock.portfolio.integrity import (
    KNOWN_INCOMPLETE_LEDGERS, check_share_ledgers, ledger_deficit,
)


def _holding(ticker, shares, trades):
    return {'ticker': ticker, 'shares': shares, 'trades': trades}


def _buy(date, shares):
    return {'date': date, 'action': 'buy', 'shares': shares, 'price': 10}


def _sell(date, shares):
    return {'date': date, 'action': 'sell', 'shares': shares, 'price': 12}


def _codes(findings, code):
    return [f for f in findings if f['code'] == code]


def test_a_complete_ledger_replays_to_the_recorded_shares():
    holding = _holding('CRCL', 2, [_buy('2026-05-01', 5), _sell('2026-05-02', 3)])
    assert ledger_deficit(holding) == 0


def test_the_deficit_is_the_unrecorded_opening_lot():
    """07226's shape: every recorded trade is a buy, and the position is still
    larger than all of them together."""
    holding = _holding('07226', 6200, [_buy('2026-06-01', 1000)])
    assert ledger_deficit(holding) == 5200


def test_the_deficit_survives_further_selling():
    """Why the deficit is the recorded number and the negative low-water mark is
    not: selling more deepens the trough but cannot change what is missing."""
    before = _holding('02208', 400, [_sell('2026-04-27', 200)])
    after = _holding('02208', 300, [_sell('2026-04-27', 200), _sell('2026-05-06', 100)])
    assert ledger_deficit(before) == ledger_deficit(after) == 600


def test_a_ledger_that_never_goes_negative_is_still_caught():
    """The gap this check exists to close: the issue's negative-balance test
    reports nothing here, and 5,200 shares are still unaccounted for."""
    findings = check_share_ledgers(
        {'hk_stocks': {'holdings': [_holding('NEWTKR', 6200, [_buy('2026-06-01', 1000)])]}})
    assert _codes(findings, 'SHARE_LEDGER'), 'an unrecorded opening lot must be reported'


def test_a_known_incomplete_ledger_is_not_reported_again():
    holdings = [_holding('TQQQ', 0, [_sell('2026-04-16', 8)])]
    findings = check_share_ledgers({'us_stocks': {'holdings': holdings}})
    assert not _codes(findings, 'SHARE_LEDGER')


def test_a_known_ledger_that_drifts_further_is_reported():
    """The allowlist forgives one recorded deficit, not any deficit on that
    ticker: a NEW unmatched sell is a new data-entry error."""
    holdings = [_holding('TQQQ', 0, [_sell('2026-04-16', 8), _sell('2026-05-20', 3)])]
    findings = check_share_ledgers({'us_stocks': {'holdings': holdings}})
    found = _codes(findings, 'SHARE_LEDGER')
    assert found, 'a deepened deficit is not the deficit that was signed off'
    assert '11' in found[0]['msg']


def test_a_repaired_ledger_is_silent_at_runtime():
    """A backfilled ledger produces no finding — and the demand that its
    allowlist entry then be *removed* is made against the real book in
    `test_the_check_actually_replays_nine_real_ledgers`, not here. A runtime
    code for it would fire on every synthetic fixture that borrows a real
    ticker, and a code that always fires is a code nobody reads."""
    holdings = [_holding('TQQQ', 8, [_buy('2026-01-05', 8), _sell('2026-04-16', 8),
                                     _buy('2026-04-17', 8)])]
    assert check_share_ledgers({'us_stocks': {'holdings': holdings}}) == []


def test_a_holding_with_no_trades_is_not_a_finding():
    """Positions that predate the trade log entirely carry no list to replay.
    Flagging them would bury the nine real ones in noise — and an all-cash or
    gold-only book legitimately has nothing to scan at all."""
    findings = check_share_ledgers(
        {'us_stocks': {'holdings': [{'ticker': 'NVDA', 'shares': 10, 'trades': []},
                                    _holding('CRCL', 2, [_buy('2026-05-01', 2)])]}})
    assert not _codes(findings, 'SHARE_LEDGER')


def test_the_finding_never_blocks_publication():
    """Realized P&L reconciles to the cent and the book totals are right, so an
    incomplete share ledger must stay visible without stopping delivery — the
    same level REALIZED_SUM sits at."""
    findings = check_share_ledgers(
        {'hk_stocks': {'holdings': [_holding('NEWTKR', 6200, [_buy('2026-06-01', 1000)])]}})
    assert all(f['level'] == 'WARN' for f in findings)


def test_the_allowlist_matches_the_live_book_exactly():
    """The list is a statement about real data, so it is checked against real
    data: every entry must still reproduce, and nothing outside it may be
    incomplete. This is the test that fails the day a tenth one appears."""
    from clawock.portfolio.integrity import PORTFOLIO

    if not PORTFOLIO.exists():
        pytest.skip('no live book in this checkout')
    data = json.loads(PORTFOLIO.read_text())
    findings = check_share_ledgers(data.get('portfolios', {}))
    assert [f for f in findings if f['code'] == 'SHARE_LEDGER_VACUOUS'] == []
    assert [f['msg'] for f in findings if f['code'].startswith('SHARE_LEDGER')] == []


def test_the_gate_is_actually_wired_into_the_published_check(tmp_path):
    """A check nobody calls is the most expensive kind of green. `clawock
    integrity` is what preflight and publishing run, so the finding has to come
    out of `check()` — not merely out of the function this file tests directly.
    """
    from clawock.portfolio.integrity import check

    book = tmp_path / 'portfolio.json'
    book.write_text(json.dumps({'portfolios': {'us_stocks': {
        'currency': 'USD',
        'holdings': [_holding('NEWTKR', 6200, [_buy('2026-06-01', 1000)])],
    }}}))

    report = check(book)
    assert [f for f in report['findings'] if f['code'] == 'SHARE_LEDGER'], (
        'check() must surface the share-ledger finding')
    assert report['ok'], 'the money is right — this finding must not block publishing'


def test_the_check_actually_replays_nine_real_ledgers():
    """The anti-vacuous assertion, and it lives here on purpose.

    A discovery-style gate that finds nothing because it looked at nothing
    reports success forever (#452, #453). But "scanned zero" cannot be a runtime
    finding: an all-cash or gold-only book legitimately has no trade list to
    replay, and firing there would train everyone to ignore the code.

    So the claim is checked against the real book instead, where it is falsifiable
    without being noisy: each of the nine must still be present, still carry a
    trades list, and still reproduce its recorded deficit. Rename the `trades`
    key or move holdings and this fails — which is the exact rot that would
    otherwise leave the gate scanning nothing and reporting clean.
    """
    from clawock.portfolio.integrity import PORTFOLIO

    if not PORTFOLIO.exists():
        pytest.skip('no live book in this checkout')
    portfolios = json.loads(PORTFOLIO.read_text()).get('portfolios', {})
    by_key = {(region, h.get('ticker')): h
              for region, port in portfolios.items()
              for h in (port.get('holdings') or [])}

    assert len(KNOWN_INCOMPLETE_LEDGERS) == 9
    assert ('hk_stocks', '07226') in KNOWN_INCOMPLETE_LEDGERS, (
        'the one the negative-balance framing missed')

    for key, deficit in KNOWN_INCOMPLETE_LEDGERS.items():
        holding = by_key.get(key)
        assert holding is not None, f'{key} left the book without leaving the list'
        assert holding.get('trades'), f'{key} no longer carries a replayable list'
        assert ledger_deficit(holding) == deficit, (
            f'{key} deficit moved; the signed-off number is stale')
