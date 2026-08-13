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
from datetime import datetime
from pathlib import Path

from clawock.workspace import workspace_root
from clawock.market_data import sessions as trading_calendar
from clawock.decision import plans as plan_surface
from clawock.decision import signals as quant_signals
from clawock.evidence import research_surface
from clawock.cli import PACKAGED_UTILITIES
from clawock.market_data import known_catalysts, mover_evidence as mover_news, peer_scan

WS = workspace_root(Path.cwd())
TMP = WS / 'memory' / '.tmp'

from ._harness_common import compute_context_id

from clawock_kcnyu.automation import cron_heartbeat  # noqa: E402
from clawock_kcnyu import active_information  # noqa: E402


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
            region='HK' if market == 'hk' else 'US')
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


def append_active_information_section(block, active):
    """Make information-first candidates visible without relying on model prose."""
    rows = (active or {}).get('candidates') or []
    degraded = (active or {}).get('degraded_issuers') or []
    if not rows and not degraded:
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
    if degraded:
        lines.append(f"  ⚠️ 一级源降级：{','.join(degraded)}（不是无消息）")
    return block + '\n' + '\n'.join(lines)


def apply_active_information_alert(should_alert, reasons, active):
    """A primary event is alert-worthy even when no ticker has moved 3%."""
    rows = (active or {}).get('candidates') or []
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

    now = datetime.now()
    stamp = now.strftime('%Y-%m-%d_%H%M')
    heartbeat = cron_heartbeat.record(args.market, 'started')

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
        active_information_ctx = active_information.scan_workspace(args.market)
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
    raw_block = append_setup_section(stdout.strip(), live_setups, signals_detail)
    raw_block = append_active_information_section(raw_block, active_information_ctx)

    result = {
        'status':           'ok',
        'market':           args.market,
        'date':             now.strftime('%Y-%m-%d'),
        'time':             now.strftime('%H:%M'),
        'generated_at':     now.isoformat(timespec='seconds'),
        'raw_wechat_block': raw_block,
        'provisional_setups': live_setups,
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
