"""Harness-owned rendering of manual intraday recommendations.

Two renderings of one context. `render` is the audit record: every refusal
reason, the adverse research evidence, cost caveats and the manifest/data
hashes. It is reproducible from the context JSON and is not pushed.
`render_card` is what kcn reads on the WeChat/Telegram card: only an actionable
order, in trading language, with the conditions needed to place it safely.
kcn 2026-10-19: hashes, English disclaimers, arm-by-arm backtests and "no
recommendation because ..." lines are not for a human reader.
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from clawock.decision.intraday_recommendations import build


def _metric(base, key):
    value = base.get(key)
    return f'{value:.4f}' if type(value) in (int, float) and math.isfinite(value) else '未知'


def render(ctx):
    lines = ['▎今日可执行建议 · 仅供人工确认',
             '探索性条件建议；不自动下单。历史未通过不等于有效策略。']
    rows = ctx.get('rows') or []
    for row in rows or [ctx]:
        if rows:
            lines.extend([
                f"{row['ticker']}：限价卖出底仓 {row['shares']} 股，卖价不低于 {row['sell_limit']:.2f} USD。",
                f"仅在现价仍高于 {row['band']:.4f} 且低于 {row['buyback_stop']:.2f} 时考虑；先核对真实可卖股数、未成交单和现金，重复卡不是追加单。",
                f"成交后：回落至 {row['buyback_target']:.2f} 买回；升至 {row['buyback_stop']:.2f} 则失效买回，均为 {row['shares']} 股；未触及则本场收盘前买回。",
                f"信号 {row['signal_at']}；未成交至 {row['expires_at']} 即撤销，持仓/计划改变或出现新 bar 也须重评。",
                '买回以实际卖出成交股数为限；跳空、滑点和不能成交可能扩大损失。',
                f"条件往返成本 {row['conditional_roundtrip_cost']:.4f} USD；不承诺净收益。",
            ])
        else:
            lines.append('不出建议：' + '；'.join(ctx.get('reasons') or ['条件未成立']))
        base = row.get('research_base')
        if base:
            lines.append(f"历史 base 净增量 {_metric(base, 'net_increment')} USD｜场次末回撤 {_metric(base, 'max_session_close_drawdown')}｜成本 {_metric(base, 'costs')}；历史净验证未证明有效。")
        lines.extend([
            'OHLC execution conditional; no order book/queue or intrabar drawdown（无盘口队列或 bar 内回撤）。',
            'current tariff counterfactual, not historical invoice；Zero commission is conditional on unused monthly allowance（非真实账单，免佣取决于剩余额度）。',
            f"prospective_status: {row.get('prospective_status', 'not_started')}；无已完成前瞻验证，历史 OOS 不是前瞻。",
        ])
        if row.get('manifest_sha256') and row.get('data_sha256'):
            lines.extend([f"manifest_sha256: {row['manifest_sha256']}",
                          f"data_sha256: {row['data_sha256']}"])
        if rows:
            lines.append(f"live_data_sha256: {row['live_data_sha256']}")
    return '\n'.join(lines)


_MARKET_TZ = {'us': 'America/New_York', 'hk': 'Asia/Hong_Kong'}


def _clock(stamp, market):
    try:
        moment = datetime.fromisoformat(str(stamp))
        return moment.astimezone(ZoneInfo(_MARKET_TZ.get(market, 'UTC'))).strftime('%H:%M')
    except (TypeError, ValueError):
        return str(stamp)


def render_card(ctx):
    """The human card: empty unless there is an order to consider placing."""
    rows = ctx.get('rows') or []
    if not rows:
        return ''
    market = ctx.get('market') or 'us'
    lines = ['### 🔁 做T建议（需你手动下单，不会自动成交）']
    for row in rows:
        lines.extend([
            f"- **{row['ticker']}** 先卖后买回 {row['shares']} 股：限价卖出，卖价不低于 `{row['sell_limit']:.2f}`",
            f"- 买回：回落到 `{row['buyback_target']:.2f}` 买回；涨到 `{row['buyback_stop']:.2f}` 放弃买回；"
            '都没碰到就收盘前买回',
            f"- 前提：现价在 `{row['band']:.2f}`–`{row['buyback_stop']:.2f}` 之间；"
            f"`{_clock(row['expires_at'], market)}` 前没成交就撤单；持仓或计划变了先别下",
            f"- 往返成本约 {row['conditional_roundtrip_cost']:.2f} {'HKD' if market == 'hk' else 'USD'}；"
            '回测未经前瞻验证，跳空和滑点可能放大亏损',
        ])
    return '\n'.join(lines)


def section(workspace, market, research, policies, plan_context, *, now=None):
    ctx = build(workspace, market, research, policies, plan_context, now=now)
    return ctx, render_card(ctx)
