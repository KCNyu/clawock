#!/usr/bin/env python3
"""
KCNyu Sunday 22:00 HKT weekly portfolio review.

Bundles past 7 days of plans / decision episodes / snapshots / current risk
into a single prompt, calls MiniMax M3 (optional opencode-go fallback), and writes
memory/weekly/{ISO-week}.md.

Env: MINIMAX_API_KEY required; OPENCODE_API_KEY optional fallback
"""
import glob
import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from clawock.automation.llm import chat
from clawock.decision import ledger as decision_v2


def _load_json(path, kind, errors):
    try:
        with open(path, encoding='utf-8') as handle:
            value = json.load(handle)
    except Exception as exc:
        errors.append(f'{kind} {path}: {type(exc).__name__}')
        return None
    if not isinstance(value, dict):
        errors.append(f'{kind} {path}: top-level JSON must be an object')
        return None
    return value


def _finite_nonnegative(value):
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0)


def _snapshot_nav(snapshot, fx_rate):
    if not (isinstance(fx_rate, (int, float))
            and not isinstance(fx_rate, bool)
            and math.isfinite(fx_rate)
            and fx_rate > 0):
        raise ValueError('plan FX rate missing or invalid')
    portfolios = snapshot.get('portfolios')
    if not isinstance(portfolios, dict):
        raise ValueError('portfolios missing')
    us = portfolios.get('us_stocks')
    hk = portfolios.get('hk_stocks')
    if not isinstance(us, dict) or not isinstance(hk, dict):
        raise ValueError('US/HK portfolio books missing')
    values = {
        'us_value_usd': us.get('total_current_value'),
        'us_cash_usd': us.get('cash_usd'),
        'hk_value_hkd': hk.get('total_current_value'),
        'hk_cash_hkd': hk.get('cash_hkd'),
    }
    invalid = [name for name, value in values.items()
               if not _finite_nonnegative(value)]
    if invalid:
        raise ValueError(f'invalid NAV fields: {", ".join(invalid)}')
    return {
        **values,
        'fx_rate_usdhkd': fx_rate,
        'total_nav_usd': (
            values['us_value_usd']
            + values['us_cash_usd']
            + (values['hk_value_hkd'] + values['hk_cash_hkd']) / fx_rate
        ),
    }


def _nearest_plan_fx(snapshot_date, plan_fx):
    if snapshot_date in plan_fx:
        return plan_fx[snapshot_date]
    if not plan_fx:
        return None
    target = date.fromisoformat(snapshot_date)
    _, fx_rate = min(
        ((date.fromisoformat(plan_date), fx_rate)
         for plan_date, fx_rate in plan_fx.items()),
        key=lambda item: (abs((item[0] - target).days), item[0]),
    )
    return fx_rate


def aggregate_week(today=None):
    today = today or date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    start = today - timedelta(days=7)
    boundary = start - timedelta(days=1)
    input_errors = []

    plans = []
    plan_fx = {}
    for f in sorted(glob.glob('memory/*-plan.json')):
        d_str = os.path.basename(f).split('-plan.json')[0]
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            input_errors.append(f'plan {f}: invalid date in filename')
            continue
        if boundary <= d <= today:
            plan = _load_json(f, 'plan', input_errors)
            if plan is not None:
                fx_rate = plan.get('fx_rate_usdhkd')
                if (isinstance(fx_rate, (int, float))
                        and not isinstance(fx_rate, bool)
                        and math.isfinite(fx_rate)
                        and fx_rate > 0):
                    plan_fx[d_str] = fx_rate
                if d >= start:
                    plans.append({'date': d_str, 'data': plan})

    decisions = decision_v2.load_decisions()
    decision_episodes = [r for r in decision_v2.episode_representatives(decisions, 't1')
                         if r.get('plan_date', '') >= start.isoformat()]

    snapshots = []
    snapshot_records = []
    for f in sorted(glob.glob('memory/snapshots/*.json')):
        d_str = os.path.basename(f).split('.json')[0]
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            input_errors.append(f'snapshot {f}: invalid date in filename')
            continue
        if boundary <= d <= today:
            snapshot = _load_json(f, 'snapshot', input_errors)
            if snapshot is not None:
                snapshots.append(snapshot)
                snapshot_records.append((d_str, snapshot))

    risk = None
    if os.path.exists('assets/data/risk.json'):
        risk = _load_json('assets/data/risk.json', 'risk', input_errors)
    else:
        input_errors.append('risk assets/data/risk.json: missing')

    plan_decisions = 0
    valid_plan_days = 0
    for plan in plans:
        data = plan['data']
        decisions_for_day = data.get('decisions')
        if not isinstance(decisions_for_day, list):
            input_errors.append(
                f"plan memory/{plan['date']}-plan.json: decisions must be a list")
            continue
        valid_plan_days += 1
        plan_decisions += len(decisions_for_day)

    nav_points = []
    for d_str, snapshot in snapshot_records:
        try:
            nav = _snapshot_nav(snapshot, _nearest_plan_fx(d_str, plan_fx))
        except ValueError as exc:
            input_errors.append(f'snapshot memory/snapshots/{d_str}.json: {exc}')
            continue
        nav_points.append({'date': d_str, **nav})

    bundle_evidence = {
        'plan_days': valid_plan_days,
        'plan_decisions': plan_decisions,
        'decision_episodes': len(decision_episodes),
        'nav_points': nav_points[-7:],
    }
    return {
        'week': week_id,
        'window': f'{start.isoformat()} -> {today.isoformat()}',
        # Keep compact, deterministic evidence before bulky raw inputs: main()
        # truncates the serialized bundle at 40k characters for the LLM prompt.
        'bundle_evidence': bundle_evidence,
        'plans': plans,
        'decision_episodes': decision_episodes,
        'decision_metrics': decision_v2.compute_metrics(decisions),
        'snapshots': snapshots[-7:],
        'current_risk': risk,
        'input_warnings': input_errors,
    }


def validate_bundle(bundle):
    evidence = bundle.get('bundle_evidence')
    missing = []
    if not isinstance(evidence, dict) or evidence.get('plan_days', 0) < 1:
        missing.append('weekly plans with decision counts')
    if not isinstance(bundle.get('decision_episodes'), list):
        missing.append('decision episode count')
    if not isinstance(bundle.get('decision_metrics'), dict):
        missing.append('decision metrics')
    nav_points = evidence.get('nav_points', []) if isinstance(evidence, dict) else []
    dated_nav = (
        [point for point in nav_points
         if isinstance(point, dict) and isinstance(point.get('date'), str)]
        if isinstance(nav_points, list) else []
    )
    if len(dated_nav) < 2 or dated_nav[0]['date'] == dated_nav[-1]['date']:
        missing.append('start/end NAV from two dated snapshots')
    if not isinstance(bundle.get('current_risk'), dict) or not bundle['current_risk']:
        missing.append('current risk snapshot')
    if missing:
        warnings = bundle.get('input_warnings')
        detail = f"; input errors: {'; '.join(warnings)}" if warnings else ''
        raise RuntimeError(
            f"weekly bundle incomplete: missing {', '.join(missing)}{detail}")
    return evidence


def main():
    bundle = aggregate_week()
    validate_bundle(bundle)
    week_id = bundle['week']

    system = "You are Rick, kcn's HK+US stock analyst. Write a weekly portfolio review."

    user = (
        f"根据这一周（{week_id}）的 brief / plan / decision v2 / risk 数据, "
        f"写一篇 markdown 周复盘。长度 1500-2500 字。"
        "\n\n"
        "重点回答 4 个问题:\n"
        "1. **本周净值**: 总市值 USD-base 周初 vs 周末, "
        "涨跌 + 主要贡献者 + 主要拖累\n"
        "2. **决策兑现**: 按 strategy episode 汇总触发、执行和 win/loss；不要把每日重复 call 当独立样本\n"
        "3. **风险演变**: 当前 risk.json 数值, β/Vol/Max DD/Sharpe 怎么走?\n"
        "4. **下周关注 3 条**: actionable (ticker + 触发条件 + 仓位影响)\n\n"
        f"数据 bundle (JSON):\n```json\n{json.dumps(bundle, ensure_ascii=False)[:40000]}\n```\n\n"
        "直接出 markdown, 不要客套."
    )

    # Weekly review benefits most from thinking + depth (1 turn, complex synthesis)
    out = chat(system=system, user=user, max_tokens=32000, temperature=0.6)

    os.makedirs('memory/weekly', exist_ok=True)
    path = Path(f'memory/weekly/{week_id}.md')
    fm = f"---\nlayout: default\ntitle: 周复盘 · {week_id}\n---\n\n"
    path.write_text(fm + out.strip())
    print(f'  wrote {path}  ({len(out)} chars)')


if __name__ == '__main__':
    main()
