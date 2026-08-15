#!/usr/bin/env python3
"""
intraday_preflight.py — Mode 7 (intraday) harness preflight.

Runs deterministic work for the 3 intraday cron jobs (every 30 min):
  HK 盘中盯盘:              */30 10-11,14-15 * * 1-5  Asia/Shanghai
  US 盘中盯盘:              */30 22-23 * * 1-5        Asia/Shanghai
  US 盘中盯盘-overnight:    */30 0-2 * * 2-6          Asia/Shanghai

Each invocation:
  1. Runs analyze_{hk,us}_stocks.py --wechat
  2. Captures stdout as `raw_wechat_block` — the harness owns it end to end:
     intraday_postflight prepends it to the model's prose at send time, so it
     never makes a round trip through the LLM (see that module's
     assemble_message docstring for the 2026-07-28 mangling this removed)
  3. Detects anomalies (≥3% move, RSI extremes from script signals)
  4. Decides should_alert: bool (true if any anomaly OR ≥2 signals)
  4b. Collects peer/rotation data for this leg (`peer_scan`), free Tencent feed
      only, so the 板块全景 line has real numbers instead of an improvised fetch
  4c. Carries the 08:00 plan's still-open decisions for this leg (`plan_context`)
      so a slot executes the day's discipline instead of re-deriving it
  5. Writes memory/.tmp/intraday-context-{market}-{HHMM}.json

NB: Mode 7 is lightweight on purpose (8 HK + 10 US slots per trading day).
    The preflight itself does not commit and has no rich news block. A successful
    postflight publishes a semantic dashboard change, if any.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.workspace import workspace_root
from clawock.market_data import sessions as trading_calendar
from clawock.decision import plans as plan_surface
from clawock.decision import signals as quant_signals
from clawock.evidence import research_surface
from clawock.cli import PACKAGED_UTILITIES
from clawock.market_data import known_catalysts, mover_evidence as mover_news, peer_scan
from clawock.decision import active_information
from clawock.decision import early_trend
from clawock.portfolio.instruments import is_leveraged_holding

WS = workspace_root(Path.cwd())
TMP = WS / 'memory' / '.tmp'

from ._harness_common import compute_context_id

from clawock.automation import cron_heartbeat  # noqa: E402
from clawock.harness import intraday_delta  # noqa: E402


# Process-local bars cache for one preflight slot (#613): the provisional,
# early-trend and radar collectors each fetch the same code, and a 10-name
# portfolio was paying 3x fetches per slot (~540 requests/day). Cleared at the
# start of every main() run so a slot never reads the previous slot's bars.
_BARS_CACHE: dict[tuple[str, int], list] = {}


def _fetch_bars_cached(code, cnt=400):
    """fetch_bars memoised for the lifetime of one preflight slot."""
    key = (code, cnt)
    if key not in _BARS_CACHE:
        _BARS_CACHE[key] = quant_signals.fetch_bars(code, cnt)
    return _BARS_CACHE[key]


# `scripts/data` was deleted in #429 and the analysis moved into the package in
# #421, which added `clawock analyze-hk` / `analyze-us` but left these two callers
# pointing at the old path. Both preflights then failed on every run while still
# exiting 0, so the agent saw no error and went hunting through site-packages
# instead of writing a report (#447).
#
# PACKAGED_UTILITIES is the CLI's own map and is already guarded by
# test_harness_cli_contract, so resolving through it means these callers cannot
# drift from the commands again. sys.executable rather than a bare name: this
# runs under cron, whose PATH is /usr/bin:/bin (#438, #443).
def run_analyze(market):
    module = PACKAGED_UTILITIES[f'analyze-{market}']
    try:
        r = subprocess.run(
            [sys.executable, '-m', module, '--wechat', '--md-table'],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'{module} timeout (120s)'
    except Exception as e:
        return -1, '', f'{module} error: {e}'


SIGNAL_LEVELS = ('ALERT', 'WATCH', 'STOP', 'TRIM')


def read_signal_line(line):
    """`(level, ticker)` for a rendered signal line, or `(None, None)`.

    The renderer writes `✋ STOP? 02208 金风科技 | …` — marker, level, code. The
    level must therefore *be* one of the first two tokens, not appear inside
    one: `WATCHDOG` contains WATCH and a substring test reads that line as a
    signal, then publishes the following word as its ticker. Letters only, so
    `✋STOP?` and `STOP?` both normalise to STOP however the emoji lands.

    Reading the code here, once, is also what keeps consumers from matching the
    display text — a substring test lets a one-letter US ticker match any word
    on the line, and reads a bare figure in the P&L cell as a code.
    """
    tokens = (line or '').split()
    for index, token in enumerate(tokens[:2]):
        word = re.sub(r'[^A-Z]', '', token.upper())
        if word in SIGNAL_LEVELS:
            ticker = tokens[index + 1] if index + 1 < len(tokens) else None
            return word, ticker
    return None, None


def parse_signals(stdout):
    counts = {level.lower(): 0 for level in SIGNAL_LEVELS}
    in_signals = False
    signals_detail = []
    for line in stdout.splitlines():
        if '⚠️ 信号' in line:
            in_signals = True
            continue
        if in_signals:
            s = line.strip()
            if s.startswith('📉') or s.startswith('📰'):
                break
            if not s:
                continue
            # ALERT is the most severe line the renderer emits (a -8% day) and
            # it was in none of these counts — so the one level that outranks
            # STOP was invisible to every consumer, including the entry/risk
            # contradiction check below.
            level, ticker = read_signal_line(s)
            if level:
                counts[level.lower()] += 1
                signals_detail.append({'level': level, 'line': s, 'ticker': ticker})
    return counts, signals_detail


def decide_alert(signals, anomalies):
    """`(should_alert, reasons)` for this slot.

    Extracted from `main` so the rule can be asserted rather than read: ALERT
    joining STOP as a severity that alone justifies waking kcn is a change to
    what 18 slots a day do, and it was previously only visible by running the
    whole preflight.

    ALERT does not in practice add wake-ups — the renderer only emits it on a
    -8% day, which the ≥3% anomaly rule already caught — but it must not be the
    one severity that a slot could see and stay quiet about.
    """
    total = sum(signals[level.lower()] for level in SIGNAL_LEVELS)
    severe = signals['stop'] + signals['alert']
    should_alert = bool(anomalies) or total >= 2 or severe > 0

    reasons = []
    if anomalies:
        tickers = ', '.join(f"{a['ticker']} ({a['move_pct']:+.1f}%)" for a in anomalies)
        reasons.append(f'异动: {tickers}')
    if signals['alert'] > 0:
        reasons.append(f'ALERT 信号 ×{signals["alert"]}')
    if signals['stop'] > 0:
        reasons.append(f'STOP 信号 ×{signals["stop"]}')
    if total >= 2:
        reasons.append(f'多重信号 (A{signals["alert"]} W{signals["watch"]} '
                       f'S{signals["stop"]} T{signals["trim"]})')
    return should_alert, reasons


MAX_SETUP_LINES = 6


def collect_provisional_setups(market):
    """This leg's entry rules re-run on the open bar. Never raises.

    Bounded to the leg being reported: a 港股 slot has no use for a US breakout
    it cannot act on for another nine hours.
    """
    try:
        return quant_signals.provisional_setups(
            region='HK' if market == 'hk' else 'US', fetch=_fetch_bars_cached)
    except Exception as exc:  # noqa: BLE001 — a quote feed must never red the cron
        return {'rows': [], 'confirmed_at_close': False,
                'errors': [{'label': None,
                            'error': f'{type(exc).__name__}: {exc}'[:200]}]}


CONFLICTING_LEVELS = ('STOP', 'ALERT')


def setup_conflicts(setups, signals_detail):
    """Tickers that have an entry condition and a risk signal in the same push.

    An entry rule reads the price series; the risk line reads the position. They
    can and do disagree — 02208 can reclaim its 20-day high while sitting at
    -24% and flagged ✋ STOP?. Sending both without a word is how a push
    contradicts itself, and the reader resolves it by picking whichever line
    they saw first. The entry row is not suppressed (the condition is a fact),
    it is marked (so is the risk).
    """
    flagged = {item.get('ticker') for item in (signals_detail or [])
               if str(item.get('level', '')).upper() in CONFLICTING_LEVELS}
    flagged.discard(None)
    conflicted = set()
    for row in (setups or {}).get('rows') or []:
        for ticker in row.get('holdings') or [row.get('label')]:
            if ticker and ticker in flagged:
                conflicted.add(ticker)
    return sorted(conflicted)


def append_setup_section(block, setups, signals_detail=None):
    """Render provisional setups under the block, or return it untouched.

    Untouched is the common case and it has to stay byte-identical: postflight
    checks the report against this string, and every slot without a setup is a
    slot whose push must look exactly as it did before.

    Every row repeats 未收盘 rather than leaning on the heading. The heading is
    not protected by anything: postflight's verbatim check only covers the block
    first line and its markdown tables, so in legacy mode a report that dropped
    the heading and kept `20日突破确认 | 入场 …` would pass — and a provisional
    condition would have been published as an entry that fired. The caveat has
    to live on the line it qualifies.
    """
    rows = (setups or {}).get('rows') or []
    if not rows:
        return block
    conflicts = set(setup_conflicts(setups, signals_detail))
    lines = ['', '⚡ 盘中 setup（未收盘 · 若收在此位则成立，不是已触发）']
    for row in rows[:MAX_SETUP_LINES]:
        entry, invalid = row.get('entry_price'), row.get('invalidation_price')
        bits = [f"  ◆ [未收盘] {row.get('label')} "
                f"{row.get('label_zh') or row.get('setup_id')}"]
        if entry is not None:
            bits.append(f"入场 {entry:g}")
        if invalid is not None:
            bits.append(f"失效 {invalid:g}")
        held = [t for t in (row.get('holdings') or []) if t in conflicts]
        if held:
            bits.append(f"⚠️ 同票有风险信号({'/'.join(held)})")
        lines.append(' | '.join(bits))
    if len(rows) > MAX_SETUP_LINES:
        lines.append(f'  …另有 {len(rows) - MAX_SETUP_LINES} 条')
    return block + '\n' + '\n'.join(lines)


EARLY_STATE_LABELS = {
    'wait_pullback_rebreak': '候选·等回踩再突破',
    'wait_information': '候选·等信息确认',
    'exploration_ready': '候选·探索就绪',
    'candidate_only': '候选·仅观察(杠杆)',
}


def _load_json(path):
    """Read a JSON asset as a dict, never raising.

    #612: a file that parses to a non-dict (e.g. a list) used to escape the
    try/except below and AttributeError the whole preflight at `.get`. A
    non-dict shape is treated as absent, matching the missing-file case.
    """
    try:
        value = json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def collect_early_trend_candidates(market):
    """Re-run the early-trend classifier on the open bar for this leg (#543).

    The 08:00 brief computes `wait_pullback_rebreak` once on completed bars, so a
    CRCL pullback at 11:00 is a fact the decision surface does not see until the
    next morning. This re-runs `early_trend.classify` with the intraday technical
    view (the only input that changes intraday) and reuses the daily peer /
    information / policy payloads. It is fail-soft by design: a feed that stops
    answering returns no candidates, never a red cron.
    """
    region = 'HK' if market == 'hk' else 'US'
    errors = []
    try:
        universe = [d for d in quant_signals.universe_details(errors=errors)
                    if d.get('region') == region]
    except Exception as exc:  # noqa: BLE001 — last resort; universe_details is per-holding tolerant
        return {'rows': [],
                'errors': [{'label': None,
                            'error': f'{type(exc).__name__}: {exc}'[:200]}]}
    peer_rows = (_load_json(WS / 'assets' / 'data' / 'peer_residual.json')
                 .get('live') or {})
    graph = _load_json(WS / 'assets' / 'data' / 'news_evidence_graph.json')
    info_rows = ((graph.get('information_overlay') or {}).get('tickers') or {})
    events = (graph or {}).get('events') or []
    try:
        policy = json.loads(
            (WS / 'config' / 'add-alpha-policy.json').read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        policy = {}
    rows = []
    run_date = datetime.now(ZoneInfo('Asia/Hong_Kong')).date()
    for detail in universe:
        label = detail.get('label')
        try:
            bars = _fetch_bars_cached(detail['code'], 400)
            sig = quant_signals.compute_signals(bars)
            if sig is None and quant_signals.is_short_history_candidate(
                    detail, run_date):
                # Only a genuinely-new name may use the 20-bar short view; a
                # partial-feed mature name stays on the 30-bar gate (#608).
                sig = quant_signals.compute_short_history_signals(bars)
        except Exception:  # noqa: BLE001
            continue
        if not sig:
            continue
        technical = {
            'close': sig.get('close'),
            'prior_20d_high': sig.get('prior_20d_high'),
            'prior_5d_low': sig.get('prior_5d_low'),
            'ma20': sig.get('ma20'),
            'chandelier_stop': sig.get('chandelier_stop'),
            'zscore20': sig.get('zscore20'),
            'usable': True,
        }
        prow = peer_rows.get(label) or {}
        peer = {
            'residual_5d': prow.get('residual_blend_5d'),
            'dispersion_5d': prow.get('peer_dispersion_5d'),
            'available_peer_count': prow.get('available_peer_count'),
        }
        irow = info_rows.get(label) or {}
        information = {
            'attention_rank': irow.get('attention_rank'),
            'attention_acceleration': irow.get('attention_acceleration'),
            'attention_source_type_count': irow.get('attention_source_type_count'),
            'attention_event_count': irow.get('attention_event_count'),
        }
        holdings = list(detail.get('source_holdings') or [label])
        # #603: the daily path bridges `direction` from `impact_direction`
        # (packet._event_view); the raw event dicts only carry impact_direction,
        # so the intraday lane handed classify() a payload where primary_ids was
        # always empty. Normalise exactly like the daily path before matching.
        matching = []
        for event in events:
            if str(event.get('ticker') or event.get('reported_ticker') or '') \
                    not in set(holdings) | {label}:
                continue
            view = dict(event)
            direction = event.get('direction', event.get('impact_direction'))
            if direction not in (None, '', []):
                view['direction'] = direction
            matching.append(view)
        leveraged = any(
            is_leveraged_holding({'ticker': ticker}) for ticker in holdings
        )
        try:
            candidate = early_trend.classify(
                technical, peer, information, matching,
                leveraged=leveraged, policy=policy, market=market,
            )
        except Exception:  # noqa: BLE001
            continue
        if not candidate.get('observed'):
            continue
        rows.append({
            'label': label,
            'setup_id': f"early_trend:{candidate['state']}",
            'state': candidate.get('state'),
            'state_zh': EARLY_STATE_LABELS.get(candidate.get('state'),
                                              candidate.get('state')),
            'holdings': holdings,
            'close': sig.get('close'),
            'prior_20d_high': sig.get('prior_20d_high'),
            'blockers': candidate.get('blockers') or [],
        })
    result = {'rows': rows}
    if errors:
        # Data gaps must be said, not swallowed (#612): a registry gap that
        # used to blank the whole lane now lands here for the context JSON.
        result['errors'] = errors
    return result


def append_early_trend_section(block, candidates, signals_detail=None):
    """Render observed early-trend candidates, or return the block untouched.

    Additive only: a slot with no candidates must stay byte-identical, exactly
    like `append_setup_section`. A candidate is a reason to look, never an entry
    — the 08:00 discipline is "候选≠下单".
    """
    rows = (candidates or {}).get('rows') or []
    if not rows:
        return block
    conflicts = setup_conflicts(candidates, signals_detail)
    lines = ['', '🕯️ 早期趋势候选（未收盘 · 候选≠下单）']
    for row in rows[:MAX_SETUP_LINES]:
        bits = [f"  ◆ [未收盘] {row.get('label')} "
                f"{row.get('state_zh') or row.get('state')}"]
        close, prior = row.get('close'), row.get('prior_20d_high')
        if close is not None and prior is not None:
            bits.append(f"现价 {close:g} / 前高 {prior:g}")
        held = [t for t in (row.get('holdings') or []) if t in conflicts]
        if held:
            bits.append(f"⚠️ 同票有风险信号({'/'.join(held)})")
        lines.append(' | '.join(bits))
    if len(rows) > MAX_SETUP_LINES:
        lines.append(f'  …另有 {len(rows) - MAX_SETUP_LINES} 条')
    return block + '\n' + '\n'.join(lines)


OPPORTUNITY_NEAR_PCT = 5.0


def collect_opportunity_radar(market):
    """机会雷达:突破/等回踩/接近突破的价格面候选观察(#551)。

    与 early_trend 的区别:这是纯价格面,不要求 peer/information 确认——
    回答"机会在哪",不下单授权(候选≠下单)。数据来自 technical 视图,
    与本槽其他 collector 共享同一趟 bars 抓取(#613,非"零抓取")。
    fail-soft:任何名字取不到 bars 就跳过,registry 缺口进 errors,不红 cron。
    """
    region = 'HK' if market == 'hk' else 'US'
    errors = []
    try:
        universe = [d for d in quant_signals.universe_details(errors=errors)
                    if d.get('region') == region]
    except Exception as exc:  # noqa: BLE001 — last resort; universe_details is per-holding tolerant
        return {'rows': [],
                'errors': [{'label': None,
                            'error': f'{type(exc).__name__}: {exc}'[:200]}]}
    rows = []
    run_date = datetime.now(ZoneInfo('Asia/Hong_Kong')).date()
    for detail in universe:
        label = detail.get('label')
        try:
            bars = _fetch_bars_cached(detail['code'], 400)
            sig = quant_signals.compute_signals(bars)
            if sig is None and quant_signals.is_short_history_candidate(
                    detail, run_date):
                # Only a genuinely-new name may use the 20-bar short view; a
                # partial-feed mature name stays on the 30-bar gate (#608).
                sig = quant_signals.compute_short_history_signals(bars)
        except Exception:  # noqa: BLE001
            continue
        if not sig:
            continue
        close = sig.get('close')
        prior = sig.get('prior_20d_high')
        z = sig.get('zscore20')
        if close is None or prior is None or prior <= 0:
            continue
        pct_from_high = (close / prior - 1) * 100
        if close > prior and (z is None or z < 2):
            state, state_zh = 'breakout', '机会·突破'
        elif close > prior:
            state, state_zh = 'wait_rebreak', '机会·等回踩'
        elif close >= prior * (1 - OPPORTUNITY_NEAR_PCT / 100):
            state, state_zh = 'near_breakout', '机会·接近'
        else:
            continue
        rows.append({
            'label': label,
            'setup_id': f"opportunity:{state}",
            'state': state,
            'state_zh': state_zh,
            'holdings': list(detail.get('source_holdings') or [label]),
            'close': close,
            'prior_20d_high': prior,
            'pct_from_high': round(pct_from_high, 2),
            'zscore20': z,
        })
    rows.sort(key=lambda row: row['pct_from_high'], reverse=True)
    result = {'rows': rows}
    if errors:
        result['errors'] = errors
    return result


def append_opportunity_radar_section(block, radar, signals_detail=None):
    """Render the opportunity radar, or return the block untouched.

    Additive only: a slot with no candidates must stay byte-identical, exactly
    like `append_early_trend_section`. Radar rows are price-surface observations
    — 候选≠下单, they never grant entry authorization.
    """
    rows = (radar or {}).get('rows') or []
    if not rows:
        return block
    conflicts = setup_conflicts(radar, signals_detail)
    lines = ['', '🎯 机会雷达（候选≠下单 · 价格面观察）']
    for row in rows[:MAX_SETUP_LINES]:
        bits = [f"  ◆ {row.get('label')} {row.get('state_zh')}"]
        close, prior = row.get('close'), row.get('prior_20d_high')
        if close is not None and prior is not None:
            bits.append(f"现价 {close:g} / 前高 {prior:g}")
        pct = row.get('pct_from_high')
        if isinstance(pct, (int, float)) and pct < 0:
            bits.append(f"距前高 {-pct:.1f}%")
        z = row.get('zscore20')
        if z is not None:
            bits.append(f"z {z:.2f}")
        held = [t for t in (row.get('holdings') or []) if t in conflicts]
        if held:
            bits.append(f"⚠️ 同票有风险信号({'/'.join(held)})")
        lines.append(' | '.join(bits))
    if len(rows) > MAX_SETUP_LINES:
        lines.append(f'  …另有 {len(rows) - MAX_SETUP_LINES} 条')
    return block + '\n' + '\n'.join(lines)


def attach_reinvest_candidates(plan_ctx, opportunity_radar, signals_detail=None):
    """Pair cut/trim ammunition with same-leg opportunity candidates (#555).

    A risk_rule cut used to be a dead end: the plan says sell, never what the
    money is for. This attaches up to two radar candidates (the same leg, no
    STOP/ALERT flag) to the plan context so the prose can say "砍 X 的弹药 →
    候选:Y(突破 Z 触发)/ W(等回踩)". Candidates are observations, never orders.
    Returns the plan context unchanged when there is nothing to pair.
    """
    rows = (opportunity_radar or {}).get('rows') or []
    if not rows:
        return plan_ctx
    # #605: only an open cut/trim decision has ammunition to pair. A clean day
    # must return the context unchanged — otherwise the model sees an
    # "ammunition" field with nothing to cut and can invent a cut for the money.
    if not any(str(row.get('action')) in ('cut', 'trim_on_rebound')
               for row in ((plan_ctx or {}).get('open') or [])):
        return plan_ctx
    flagged = {item.get('ticker') for item in (signals_detail or [])
               if str(item.get('level', '')).upper() in CONFLICTING_LEVELS}
    flagged.discard(None)
    candidates = []
    for row in rows:
        if set(row.get('holdings') or []) & flagged:
            continue
        prior = row.get('prior_20d_high')
        trigger = ('已突破' if row.get('state') == 'breakout'
                   else f"突破前高 {prior:g}" if prior is not None else '等回踩')
        candidates.append({
            'ticker': row.get('label'),
            'state': row.get('state'),
            'trigger': trigger,
        })
        if len(candidates) >= 2:
            break
    if not candidates:
        return plan_ctx
    return {**(plan_ctx or {}), 'reinvest_candidates': candidates}


def append_active_information_section(block, active, *, event_ids=None):
    """Render changed primary events plus compact context for existing ones.

    A setup or risk delta still produces a full message.  In that case an
    unchanged but live primary candidate must not disappear, while repeating
    its full detail every 30 minutes would recreate the noise this lane removes.
    """
    all_rows = (active or {}).get('candidates') or []
    rows = all_rows
    if event_ids is not None:
        rows = [row for row in rows if row.get('event_id') in event_ids]
    existing = [row for row in all_rows if row not in rows]
    degraded = (active or {}).get('degraded_issuers') or []
    partial = (active or {}).get('partially_degraded_issuers') or []
    if not rows and not existing and not degraded and not partial:
        return block
    lines = ['', '🛰️ 主动一级信息（候选≠下单）']
    label = {'candidate': '候选', 'wait': '等待', 'reject': '拒绝加仓'}
    for row in rows[:4]:
        reaction = row.get('session_reaction_pct')
        reaction_text = f'{reaction:+g}%' if isinstance(reaction, (int, float)) else '价格反应缺失'
        detail = str(row.get('detail') or '')[:120]
        bits = [
            f"  ◆ {row.get('issuer')} [{label.get(row.get('disposition'), row.get('disposition'))}]",
            f"{row.get('category')} / {row.get('direction')}", reaction_text, detail,
        ]
        hint = row.get('exploration_hint') or {}
        if hint:
            unit = '一手' if hint.get('unit') == 'one_board_lot' else '1股'
            bits.append(f"探索上限 {unit}({hint.get('shares')}股)，未授权")
        lines.append(' | '.join(bits))
    if len(rows) > 4:
        lines.append(f'  …另有 {len(rows) - 4} 条')
    if existing:
        summaries = [
            f"{row.get('issuer')}[{label.get(row.get('disposition'), row.get('disposition'))}]"
            for row in existing[:6]
        ]
        suffix = f"，另{len(existing) - 6}条" if len(existing) > 6 else ''
        lines.append(f"  ↳ 仍有效：{'、'.join(summaries)}{suffix}（详因沿用，不重复展开）")
    if degraded:
        lines.append(f"  ⚠️ 一级源降级：{','.join(degraded)}（不是无消息）")
    if partial:
        lines.append(
            f"  △ SEC直连降级、镜像已检查：{','.join(partial)}"
        )
    return block + '\n' + '\n'.join(lines)


def _quote_fetched_at(data_source, market, now):
    """Parse the per-holding provenance stamp written by this analysis run."""
    text = str(data_source or '')
    zone = ZoneInfo('America/New_York') if market == 'us' else ZoneInfo('Asia/Hong_Kong')
    patterns = (
        (r'([A-Z][a-z]{2} \d{1,2}, \d{4} \d{2}:\d{2}) ET\b', '%b %d, %Y %H:%M'),
        (r'([A-Z][a-z]{2} \d{1,2} \d{2}:\d{2}) HKT\b', '%b %d %H:%M'),
    )
    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            parsed = datetime.strptime(match.group(1), fmt)
            if '%Y' not in fmt:
                parsed = parsed.replace(year=now.astimezone(zone).year)
                # A Dec quote observed just after New Year belongs to last year.
                if parsed.replace(tzinfo=zone) > now.astimezone(zone) + timedelta(days=2):
                    parsed = parsed.replace(year=parsed.year - 1)
            return parsed.replace(tzinfo=zone)
        except ValueError:
            return None
    return None


def quote_coverage(_block, market, portfolio_path=None, *, now=None,
                   started_at=None, fresh_minutes=5):
    """Count holdings whose persisted provenance proves a fetch in this run.

    Rendered table rows are not evidence of freshness: the analyzer also renders
    an old portfolio value when every provider failed.  Each successful fetch
    stamps that holding's ``data_source``, so compare those stamps with the
    timezone-aware preflight time instead.
    """
    now = now or datetime.now(ZoneInfo('Asia/Hong_Kong'))
    now = now if now.tzinfo else now.replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
    started_at = started_at or (now - timedelta(minutes=fresh_minutes))
    started_at = (
        started_at if started_at.tzinfo
        else started_at.replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
    )
    active = []
    try:
        portfolio = json.loads(Path(portfolio_path or (WS / 'portfolio.json')).read_text())
        leg = 'hk_stocks' if market == 'hk' else 'us_stocks'
        active = [
            row for row in portfolio.get('portfolios', {}).get(leg, {}).get('holdings', [])
            if (row.get('shares') or 0) > 0
        ]
    except (OSError, json.JSONDecodeError, TypeError):
        return {'refreshed': 0, 'active': 0, 'unrefreshed': []}
    refreshed = []
    unrefreshed = []
    for row in active:
        fetched_at = _quote_fetched_at(row.get('data_source'), market, now)
        since_start = (
            fetched_at - started_at.astimezone(fetched_at.tzinfo)
        ).total_seconds() if fetched_at else None
        until_end = (
            now.astimezone(fetched_at.tzinfo) - fetched_at
        ).total_seconds() if fetched_at else None
        ticker = row.get('ticker')
        # US fallback can return an earlier-session print.  The fetch happened,
        # but ``quote_incomplete`` is the analyzer's explicit warning that the
        # resulting price is not a fully refreshed live quote.
        if (since_start is not None and since_start >= -60 and until_end >= -60
                and not row.get('quote_incomplete')):
            refreshed.append(ticker)
        else:
            unrefreshed.append(ticker)
    return {
        'refreshed': len(refreshed), 'active': len(active),
        'unrefreshed': [ticker for ticker in unrefreshed if ticker],
    }


def render_unchanged_receipt(market, block, coverage, active):
    first = ((block or '').strip().splitlines() or [
        '🇭🇰 港股盯盘' if market == 'hk' else '🇺🇸 美股盯盘'
    ])[0]
    refreshed, total = coverage.get('refreshed', 0), coverage.get('active', 0)
    collection = (active or {}).get('collection') or {}
    source = '一级信息缓存复核' if collection.get('cache_hit') else '一级信息刚检查'
    lines = [first, f'✓ 本轮无新的加仓/减仓条件；本轮行情刷新 {refreshed}/{total}；{source}。']
    missing = coverage.get('unrefreshed') or []
    if missing:
        lines.append(f"⚠️ 未证实本轮刷新：{','.join(missing)}（沿用上一笔，不冒充实时）")
    degraded = (active or {}).get('degraded_issuers') or []
    partial = (active or {}).get('partially_degraded_issuers') or []
    if degraded:
        lines.append(f"⚠️ 一级源降级：{','.join(degraded)}（不是无消息）")
    if partial:
        lines.append(f"△ 一级源部分降级、镜像已检查：{','.join(partial)}")
    return '\n'.join(lines)


def apply_active_information_alert(should_alert, reasons, active):
    """A primary event is alert-worthy even when no ticker has moved 3%."""
    rows = [
        row for row in ((active or {}).get('candidates') or [])
        if row.get('is_new', True)
    ]
    if not rows:
        return should_alert, reasons
    issuers = ', '.join(dict.fromkeys(
        row.get('issuer') for row in rows if row.get('issuer')
    ))
    return True, [*reasons, f'主动一级信息: {issuers}']


def parse_anomalies(stdout):
    """Parse markdown holdings table rows (--md-table form) and flag ≥3% moves.

    Row shape (7 cols, both markets, since 2026-05-21):
      HK: `| 00100 | 60 | 822.83 | 722.00 | +5.1% | -12.2% | -6,050 |`
      US: `| RKLB |  5 |  71.00 | 134.28 | +0.0% | +89.1% |   +316 |`
    Cell[0]=ticker, [4]=today%, [5]=pnl%, [6]=pnl_abs ($).
    Header / separator rows are filtered (代码 / `:---`).
    """
    anomalies = []
    pct_re = re.compile(r'([+\-])([\d\.]+)%')
    for line in stdout.splitlines():
        s = line.strip()
        if not s.startswith('|') or not s.endswith('|'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if len(cells) < 7:
            continue
        ticker = cells[0]
        if ticker == '代码' or ticker.startswith(':'):  # header / separator
            continue
        today = cells[4]
        m = pct_re.search(today)
        if not m:
            continue
        sign, pct_str = m.groups()
        pct = float(pct_str)
        if pct < 3.0:
            continue
        anomalies.append({
            'ticker':   ticker,
            'move_pct': (1 if sign == '+' else -1) * pct,
            'severity': 'high' if pct >= 5 else 'medium',
        })
    return anomalies


def collect_peers(market):
    """Peer/rotation data for this market's holdings (板块全景 section).

    Scoped to the leg being watched so a HK check-in never fans out to US
    tickers. Only hits the free Tencent feed and shares fetch_peers' 90s budget;
    peers must never delay or fail a check-in, so anything wrong degrades to {}.
    """
    leg = 'hk_stocks' if market == 'hk' else 'us_stocks'
    try:
        portfolio = json.loads((WS / 'portfolio.json').read_text())
        # stdout carries the context JSON the agent parses; logs go to stderr.
        return peer_scan.collect(portfolio, log=lambda m: print(m, file=sys.stderr),
                                 legs=(leg,))
    except Exception as e:
        print(f'   ⚠️  peer scan skipped: {e}', file=sys.stderr)
        return {}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    args = parser.parse_args(argv)

    now = datetime.now(ZoneInfo('Asia/Hong_Kong'))
    stamp = now.strftime('%Y-%m-%d_%H%M')
    heartbeat = cron_heartbeat.record(args.market, 'started')

    # One fetch per code per slot: the three collectors share this slot's bars
    # through _fetch_bars_cached (#613).
    _BARS_CACHE.clear()

    # Holiday/weekend gate (before fetch): closed market → no stale price write,
    # emit a market_closed sentinel (no alert), exit 0.
    reason = trading_calendar.closed_reason(args.market)
    if reason:
        cron_heartbeat.record(
            args.market, 'market_closed', job_name=heartbeat['job'],
            slot=heartbeat['slot'], reason=reason,
        )
        result = {'status': 'market_closed', 'market': args.market,
                  'reason': reason, 'should_alert': False, 'skip': True,
                  'heartbeat': {'job': heartbeat['job'], 'slot': heartbeat['slot']}}
        TMP.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        (TMP / f'intraday-context-{args.market}-{stamp}.json').write_text(payload)
        # Also refresh -latest.json (the watchdog reads it) so it sees a clean
        # market_closed instead of yesterday's stale block.
        (TMP / f'intraday-context-{args.market}-latest.json').write_text(payload)
        market_cn = '港股' if args.market == 'hk' else '美股'
        print(f'=== MARKET CLOSED — {market_cn}今日{reason} ===')
        print('SKIP：不要生成报告、不要调用任何 send/postflight、本回合到此结束。')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    rc, stdout, stderr = run_analyze(args.market)

    if rc != 0:
        cron_heartbeat.record(
            args.market, 'preflight_failed', job_name=heartbeat['job'],
            slot=heartbeat['slot'], failure_stage='preflight', return_code=rc,
        )
        result = {
            'status': 'preflight_failed',
            'market': args.market,
            'error':  stderr[-500:] if stderr else f'rc={rc}',
            'heartbeat': {'job': heartbeat['job'], 'slot': heartbeat['slot']},
        }
        TMP.mkdir(parents=True, exist_ok=True)
        (TMP / f'intraday-context-{args.market}-{stamp}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    signals, signals_detail = parse_signals(stdout)
    anomalies = parse_anomalies(stdout)

    # T+0 牌面评级 — analyze_*_stocks 刚刷过价，此处用实时区间位算追高检测。
    # 零额外请求（T0_INTRADAY 默认关）。失败不阻断盯盘。
    t0_setups = {}
    try:
        # Same interpreter, not a bare name: under cron PATH is /usr/bin:/bin and
        # the launcher lives in ~/.local/bin, so `clawock` does not resolve (#438,
        # #443). Here the except swallows it, which is exactly how a dead call
        # stays invisible.
        subprocess.run([sys.executable, '-m', PACKAGED_UTILITIES['t0']],
                       capture_output=True, text=True, timeout=45, check=False)
        t0_path = WS / 'assets' / 'data' / 't0_setups.json'
        if t0_path.exists():
            t0_setups = json.loads(t0_path.read_text())
    except Exception:
        pass

    should_alert, alert_reasons = decide_alert(signals, anomalies)

    # Information first: scan the bounded issuer set before requiring a tape
    # anomaly.  This is the active counterpart to mover_news below, which still
    # answers the separate question "what explains an already-large move?".
    try:
        active_information_ctx = active_information.scan_workspace(WS, args.market)
    except Exception as exc:  # noqa: BLE001 — a filing source must not red a slot
        active_information_ctx = {
            'schema_version': 1, 'market': args.market, 'candidates': [],
            'candidate_count': 0, 'wait_count': 0, 'reject_count': 0,
            'degraded_issuers': [],
            'error': f'{type(exc).__name__}: {exc}'[:200],
        }
    should_alert, alert_reasons = apply_active_information_alert(
        should_alert, alert_reasons, active_information_ctx,
    )

    # Thesis/red-line state for the names this slot already flagged. Local JSON
    # only, scoped to movers, and attribution context — never an action trigger
    # on its own (the catalyst gate still decides that).
    mover_thesis = research_surface.movers_thesis_context(
        [a['ticker'] for a in anomalies]
    )

    # What was actually published behind those moves. Mover-scoped, bounded
    # by a wall-clock budget, and fails soft — a news endpoint must never
    # slow or red a reporting cron.
    mover_news_ctx = mover_news.probe(
        [a['ticker'] for a in anomalies], market=args.market,
    )

    # The 08:00 plan's open orders for this leg. A 30-minute slot's most useful
    # sentence is usually "the swap you planned has not filled yet" — before this
    # existed, the 10:05 slot had to shell out six times to find that out and
    # still misquoted the size (issues #119/#120). Never raises.
    plan_ctx = plan_surface.open_decisions_context(
        leg='HK' if args.market == 'hk' else 'US',
        today=now.strftime('%Y-%m-%d'),
    )

    # A narrow news window answers "what is new this slot", not "what is known
    # to drive the move".  Carry the morning brief's structured events for these
    # movers so an overnight announcement that is reacting today is not called
    # unexplainable (#354).  Local, bounded, fail-soft; mover_news stays narrow.
    known_catalyst_ctx = known_catalysts.for_movers(
        [a['ticker'] for a in anomalies], today=now.strftime('%Y-%m-%d'),
    )

    # The same entry rules the 08:00 brief runs, re-evaluated on the open bar.
    # Rendered into the block rather than left in JSON alone: a field nothing
    # prints is a detector that has been silenced (#515).
    live_setups = collect_provisional_setups(args.market)
    # The early-trend lane is re-run on the open bar too (#543): the 08:00 brief
    # computes `wait_pullback_rebreak` once on completed bars, so a CRCL pullback
    # intraday was invisible to every subsequent slot.
    early_candidates = collect_early_trend_candidates(args.market)
    # Price-surface opportunity radar (#551): breakthrough / wait-rebreak /
    # near-breakout candidates, additive to the early-trend lane. Candidate rows
    # join the setups dimension so the delta gate surfaces their appearance.
    opportunity_radar = collect_opportunity_radar(args.market)
    # A cut's ammunition gets a same-leg destination (#555): the radar rows that
    # are not themselves flagged pair into the plan context, so the prose can
    # say what the money is for instead of ending at "sell".
    plan_ctx = attach_reinvest_candidates(
        plan_ctx, opportunity_radar, signals_detail)
    combined_setups = {
        'rows': (live_setups.get('rows') or [])
        + (early_candidates.get('rows') or [])
        + (opportunity_radar.get('rows') or []),
    }
    # Read provenance after the analyzer returns: its successful quote stamps
    # are later than the preflight start time, especially on a slow US run.
    coverage = quote_coverage(
        stdout, args.market,
        now=datetime.now(ZoneInfo('Asia/Hong_Kong')),
        started_at=now,
    )
    semantic_state = intraday_delta.semantic_state(
        args.market, intraday_delta.market_session_date(args.market, now),
        signals_detail=signals_detail,
        anomalies=anomalies, setups=combined_setups, plans=plan_ctx,
        active_information=active_information_ctx,
    )
    prior_doc = intraday_delta.load_delivered_state(WS, args.market)
    prior_state = prior_doc.get('state') if isinstance(prior_doc, dict) else {}
    semantic_delta = intraday_delta.compare_semantic_states(semantic_state, prior_state)
    unchanged = bool(prior_state) and not semantic_delta['changed']
    if unchanged:
        raw_block = render_unchanged_receipt(
            args.market, stdout.strip(), coverage, active_information_ctx,
        )
        delivery_mode = 'unchanged_receipt'
        # Persistent thresholds explain the stored state; they do not turn the
        # receipt back into another full alert.
        should_alert, alert_reasons = False, []
    else:
        raw_block = append_setup_section(stdout.strip(), live_setups, signals_detail)
        raw_block = append_early_trend_section(
            raw_block, early_candidates, signals_detail)
        raw_block = append_opportunity_radar_section(
            raw_block, opportunity_radar, signals_detail)
        raw_block = append_active_information_section(
            raw_block, active_information_ctx,
            event_ids=set(semantic_delta['changed_event_ids']),
        )
        delivery_mode = 'full_delta'

    result = {
        'status':           'ok',
        'market':           args.market,
        'date':             now.strftime('%Y-%m-%d'),
        'time':             now.strftime('%H:%M'),
        'generated_at':     now.isoformat(timespec='seconds'),
        'raw_wechat_block': raw_block,
        'delivery_mode': delivery_mode,
        'semantic_state': semantic_state,
        'semantic_delta': semantic_delta,
        'quote_coverage': coverage,
        'provisional_setups': live_setups,
        'early_trend_candidates': early_candidates,
        'opportunity_radar': opportunity_radar,
        'signal_count':     signals,
        'signals_detail':   signals_detail,
        'anomalies':        anomalies,
        'should_alert':     should_alert,
        'alert_reasons':    alert_reasons,
        't0_setups':        t0_setups,
        'peer_scan':        collect_peers(args.market),
        'plan_context':     plan_ctx,
        'mover_thesis':     mover_thesis,
        'mover_news':       mover_news_ctx,
        'active_information_candidates': active_information_ctx,
        'known_catalysts':  known_catalyst_ctx,
        'heartbeat':        {'job': heartbeat['job'], 'slot': heartbeat['slot']},
    }
    # Last field: the id digests everything above it, and the model echoes it to
    # postflight so prose can never be assembled onto a context that was
    # regenerated mid-turn. Must stay after the dict is otherwise complete.
    result['context_id'] = compute_context_id(result)

    cron_heartbeat.record(
        args.market, 'preflight_ok', job_name=heartbeat['job'],
        slot=heartbeat['slot'], should_alert=should_alert,
        anomaly_count=len(anomalies),
    )

    TMP.mkdir(parents=True, exist_ok=True)
    out_path = TMP / f'intraday-context-{args.market}-{stamp}.json'
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    # Also write latest pointer for postflight to pick up easily
    (TMP / f'intraday-context-{args.market}-latest.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
