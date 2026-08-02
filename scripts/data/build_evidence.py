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

Writes: evidence.md   Run: python3 scripts/data/build_evidence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
OUT = WS / 'evidence.md'
CARDS = WS / 'memory' / 'backtests'
DATA = WS / 'assets' / 'data'

VERDICT = {
    'failed': '🔴 未通过',
    'undecided': '⚪ 尚不可判',
    'passed': '🟢 通过',
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
        rows.append((
            f'`{name}`',
            f"命中率 {_pct(stats.get('hit_rate'))} · "
            f"CI95 {'—' if not ci else f'[{ci[0] * 100:.1f}%, {ci[1] * 100:.1f}%]'} · "
            f"n={stats.get('n_events')}（{stats.get('n_dates')} 日 × {stats.get('n_tickers')} 标的）· "
            f"{'✅ 可入决策' if stats.get('edge_significant') else '⚪ CI 跨 50%，锁定'}"))
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
    return {
        'title': '截面因子（预注册）',
        'verdict': VERDICT['passed'] if activation.get('usable_for_decisions')
        else VERDICT['undecided'],
        'rows': rows,
        'reading': (
            "这一层**只用 `registered_at` 之后记录的快照**做样本外验证，"
            "回溯结果永远不能激活它。目前仍未达标，因此不参与任何决策。"
            "「还没通过」被公开写出来，是为了让它日后通过时那句话有意义。"),
        'source': '`assets/data/cross_sectional_factor.json`',
        'sample': f"预注册于 {payload.get('registered_at')}",
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
              f'<sub>由 `scripts/data/build_evidence.py` 生成于 {generated_at}。'
              f'数字全部读自产物；改动结论请改产物，不要改这一页。</sub>', '']
    return '\n'.join(lines)


def build() -> str:
    builders = (dial_section, factor_section, cross_sectional_section)
    sections = [section for section in (build() for build in builders) if section]
    audit = _load(DATA / 'decision_audit.json') or {}
    return render(sections, audit.get('as_of') or 'unknown')


def main() -> int:
    page = build()
    OUT.write_text(page, encoding='utf-8')
    print(f'wrote {OUT.relative_to(WS)} ({len(page.encode())} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
