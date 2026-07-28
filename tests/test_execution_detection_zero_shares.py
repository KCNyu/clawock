"""`_shares_at_date`: a ticker the portfolio does not list is zero, not unknown.

`_detect_followed` settles `execution.status` by diffing shares in
`portfolio.json` across the decision's window, and it re-runs on every brief
preflight. That retry loop is why conflating "absent from holdings" with "could
not read the portfolio" is not a cosmetic bug: an unknown that is really a zero
is retried forever and never resolves.

Measured on the live ledger before the fix — 9 decisions stranded:

    2026-07-15 .. 2026-07-20   PLTR × 4, MSFT × 4   add_only_on_trigger
    2026-07-13                 SKHY                 hold_and_watch

all because kcn holds the 2x ETFs (PLTU/MSFU) while the decisions name the spot
tickers, which appear in no holdings list at all. Never opening a position is
exactly what `add_only_on_trigger` not being followed looks like, so the answer
was always readable.

The tests below pin both directions: absence must read as 0, and a portfolio
that genuinely cannot be read must still read as None — a false 0 would invent
`not_followed` out of a git failure.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))

import brief_preflight  # noqa: E402


def _portfolio(us=(), hk=()):
    return {'portfolios': {
        'us_stocks': {'holdings': [{'ticker': t, 'shares': s} for t, s in us]},
        'hk_stocks': {'holdings': [{'ticker': t, 'shares': s} for t, s in hk]},
    }}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo with one committed portfolio.json, standing in for the live WS."""
    def build(payload, when='2026-07-16T12:00:00'):
        subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
        (tmp_path / 'portfolio.json').write_text(json.dumps(payload), encoding='utf-8')
        env = {'GIT_AUTHOR_DATE': when, 'GIT_COMMITTER_DATE': when}
        subprocess.run(['git', '-C', str(tmp_path), 'add', 'portfolio.json'], check=True)
        subprocess.run(
            ['git', '-C', str(tmp_path), '-c', 'user.email=t@t', '-c', 'user.name=t',
             'commit', '-q', '-m', 'portfolio'],
            check=True, env={**dict(**__import__('os').environ), **env},
        )
        monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
        return tmp_path
    return build


# ── absence is a readable state ───────────────────────────────────────────────

def test_a_ticker_that_was_never_held_reads_as_zero(repo):
    repo(_portfolio(us=[('PLTU', 14)]))

    # PLTU is held via the 2x ETF; the spot ticker appears nowhere.
    assert brief_preflight._shares_at_date('PLTR', '2026-07-17') == 0


def test_a_fully_exited_position_reads_as_its_zero(repo):
    repo(_portfolio(us=[('NVDA', 0), ('PLTU', 14)]))

    assert brief_preflight._shares_at_date('NVDA', '2026-07-17') == 0


def test_a_held_position_still_reads_its_count(repo):
    repo(_portfolio(us=[('PLTU', 14)], hk=[('07226', 6200)]))

    assert brief_preflight._shares_at_date('PLTU', '2026-07-17') == 14
    assert brief_preflight._shares_at_date('07226', '2026-07-17') == 6200


def test_both_regions_are_searched_before_concluding_absence(repo):
    """HK is scanned first; a US-only ticker must not short-circuit to 0."""
    repo(_portfolio(us=[('SPCH', 160)], hk=[('00100', 100)]))

    assert brief_preflight._shares_at_date('SPCH', '2026-07-17') == 160


# ── unreadable stays unknown ──────────────────────────────────────────────────

def test_no_commit_before_the_date_is_still_unknown(repo):
    repo(_portfolio(us=[('PLTU', 14)]), when='2026-07-16T12:00:00')

    # Nothing was committed this far back — absence of history is not a zero.
    assert brief_preflight._shares_at_date('PLTU', '1990-01-01') is None


def test_a_malformed_portfolio_is_unknown_not_zero(repo):
    """A structure change must not silently become 'nobody held anything'.

    This is the assertion that keeps the fix honest: returning 0 on any read
    failure would manufacture `not_followed` verdicts out of a broken file.
    """
    repo({'portfolios': {'us_stocks': {}}})

    assert brief_preflight._shares_at_date('PLTU', '2026-07-17') is None


def test_unparseable_json_is_unknown(repo, tmp_path, monkeypatch):
    repo(_portfolio(us=[('PLTU', 14)]))
    (tmp_path / 'portfolio.json').write_text('{not json', encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'portfolio.json'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.email=t@t',
                    '-c', 'user.name=t', 'commit', '-q', '-m', 'break'], check=True)

    assert brief_preflight._shares_at_date('PLTU', '2026-07-30') is None


# ── the verdict the stranded decisions were owed ─────────────────────────────

def test_never_opening_the_position_settles_as_not_followed(repo, monkeypatch):
    """The live PLTR/MSFT case: absent on both sides → no add → not_followed."""
    repo(_portfolio(us=[('PLTU', 14)]))
    monkeypatch.setattr(brief_preflight, '_shares_at_date',
                        lambda ticker, date: 0 if ticker == 'PLTR' else None)

    verdict = brief_preflight._detect_followed(
        {'plan_date': '2026-07-15', 'ticker': 'PLTR', 'bucket': 'add_only_on_trigger'}
    )

    assert verdict == 'false'


def test_opening_the_position_settles_as_followed(repo, monkeypatch):
    """Same shape, opposite fact — the fix must unstick both verdicts, not just
    the negative one, or it would bias the ledger toward not_followed."""
    repo(_portfolio(us=[('PLTU', 14)]))
    shares = {'2026-07-14': 0, '2026-07-17': 25}
    monkeypatch.setattr(brief_preflight, '_shares_at_date',
                        lambda ticker, date: shares.get(date))

    verdict = brief_preflight._detect_followed(
        {'plan_date': '2026-07-15', 'ticker': 'PLTR', 'bucket': 'add_only_on_trigger'}
    )

    assert verdict == 'true'


def test_an_unreadable_window_still_refuses_to_settle(repo, monkeypatch):
    repo(_portfolio(us=[('PLTU', 14)]))
    monkeypatch.setattr(brief_preflight, '_shares_at_date', lambda ticker, date: None)

    verdict = brief_preflight._detect_followed(
        {'plan_date': '2026-07-15', 'ticker': 'PLTR', 'bucket': 'add_only_on_trigger'}
    )

    assert verdict == 'unknown'
