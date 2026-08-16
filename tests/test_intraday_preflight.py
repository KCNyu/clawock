"""Intraday preflight helpers: alert rule, fail-soft setup collection, receipt (#554).

Mode 7 runs 8 HK + 10 US slots per trading day. The alert rule decides whether
a slot wakes kcn, `collect_provisional_setups` must never red a cron when the
quote feed fails, and the unchanged receipt is the common-case push — its
wording is the only thing most slots ever say.
"""
import pytest

from clawock.harness import intraday_preflight as P


# ── decide_alert: what wakes kcn ────────────────────────────────────────────

def test_anomaly_alone_wakes():
    should, reasons = P.decide_alert(
        {"alert": 0, "watch": 0, "stop": 0, "trim": 0},
        [{"ticker": "00100", "move_pct": -5.1}],
    )
    assert should is True
    assert any("异动" in r for r in reasons)


def test_two_signals_without_anomaly_wake():
    should, _ = P.decide_alert(
        {"alert": 0, "watch": 2, "stop": 0, "trim": 0}, [],
    )
    assert should is True


def test_stop_or_alert_alone_wakes():
    assert P.decide_alert(
        {"alert": 0, "watch": 0, "stop": 1, "trim": 0}, [])[0] is True
    assert P.decide_alert(
        {"alert": 1, "watch": 0, "stop": 0, "trim": 0}, [])[0] is True


def test_single_watch_does_not_wake():
    should, reasons = P.decide_alert(
        {"alert": 0, "watch": 1, "stop": 0, "trim": 0}, [],
    )
    assert should is False
    assert reasons == []


# ── collect_provisional_setups: fail-soft by value ─────────────────────────

def test_setup_collection_passes_through(monkeypatch):
    expected = {"rows": [{"label": "CRCL", "setup_id": "x"}],
                "confirmed_at_close": False}
    monkeypatch.setattr(
        P.quant_signals, "provisional_setups", lambda **kwargs: expected)

    assert P.collect_provisional_setups("us") == expected


def test_setup_collection_never_reds_the_cron(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("quote feed down")

    monkeypatch.setattr(P.quant_signals, "provisional_setups", boom)

    out = P.collect_provisional_setups("hk")
    assert out["rows"] == []
    assert out["confirmed_at_close"] is False
    assert out["errors"] and out["errors"][0]["error"].startswith("RuntimeError")


# ── render_unchanged_receipt: the common-case wording ──────────────────────

def test_receipt_states_no_conditions_and_refresh_counts():
    block = "🇭🇰 港股盯盘 | 08/14 15:30 HKT\n| 00100 | 120 | ..."
    text = P.render_unchanged_receipt("hk", block, {
        "refreshed": 3, "active": 4, "unrefreshed": [],
    }, {"collection": {"cache_hit": False}})

    assert text.startswith("🇭🇰 港股盯盘 | 08/14 15:30 HKT")
    assert "本轮无新的加仓/减仓条件" in text
    assert "3/4" in text


def test_receipt_names_unrefreshed_and_degraded_sources():
    text = P.render_unchanged_receipt("us", "🇺🇸 美股盯盘", {
        "refreshed": 2, "active": 4, "unrefreshed": ["SPCH"],
    }, {"collection": {}, "degraded_issuers": ["BAD"], "partial": []})

    assert "未证实本轮刷新：SPCH" in text
    assert "一级源降级：BAD" in text


def test_receipt_uses_cache_source_when_collection_was_cached():
    text = P.render_unchanged_receipt("hk", "🇭🇰 港股盯盘", {
        "refreshed": 1, "active": 1, "unrefreshed": [],
    }, {"collection": {"cache_hit": True}})

    assert "一级信息缓存复核" in text


# ── _load_json: the #612 non-dict guard, pinned (#644) ─────────────────────

def test_load_json_returns_empty_for_non_dict_payload(tmp_path):
    """#644: a file that parses to a non-dict (e.g. a list) is treated as
    absent — the #612 guard must stay pinned by a test, or a refactor that
    drops the `isinstance(value, dict)` check silently reds the whole
    preflight the next time a list-shaped file appears."""
    path = tmp_path / "config" / "add-alpha-policy.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]")

    assert P._load_json(path) == {}


def test_load_json_returns_empty_for_missing_file(tmp_path):
    assert P._load_json(tmp_path / "nope.json") == {}


def test_load_json_returns_dict_as_is(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text('{"a": 1}')

    assert P._load_json(path) == {"a": 1}
