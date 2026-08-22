#!/usr/bin/env python3
"""Publish what we tested and what did not survive.

The dashboard shows outcomes. It cannot show the part that is actually rare:
what was tested, what failed, and what we refuse to claim. This repository runs
Wilson intervals, a leave-one-out Brier baseline, two-way clustered bootstrap
CIs, pre-registration that forbids retrospective activation, and — since #233 —
a permutation test that returned p = 0.92 against our own flagship leverage dial
and was published rather than buried. None of that was visible anywhere.

For a reader who knows what they are looking at, "here is what we tested and
here is what did not survive" is stronger evidence of method than any equity
curve, and it does not need a longer track record to become convincing.

Rules this generator follows
----------------------------
* **Every figure is read from an artifact.** Nothing is typed into the template.
  A number in static copy goes stale silently; this page is regenerated instead.
* **A negative result is not softened.** If a p-value cannot reject, the page
  says so in those words.
* **Absent evidence is not failure.** "Not yet decidable" is a distinct verdict
  from "tested and failed", and conflating them would be its own dishonesty.

Writes: site/evidence.md   Run: clawock evidence
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
OUT = WS / 'site' / 'evidence.md'
CARDS = WS / 'memory' / 'backtests'
DATA = WS / 'assets' / 'data'

VERDICT = {
    'failed': '🔴 未通过',
    'undecided': '⚪ 尚不可判',
    'passed': '🟢 通过',
    'pending': '⏳ 尚未到期',
}


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _latest_card(prefix: str):
    cards = sorted(CARDS.glob(f'{prefix}-*.json'))
    return _load(cards[-1]) if cards else None


def _pct(value, digits=1):
    return None if value is None else f'{float(value) * 100:.{digits}f}%'


def dial_section() -> dict | None:
    """The leverage dial: the strongest claim we had, and what it survived."""
    card = _latest_card('regime_dial_validation')
    if not card:
        return None
    metrics = card.get('metrics') or {}
    ins = metrics.get('in_sample') or {}
    perm = metrics.get('permutation') or {}
    wf = metrics.get('walk_forward') or {}
    sens = metrics.get('sensitivity') or {}
    tiers = (metrics.get('tier_distribution') or {}).get('pct') or {}

    p_dd = perm.get('p_value_drawdown')
    rows = [
        ('样本内改善（对比一直 2x）',
         f"{_pct(ins.get('dial_max_drawdown'))} vs {_pct(ins.get('hold_max_drawdown'))}"
         f"，即 {float(ins.get('drawdown_improvement', 0)) * 100:+.1f}pp"),
        ('置换检验 p 值（回撤 / 收益）',
         f"{p_dd:.3f} / {perm.get('p_value_return'):.3f}"),
        ('随机重排的中位改善',
         f"{_pct(perm.get('null_drawdown_improvement_median'))}"),
        ('样本外 walk-forward',
         f"{wf.get('folds_with_shallower_drawdown')} / {wf.get('n_folds')} 折改善回撤"
         f"，阈值{'稳定' if wf.get('threshold_stability') == 'stable' else '不稳定'}"),
        ('生产阈值在网格中的排名',
         f"{sens.get('production_rank')} / {len(sens.get('grid') or [])}"),
        ('各档触发占比',
         f"green {tiers.get('green')}% · amber {tiers.get('amber')}% · red {tiers.get('red')}%"),
    ]
    return {
        'title': '杠杆刻度盘（生产 tier 映射）',
        'verdict': VERDICT['failed'] if (p_dd is not None and p_dd > 0.10)
        else VERDICT['undecided'],
        'rows': rows,
        'reading': (
            f"观测到的改善比**随机重排同一条敞口路径的中位数还差**"
            f"（{_pct(perm.get('null_drawdown_improvement_median'))}）。"
            f"p = {p_dd:.3f} 是**未能拒绝原假设，不是证伪**——一个指数、一次崩盘，"
            f"撑不起「没用」，正如它撑不起「有用」。刻度盘保留未改；"
            f"不能再做的是拿另一个策略的数字当它的证据。"),
        'source': f"run card `{card.get('run_id')}`",
        'sample': f"{(card.get('inputs') or [{}])[0].get('bars')} 根日线 · "
                  f"{(card.get('inputs') or [{}])[0].get('first_session')} → "
                  f"{(card.get('inputs') or [{}])[0].get('last_session')}",
    }


def factor_section() -> dict | None:
    """Quant factors: which edges are locked out, and by what rule."""
    review = _load(DATA / 'quant_signal_review.json')
    if not review:
        return None
    factors = review.get('factors') or {}
    rows = []
    for name, stats in sorted(factors.items()):
        ci = stats.get('ci95')
        # A sample spanning a single date- or ticker-cluster cannot produce a
        # two-way clustered interval at all. Printing a bare hit rate there
        # invites the exact misreading the page exists to prevent: trend_on_follow
        # shows 3.1%, which is one ticker's 32 sessions, not a broken factor.
        single_cluster = (stats.get('n_tickers') or 0) < 2 or (stats.get('n_dates') or 0) < 2
        if single_cluster:
            verdict_text = '⚪ 样本只覆盖单一簇，算不出聚类 CI —— 无法解读'
        elif stats.get('edge_significant'):
            verdict_text = '✅ 可入决策'
        else:
            verdict_text = '⚪ CI 跨 50%，锁定'
        rows.append((
            f'`{name}`',
            f"命中率 {_pct(stats.get('hit_rate'))} · "
            f"CI95 {'—' if not ci else f'[{ci[0] * 100:.1f}%, {ci[1] * 100:.1f}%]'} · "
            f"n={stats.get('n_events')}（{stats.get('n_dates')} 日 × {stats.get('n_tickers')} 标的）· "
            f"{verdict_text}"))
    unlocked = sum(1 for s in factors.values() if s.get('edge_significant'))
    return {
        'title': '量化因子 edge',
        'verdict': VERDICT['passed'] if unlocked else VERDICT['undecided'],
        'rows': rows,
        'reading': (
            f"解锁规则是 `{review.get('unlock_rule')}`：置信区间必须整体落在 50% 一侧。"
            f"目前 {unlocked}/{len(factors)} 个因子达标。"
            f"**CI 跨 50% 是「样本还不够」，不是「因子无效」**——两者的处置相同（不入决策），"
            f"结论不同。"),
        'source': '`assets/data/quant_signal_review.json`',
        'sample': f"留痕 {review.get('days_logged')} 天",
    }



def _sessions_after(start: str, n: int, market: str = 'hk') -> str | None:
    """The date `n` trading sessions after `start`, or None if unknowable.

    Used to answer "when could this criterion first pass" instead of leaving a
    reader to derive it. Falls back to None rather than guessing when the
    calendar does not cover the horizon — a wrong date here would be worse than
    no date.
    """
    try:
        from datetime import date, timedelta
        from clawock import sessions as trading_calendar
    except Exception:
        return None
    try:
        day = date.fromisoformat(str(start)[:10])
    except ValueError:
        return None
    seen = 0
    for _ in range(n * 4):          # generous bound; loop is cheap and finite
        day += timedelta(days=1)
        if day.year > max(trading_calendar.covered_years(market) or {day.year}):
            return None
        if trading_calendar.is_trading_day(market, day):
            seen += 1
            if seen >= n:
                return day.isoformat()
    return None


def _horizon_status(payload, checks) -> dict:
    """Split "waiting on a horizon" from "measured and short".

    A prospective criterion sitting at zero while the forward window has not
    elapsed is not a failing check, and rendering it as one is the exact
    conflation this page claims not to make.
    """
    registered = str(payload.get('registered_at') or '')[:10]
    # The horizon lives in the layer's pre-registration config, not in its
    # output — reading it from the config is what makes "not yet elapsed" a
    # derived fact rather than a guess.
    config = _load(WS / 'config' / 'factor-universe.json') or {}
    horizon = int(config.get('forward_horizon_sessions') or 0)
    required = ((checks.get('prospective_dates') or {}).get('required')
                or (config.get('activation_criteria') or {}).get(
                    'min_prospective_dates'))
    actual = (checks.get('prospective_dates') or {}).get('actual')
    if not registered or not horizon or actual is None:
        return {'pending': False}
    if actual > 0:
        return {'pending': False}

    first_measurable = _sessions_after(registered, horizon)
    earliest_activation = (
        _sessions_after(first_measurable, int(required) - 1)
        if first_measurable and required else None)
    return {
        'pending': True,
        'horizon': horizon,
        'first_measurable': first_measurable,
        'earliest_activation': earliest_activation,
    }


def cross_sectional_section() -> dict | None:
    """The pre-registered layer that is still refusing to activate."""
    payload = _load(DATA / 'cross_sectional_factor.json')
    if not payload:
        return None
    activation = payload.get('activation') or {}
    checks = activation.get('checks') or {}
    rows = []
    for name, check in checks.items():
        if not isinstance(check, dict):
            continue
        rows.append((f'`{name}`',
                     f"{check.get('actual')} / 需要 {check.get('required')} · "
                     f"{'✅' if check.get('pass') else '⚪ 未达标'}"))
    horizon = _horizon_status(payload, checks)
    if horizon['pending']:
        verdict = VERDICT['pending']
        window = (f"最早可测 {horizon['first_measurable']}"
                  if horizon['first_measurable'] else '最早可测日期待日历覆盖')
        activation_at = (f"，按当前节奏最早 {horizon['earliest_activation']} 才可能激活"
                         if horizon['earliest_activation'] else '')
        reading = (
            f"**这不是一条没通过的检验，是还没到期。** 前瞻收益要 "
            f"{horizon['horizon']} 个交易日才算得出来，注册后的快照一条都还没满窗，"
            f"所以计数必然是 0（{window}{activation_at}）。"
            "这一层只用 `registered_at` 之后记录的快照，回溯结果永远不能激活它——"
            "代价就是必须等，而等待和失败是两件事。")
    else:
        verdict = (VERDICT['passed'] if activation.get('usable_for_decisions')
                   else VERDICT['undecided'])
        reading = (
            "这一层**只用 `registered_at` 之后记录的快照**做样本外验证，"
            "回溯结果永远不能激活它。目前仍未达标，因此不参与任何决策。"
            "「还没通过」被公开写出来，是为了让它日后通过时那句话有意义。")

    return {
        'title': '截面因子（预注册）',
        'verdict': verdict,
        'rows': rows,
        'reading': reading,
        'source': '`assets/data/cross_sectional_factor.json`',
        'sample': f"预注册于 {payload.get('registered_at')}",
    }


def add_alpha_section() -> dict | None:
    """The new add interaction, kept separate from legacy add decisions."""
    card = _latest_card('add_alpha_walkforward')
    if not card:
        return None
    metrics = card.get('metrics') or {}
    coverage = metrics.get('coverage') or {}
    rows = []
    for market in ('us', 'hk'):
        interaction = ((metrics.get(market) or {}).get('interaction') or {})
        for horizon in ('t1', 't5', 't20'):
            stat = interaction.get(horizon) or {}
            n = int(stat.get('n') or 0)
            if not n:
                value = 'collecting · n=0（不显示为 0%）'
            else:
                value = (f"n={n} · mean {_pct(stat.get('mean_return'), 2)} · "
                         f"hit {_pct(stat.get('hit_rate'), 1)} · "
                         f"{stat.get('status') or 'collecting'}")
            rows.append((f'`{market.upper()} {horizon.upper()} interaction`', value))
    authority = coverage.get('authority_classifications') or {}
    rows += [
        ('覆盖日期',
         f"factor {coverage.get('factor_dates')} · information "
         f"{coverage.get('information_dates')} · overlap {coverage.get('overlap_dates')}"),
        ('前瞻信息日期', str(coverage.get('prospective_information_dates'))),
        ('authority 分类',
         f"none {authority.get('none', 0)} · exploration "
         f"{authority.get('exploration', 0)} · validated {authority.get('validated', 0)}"),
    ]
    return {
        'title': '低频加仓交互（新 campaign）',
        'verdict': VERDICT['undecided'],
        'rows': rows,
        'reading': (
            "价格相对强弱与点时信息必须共同出现；技术位只安排已经获准的 tranche。"
            "当前 run card 是 current-universe / legacy-news replay，且前瞻信息日期仍为 0，"
            "所以只用于收集与诊断，**不是 validated alpha**。旧账本里的 "
            "`add_only_on_trigger` 是 mixed/legacy 样本，不计作这套 campaign 的成绩。"),
        'source': f"run card `{card.get('run_id')}`",
        'sample': f"factor {coverage.get('factor_dates')} 日 × information "
                  f"{coverage.get('information_dates')} 日",
    }


def render(sections: list[dict], generated_at: str) -> str:
    lines = [
        '---',
        'layout: default',
        'title: clawock · 证据与反证',
        'description: 我们测了什么、什么没通过。全部数字从产物读取，非手写。',
        '---',
        '',
        '# 证据与反证',
        '',
        '面板展示的是结果。这一页展示的是**方法**——测了什么、什么没活下来、'
        '以及我们拒绝声称什么。',
        '',
        '每个数字都在页面生成时从产物读出，没有一个是手打的：静态文案里的数字会'
        '悄悄过期，这一页是重新生成的。三种判定严格区分——'
        '**未通过**（测了，没活下来）、**尚不可判**（样本不够，还不能说）、'
        '**通过**。把前两者混为一谈本身就是一种不诚实。',
        '',
    ]
    for section in sections:
        lines += [f"## {section['title']}", '',
                  f"**判定：{section['verdict']}** · 样本：{section['sample']} · "
                  f"来源：{section['source']}", '', '| | |', '|---|---|']
        lines += [f'| {label} | {value} |' for label, value in section['rows']]
        lines += ['', f"> {section['reading']}", '']
    lines += ['---', '',
              f'<sub>由 `clawock evidence` 生成于 {generated_at}。'
              f'数字全部读自产物；改动结论请改产物，不要改这一页。</sub>', '']
    return '\n'.join(lines)


def build() -> str:
    builders = (dial_section, factor_section, cross_sectional_section,
                add_alpha_section)
    sections = [section for section in (build() for build in builders) if section]
    audit = _load(DATA / 'decision_audit.json') or {}
    return render(sections, audit.get('as_of') or 'unknown')


def main(argv=None) -> int:
    argparse.ArgumentParser(
        prog='clawock evidence', description=__doc__
    ).parse_args(argv)
    page = build()
    OUT.write_text(page, encoding='utf-8')
    print(f'wrote {OUT.relative_to(WS)} ({len(page.encode())} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
