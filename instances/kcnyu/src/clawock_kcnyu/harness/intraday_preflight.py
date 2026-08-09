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
from clawock import known_catalysts, peer_scan, plan_surface, trading_calendar
from clawock.evidence import research_surface

WS = workspace_root(Path.cwd())
DATA_DIR = WS / 'scripts' / 'data'
TMP = WS / 'memory' / '.tmp'

from ._harness_common import compute_context_id

sys.path.insert(0, str(DATA_DIR))
import cron_heartbeat  # noqa: E402
import mover_news  # noqa: E402


def run_analyze(market):
    script = DATA_DIR / f'analyze_{market}_stocks.py'
    try:
        r = subprocess.run(
            ['python3', str(script), '--wechat', '--md-table'],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, '', str(e)


def parse_signals(stdout):
    counts = {'watch': 0, 'stop': 0, 'trim': 0}
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
            if 'WATCH' in s:
                counts['watch'] += 1
                signals_detail.append({'level': 'WATCH', 'line': s})
            elif 'STOP' in s:
                counts['stop'] += 1
                signals_detail.append({'level': 'STOP', 'line': s})
            elif 'TRIM' in s:
                counts['trim'] += 1
                signals_detail.append({'level': 'TRIM', 'line': s})
    return counts, signals_detail


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
        subprocess.run(['clawock', 't0'],
                       capture_output=True, text=True, timeout=45, check=False)
        t0_path = WS / 'assets' / 'data' / 't0_setups.json'
        if t0_path.exists():
            t0_setups = json.loads(t0_path.read_text())
    except Exception:
        pass

    total_signals = signals['watch'] + signals['stop'] + signals['trim']
    should_alert = (len(anomalies) > 0) or (total_signals >= 2) or (signals['stop'] > 0)

    alert_reasons = []
    if anomalies:
        tickers = ', '.join(f"{a['ticker']} ({a['move_pct']:+.1f}%)" for a in anomalies)
        alert_reasons.append(f'异动: {tickers}')
    if signals['stop'] > 0:
        alert_reasons.append(f'STOP 信号 ×{signals["stop"]}')
    if total_signals >= 2:
        alert_reasons.append(f'多重信号 (W{signals["watch"]} S{signals["stop"]} T{signals["trim"]})')

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

    result = {
        'status':           'ok',
        'market':           args.market,
        'date':             now.strftime('%Y-%m-%d'),
        'time':             now.strftime('%H:%M'),
        'generated_at':     now.isoformat(timespec='seconds'),
        'raw_wechat_block': stdout.strip(),
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
