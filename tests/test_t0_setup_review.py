import json
import sys
from datetime import date as real_date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))
from clawock import t0_setup_review as review  # noqa: E402


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
        {"as_of": "2026-07-24", "rows": first},
        {"as_of": "2026-07-25", "rows": second},
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
