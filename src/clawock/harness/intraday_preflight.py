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

from clawock.harness import _harness_common
from clawock.harness._harness_common import run_analyze
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from clawock.workspace import workspace_root
from clawock.safe_io import safe_write_text
from clawock import sessions as trading_calendar
from clawock.decision import plans as plan_surface
from clawock.decision import signals as quant_signals
from clawock.evidence import research_surface
from clawock.utilities import PACKAGED_UTILITIES
from clawock.market_data import known_catalysts, mover_evidence as mover_news, peer_scan
from clawock.decision import active_information
from clawock.decision import add_side, early_trend, intraday_policy
from clawock.evidence import anomaly_search, intraday_information
from clawock.instruments import is_leveraged_holding

WS = workspace_root()
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


# 信号词表/读行/分段都在 _harness_common（#918：两个 preflight 曾各存一份，
# 且各自有盲区 —— 这边不认 US 的 `STOP-LOSS`，那边拿子串匹配把 `WATCHDOG`
# 读成 WATCH）。这里只保留名字，consumer 与测试引用的是这些。
SIGNAL_LEVELS = _harness_common.SIGNAL_LEVELS
read_signal_line = _harness_common.read_signal_line


def parse_signals(stdout):
    """`(counts, detail)` —— 实现在 _harness_common.parse_signal_lines。"""
    return _harness_common.parse_signal_lines(stdout)


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
        policy = _load_json(WS / 'config' / 'add-alpha-policy.json')
    except Exception:  # noqa: BLE001
        policy = {}
    rows = []
    run_date = datetime.now(trading_calendar.HKT).date()
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
    # #759: every name whose 20-day level is computable, in play or not. The
    # radar's own rows must keep carrying only the in-play states (they drive the
    # rendered section and the reinvest pairing), but a name 12% below its high
    # still has a level, and an add-side `wait` needs it to say what would settle
    # the question. Computed in this same pass — no extra fetch, no new threshold.
    levels = {}
    run_date = datetime.now(trading_calendar.HKT).date()
    # #621: thresholds come from add-alpha-policy.json like every other lane
    # (early_no_chase_zscore / opportunity_near_pct), so radar and early-trend
    # cannot drift apart when the config changes.
    try:
        radar_policy = _load_json(WS / 'config' / 'add-alpha-policy.json')
        # #649: explicit None checks, never `X or DEFAULT` — a config value of
        # 0 (e.g. `early_no_chase_zscore: 0` = z≥0 永不追高) is legal and must
        # not be swallowed into the default.
        raw_near = radar_policy.get("opportunity_near_pct")
        raw_z = radar_policy.get("early_no_chase_zscore")
        near_pct = float(raw_near) if raw_near is not None else OPPORTUNITY_NEAR_PCT
        no_chase_z = float(raw_z) if raw_z is not None else 2.0
    except (TypeError, ValueError):
        near_pct, no_chase_z = OPPORTUNITY_NEAR_PCT, 2.0
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
        # Keyed by the label alone, never by `source_holdings`: the universe
        # carries proxy indices or underlyings for leveraged holdings, and a
        # proxy's 20-day high is in a different price scale entirely. Telling a
        # 3.5 HKD warrant to 「站上 4948.5」(恒科指数点位) is worse than saying
        # nothing. A radar row may carry a proxy because the row names the index
        # it is about; a bare level has no such label, so it stays home.
        if label:
            levels.setdefault(label, {'prior_20d_high': prior, 'close': close,
                                      'pct_from_high': round(pct_from_high, 2),
                                      # The pullback read's invalidation (#contract §5).
                                      'prior_5d_low': sig.get('prior_5d_low')})
        # One definition, two readers (#819): `add_side.classify_level` is also
        # what the daily brief's close-confirmed radar calls, so a slot and a
        # brief cannot disagree about where the same name sits.
        classified = add_side.classify_level(close, prior, z,
                                             near_pct=near_pct,
                                             no_chase_z=no_chase_z)
        if classified is None:
            continue
        state, state_zh = classified
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
    result = {'rows': rows, 'levels': levels}
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


def partial_unchanged(active, state, prior):
    """Whether the SEC-mirror list equals the last delivered one this session.

    The mirror line appeared on 9 of the last 11 US sessions, 2–6 slots a day;
    printed every slot it dilutes the ⛔ that matters (kcn 2026-09-25). A first
    slot of the session, or any change in the list, still prints it whole.
    """
    partial = sorted((active or {}).get('partially_degraded_issuers') or [])
    prior = prior if isinstance(prior, dict) else {}
    if not partial or prior.get('session') != (state or {}).get('session'):
        return False
    return sorted(((prior.get('primary_source_health') or {}).get('partial')) or []) == partial


def append_active_information_section(block, active, *, event_ids=None,
                                      partial_unchanged=False):
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
    lines = ['', '📑 主动一级信息（候选≠下单）']
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
        lines.append(f"  ⛔ 一级源降级：{','.join(degraded)}（不是无消息）")
    if partial and partial_unchanged:
        # Same list as the last delivered card: one sentence, no △ line.
        quiet = not any(row.get('issuer') in partial for row in all_rows)
        lines.append(f"  · {'、'.join(partial)}：" + (
            '无新披露（SEC 直连降级已由镜像兜住；名单未变，不再逐档印）' if quiet
            else 'SEC 直连降级已由镜像兜住（名单未变，不再逐档印）'))
    elif partial:
        lines.append(
            f"  △ SEC直连降级、镜像已检查：{','.join(partial)}"
        )
    return block + '\n' + '\n'.join(lines)


def _quote_fetched_at(data_source, market, now):
    """Parse the per-holding provenance stamp written by this analysis run."""
    text = str(data_source or '')
    zone = trading_calendar.market_tz(market)
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
    now = now or datetime.now(trading_calendar.HKT)
    now = now if now.tzinfo else now.replace(tzinfo=trading_calendar.HKT)
    started_at = started_at or (now - timedelta(minutes=fresh_minutes))
    started_at = (
        started_at if started_at.tzinfo
        else started_at.replace(tzinfo=trading_calendar.HKT)
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


def always_full_intraday() -> bool:
    """Whether every open-market slot should send the full block.

    On (kcn 2026-09-25, the live setting): every slot sends the full card; an
    unchanged slot says so in its 变化 line and judgment. Off: the 2026-09-24
    behaviour, where a healthy unchanged slot is silent with an auditable
    heartbeat and exact-slot marker (`can_silence`, `render_unchanged_receipt`
    and the watchdog's quiet-marker check stay for that). Data/source
    degradation never silences either way. Missing or invalid config leaves
    the semantic gate enabled.

    `config/intraday-delivery.json`:  {"always_full": true}
    """
    try:
        doc = json.loads((WS / 'config' / 'intraday-delivery.json').read_text())
    except Exception:
        return False
    return doc.get('always_full') is True


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
        lines.append(f"⛔ 一级源降级：{','.join(degraded)}（不是无消息）")
    if partial:
        lines.append(f"△ 一级源部分降级、镜像已检查：{','.join(partial)}")
    return '\n'.join(lines)


DELTA_LABELS = {
    'session': '本交易日首档', 'breaches': '信号/触发档位',
    'setups': '机会形态', 'plans': '未成交计划',
    'primary_events': '一级披露', 'primary_source_health': '一级源状态',
    'regime': '组合风险档位', 'soft_candidates_seen': '边缘候选',
    'strategy_policies': '持仓策略口径', 'strategy_conflicts': '计划与策略冲突',
}


def delta_lead(delta, *, current, previous):
    """The 变化 line: why this slot is a full card, naming first-seen breaches."""
    if not previous:
        return '变化：本交易日首档，建立对照'
    if not delta.get('components'):
        # Only reachable with always_full on: say plainly that nothing changed
        # instead of the old '决策条件' fallback, which read as a change.
        return '变化：无（与上次送达相比，本档没有新条件）'
    labels = [DELTA_LABELS[key] for key in delta.get('components', [])
              if key in DELTA_LABELS]
    lead = '变化：' + '、'.join(labels or ['决策条件'])
    old = {json.dumps(row, sort_keys=True, ensure_ascii=False)
           for row in (previous.get('breaches_seen')
                       or previous.get('breaches') or [])}
    fresh = [row for row in current.get('breaches', [])
             if json.dumps(row, sort_keys=True, ensure_ascii=False) not in old]
    names = list(dict.fromkeys(str(row.get('ticker')) for row in fresh
                               if row.get('ticker')))
    if names:
        lead += '（新触发：' + '、'.join(names[:4]) + '）'
    return lead


def prepend_delta_lead(block, delta, *, current, previous):
    """Put the reason for a full card before the holdings table on both legs."""
    lines = block.splitlines()
    if not lines:
        return block
    return '\n'.join([lines[0], delta_lead(delta, current=current, previous=previous),
                      *lines[1:]])


def carry_quote_gap(coverage, previous, *, session, slot_time):
    """Stamp since when the same unverified names have been carried.

    `previous` is the last slot's written context (`-latest.json`, read before
    this slot overwrites it). The same names in the same session keep the
    earlier start, so a gap that lasts an evening reads as one fact with a
    start time instead of the same line reprinted every 30 minutes (kcn
    2026-09-25 preview). Contexts written before this field fall back to that
    slot's own time.
    """
    missing = sorted(coverage.get('unrefreshed') or [])
    if not missing:
        return coverage
    previous = previous if isinstance(previous, dict) else {}
    prior = previous.get('quote_coverage') or {}
    same = ((previous.get('semantic_state') or {}).get('session') == session
            and sorted(prior.get('unrefreshed') or []) == missing)
    since = (prior.get('unrefreshed_since') or previous.get('time')) if same else None
    return {**coverage, 'unrefreshed_since': since or slot_time,
            'unrefreshed_carried': bool(since)}


EVIDENCE_REASONS = (
    ('quote not freshly verified', '行情未证实刷新'),
    ('daily move unavailable', '今日涨跌缺失'),
    ('five-session bars unavailable or stale', '五日K线缺失或过期'),
    ('invalid five-session bars', '五日K线无效'),
    ('price or universe code unavailable', '价格或代码缺失'),
    ('not in instrument registry', '标的未登记'),
)


def evidence_gaps(errors, checks):
    """`policy_evidence_errors` per holding, in card words.

    Each error is `<ticker>: <reason>`; the ticker may be a rule's underlying,
    so `strategy_checks` maps it back to the holding whose add-side row it
    belongs on. Unknown reasons are kept verbatim rather than dropped.
    """
    owner = {row.get('ticker'): row.get('holding') for row in checks or []
             if row.get('ticker')}
    gaps = {}
    for error in errors or []:
        ticker, _, reason = str(error).partition(': ')
        word = next((cn for en, cn in EVIDENCE_REASONS if reason.startswith(en)), reason)
        holding = owner.get(ticker) or ticker
        label = word if holding == ticker else f'{ticker} {word}'
        gaps.setdefault(holding, [])
        if label not in gaps[holding]:
            gaps[holding].append(label)
    return gaps


def coverage_warning(coverage, gaps=None):
    """Block 4's quote line: the only ⛔ that bears on the whole table.

    One line, not three (kcn 2026-09-25): the names, since when they are
    carried, and — as a bare pointer — holdings whose strategy evidence is
    incomplete; the reason for those sits on their 🛰️ row.
    """
    missing = coverage.get('unrefreshed') or []
    parts = []
    if missing:
        since = coverage.get('unrefreshed_since')
        carried = f"，自 {since} 起" if coverage.get('unrefreshed_carried') and since else ''
        parts.append('、'.join(missing) + f' 行情未证实（沿用上一笔{carried}）')
    if gaps:
        parts.append('、'.join(gaps) + ' 策略升级证据未取全'
                     + ('' if missing else '（原因见 🛰️ 加仓侧）'))
    return DEGRADED + ' · '.join(parts) if parts else None


def prepend_coverage_warning(block, coverage):
    """A full card must disclose incomplete quotes, as the receipt already does."""
    warning = coverage_warning(coverage)
    if not warning:
        return block
    lines = block.splitlines()
    return '\n'.join([*lines[:2], warning, *lines[2:]])


# ── Card layout contract (2026-09-25, kcn: 「还是有点乱」) ──────────────────
#
# A full card reads top-down in this order; a block with nothing to say is
# omitted, never printed empty:
#
#   1 title          analyzer's first line — the watchdog's slot anchor
#   2 P0 line        only when a strategy escalation newly fired
#   3 变化 line      why this slot woke: components + first-seen tickers
#   4 ⛔ lines       data faults, each once: unverified quotes (with since
#                    when, `carry_quote_gap`) plus a pointer to holdings whose
#                    strategy evidence is incomplete; T+0, information, search
#   5 index + 📊     analyzer's market strip and book line
#   6 table          analyzer's holdings table, byte for byte
#   7 ↑ pointer      one line naming the rows with a new move/trigger;
#                    omitted when there is none (unverified rows are block 4's)
#   8 ⚠️ 信号        signals new today in full; ones already delivered this
#                    session fold into one 「今日已报、仍在」 line
#   9 candidates     setups / trend / radar / primary info / plan triggers
#  9b 🛰️ 加仓侧      `add_side_reads` per ticker: verdict copied, why/needs
#                    clipped, at most MAX_ADD_SIDE_ROWS (#755; the model's
#                    prose no longer has to carry it to reach kcn); a holding
#                    with incomplete strategy evidence gets its reason here
#  10 ▎我的看法      model judgment — postflight appends it after the whole
#                    data block, below the table (kcn 2026-09-25: #1863 had
#                    put it above the table and kcn read that as the table
#                    being out of place)
#  11 ℹ️ footnote    advisory checker findings, last (postflight)
#
# Why: the header (2–4) answers "what changed, can I trust it" before the
# table; the table keeps the position kcn reads it in. Marks sit next to the
# table instead of inside it: the table is the analyzer's and stays
# identical, and a mark inside a cell would also break Telegram's code-block
# alignment. ⛔ is only ever data health; ⚠️ is only the analyzer's signal
# header — one symbol, one meaning. Card only: the model reads the complete
# context (analyzer_block, signals_detail, full_holdings, …) regardless.
DEGRADED = '⛔ 数据降级：'
POINTER = '↑ '
# Unverified quotes are said once, in block 4 with their start time; the
# pointer no longer repeats them (kcn 2026-09-25: one fact, one line).
POINTER_KINDS = (('new', '新异动/触发'),)


def compose_card(block, *, p0_lines, lead, degraded):
    """Header blocks 2–4 in contract order under the analyzer's title."""
    lines = block.splitlines()
    if not lines:
        return block
    return '\n'.join([lines[0], *p0_lines, lead,
                      *[line for line in degraded if line], *lines[1:]])


def mark_card_changes(block, *, fresh_tickers, unrefreshed, seen_signals):
    """Point at the rows that matter and fold what was already said today.

    Never edits a table line. `fresh_tickers` are holdings with a
    move/trigger breach first seen this session; `seen_signals` are
    `(level, ticker)` signal identities delivered earlier this session.
    `unrefreshed` only keeps a stale row out of `new`: block 4 names it.
    """
    stale = [t for t in (unrefreshed or [])]
    fresh = [t for t in sorted(fresh_tickers or []) if t not in stale]
    out, folded = [], []
    in_signals = skip_reasons = False
    last_table_row = None
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            out.append(line)
            last_table_row = len(out)
            continue
        if stripped == '⚠️ 信号':
            in_signals = True
            out.append(line)
            continue
        if in_signals:
            if not stripped or stripped.startswith(('📉', '📰', '🕯️', '🎯', '🛰️', '📑', '⚡')):
                in_signals = False
                if folded:
                    out.append('  · 今日已报、仍在：' + '、'.join(folded))
                    folded = []
            else:
                if skip_reasons and stripped.startswith('·'):
                    continue
                skip_reasons = False
                level, ticker = read_signal_line(stripped)
                if level and (level, ticker) in seen_signals:
                    word = stripped.split()[1] if stripped.split()[0] in ('✋', '▼', '△', '▲') else level
                    folded.append(f'{word} {ticker}')
                    skip_reasons = True
                    continue
        out.append(line)
    if folded:
        out.append('  · 今日已报、仍在：' + '、'.join(folded))
    named = dict(POINTER_KINDS)
    parts = [f"{named[kind]} {'、'.join(rows)}"
             for kind, rows in (('new', fresh),) if rows]
    if parts and last_table_row is not None:
        # A blank line first: GFM reads a pipe-less line right under a table
        # as one more row.
        out[last_table_row:last_table_row] = ['', POINTER + '　'.join(parts)]
    return '\n'.join(out)


ADD_SIDE_HEADER = '🛰️ 加仓侧（三态都不是下单授权）'
ADD_SIDE_WORDS = {'candidate': '候选', 'wait': '等待', 'reject': '拒绝'}
MAX_ADD_SIDE_ROWS = 4
ADD_SIDE_WHY_CHARS = 44
ADD_SIDE_NEEDS_CHARS = 40


def _clip(text, limit):
    """Cut at `limit`, never inside a number: 「73.5…」 for 73.57 reads as a
    different price (2026-09-25 US 02:33 sample)."""
    text = str(text or '')
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if re.match(r'[\d.,%+-]', text[limit - 1]):
        cut = re.sub(r'[\d.,%+-]+$', '', cut)
    return cut.rstrip('(（:：,，;； ') + '…'


EVIDENCE_WAIT_WORD = '观望'


def append_add_side_section(block, reads, gaps=None):
    """Card block 10: the add-side read per ticker, rendered by the harness.

    `add_side_reads` was only in the model's context, and on 2026-08-17 a +6.4%
    move with three near-breakout rows produced prose about nothing but holdings
    (#755); the advisory check that followed only reminds. Printed here, the
    three-state read reaches kcn whatever the prose says, and the model cannot
    restate a verdict it does not write. Ticker and verdict are copied row by
    row; only `why`/`needs` are clipped, at a fixed length.

    `gaps` (`evidence_gaps`) is strategy evidence this slot could not
    complete. It only concerns those holdings, so it sits with them: under
    their row, or as a 观望 row of its own — not a fourth verdict, just
    「本档不给尺寸」 (kcn 2026-09-25 preview; the ⛔ line keeps a pointer).
    """
    rows = (reads or {}).get('rows') or []
    gaps = dict(gaps or {})
    if not rows and not gaps:
        return block
    lines = ['', ADD_SIDE_HEADER]
    for row in rows[:MAX_ADD_SIDE_ROWS]:
        word = ADD_SIDE_WORDS.get(row.get('verdict'), row.get('verdict'))
        text = f"  · {row.get('ticker')} {word}：{_clip(row.get('why'), ADD_SIDE_WHY_CHARS)}"
        if row.get('needs'):
            text += f" → {_clip(row.get('needs'), ADD_SIDE_NEEDS_CHARS)}"
        lines.append(text)
        if row.get('ticker') in gaps:
            lines.append(f"    ↳ 策略升级证据未取全（{'；'.join(gaps.pop(row['ticker']))}）")
    listed = {row.get('ticker') for row in rows}
    for ticker, reasons in gaps.items():
        # A ticker whose own row is past the cap has a verdict; don't relabel it.
        word = '' if ticker in listed else f' {EVIDENCE_WAIT_WORD}'
        lines.append(f"  · {ticker}{word}：策略升级证据未取全"
                     f"（{'；'.join(reasons)}）→ 本档不给尺寸")
    if len(rows) > MAX_ADD_SIDE_ROWS:
        lines.append(f'  …另有 {len(rows) - MAX_ADD_SIDE_ROWS} 条')
    return block + '\n' + '\n'.join(lines)


def _split_generic_news(block):
    card, feed = [], []
    in_news = False
    for line in block.splitlines():
        if line.strip() == '📰 新闻':
            in_news = True
            continue
        if in_news and line.startswith(('🎯', '🛰️', '⚠️', '📉', '📊', '🇭🇰', '🇺🇸')):
            in_news = False
        (feed if in_news else card).append(line)
    return '\n'.join(card).rstrip(), [line.strip() for line in feed if line.strip()]


def strip_generic_news(block):
    """Drop the analyzer's repeated, truncated headline feed from intraday cards.

    Mover-specific primary evidence stays in the structured context and the
    explicit active-information section. The generic feed has no newness gate.
    """
    return _split_generic_news(block)[0]


def generic_news_feed(block):
    """The headline lines `strip_generic_news` keeps out of the card.

    The card drops them, the model must not: `raw_wechat_block` was the only
    carrier, and `mover_news` covers only >=3% movers, so a soft candidate's or
    underlying's headline (the 2026-09-24 SPCX insider-sale line both replay
    models cited) left the model's view along with the WeChat copy.
    """
    return _split_generic_news(block)[1]


ACTION_CN = {
    'trim_on_rebound': '减仓', 'cut': '清仓', 'add_only_on_trigger': '加仓',
    'add_on_breakout': '突破加仓', 'hold_and_watch': '持有观察',
}


def append_plan_trigger_section(block, triggered):
    """Print the plan conditions this slot's quotes satisfy.

    Rendered rather than left in JSON alone, for the #515 reason: a detector
    whose finding nothing prints has been silenced. This one is the whole point
    of carrying `condition_price` at all — the model may or may not notice a
    number buried in the context, but a line in the block is in the message kcn
    reads.
    """
    if not triggered:
        return block
    lines = ['', '🎯 计划触发线已破（计划自己的价，不是新阈值）']
    for row in triggered[:6]:
        arrow = plan_surface.PRICE_CONDITIONS[row['condition']]
        action = ACTION_CN.get(row['action'], row['action'])
        status = '未执行' if row.get('execution_status') == 'unknown' else row.get('execution_status')
        shares = f"{row['shares']}股" if row.get('shares') else '—'
        # `open_since` before today is the whole point of the line: a trigger
        # met for the second session running is not news about the price, it is
        # news about the order.
        carried = ''
        if row.get('open_since') and row['open_since'] != row.get('plan_date'):
            carried = f"｜自 {row['open_since']} 起未执行"
        elif (row.get('restated_count') or 1) > 1:
            carried = f"｜已重挂 ×{row['restated_count']}"
        lines.append(
            f"  ◆ {row['ticker']} {action} {shares} | 触发 {arrow}{row['condition_price']:g}"
            f" | 现价 {row['last']:g}（破线 {row['through_pct']:+g}%）| {status}{carried}"
        )
    return block + '\n' + '\n'.join(lines)


def apply_plan_trigger_alert(should_alert, reasons, triggered):
    """A plan condition being met wakes the slot on its own.

    It has to: on 2026-09-07 the only anomaly all session was 00100 moving, and
    a move is not the same statement as "the trim you planned is now fillable".
    The trigger can also be satisfied on a quiet day the ≥3% gate never sees.
    """
    if not triggered:
        return should_alert, reasons
    named = ', '.join(dict.fromkeys(
        f"{row['ticker']} {plan_surface.PRICE_CONDITIONS[row['condition']]}"
        f"{row['condition_price']:g}" for row in triggered))
    return True, [*reasons, f'计划触发: {named}']


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
    """≥3% 异动行。实现在 _harness_common —— 两个 preflight 曾各存一份（#918）。"""
    return _harness_common.parse_holdings_anomalies(stdout)


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
        return {'_error': f'{type(e).__name__}: {e}'[:200]}


# ── Context layers (docs/architecture/intraday-agent.md §3) ──────────────────
#
# The core packet is what the model is printed; the reference layer is the rest
# of the same context, one named call away. Split by whether a field can change
# this slot's judgment or mostly dilutes attention — not by size: plans, the
# analyzer's own output, add-side reads and mover evidence stay in the core
# however large. Nothing is dropped. The #1839 whitelist lost zero-share plans
# and signal provenance with no way back; every entry here is listed in the
# packet's index and fetched by name (`intraday_reference` tool), and a test
# holds core ∪ references to the whole context.
from clawock.context.intraday_layers import REFERENCE_ENTRIES, REFERENCE_TOOL  # noqa: E402


def _reference_tickers(value):
    """Tickers a reference entry can be sliced by, for the index."""
    found = []

    def add(name):
        if isinstance(name, str) and name and name not in found:
            found.append(name)

    def rows_of(obj):
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            return obj.get('rows') if isinstance(obj.get('rows'), list) else []
        return []

    for row in rows_of(value):
        if isinstance(row, dict):
            add(row.get('ticker') or row.get('label'))
    for container in (value, (value or {}).get('rows') if isinstance(value, dict) else None):
        if isinstance(container, dict):
            for key, item in container.items():
                if isinstance(item, dict) and re.fullmatch(r'[A-Z0-9]{2,6}', str(key)):
                    add(key)
    return found


def reference_index(ctx):
    """One line per reference entry: what it is, how big, how to fetch it."""
    market, context_id = ctx.get('market'), ctx.get('context_id')
    refs = []
    for name, about in REFERENCE_ENTRIES.items():
        if name not in ctx:
            continue
        value = ctx[name]
        refs.append({
            'name': name, 'about': about,
            'bytes': len(json.dumps(value, ensure_ascii=False).encode()),
            'tickers': _reference_tickers(value)[:12],
            'fetch': (f'clawock tool {REFERENCE_TOOL} --arg market={market} '
                      f'--arg context_id={context_id} --arg entry={name}'),
        })
    return refs


def judgment_packet(ctx):
    """The core packet: every field that can change this slot's judgment, plus
    the index that makes the rest addressable. Brevity belongs to delivery;
    this only moves attention-diluting detail one named call away."""
    prior = ctx.get('prior_semantic_state') or {}
    index = {
        'context_id': ctx.get('context_id'),
        'slot': (ctx.get('heartbeat') or {}).get('slot'),
        'generated_at': ctx.get('generated_at'),
        'last_delivered': {'session': prior.get('session'),
                           'breaches_seen': len(prior.get('breaches_seen') or [])},
        'references': reference_index(ctx),
        'slice': ('参考层用 fetch 命令取整份；加 --arg ticker=<代码> 只取一只票，'
                  '加 --arg since=HH:MM 只取该时刻之后的条目'),
    }
    return {'index': index,
            **{key: value for key, value in ctx.items() if key not in REFERENCE_ENTRIES}}


def can_silence(ctx, *, allow_soft_review=False):
    """Only a proved healthy, unchanged slot may omit user delivery.

    Not the default path: kcn overturned the 2026-09-24 silence contract on
    2026-09-25 (「全部都正常发」). `always_full` is on and short-circuits this to
    False; the silence code runs only if that config is explicitly set to
    false. Data/source degradation refuses silence either way.
    """
    soft_only = (ctx.get('semantic_delta') or {}).get('components') == ['soft_candidates_seen']
    if (not ctx.get('semantic_unchanged') and not (allow_soft_review and soft_only)):
        return False
    if ctx.get('always_full'):
        return False
    coverage = ctx.get('quote_coverage') or {}
    if (not coverage.get('active') or coverage.get('active') != coverage.get('refreshed')
            or coverage.get('unrefreshed')):
        return False
    active = ctx.get('active_information_candidates') or {}
    if (active.get('error') or active.get('policy_evidence_error')
            or active.get('degraded_issuers') or active.get('partially_degraded_issuers')):
        return False
    if (ctx.get('peer_scan') or {}).get('_error'):
        return False
    if ctx.get('policy_evidence_errors'):
        return False
    if (ctx.get('t0_setups') or {}).get('error'):
        return False
    if ctx.get('information_degraded'):
        return False
    if (ctx.get('plan_context') or {}).get('error'):
        return False
    mover = ctx.get('mover_news') or {}
    if (mover.get('halts') or {}).get('status') == 'degraded':
        return False
    if any((row or {}).get('status') == 'degraded'
           for row in (mover.get('tickers') or {}).values()):
        return False
    if any((ctx.get(name) or {}).get('errors') for name in
           ('provisional_setups', 'early_trend_candidates', 'opportunity_radar')):
        return False
    return True


def decision_sweep(stdout, coverage, plan_context, radar, t0_setups):
    """Expose every holding and soft candidates before the model sets its agenda.

    The 3% anomaly gate remains a guaranteed alert floor. A 1.5–3% move,
    approach within 3% of the existing 20-day radar level, or zscore >=1.5
    enters the candidate lane. Stable candidate identities, not raw prices,
    participate in semantic deduplication.
    """
    missing = set(coverage.get('unrefreshed') or [])
    plans = (plan_context or {}).get('open') or []
    holdings, candidates = [], []
    for row in _harness_common.parse_holdings_rows(stdout):
        ticker, price, move = row.get('ticker'), row.get('price'), row.get('move_pct')
        lines = [p for p in plans if p.get('ticker') == ticker
                 and isinstance(p.get('condition_price'), (int, float))]
        distances = [{
            'decision_id': p.get('decision_id'), 'condition_price': p['condition_price'],
            'pct_to_trigger': round((p['condition_price'] / price - 1) * 100, 2),
        } for p in lines if isinstance(price, (int, float)) and price > 0]
        holdings.append({'ticker': ticker, 'price': price, 'pct_1d': move,
                         'quote_fresh': bool(coverage.get('refreshed'))
                         and ticker not in missing,
                         'plan_distances': distances})
        if (holdings[-1]['quote_fresh'] and isinstance(move, (int, float))
                and 1.5 <= abs(move) < 3):
            candidates.append({'ticker': ticker, 'kind': 'soft_move',
                               'pct_1d': move,
                               'band': '2.5-3' if abs(move) >= 2.5 else '1.5-2.5'})
    levels = (radar or {}).get('levels') or {}
    for label, level in levels.items():
        pct = level.get('pct_from_high')
        if isinstance(pct, (int, float)) and -3 <= pct <= 0:
            candidates.append({'ticker': label, 'kind': 'near_20d_high',
                               'pct_from_high': pct,
                               'price_owner': label})
    for row in (radar or {}).get('rows') or []:
        z = row.get('zscore20')
        if isinstance(z, (int, float)) and z >= 1.5:
            candidates.append({'ticker': row.get('label'), 'kind': 'zscore_watch',
                               'zscore20': z, 'price_owner': row.get('label')})
    for ticker, row in ((t0_setups or {}).get('rows') or {}).items():
        if (row.get('grade_label') not in (None, '中性')
                and any(h['ticker'] == ticker for h in holdings)):
            candidates.append({'ticker': ticker, 'kind': 't0_quality',
                               'grade': row.get('grade_label'),
                               'range_pos': row.get('range_pos')})
    return holdings, candidates


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--judgment-packet', action='store_true')
    args = parser.parse_args(argv)

    now = datetime.now(trading_calendar.HKT)
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
        safe_write_text(str(TMP / f'intraday-context-{args.market}-{stamp}.json'), payload)
        # Also refresh -latest.json (the watchdog reads it) so it sees a clean
        # market_closed instead of yesterday's stale block.
        safe_write_text(str(TMP / f'intraday-context-{args.market}-latest.json'), payload)
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
        safe_write_text(str(TMP / f'intraday-context-{args.market}-{stamp}.json'),
                        json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    source_signals, source_signals_detail = parse_signals(stdout)
    holding_policies = intraday_policy.load(WS, args.market)
    signals, signals_detail = intraday_policy.actionable_signals(
        source_signals, source_signals_detail, holding_policies)
    anomalies = parse_anomalies(stdout)

    # T+0 牌面评级 — analyze_*_stocks 刚刷过价，此处用实时区间位算追高检测。
    # 零额外请求（T0_INTRADAY 默认关）。失败不阻断盯盘。
    t0_setups = {}
    try:
        # Same interpreter, not a bare name: under cron PATH is /usr/bin:/bin and
        # the launcher lives in ~/.local/bin, so `clawock` does not resolve (#438,
        # #443). Here the except swallows it, which is exactly how a dead call
        # stays invisible.
        t0_run = subprocess.run([sys.executable, '-m', PACKAGED_UTILITIES['t0']],
                                capture_output=True, text=True, timeout=45, check=False)
        t0_path = WS / 'assets' / 'data' / 't0_setups.json'
        if t0_run.returncode != 0:
            t0_setups = {'error': f'T+0 collector exit {t0_run.returncode}'}
        elif t0_path.exists():
            t0_setups = json.loads(t0_path.read_text())
        else:
            t0_setups = {'error': 'T+0 result missing'}
    except Exception as exc:
        t0_setups = {'error': f'T+0 collector {type(exc).__name__}: {exc}'[:200]}

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

    # Tier 3 (contract §6): one web search per mover per session, only when
    # something moved; the cache serves every later slot of the same session.
    anomaly_search_ctx = {}
    if anomalies:
        movers = [a['ticker'] for a in anomalies]
        try:
            anomaly_search_ctx = anomaly_search.search_anomalies(
                WS, args.market, intraday_delta.market_session_date(args.market, now),
                anomalies, names=mover_news.holding_names(movers),
                targets={t: mover_news.probe_targets(t, args.market) for t in movers})
        except Exception as exc:  # noqa: BLE001 — enrichment never reds a slot
            anomaly_search_ctx = {t: {'status': 'unavailable', 'items': [],
                                      'reason': type(exc).__name__} for t in movers}

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
    strategy_conflicts = intraday_policy.plan_conflicts(holding_policies, plan_ctx)
    # Does this slot's tape satisfy any condition the 08:00 plan wrote down?
    # Deterministic and harness-owned: the plan already named the price, so the
    # comparison is arithmetic, not judgement. Leaving it to the model is how
    # 2026-09-07 ended with eight slots of 「跳空/异动」 and a trim trigger blown
    # by 7.7% that nobody said out loud.
    plan_triggers = plan_surface.triggered_conditions(
        plan_ctx,
        {row['ticker']: row['price']
         for row in _harness_common.parse_holdings_rows(stdout)
         if row.get('price') is not None},
    )
    combined_setups = {
        'rows': (live_setups.get('rows') or [])
        + (early_candidates.get('rows') or [])
        + (opportunity_radar.get('rows') or []),
    }
    # Read provenance after the analyzer returns: its successful quote stamps
    # are later than the preflight start time, especially on a slow US run.
    coverage = quote_coverage(
        stdout, args.market,
        now=datetime.now(trading_calendar.HKT),
        started_at=now,
    )
    full_holdings, soft_candidates = decision_sweep(
        stdout, coverage, plan_ctx, opportunity_radar, t0_setups)
    prices = {row['ticker']: row['price'] for row in
              _harness_common.parse_holdings_rows(stdout) if row.get('price') is not None}
    # Information lane (contract §6): the morning files, read not refetched,
    # each item labelled with its time; plus one market-level 7x24 fetch.
    # Keyed by holding and by the issuer a fund looks through to (RKLX → RKLB).
    info_tickers = [row['ticker'] for row in full_holdings if row.get('ticker')]
    for ticker in list(info_tickers):
        issuer = mover_news.probe_targets(ticker, args.market).get('issuer')
        if issuer and issuer not in info_tickers:
            info_tickers.append(issuer)
    try:
        information = intraday_information.collect(WS, args.market, info_tickers)
    except Exception as exc:  # noqa: BLE001 — a colour lane must never red a slot
        information = {'summary': {}, 'full': {},
                       'degraded': [f'资讯汇总（{type(exc).__name__}）']}
    try:
        universe = quant_signals.universe_details()
    except Exception as exc:
        universe = []
        active_information_ctx['policy_evidence_error'] = f'{type(exc).__name__}: {exc}'[:200]
    policy_evidence_errors = []
    strategy_checks = []
    policy_escalations = intraday_policy.escalations(
        holding_policies, anomalies, coverage, prices, universe,
        _fetch_bars_cached, intraday_delta.market_session_date(args.market, now),
        errors=policy_evidence_errors, checks=strategy_checks,
        daily_moves={row['ticker']: row.get('pct_1d') for row in full_holdings})
    if policy_escalations:
        should_alert = True
        alert_reasons.append('策略升级条件')
    # The add-side read over the three lanes below (#755). They were all
    # computed and none of them reached the prose; the card now prints it
    # (block 10) and the model reads the same rows.
    add_side_reads = add_side.read_rows(
        anomalies=anomalies, radar=opportunity_radar,
        levels=opportunity_radar.get('levels'),
        early_trend=early_candidates, mover_news=mover_news_ctx,
        mover_thesis=mover_thesis, plan_context=plan_ctx,
        # Contract §5: graded news support, the leveraged sleeve, and the
        # exploration tranche the desk configured (quoted as the size cap).
        information=information['summary'],
        leveraged={row['ticker'] for row in full_holdings
                   if is_leveraged_holding({'ticker': row['ticker']})},
        policy=_load_json(WS / 'config' / 'add-alpha-policy.json'))
    semantic_state = intraday_delta.semantic_state(
        args.market, intraday_delta.market_session_date(args.market, now),
        signals_detail=signals_detail,
        anomalies=anomalies, setups=combined_setups, plans=plan_ctx,
        active_information=active_information_ctx,
        plan_triggers=plan_triggers,
    )
    semantic_state['strategy_policies'] = holding_policies
    semantic_state['strategy_conflicts'] = strategy_conflicts
    for row in policy_escalations:
        semantic_state['breaches'].append({
            'ticker': row['ticker'], 'kind': 'strategy_escalation',
            'level': f"{row['window']}:{row['threshold_pct']}",
        })
    prior_doc = intraday_delta.load_delivered_state(WS, args.market)
    prior_state = (prior_doc.get('state') or {}) if isinstance(prior_doc, dict) else {}
    current_soft = [{key: row.get(key) for key in ('ticker', 'kind', 'band')
                     if row.get(key) is not None} for row in soft_candidates]
    old_soft = (prior_state.get('soft_candidates_seen') or []
                if prior_state.get('session') == semantic_state.get('session') else [])
    semantic_state['soft_candidates_seen'] = sorted(
        {json.dumps(row, sort_keys=True, ensure_ascii=False): row
         for row in [*old_soft, *current_soft]}.values(),
        key=lambda row: json.dumps(row, sort_keys=True))
    # Same rule for breaches: a ticker sitting on a bucket edge (07226 at -5%
    # on 2026-09-25 flipped move medium/high and STOP/WATCH every slot) must
    # not re-wake a full card for a state kcn already got this session. Only
    # an identity first seen today counts; the current set stays for audit.
    old_breaches = ((prior_state.get('breaches_seen') or prior_state.get('breaches') or [])
                    if prior_state.get('session') == semantic_state.get('session') else [])
    semantic_state['breaches_seen'] = sorted(
        {json.dumps(row, sort_keys=True, ensure_ascii=False): row
         for row in [*old_breaches, *semantic_state['breaches']]}.values(),
        key=lambda row: json.dumps(row, sort_keys=True))
    semantic_delta = intraday_delta.compare_semantic_states(semantic_state, prior_state)
    # Since when the same names have been unverified: the previous slot's
    # context, read before this slot overwrites `-latest.json`.
    coverage = carry_quote_gap(
        coverage, _load_json(TMP / f'intraday-context-{args.market}-latest.json'),
        session=semantic_state.get('session'), slot_time=now.strftime('%H:%M'))
    # The delta is still computed and still stored when the gate is off: the
    # delivered-state cursor has to keep advancing, or flipping the toggle back
    # would compare against a months-old state and send one bogus full slot.
    always_full = always_full_intraday()
    peer_context = collect_peers(args.market)
    silence_context = {
        'semantic_unchanged': bool(prior_state) and not semantic_delta['changed'],
        'semantic_delta': semantic_delta,
        'always_full': always_full, 'quote_coverage': coverage,
        'active_information_candidates': active_information_ctx,
        'provisional_setups': live_setups,
        'early_trend_candidates': early_candidates,
        'opportunity_radar': opportunity_radar,
        'peer_scan': peer_context,
        'policy_evidence_errors': policy_evidence_errors,
        'plan_context': plan_ctx,
        'mover_news': mover_news_ctx,
        't0_setups': t0_setups,
        'information_degraded': [*information['degraded'],
                                 *anomaly_search.degraded_lines(anomaly_search_ctx)],
    }
    unchanged = can_silence(silence_context)
    soft_review = can_silence(silence_context, allow_soft_review=True) and not unchanged
    card_marks = {'new': [], 'stale': []}
    if unchanged:
        raw_block = render_unchanged_receipt(
            args.market, stdout.strip(), coverage, active_information_ctx)
        delivery_mode = 'no_change'
        # Persistent thresholds explain the stored state; they do not turn the
        # receipt back into another full alert.
        should_alert, alert_reasons = False, []
    else:
        raw_block = append_setup_section(
            strip_generic_news(stdout.strip()), live_setups, signals_detail)
        raw_block = append_early_trend_section(
            raw_block, early_candidates, signals_detail)
        raw_block = append_opportunity_radar_section(
            raw_block, opportunity_radar, signals_detail)
        raw_block = append_active_information_section(
            raw_block, active_information_ctx,
            event_ids=set(semantic_delta['changed_event_ids']),
            partial_unchanged=partial_unchanged(
                active_information_ctx, semantic_state, prior_state),
        )
        raw_block = append_plan_trigger_section(raw_block, plan_triggers)
        raw_block = intraday_policy.strip_suppressed_signal_lines(
            raw_block, holding_policies)
        # After the policy strip: that pass reads '·' lines as signal reasons.
        gaps = evidence_gaps(policy_evidence_errors, strategy_checks)
        raw_block = append_add_side_section(raw_block, add_side_reads, gaps)
        prior_escalations = {(row.get('ticker'), row.get('level'))
                             for row in [*prior_state.get('breaches', []), *old_breaches]
                             if row.get('kind') == 'strategy_escalation'}
        p0_lines = []
        for row in policy_escalations:
            identity = (row['ticker'], f"{row['window']}:{row['threshold_pct']}")
            if identity not in prior_escalations:
                window = '单日' if row['window'] == 'session' else '五交易日'
                p0_lines.append(f"P0：{row['ticker']} {window} {row['move_pct']:+.1f}%，"
                                f"{row['holding']} 策略是否继续？")
        seen_before = {json.dumps(row, sort_keys=True, ensure_ascii=False)
                       for row in old_breaches}
        fresh_tickers = {row['ticker'] for row in semantic_state['breaches']
                         if row.get('kind') in ('move', 'plan_trigger', 'strategy_escalation')
                         and json.dumps(row, sort_keys=True, ensure_ascii=False)
                         not in seen_before}
        # For postflight: WeChat bolds the `new` rows (the ↑ line); `stale`
        # is the ⛔ line's names, kept for audit.
        card_marks = {
            'new': sorted(t for t in fresh_tickers
                          if t not in (coverage.get('unrefreshed') or [])),
            'stale': list(coverage.get('unrefreshed') or []),
        }
        raw_block = mark_card_changes(
            raw_block,
            fresh_tickers=fresh_tickers,
            unrefreshed=coverage.get('unrefreshed'),
            seen_signals={(row.get('level'), row.get('ticker')) for row in old_breaches
                          if row.get('kind') == 'signal'})
        raw_block = compose_card(
            raw_block, p0_lines=p0_lines,
            lead=delta_lead(semantic_delta, current=semantic_state, previous=prior_state),
            degraded=[
                coverage_warning(coverage, gaps),
                (f"{DEGRADED}T+0 牌面未取到：{t0_setups['error']}"
                 if t0_setups.get('error') else None),
                (DEGRADED + '资讯源未取到：' + '、'.join(information['degraded'])
                 + '（不是无消息）' if information['degraded'] else None),
                (DEGRADED + '异动检索：' + '、'.join(anomaly_search.degraded_lines(
                    anomaly_search_ctx)) + '（不是无消息）'
                 if anomaly_search.degraded_lines(anomaly_search_ctx) else None),
            ])
        should_alert, alert_reasons = apply_plan_trigger_alert(
            should_alert, alert_reasons, plan_triggers)
        delivery_mode = 'review_candidate' if soft_review else 'full_delta'

    result = {
        'status':           'ok',
        'market':           args.market,
        'date':             now.strftime('%Y-%m-%d'),
        'time':             now.strftime('%H:%M'),
        'generated_at':     now.isoformat(timespec='seconds'),
        'raw_wechat_block': raw_block,
        # `new` move/trigger rows (the ↑ line; WeChat bolds them, Telegram
        # keeps the plain table) and `stale` quote rows (named by ⛔).
        'card_marks': card_marks,
        'delivery_mode': delivery_mode,
        # Auditable: a full block on a slot the delta called unchanged is the
        # toggle at work, not the delta misfiring.
        'always_full': always_full,
        'semantic_unchanged': bool(prior_state) and not semantic_delta['changed'],
        'semantic_state': semantic_state,
        'semantic_delta': semantic_delta,
        'quote_coverage': coverage,
        'full_holdings': full_holdings,
        # Model-only: the card drops this feed (no newness gate, truncated), the
        # judgment keeps it as background — see `generic_news_feed`.
        'headline_feed': generic_news_feed(stdout),
        # Model-only: the analyzer's output exactly as printed. The card folds
        # signals already delivered today (and their reason lines) and drops
        # the headline feed; the judgment must still see all of it.
        'analyzer_block': stdout.strip(),
        'soft_candidates': soft_candidates,
        # Information lane summary (core) and the whole of it (reference).
        'information': information['summary'],
        'information_full': information['full'],
        # The delivered state this slot was compared against (reference layer).
        'prior_semantic_state': prior_state,
        'provisional_setups': live_setups,
        'early_trend_candidates': early_candidates,
        'opportunity_radar': opportunity_radar,
        # Printed on the card as block 10 (`append_add_side_section`).
        'add_side_reads': add_side_reads,
        # Carried on BOTH paths, receipt included: the JSON is the audit trail
        # for what the slot knew, and a receipt slot that knew a trigger was
        # still live must not read later as a slot that did not check.
        'plan_triggers':    plan_triggers,
        'signal_count':     signals,
        'signals_detail':   signals_detail,
        'source_signals_detail': source_signals_detail,
        'strategy_escalations': policy_escalations,
        'strategy_checks': strategy_checks,
        'policy_evidence_errors': policy_evidence_errors,
        'holding_policies': holding_policies,
        'anomalies':        anomalies,
        'should_alert':     should_alert,
        'alert_reasons':    alert_reasons,
        't0_setups':        t0_setups,
        'peer_scan':        peer_context,
        'plan_context':     plan_ctx,
        'strategy_conflicts': strategy_conflicts,
        # The lines the 08:00 plan set for the book and the indices. Carried,
        # not evaluated — see `plan_surface.watch_levels` for why the arithmetic
        # `plan_triggers` does on a decision's price cannot be done on these.
        'watch_levels':     plan_surface.watch_levels(),
        'mover_thesis':     mover_thesis,
        'mover_news':       mover_news_ctx,
        # Web search for this slot's movers (cached per session): each hit is
        # {title, url, one_liner, grade}; unavailable/empty is on the card.
        'anomaly_search':   anomaly_search_ctx,
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
    safe_write_text(str(out_path), json.dumps(result, ensure_ascii=False, indent=2))

    # Also write latest pointer for postflight to pick up easily
    safe_write_text(str(TMP / f'intraday-context-{args.market}-latest.json'),
                    json.dumps(result, ensure_ascii=False, indent=2))

    print(json.dumps(judgment_packet(result) if args.judgment_packet else result,
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
