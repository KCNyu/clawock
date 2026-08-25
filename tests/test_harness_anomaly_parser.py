"""#918：≥3% 异动行只有一份解析实现。

report_preflight 与 intraday_preflight 曾各存一份逐行相同的表格解析，且两份
输出的每行字段已经漂开（severity vs reason）。合并的判据不是「代码短了」，
而是「两边读到的东西不变，且改一次表格形状不用改两处」。
"""
from clawock.harness import _harness_common, intraday_preflight, report_preflight


TABLE = "\n".join([
    "| 代码 | 股数 | 成本 | 现价 | 今日 | 盈亏% | 盈亏 |",
    "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    "| 00100 | 60 | 822.83 | 722.00 | +5.1% | -12.2% | -6,050 |",
    "| RKLB |  5 |  71.00 | 134.28 | -3.2% | +89.1% |   +316 |",
    "| SPCX |  9 | 135.00 | 138.00 | +0.4% |  +2.2% |    +27 |",
    "not a table row at all",
])


def test_both_preflights_read_the_same_rows():
    assert (intraday_preflight.parse_anomalies(TABLE)
            == report_preflight.parse_anomalies(TABLE)
            == _harness_common.parse_holdings_anomalies(TABLE))


def test_the_row_keeps_every_key_either_side_used_to_emit():
    rows = _harness_common.parse_holdings_anomalies(TABLE)

    assert [r["ticker"] for r in rows] == ["00100", "RKLB"], "≥3% 才算，表头/分隔行不算"
    severe, mild = rows
    # intraday 侧读 severity（下游 add_side 也读它）；report 侧读 reason。
    assert (severe["severity"], severe["reason"]) == ("high", "跳空/异动")
    assert (mild["severity"], mild["reason"]) == ("medium", "日内大幅波动")
    # 方向保留在符号里，不在文案里。
    assert severe["move_pct"] == 5.1 and mild["move_pct"] == -3.2


def test_the_thresholds_are_named_not_scattered():
    assert _harness_common.ANOMALY_MOVE_PCT == 3.0
    assert _harness_common.ANOMALY_SEVERE_PCT == 5.0
    # 边界：正好 3.0% 算异动，2.9% 不算（合并前后同一条闸）。
    at_floor = "| AAA | 1 | 1.00 | 1.00 | +3.0% | +0.0% | 0 |"
    below = "| BBB | 1 | 1.00 | 1.00 | +2.9% | +0.0% | 0 |"
    assert [r["ticker"] for r in _harness_common.parse_holdings_anomalies(at_floor)] == ["AAA"]
    assert _harness_common.parse_holdings_anomalies(below) == []
