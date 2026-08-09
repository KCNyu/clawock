"""CLI contract tests for ``clawock fetch-peers``.

The script is stdin-driven and takes no options, so an agent probing it with
``--help`` used to fall through to ``json.loads('')`` and exit 1 — a non-zero
Bash call that OpenClaw promotes into a run-level cron error even when the run
otherwise succeeds (2026-07-22, 港股开盘报告).  These tests pin the contract:
probing is safe, but a genuinely broken request is still a real failure.

No network is touched: every case either short-circuits before fetching or
sends an explicit empty request.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


WS = Path(__file__).resolve().parents[1]
PACKAGE_SRC = str(WS / "src")


def run(args=(), stdin=""):
    return subprocess.run(
        [sys.executable, "-m", "clawock.cli", "fetch-peers", *args],
        input=stdin, capture_output=True, text=True, timeout=60,
        cwd=WS,
        env={**os.environ, "PYTHONPATH": PACKAGE_SRC},
    )


@pytest.fixture(scope="module")
def fp():
    return pytest.importorskip("clawock.fetch_peers")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_exits_zero_with_usage(flag):
    """Probing the script must never poison a cron run."""
    r = run([flag])
    assert r.returncode == 0
    assert "usage: clawock fetch-peers" in r.stdout
    assert "stdin" in r.stdout


def test_unknown_args_exit_two_and_do_not_fetch():
    """A typo alongside valid input must fail loudly, not look like success."""
    r = run(["--peers", "00020"], stdin='[{"ticker": "00020", "region": "hk"}]')
    assert r.returncode == 2
    assert "unrecognized arguments" in r.stderr
    assert r.stdout.strip() == ""


def test_empty_stdin_is_a_real_failure_on_stderr():
    """The only caller always pipes a non-empty request, so empty means broken."""
    r = run(stdin="")
    assert r.returncode == 1
    assert "empty stdin" in r.stderr
    assert r.stdout.strip() == ""


def test_explicit_empty_array_succeeds():
    r = run(stdin="[]")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["peers"] == {}
    assert payload["requested"] == 0


def test_malformed_json_fails_with_stderr_diagnostic():
    r = run(stdin="{not json")
    assert r.returncode == 1
    assert "not valid JSON" in r.stderr
    assert r.stdout.strip() == ""


@pytest.mark.parametrize(
    "payload, expected",
    [
        ('{"ticker": "00020"}', "expected a JSON array"),
        ("[42]", "expected an object"),
        ("[{}]", 'missing or empty "ticker"'),
        ('[{"ticker": ""}]', 'missing or empty "ticker"'),
        ('[{"ticker": "00020", "region": "cn"}]', "region must be one of"),
    ],
)
def test_schema_violations_fail(payload, expected):
    r = run(stdin=payload)
    assert r.returncode == 1
    assert expected in r.stderr


def test_parse_request_defaults_region_to_us(fp):
    peers, err = fp.parse_request('[{"ticker": "NVDA"}]')
    assert err is None
    assert peers == [{"ticker": "NVDA"}]


def test_quote_age_flags_a_frozen_line(fp):
    """usSQ keeps answering with Block's 2026-02 price at 0.00% — worse than a gap."""
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=163)).strftime('%Y-%m-%d %H:%M:%S')
    out = {}
    fp._apply_quote_age(out, [''] * 30 + [old])
    assert out['quote_time'] == old
    assert '163d old' in out['stale_quote']


def test_quote_age_accepts_a_fresh_line_in_either_format(fp):
    from datetime import datetime
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S'):
        out = {}
        fp._apply_quote_age(out, [''] * 30 + [datetime.now().strftime(fmt)])
        assert 'stale_quote' not in out
        assert out['quote_time']


def test_five_day_move_uses_the_adjusted_series(fp, monkeypatch):
    """A split inside the window would read as a phantom ±50% move on raw bars.

    Opposite of fetch_daily_bars.py, which stores raw bars because a historical
    trigger price must stay nominal. This is a return, so it needs qfq.
    """
    captured = {}

    def fake_get(url, **kw):
        captured['url'] = url
        raise RuntimeError('stop here')

    monkeypatch.setattr(fp.requests, 'get', fake_get)
    out = {}
    fp._apply_pct_5d(out, 'hk00700')
    assert 'fqkline/get' in captured['url'] and captured['url'].endswith(',qfq')
    assert out['error_kline']


def test_closes_prefer_qfqday_over_day(fp, monkeypatch):
    """Tencent only emits qfqday when an adjustment actually happened."""
    class R:
        @staticmethod
        def json():
            return {'data': {'hk00700': {
                'qfqday': [['d', '1', '10.0'], ['d', '1', '11.0']],
                'day':    [['d', '1', '99.0'], ['d', '1', '98.0']],
            }}}

    monkeypatch.setattr(fp.requests, 'get', lambda *a, **kw: R())
    assert fp.tencent_closes('hk00700') == [10.0, 11.0]


def test_budget_preserves_fast_results_and_marks_late_workers(
        fp, monkeypatch):
    """The batch returns completed work and marks every unfinished request.

    Keep this hermetic: real providers can answer before a 50 ms deadline, so
    using invented tickers makes the expected result depend on network latency.
    The direct `_req_timeout` and process-level tests below cover the timeout
    clamp and uncooperative-worker cases separately.
    """
    import threading
    import time

    release = threading.Event()

    def fake_fetch(ticker, deadline=None):
        if ticker == 'FAST':
            return {'ticker': ticker, 'region': 'hk', 'price': 1.0}
        release.wait(timeout=1)
        return {'ticker': ticker, 'region': 'hk', 'price': 1.0}

    monkeypatch.setattr(fp, 'fetch_hk_one', fake_fetch)
    req = [
        {'ticker': 'FAST', 'region': 'hk'},
        *[{'ticker': f'SLOW{i}', 'region': 'hk'} for i in range(9)],
    ]
    started = time.monotonic()
    try:
        results = fp.fetch_all(req, deadline_s=0.05, workers=2)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert elapsed < 2.0, f'budget not enforced: took {elapsed:.2f}s'
    assert len(results) == 10
    assert results['FAST']['price'] == 1.0
    assert all(
        'error_deadline' in results[f'SLOW{i}']
        for i in range(9)
    )


def test_exhausted_budget_raises_before_issuing_a_request(fp):
    import time
    with pytest.raises(fp.BudgetExhausted):
        fp._req_timeout(time.monotonic() - 1)
    assert fp._req_timeout(None) == fp.TIMEOUT
    assert fp._req_timeout(time.monotonic() + 1000) == fp.TIMEOUT


def test_request_timeout_shrinks_to_the_remaining_budget(fp):
    """The clamp is the whole enforcement — returning TIMEOUT flat re-breaks it."""
    import time
    left = fp._req_timeout(time.monotonic() + 0.5)
    assert left < fp.TIMEOUT, 'per-request timeout must shrink near the deadline'
    assert 0 < left <= 0.5


def test_a_slow_worker_cannot_overrun_the_budget(fp, monkeypatch):
    """Executor shutdown waits for running workers, so this is not hypothetical."""
    import time

    def slow(ticker, deadline=None):
        # Mimics a provider that hangs: sleeps for whatever timeout it is handed.
        time.sleep(fp._req_timeout(deadline))
        return {'ticker': ticker, 'region': 'hk', 'price': 1.0}

    monkeypatch.setattr(fp, 'fetch_hk_one', slow)
    req = [{'ticker': f'T{i}', 'region': 'hk'} for i in range(4)]
    started = time.monotonic()
    fp.fetch_all(req, deadline_s=0.3, workers=2)
    elapsed = time.monotonic() - started
    assert elapsed < fp.TIMEOUT / 2, f'worker overran the budget: {elapsed:.2f}s'


def test_process_exits_despite_an_uncooperative_worker():
    """The budget must hold at PROCESS level, not just inside fetch_all.

    `requests`' timeout is an inactivity timeout, so a provider that trickles
    bytes outlives its clamp; and executor threads are non-daemon, so the
    interpreter joins them at exit. The caller reads our stdout to EOF, so a
    lingering thread holds *its* 120s timeout open and discards JSON we already
    wrote. This worker ignores the deadline entirely — the previous cooperative
    test (it slept exactly `_req_timeout`) could not catch that.
    """
    import subprocess
    import textwrap
    import time

    program = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {PACKAGE_SRC!r})
        from clawock import fetch_peers as fp

        def uncooperative(ticker, deadline=None):
            time.sleep(30)                      # never looks at the deadline
            return {{'ticker': ticker, 'region': 'hk', 'price': 1.0}}

        fp.fetch_hk_one = uncooperative
        req = [{{'ticker': 'T%d' % i, 'region': 'hk'}} for i in range(4)]
        results = fp.fetch_all(req, deadline_s=0.05, workers=4)
        print('DONE', len(results), flush=True)
        fp.hard_exit(0)
    """)

    started = time.monotonic()
    r = subprocess.run([sys.executable, '-c', program],
                       capture_output=True, text=True, timeout=25)
    elapsed = time.monotonic() - started

    assert r.returncode == 0
    assert 'DONE 4' in r.stdout, 'partial results must still reach the caller'
    assert elapsed < 10, f'process did not exit on time: {elapsed:.2f}s'


def test_duplicate_tickers_resolve_deterministically(fp, monkeypatch):
    """Results are keyed by ticker; concurrency must not decide who wins."""
    peers = [{'ticker': 'A', 'region': 'us'}, {'ticker': 'A', 'region': 'hk'},
             {'ticker': 'B', 'region': 'us'}]
    unique, dropped = fp.dedupe(peers)
    assert [p['ticker'] for p in unique] == ['A', 'B']
    assert unique[0]['region'] == 'us', 'first occurrence must win'
    assert dropped == ['A']

    # …and fetch_all must actually apply it, not just expose the helper.
    monkeypatch.setattr(fp, 'fetch_hk_one',
                        lambda t, deadline=None: {'ticker': t, 'region': 'hk'})
    monkeypatch.setattr(fp, 'fetch_us_one',
                        lambda t, deadline=None: {'ticker': t, 'region': 'us'})
    results = fp.fetch_all(peers)
    assert list(results) == ['A', 'B']
    assert results['A']['region'] == 'us', 'the later duplicate must not win the key'


def test_five_day_move_needs_six_bars(fp, monkeypatch):
    monkeypatch.setattr(fp, 'tencent_closes', lambda sym, **kw: [1.0, 2.0, 3.0])
    out = {'price': 3.0}
    fp._apply_pct_5d(out, 'usSOXL.AM')
    assert 'pct_5d' not in out
    assert 'short history' in out['error_kline']

    monkeypatch.setattr(fp, 'tencent_closes', lambda sym, **kw: [10.0, 1, 2, 3, 4, 11.0])
    out = {'price': 11.0}
    fp._apply_pct_5d(out, 'usSOXL.AM')
    assert out['pct_5d'] == 10.0


def test_peer_map_tickers_are_well_formed():
    """HK peers must be 5-digit codes — a malformed one silently prices nothing."""
    pmap = json.loads((WS / "memory" / "peer-map.json").read_text())
    for holding, info in pmap["holdings"].items():
        for peer in info.get("listed_peers", []):
            assert peer["region"] in ("hk", "us"), (holding, peer)
            assert peer.get("name"), (holding, peer)
            if peer["region"] == "hk":
                assert peer["ticker"].isdigit() and len(peer["ticker"]) == 5, (holding, peer)
