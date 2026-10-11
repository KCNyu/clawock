"""Risk guardrail and break-even arithmetic: pure functions of book state.

These lived in `harness.brief_preflight`, and `publish.dashboard` reached up into
the harness to call them — a lower layer importing an orchestration module for
what is, in every case here, arithmetic over holdings (#814). That single import
was the whole of the `publish -> harness` dependency, one half of a package cycle.

Nothing in this module orchestrates anything: no I/O, no subprocess, no
workspace. Given holdings it returns concentration, capped disciplinary
directives, and the arithmetic of getting back to break-even. `brief_preflight`
re-exports the names it used to own, because the brief SKILL contract and
several tests refer to them there.
"""
from __future__ import annotations

from clawock.safe_io import to_number as _share_number

from clawock.portfolio.math import ledger_rows

import math

from clawock.instruments import is_leveraged_holding, one_x_swap_map

def _is_leveraged_etf(holding):
    """Compatibility alias for the product-owned conservative classifier."""
    return is_leveraged_holding(holding)


def compute_concentration(holdings):
    """HHI + Top2 + per-holding weights for one leg."""
    active = [h for h in ledger_rows(holdings) if (_share_number(h.get('shares', 0)) or 0) > 0]
    if not active:
        return {}
    total = sum(h.get('current_value', h['cost_basis'] * (_share_number(h['shares']) or 0)) for h in active)
    if not total:
        return {'error': 'leg has zero total value'}

    weights = []
    for h in active:
        v = h.get('current_value', h['cost_basis'] * (_share_number(h['shares']) or 0))
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
# dashboard cards into explicit risk responses. Caps allow a reasoned hold;
# stops/regime obligations follow the durable standing and override contracts.
GUARDRAIL_CAPS = {
    # kcn 2026-10-11: 「集中度未必是坏事，可以单调一只甚至都可以」「偏激进甚至可以杠杆」.
    # Measured the same week: the single-name, leveraged-leg, cluster and β caps
    # stood open for up to 86 days, were answered with 0 sells on the four names
    # still held, and froze adds on the names the book bought 24 times anyway.
    # So construction is state to look at, not a breach: one name, leveraged or
    # not, may be the whole leg (a `single_name_review` row from 35%), a leg may
    # be all leveraged ETFs, and one cluster may be the whole book. What stays a
    # rule is what a daily-reset product loses by waiting: the hard stop and the
    # regime dial, which also still halves or zeroes the HK leveraged-leg cap.
    'single_name_review_pct': 35,
    'single_name_mandatory_pct': 100,
    'leveraged_single_name_pct': 100,
    'correlated_cluster_pct': 100,
    'correlation_min_coverage_pct': 80,
    'lev_etf_leg_pct':   100,   # leveraged ETFs as % of a leg, before the regime multiplier
    # A leg held entirely in a 2x product on a β≈3 stock runs β 6; above that
    # the book is levered beyond anything a 2x ETF alone can build.
    'us_beta_max':       6.0,   # US β vs S&P 500
    'lev_etf_stop_pct': -18,    # hard-stop line for one leveraged ETF (vs cost)
}


# 2x→1x 解套换仓映射（kcn 2026-06-11 口径）：现货套牢可以躺（等待免费），2x 日内重置
# 套牢不能躺（震荡 decay 让等待持续收费）。所以杠杆仓的硬闸动作一律先给「换仓」而非
# 「清仓 trim」——换成同因子 1x 后反弹敞口一点不丢、decay 出血停止，不算割肉离场。
# 换回条件 = 🧭 lev_regime 转 green（标的收复 200 日线且波动正常），1x→2x 只在 green 档执行。
LEV_1X_SWAP = one_x_swap_map()


def _swap_suggestions(holdings):
    """持有中的杠杆 ETF → 「2x→1x」换仓建议串，如 "07226→03033、ROBN→HOOD"。"""
    return '、'.join(f"{h['ticker']}→{LEV_1X_SWAP[h['ticker']]}" for h in holdings
                     if (_share_number(h.get('shares', 0)) or 0) > 0 and _is_leveraged_etf(h)
                     and h.get('ticker') in LEV_1X_SWAP)


def _holding_pnl_pct(h):
    cost = h.get('cost_basis', 0) * (_share_number(h.get('shares', 0)) or 0)
    cur  = h.get('current_value', cost)
    return None if not cost else round((cur - cost) / cost * 100, 1)


def _directive(*, type, leg, ticker, severity, detail, action, required_reduction, **extra):
    """One shape for executable risk directives; policy identity is mandatory."""
    return dict(type=type, leg=leg, ticker=ticker, severity=severity, detail=detail,
                action=action, required_reduction=required_reduction, **extra)


def _single_name_policy(leg, ws, hold, total, ccy):
    caps = GUARDRAIL_CAPS
    breaches, reviews = [], []
    # Single-name policy: concentration is allowed. Above the review line a
    # name is visible review state, leveraged or not; the mandatory caps
    # (`GUARDRAIL_CAPS`) no longer bind below the whole leg.
    for w in ws:
        holding = next((h for h in hold if h.get('ticker') == w['ticker']), {})
        leveraged = _is_leveraged_etf(holding)
        mandatory_cap = (
            caps['leveraged_single_name_pct'] if leveraged
            else caps['single_name_mandatory_pct']
        )
        if w['weight_pct'] > mandatory_cap and total:
            # Selling changes both the position and the leg denominator.
            # Solve (value - sell) / (total - sell) <= target rather than
            # subtracting the current excess from an unchanged denominator.
            target = mandatory_cap / 100
            trim_val = round(
                (w['value'] - target * total) / (1 - target), 2
            )
            breaches.append(_directive(
                type='single_name', leg=leg, ticker=w['ticker'],
                severity='high',
                detail=(f"{w['ticker']} = {w['weight_pct']}% of {leg} "
                           f"(mandatory cap {mandatory_cap}%; "
                           f"{'2x/3x' if leveraged else 'non-leveraged core'})"),
                action=(f"可说明理由后持有；登记策略建议纪律性 trim {w['ticker']} → ≤{mandatory_cap}% "
                           f"(减约 {trim_val} {ccy}，借反弹分批、勿在新低日一次砍)"),
                required_reduction={
                    'kind': 'market_value',
                    'minimum_value': trim_val,
                    'currency': ccy,
                    'target_pct': mandatory_cap,
                    'target_tickers': [w['ticker']],
                },
            ))
        elif w['weight_pct'] > caps['single_name_review_pct']:
            reviews.append({
                'type': 'single_name_review', 'leg': leg,
                'ticker': w['ticker'], 'severity': 'advisory',
                'detail': (f"{w['ticker']} = {w['weight_pct']}% of {leg}"
                           f"{' (2x/3x)' if leveraged else ''}; above the "
                           f"{caps['single_name_review_pct']}% review line, "
                           "no mandatory trim"),
            })

    return breaches, reviews


def _leveraged_leg_policy(leg, hold, total, ccy, hk_mult, lev_regime):
    caps = GUARDRAIL_CAPS
    breaches = []
    # leveraged-ETF leg exposure — use the name heuristic, not the unreliable
    # is_leveraged_etf flag (which concentration weights mirror and is often unset)
    lev_val = sum(h.get('current_value', h.get('cost_basis', 0) * (_share_number(h.get('shares', 0)) or 0))
                  for h in hold if (_share_number(h.get('shares', 0)) or 0) > 0 and _is_leveraged_etf(h))
    # HK leg cap tightened by HSTECH dial; US leg stays at base (its risk is handled
    # per-name below — verified: a single US index mult over-cuts calm names like MSFT).
    leg_mult = hk_mult if leg == 'HK' else 1.0
    eff_lev_cap = round(caps['lev_etf_leg_pct'] * leg_mult)
    lev_pct = round(lev_val / total * 100, 1) if total else 0
    if lev_pct > eff_lev_cap and total:
        trim_val = round(lev_val - eff_lev_cap / 100 * total, 2)
        tightened = eff_lev_cap < caps['lev_etf_leg_pct']
        hk_tier = (lev_regime.get('hk') or lev_regime).get('tier') if isinstance(lev_regime, dict) else None
        regime_note = (f"（🧭HK制度 {hk_tier}：基准 {caps['lev_etf_leg_pct']}% ×"
                       f"{leg_mult:g} → {eff_lev_cap}%，{(lev_regime.get('hk') or lev_regime).get('label','')}）"
                       if tightened and leg == 'HK' and isinstance(lev_regime, dict) else '')
        breaches.append(_directive(
            type='leveraged_exposure', leg=leg, ticker=None, severity='high',
            detail=f"{leg} 杠杆 ETF = {lev_pct}% (cap {eff_lev_cap}%) — 2x 日内重置，下杀崩/震荡衰减{regime_note}",
            action=(f"可说明理由后持有；登记策略建议降杠杆=换仓非清仓：把约 {trim_val} {ccy} 的 2x 换成 1x 同因子"
                       f"({_swap_suggestions(hold) or '同因子 1x/标的现货'})，"
                       f"敞口不变、停 decay；🧭转 green 后可换回 2x"),
            required_reduction={
                'kind': 'leveraged_market_value',
                'minimum_value': trim_val,
                'currency': ccy,
                'target_pct': eff_lev_cap,
                'target_tickers': [
                    h.get('ticker') for h in hold
                    if (_share_number(h.get('shares', 0)) or 0) > 0 and _is_leveraged_etf(h)
                ],
            },
        ))

    return breaches, eff_lev_cap


def _reduce_exempt(holding, strategies):
    """True when the holding runs a strategy whose policy forbids reduce advice."""
    return bool(holding.get('strategy')) and holding.get('strategy') in strategies


def _hard_stop_watch(leg, hold, ccy, reduce_exempt_strategies=frozenset()):
    caps = GUARDRAIL_CAPS
    hard_stops = []
    # hard-stop watch on individual leveraged ETFs
    for h in hold:
        if (_share_number(h.get('shares', 0)) or 0) <= 0 or not _is_leveraged_etf(h):
            continue
        if _reduce_exempt(h, reduce_exempt_strategies):
            continue
        pnl = _holding_pnl_pct(h)
        if pnl is not None and pnl <= caps['lev_etf_stop_pct']:
            hard_stops.append(_directive(
                # Every other guardrail row names its own kind; this one
                # did not, and a row without a `type` is a row a debate
                # cannot cite (#1141 resolves `risk:<type>[:<ticker>]`
                # against exactly this field).
                type='leveraged_hard_stop',
                ticker=h['ticker'], leg=leg, pnl_pct=pnl,
                severity='critical',
                detail=f"{h['ticker']} 浮亏 {pnl}% ≤ 硬止损线 {caps['lev_etf_stop_pct']}%",
                action=(f"{h['ticker']} 触发杠杆 ETF 硬止损 → 换仓 "
                           f"{('1x 同因子 ' + LEV_1X_SWAP[h['ticker']]) if h.get('ticker') in LEV_1X_SWAP else '同因子 1x/标的现货'}"
                           f"（敞口保留、停 decay，规则非择时）；🧭转 green 再换回 2x"),
                required_reduction={
                    'kind': 'full_leveraged_position',
                    'minimum_shares': h.get('shares'),
                    'minimum_value': (
                        h.get('current_value')
                        or h.get('cost_basis', 0) * (_share_number(h.get('shares', 0)) or 0)),
                    'currency': ccy,
                    'target_tickers': [h['ticker']],
                    'swap_to': LEV_1X_SWAP.get(h['ticker']),
                },
            ))

    return hard_stops


def _regime_delever_policy(us_holdings, lev_regime, reduce_exempt_strategies=frozenset()):
    breaches = []
    # US per-name leverage dial (lev_regime['us']) — only the 'cut' state (underlying
    # trend-off AND vol hot) becomes a forced directive; 'watch' (calm) stays advisory.
    us_reg = (lev_regime or {}).get('us') if isinstance(lev_regime, dict) else None
    if isinstance(us_reg, dict):
        held_us = {h.get('ticker') for h in us_holdings if (_share_number(h.get('shares', 0)) or 0) > 0}
        for nm in us_reg.get('names', []):
            if nm.get('state') == 'cut' and nm.get('etf') in held_us:
                holding = next(h for h in us_holdings if h.get('ticker') == nm['etf']
                               and (_share_number(h.get('shares', 0)) or 0) > 0)
                if _reduce_exempt(holding, reduce_exempt_strategies):
                    continue
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
                breaches.append(_directive(
                    type='regime_delever', leg='US', ticker=nm['etf'], severity='high',
                    detail=detail,
                    action=(
                        f"{nm['etf']} 2x→{nm['underlying']} 现货换仓"
                        f"(driven_by=risk_rule,规则非择时)：{action_reason}"
                    ),
                    required_reduction={
                        'kind': 'full_leveraged_position',
                        'target_tickers': [nm['etf']],
                        'swap_to': nm['underlying'],
                        'minimum_shares': holding.get('shares'),
                        'minimum_value': (holding.get('current_value')
                                          or holding.get('cost_basis', 0) * (_share_number(holding.get('shares', 0)) or 0)),
                        'currency': 'USD',
                    },
                ))

    return breaches


def _factor_concentration_policy(hk_holdings, us_holdings, risk):
    caps = GUARDRAIL_CAPS
    breaches = []
    # Measured correlation clusters replace the old Top2 proxy. The x-ray is
    # cross-market/USD weighted, so evaluate once at book level. A one-name
    # cluster is simply a concentrated name and must never be called a factor.
    correlation = (risk or {}).get('correlation') or {}
    coverage = correlation.get('covered_weight_pct')
    fx_hkd_to_usd = float(
        ((risk or {}).get('meta') or {}).get('fx_hkd_to_usd_used') or 0
    )
    book_value_usd = sum(
        float(w.get('current_value') or 0)
        * (1.0 if leg == 'US' else fx_hkd_to_usd)
        for leg, holdings in (('HK', hk_holdings), ('US', us_holdings))
        for w in holdings if (_share_number(w.get('shares', 0)) or 0) > 0
    )
    if (not correlation.get('reason') and isinstance(coverage, (int, float))
            and coverage >= caps['correlation_min_coverage_pct']
            and book_value_usd > 0
            and (not hk_holdings or fx_hkd_to_usd > 0)):
        for cluster in correlation.get('clusters') or []:
            tickers = [str(t) for t in cluster.get('tickers') or []]
            if len(tickers) < 2:
                continue
            cluster_value_usd = sum(
                float(w.get('current_value') or 0)
                * (1.0 if leg == 'US' else fx_hkd_to_usd)
                for leg, holdings in (('HK', hk_holdings), ('US', us_holdings))
                for w in holdings if str(w.get('ticker')) in tickers
            )
            weight_pct = cluster_value_usd / book_value_usd * 100
            if weight_pct <= caps['correlated_cluster_pct']:
                continue
            target = caps['correlated_cluster_pct'] / 100
            factor_trim = max(0, round(
                (cluster_value_usd - target * book_value_usd) / (1 - target), 2
            ))
            breaches.append(_directive(
                type='factor_concentration', leg='BOOK', ticker=None,
                severity='high',
                detail=(f"Measured cluster {tickers} = {weight_pct:.2f}% of book "
                           f"(cap {caps['correlated_cluster_pct']}%, "
                           f"|rho|≥{correlation.get('cluster_rho')})"),
                action=(f"可说明理由后持有；登记策略建议把相关集群 {', '.join(tickers)} 降到 "
                           f"≤{caps['correlated_cluster_pct']}%，优先降其中杠杆仓"),
                required_reduction={
                    'kind': 'factor_market_value',
                    'minimum_value': factor_trim,
                    'currency': 'USD',
                    'target_pct': caps['correlated_cluster_pct'],
                    'target_tickers': tickers,
                },
            ))

    return breaches


def _beta_policy(us_holdings, risk):
    caps = GUARDRAIL_CAPS
    breaches = []
    # portfolio-level β from risk.json
    us_risk = risk.get('us') or {}
    us_beta = us_risk.get('beta_spx')
    # A revived block (#1036) carries β of unknown age: risk.py only keeps the
    # last good stats when this run's fetch failed, so `stale` means "not
    # measured today". A HIGH-severity trim directive must not be sourced from
    # data whose age the flag itself admits is unknown.
    beta_eligible = (
        not us_risk.get('stale')
        and us_risk.get('threshold_eligible', True)
        and us_risk.get('beta_threshold_eligible', True)
    )
    if (beta_eligible and isinstance(us_beta, (int, float))
            and us_beta > caps['us_beta_max']):
        breaches.append(_directive(
            type='beta', leg='US', ticker=None, severity='high',
            detail=f"US β vs S&P = {us_beta} (cap {caps['us_beta_max']}) — 大盘 −1% 本子约 −{us_beta:.1f}%",
            action="可说明理由后持有；登记策略建议降 US β：优先削杠杆 ETF(β 主要来源)，比较单票 thesis",
            required_reduction={
                'kind': 'beta',
                'target_beta': caps['us_beta_max'],
                'target_tickers': [
                    h.get('ticker') for h in us_holdings
                    if (_share_number(h.get('shares', 0)) or 0) > 0 and _is_leveraged_etf(h)
                ],
            },
        ))

    return breaches


def compute_risk_guardrail(hk_holdings, us_holdings, hk_conc, us_conc, risk,
                           lev_regime=None, *, reduce_exempt_strategies=frozenset()):
    """Pure function of current state → concrete, capped trim/cut directives.
    A hard stop and a regime de-lever oblige a sell; the four caps
    (`decision.risk.RESPOND_ONLY_TYPES`) oblige an answer.

    lev_regime (lev_regime.json, optional): the HSTECH trend+vol leverage dial.
    When present and hostile (amber/red), it TIGHTENS the leveraged-ETF leg cap by
    its multiplier (green 1.0 / amber 0.5 / red 0.0). Backtest-verified: the lever
    that mattered in the 2021-22 crash was leverage (2x→1x→cash), not timing.

    reduce_exempt_strategies: holding strategies whose policy sets
    `forbid_reduce_advice` (`decision.intraday_policy.reduce_exempt_strategies`).
    A holding on one of them gets no hard-stop and no regime de-lever row: its
    owner declared it is bought on the way down, and its own escalations are
    the intraday strategy rules. Its weight still shows as a review row."""
    caps = GUARDRAIL_CAPS
    breaches, hard_stops, reviews = [], [], []
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

        single, advisory = _single_name_policy(leg, ws, hold, total, ccy)
        breaches.extend(single)
        reviews.extend(advisory)
        leveraged, eff_caps[leg] = _leveraged_leg_policy(
            leg, hold, total, ccy, hk_mult, lev_regime)
        breaches.extend(leveraged)
        hard_stops.extend(_hard_stop_watch(leg, hold, ccy, reduce_exempt_strategies))

    breaches.extend(_regime_delever_policy(
        us_holdings, lev_regime, reduce_exempt_strategies))
    breaches.extend(_factor_concentration_policy(hk_holdings, us_holdings, risk))
    breaches.extend(_beta_policy(us_holdings, risk))

    n = len(breaches) + len(hard_stops)
    if n:
        directive = (f"⛔ {len(breaches)} 仓位硬闸 + {len(hard_stops)} 杠杆止损触发。"
                     "硬止损与 regime_delever 在无 may_stand 或有效 durable override 时，"
                     "必须在 Judge 段出对应动作(driven_by=risk_rule,"
                     "纪律性再平衡,不算听消息、不受 risk_on HOLD 默认约束)；"
                     "单名/杠杆敞口/相关集群/β 四类上限必须逐条回应：减仓，或写明理由的持有，"
                     "超限期间不得加仓；regime 对其余主动 call 只是策略参考。"
                     "登记策略倾向2x→1x 同因子换仓，也可说明理由后卖出持有现金；买腿遵守处方(见各 action)。")
    else:
        directive = "✅ 无仓位/杠杆硬闸触发，按常规决策。"

    reentry_rule = ("1x→2x 换回闸：HK=HSTECH 收复 200日线且 20日波动<50%(🧭green ×1.0)；"
                    "US=各标的自身收复 200日线且波动<70%。green 之前不加任何 2x。")

    return {'caps': caps, 'breaches': breaches, 'hard_stop_watch': hard_stops,
            'concentration_reviews': reviews,
            'breach_count': n, 'directive': directive, 'reentry_rule': reentry_rule,
            'lev_regime': lev_regime, 'eff_lev_caps': eff_caps}


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
            if (_share_number(h.get('shares', 0)) or 0) <= 0:
                continue
            pnl = _holding_pnl_pct(h)
            if pnl is None or pnl >= 0:
                continue
            cost = h.get('cost_basis', 0) * (_share_number(h['shares']) or 0)
            cur  = h.get('current_value', cost)
            if not cur:
                continue
            need = (cost / cur - 1) * 100
            row = {'ticker': h['ticker'], 'leg': leg, 'pnl_pct': pnl,
                   'breakeven_need_pct': round(need, 1),
                   'leveraged': bool(_is_leveraged_etf(h))}
            if row['leveraged']:
                row['swap_1x'] = LEV_1X_SWAP.get(h['ticker'])
                row['underlying_need_if_1x_pct'] = round(need, 1)
                sigma = us_vols.get(h['ticker']) if leg == 'US' else hk_dial.get('vol_annualized')
                if isinstance(sigma, (int, float)) and sigma > 0:
                    drag_y = sigma ** 2                     # k=2 → (k²−k)/2·σ² = σ²
                    x_2x = math.sqrt((1 + need / 100) * math.exp(drag_y * 0.5)) - 1
                    row.update({
                        'underlying_vol_pct':        round(sigma * 100, 1),
                        'chop_drag_pct_per_month':   round(drag_y / 12 * 100, 2),
                        'underlying_need_2x_6m_pct': round(x_2x * 100, 1),
                        'underlying_need_if_1x_pct': round(need, 1),
                    })
            rows.append(row)
    rows.sort(key=lambda r: r['pnl_pct'])
    return {
        'rows': rows,
        'note': ('回本涨幅=成本/现价−1。2x 行加印：标的σ、横盘 decay≈σ²/12 每月、半年窗含 drag '
                 '的等效标的涨幅。解读纪律：直线涨→2x 回本更快；横盘→2x 每月白付 decay；'
                 '再跌→2x 双倍挨打。换 1x 买的是后两种情景的保护，不是回本速度。'),
    }
