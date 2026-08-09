"""The morning brief's known catalyst survives into the intraday mover context."""
from __future__ import annotations

import json
from pathlib import Path

from clawock import known_catalysts as kc


TODAY = "2026-08-06"


def _write_brief(tmp_path: Path):
    (tmp_path / f"brief-context-{TODAY}.json").write_text(json.dumps({
        "date": TODAY,
        "catalysts": {"scheduled_events": [
            {
                "ticker": "00100",
                "type": "stock_connect_inclusion",
                "date": None,
                "date_confidence": "unconfirmed",
                "detail": "上交所 8/5 公告港股通标的名单调入 MINIMAX-W",
                "source": "上交所公告 2026-08-05",
            },
            {"ticker": "RKLB", "type": "earnings", "detail": "8/10 盘后财报"},
        ]},
    }, ensure_ascii=False), encoding="utf-8")


def test_yesterday_announcement_is_carried_for_todays_mover(tmp_path):
    _write_brief(tmp_path)
    result = kc.for_movers(["00100"], today=TODAY, tmp_dir=tmp_path)
    event = result["00100"][0]
    assert "港股通" in event["detail"]
    assert event["source"] == "上交所公告 2026-08-05"
    assert event["provenance"] == "daily_brief"


def test_context_is_mover_scoped_and_date_exact(tmp_path):
    _write_brief(tmp_path)
    assert set(kc.for_movers(["00100"], today=TODAY, tmp_dir=tmp_path)) == {"00100"}
    assert kc.for_movers(["00100"], today="2026-08-07", tmp_dir=tmp_path) == {}


def test_missing_or_corrupt_brief_fails_soft(tmp_path):
    assert kc.for_movers(["00100"], today=TODAY, tmp_dir=tmp_path) == {}
    (tmp_path / f"brief-context-{TODAY}.json").write_text("{broken", encoding="utf-8")
    assert kc.for_movers(["00100"], today=TODAY, tmp_dir=tmp_path) == {}
