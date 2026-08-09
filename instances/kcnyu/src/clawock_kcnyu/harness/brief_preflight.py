#!/usr/bin/env python3
"""
brief_preflight.py — deterministic data collection for daily-deep-brief harness.

Runs everything that must happen BEFORE LLM analysis. It keeps a complete audit
context, then emits a budgeted core plus generation-bound lazy bundles for the
LLM (FX rate, concentration, retrospective, etc.) so it cannot forget steps or
silently absorb an unbounded monolith.

Steps:
  1. Refresh US + HK prices (mutates portfolio.json)
  2. Fetch FX rate (3-route fallback)
  3. Snapshot portfolio.json → memory/snapshots/{date}.json
  4. Compute HHI concentration + Top2 for HK and US legs
  5. Compute USD-base / HKD-base book totals
  6. Pull SEC EDGAR fundamentals for US singles (is_leveraged_etf=false)
  7. Locate prior plan.json + compute retrospective (trigger fired + simulated PnL)
  8. Peer scan
  9. Self-calibration
 10. Risk metrics
 11. Catalyst calendar (next 14d earnings + FOMC + macro)
 12. Benchmark history (SPY + HSI/HSTECH) for equity curve overlay
 13. Load macro + sentiment snapshots (read assets/data/{macro,sentiment}.json)
 14. Write the full audit context + model-facing manifest/core/bundles

Output (stdout): step-by-step progress; final summary with issue count.
Exit: 0 if no issues, 1 if any data leg failed.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.workspace import workspace_root
from clawock import trading_calendar
from clawock import (
    brief_context,
    brief_decision_packet,
    decision_v2,
    research_surface,
    risk_discipline,
    thesis_registry,
)

WS = workspace_root(Path.cwd())
_CHECKOUT = WS
TMP_DIR = WS / 'memory' / '.tmp'
SNAPSHOT_DIR = WS / 'memory' / 'snapshots'

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
import peer_scan  # noqa: E402
import workflow_outcomes  # noqa: E402
import mover_news  # noqa: E402
from clawock.instrument_registry import get as get_instrument  # noqa: E402
from clawock.instrument_registry import compute_lookthrough_exposure  # noqa: E402
from clawock.instrument_registry import one_x_swap_map  # noqa: E402


def _fetch_hk_results_notices(ticker):
    """KCNyu's free HK notice feed; core only consumes injected records."""
    symbol = mover_news.tencent_symbol(ticker, "hk")
    if not symbol:
        return []
    payload = mover_news._http_json(
        f"{mover_news.TENCENT_NEWS}?symbol={symbol}&n=20&page=1&type=0"
    )
    return ((payload or {}).get("data") or {}).get("data") or []


def _run(script, args=None, timeout=120):
    """Run a workspace script; return (stdout, ok)."""
    cmd = ['python3', str(WS / script)] + (args or [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.returncode == 0
    except Exception as e:
        return f'{type(e).__name__}: {e}', False


def fetch_fx_rate():
    try:
        result = subprocess.run(
            ['clawock', 'fx', '--json'], cwd=WS, capture_output=True,
            text=True, timeout=30)
        out, ok = result.stdout, result.returncode == 0
    except Exception as exc:
        out, ok = f'{type(exc).__name__}: {exc}', False
    if not ok:
        return {'rate': 7.80, 'source': 'HARDCODED_FALLBACK', 'error': out[-300:]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {'rate': 7.80, 'source': 'PARSE_FAILED', 'error': out[-300:]}


_LEVERAGED_KEYWORDS = ('倍', 'Direxion', 'T-Rex', 'Defiance', 'ProShares',
                       '2X Long', '3X Long', '2x Long', '3x Long', 'Daily Target',
                       # HK leveraged/inverse products: 「XL二/XL三」= L×2/×3, 「两倍」
                       'XL二', 'XL三', 'XL两', '两倍')


def _is_leveraged_etf(holding):
    """Use canonical leverage metadata; retain an unknown-name fallback."""
    if holding.get('is_leveraged_etf') is True:
        return True
    meta = get_instrument(holding.get('ticker'))
    if meta is not None:
        return meta['leverage_multiple'] > 1
    name = holding.get('name', '')
    return any(kw in name for kw in _LEVERAGED_KEYWORDS)


def collect_us_fundamentals(portfolio):
    """Pull SEC EDGAR --financials for each non-leveraged US single."""
    fundamentals = {}
    for h in portfolio['portfolios']['us_stocks']['holdings']:
        if h.get('shares', 0) <= 0 or _is_leveraged_etf(h):
            continue
        ticker = h['ticker']
        out, ok = _run('scripts/data/fetch_us_filings.py', [ticker, '--financials', '--json'], timeout=30)
        if not ok:
            fundamentals[ticker] = {'error': out[-300:]}
            continue
        try:
            fundamentals[ticker] = json.loads(out)
        except json.JSONDecodeError:
            fundamentals[ticker] = {'error': 'parse failed', 'raw': out[:300]}
    return fundamentals


def compute_concentration(holdings):
    """HHI + Top2 + per-holding weights for one leg."""
    active = [h for h in holdings if h.get('shares', 0) > 0]
    if not active:
        return {}
    total = sum(h.get('current_value', h['cost_basis'] * h['shares']) for h in active)
    if not total:
        return {'error': 'leg has zero total value'}

    weights = []
    for h in active:
        v = h.get('current_value', h['cost_basis'] * h['shares'])
        weights.append({
            'ticker':     h['ticker'],
            'value':      round(v, 2),
            'weight_pct': round(v / total * 100, 2),
            'leveraged':  _is_leveraged_etf(h),
        })
    weights.sort(key=lambda x: -x['weight_pct'])

    hhi  = sum((w['weight_pct'] / 100) ** 2 for w in weights)
    top2 = sum(w['weight_pct'] for w in weights[:2])

    if hhi > 0.40:
        verdict = '🔴 危险集中'
    elif hhi > 0.25:
        verdict = '⚠️ 集中风险'
    elif hhi > 0.15:
        verdict = '偏集中'
    else:
        verdict = '✅ 健康'

    return {
        'hhi':        round(hhi, 3),
        'top2_pct':   round(top2, 1),
        'verdict':    verdict,
        'leg_total':  round(total, 2),
        'weights':    weights,
    }


# ── Risk guardrails: position-sizing / leverage HARD CAPS ───────────────────
# Backing: the 2026-06 drawdown was a *construction* problem (US β≈4.4, 73%
# leveraged ETFs, HK 85% one factor), not a signal problem — no driven_by face
# called it ahead. These caps turn risk.json + concentration from read-only
# dashboard cards into actionable, capped trim/cut directives the brief MUST act
# on. The trims are driven_by=risk_rule (disciplinary rebalancing), which the
# 证伪 rule explicitly exempts from the risk_on HOLD default.
GUARDRAIL_CAPS = {
    'single_name_pct':   35,    # any one name within a leg
    'top2_factor_pct':   70,    # Top2 as single-factor proxy
    'lev_etf_leg_pct':   50,    # leveraged ETFs as % of a leg
    'us_beta_max':       3.0,   # US β vs S&P 500
    'lev_etf_stop_pct': -18,    # hard-stop line for one leveraged ETF (vs cost)
}

# 2x→1x 解套换仓映射（kcn 2026-06-11 口径）：现货套牢可以躺（等待免费），2x 日内重置
# 套牢不能躺（震荡 decay 让等待持续收费）。所以杠杆腿的硬闸动作一律先给「换仓」而非
# 「清仓 trim」——换成同因子 1x 后反弹敞口一点不丢、decay 出血停止，不算割肉离场。
# 换回条件 = 🧭 lev_regime 转 green（标的收复 200 日线且波动正常），1x→2x 只在 green 档执行。
LEV_1X_SWAP = one_x_swap_map()


def _swap_suggestions(holdings):
    """持有中的杠杆 ETF → 「2x→1x」换仓建议串，如 "07226→03033、ROBN→HOOD"。"""
    return '、'.join(f"{h['ticker']}→{LEV_1X_SWAP[h['ticker']]}" for h in holdings
                     if h.get('shares', 0) > 0 and _is_leveraged_etf(h)
                     and h.get('ticker') in LEV_1X_SWAP)


def _holding_pnl_pct(h):
    cost = h.get('cost_basis', 0) * h.get('shares', 0)
    cur  = h.get('current_value', cost)
    return None if not cost else round((cur - cost) / cost * 100, 1)


def compute_risk_guardrail(hk_holdings, us_holdings, hk_conc, us_conc, risk, lev_regime=None):
    """Pure function of current state → concrete, capped trim/cut directives.
    The brief LLM must emit a disciplinary action for EVERY breach (not optional).

    lev_regime (lev_regime.json, optional): the HSTECH trend+vol leverage dial.
    When present and hostile (amber/red), it TIGHTENS the leveraged-ETF leg cap by
    its multiplier (green 1.0 / amber 0.5 / red 0.0). Backtest-verified: the lever
    that mattered in the 2021-22 crash was leverage (2x→1x→cash), not timing."""
    caps = GUARDRAIL_CAPS
    breaches, hard_stops = [], []
    # Leveraged-ETF leg cap is tightened PER LEG: the HK leg by the HSTECH dial
    # (lev_regime top-level / hk), the US leg by its own per-name dial (not HSTECH).
    hk_mult = 1.0
    if isinstance(lev_regime, dict) and isinstance(lev_regime.get('lev_cap_mult'), (int, float)):
        hk_mult = lev_regime['lev_cap_mult']
    eff_caps = {}

    for leg, conc, hold in (('HK', hk_conc, hk_holdings), ('US', us_conc, us_holdings)):
        if not conc or not conc.get('weights'):
            continue
        total = conc['leg_total'] or 0
        ccy   = 'HKD' if leg == 'HK' else 'USD'
        ws    = conc['weights']

        # single-name cap
        for w in ws:
            if w['weight_pct'] > caps['single_name_pct'] and total:
                trim_val = round(w['value'] - caps['single_name_pct'] / 100 * total, 2)
                breaches.append({
                    'type': 'single_name', 'leg': leg, 'ticker': w['ticker'],
                    'severity': 'high' if w['weight_pct'] > caps['single_name_pct'] + 15 else 'medium',
                    'detail': f"{w['ticker']} = {w['weight_pct']}% of {leg} (cap {caps['single_name_pct']}%)",
                    'action': (f"纪律性 trim {w['ticker']} → ≤{caps['single_name_pct']}% "
                               f"(减约 {trim_val} {ccy}，借反弹分批、勿在新低日一次砍)"),
                    'required_reduction': {
                        'kind': 'market_value',
                        'minimum_value': trim_val,
                        'currency': ccy,
                        'target_pct': caps['single_name_pct'],
                        'target_tickers': [w['ticker']],
                    },
                })

        # single-factor proxy = Top2
        if conc.get('top2_pct', 0) > caps['top2_factor_pct']:
            top2 = ws[:2]
            factor_trim = max(0, round(
                sum(w['value'] for w in top2)
                - caps['top2_factor_pct'] / 100 * total, 2))
            breaches.append({
                'type': 'factor_concentration', 'leg': leg, 'ticker': None, 'severity': 'high',
                'detail': f"{leg} Top2 = {conc['top2_pct']}% (cap {caps['top2_factor_pct']}%) — 名义多只实为单因子",
                'action': f"把 {leg} Top2 降到 ≤{caps['top2_factor_pct']}%：借强减最大那只，别在同因子内换票",
                'required_reduction': {
                    'kind': 'factor_market_value',
                    'minimum_value': factor_trim,
                    'currency': ccy,
                    'target_pct': caps['top2_factor_pct'],
                    'target_tickers': [w['ticker'] for w in top2],
                },
            })

        # leveraged-ETF leg exposure — use the name heuristic, not the unreliable
        # is_leveraged_etf flag (which concentration weights mirror and is often unset)
        lev_val = sum(h.get('current_value', h.get('cost_basis', 0) * h.get('shares', 0))
                      for h in hold if h.get('shares', 0) > 0 and _is_leveraged_etf(h))
        # HK leg cap tightened by HSTECH dial; US leg stays at base (its risk is handled
        # per-name below — verified: a single US index mult over-cuts calm names like MSFT).
        leg_mult = hk_mult if leg == 'HK' else 1.0
        eff_lev_cap = round(caps['lev_etf_leg_pct'] * leg_mult)
        eff_caps[leg] = eff_lev_cap
        lev_pct = round(lev_val / total * 100, 1) if total else 0
        if lev_pct > eff_lev_cap and total:
            trim_val = round(lev_val - eff_lev_cap / 100 * total, 2)
            tightened = eff_lev_cap < caps['lev_etf_leg_pct']
            hk_tier = (lev_regime.get('hk') or lev_regime).get('tier') if isinstance(lev_regime, dict) else None
            regime_note = (f"（🧭HK制度 {hk_tier}：基准 {caps['lev_etf_leg_pct']}% ×"
                           f"{leg_mult:g} → {eff_lev_cap}%，{(lev_regime.get('hk') or lev_regime).get('label','')}）"
                           if tightened and leg == 'HK' and isinstance(lev_regime, dict) else '')
            breaches.append({
                'type': 'leveraged_exposure', 'leg': leg, 'ticker': None, 'severity': 'high',
                'detail': f"{leg} 杠杆 ETF = {lev_pct}% (cap {eff_lev_cap}%) — 2x 日内重置，下杀崩/震荡衰减{regime_note}",
                'action': (f"降杠杆=换仓非清仓：把约 {trim_val} {ccy} 的 2x 换成 1x 同因子"
                           f"({_swap_suggestions(hold) or '同因子 1x/标的现货'})，"
                           f"敞口不变、停 decay；🧭转 green 后可换回 2x"),
                'required_reduction': {
                    'kind': 'leveraged_market_value',
                    'minimum_value': trim_val,
                    'currency': ccy,
                    'target_pct': eff_lev_cap,
                    'target_tickers': [
                        h.get('ticker') for h in hold
                        if h.get('shares', 0) > 0 and _is_leveraged_etf(h)
                    ],
                },
            })

        # hard-stop watch on individual leveraged ETFs
        for h in hold:
            if h.get('shares', 0) <= 0 or not _is_leveraged_etf(h):
                continue
            pnl = _holding_pnl_pct(h)
            if pnl is not None and pnl <= caps['lev_etf_stop_pct']:
                hard_stops.append({
                    'ticker': h['ticker'], 'leg': leg, 'pnl_pct': pnl,
                    'severity': 'critical',
                    'detail': f"{h['ticker']} 浮亏 {pnl}% ≤ 硬止损线 {caps['lev_etf_stop_pct']}%",
                    'action': (f"{h['ticker']} 触发杠杆 ETF 硬止损 → 换仓 "
                               f"{('1x 同因子 ' + LEV_1X_SWAP[h['ticker']]) if h.get('ticker') in LEV_1X_SWAP else '同因子 1x/标的现货'}"
                               f"（敞口保留、停 decay，规则非择时）；🧭转 green 再换回 2x"),
                    'required_reduction': {
                        'kind': 'full_leveraged_position',
                        'minimum_shares': h.get('shares'),
                        'minimum_value': (
                            h.get('current_value')
                            or h.get('cost_basis', 0) * h.get('shares', 0)),
                        'currency': ccy,
                        'target_tickers': [h['ticker']],
                        'swap_to': LEV_1X_SWAP.get(h['ticker']),
                    },
                })

    # US per-name leverage dial (lev_regime['us']) — only the 'cut' state (underlying
    # trend-off AND vol hot) becomes a forced directive; 'watch' (calm) stays advisory.
    us_reg = (lev_regime or {}).get('us') if isinstance(lev_regime, dict) else None
    if isinstance(us_reg, dict):
        held_us = {h.get('ticker') for h in us_holdings if h.get('shares', 0) > 0}
        for nm in us_reg.get('names', []):
            if nm.get('state') == 'cut' and nm.get('etf') in held_us:
                vol = nm.get('vol_annualized')
                if vol is None:
                    basis = nm.get('regime_basis') or 'short_ma'
                    detail = (
                        f"🧭 {nm['etf']}=2x{nm['underlying']} 完整波动率不可用；"
                        f"{nm.get('ma_window') or '短'}日均线偏离 "
                        f"{nm.get('dist_ma_pct')}%，按 {basis} 右侧确认制度为 cut"
                    )
                    action_reason = (
                        f"完整波动率不可用，当前仅按 {basis}：标的仍在短均线下，"
                        "2x 暂换现货；短均线重新确认后再评估"
                    )
                else:
                    vol_pct = vol * 100
                    detail = (
                        f"🧭 {nm['etf']}=2x{nm['underlying']} 标的破200线 "
                        f"({nm.get('dist_ma_pct')}%)+波动 {vol_pct:.0f}% 过热 → 杠杆制度 red"
                    )
                    action_reason = (
                        f"标的趋势off 且波动>{int(nm.get('vol_hot_cap',0.7)*100)}%，"
                        "2x 日内重置在下杀里放大衰减；"
                        f"{nm['underlying']} 收复200线(green)再换回 2x"
                    )
                breaches.append({
                    'type': 'regime_delever', 'leg': 'US', 'ticker': nm['etf'], 'severity': 'high',
                    'detail': detail,
                    'action': (
                        f"{nm['etf']} 2x→{nm['underlying']} 现货换仓"
                        f"(driven_by=risk_rule,规则非择时)：{action_reason}"
                    ),
                    'required_reduction': {
                        'kind': 'full_leveraged_position',
                        'target_tickers': [nm['etf']],
                        'swap_to': nm['underlying'],
                    },
                })

    # portfolio-level β from risk.json
    us_risk = risk.get('us') or {}
    us_beta = us_risk.get('beta_spx')
    beta_eligible = (
        us_risk.get('threshold_eligible', True)
        and us_risk.get('beta_threshold_eligible', True)
    )
    if (beta_eligible and isinstance(us_beta, (int, float))
            and us_beta > caps['us_beta_max']):
        breaches.append({
            'type': 'beta', 'leg': 'US', 'ticker': None, 'severity': 'high',
            'detail': f"US β vs S&P = {us_beta} (cap {caps['us_beta_max']}) — 大盘 −1% 本子约 −{us_beta:.1f}%",
            'action': "降 US β：优先削杠杆 ETF(β 主要来源)，不是砍单票 thesis",
            'required_reduction': {
                'kind': 'beta',
                'target_beta': caps['us_beta_max'],
                'target_tickers': [
                    h.get('ticker') for h in us_holdings
                    if h.get('shares', 0) > 0 and _is_leveraged_etf(h)
                ],
            },
        })

    n = len(breaches) + len(hard_stops)
    if n:
        directive = (f"⛔ {len(breaches)} 仓位硬闸 + {len(hard_stops)} 杠杆止损触发。"
                     "每条必须在 Judge 段出一个对应动作(driven_by=risk_rule,纪律性再平衡,"
                     "不算听消息、不受 risk_on HOLD 默认约束)；其余主动 call 仍按 regime guard。"
                     "杠杆腿解套口径=2x→1x 同因子换仓而非清仓(见各 action)。")
    else:
        directive = "✅ 无仓位/杠杆硬闸触发，按常规决策。"

    reentry_rule = ("1x→2x 换回闸：HK=HSTECH 收复 200日线且 20日波动<50%(🧭green ×1.0)；"
                    "US=各标的自身收复 200日线且波动<70%。green 之前不加任何 2x。")

    return {'caps': caps, 'breaches': breaches, 'hard_stop_watch': hard_stops,
            'breach_count': n, 'directive': directive, 'reentry_rule': reentry_rule,
            'lev_regime': lev_regime, 'eff_lev_caps': eff_caps}


GUARDRAIL_HISTORY = WS / 'assets' / 'data' / 'guardrail_history.jsonl'


def _append_guardrail_history(today, guardrail, hk_conc, us_conc, risk):
    """Persist the day's guardrail verdict so its value becomes measurable.

    The caps are the part of this system that demonstrably works — the 2026-06
    drawdown was a construction problem, and they exist to stop it recurring. But
    they were recomputed into gitignored tmp every morning and thrown away, so
    "what did the guardrail prevent?" had no data behind it while every timing
    call was scored to four decimals. One row per brief, appended, idempotent by
    date. Nothing can be reconstructed retroactively, so this starts today and
    accrues; do not expect a verdict from it for some weeks.
    """
    try:
        row = {
            'date': today,
            'breach_count': guardrail.get('breach_count'),
            'breaches': [{k: b.get(k) for k in ('type', 'leg', 'ticker', 'severity', 'detail')}
                         for b in (guardrail.get('breaches') or [])],
            'hard_stop_watch': [{k: h.get(k) for k in ('ticker', 'leg', 'pnl_pct')}
                                for h in (guardrail.get('hard_stop_watch') or [])],
            'eff_lev_caps': guardrail.get('eff_lev_caps'),
            'lev_regime_tier': ((guardrail.get('lev_regime') or {}).get('tier')),
            'hk_top2_pct': (hk_conc or {}).get('top2_pct'),
            'us_top2_pct': (us_conc or {}).get('top2_pct'),
            'us_beta_spx': ((risk or {}).get('us') or {}).get('beta_spx'),
        }
        existing = []
        if GUARDRAIL_HISTORY.exists():
            existing = [l for l in GUARDRAIL_HISTORY.read_text().splitlines()
                        if l.strip() and json.loads(l).get('date') != today]
        GUARDRAIL_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        GUARDRAIL_HISTORY.write_text(
            ''.join(l + '\n' for l in existing)
            + json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
        print(f'  guardrail_history: {today} ({row["breach_count"]} breaches)')
    except Exception as e:  # never block the brief on bookkeeping
        print(f'warn: guardrail history append failed: {e}', file=sys.stderr)


def compute_breakeven_math(hk_holdings, us_holdings, lev_regime=None):
    """解套数学（纯算术，零观点）：每只浮亏持仓回本所需涨幅；2x 另算横盘 decay 成本
    与含 drag 的等效标的涨幅。k 倍日内重置 ETF 的波动拖累（lognormal 近似）=
    (k²−k)/2·σ²/年，k=2 → σ²/年 ≈ σ²/12 每月。诚实口径：直线拉升时 2x 回本更快
    （β 也是 2x）——换 1x 买的是「横盘不失血 + 再跌少挨一半」，不是「回本更快」。
    LLM 报解套/回本相关数字时必须引用这里，不准心算。"""
    us_reg = (lev_regime or {}).get('us') if isinstance(lev_regime, dict) else None
    us_vols = {n.get('etf'): n.get('vol_annualized') for n in (us_reg or {}).get('names', [])}
    hk_dial = (lev_regime.get('hk') or lev_regime) if isinstance(lev_regime, dict) else {}
    rows = []
    for leg, hold in (('HK', hk_holdings), ('US', us_holdings)):
        for h in hold:
            if h.get('shares', 0) <= 0:
                continue
            pnl = _holding_pnl_pct(h)
            if pnl is None or pnl >= 0:
                continue
            cost = h.get('cost_basis', 0) * h['shares']
            cur  = h.get('current_value', cost)
            if not cur:
                continue
            need = (cost / cur - 1) * 100
            row = {'ticker': h['ticker'], 'leg': leg, 'pnl_pct': pnl,
                   'breakeven_need_pct': round(need, 1),
                   'leveraged': bool(_is_leveraged_etf(h))}
            if row['leveraged']:
                sigma = us_vols.get(h['ticker']) if leg == 'US' else hk_dial.get('vol_annualized')
                if isinstance(sigma, (int, float)) and sigma > 0:
                    drag_y = sigma ** 2                     # k=2 → (k²−k)/2·σ² = σ²
                    x_2x = math.sqrt((1 + need / 100) * math.exp(drag_y * 0.5)) - 1
                    row.update({
                        'underlying_vol_pct':        round(sigma * 100, 1),
                        'chop_drag_pct_per_month':   round(drag_y / 12 * 100, 2),
                        'underlying_need_2x_6m_pct': round(x_2x * 100, 1),
                        'underlying_need_if_1x_pct': round(need, 1),
                        'swap_1x':                   LEV_1X_SWAP.get(h['ticker']),
                    })
            rows.append(row)
    rows.sort(key=lambda r: r['pnl_pct'])
    return {
        'rows': rows,
        'note': ('回本涨幅=成本/现价−1。2x 行加印：标的σ、横盘 decay≈σ²/12 每月、半年窗含 drag '
                 '的等效标的涨幅。解读纪律：直线涨→2x 回本更快；横盘→2x 每月白付 decay；'
                 '再跌→2x 双倍挨打。换 1x 买的是后两种情景的保护，不是回本速度。'),
    }


def find_prior_plan(today_iso):
    """Most recent memory/*-plan.json with filename date < today."""
    candidates = sorted((WS / 'memory').glob('*-plan.json'))
    today_filename = f'{today_iso}-plan.json'
    prior = [p for p in candidates if p.name < today_filename]
    return prior[-1] if prior else None


def _is_hk_ticker(t):
    return t.isdigit() and len(t) <= 5


def compute_retrospective(prior_plan_path, portfolio):
    """V2 retrospective: each strategy decision is scored only if its condition fired."""
    if not prior_plan_path:
        return {'prior_plan_date': None, 'decisions': [], 'note': 'first run (no prior plan)'}

    try:
        prior = json.loads(prior_plan_path.read_text())
    except Exception as e:
        return {'error': f'parse prior plan failed: {e}', 'path': str(prior_plan_path)}

    all_holdings = (portfolio['portfolios']['hk_stocks']['holdings'] +
                    portfolio['portfolios']['us_stocks']['holdings'])
    htmap = {h['ticker']: h for h in all_holdings}

    results = []
    for action in prior.get('decisions', []):
        ticker = action.get('ticker')
        h = htmap.get(ticker)
        if not h:
            results.append({
                'ticker': ticker, 'error': 'ticker no longer in portfolio', 'plan': action,
            })
            continue

        condition = action.get('condition') or {}
        trigger_type  = condition.get('type', 'manual')
        trigger_price = condition.get('price')
        size_shares   = (action.get('size') or {}).get('shares')
        bucket        = action.get('action', '')

        current   = h.get('current_price', 0)
        prev_close = h.get('prev_close', current)
        open_px   = h.get('day_open', current)
        day_high  = h.get('day_high', current)
        day_low   = h.get('day_low', current)

        fired = None
        if trigger_type == 'open':
            fired = True
        elif trigger_type == 'price_above' and trigger_price is not None:
            fired = day_high >= trigger_price
        elif trigger_type == 'price_below' and trigger_price is not None:
            fired = day_low <= trigger_price
        # index_breakdown / event / manual → leave as None (LLM judges)

        sim_pnl = None
        execution_price = None
        if fired and size_shares:
            if trigger_type == 'open':
                execution_price = open_px
            elif trigger_price is not None:
                execution_price = trigger_price

            if execution_price is not None:
                # Sell-side actions: PnL = (execution - current) × shares (positive = good)
                if bucket in ('cut', 'trim_on_rebound', 't_only'):
                    sim_pnl = round((execution_price - current) * size_shares, 2)
                # Buy-side actions: PnL = (current - execution) × shares (positive = good)
                elif bucket == 'add_only_on_trigger':
                    sim_pnl = round((current - execution_price) * size_shares, 2)

        results.append({
            'ticker':                   ticker,
            'decision_id':              action.get('decision_id'),
            'episode_id':               action.get('episode_id'),
            'thesis_id':                action.get('thesis_id'),
            'strategy_id':              action.get('strategy_id'),
            'action':                    bucket,
            'plan_trigger_type':        trigger_type,
            'plan_trigger_price':       trigger_price,
            'plan_size_shares':         size_shares,
            'plan_confidence':          action.get('confidence'),
            'plan_rationale':           action.get('rationale'),
            'actual_open':              open_px,
            'actual_close':             current,
            'actual_day_high':          day_high,
            'actual_day_low':           day_low,
            'actual_prev_close':        prev_close,
            'trigger_fired':            fired,
            'simulated_execution_price': execution_price,
            'simulated_pnl':            sim_pnl,
            'pnl_currency':             'HKD' if _is_hk_ticker(ticker) else 'USD',
        })

    # Confidence calibration buckets
    def _calib(lo, hi):
        scored = [r for r in results
                  if r.get('plan_confidence') is not None
                  and lo <= r['plan_confidence'] < hi
                  and r['trigger_fired'] is not None]
        fired = sum(1 for r in scored if r['trigger_fired'])
        return f'{fired}/{len(scored)}' if scored else 'n/a'

    return {
        'prior_plan_date': prior.get('date'),
        'prior_plan_path': str(prior_plan_path),
        'decisions':       results,
        'confidence_calibration': {
            'conf_80_100':  _calib(0.80, 1.01),
            'conf_60_79':   _calib(0.60, 0.80),
            'conf_below_60': _calib(0.0,  0.60),
        },
    }


def collect_peer_scan(portfolio):
    """Delegates to the shared peer scanner (also used by report_preflight)."""
    return peer_scan.collect(portfolio)


def _shares_at_date(ticker, date_iso):
    """Get shares of `ticker` from portfolio.json as committed on/before `date_iso`.
    Returns int shares, or None if can't determine."""
    try:
        r = subprocess.run(
            ['git', '-C', str(WS), 'log', '--pretty=%H',
             f'--before={date_iso} 23:59:59', '-1', '--', 'portfolio.json'],
            capture_output=True, text=True, timeout=10)
        sha = r.stdout.strip()
        if not sha:
            return None
        r = subprocess.run(['git', '-C', str(WS), 'show', f'{sha}:portfolio.json'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        pf = json.loads(r.stdout)
        for region in ('hk_stocks', 'us_stocks'):
            for h in pf['portfolios'][region]['holdings']:
                if h['ticker'] == ticker:
                    return int(h.get('shares', 0))
    except Exception:
        pass
    return None


def _detect_followed(row, min_window_days=None):
    """Compare shares on plan_date vs T+N. Return 'true' / 'false' / 'unknown'.

    Bucket → expected delta:
      cut / trim_on_rebound → shares should DECREASE
      add_only_on_trigger / add_on_breakout → shares should INCREASE
      hold_and_watch / watch / t_only → shares should be UNCHANGED

    min_window_days defaults to `decision_v2.verification_window_days`:
      hold_and_watch / watch / t_only → T+1 (held by next day = followed)
      cut / trim / add → T+2 (give user a working day to actually trade)
    """
    plan_date = row.get('plan_date')
    ticker = row.get('ticker')
    bucket = row.get('bucket', '').lower()
    if not (plan_date and ticker):
        return 'unknown'

    if min_window_days is None:
        # One definition, in decision_v2: _exec_rate needs the identical rule to
        # separate "not verifiable yet" from "never will be", and a second copy
        # here would drift without anything failing.
        min_window_days = decision_v2.verification_window_days(bucket)

    # Day BEFORE plan_date (last commit before plan was created)
    try:
        plan_dt = datetime.strptime(plan_date, '%Y-%m-%d')
        before_dt = (plan_dt - timedelta(days=1)).strftime('%Y-%m-%d')
        after_dt = (plan_dt + timedelta(days=min_window_days)).strftime('%Y-%m-%d')
    except Exception:
        return 'unknown'

    # don't look ahead if window end is in the future
    if datetime.now() < plan_dt + timedelta(days=min_window_days):
        return 'unknown'  # too early; will retry next preflight

    shares_before = _shares_at_date(ticker, before_dt)
    shares_after  = _shares_at_date(ticker, after_dt)
    if shares_before is None or shares_after is None:
        return 'unknown'

    delta = shares_after - shares_before

    # Apply bucket rule
    if bucket in ('cut', 'trim_on_rebound'):
        return 'true' if delta < 0 else 'false'
    if bucket in ('add_only_on_trigger', 'add_on_breakout'):
        return 'true' if delta > 0 else 'false'
    if bucket in ('hold_and_watch', 'watch', 't_only'):
        return 'true' if delta == 0 else 'false'  # you held → followed; you bought/sold → didn't follow plan
    return 'unknown'  # 未识别 bucket




def compute_reflections(portfolio):
    """Episode-level lessons for currently held tickers."""
    rows = decision_v2.episode_representatives(decision_v2.load_decisions(), 't1')

    held = {h['ticker'] for leg in ('hk_stocks', 'us_stocks')
            for h in portfolio['portfolios'][leg]['holdings'] if h.get('shares', 0) > 0}
    SELL = {'cut', 'trim_on_rebound'}
    out = {}
    for tk in sorted(held):
        settled = [r for r in rows if r['ticker'] == tk and (r.get('evaluation') or {}).get('outcome') in ('win', 'loss')]
        if not settled:
            continue
        settled.sort(key=lambda r: r['plan_date'])
        wins = sum(1 for r in settled if (r.get('evaluation') or {}).get('outcome') == 'win')
        # dominant bucket history + a plain lesson
        by_b = {}
        for r in settled:
            by_b.setdefault(r['action'], []).append(r)
        lessons = []
        for b, rs in by_b.items():
            w = sum(1 for r in rs if (r.get('evaluation') or {}).get('outcome') == 'win')
            verb = {'cut': '清', 'trim_on_rebound': '减', 'add_only_on_trigger': '加',
                    'hold_and_watch': '持', 't_only': 'T'}.get(b, b)
            lessons.append(f'{verb}×{len(rs)} 胜{w}')
        recent = settled[-3:]
        out[tk] = {
            'n': len(settled),
            'win_rate': round(wins / len(settled), 2),
            'bucket_history': '; '.join(lessons),
            'recent': [{'date': r['plan_date'], 'strategy_id': r.get('strategy_id'),
                        'action': r['action'], 'conf': r.get('confidence'),
                        'outcome': (r.get('evaluation') or {}).get('outcome'),
                        'benefit_pct': (r.get('evaluation') or {}).get('benefit_t1_pct')} for r in recent],
            'lesson': (f'{tk}: 过去 {len(settled)} 个策略 episode 胜率 {wins/len(settled):.0%}'
                       + ('（主动 call 多半没跑赢持有，本次谨慎）' if wins / len(settled) < 0.5 else '')),
        }
    return out


def trim_abstaining_calibrators(metrics):
    """Inject only the calibrator rows that can still change a sizing decision.

    `hierarchical_calibration.current_group_calibrators` is one row of beta-binomial
    posterior state per `action + driver + condition + regime` group. On 2026-07-27
    that was 42 rows / 27KB — 10.7% of the whole injected context, re-sent on every
    turn of a 17-minute multi-turn run. `build_dashboard.trim_decision_metrics`
    already drops the same block from the public payload (#102); the brief, which
    pays for it far more often, kept shipping all of it.

    Dropping the abstaining rows is behaviour-preserving because both skills that
    read this table define a missing row and an abstaining row as the same outcome:
    "找不到完全匹配行：按 abstain 处理" (daily-deep-brief), "A missing exact row,
    `abstain=true`, or `edge_supported=false` means the signal contributes zero
    incremental size" (portfolio-swarm-review).

    The filter is `evidence_sufficient`, not `edge_supported`, on purpose.
    decision_v2 defines `edge_supported = not abstain and ci[0] > 0.5` while
    `evidence_sufficient = not abstain`, so evidence-sufficient is the strictly
    weaker predicate and *cannot* drop a row that would have multiplied size — it
    also leaves the rows that are one settled episode away from clearing the bar.
    Filtering on `edge_supported` would ship nothing at all on a day like
    2026-07-27, and the table would silently reappear as load-bearing later.

    Counts and reasons for everything dropped stay in the payload, so a shrinking
    table reads as evidence being thin rather than as data going missing.
    """
    if not isinstance(metrics, dict):
        return metrics
    calibration = metrics.get('hierarchical_calibration')
    if not isinstance(calibration, dict):
        return metrics
    groups = calibration.get('current_group_calibrators')
    if not isinstance(groups, list):
        return metrics

    kept = [g for g in groups if isinstance(g, dict) and g.get('evidence_sufficient')]
    omitted = [g for g in groups if g not in kept]
    reasons = {}
    for g in omitted:
        if isinstance(g, dict):
            reason = g.get('abstain_reason') or 'unspecified'
            reasons[reason] = reasons.get(reason, 0) + 1

    trimmed = dict(calibration)
    trimmed['current_group_calibrators'] = kept
    trimmed['current_group_calibrator_count'] = len(groups)
    trimmed['current_group_calibrators_omitted'] = len(omitted)
    trimmed['omitted_abstain_reasons'] = reasons
    trimmed['omitted_rule'] = (
        'Rows with evidence_sufficient=false are omitted; treat any group absent '
        'from this table as abstain (signal_size_multiplier=0), which is what both '
        'skills already require for a missing row.')
    return {**metrics, 'hierarchical_calibration': trimmed}


def compute_decision_metrics():
    """Settle the v2 ledger and return episode-level decision metrics."""
    decisions = decision_v2.load_decisions()
    # Preserve execution ground truth while migrating; prospective detection is
    # applied only to triggered decisions whose execution is still unknown.
    for d in decisions:
        if (d.get('execution') or {}).get('status') != 'unknown':
            continue
        if (d.get('evaluation') or {}).get('triggered') is not True:
            continue
        legacy_view = {'plan_date': d.get('plan_date'), 'ticker': d.get('ticker'),
                       'bucket': d.get('action')}
        verdict = _detect_followed(legacy_view)
        if verdict in ('true', 'false'):
            d['execution'] = {'status': 'followed' if verdict == 'true' else 'not_followed',
                              'detected_at': datetime.now().isoformat(), 'source': 'git_shares_diff'}
    decision_v2.settle_decisions(decisions)
    decision_v2.write_decisions(decisions)
    return trim_abstaining_calibrators(decision_v2.compute_metrics(decisions))


def refresh_daily_bars():
    """Append newly closed sessions to `memory/bars/` before anything settles.

    The canonical bar store is what decision_v2 settles against, and settling only
    *reads* it — nothing in the ledger path ever fetches. The store was backfilled
    once (8aad505, every bar stamped 2026-07-15T23:39) and then had no writer at
    all: no cron, no contract entry, no workflow called fetch_daily_bars.py. So each
    new session was invisible to the ledger, its decisions stayed `pending`
    forever, and the dashboard kept refreshing around a win rate that could no
    longer move. This is that writer, and it has to run ahead of [10].

    Non-fatal by design: a stale store degrades to `pending`, which is bad but
    honest — losing the whole morning brief to a provider hiccup is worse. A
    non-zero exit means the provider now disagrees with a bar the ledger already
    settled against; fetch_daily_bars never overwrites one, so that surfaces as an
    issue for a human to resolve with --repair rather than being applied here.
    """
    cmd = ['python3', str(WS / 'scripts' / 'data' / 'fetch_daily_bars.py')]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    out = (r.stdout or '') + (r.stderr or '')
    res = {'ok': r.returncode == 0, 'returncode': r.returncode}
    m = re.search(r'(\d+) bars added, (\d+) revised', out)
    if m:
        res['added'], res['revised'] = int(m.group(1)), int(m.group(2))
    if r.returncode != 0:
        res['conflicts'] = [ln.strip() for ln in out.splitlines()
                            if ' vs fetched ' in ln or 'insane OHLC' in ln][:10]
    res['stale'] = bars_staleness()
    return res


def _last_closed_session(market):
    """The newest date `market` actually traded and has since closed (17:00 local).

    Walks back through trading_calendar rather than subtracting a day: a missing bar
    is not a closed market. Conflating the two is what once deleted 10 live US rows,
    and on any Monday a naive "yesterday" would report the whole weekend as missing.
    """
    d = datetime.now(ZoneInfo(trading_calendar.MARKET_TZ[market]))
    cur = d.date() if d.hour >= 17 else d.date() - timedelta(days=1)
    for _ in range(14):  # a two-week hole is a broken store, not a holiday
        if trading_calendar.is_trading_day(market, cur):
            return cur
        cur -= timedelta(days=1)
    return None


def bars_staleness():
    """Per-leg gap between the newest stored bar and the last session that closed.

    Reported per leg, never as one number: HK and US close on different days, so a
    shared cutoff would flag one of them as stale every single morning. This is the
    check that would have caught the store going a month without a writer — the
    fetch reporting "+0 bars" looks identical to "nothing to do".

    Two levels, because they mean different things and only one is an alarm:

    * leg — the leg's newest bar vs its calendar. The whole leg falling behind means
      the writer is dead or the provider is blocked. That is the regression guard.
    * `laggards` — tickers behind their own leg, reported but never raised. A thin
      name legitimately prints no bar on a day it never traded (a freshly listed line
      may have only one bar), so flagging those would cry wolf every morning until nobody reads
      the warnings. A real per-ticker outage shows up as a laggard that keeps
      growing, which is a question for a human, not an exit code.
    """
    bars_dir = WS / 'memory' / 'bars'
    out = {}
    for leg, market in (('HK', 'hk'), ('US', 'us')):
        per_ticker = {}
        for p in bars_dir.glob('*.json'):
            try:
                doc = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (doc.get('leg') or '') != leg or not doc.get('bars'):
                continue
            per_ticker[doc.get('ticker') or p.stem] = max(doc['bars'])
        if not per_ticker:
            continue
        newest = max(per_ticker.values())
        expected = _last_closed_session(market)
        missing = []
        # Past the holiday table's horizon `is_trading_day` has no data and answers
        # True for everything, so it would file 2027-01-01 as a missing session every
        # January until someone extends the table. Unlike `closed_reason` it does not
        # fail open. The table is extended each December by convention; until then the
        # honest report is "the calendar expired", not an invented list of holes.
        expired = bool(expected and expected.year > trading_calendar.LATEST_YEAR)
        if expected and not expired:
            cur = date.fromisoformat(newest) + timedelta(days=1)
            while cur <= expected:
                if trading_calendar.is_trading_day(market, cur):
                    missing.append(cur.isoformat())
                cur += timedelta(days=1)
        out[leg] = {'newest_bar': newest,
                    'last_closed_session': expected.isoformat() if expected else None,
                    'missing_sessions': missing,
                    'calendar_expired': expired,
                    'laggards': {t: d for t, d in sorted(per_ticker.items()) if d < newest}}
    return out


def _classify_regime(macro_trim):
    """Derive a coarse risk regime from the macro snapshot so the brief can make it
    EXPLICIT and stop fighting the tape (2026-05-30). calibration shows hold=76% in
    this regime — when risk_on, the default action should be HOLD and active cuts need
    a hard negative catalyst. Uses what macro_trim has: VIX level, Fear&Greed score,
    SPX/NDX 1-day direction. Returns {'label','score','reasons'} or None if too sparse."""
    if not macro_trim:
        return None
    score = 0
    reasons = []
    fg = (macro_trim.get('fear_greed') or {})
    fg_score = fg.get('score')
    if isinstance(fg_score, (int, float)):
        if fg_score >= 60:
            score += 1; reasons.append(f'F&G {fg_score:.0f} greed')
        elif fg_score <= 40:
            score -= 1; reasons.append(f'F&G {fg_score:.0f} fear')
    vix = (macro_trim.get('vix') or {}).get('price')
    if isinstance(vix, (int, float)):
        if vix < 18:
            score += 1; reasons.append(f'VIX {vix:.0f} calm')
        elif vix > 25:
            score -= 1; reasons.append(f'VIX {vix:.0f} stress')
    spx_c = (macro_trim.get('spx') or {}).get('change_pct')
    ndx_c = (macro_trim.get('nasdaq') or {}).get('change_pct')
    if isinstance(spx_c, (int, float)) and isinstance(ndx_c, (int, float)):
        if spx_c > 0 and ndx_c > 0:
            score += 1; reasons.append('SPX+NDX 同向上行')
        elif spx_c < 0 and ndx_c < 0:
            score -= 1; reasons.append('SPX+NDX 同向下行')
    if not reasons:
        return None
    label = 'risk_on' if score >= 2 else ('risk_off' if score <= -2 else 'neutral')
    return {'label': label, 'score': score, 'reasons': reasons}


def _recent_price_moves(tickers, lookback_sessions=5):
    """Per-ticker price move over the last N snapshot sessions — fuels the
    'is this news already priced in?' judgement (2026-05-30). A bull market
    prices good news fast: if the stock already ran on a catalyst, acting on
    that headline is chasing. Returns {ticker: {'px_pct': float, 'n_sessions': int}}.
    Derived from memory/snapshots/{date}.json (current_price per holding); no fetch."""
    import glob
    want = set(tickers)
    if not want:
        return {}
    files = sorted(f for f in glob.glob(str(SNAPSHOT_DIR / '*.json')))
    # keep the most recent (lookback+1) snapshots so a 5-session move has both ends
    files = files[-(lookback_sessions + 1):]
    if len(files) < 2:
        return {}
    series = {t: [] for t in want}  # ticker -> [px oldest..newest]
    for fp in files:
        try:
            snap = json.loads(Path(fp).read_text())
        except Exception:
            continue
        for leg in ('us_stocks', 'hk_stocks'):
            for h in (snap.get('portfolios', {}).get(leg, {}) or {}).get('holdings', []) or []:
                tk = h.get('ticker')
                px = h.get('current_price')
                if tk in want and px not in (None, 0):
                    series[tk].append(px)
    out = {}
    for tk, pxs in series.items():
        if len(pxs) >= 2 and pxs[0]:
            out[tk] = {'px_pct': round((pxs[-1] / pxs[0] - 1) * 100, 1),
                       'n_sessions': len(pxs) - 1}
    return out


def load_em_news(issues):
    """Read em_news.json (Eastmoney Chinese-language info layer) → LLM-friendly subset.

    Widens the brief's information inputs where clawock is thinnest: HK-holding
    Chinese news + market 7x24 快讯. Catalyst-grade (dated, company-specific), so
    it feeds the catalyst-gate. Stale/missing → {} (warn-only, never blocks)."""
    path = WS / 'assets' / 'data' / 'em_news.json'
    if not path.exists():
        issues.append('em_news.json 缺失 — fetch_em_news 未跑(中文消息源)')
        return {}
    try:
        d = json.loads(path.read_text())
        hold = {tk: {'name': v.get('name'),
                     'items': [{'date': i.get('date'), 'title': i.get('title')}
                               for i in (v.get('items') or [])[:3]]}
                for tk, v in (d.get('holdings_news') or {}).items()}
        mkt = [{'date': i.get('date'), 'title': i.get('title')}
               for i in (d.get('market_724') or [])[:5]]
        return {'holdings_news': hold, 'market_724': mkt,
                'generated_at': d.get('generated_at')}
    except Exception as e:
        issues.append(f'em_news.json 解析失败: {e}')
        return {}


def _payload_age_hours(payload):
    """Age in hours from the payload's own `generated_at`, or None if absent/unparseable.

    WHY NOT file mtime (2026-07 audit): `actions/checkout` stamps every tracked
    file with a fresh checkout time, so a committed-days-ago sidecar reads as
    seconds old. The off-host brief fallback used st_mtime and therefore fed
    stale macro/sentiment/influencer into a live trading brief while labelling it
    fresh. The producer stamps `generated_at`; that is the only honest clock.
    Callers treat None (missing/bad stamp) as STALE — an unprovable age is not a
    fresh one.
    """
    gen = (payload or {}).get('generated_at')
    if not gen:
        return None
    try:
        t = datetime.fromisoformat(str(gen).replace('Z', '+00:00'))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


# A materially future generated_at (beyond clock skew) is as untrustworthy as an
# old one — it means a broken producer clock, not fresh data.
_CLOCK_SKEW_H = 2


def _is_stale(age, cutoff_h):
    """True if age (hours, or None) is unusable: unknown, too old, or from the
    future beyond clock skew. Callers omit stale data rather than feed it."""
    return age is None or age > cutoff_h or age < -_CLOCK_SKEW_H


def _age_str(age):
    return f'{age:.0f}h' if age is not None else 'unknown-age (no generated_at)'


def load_macro_and_sentiment(today, issues):
    """Read GH-Action-produced macro.json + sentiment.json; trim to LLM-friendly subset.

    Files are written daily by sentiment-scan.yml / macro-scan.yml. Stale (>36h)
    or missing files emit a non-fatal warn — brief still runs, just without these
    sections.

    Returns: (macro_trim, sentiment_trim) — either may be {} on miss.
    """
    macro_path = WS / 'assets' / 'data' / 'macro.json'
    sent_path  = WS / 'assets' / 'data' / 'sentiment.json'
    stale_cutoff_h = 36

    macro_trim = {}
    try:
        if not macro_path.exists():
            print(f'   ⚠ macro.json missing — sentiment-scan never ran')
            issues.append('macro snapshot missing')
        else:
            m = json.loads(macro_path.read_text())
            age = _payload_age_hours(m)
            if _is_stale(age, stale_cutoff_h):
                # OMIT stale/unknown-age data — do NOT feed it as fresh, and do NOT
                # append to `issues` (main() returns exit 1 on any issue, which
                # under the fallback workflow's pipefail would hard-fail the entire
                # brief — a worse outage than a missing macro section). The brief
                # runs without macro; downstream postflight sees no macro context.
                print(f'   ⚠ macro stale/unknown ({_age_str(age)}, cutoff '
                      f'{stale_cutoff_h}h) — omitting from brief (non-fatal)')
            else:
                def _q(k):
                    v = m.get(k)
                    if not v: return None
                    return {'price': v.get('price'), 'change_pct': v.get('change_pct'),
                            'source': v.get('source')}
                macro_trim = {
                    'as_of':        m.get('generated_at'),
                    'age_hours':    round(age, 1),
                    'vix':          _q('vix'),
                    'dxy':          _q('dxy'),
                    'treasury_10y_yield_pct': (m.get('treasury_10y') or {}).get('yield_pct'),
                    'fear_greed':   m.get('fear_greed'),
                    'hsi':          _q('hsi'),
                    'hstech':       _q('hstech'),
                    'spx':          _q('spx'),
                    'nasdaq':       _q('nasdaq'),
                    'fed_press':    (m.get('fed_press') or [])[:3],
                }
                macro_trim['regime'] = _classify_regime(macro_trim)  # risk_on/neutral/risk_off
                fg = macro_trim['fear_greed'] or {}
                print(f'   macro: VIX {(macro_trim["vix"] or {}).get("price","?")}, '
                      f'F&G {fg.get("score","?")} ({fg.get("rating","?")}), '
                      f'fed_press {len(macro_trim["fed_press"])}')
    except Exception as e:
        print(f'   ⚠ macro load failed: {e}')
        issues.append(f'macro load exception: {type(e).__name__}')

    sentiment_trim = {}
    try:
        if not sent_path.exists():
            print(f'   ⚠ sentiment.json missing — sentiment-scan never ran')
            issues.append('sentiment snapshot missing')
        else:
            s = json.loads(sent_path.read_text())
            age = _payload_age_hours(s)
            if _is_stale(age, stale_cutoff_h):
                # Omit stale/unknown sentiment (non-fatal — see macro note above).
                print(f'   ⚠ sentiment stale/unknown ({_age_str(age)}, cutoff '
                      f'{stale_cutoff_h}h) — omitting from brief (non-fatal)')
            else:
                # price-in lens: recent 5-session move per signalled ticker (priced-in check)
                signalled = [t.get('ticker') for t in s.get('tickers', [])
                             if t.get('reddit_mentions_7d', 0) or t.get('google_news_en')
                             or t.get('google_news_zh')]
                moves = _recent_price_moves(signalled)
                tickers_out = []
                for t in s.get('tickers', []):
                    reddit_n  = t.get('reddit_mentions_7d', 0)
                    gn_en     = t.get('google_news_en') or []
                    gn_zh     = t.get('google_news_zh') or []
                    # Skip noise: 0 mention + 0 news
                    if reddit_n == 0 and not gn_en and not gn_zh:
                        continue
                    tickers_out.append({
                        'ticker': t.get('ticker'),
                        'name':   t.get('name'),
                        'region': t.get('region'),
                        'reddit_mentions_7d': reddit_n,
                        'reddit_top': [{'title': p.get('title'), 'score': p.get('score'),
                                        'comments': p.get('num_comments')}
                                       for p in (t.get('reddit_posts') or [])[:3]],
                        'news_top':   [n.get('title') for n in (gn_en + gn_zh)[:3] if n.get('title')],
                        'recent_move': moves.get(t.get('ticker')),  # {px_pct, n_sessions} or None — priced-in check
                    })
                sentiment_trim = {
                    'as_of':       s.get('generated_at'),
                    'age_hours':   round(age, 1),
                    'sources':     s.get('sources', []),
                    'tickers':     tickers_out,
                }
                with_signal = sum(1 for t in tickers_out if t['reddit_mentions_7d'] or t['news_top'])
                print(f'   sentiment: {with_signal}/{len(s.get("tickers",[]))} tickers '
                      f'have reddit/news signal')
    except Exception as e:
        print(f'   ⚠ sentiment load failed: {e}')
        issues.append(f'sentiment load exception: {type(e).__name__}')

    return macro_trim, sentiment_trim


def load_influencer_feed(issues):
    """Read GH-Action-produced influencer_feed.json (Trump/Musk/Serenity radar).

    Written by influencer-scan.yml before the brief. Stale (>36h)/missing → warn,
    brief still runs without the 名人异动 section. Returns trimmed dict or {}.
    """
    path = WS / 'assets' / 'data' / 'influencer_feed.json'
    try:
        if not path.exists():
            print('   ⚠ influencer_feed.json missing — influencer-scan never ran')
            issues.append('influencer feed missing')
            return {}
        d = json.loads(path.read_text())
        age = _payload_age_hours(d)
        if _is_stale(age, 36):
            # Omit stale/unknown influencer feed (non-fatal — see macro note above);
            # brief runs without the 名人异动 section rather than on stale statements.
            print(f'   ⚠ influencer feed stale/unknown ({_age_str(age)}) '
                  f'— omitting from brief (non-fatal)')
            return {}
        # Trim each item to the fields the brief needs.
        def _trim(it):
            return {k: it.get(k) for k in
                    ('author', 'stance', 'relevance', 'held', 'new_ideas',
                     'sector_holdings', 'sectors', 'summary_cn')}
        out = {
            'as_of':     d.get('generated_at'),
            'age_hours': round(age, 1),
            'counts':    d.get('counts', {}),
            'held_hits': [_trim(x) for x in d.get('held_hits', [])][:6],
            'new_ideas': [_trim(x) for x in d.get('new_ideas', [])][:6],
            'sector_hits': [_trim(x) for x in d.get('sector_hits', [])][:4],
        }
        c = out['counts']
        print(f'   influencer: {c.get("held_hits",0)} held-hits, '
              f'{c.get("new_ideas",0)} new-ideas, {c.get("sector_hits",0)} sector')
        return out
    except Exception as e:
        print(f'   ⚠ influencer feed load failed: {e}')
        issues.append(f'influencer load exception: {type(e).__name__}')
        return {}


def main(argv=None):
    # This script took no arguments at all, so `--help` was not "unsupported" —
    # it was ignored, and the full preflight ran: live price fetches, SEC EDGAR,
    # Tavily. A probe meant to cost nothing did a minutes-long real run.
    #
    # CI wraps this call in `|| true`, which reads like the case was handled. It
    # is not: `|| true` catches a non-zero exit, and this never exited non-zero —
    # it hung. On 2026-08-06 that consumed the validate job's entire 10-minute
    # budget and failed a PR that had nothing to do with it.
    #
    # Parsing argv also restores the contract the repo relies on when an agent
    # probes a script: `--help` exits 0 having done nothing, and an unknown flag
    # exits 2 rather than being silently ignored — the latter is what turns
    # "mistyped argument plus valid input" into a successful-looking no-op.
    argparse.ArgumentParser(
        description=(
            "Deterministic data collection for the daily-deep-brief harness. "
            "Takes no arguments; the date comes from TODAY or HKT now()."
        ),
    ).parse_args(argv)

    # Date in HKT (the system's canonical TZ), or honor the TODAY env that the
    # brief-fallback workflow exports — so the context filename here always matches
    # the date the fallback script reads. Naive now() = runner UTC, which mismatched
    # HKT in the 16:00–23:59 UTC window and broke off-schedule fallback runs.
    today = (os.environ.get('TODAY')
             or datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d'))
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    issues = []
    job_name = '盘前深度简报'
    slot = workflow_outcomes.slot_for_job(job_name)
    workflow_outcomes.record_stage(job_name, 'preflight', 'pending', slot=slot)

    # Holiday/weekend gate: the brief covers both markets, so skip ONLY when both
    # HK and US are closed (still runs if either trades). At 08:00 HKT the relevant
    # US session is the just-closed NY day, which trading_calendar reads correctly
    # (NY-local date is still the prior calendar day at that hour).
    hk_closed = trading_calendar.closed_reason('hk')
    us_closed = trading_calendar.closed_reason('us')
    if hk_closed and us_closed:
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'skipped', slot=slot,
            reason=f'港股{hk_closed}+美股{us_closed}',
        )
        result = {'status': 'market_closed', 'date': today,
                  'reason': f'港股{hk_closed}+美股{us_closed}', 'skip': True}
        (TMP_DIR / f'brief-context-{today}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        print(f'=== MARKET CLOSED — 港股{hk_closed} + 美股{us_closed} ({today}) ===')
        print('SKIP：两市均休市，不生成简报、不调用 send/postflight，本回合结束。')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f'═════ brief_preflight.py | {today} ═════')

    # [1] Refresh prices
    print('\n[1/14] Refresh US prices')
    us_out, us_ok = _run('scripts/data/analyze_us_stocks.py', ['--no-news'])
    if not us_ok:
        issues.append(f'US refresh failed: {us_out[-200:]}')
        print(f'   ⚠️  {issues[-1]}')
    else:
        print('   ✓ done')

    print('[2/14] Refresh HK prices')
    hk_out, hk_ok = _run('scripts/data/analyze_hk_stocks.py', ['--no-news'])
    if not hk_ok:
        issues.append(f'HK refresh failed: {hk_out[-200:]}')
        print(f'   ⚠️  {issues[-1]}')
    else:
        print('   ✓ done')

    # [3] FX
    print('[3/14] FX rate')
    fx = fetch_fx_rate()
    if 'error' in fx:
        issues.append(f'FX fallback used: {fx["error"][-200:]}')
    print(f'   USDHKD = {fx["rate"]}  ({fx["source"]})')

    # [4] Snapshot
    print('[4/14] Portfolio snapshot')
    portfolio_path = WS / 'portfolio.json'
    snapshot_path  = SNAPSHOT_DIR / f'{today}.json'
    snapshot_path.write_bytes(portfolio_path.read_bytes())
    print(f'   ✓ {snapshot_path.name}')

    # Load for downstream
    portfolio = json.loads(portfolio_path.read_text())

    # [5] Concentration
    print('[5/14] Concentration')
    hk_conc = compute_concentration(portfolio['portfolios']['hk_stocks']['holdings'])
    us_conc = compute_concentration(portfolio['portfolios']['us_stocks']['holdings'])
    lookthrough = compute_lookthrough_exposure(portfolio)
    print(f'   HK: HHI={hk_conc.get("hhi"):.3f} {hk_conc.get("verdict")} '
          f'(Top2 {hk_conc.get("top2_pct")}%)')
    print(f'   US: HHI={us_conc.get("hhi"):.3f} {us_conc.get("verdict")} '
          f'(Top2 {us_conc.get("top2_pct")}%)')
    print(f'   Look-through: HK factor HHI={lookthrough["hk"]["factor_hhi"]:.3f}; '
          f'US factor HHI={lookthrough["us"]["factor_hhi"]:.3f}')

    # Book totals (FX-aware)
    rate = fx['rate']
    hk_pnl_hkd = portfolio['portfolios']['hk_stocks'].get('total_pnl', 0)
    us_pnl_usd = portfolio['portfolios']['us_stocks'].get('total_pnl', 0)
    book = {
        'hk_pnl_hkd':      round(hk_pnl_hkd, 2),
        'us_pnl_usd':      round(us_pnl_usd, 2),
        'usd_base_total':  round(hk_pnl_hkd / rate + us_pnl_usd, 2),
        'hkd_base_total':  round(hk_pnl_hkd + us_pnl_usd * rate, 2),
        'fx_used':         rate,
    }

    # [6] SEC EDGAR
    print('[6/14] SEC EDGAR US singles')
    us_fund = collect_us_fundamentals(portfolio)
    for t, data in us_fund.items():
        if 'error' in data:
            print(f'   ⚠️  {t}: {data["error"][:80]}')
            issues.append(f'SEC EDGAR {t} failed')
        else:
            kf = data.get('key_financials', {})
            print(f'   ✓ {t}: {len(kf)} concepts')

    # [7] Retrospective
    print('[7/14] Retrospective')
    prior_plan = find_prior_plan(today)
    retro = compute_retrospective(prior_plan, portfolio)
    if retro.get('prior_plan_date'):
        actions = retro['decisions']
        fired = sum(1 for a in actions if a.get('trigger_fired') is True)
        not_fired = sum(1 for a in actions if a.get('trigger_fired') is False)
        ambiguous = sum(1 for a in actions if a.get('trigger_fired') is None and 'error' not in a)
        print(f'   prior plan: {retro["prior_plan_date"]}')
        print(f'   fired: {fired}   not fired: {not_fired}   ambiguous (manual/event): {ambiguous}')
        print(f'   conf cal: 80%+ {retro["confidence_calibration"]["conf_80_100"]}, '
              f'60-79% {retro["confidence_calibration"]["conf_60_79"]}')
    else:
        print(f'   first run (no prior plan)')

    # [8] Peer scan — for each active holding, fetch peer prices + flag divergence
    print('[8/14] Peer scan')
    peer_scan = collect_peer_scan(portfolio)
    print(f'   {len(peer_scan)} holdings with peer data; {sum(1 for h in peer_scan.values() if h.get("divergence_signal"))} divergence signals')

    # [9] Canonical bars — must precede [10]: settling only reads this store.
    print('[9/14] Refresh canonical daily bars')
    bars = refresh_daily_bars()
    if not bars.get('ok'):
        if bars.get('conflicts'):
            # Stored bars the ledger already settled against now disagree with the
            # provider. Never auto-applied — see fetch_daily_bars.py --repair.
            print(f'   ⚠ {len(bars["conflicts"])} provider conflicts, nothing overwritten:')
            for c in bars['conflicts'][:5]:
                print(f'     {c}')
            issues.append(f'{len(bars["conflicts"])} bar conflicts need --repair')
        else:
            print(f'   ⚠ bar refresh failed: {bars.get("error", "")[:150]}')
            issues.append('daily bar refresh failed')
    else:
        print(f'   +{bars.get("added", 0)} bars, {bars.get("revised", 0)} revised')
    for leg, st in (bars.get('stale') or {}).items():
        miss = st.get('missing_sessions') or []
        if st.get('calendar_expired'):
            # Actionable and specific: the check is blind, rather than quietly
            # inventing a holiday-shaped hole every January.
            print(f'   ⚠ {leg}: trading calendar table ends at '
                  f'{trading_calendar.LATEST_YEAR}; freshness unverifiable')
            issues.append(f'trading_calendar table expired past '
                          f'{trading_calendar.LATEST_YEAR} — extend it; {leg} bar '
                          f'freshness cannot be checked')
        elif miss:
            # "+0 bars" and "the store has no writer" print identically; only the
            # calendar tells them apart, so an unfetched session is an issue here.
            print(f'   ⚠ {leg}: newest bar {st["newest_bar"]}, last close '
                  f'{st["last_closed_session"]} — {len(miss)} session(s) missing: {miss}')
            issues.append(f'{leg} bars missing {len(miss)} session(s); '
                          f'those decisions cannot settle')
        else:
            print(f'   ✓ {leg}: current through {st["newest_bar"]}')
        if st.get('laggards'):
            # Informational: thin names skip sessions legitimately. See bars_staleness.
            print(f'     {leg} behind leg: '
                  + ', '.join(f'{t}@{d}' for t, d in st['laggards'].items()))

    # [10] V2 episode metrics — triggered-only, strategy-aware, cluster-bootstrap
    print('[10/14] Decision metrics v2')
    decision_metrics = compute_decision_metrics()
    # Brier is never printed bare: alone it reads as "0.295, close enough to 0".
    # It only means something against the constant-forecast baseline it has to beat.
    print(f'   {decision_metrics.get("settled_episodes", 0)} settled episodes / '
          f'{decision_metrics.get("raw_decisions", 0)} raw decisions; '
          f'Brier={decision_metrics.get("brier")} vs constant-forecast baseline '
          f'{decision_metrics.get("brier_baseline_loo")} '
          f'({"beats" if decision_metrics.get("brier_beats_baseline") else "LOSES to"} it)')
    hierarchical = decision_metrics.get('hierarchical_calibration') or {}
    prequential = hierarchical.get('after_warmup') or {}
    print(f'   hierarchical prequential: n={prequential.get("n", 0)} '
          f'Brier={prequential.get("calibrated_brier")} vs raw '
          f'{prequential.get("raw_brier")}; '
          f'{hierarchical.get("abstained_predictions", 0)} historical abstentions / '
          f'{hierarchical.get("edge_supported_predictions", 0)} edge-supported')
    active_v2 = decision_metrics.get('active') or {}
    print(f'   active: n={active_v2.get("n_episodes", 0)} '
          f'avg benefit={active_v2.get("avg_benefit_pct")}%, '
          f'cluster CI={active_v2.get("cluster_ci95")}')

    # [9b] Reflection memory — per held ticker, prior call outcomes (TradingAgents-style)
    reflections = compute_reflections(portfolio)
    if reflections:
        print(f'[9b/11] Reflections: {len(reflections)} held tickers with prior-call history')

    # [10] Risk metrics — Tier 2: β / vol / DD / Sharpe / margin sim
    print('[11/14] Risk metrics')
    risk = {}
    try:
        r = subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'portfolio_risk_metrics.py')],
                           capture_output=True, text=True, timeout=180, check=False)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or '')[-500:]
            print(f'   ⚠ risk metrics exited {r.returncode}: ...{tail}')
        risk_path = WS / 'assets' / 'data' / 'risk.json'
        if risk_path.exists():
            risk = json.loads(risk_path.read_text())
            # Freshness check — silent failures can leave a stale file in place
            from datetime import datetime as _dt, timezone as _tz
            gen = risk.get('generated_at', '')
            try:
                age_h = (_dt.now(_tz.utc) - _dt.fromisoformat(gen.replace('Z','+00:00'))).total_seconds() / 3600
                if age_h > 26:  # daily refresh; >1 day = stale
                    print(f'   ⚠ risk.json stale: generated_at={gen} ({age_h:.0f}h ago)')
            except Exception:
                pass
            alerts = risk.get('alerts', [])
            print(f'   US β={risk.get("us",{}).get("beta_spx","?")}, combined vol={risk.get("combined",{}).get("vol_30d_annualized","?")}, alerts={len(alerts)}')
            for a in alerts[:5]:
                print(f'   ⚠ {a["type"]:18s} ({a["severity"]:6s}) {a["detail"][:80]}')
    except Exception as e:
        print(f'   ⚠ risk metrics failed: {e}')

    # [10b] Leverage dial — HSTECH 200DMA trend + 20d vol → leveraged-ETF cap multiplier
    lev_regime = None
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'compute_regime.py')],
                       capture_output=True, text=True, timeout=60, check=False)
        lr_path = WS / 'assets' / 'data' / 'lev_regime.json'
        if lr_path.exists():
            lev_regime = json.loads(lr_path.read_text())
            print(f'   🧭 lev_regime: {lev_regime.get("tier")} (×{lev_regime.get("lev_cap_mult")}) — {lev_regime.get("label","")}')
    except Exception as e:
        print(f'   ⚠ lev_regime compute failed: {e}')

    # [10b2] 量化因子层 — 趋势/动量/RSI/z-score/ATR吊灯止损/vol-target（纯算术，
    # LLM 技术面判断只准引用此表）。merge-not-overwrite，单只抓空保留旧值。
    quant_signals = {}
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'compute_quant_signals.py')],
                       capture_output=True, text=True, timeout=120, check=False)
        qs_path = WS / 'assets' / 'data' / 'quant_signals.json'
        if qs_path.exists():
            quant_signals = json.loads(qs_path.read_text())
            tags = {k: v.get('tag') for k, v in (quant_signals.get('rows') or {}).items()
                    if v.get('status') in (None, 'fresh')}
            nonfresh = [k for k, v in (quant_signals.get('rows') or {}).items()
                        if v.get('status') not in (None, 'fresh')]
            print(f'   📊 quant_signals: {len(tags)} fresh symbols'
                  f' / {len(nonfresh)} unavailable — '
                  + '; '.join(f'{k}:{v}' for k, v in list(tags.items())[:4]) + ' …')
    except Exception as e:
        print(f'   ⚠ quant_signals compute failed: {e}')

    # [10b3] 因子 edge 自检 — 历史留痕 vs forward return 对账（自迭代：因子话语权由
    # hit_rate 决定，样本<20 不解锁）。纯本地文件运算。
    quant_review = {}
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'quant_signal_review.py')],
                       capture_output=True, text=True, timeout=60, check=False)
        qr_path = WS / 'assets' / 'data' / 'quant_signal_review.json'
        if qr_path.exists():
            quant_review = json.loads(qr_path.read_text())
            print(f'   📐 factor edge: {quant_review.get("summary", "")[:80]}')
    except Exception as e:
        print(f'   ⚠ quant_signal_review failed: {e}')

    # [10b3b] Cross-sectional factor research — curated peers + 1x underlyings,
    # sector-neutral ranks and strictly prospective activation. The full artifact
    # stays on disk; context gets a compact view to avoid spending brief tokens on
    # 38 complete research rows. `usable_for_decisions=false` is a hard boundary.
    cross_sectional_factor = {}
    cross_sectional_factor_ctx = {}
    try:
        subprocess.run(
            ['python3', str(WS / 'scripts' / 'data' / 'cross_sectional_factor.py')],
            capture_output=True, text=True, timeout=240, check=False,
        )
        cs_path = WS / 'assets' / 'data' / 'cross_sectional_factor.json'
        if cs_path.exists():
            cross_sectional_factor = json.loads(cs_path.read_text())
            activation = cross_sectional_factor.get('activation') or {}
            rankings = cross_sectional_factor.get('live_rankings') or {}
            held = {
                h.get('ticker')
                for leg in ('hk_stocks', 'us_stocks')
                for h in portfolio.get('portfolios', {}).get(leg, {}).get('holdings', [])
                if h.get('shares', 0) > 0
            }
            held_rows = {
                ticker: row for ticker, row in rankings.items() if ticker in held
            }
            leaders = sorted(
                rankings.items(),
                key=lambda item: item[1].get('composite_score') or -999,
                reverse=True,
            )[:8]
            cross_sectional_factor_ctx = {
                'as_of': cross_sectional_factor.get('as_of'),
                'activation': activation,
                'validation': cross_sectional_factor.get('validation'),
                'held_rankings': held_rows,
                'sector_leaders': dict(leaders),
                'leveraged_proxy_decay': cross_sectional_factor.get(
                    'leveraged_proxy_decay'
                ),
            }
            print(
                f'   🧪 cross-sectional: active={activation.get("active", False)}, '
                f'blockers={",".join(activation.get("blockers") or [])}'
            )
    except Exception as e:
        print(f'   ⚠ cross-sectional factor failed: {e}')

    # 证据页：读上面刚刷新的产物重新生成，保证「测了什么、什么没通过」不落后于事实。
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'build_evidence.py')],
                       capture_output=True, text=True, timeout=60, check=False)
    except Exception as e:
        print(f'   ⚠ evidence page rebuild failed: {e}')

    # [10b3c] Curated peer residual/leadership research. HK taxonomy is explicitly
    # manual-only; leveraged products are folded to 1x before basket construction.
    # As with the broader cross-sectional layer, inactive rules are display-only.
    peer_residual_ctx = {}
    try:
        subprocess.run(
            ['python3', str(WS / 'scripts' / 'data' / 'peer_residual_engine.py')],
            capture_output=True, text=True, timeout=180, check=False,
        )
        pr_path = WS / 'assets' / 'data' / 'peer_residual.json'
        if pr_path.exists():
            peer_residual = json.loads(pr_path.read_text())
            peer_live = peer_residual.get('live') or {}
            held = {
                h.get('ticker')
                for leg in ('hk_stocks', 'us_stocks')
                for h in portfolio.get('portfolios', {}).get(leg, {}).get('holdings', [])
                if h.get('shares', 0) > 0
            }
            peer_residual_ctx = {
                'as_of': peer_residual.get('as_of'),
                'taxonomy': peer_residual.get('taxonomy'),
                'calibration': peer_residual.get('calibration'),
                'rule_activation': peer_residual.get('rule_activation'),
                'held': {
                    ticker: row for ticker, row in peer_live.items()
                    if ticker in held
                },
            }
            active_peer_rules = [
                rule for rule, state in
                (peer_residual.get('rule_activation') or {}).items()
                if state.get('active')
            ]
            print(
                f'   🧭 peer residual: active_rules='
                f'{",".join(active_peer_rules) or "none"}, HK_auto=false'
            )
    except Exception as e:
        print(f'   ⚠ peer residual engine failed: {e}')

    # [10b4] T+0 牌面评级 — 零额外请求（从已抓字段 + quant ATR 推导），追高检测。
    # 紧跟 quant_signals 之后跑（依赖其 ATR 刷新）。
    t0_setups = {}
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'compute_t0_setups.py')],
                       capture_output=True, text=True, timeout=60, check=False)
        t0_path = WS / 'assets' / 'data' / 't0_setups.json'
        if t0_path.exists():
            t0_setups = json.loads(t0_path.read_text())
            chase = [k for k, v in (t0_setups.get('rows') or {}).items() if v.get('grade') == '🔴']
            print(f'   🎯 T+0 牌面: {len(t0_setups.get("rows", {}))} 票'
                  + (f' — 🔴 追高: {", ".join(chase)}' if chase else ''))
    except Exception as e:
        print(f'   ⚠ t0_setups compute failed: {e}')

    # [10b4b] T+0 牌面 edge 自检 — 牌面评级对账 T+1 forward return（数据背书）。
    # 零网络：结算用历史留痕的 close，绝不每分钟抓价。
    t0_review = {}
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 't0_setup_review.py')],
                       capture_output=True, text=True, timeout=60, check=False)
        tr_path = WS / 'assets' / 'data' / 't0_setup_review.json'
        if tr_path.exists():
            t0_review = json.loads(tr_path.read_text())
            print(f'   🎯 T+0 牌面背书: {t0_review.get("summary", "")[:80]}')
    except Exception as e:
        print(f'   ⚠ t0_setup_review failed: {e}')

    # [10b6] 中文消息源 — Eastmoney HK 持仓新闻 + 7x24 快讯（信息广度，喂 catalyst-gate）。
    # 借鉴 UZI-Skill 的数据源广度；信息收集是 LLM 强项 + kcn token 充足。失败 fail-soft。
    try:
        subprocess.run(['python3', str(WS / 'scripts' / 'data' / 'fetch_em_news.py')],
                       capture_output=True, text=True, timeout=60, check=False)
    except Exception as e:
        print(f'   ⚠ fetch_em_news failed: {e}')

    # [10b5] 数据体检闸 — 把历史踩过的数字 bug 固化成自动门。warn-only 注入 context
    # （遵 feedback_no_individual_cron_alerts 不推送），ERROR 由 build_status 健康卡暴露。
    integrity = {}
    try:
        sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
        import preflight_integrity as _pi
        integrity = _pi.check()
        if not integrity['ok']:
            print(f'   🔴 数据体检 {integrity["error_count"]} ERROR：')
            for f in integrity['findings']:
                if f['level'] == 'ERROR':
                    print(f'      • {f["code"]}: {f["msg"][:90]}')
        elif integrity['warn_count']:
            print(f'   🟡 数据体检 {integrity["warn_count"]} WARN（见 integrity_report.json）')
        else:
            print('   ✅ 数据体检全过')
    except Exception as e:
        print(f'   ⚠ integrity check failed: {e}')

    # [10c] Risk guardrails — position-sizing / leverage hard caps → trim/cut directives
    guardrail = compute_risk_guardrail(
        portfolio['portfolios']['hk_stocks']['holdings'],
        portfolio['portfolios']['us_stocks']['holdings'],
        hk_conc, us_conc, risk, lev_regime=lev_regime)
    guardrail = risk_discipline.attach_breach_ids(guardrail)
    _append_guardrail_history(today, guardrail, hk_conc, us_conc, risk)
    discipline = {}
    try:
        discipline = risk_discipline.reconcile_guardrail(
            guardrail, portfolio)
    except Exception as e:
        discipline = {'error': f'{type(e).__name__}: {e}', 'records': []}
        issues.append(f'risk discipline reconcile failed: {type(e).__name__}')
    print(f'   guardrail: {guardrail["breach_count"]} breaches/stops — {guardrail["directive"][:64]}')
    if discipline.get('error'):
        print(f'   🔴 durable risk ledger failed: {discipline["error"]}')
    else:
        print(f'   durable risk ledger: {discipline.get("open_count", 0)} open / '
              f'{discipline.get("overridden_count", 0)} overridden / '
              f'oldest {discipline.get("oldest_open_days", 0)}d')
    for b in guardrail['breaches']:
        print(f'   ⛔ {b["type"]:20s} ({b["severity"]:6s}) {b["detail"][:78]}')
    for s in guardrail['hard_stop_watch']:
        print(f'   🛑 {s["detail"][:78]}')

    # [10d] 解套数学 — 纯算术回本表（浮亏持仓回本所需涨幅 / 2x 横盘 decay 成本）
    breakeven = compute_breakeven_math(
        portfolio['portfolios']['hk_stocks']['holdings'],
        portfolio['portfolios']['us_stocks']['holdings'], lev_regime=lev_regime)
    print(f'   breakeven: {len(breakeven["rows"])} 只浮亏持仓入表')

    # [11] Catalyst calendar — next 14d earnings + FOMC + macro
    print('[12/14] Fetch catalysts')
    catalysts = {}
    try:
        cat_out, cat_ok = _run('scripts/data/fetch_catalysts.py', ['--json'], timeout=60)
        if not cat_ok:
            print(f'   ⚠ catalysts fetch failed: {cat_out[-150:]}')
            issues.append('catalysts fetch failed')
        else:
            catalysts = json.loads(cat_out)
            summary = catalysts.get('summary', {})
            print(f'   earnings: {summary.get("earnings_count", 0)}, '
                  f'FOMC: {summary.get("fomc_in_window", 0)}, '
                  f'macro: {summary.get("macro_count", 0)}')
            hi = summary.get('highest_impact_within_7d')
            if hi:
                print(f'   highest impact 7d: {hi}')
            if 'error' in catalysts:
                print(f'   ⚠ partial errors: {list(catalysts["error"].keys())}')
    except Exception as e:
        print(f'   ⚠ catalysts step failed: {e}')
        issues.append(f'catalysts step exception: {type(e).__name__}')

    # [11b] News evidence graph — normalize filings/news/calendar nodes, expire
    # repeated summaries and apply deterministic source/novelty/confirmation
    # gates. Only a compact decision envelope enters the LLM context.
    news_evidence_ctx = {}
    try:
        graph_out, graph_ok = _run(
            'scripts/data/news_evidence_graph.py', timeout=150
        )
        graph_path = WS / 'assets' / 'data' / 'news_evidence_graph.json'
        if not graph_ok:
            print(f'   ⚠ news evidence graph failed: {graph_out[-150:]}')
            issues.append('news evidence graph failed')
        elif graph_path.exists():
            graph = json.loads(graph_path.read_text())
            current_events = [
                event for event in graph.get('events') or []
                if event.get('status') in ('active', 'upcoming')
            ]
            current_events.sort(
                key=lambda event: (
                    bool(event.get('actionable_escalation')),
                    bool(event.get('high_impact')),
                    event.get('source_reliability') or 0,
                    event.get('publication_time', {}).get('iso') or '',
                ),
                reverse=True,
            )
            decision_fields = (
                'event_id', 'ticker', 'reported_ticker', 'event_type',
                'title', 'publication_time', 'event_time', 'source_type',
                'source_reliability', 'novelty_score', 'novelty_reason',
                'status', 'expires_at', 'impact_direction', 'confirmation',
                'high_impact', 'actionable_escalation',
                'actionable_blockers', 'decision_permission',
            )
            news_evidence_ctx = {
                'as_of': graph.get('as_of'),
                'summary': graph.get('summary'),
                'events': [
                    {key: event.get(key) for key in decision_fields}
                    for event in current_events[:40]
                ],
                'actionable_events': graph.get('actionable_events') or [],
                'tavily_resolution_queue': (
                    graph.get('tavily_resolution_queue') or []
                ),
                'policy': graph.get('policy'),
            }
            summary = graph.get('summary') or {}
            print(
                f'   🧾 news evidence: {summary.get("events", 0)} events, '
                f'{summary.get("actionable_escalations", 0)} actionable, '
                f'{summary.get("tavily_resolution_queue", 0)} unresolved'
            )
    except Exception as e:
        print(f'   ⚠ news evidence graph step failed: {e}')
        issues.append(
            f'news evidence graph exception: {type(e).__name__}'
        )

    # Benchmark history (SPY + HSI/HSTECH) for the Equity Curve overlay.
    # Refreshed once per day at brief time; consumed by build_dashboard.
    print('[13/14] Fetch benchmark history')
    try:
        bm_out, bm_ok = _run('scripts/data/fetch_benchmark_history.py', timeout=30)
        if not bm_ok:
            print(f'   ⚠ benchmark fetch failed: {bm_out[-150:]}')
            issues.append('benchmark history fetch failed')
        else:
            # Surface a one-line summary
            tail = bm_out.strip().splitlines()[-1] if bm_out.strip() else ''
            print(f'   {tail}')
    except Exception as e:
        print(f'   ⚠ benchmark step failed: {e}')
        issues.append(f'benchmark step exception: {type(e).__name__}')

    # [13] Macro + sentiment snapshots — written by GH Action (macro-scan / sentiment-scan).
    # Read-only here; brief LLM consumes the trimmed subset so "▎大盘速读" and
    # "▎社交舆情速读" sections aren't flying blind.
    print('[14/14] Load macro + sentiment + influencer snapshots')
    macro_trim, sentiment_trim = load_macro_and_sentiment(today, issues)
    influencer_trim = load_influencer_feed(issues)
    em_news_trim = load_em_news(issues)

    # Write the complete audit context plus a budgeted, generation-bound model
    # boundary. The full JSON remains available for postflight/audit; the skill
    # reads manifest+core and lazy-loads feature bundles.
    # 简报上下文里的 portfolio 拷贝去掉 gold_dca.nav_history(~140条/3.3KB 黄金每日净值流水):
    # 简报 LLM 不逐日分析黄金(黄金有独立 cron)，dashboard 🥇卡也是直接读 portfolio.json，
    # 都用不到这段 → 纯占 token。浅拷贝只替换 gold_dca 键，不改原始 portfolio(下游仍用全量)。
    portfolio_ctx = portfolio
    _g = portfolio.get('gold_dca')
    if isinstance(_g, dict) and _g.get('nav_history'):
        _g_trim = {k: v for k, v in _g.items() if k != 'nav_history'}
        _g_trim['nav_history_omitted'] = len(_g['nav_history'])  # 留计数标记=故意省略非丢失
        portfolio_ctx = {**portfolio, 'gold_dca': _g_trim}

    active_tickers = [
        str(holding.get('ticker'))
        for region in ('hk_stocks', 'us_stocks')
        for holding in portfolio['portfolios'].get(region, {}).get('holdings', [])
        if holding.get('shares', 0) > 0
    ]
    thesis_registry_ctx = thesis_registry.registry_summary(
        WS / 'memory' / 'theses', active_tickers
    )
    thesis_docs, _ = thesis_registry.load_registry(WS / 'memory' / 'theses')
    if isinstance(retro.get('decisions'), list):
        retro['decisions'] = thesis_registry.resolve_decision_links(
            retro['decisions'], thesis_docs
        )

    # Research lifecycle work queue: a reported quarter with no primary-source
    # artifact, a management promise past its due date, a position no gate cleared.
    # Read-only — the brief reports these, it does not resolve them.
    # hk_watch costs two Tencent calls a day (HK operating companies only) and is
    # the only advance warning we have that HK results are near — see issue #99.
    research_surface_ctx = research_surface.summarize(
        portfolio=portfolio,
        catalysts=catalysts,
        hk_watch=True,
        hk_results_fetch=_fetch_hk_results_notices,
    )

    context = {
        'generated_at':  datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'date':          today,
        'fx':            fx,
        'portfolio_path': str(portfolio_path),
        'snapshot_path': str(snapshot_path),
        'portfolio':     portfolio_ctx,
        'book_totals':   book,
        'concentration': {'hk': hk_conc, 'us': us_conc},
        'lookthrough_exposure': lookthrough,
        'risk_guardrail': guardrail,
        'risk_discipline': discipline,
        'breakeven_math': breakeven,
        'quant_signals': quant_signals,
        'quant_signal_review': quant_review,
        'cross_sectional_factor': cross_sectional_factor_ctx,
        'peer_residual': peer_residual_ctx,
        't0_setups': t0_setups,
        't0_setup_review': t0_review,
        'integrity': integrity,
        'us_fundamentals': us_fund,
        'retrospective': retro,
        'peer_scan':     peer_scan,
        'decision_metrics': decision_metrics,
        'reflections':   reflections,
        'risk_metrics':  risk,
        'catalysts':     catalysts,
        'news_evidence_graph': news_evidence_ctx,
        'thesis_registry': thesis_registry_ctx,
        'research_surface': research_surface_ctx,
        'macro':         macro_trim,
        'sentiment':     sentiment_trim,
        'influencer':    influencer_trim,
        'em_news':       em_news_trim,
        'issues':        issues,
    }
    ctx_path = TMP_DIR / f'brief-context-{today}.json'
    try:
        generation_id = brief_context.compute_generation_id(context)
        decision_packet = brief_decision_packet.compile_packet(
            context, generation_id=generation_id
        )
        context, bundle_manifest = brief_context.write_run_bundle(
            context,
            ctx_path,
            tool_artifacts={"decision_packet": decision_packet},
        )
    except Exception as exc:
        print(f'FATAL: brief context boundary failed: {exc}', file=sys.stderr)
        workflow_outcomes.record_stage(
            job_name, 'preflight', 'failed', slot=slot,
            reason='context_budget', detail=str(exc),
        )
        return 2

    print(f'\n═════ preflight done | {len(issues)} issues ═════')
    print(f'context: {ctx_path}')
    print(
        'model context: '
        f'{bundle_manifest["budget"]["always_loaded_bytes"]:,} / '
        f'{bundle_manifest["budget"]["max_always_loaded_bytes"]:,} bytes '
        f'({bundle_manifest["budget"]["actual_reduction_pct"]}% reduction; '
        f'≈{bundle_manifest["budget"]["estimated_tokens"]:,} est. tokens)'
    )
    for section, size in sorted(
            bundle_manifest['source_section_bytes'].items(),
            key=lambda item: item[1], reverse=True):
        print(f'  context bytes {section}: {size:,}')
    if issues:
        for i in issues:
            print(f'  ⚠️  {i}')
    workflow_outcomes.record_stage(
        job_name,
        'preflight',
        'success' if not issues else 'warning',
        slot=slot,
        issue_count=len(issues),
        context_path=str(ctx_path),
        context_generation_id=context['generation_id'],
        model_context_bytes=bundle_manifest['budget']['always_loaded_bytes'],
    )
    return 0 if not issues else 1


if __name__ == '__main__':
    sys.exit(main())
