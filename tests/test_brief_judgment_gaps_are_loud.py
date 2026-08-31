"""A missing or invalid judgment now costs published content, so it must be said.

Since #1232 the report's Tier 2/3, sector, macro and calibration sections are
rendered from the judgment. Before that, an absent or invalid overlay only cost
a field in the Pages sidecar, and postflight recorded it in `projection_issues`
— a key in the result JSON that nothing reads in time. A brief could therefore
ship with empty debate sections and a clean status line.
"""
import json

from clawock.harness import brief_postflight as postflight


PACKET = {
    "_meta": {"generation_id": "gen-1"},
    "tickers": {"00100": {"quant": {}, "constraints": {}}},
}


def _overlay(**overrides):
    from clawock.decision.packet import judgment_template

    overlay = judgment_template(PACKET)
    overlay["portfolio_assessment"] = "三条杠杆全破硬止损。"
    overlay["portfolio_counterargument"] = "软执行只会加码纪律债。"
    overlay["narrative"].update({
        "regime_read": "两地趋势 OFF。", "bull": "最坏定价已吃掉大半。",
        "bear": "纪律未执行是最大风险。", "devils_advocate": "共识只有单一来源。",
        "attacked_consensus": "板块仍有 alpha", "aggressive": "留一半敞口。",
        "conservative": "硬闸今天必须执行。", "neutral": "硬闸执行，其余持有。",
        "sector_read": "板块内部分化。", "macro_read": "指数小幅向下。",
        "calibration_read": "risk_rule 是唯一 edge。",
        "next_session": ["09:30 确认成交"], "data_holes": [],
    })
    for row in overlay["ticker_judgments"]:
        row.update({
            "assessment": "杠杆放大下行。", "counterargument": "反弹会踏空。",
            "rationale": "硬闸优先。", "falsifier": "收复 200 线。",
            "next_evidence": "09:30 成交。", "fundamentals": "无基本面。",
            "cross_market": "跟随指数。", "sentiment_read": "无硬催化。",
            "peer_read": "板块中位。",
        })
    overlay.update(overrides)
    return overlay


def _write(tmp_path, payload):
    path = tmp_path / "brief-judgment.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_missing_judgment_names_the_sections_that_will_be_empty(tmp_path):
    issues = postflight._judgment_gap_issues(tmp_path / "absent.json", PACKET)

    assert len(issues) == 1
    assert "缺失" in issues[0] and "Tier 2/3" in issues[0]


def test_an_unparseable_judgment_is_reported_as_such(tmp_path):
    path = tmp_path / "brief-judgment.json"
    path.write_text("{not json", encoding="utf-8")

    issues = postflight._judgment_gap_issues(path, PACKET)

    assert len(issues) == 1 and "无法解析" in issues[0]


def test_an_invalid_judgment_says_what_is_lost_and_what_is_not(tmp_path):
    """It still renders — the renderer reads what is there — but the projection
    drops the whole layer, and those are different losses."""
    overlay = _overlay()
    overlay["ticker_judgments"][0]["assessment"] = ""
    path = _write(tmp_path, overlay)

    issues = postflight._judgment_gap_issues(path, PACKET)

    assert len(issues) == 1
    assert "未通过校验" in issues[0]
    assert "assessment" in issues[0], "the operator needs the first failing field"
    assert "projection" in issues[0]


def test_a_valid_judgment_says_nothing(tmp_path):
    path = _write(tmp_path, _overlay())

    assert postflight._judgment_gap_issues(path, PACKET) == []


def test_without_a_packet_only_the_file_itself_can_be_judged(tmp_path):
    """No packet means no schema to check against; the file's presence is still
    checkable, and is the half that costs report content."""
    path = _write(tmp_path, {"schema_version": 3})

    assert postflight._judgment_gap_issues(path, None) == []
    assert postflight._judgment_gap_issues(tmp_path / "absent.json", None) != []


def test_the_issue_is_escalating_not_advisory(tmp_path):
    """Advisory issues never change the status; a report published with empty
    debate sections should not read as clean."""
    from clawock.harness.validation import is_advisory

    for issue in postflight._judgment_gap_issues(tmp_path / "absent.json", PACKET):
        assert not is_advisory(issue)
