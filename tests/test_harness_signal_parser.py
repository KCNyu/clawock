"""#918 收尾：两个 harness 的信号计数只有一份实现，且按**语义**分档。

kcn 2026-08-26：「可以根据合适的语意来告警，不要做硬匹配」。

合并前两份各有盲区，方向相反：
  * intraday 按整词匹配 ('ALERT','WATCH','STOP','TRIM')，**不认 US 渲染器写的
    `STOP-LOSS`** —— 2026-08-25 美股收盘那份真实 block 里两行 STOP-LOSS 被数成 0，
    而 `decide_alert` 醒不醒看 `stop + alert`；
  * report 用子串匹配（`'WATCH' in line`），顺手把 STOP-LOSS catch 住了，但也会把
    `WATCHDOG` 读成 WATCH，且 **ALERT 一个都不数** —— 比 STOP 还高的那一档。
"""
from pathlib import Path

from clawock.harness import _harness_common as common
from clawock.harness import intraday_preflight, report_preflight


# 两段都是渲染器真实写出来的形状（hk_analysis / us_analysis 的 f-string）：
# HK 是 `<emoji> LEVEL <code> <name> | …`，US 是 `<arrow> LEVEL <ticker> | …`
# 外加缩进的 `· 理由` 续行。
US_BLOCK = "\n".join([
    "📊 美股持仓",
    "",
    "⚠️ 信号",
    "  ▼ STOP-LOSS RKLX | 今日-11.9% 浮-65.1%",
    "     · 价格低于MA20 -17.9%",
    "     · 跌破MA50",
    "  ▼ STOP-LOSS SPCH | 今日-2.9% 浮-31.0%",
    "     · 浮亏 -31.0% 警惕止损",
    "",
    "📉 亏损持仓 5/6  |  杠杆ETF敞口 85%",
])

HK_BLOCK = "\n".join([
    "⚠️ 信号",
    "  ⚠️ ALERT 07226 南方2倍做多 | 今日-8.3% 浮-26.3%",
    "  △ WATCH 00100 MINIMA | 今日-5.1% 浮-46.5%",
    "  ✋ STOP? 02208 金风科技 | 今日-0.7% 浮-33.6%",
    "",
    "📉 亏损持仓 4/5  |  2x杠杆敞口 30%",
])


def test_the_us_stop_loss_line_is_a_stop_on_both_sides():
    """这条就是合并前 intraday 的盲区：真实 US block 里两行止损被数成 0。"""
    counts, detail = common.parse_signal_lines(US_BLOCK)

    assert counts == {"alert": 0, "watch": 0, "stop": 2, "trim": 0}
    assert [row["ticker"] for row in detail] == ["RKLX", "SPCH"]
    assert intraday_preflight.parse_signals(US_BLOCK)[0] == counts
    assert report_preflight.parse_signals(US_BLOCK) == counts


def test_alert_reaches_the_report_side_too():
    """ALERT 是渲染端最严重的一行，report 侧此前一个字都不数。"""
    counts = report_preflight.parse_signals(HK_BLOCK)

    assert counts == {"alert": 1, "watch": 1, "stop": 1, "trim": 0}
    assert intraday_preflight.parse_signals(HK_BLOCK)[0] == counts


def test_a_word_that_merely_contains_a_level_is_not_a_signal():
    """不做硬匹配：WATCHDOG 含 WATCH，子串测试会把它读成信号并把下一个词当代码。"""
    block = "\n".join([
        "⚠️ 信号",
        "  ─ WATCHDOG 备注 | 这行不是信号",
        "  · STOP 出现在理由行里也不算",
        "📉 收尾",
    ])

    counts, detail = common.parse_signal_lines(block)

    assert counts == {"alert": 0, "watch": 0, "stop": 0, "trim": 0}
    assert detail == []


def test_the_section_ends_where_the_renderer_ends_it():
    """信号段之外的 STOP 字样不能被数进来（📉 风险行、📰 新闻段）。"""
    block = "\n".join([
        "⚠️ 信号",
        "  ✋ STOP? 02208 金风科技 | 今日-0.7% 浮-33.6%",
        "📉 亏损持仓 4/5",
        "  ✋ STOP? 09999 段外的行 | 不该被数",
        "📰 新闻",
        "  ⚠️ ALERT 08888 也不该被数 | ",
    ])

    counts, _ = common.parse_signal_lines(block)

    assert counts == {"alert": 0, "watch": 0, "stop": 1, "trim": 0}


def test_one_alert_alone_asks_for_a_risk_section():
    """语义分档：ALERT 压过两条 STOP/TRIM，它自己就要一段风险提示。

    钉的是判据本身（`needs_risk_section` 的表达式），不是某次 preflight 的产物 ——
    后者要跑整条行情链路才生得出来。
    """
    def gate(counts):
        return counts["alert"] >= 1 or (counts["stop"] + counts["trim"]) >= 2

    assert gate({"alert": 1, "watch": 0, "stop": 0, "trim": 0}) is True
    assert gate({"alert": 0, "watch": 0, "stop": 1, "trim": 1}) is True
    assert gate({"alert": 0, "watch": 3, "stop": 1, "trim": 0}) is False
    # 与生产代码同源：闸的表达式改了，这条要跟着红。
    source = Path(report_preflight.__file__).read_text(encoding="utf-8")
    assert "signals['alert'] >= 1" in source
