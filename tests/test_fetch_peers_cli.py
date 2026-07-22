"""CLI contract tests for scripts/data/fetch_peers.py.

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
import subprocess
import sys
from pathlib import Path

import pytest


WS = Path(__file__).resolve().parents[1]
SCRIPT = WS / "scripts" / "data" / "fetch_peers.py"
DATA_SCRIPTS = str(WS / "scripts" / "data")


def run(args=(), stdin=""):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture(scope="module")
def fp():
    if DATA_SCRIPTS not in sys.path:
        sys.path.insert(0, DATA_SCRIPTS)
    return pytest.importorskip("fetch_peers")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_exits_zero_with_usage(flag):
    """Probing the script must never poison a cron run."""
    r = run([flag])
    assert r.returncode == 0
    assert "usage: fetch_peers.py" in r.stdout
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


def test_five_day_move_uses_the_unadjusted_series(fp, monkeypatch):
    """qfq bars would silently re-price the comparison through later splits."""
    captured = {}

    def fake_get(url, **kw):
        captured['url'] = url
        raise RuntimeError('stop here')

    monkeypatch.setattr(fp.requests, 'get', fake_get)
    out = {}
    fp._apply_pct_5d(out, 'hk00700')
    assert 'kline/kline' in captured['url']
    assert 'fqkline' not in captured['url'] and 'qfq' not in captured['url']
    assert out['error_kline']


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
