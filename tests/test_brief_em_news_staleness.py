"""The Chinese-news sidecar gets the same 36h freshness gate as its siblings (#2081).

macro / sentiment / influencer are omitted when their own `generated_at` is
older than 36h; em_news.json was passed through whatever its age, so a fetch
that silently wrote nothing new fed yesterday's headlines to the brief as today's.
"""
import json
from datetime import datetime, timedelta, timezone

from clawock.harness import brief_preflight as pre


def _write(tmp_path, hours_ago):
    data = tmp_path / "assets" / "data"
    data.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    (data / "em_news.json").write_text(json.dumps({
        "generated_at": stamp,
        "holdings_news": {"00100": {"name": "MINIMAX", "items": [{"date": "2026-09-27", "title": "x"}]}},
        "market_724": [{"date": "2026-09-27", "title": "y"}],
    }), encoding="utf-8")


def test_a_stale_em_news_file_is_omitted_without_an_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(pre, "WS", tmp_path)
    _write(tmp_path, hours_ago=48)
    issues = []
    assert pre.load_em_news(issues) == {}
    assert issues == [], "stale is omitted, never an issue (an issue reds the brief)"


def test_a_fresh_em_news_file_still_reaches_the_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(pre, "WS", tmp_path)
    _write(tmp_path, hours_ago=2)
    out = pre.load_em_news([])
    assert out["holdings_news"]["00100"]["items"][0]["title"] == "x"
    assert out["age_hours"] is not None and out["age_hours"] < 3


def test_sources_that_did_not_answer_are_named_not_read_as_a_quiet_day(tmp_path, monkeypatch):
    """All sources down used to write a fresh file with empty lists: to the
    brief that is "no news today". The fetch now records which did not answer."""
    from clawock.market_data import eastmoney_news as em

    monkeypatch.setattr(em, "em_get", lambda *a, **k: None)
    monkeypatch.setattr(em, "active_hk_names", lambda *a: [("00100", "MINIMAX")])
    out = em.fetch_workspace(tmp_path, tmp_path / "em_news.json")
    assert out["holdings_news"] == {} and out["market_724"] == []
    assert out["degraded"] == ["em-search(MINIMAX): no response", "em-724: no response"]

    data = tmp_path / "assets" / "data"
    data.mkdir(parents=True)
    (data / "em_news.json").write_text((tmp_path / "em_news.json").read_text(), encoding="utf-8")
    monkeypatch.setattr(pre, "WS", tmp_path)
    issues = []
    brief = pre.load_em_news(issues)
    assert brief["degraded"] == out["degraded"] and issues == []
