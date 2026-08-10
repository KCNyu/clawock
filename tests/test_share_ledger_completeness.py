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


def _replay_residuals(rest, quantity, price, cost_basis):
    """How badly an opening lot of (quantity @ price) contradicts what IS recorded.

    Deliberately a second implementation rather than a call into the package: it
    re-derives the stored price from the rest of the ledger, so a bug in the
    production moving-average would have to be reproduced here identically to
    hide. Same reason the money gate recomputes rather than trusts.
    """
    order = [{'date': '0000-00-00', 'action': 'buy',
              'shares': quantity, 'price': price}]
    order += sorted(rest, key=lambda t: t.get('date', ''))
    shares = 0.0
    cost = 0.0
    errors = []
    for trade in order:
        qty = float(trade.get('shares') or 0)
        px = float(trade.get('price') or 0)
        if trade.get('action') == 'buy':
            shares += qty
            cost += qty * px
            continue
        average = cost / shares if shares else 0.0
        if trade.get('realized_pnl') is not None:
            errors.append(qty * (px - average) - float(trade['realized_pnl']))
        cost -= qty * average
        shares -= qty
    final = cost / shares if shares else None
    if final is not None and cost_basis:
        errors.append(final - cost_basis)
    return errors


def _solve_opening_price(rest, quantity, cost_basis, shares_now):
    low, high = 0.0, 500.0
    def total(price):
        return sum(e * e for e in _replay_residuals(rest, quantity, price, cost_basis))
    for _ in range(400):
        left = low + (high - low) / 3
        right = high - (high - low) / 3
        if total(left) < total(right):
            high = right
        else:
            low = left
    return (low + high) / 2


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


def test_a_signed_off_deficit_is_not_reported_again(monkeypatch):
    """The suppression mechanism, exercised against a patched list rather than
    the live one — which is empty now that #456 was fixed by backfill instead of
    by exemption. Testing it through real data would make this test pass or fail
    on today's book instead of on the behaviour."""
    monkeypatch.setattr(
        'clawock.portfolio.integrity.KNOWN_INCOMPLETE_LEDGERS',
        {('us_stocks', 'ZZZZ'): 8})
    holdings = [_holding('ZZZZ', 0, [_sell('2026-04-16', 8)])]
    findings = check_share_ledgers({'us_stocks': {'holdings': holdings}})
    assert not _codes(findings, 'SHARE_LEDGER')


def test_a_signed_off_ledger_that_drifts_further_is_reported(monkeypatch):
    """The list forgives one recorded deficit, not any deficit on that ticker:
    a NEW unmatched sell is a new data-entry error."""
    monkeypatch.setattr(
        'clawock.portfolio.integrity.KNOWN_INCOMPLETE_LEDGERS',
        {('us_stocks', 'ZZZZ'): 8})
    holdings = [_holding('ZZZZ', 0, [_sell('2026-04-16', 8), _sell('2026-05-20', 3)])]
    findings = check_share_ledgers({'us_stocks': {'holdings': holdings}})
    found = _codes(findings, 'SHARE_LEDGER')
    assert found, 'a deepened deficit is not the deficit that was signed off'
    assert '11' in found[0]['msg']


def test_a_repaired_ledger_is_silent_at_runtime():
    """What the nine look like now: replays clean, says nothing."""
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


def test_the_check_actually_replays_the_real_book():
    """The anti-vacuous assertion, and with the allowlist empty it is now the
    ONLY thing proving this gate is still alive.

    A discovery-style gate that finds nothing because it looked at nothing
    reports success forever (#452, #453). "Scanned zero" cannot be a runtime
    finding — an all-cash or gold-only book legitimately has no trade list to
    replay — so the claim is made here, against the real book.

    Delete this test and the gate reports clean for the rest of time.
    """
    from clawock.portfolio.integrity import PORTFOLIO

    if not PORTFOLIO.exists():
        pytest.skip('no live book in this checkout')
    portfolios = json.loads(PORTFOLIO.read_text()).get('portfolios', {})
    scanned = [h for port in portfolios.values()
               for h in (port.get('holdings') or []) if h.get('trades')]

    assert len(scanned) >= 15, (
        f'only {len(scanned)} ledgers carry trades[] — the gate is scanning almost '
        'nothing, which is how it goes quiet without going red')
    assert not check_share_ledgers(portfolios), 'the live book must replay clean'
    for holding in scanned:
        assert ledger_deficit(holding) == 0, holding.get('ticker')


def test_the_allowlist_is_empty_and_that_is_the_success_state():
    """#456 closed by backfill, not by exemption. A non-empty list means a tenth
    incomplete ledger appeared and someone signed it off instead of fixing it —
    which is a decision that should be visible in a diff."""
    assert KNOWN_INCOMPLETE_LEDGERS == {}


def test_every_reconstructed_lot_is_re_derivable_from_the_rest_of_the_ledger():
    """The reconstructed opening lots are the one place in the book where a
    number was computed rather than recorded, so the computation is re-run here
    on every CI run instead of being trusted because a commit message said so.

    For each lot: drop it, solve for the opening price that reproduces every
    OTHER recorded number in that holding — each sell's own realized_pnl, and
    the holding's cost_basis — and require the stored price back. A hand-edited
    price, or a later trade that contradicts it, fails this.
    """
    from clawock.portfolio.integrity import PORTFOLIO

    if not PORTFOLIO.exists():
        pytest.skip('no live book in this checkout')
    portfolios = json.loads(PORTFOLIO.read_text()).get('portfolios', {})

    checked = 0
    for port in portfolios.values():
        for holding in port.get('holdings') or []:
            trades = holding.get('trades') or []
            lots = [t for t in trades if t.get('reconstructed')]
            if not lots:
                continue
            assert len(lots) == 1, 'one opening lot per holding'
            lot = lots[0]
            rest = [t for t in trades if not t.get('reconstructed')]
            solved = _solve_opening_price(
                rest, float(lot['shares']), float(holding.get('cost_basis') or 0),
                float(holding.get('shares') or 0))
            assert abs(solved - float(lot['price'])) < 0.01, (
                f"{holding.get('ticker')}: stored {lot['price']}, "
                f"re-derived {solved:.4f}")
            checked += 1

    assert checked == 9, f'expected 9 reconstructed lots, found {checked}'


def test_a_lot_pinned_only_by_cost_basis_is_not_marked_corroborated():
    """07226 has no sells, so its opening price comes from cost_basis alone and
    checking cost_basis against it would be circular. The flag that keeps
    COST_BASIS honest has to actually be set on that holding and not on the
    others."""
    from clawock.portfolio.integrity import PORTFOLIO

    if not PORTFOLIO.exists():
        pytest.skip('no live book in this checkout')
    portfolios = json.loads(PORTFOLIO.read_text()).get('portfolios', {})
    flags = {}
    for port in portfolios.values():
        for holding in port.get('holdings') or []:
            for t in holding.get('trades') or []:
                if t.get('reconstructed'):
                    flags[holding['ticker']] = t.get('corroborated')

    assert flags.get('07226') is False, (
        'the one lot with no independent source must not claim corroboration')
    assert all(v is True for k, v in flags.items() if k != '07226'), flags


def test_cost_basis_declines_to_judge_an_uncorroborated_reconstruction():
    """The gate must skip exactly the circular case — and must NOT skip a
    holding whose reconstruction was pinned by independent realized_pnl."""
    from clawock.portfolio.integrity import check

    def book(corroborated, cost_basis):
        return {'portfolios': {'hk_stocks': {
            'currency': 'HKD',
            'holdings': [{
                'ticker': 'X', 'shares': 200, 'cost_basis': cost_basis,
                'trades': [
                    {'date': '2026-01-01', 'action': 'buy', 'shares': 200,
                     'price': 10.0, 'reconstructed': True,
                     'corroborated': corroborated},
                ],
            }],
        }}}

    import tempfile
    from pathlib import Path as _P

    def findings(corroborated, cost_basis):
        with tempfile.TemporaryDirectory() as d:
            p = _P(d) / 'portfolio.json'
            p.write_text(json.dumps(book(corroborated, cost_basis)))
            return [f['code'] for f in check(p)['findings']]

    # cost_basis wildly disagrees with the replay (10.0)
    assert 'COST_BASIS' in findings(True, 99.0), (
        'a corroborated reconstruction must still be checked'
    )
    assert 'COST_BASIS' not in findings(False, 99.0), (
        'an uncorroborated reconstruction must not be judged against itself'
    )
