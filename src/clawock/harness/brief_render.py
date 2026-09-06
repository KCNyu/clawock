"""Render the daily deep brief from the context and the model's judgment.

Until now the model wrote `memory/{date}-pre-open.md` itself: every table, every
heading, every ornament.  Two things followed from that, and both are why this
module exists.

The layout drifted.  Section order, table widths, how a number was emphasised
and where the reasoning stopped and the data started all changed from day to
day, because they were re-decided from scratch every morning by a model whose
job that was never supposed to be.

And the reasoning leaked.  A model asked to produce a finished document tends to
show its work inside it — the deliberation that belongs in the debate section
spreads into the tables, and a reader looking for "what do I do at 09:30" reads
paragraphs of thinking to find it.

So the split is now literal: the model writes the judgment JSON — assessments,
the bull and bear cases, the risk voices, the reads — and nothing else, with
`packet._layout_violation` refusing any markdown that shows up in those fields.
Every heading, table, ordering and number in the published brief is produced
here, from the deterministic context and the validated plan.  Same facts every
day, in the same place on the page.
"""
from __future__ import annotations

import argparse
import json
from datetime import date as _date
from pathlib import Path

from clawock.scheduling import BRIEF_SLOT_HKT

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
VOICE_LABELS = {
    "aggressive": "Aggressive（抓 upside）",
    "conservative": "Conservative（保本 derisk）",
    "neutral": "Neutral（拍中线）",
}
# Verdict is the one categorical column in the Confidence table, and it was
# plain text: ten rows of 看多/看空/中性 that had to be read line by line to see
# which way the book leaned (#1272).  The cell is now a badge: a glyph and the
# label inside a class the stylesheet tints.
#
# The glyph is not decoration, it is the portable half.  The brief is read on
# three surfaces: GitHub Pages renders the markdown through kramdown and gets
# the CSS class (`site/_layouts/default.html` maps `.verdict-*` onto the same
# --green/--red tokens the dashboard uses, so the colour follows the reader's
# light/dark preference); GitHub's own markdown sanitiser drops `class` and
# `style` and keeps the inner text; a plain-text reader sees neither.  A glyph
# inside the span survives all three, which a hardcoded `#10b981` — the issue's
# suggestion — survives in exactly none of them, and would be wrong in one of
# the two themes even where it did land.
VERDICT_LABELS = {
    "bullish": {"label": "看多", "glyph": "🟢"},
    "bearish": {"label": "看空", "glyph": "🔴"},
    "neutral": {"label": "中性", "glyph": "⚪"},
    "mixed": {"label": "分歧", "glyph": "🟠"},
}
MISSING = "—"


# --- formatting primitives -------------------------------------------------
# Every number in the brief goes through one of these, so a percentage looks the
# same in the header as it does in the last table.  That consistency is the
# whole point of moving rendering out of the model.

def _numeric(value):
    """A number, or None when the field is absent or is not one.

    Context and plan fields are producer-owned and occasionally arrive as text
    ("4500" for a watch level, or a note where a level was expected). Rendering
    is the wrong place to reject that: the brief still has to go out, so a
    non-number falls through to its own string rather than raising.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def pct(value, digits=2, sign=True):
    number = _numeric(value)
    if number is None:
        return MISSING if value is None else str(value)
    return f"{number:+.{digits}f}%" if sign else f"{number:.{digits}f}%"


def money(value, currency="", digits=0):
    number = _numeric(value)
    if number is None:
        return MISSING if value is None else str(value)
    body = f"{number:,.{digits}f}"
    return f"{currency}{body}" if currency else body


def num(value, digits=2):
    number = _numeric(value)
    if number is None:
        return MISSING if value is None else str(value)
    return f"{number:,.{digits}f}"


def text(value):
    """A model field on its way into a table cell.

    The validator already refused pipes and newlines-as-layout, so this only has
    to answer for an absent field: a blank cell is a hole in the report and must
    read as one rather than as an empty-looking judgment.
    """
    value = (value or "").strip()
    return value.replace("\n", " ") if value else MISSING


def table(headers, rows):
    """A markdown table with a fixed column count.

    Rows shorter than the header are padded rather than silently misaligned —
    a ragged table was one of the recurring symptoms of model-authored layout.
    """
    width = len(headers)
    out = ["| " + " | ".join(_cell(header) for header in headers) + " |",
           "|" + "|".join(["---"] * width) + "|"]
    for row in rows:
        cells = [_cell(cell) for cell in row][:width]
        cells += [MISSING] * (width - len(cells))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _cell(value):
    """One table cell, escaped so its content cannot become layout.

    Not every string reaching a table is judgment-gated: a news headline out of
    the sentiment feed ("Hong Kong Stock Market Alert | MINIMAX...") and a plan
    rationale both arrive with whatever punctuation they have. An unescaped pipe
    there adds a column to that one row, which is precisely the ragged-table
    failure this module exists to end.
    """
    return str(value).replace("|", "\\|").replace("\n", " ")


def _holdings(context, leg):
    portfolios = ((context.get("portfolio") or {}).get("portfolios") or {})
    book = portfolios.get(f"{leg}_stocks") or {}
    held = [row for row in (book.get("holdings") or []) if (row.get("shares") or 0) > 0]
    return book, held


def _judgments(judgment):
    return {
        str(row.get("ticker")): row
        for row in (judgment.get("ticker_judgments") or [])
    }


def _narrative(judgment):
    return judgment.get("narrative") or {}


# --- sections --------------------------------------------------------------

def header_section(context, judgment):
    book = context.get("book_totals") or {}
    fx = context.get("fx") or {}
    macro = context.get("macro") or {}
    regime = (macro.get("regime") or {}).get("label")
    hk_book, _ = _holdings(context, "hk")
    us_book, _ = _holdings(context, "us")

    lines = ["### 双币账本（HK + USD 不能直接相加）", ""]
    lines.append(f"**🧭 Regime**: {text(regime)} · {text(_narrative(judgment).get('regime_read'))}")
    lines.append("")
    lines.append(
        f"**FX**: USDHKD = **{num(fx.get('rate'), 4)}**"
        f"（{text(fx.get('source'))}，抓取于 {text(fx.get('fetched_at'))}）")
    lines.append("")
    lines.append("```")
    lines.append(f"真实总浮亏: USD${money(book.get('usd_base_total'), digits=2)}"
                 f"  ≈  HKD${money(book.get('hkd_base_total'), digits=2)}")
    lines.append(f"  ├─ HK 段: HKD${money(book.get('hk_pnl_hkd'), digits=2)}"
                 f"  ({pct(hk_book.get('total_pnl_percent'))})")
    lines.append(f"  └─ US 段: USD${money(book.get('us_pnl_usd'), digits=2)}"
                 f"  ({pct(us_book.get('total_pnl_percent'))})")
    lines.append(f"HK 现金: {money(hk_book.get('cash_hkd'))} HKD"
                 f" | US 现金: {money(us_book.get('cash_usd'), digits=2)} USD")
    lines.append("```")
    return "\n".join(lines)


def concentration_section(context):
    rows = []
    for leg in ("hk", "us"):
        row = (context.get("concentration") or {}).get(leg) or {}
        rows.append([
            leg.upper(),
            num(row.get("hhi"), 3),
            text(row.get("verdict")),
            pct(row.get("top2_pct"), sign=False),
            money(row.get("leg_total"), digits=0),
        ])
    return "### 集中度\n\n" + table(
        ["Leg", "HHI", "判定", "Top2", "腿总值"], rows)


def _track_record_line(context, actions):
    """One line: how this kind of advice has actually settled.

    A cut printed at confidence 0.92 reads differently beside "历史 52.6%
    (n=213)", and the number was already in the ledger — it just never appeared
    next to the sentence it qualifies.
    """
    record = (context.get("action_track_record") or {}).get("by_action") or {}
    parts = []
    for action in actions:
        seat = record.get(action) or {}
        if not seat.get("settled"):
            continue
        parts.append(f"`{action}` {seat['hit_rate'] * 100:.1f}% "
                     f"({seat['win']}胜/{seat['loss']}负, n={seat['settled']}"
                     + (f", 未触发 {seat['not_triggered']}" if seat.get("not_triggered") else "")
                     + ")")
    if not parts:
        return "_历史命中率：台账里还没有已结算样本_"
    return ("**这类建议的历史命中率**（T+1，假设成交）：" + " · ".join(parts)
            + "　— 命中率不是执行理由，是读这条建议时的先验")


def opportunity_section(context):
    """The add side, printed whether or not it has anything to say.

    Before 2026-09-05 this section did not exist and neither did its input: the
    brief context held 34 fields, all of them risk or state, so a breakout the
    bar store had recorded could not reach the model that writes the day's
    decisions. Between 07-20 and 09-05 that was 48 close-confirmed breakouts
    across 18 names against zero add decisions. An empty add side is fine; a
    silent one is what made the advice stream read as sell-only.
    """
    read = context.get("opportunity") or {}
    counts = read.get("counts") or {}
    lines = ["### 加仓面（收盘确认）", ""]
    if not read:
        return "\n".join(lines + ["_context 里没有 opportunity 读数（preflight 版本过旧）_"])
    lines.append(
        f"candidate **{counts.get('candidate', 0)}** / wait {counts.get('wait', 0)} "
        f"/ reject {counts.get('reject', 0)}　·　{text(read.get('policy'))}")
    lines.append("")
    if read.get("why_no_candidate"):
        lines.append(f"**今天没有 candidate 的原因**：{text(read['why_no_candidate'])}")
        lines.append("")
    rows = []
    for row in (read.get("rows") or [])[:8]:
        evidence = row.get("evidence") or {}
        level = evidence.get("prior_20d_high") or evidence.get("proxy_prior_20d_high")
        rows.append([text(row.get("ticker")), text(row.get("verdict")),
                     text(row.get("why")), text(row.get("needs")),
                     text(f"{level:g}" if isinstance(level, (int, float)) else "—")])
    if rows:
        lines.append(table(["标的", "判定", "为什么", "要什么才算数", "前20日高"], rows))
    else:
        lines.append("_没有任何名字进入加仓读数区间_")
    lines.append("")
    lines.append(_track_record_line(context, ("add_only_on_trigger",)))

    act = context.get("add_alpha_activation") or {}
    families = act.get("families") or {}
    if families:
        lines += ["", "**三个证据族的开机状态**（任意两族成立才授权试探仓；"
                      "两族没上线时「任意两族」就退化成「必须追涨」）：", ""]
        rows = []
        for name, row in families.items():
            progress = row.get("progress") or {}
            counters = "、".join(
                f"{k} {v[0]}/{v[1]}" for k, v in progress.items()
                # `isinstance(False, int)` is True, so bool checks would render
                # as "membership_history False/True" — a pass/fail flag is not a
                # counter and has nothing to count down.
                if isinstance(v, list) and len(v) == 2
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
                and v[0] < v[1]) or "—"
            rows.append([name, "✅ 已激活" if row.get("active") else "⏳ 预热中",
                         counters, "、".join(row.get("blockers") or []) or "—"])
        lines.append(table(["证据族", "状态", "还差", "blocker"], rows))
        if act.get("cold_start"):
            lines += ["", "_冷启动期：单族 + 价格确认 + 非杠杆 ⇒ 半个试探仓（policy "
                          "`cold_start_single_family_enabled`）；计数器填满后此例外自动失效_"]
    return "\n".join(lines)


def market_trend_section(context):
    """Both legs' trend reads, each with the window it was measured over.

    The brief printed one 「趋势OFF：杠杆敞口上限砍半」 line and nothing else about
    market direction. That line is HSTECH against its 200-day mean, and it caps
    the HK leveraged sleeve only — `portfolio/guardrail.py` has applied the US
    leg's own per-name dial since it was written. Read as a market call it says
    the desk thinks nothing is going up, which on 2026-09-05 was not what the US
    book looked like at all. Printing both legs with their windows turns an
    implicit market call into a stated one that can be argued with.
    """
    regime = ((context.get("risk_guardrail") or {}).get("lev_regime")) or {}
    history = regime.get("regime_history") or {}
    meta = history.get("meta") or {}
    lines = ["### 大盘趋势（两条腿各自的读数）", ""]
    rows = []

    dist = regime.get("dist_ma_pct")
    rows.append([
        f"HK · {text(regime.get('index') or 'HSTECH')}",
        f"{regime.get('ma_window', 200)}日线",
        f"{dist:+.1f}%" if isinstance(dist, (int, float)) else "—",
        "ON" if regime.get("trend_on") else "OFF",
        text(regime.get("label")),
    ])

    us_days = history.get("us") or {}
    latest = us_days.get(max(us_days)) if us_days else {}
    trend_on = latest.get("trend_on")
    us_dist = latest.get("dist_ma_pct")
    rows.append([
        f"US · {text(meta.get('us_index') or '—')}",
        (f"{meta.get('ma_window', 200)}日线" if trend_on is not None
         else f"近{meta.get('mom_window', 10)}日动量"),
        (f"{us_dist:+.1f}%" if isinstance(us_dist, (int, float))
         else (f"{latest['mom_pct']:+.1f}%" if isinstance(latest.get("mom_pct"), (int, float)) else "—")),
        ("ON" if trend_on else "OFF") if trend_on is not None else "未知",
        text(latest.get("regime3") or "—"),
    ])

    lines.append(table(["腿", "窗口", "距均线/动量", "趋势", "读数"], rows))
    if meta.get("note"):
        lines += ["", f"_{text(meta['note'])}_"]
    lines += ["", "_HK 的趋势闸只收紧 HK 杠杆腿的上限；US 杠杆腿走它自己的 per-name dial_"]
    return "\n".join(lines)


def risk_section(context):
    guard = context.get("risk_guardrail") or {}
    discipline = context.get("risk_discipline") or {}
    rows = []
    for item in (guard.get("hard_stop_watch") or []):
        rows.append(["hard_stop", text(item.get("ticker")), text(item.get("severity")),
                     text(item.get("detail")), text(item.get("breach_id"))])
    for item in (guard.get("breaches") or []):
        rows.append([text(item.get("type")), text(item.get("ticker") or item.get("leg")),
                     text(item.get("severity")), text(item.get("detail")),
                     text(item.get("breach_id"))])

    lines = ["### 风控硬闸", ""]
    lines.append(_track_record_line(context, ("cut", "trim_on_rebound")))
    lines.append("")
    lines.append(
        f"open **{discipline.get('open_count', 0)}** / overridden "
        f"{discipline.get('overridden_count', 0)} / unacknowledged "
        f"{discipline.get('unacknowledged_count', 0)} / oldest "
        f"{discipline.get('oldest_open_days', 0)}d / decision_overdue "
        f"{discipline.get('decision_overdue_count', 0)}")
    lines.append("")
    if rows:
        lines.append(table(["闸", "标的", "严重度", "detail", "breach_id"], rows))
    else:
        lines.append("✅ 仓位硬闸无触发。")
    directive = guard.get("directive")
    if directive:
        lines += ["", f"**directive**: {text(directive)}"]
    return "\n".join(lines)


def breakeven_section(context):
    math_block = context.get("breakeven_math") or {}
    rows = []
    for row in (math_block.get("rows") or []):
        rows.append([
            text(row.get("ticker")),
            pct(row.get("pnl_pct")),
            pct(row.get("chop_drag_pct_per_month"), sign=False)
            if row.get("chop_drag_pct_per_month") is not None else MISSING,
            pct(row.get("breakeven_need_pct")),
            pct(row.get("underlying_need_2x_6m_pct"))
            if row.get("underlying_need_2x_6m_pct") is not None else MISSING,
        ])
    if not rows:
        return ""
    out = ["### 回本测算", "",
           table(["Ticker", "浮%", "2x chop drag/月", "回本需", "半年窗含 drag 等效标的需"], rows)]
    note = math_block.get("note")
    if note:
        out += ["", f"注：{text(note)}"]
    return "\n".join(out)


def holdings_section(context):
    out = ["### 仓位明细"]
    for leg, currency in (("hk", "HKD"), ("us", "USD")):
        book, held = _holdings(context, leg)
        if not held:
            continue
        rows = []
        for row in held:
            rows.append([
                f"{text(row.get('ticker'))} {text(row.get('name'))}",
                num(row.get("shares"), 0),
                num(row.get("cost_basis")),
                num(row.get("current_price")),
                pct(row.get("today_change_pct")),
                pct(row.get("pnl_percent")),
                money(row.get("pnl_abs"), digits=0),
            ])
        rows.append([f"**小计 {leg.upper()}**", "", "", "",
                     money(book.get("today_total_change"), digits=0),
                     pct(book.get("total_pnl_percent")),
                     f"**{money(book.get('total_pnl'), digits=0)}**"])
        sources = sorted({str(row.get("data_source") or "") for row in held if row.get("data_source")})
        out += ["", f"**{leg.upper()} leg**（{currency}；报价源 {', '.join(sources) or MISSING}）", "",
                table(["代码", "股", "成本", "现价", "今日", "浮%", f"浮$ {currency}"], rows)]
    return "\n".join(out)


def retrospective_section(context):
    retro = context.get("retrospective") or {}
    rows = []
    for row in (retro.get("decisions") or []):
        rows.append([
            text(row.get("ticker")),
            text(row.get("action")),
            text(row.get("strategy_id")),
            num(row.get("plan_size_shares"), 0) if row.get("plan_size_shares") else MISSING,
            pct((row.get("plan_confidence") or 0) * 100, digits=0, sign=False),
            text(row.get("followed") if row.get("followed") is not None
                 else row.get("outcome") or row.get("verdict")),
        ])
    prior = retro.get("prior_plan_date")
    head = f"### 昨日兑现（{text(prior)} 的 plan）"
    if not rows:
        return head + "\n\n上一份 plan 无可对账决策。"
    return head + "\n\n" + table(
        ["票", "Action", "Strategy", "计划股数", "计划信心", "兑现"], rows)


def _quant_rows(context):
    """Signals keyed by the holding they speak for.

    `quant_signals.rows` is keyed by the instrument actually measured — a
    leveraged holding is scored on its underlying — and names its consumers in
    `source_holdings`. Reading it by holding is what keeps a proxy row from
    silently going missing for the ticker it was computed for.
    """
    by_holding = {}
    for key, row in ((context.get("quant_signals") or {}).get("rows") or {}).items():
        for holding in (row.get("source_holdings") or [key]):
            by_holding[str(holding)] = row
    return by_holding


def _pnl_by_ticker(context):
    out = {}
    for leg in ("hk", "us"):
        _, held = _holdings(context, leg)
        for row in held:
            out[str(row.get("ticker"))] = row.get("pnl_percent")
    return out


def tier1_section(context, judgment):
    judgments = _judgments(judgment)
    quant = _quant_rows(context)
    pnl = _pnl_by_ticker(context)
    rows = []
    for ticker in sorted(judgments):
        row = judgments[ticker]
        signal = quant.get(ticker) or {}
        stale = signal.get("status") not in (None, "fresh")
        market = " / ".join(filter(None, [
            pct(pnl.get(ticker)) if pnl.get(ticker) is not None else None,
            f"RSI {num(signal.get('rsi14'), 1)}" if signal.get("rsi14") is not None else None,
            signal.get("tag"),
            f"距 MA200 {pct(signal.get('dist_ma200_pct'))}"
            if signal.get("dist_ma200_pct") is not None else None,
            f"⚠️{signal.get('status')}" if stale else None,
        ])) or MISSING
        rows.append([ticker, market, text(row.get("fundamentals")),
                     text(row.get("sentiment_read")), text(row.get("cross_market"))])
    return "### 分析师四格\n\n" + table(
        ["票", "Market（harness 计算）", "Fundamentals", "Sentiment", "Cross-Market"], rows)


def tier2_section(judgment):
    narrative = _narrative(judgment)
    return "\n".join([
        "### 多空对辩",
        "",
        "**看多**", "", text(narrative.get("bull")),
        "",
        "**看空**", "", text(narrative.get("bear")),
        "",
        f"**魔鬼代言人** — 攻击的共识：{text(narrative.get('attacked_consensus'))}",
        "", text(narrative.get("devils_advocate")),
    ])


def risk_voices_section(judgment):
    """The three risk officers, in the rotation the model declared."""
    narrative = _narrative(judgment)
    voices = ("aggressive", "conservative", "neutral")
    first = narrative.get("risk_voice_first")
    if first not in voices:
        # The rotation is the model's to state; a missing value must still
        # produce three named voices rather than a section headed "None".
        first = voices[0]
    ordered = [first] + [voice for voice in voices if voice != first]
    out = ["### 风险官三票", ""]
    for index, voice in enumerate(ordered):
        label = VOICE_LABELS.get(voice, voice)
        suffix = " · 今日首位表态" if index == 0 else ""
        out += [f"**{label}{suffix}**", "", text(narrative.get(voice)), ""]
    return "\n".join(out).rstrip()


def judge_section(plan):
    """The calls themselves — what the harness validated and the ledger records.

    Split out of the old `Tier 3 — 3 Risk Voices + Judge` because those are two
    different questions: the voices are the argument, this is the answer. Under
    the four-part layout the answer opens the report and the argument follows it.
    """
    rows = []
    for decision in (plan.get("decisions") or []):
        debate = decision.get("debate") or {}
        rows.append([
            text(decision.get("ticker")),
            f"**{text(decision.get('action'))}**",
            " + ".join(debate.get("frames") or []) or MISSING,
            text(decision.get("strategy_id")),
            text(decision.get("driven_by")),
            text(decision.get("rationale")),
        ])
    return f"### {PAGE_ACTION_HEADING}\n\n" + table(
        ["Ticker", "Action", "Frame", "Strategy", "driven_by", "理由"], rows)


def sector_section(sector_scan, judgment):
    """板块全景 — the sweep the model runs with web search, laid out here.

    The scan lands in `memory/.tmp/sector-scan-{date}.json` because the
    dashboard reads it too; rendering the report from the same file keeps the
    page and the panel telling one story, and keeps the peer detail kcn asked
    never to compress.
    """
    sectors = (sector_scan or {}).get("sectors") or []
    read = text(_narrative(judgment).get("sector_read"))
    if not sectors:
        return "\n".join(["### 板块全景", "", read])
    rows = []
    for sector in sectors:
        movers = "、".join(
            f"{text(m.get('ticker'))} {text(m.get('name'))} {pct(m.get('pct'))}"
            for m in (sector.get("top_movers") or [])[:3])
        for own in (sector.get("self") or []):
            rows.append([
                text(sector.get("theme")),
                text(own.get("ticker")),
                pct(own.get("pct")),
                text(own.get("rank_text")),
                movers or MISSING,
                text(own.get("attribution")),
            ])
    out = ["### 板块全景", "",
           table(["板块", "持仓", "今日", "位置", "板块 Top", "归因"], rows), "", read]
    return "\n".join(out)


def peer_section(context, judgment):
    judgments = _judgments(judgment)
    rows = []
    for ticker, row in sorted((context.get("peer_scan") or {}).items()):
        peers = row.get("listed_peers") or []
        best = max(peers, key=lambda p: p.get("pct_1d") if p.get("pct_1d") is not None else -1e9,
                   default=None)
        gap = None
        if best and best.get("pct_1d") is not None and row.get("self_pct_1d") is not None:
            gap = row["self_pct_1d"] - best["pct_1d"]
        rows.append([
            ticker,
            text(row.get("theme")),
            pct(row.get("self_pct_1d")),
            f"{text(best.get('ticker'))} {text(best.get('name'))} {pct(best.get('pct_1d'))}"
            if best else MISSING,
            f"{gap:+.2f}pp" if gap is not None else MISSING,
            text((judgments.get(ticker) or {}).get("peer_read")),
        ])
    return "### 同行扫描\n\n" + table(
        ["持仓", "主题", "今日 self", "最强同行", "差距", "判断"], rows)


def macro_section(context, judgment):
    macro = context.get("macro") or {}

    def quote(key, label):
        row = macro.get(key) or {}
        if not row:
            return None
        return f"{label} **{num(row.get('price'))}** ({pct(row.get('change_pct'))})"

    parts = [quote(key, label) for key, label in (
        ("vix", "VIX"), ("hsi", "HSI"), ("hstech", "HSTECH"),
        ("spx", "SPX"), ("nasdaq", "纳指"), ("dxy", "DXY"))]
    fear = macro.get("fear_greed") or {}
    if fear:
        parts.append(f"F&G **{num(fear.get('score'), 1)}** {text(fear.get('rating'))}")
    if macro.get("treasury_10y_yield_pct") is not None:
        parts.append(f"10Y **{pct(macro.get('treasury_10y_yield_pct'), sign=False)}**")
    body = " · ".join(part for part in parts if part)
    return "\n".join([
        "### 大盘速读", "",
        f"{body}（as_of {text(macro.get('as_of'))}, age {num(macro.get('age_hours'), 1)}h）",
        "", text(_narrative(judgment).get("macro_read")),
    ])


def sentiment_section(context, judgment):
    judgments = _judgments(judgment)
    rows = []
    for row in ((context.get("sentiment") or {}).get("tickers") or []):
        ticker = str(row.get("ticker"))
        keywords = "、".join(
            str((item.get("title") or item.get("headline") or "")
                if isinstance(item, dict) else item)[:36]
            for item in (row.get("news_top") or [])[:3])
        rows.append([
            ticker,
            (f"{row['reddit_mentions_7d']} mentions"
             if row.get("reddit_mentions_7d") is not None else MISSING),
            keywords or MISSING,
            pct((row.get("recent_move") or {}).get("pct_5d"))
            if isinstance(row.get("recent_move"), dict) else MISSING,
            text((judgments.get(ticker) or {}).get("sentiment_read")),
        ])
    if not rows:
        return ""
    return "### 社交舆情\n\n" + table(
        ["票", "Reddit 7d", "新闻关键词", "近 5 日", "信号判断"], rows)


def influencer_section(context):
    influencer = context.get("influencer") or {}
    counts = influencer.get("counts") or {}
    if not counts.get("total"):
        return ""
    out = [f"### 名人异动 / 政策风向（{num(influencer.get('age_hours'), 1)}h 前）", "",
           f"撞持仓 **{counts.get('held_hits', 0)}** · 新机会 {counts.get('new_ideas', 0)}"
           f" · 板块相关 {counts.get('sector_hits', 0)}", ""]
    for bucket, label in (("held_hits", "撞持仓"), ("new_ideas", "新机会"),
                          ("sector_hits", "板块相关")):
        for row in (influencer.get(bucket) or [])[:3]:
            out.append(f"- [{label}] {text(row.get('author'))}"
                       f"（{text(row.get('stance'))}）：{text(row.get('summary_cn'))}")
    return "\n".join(out)


def verdict_badge(value):
    """A verdict cell: glyph + label, tinted by the site's own tokens.

    An unknown verdict falls through to its own text rather than being dropped
    or coloured — `packet.VERDICTS` is the enum's authority and rendering is the
    wrong place to reject one, same rule as every other cell here.
    """
    spec = VERDICT_LABELS.get(value)
    if spec is None:
        return text(value)
    return (f'<span class="verdict verdict-{value}">'
            f'{spec["glyph"]} {spec["label"]}</span>')


def confidence_section(judgment, plan):
    judgments = _judgments(judgment)
    rows = []
    for decision in (plan.get("decisions") or []):
        ticker = str(decision.get("ticker"))
        row = judgments.get(ticker) or {}
        confidence = decision.get("confidence")
        rows.append([
            ticker,
            text(decision.get("action")),
            pct((confidence or 0) * 100, digits=0, sign=False),
            verdict_badge(row.get("verdict")),
            text(row.get("rationale")),
            text(row.get("falsifier")),
        ])
    return "### 信心与判定\n\n" + table(
        ["Ticker", "Action", "Confidence", "Verdict", "理由", "证伪条件"], rows)


def _interval(bounds):
    """A confidence interval in the same units as the benefit beside it.

    A raw `[0.3744, 6.7355]` on the page invites the reader to take it as a
    probability; these are percentage points, and the column next to it already
    reads as percent.
    """
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        return MISSING
    low, high = (_numeric(bound) for bound in bounds)
    if low is None or high is None:
        return MISSING
    return f"[{low:+.2f}%, {high:+.2f}%]"


def calibration_section(context, judgment):
    metrics = context.get("decision_metrics") or {}
    head = (f"过去 {metrics.get('window_days', MISSING)} 天：已结算 "
            f"**{metrics.get('settled_episodes', MISSING)}** 个 episode"
            f"（{metrics.get('raw_decisions', MISSING)} raw decisions；Brier "
            f"{num(metrics.get('brier'), 4)}）")
    rows = []
    for driver, row in sorted((metrics.get("by_driver") or {}).items()):
        rows.append([
            driver,
            row.get("n_episodes", MISSING),
            pct(row.get("avg_benefit_pct")) if row.get("avg_benefit_pct") is not None else MISSING,
            _interval(row.get("cluster_ci95")),
            "✅" if row.get("edge_significant") else "—",
        ])
    out = ["### 决策校准", "", head, ""]
    if rows:
        out += [table(["driven_by", "n", "avg benefit", "cluster CI95", "edge"], rows), ""]
    out.append(text(_narrative(judgment).get("calibration_read")))
    return "\n".join(out)


def next_session_section(judgment):
    steps = _narrative(judgment).get("next_session") or []
    body = "\n".join(f"{index}. {text(step)}" for index, step in enumerate(steps, 1))
    return "### 下一节点\n\n" + (body or "无。")


def data_holes_section(context, judgment):
    holes = list(_narrative(judgment).get("data_holes") or [])
    holes += [str(issue) for issue in (context.get("issues") or [])]
    surface = (context.get("research_surface") or {}).get("errors") or []
    holes += [str(error) for error in surface]
    if not holes:
        return "### 待补\n\n无。"
    return "### 待补\n\n" + "\n".join(f"- {text(hole)}" for hole in holes)


# --- documents -------------------------------------------------------------

#: Section names the page and the card share. They exist as constants because the
#: two surfaces are rendered by two functions, and a reader taps from one to the
#: other: renaming a heading in only one of them is how they drift into looking
#: like different reports. `test_the_card_and_the_page_agree` pins the pair.
PAGE_ACTION_HEADING = "今日动作"
PAGE_BOOK_PART = "这本账现在什么样"
CARD_BOOK_HEADING = "这本账"


def render_brief(context, judgment, plan, *, date=None, sector_scan=None):
    """The full pre-open report.  Order is fixed here and nowhere else."""
    date = date or context.get("date") or ""
    weekday = ""
    try:
        weekday = WEEKDAYS[_date.fromisoformat(date).weekday()]
    except ValueError:
        pass
    title = f"盘前深度简报｜{date} {weekday} {BRIEF_SLOT_HKT} HKT".strip()

    # Four parts, in this order and nowhere else (2026-09-06, kcn: 「就和盘中一样」).
    #
    # It used to be twenty flat `##` sections with four heading conventions
    # competing in one document — `## Header — Book 双视角`, `### 集中度
    # （core.concentration）`, `## ▎仓位明细`, `## Tier 1 — 4 Analyst 大表` — and
    # the layout stylesheet draws a rule above every `h2`, so the page arrived as
    # twenty equally-weighted slabs with internal field names printed in the
    # headings. Nothing told a reader which block was the decision and which was
    # background.
    #
    # Every section still renders; none of the analysis was cut (kcn: 「内容可以
    # 稍微精简，但该有的输出决策分析都要有，不要砍」). What changed is that the
    # twenty are grouped under four `##` parts with one `###` convention beneath
    # them, and the reference material moves inside a `<details>` so the page
    # opens on the call rather than on the book.
    #
    # The intraday check-in is the model this follows: harness data block plus
    # one model paragraph, and the reader never wonders where to start.
    parts = [
        ("今天做什么", [
            judge_section(plan),
            confidence_section(judgment, plan),
            next_session_section(judgment),
        ]),
        ("我的看法", [
            tier2_section(judgment),
            risk_voices_section(judgment),
            tier1_section(context, judgment),
        ]),
        (PAGE_BOOK_PART, [
            header_section(context, judgment),
            concentration_section(context),
            risk_section(context),
            opportunity_section(context),
            breakeven_section(context),
            holdings_section(context),
            market_trend_section(context),
        ]),
    ]
    appendix = [
        retrospective_section(context),
        peer_section(context, judgment),
        sector_section(sector_scan, judgment),
        macro_section(context, judgment),
        sentiment_section(context, judgment),
        influencer_section(context),
        calibration_section(context, judgment),
        data_holes_section(context, judgment),
    ]

    blocks = [
        "---",
        "layout: default",
        f"title: {title}",
        f'description: "clawock 盘前深度简报 {date}：港股 + 美股真实持仓的多空辩论、'
        '量化因子、风控硬闸与决策校准。"',
        "---",
        "",
        f"# {title}",
        "",
        text(judgment.get("portfolio_assessment")),
        "",
        f"**反方**：{text(judgment.get('portfolio_counterargument'))}",
        "",
    ]
    for heading, sections in parts:
        rendered = [section for section in sections if section and section.strip()]
        if not rendered:
            continue
        blocks += [f"## {heading}", ""]
        for section in rendered:
            blocks += [section, ""]

    # `<details>` rather than a fifth part: this is the material a reader consults
    # when a number above surprises them, not material they read every morning.
    #
    # `markdown="1"` is load-bearing, not decoration. The site runs kramdown with
    # `input: GFM` and kramdown does NOT parse markdown inside a block-level HTML
    # element unless the element says so — without the attribute every table in
    # this appendix ships to the page as literal pipe characters, and nothing in
    # the markdown validator would notice because the markdown itself is fine.
    # `test_brief_render_layout` pins it for that reason.
    kept = [section for section in appendix if section and section.strip()]
    if kept:
        blocks += [
            "<details class=\"brief-appendix\" markdown=\"1\">",
            "<summary>背景与校准</summary>",
            "",
        ]
        for section in kept:
            blocks += [section, ""]
        blocks += ["</details>", ""]

    body = "\n".join(block for block in blocks if block is not None)
    # Collapse the blank lines an omitted section leaves behind, so a quiet day
    # does not publish a page full of gaps.
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")
    return body.rstrip() + "\n"


def render_card(context, judgment, plan, *, date=None, page_url=None):
    """The WeChat/Telegram card: the same facts, cut to what fits a phone.

    Two surfaces, one report. The card is the trimmed one and the page is what a
    reader opens when the card makes them want more, so the two must agree on
    what comes first and on what things are called — a reader who taps through
    should land on the same words in the same order, not on a different document.

    So this follows the page's four-part order (2026-09-06): the call, then the
    book, then the levels. It used to lead with the book, which put 1.3KB of
    balance between the reader and the four cuts the brief exists to state.

    What the card deliberately drops, recorded here so the trim is a decision
    rather than an omission nobody re-examined:

    * `**反方**` — the page opens with the assessment and its counterargument;
      the card keeps only the assessment. Both are the model's longest prose and
      two of them is a wall on a phone.
    * every argument section (多空对辩 / 风险官三票 / 分析师四格) and the whole
      背景与校准 appendix — that is what the link at the bottom is for.

    `▎` is the card's own ornament and stays here. It was removed from the page
    headings, where markdown already carries the hierarchy.
    """
    date = date or context.get("date") or ""
    book = context.get("book_totals") or {}
    fx = context.get("fx") or {}
    concentration = context.get("concentration") or {}
    lines = [f"📊 盘前深度简报｜{date} {BRIEF_SLOT_HKT} HKT  (USDHKD={num(fx.get('rate'), 4)})", ""]
    lines += ["▎核心结论", text(judgment.get("portfolio_assessment")), ""]

    actions = [d for d in (plan.get("decisions") or [])
               if d.get("action") not in (None, "hold_and_watch", "watch")]
    holds = [d for d in (plan.get("decisions") or [])
             if d.get("action") in ("hold_and_watch", "watch")]
    lines.append(f"▎{PAGE_ACTION_HEADING}")
    if actions:
        for index, decision in enumerate(actions, 1):
            size = (decision.get("size") or {}).get("shares")
            lines.append(
                f"{index}. {text(decision.get('ticker'))} [{text(decision.get('strategy_id'))}]"
                f" {text(decision.get('action'))}"
                f"{f' {num(size, 0)} 股' if size else ''}"
                f" (driven_by={text(decision.get('driven_by'))},"
                f" conf {pct((decision.get('confidence') or 0) * 100, digits=0, sign=False)})")
    else:
        lines.append("无主动动作。")
    if holds:
        lines.append(f"{len(actions) + 1}. "
                     + "/".join(str(d.get("ticker")) for d in holds)
                     + " hold_and_watch")
    lines.append("")

    lines += [f"▎{CARD_BOOK_HEADING}",
              f"USD${money(book.get('usd_base_total'), digits=0)}"
              f" | HK leg HKD${money(book.get('hk_pnl_hkd'), digits=0)}"
              f" | US leg USD${money(book.get('us_pnl_usd'), digits=0)}",
              f"HHI: HK {num((concentration.get('hk') or {}).get('hhi'), 3)}"
              f" · US {num((concentration.get('us') or {}).get('hhi'), 3)}", ""]

    levels = plan.get("watch_levels") or {}
    if levels:
        lines.append("▎触发位")
        for key, value in levels.items():
            lines.append(f"• {key}: {num(value)}")
        lines.append("")
    if page_url:
        lines += ["📈 完整深度报告：", page_url]
    return "\n".join(lines).rstrip() + "\n"


# --- workspace wiring ------------------------------------------------------

def artifact_paths(workspace, date):
    """Where the harness keeps this generation's inputs and outputs."""
    tmp = Path(workspace) / "memory" / ".tmp"
    return {
        "context": tmp / f"brief-context-{date}.json",
        "judgment": tmp / f"brief-judgment-{date}.json",
        "plan": Path(workspace) / "memory" / f"{date}-plan.json",
        "brief": Path(workspace) / "memory" / f"{date}-pre-open.md",
        "card": tmp / f"brief-card-{date}.txt",
        "sector_scan": tmp / f"sector-scan-{date}.json",
    }


def render_from_workspace(workspace, date, *, plan=None, page_url=None, write=True):
    """Render both artifacts for one date. Returns (issues, brief_markdown).

    `plan` lets the caller hand in the normalized plan it already holds, so the
    published report is rendered from the same decisions the ledger records
    rather than from the model's pre-normalization file.
    """
    paths = artifact_paths(workspace, date)
    issues = []
    try:
        context = _load(paths["context"])
        judgment = _load(paths["judgment"])
        if plan is None:
            plan = _load(paths["plan"])
    except (OSError, ValueError) as exc:
        return ([f"简报渲染跳过（输入不可读: {exc}）；保留现有 pre-open.md"], None)

    # The sector sweep is optional: a day the search quota was spent still has
    # to publish, with the section carrying the model's read and no table.
    try:
        sector_scan = _load(paths["sector_scan"])
    except (OSError, ValueError):
        sector_scan = None

    body = render_brief(context, judgment, plan, date=date, sector_scan=sector_scan)
    card = render_card(context, judgment, plan, date=date, page_url=page_url)
    if write:
        paths["brief"].parent.mkdir(parents=True, exist_ok=True)
        paths["brief"].write_text(body, encoding="utf-8")
        paths["card"].parent.mkdir(parents=True, exist_ok=True)
        paths["card"].write_text(card, encoding="utf-8")
    return issues, body


# --- CLI -------------------------------------------------------------------

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    from clawock.workspace import workspace_root

    parser = argparse.ArgumentParser(
        description="Render the daily deep brief from context + judgment + plan. "
                    "The model writes the judgment; every heading, table and "
                    "number below is produced here.")
    parser.add_argument("--date", help="brief date (default: today)")
    parser.add_argument("--workspace", help="workspace root (default: resolved)")
    parser.add_argument("--page-url",
                        help="URL printed at the foot of the card "
                             "(default: this date's published page)")
    parser.add_argument("--dry-run", action="store_true",
                        help="render to stdout without writing the artifacts")
    args, _unknown = parser.parse_known_args(argv)

    workspace = Path(args.workspace) if args.workspace else workspace_root()
    date = args.date or _date.today().isoformat()
    from clawock.harness._watchdog_common import BRIEF_URL_TMPL

    issues, body = render_from_workspace(
        workspace, date,
        page_url=args.page_url or BRIEF_URL_TMPL.format(date=date),
        write=not args.dry_run)
    for issue in issues:
        print(issue)
    if body is None:
        return 1
    if args.dry_run:
        print(body)
    else:
        paths = artifact_paths(workspace, date)
        print(f'wrote {paths["brief"]} ({paths["brief"].stat().st_size} bytes) '
              f'and {paths["card"].name}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
