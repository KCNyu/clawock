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
