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
from clawock.automation.output_validate import validate_sections
from clawock.decision import ledger as decision_v2

# The four questions build_user_prompt asks for, checked on the way out (#1263).
WEEKLY_REQUIRED_SECTIONS = ('本周净值', '决策兑现', '风险演变', '下周关注')

# Prompt budget for the single-turn weekly review, measured in serialized-JSON
# characters. A sanity bound, not a writing target: the old prompt embedded
# `json.dumps(bundle)[:40000]`, sized when the bundle was small. By 2026-08 the
# bundle serialized to 702K characters, so the slice kept 5.7% of it, landed
# mid-string (a malformed JSON tail), and silently hid decision_metrics /
# snapshots / current_risk / input_warnings behind a cut the model could not
# see — while the prompt's question 3 asks for exactly the current risk
# numbers (#959). Same defect class brief_fallback.prepare_context fixed for
# the daily brief: never cut a serialized string; drop whole values instead
# and declare what was dropped.
PROMPT_BUDGET_CHARS = 200_000

# Per-attempt seconds for the one generation this job makes.
#
# The default (llm.TIMEOUT, 180s) dropped two weeks of review: 2026-W33
# (run 31952091127) and 2026-W35 (run 33326401496) both died as three
# consecutive `timeout after 180s` on the primary, and both fallbacks were dead
# at the time (Xiaomi 401 invalid key / opencode 401 CreditsError), so the whole
# chain failed and no file was written. Nothing re-runs a scheduled workflow, so
# an ISO week is simply missing from memory/weekly/ forever.
#
# The generation genuinely takes that long. Measured across the eight scheduled
# runs 2026-07-12..08-30 (`gh run view <id> --log`): 100.6s / 117.5s / 122.8s /
# 133.2s / 155.6s / 179.5s succeeded, twice it went past 180s. Output is
# 8.8K-17.6K tokens at 87-150 tok/s, so a full-length answer at the slow end of
# the observed throughput is 32000 / 87 = 368s.
#
# 180 was not too small because the budget was small — the chain deadline gives
# the primary 0.6 x 700 = 420s. It was too small because a per-attempt timeout
# below the primary's own share slices that share into pieces, and a generation
# that needs more than one piece can never finish however many pieces are left:
# three doomed 180s attempts spend the entire budget. Keep this >= the primary
# share (tests/test_llm_workflow_deadlines.py enforces it for every LLM job).
WEEKLY_LLM_TIMEOUT_SECONDS = 420

# Machine-owned fields on decision / episode records that no review question
# consumes; the harness already distills them into decision_episodes /
# decision_metrics. signal_provenance alone was ~76% of the decisions bytes in
# committed plans and also rides on every episode representative.
DECISION_PROMPT_DROP_FIELDS = ('signal_provenance',)

# Publication bookkeeping on `decision_metrics`, not review material:
# `provenance` names the ledger slice, window and code commit a published
# scorecard number came from (#1113). A public reader needs it to trace a
# number back to its rows; the weekly review is handed the numbers themselves,
# so in the prompt it is a kilobyte of digest the model cannot use.
METRICS_PROMPT_DROP_FIELDS = ('provenance',)

# Per-holding fields the review questions can actually use (book composition
# start-vs-end for contributor/drag attribution). Intraday OHLCV/volume/
# trade-tape detail and gold_dca stay out of the prompt; the NAV series they
# would support lives in bundle_evidence.nav_points.
HOLDING_PROMPT_FIELDS = ('ticker', 'name', 'current_value',
                         'pnl_percent', 'today_change_pct')

# Top-level sections that may be omitted WHOLE when the projected payload still
# exceeds the budget, IN THE ORDER THEY ARE SACRIFICED. Everything else —
# window, bundle_evidence, decision_episodes, current_risk, input_warnings — is
# small and load-bearing for a specific question, so it is never dropped.
#
# ORDER IS BY PURPOSE, NOT BY SIZE (#991). This used to drop the largest section
# first. On 2026-W30 data that drops plans (83,809 chars) and would take
# decision_metrics (32,380) next, ahead of snapshots (19,368) — question 2's
# distilled per-strategy win/loss sacrificed to keep the raw daily book
# composition, purely because that section happened to be bigger. `plans` is the
# daily raw view of decisions that decision_episodes and decision_metrics already
# distill, so it goes first; `snapshots` is book composition, which only question
# 1's attribution touches; `decision_metrics` is question 2's answer and goes
# last, only when dropping the other two was not enough.
OMITTABLE_SECTIONS = ('plans', 'snapshots', 'decision_metrics')


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


def week_nav_change(nav_points):
    """Start → end NAV for the week, computed once instead of in the prompt.

    Question 1 of the weekly prompt is "总市值 USD-base 周初 vs 周末, 涨跌".
    `nav_points` already carries a validated `total_nav_usd` per day, so the
    subtraction was the one piece of arithmetic still left to the model — and a
    model that mis-subtracts publishes a wrong headline number that nothing
    downstream re-checks.

    Named `nav_change`, not P&L, deliberately: this is end-of-week NAV minus
    start-of-week NAV, so any deposit, withdrawal or inter-leg transfer inside
    the window sits in it. The prompt says so; attribution stays the model's job,
    where knowing whether a move came from a trade or from the market is the
    judgment being asked for.

    Returns None when there are not two dated points — `validate_bundle`
    already refuses that bundle, so this never quietly reports a zero week.
    """
    if not isinstance(nav_points, list) or len(nav_points) < 2:
        return None
    first, last = nav_points[0], nav_points[-1]
    if not (isinstance(first, dict) and isinstance(last, dict)):
        return None
    start = first.get('total_nav_usd')
    end = last.get('total_nav_usd')
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) for v in (start, end)):
        return None
    change = end - start
    legs = {}
    for name, value_key, cash_key in (
            ('us_usd', 'us_value_usd', 'us_cash_usd'),
            ('hk_hkd', 'hk_value_hkd', 'hk_cash_hkd')):
        leg_start = _leg_total(first, value_key, cash_key)
        leg_end = _leg_total(last, value_key, cash_key)
        if leg_start is None or leg_end is None:
            continue
        legs[name] = {
            'start': round(leg_start, 2), 'end': round(leg_end, 2),
            'change': round(leg_end - leg_start, 2),
            'change_pct': (round((leg_end - leg_start) / leg_start * 100, 2)
                           if leg_start else None),
        }
    return {
        'start_date': first.get('date'), 'end_date': last.get('date'),
        'start_total_nav_usd': round(start, 2),
        'end_total_nav_usd': round(end, 2),
        'change_usd': round(change, 2),
        'change_pct': round(change / start * 100, 2) if start else None,
        'legs': legs,
        'basis': 'NAV end-minus-start; includes any capital flows in the window',
    }


def _leg_total(point, value_key, cash_key):
    value, cash = point.get(value_key), point.get(cash_key)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) for v in (value, cash)):
        return None
    return value + cash


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
    # Both edges, like plans and snapshots above: the ledger is not windowed,
    # so a lower bound alone lets every later episode into a past week's bundle
    # (#1276 — reviewing 2026-W30 carried 54 episodes from after it, 167K of
    # the 200K prompt budget, which pushed decision_metrics out of the payload).
    week_start, week_end = start.isoformat(), today.isoformat()
    decision_episodes = [r for r in decision_v2.episode_representatives(decisions, 't1')
                         if week_start <= r.get('plan_date', '') <= week_end]

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
        'nav_change': week_nav_change(nav_points[-7:]),
    }
    return {
        'week': week_id,
        'window': f'{start.isoformat()} -> {today.isoformat()}',
        # Compact, deterministic evidence first, bulky raw inputs after: the
        # reader meets verifiable numbers before prose-heavy raw views. Nothing
        # is truncated here — budget enforcement lives in build_prompt_payload.
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


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _slim_decision(decision):
    if not isinstance(decision, dict):
        return decision
    return {k: v for k, v in decision.items()
            if k not in DECISION_PROMPT_DROP_FIELDS}


def _slim_snapshot(snapshot):
    """Keep per-leg totals plus per-holding attribution fields for a snapshot day."""
    slim = {'last_updated': snapshot.get('last_updated')}
    portfolios = snapshot.get('portfolios')
    legs = {}
    for leg, pf in (portfolios or {}).items():
        if not isinstance(pf, dict):
            legs[leg] = pf
            continue
        cash = pf.get('cash_usd') if leg == 'us_stocks' else pf.get('cash_hkd')
        holdings = [
            {field: holding.get(field) for field in HOLDING_PROMPT_FIELDS}
            for holding in pf.get('holdings') or []
            if isinstance(holding, dict)
        ]
        legs[leg] = {
            'total_current_value': pf.get('total_current_value'),
            'total_pnl': pf.get('total_pnl'),
            'today_total_change': pf.get('today_total_change'),
            'cash': cash,
            'holdings': holdings,
        }
    slim['portfolios'] = legs
    return slim


def build_prompt_payload(bundle, budget=PROMPT_BUDGET_CHARS):
    """Project the aggregated bundle into the payload the LLM prompt embeds.

    Two layers, both structural:

    1. Projection — strip machine-owned bulk no question consumes (per-decision
       provenance; per-holding market microdetail). On committed 2026-08 data
       this takes the bundle from 702K to 145–280K characters depending on how
       decision-heavy the week was.
    2. Whole-value omission — if the projected payload still exceeds `budget`,
       drop entire sections in OMITTABLE_SECTIONS order — by what each question
       still needs, never by which happens to be biggest (#991) — and declare
       each in a top-level `_omitted` manifest that rides inside the payload,
       so the model is told about the gap instead of silently reading a sliced
       half-JSON. On heavy weeks this drops `plans` first, which is deliberate:
       its content is the daily raw view of the same decisions decision_episodes
       and decision_metrics already distill. The serialized result must always
       json.loads cleanly; there is deliberately no character-slice fallback.
    """
    def project_plan(entry):
        data = entry.get('data') or {}
        projected = dict(data)
        if isinstance(data.get('decisions'), list):
            projected['decisions'] = [_slim_decision(d) for d in data['decisions']]
        return {'date': entry.get('date'), 'data': projected}

    payload = dict(bundle)
    metrics = bundle.get('decision_metrics')
    if isinstance(metrics, dict):
        payload['decision_metrics'] = {
            k: v for k, v in metrics.items()
            if k not in METRICS_PROMPT_DROP_FIELDS}
    payload['plans'] = [project_plan(p) for p in bundle.get('plans') or []]
    payload['snapshots'] = [_slim_snapshot(s) for s in bundle.get('snapshots') or []]
    if isinstance(bundle.get('decision_episodes'), list):
        payload['decision_episodes'] = [
            _slim_decision(e) for e in bundle['decision_episodes']]

    omitted = []
    while True:
        # The manifest is part of the payload and grows with every drop, so it
        # is re-attached and re-measured each pass: the budget check must see
        # the payload as it will actually be serialized, manifest included.
        payload['_omitted'] = omitted
        if len(_compact(payload)) <= budget:
            break
        name = next((s for s in OMITTABLE_SECTIONS if s in payload), None)
        if name is None:
            break  # nothing omittable left: stay honest rather than slice
        omitted.append({'section': name,
                        'bytes': len(_compact(payload.pop(name)))})
    return payload


def build_user_prompt(payload):
    """Assemble the user turn. The JSON fence embeds exactly the serialization
    the budget was enforced against — `_compact`, byte for byte (#1000). The
    first cut embedded `json.dumps(payload)` with default separators, so every
    shipped prompt carried ~7% more characters than the check had measured and
    the sanity bound was not the bound of what actually left the door."""
    return (
        f"根据这一周（{payload['week']}）的 brief / plan / decision v2 / risk 数据, "
        f"写一篇 markdown 周复盘。长度自己判断，不设字数目标。"
        "\n\n"
        "1. **本周净值**: 周初/周末/涨跌三个数 harness 已算好在 "
        "`bundle_evidence.nav_change`（口径=期末减期初 NAV, 含期内任何出入金）——"
        "直接引用, 不要自己再从 snapshots 相减; 你要写的是主要贡献者与主要拖累的归因\n"
        "2. **决策兑现**: 按 strategy episode 汇总触发、执行和 win/loss；不要把每日重复 call 当独立样本\n"
        "3. **风险演变**: 当前 risk.json 数值, β/Vol/Max DD/Sharpe 怎么走?\n"
        "4. **下周关注 3 条**: actionable (ticker + 触发条件 + 仓位影响)\n\n"
        f"数据 bundle (JSON):\n```json\n{_compact(payload)}\n```\n\n"
        "若上面 JSON 含 `_omitted`，对应 section 因 prompt 预算被整体省略——"
        "相关小节必须如实写数据缺口，禁止编造。\n\n"
        "直接出 markdown, 不要客套."
    )


def main():
    bundle = aggregate_week()
    validate_bundle(bundle)
    week_id = bundle['week']

    system = "You are Rick, kcn's HK+US stock analyst. Write a weekly portfolio review."

    payload = build_prompt_payload(bundle)
    user = build_user_prompt(payload)

    # Weekly review benefits most from thinking + depth (1 turn, complex synthesis)
    out = chat(system=system, user=user, max_tokens=32000, temperature=0.6,
               timeout=WEEKLY_LLM_TIMEOUT_SECONDS)
    # Refuse before writing (#1263): a blank or off-prompt reply used to be
    # published as that week's review, and nothing downstream re-reads it.
    # Anchors are the four questions build_user_prompt asks for; the floor is
    # ~1/10th of a real review (2026-W34 is 11KB).
    validate_sections(out, label='weekly review',
                      required=WEEKLY_REQUIRED_SECTIONS, min_chars=1000)

    os.makedirs('memory/weekly', exist_ok=True)
    path = Path(f'memory/weekly/{week_id}.md')
    fm = f"---\nlayout: default\ntitle: 周复盘 · {week_id}\n---\n\n"
    path.write_text(fm + out.strip())
    print(f'  wrote {path}  ({len(out)} chars)')


if __name__ == '__main__':
    main()
