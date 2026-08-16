"""Non-held watch list scan: opportunities only, never add authorization (#556).

智谱(02513)/迅策(03317)是 kcn 关注的 AI 板块但未持仓。brief preflight 对它们
做价格面扫描,突破/接近/大涨才出现在 watch_list 段——绝不进入 decisions。
"""
import json

from clawock.decision import watch_list as W


def _wire(tmp_path, monkeypatch, sig_rows):
    watch_path = tmp_path / "config" / "watch-list.json"
    monkeypatch.setattr(W, "_watch_list_path", lambda: watch_path)
    monkeypatch.setattr(W, "_policy_near_pct", lambda: 5.0)
    watch_path.parent.mkdir(parents=True)
    watch_path.write_text(json.dumps({"tickers": list(sig_rows)}))
    metas = {
        "02513": {"name": "智谱", "tencent_symbol": "hk02513"},
        "03317": {"name": "迅策科技", "tencent_symbol": "hk03317"},
    }
    monkeypatch.setattr(W, "get_instrument", lambda t: metas.get(t) or {})
    monkeypatch.setattr(W.quant_signals, "fetch_bars", lambda code, cnt: [])
    sigs = list(sig_rows.values())
    monkeypatch.setattr(W.quant_signals, "compute_signals",
                        lambda bars: sigs.pop(0) if sigs else None)
    monkeypatch.setattr(W.quant_signals, "compute_short_history_signals",
                        lambda bars: None)


def test_collect_classifies_breakout_near_and_strong(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {
        "02513": {"close": 110.0, "prior_20d_high": 100.0},
        "03317": {"close": 98.0, "prior_20d_high": 100.0},
    })
    monkeypatch.setattr(
        W.quant_signals, "fetch_bars",
        lambda code, cnt: [{"close": 90.0} for _ in range(6)] +
                          [{"close": 98.0}] + [{"close": 99.0}] * 3,
    )

    out = W.collect()

    by = {r["ticker"]: r for r in out["rows"]}
    assert by["02513"]["state"] == "breakout"
    assert by["03317"]["state"] == "near_breakout"
    # breakout sorts before near_breakout
    assert out["rows"][0]["ticker"] == "02513"


def test_collect_omits_quiet_names(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"02513": {"close": 90.0, "prior_20d_high": 100.0}})
    monkeypatch.setattr(
        W.quant_signals, "fetch_bars",
        lambda code, cnt: [{"close": 90.0} for _ in range(10)],
    )

    assert W.collect() == {"rows": []}


def test_collect_fails_soft_on_missing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_watch_list_path",
                        lambda: tmp_path / "config" / "watch-list.json")

    assert W.watch_tickers() == []
    assert W.collect() == {"rows": []}


def test_strong_5d_appears_when_no_prior_high(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"03317": {"close": 95.0, "prior_20d_high": None}})
    monkeypatch.setattr(
        W.quant_signals, "fetch_bars",
        lambda code, cnt: [{"close": 80.0} for _ in range(5)] +
                          [{"close": 95.0}] * 5,
    )

    out = W.collect()

    assert out["rows"][0]["state"] == "strong"
    assert out["rows"][0]["ret_5d"] >= 8.0


def test_policy_near_pct_respects_explicit_zero(tmp_path, monkeypatch):
    """#649: `opportunity_near_pct: 0` ("只有真突破算机会") is legal config;
    `X or DEFAULT` would silently swallow it into 5.0."""
    cfg = tmp_path / "config" / "add-alpha-policy.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"opportunity_near_pct": 0}))
    monkeypatch.setattr(W, "workspace_root", lambda default=None: tmp_path)

    assert W._policy_near_pct() == 0.0


def test_policy_strong_5d_pct_comes_from_config(tmp_path, monkeypatch):
    """#640: `strong_5d_pct` lives in add-alpha-policy.json — editing the
    config moves the 5d gate without a code change."""
    cfg = tmp_path / "config" / "add-alpha-policy.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"strong_5d_pct": 20.0}))
    monkeypatch.setattr(W, "workspace_root", lambda default=None: tmp_path)

    assert W._policy_strong_5d_pct() == 20.0


def test_strong_state_follows_config_threshold(tmp_path, monkeypatch):
    """#640: collect() uses the configured 5d gate — an 18.75% 5d gain is
    'strong' under the 8.0 default but quiet under a 20.0 config."""
    _wire(tmp_path, monkeypatch, {"03317": {"close": 95.0, "prior_20d_high": None}})
    cfg = tmp_path / "config" / "add-alpha-policy.json"
    cfg.write_text(json.dumps({"strong_5d_pct": 20.0}))
    monkeypatch.setattr(W, "workspace_root", lambda default=None: tmp_path)
    monkeypatch.setattr(
        W.quant_signals, "fetch_bars",
        lambda code, cnt: [{"close": 80.0} for _ in range(5)] +
                          [{"close": 95.0}] * 5,
    )

    # ret_5d = (95/80 − 1)*100 = 18.75 < 20 → no row under the raised gate.
    assert W.collect() == {"rows": []}


def test_missing_instruments_entry_is_reported_not_silent(tmp_path, monkeypatch):
    """#602: a watch-list ticker absent from instruments.json must land in
    `errors` — a typo is not a permanent silent no-scan."""
    watch_path = tmp_path / "config" / "watch-list.json"
    monkeypatch.setattr(W, "_watch_list_path", lambda: watch_path)
    monkeypatch.setattr(W, "_policy_near_pct", lambda: 5.0)
    watch_path.parent.mkdir(parents=True)
    watch_path.write_text(json.dumps({"tickers": ["02513", "TYP0"]}))
    monkeypatch.setattr(
        W, "get_instrument",
        lambda t: {"name": "智谱", "tencent_symbol": "hk02513"}
        if t == "02513" else {})
    monkeypatch.setattr(W.quant_signals, "fetch_bars", lambda code, cnt: [])
    monkeypatch.setattr(W.quant_signals, "compute_signals", lambda bars: None)

    out = W.collect()

    assert any(e["ticker"] == "TYP0" for e in out.get("errors", []))
    assert [r["ticker"] for r in out["rows"]] == []


def test_completed_bars_filter_drops_the_open_bar(tmp_path, monkeypatch):
    """#621: "on completed bars" is enforced — a still-open bar (dated after
    the latest completed session) must not reach the signal computation."""
    watch_path = tmp_path / "config" / "watch-list.json"
    monkeypatch.setattr(W, "_watch_list_path", lambda: watch_path)
    monkeypatch.setattr(W, "_policy_near_pct", lambda: 5.0)
    watch_path.parent.mkdir(parents=True)
    watch_path.write_text(json.dumps({"tickers": ["02513"]}))
    monkeypatch.setattr(
        W, "get_instrument",
        lambda t: {"name": "智谱", "tencent_symbol": "hk02513", "region": "HK"})
    monkeypatch.setattr(
        W.quant_signals, "fetch_bars",
        lambda code, cnt: [{"date": "2020-01-02", "close": 10.0},
                           {"date": "2099-01-01", "close": 11.0}])
    seen = {}

    def spy_compute(bars):
        seen["dates"] = sorted(b.get("date") for b in bars)
        return None

    monkeypatch.setattr(W.quant_signals, "compute_signals", spy_compute)

    W.collect()

    assert seen["dates"] == ["2020-01-02"], seen
