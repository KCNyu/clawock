import json
import sys
from datetime import date as real_date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock.decision import setup_review as review  # noqa: E402


class _HistoryStub:
    def __init__(self, rows):
        self._text = "\n".join(json.dumps(row) for row in rows)

    def exists(self):
        return True

    def read_text(self):
        return self._text


class _FixedDate:
    @classmethod
    def today(cls):
        return real_date(2026, 7, 26)


def _run(monkeypatch, days):
    captured = {}
    monkeypatch.setattr(review, "HIST", _HistoryStub(days))
    monkeypatch.setattr(
        review, "safe_write_json",
        lambda _path, data, indent=2: captured.setdefault("data", data),
    )
    monkeypatch.setattr(review, "date", _FixedDate)
    review.main()
    return captured["data"]


def _two_day_fixture():
    first = {}
    second = {}
    for i in range(20):
        first[f"C{i}"] = {"grade_label": "追高低质", "close": 100.0}
        second[f"C{i}"] = {"grade_label": "", "close": 90.0}
        first[f"O{i}"] = {"grade_label": "低位/超卖", "close": 100.0}
        second[f"O{i}"] = {"grade_label": "", "close": 90.0}
    for i in range(5):
        first[f"E{i}"] = {"grade_label": "偏高位", "close": 100.0}
        second[f"E{i}"] = {"grade_label": "", "close": 90.0}
    return [
        {"as_of": "2026-07-23", "rows": first},
        {"as_of": "2026-07-24", "rows": second},
    ]


def test_sample_count_and_edge_support_are_separate_gates(monkeypatch):
    result = _run(monkeypatch, _two_day_fixture())

    chase = result["grades"]["chase_low_quality"]
    assert chase["sample_sufficient"] is True
    assert chase["edge_supported"] is True
    assert chase["usable"] is True

    oversold = result["grades"]["oversold_low"]
    assert oversold["sample_sufficient"] is True
    assert oversold["edge_supported"] is False
    assert oversold["reverse_edge_supported"] is True
    assert oversold["decision_direction"] is None
    assert oversold["usable"] is False
    assert "相反方向" in oversold["note"]


def test_small_sample_never_unlocks_even_with_perfect_hits(monkeypatch):
    result = _run(monkeypatch, _two_day_fixture())
    elevated = result["grades"]["elevated"]

    assert elevated["n"] == 5
    assert elevated["sample_sufficient"] is False
    assert elevated["usable"] is False
    assert elevated["note"] == "样本不足，不得当结论引用方向"


def test_weekend_rows_never_settle_and_are_disclosed(monkeypatch):
    """#1050: 周五触发顺延到周一结算；周六幽灵行不产生观测且被披露。

    闭市日报价源漂移（Sat 收盘既不等于 Fri 也不等于 Mon），跨它算出的
    forward return 是伪观测——旧实现会给 n=40（含 Sat→Mon 的伪对）。
    """
    fri = {f"C{i}": {"grade_label": "追高低质", "close": 100.0} for i in range(20)}
    sat = {f"C{i}": {"grade_label": "追高低质", "close": 101.0} for i in range(20)}
    mon = {f"C{i}": {"grade_label": "", "close": 90.0} for i in range(20)}
    days = [
        {"as_of": "2026-08-07", "rows": fri},   # 周五：触发，顺延周一结算
        {"as_of": "2026-08-08", "rows": sat},   # 周六：幽灵行，不产生观测
        {"as_of": "2026-08-10", "rows": mon},   # 周一：真实下一时段
    ]
    result = _run(monkeypatch, days)

    chase = result["grades"]["chase_low_quality"]
    assert chase["n"] == 20                      # 只有周五的触发入账
    assert chase["hit_rate"] == 1.0              # 100→90 跌，direction=-1 全命中
    assert result["weekend_rows_excluded"] == 20  # 周六行的 20 条触发被剔除


def test_weekend_only_history_produces_no_observations(monkeypatch):
    """全部留痕都落在周末时，任何牌面都不产生观测、不得解锁。"""
    sat = {f"C{i}": {"grade_label": "追高低质", "close": 100.0} for i in range(20)}
    sun = {f"C{i}": {"grade_label": "", "close": 50.0} for i in range(20)}
    result = _run(monkeypatch, [
        {"as_of": "2026-08-08", "rows": sat},
        {"as_of": "2026-08-09", "rows": sun},
    ])
    chase = result["grades"]["chase_low_quality"]
    assert chase["n"] == 0
    assert chase["usable"] is False
    assert result["weekend_rows_excluded"] == 20
