#!/usr/bin/env python3
"""
report_preflight.py — Mode 6 (briefing) harness preflight.

Runs deterministic work for the 6 briefing crons:
  HK: 开盘 09:30 / 午盘 12:00 / 午后 13:30 / 收盘 16:00
  US: 开盘 09:30 ET / 收盘 16:00 ET (runtime schedules are expressed in HKT)

Each invocation:
  1. Runs analyze_{hk,us}_stocks.py --wechat (refreshes prices, writes portfolio.json)
  2. Captures full script output (LLM uses this VERBATIM as the data block)
  3. Parses signals (WATCH/STOP/TRIM counts) and direction hints
  4. Detects anomalies (≥3% intraday moves, big floating losses)
  4b. Collects peer/rotation data so the 板块全景 section has real numbers
  5. Writes memory/.tmp/report-context-{market}-{phase}-{date}.json, where {date}
     is the RUN date (not the market-session date), drops this market+phase's
     contexts from every other date, and prints the absolute path as the final
     stdout line (`context_path: ...`) — Step 2 must read THAT path, never a
     reconstructed filename.

Output keys:
  raw_wechat_block:   str (script stdout, paste verbatim)
  market:             "hk" | "us"
  phase:              "open" | "mid" | "pm" | "close"
  title:              suggested WeChat title
  commit_msg:         git commit message suffix
  signal_count:       {watch, stop, trim}
  anomalies:          list of {ticker, move_pct, reason}
  index_direction:    {hk_index_pct, hstech_pct} for HK; null for US
  peer_scan:          {ticker: {theme, listed_peers[], divergence_signal, ...}}
                      for this market's active holdings (板块全景 section)
  needs_risk_section: bool (true if STOP+TRIM >= 2)
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Workspace root, resolved from this file's location (location-independent;
# matches the old hardcoded /root path locally, robust if run elsewhere).
WS = Path(__file__).resolve().parents[2]
DATA_DIR = WS / 'scripts' / 'data'
TMP = WS / 'memory' / '.tmp'

sys.path.insert(0, str(DATA_DIR))
import trading_calendar  # noqa: E402
import peer_scan  # noqa: E402


def _market_closed_reason(market, phase):
    """None if the market trades now; else short reason (holiday/weekend)."""
    session = trading_calendar.phase_session(market, phase)
    return trading_calendar.closed_reason(market, session=session)


def context_path(market, phase, date):
    return TMP / f'report-context-{market}-{phase}-{date}.json'


def drop_stale_contexts(market, phase, today):
    """Delete this market+phase's context files from any OTHER date.

    WHY (2026-07-24 美股收盘报告): the cron payload names the file as
    `report-context-us-close-{date}.json` and the agent resolved `{date}` to the
    *market close* date (07/23) instead of the *run* date (07/24). Yesterday's
    leftover context sat at exactly that name, so the read succeeded and a
    day-old portfolio was written into the report and pushed to WeChat. Nothing
    reads a past-date context (postflight/watchdog both key on today), so the
    leftovers are pure footgun ammunition: with them gone, the same mistake is a
    loud `FileNotFoundError` instead of silently stale numbers.

    Retention would not help — the file that got misread was one day old.
    """
    dropped = []
    for path in TMP.glob(f'report-context-{market}-{phase}-*.json'):
        if path.name != context_path(market, phase, today).name:
            try:
                path.unlink()
                dropped.append(path.name)
            except OSError as e:
                print(f'   ⚠️  stale context cleanup failed for {path.name}: {e}',
                      file=sys.stderr)
    if dropped:
        print(f'   🧹 dropped {len(dropped)} stale context file(s): {", ".join(sorted(dropped))}',
              file=sys.stderr)
    return dropped


def announce_context_path(out_path):
    """Print the canonical context path as the FINAL stdout line.

    WHY: the agent pipes preflight through `| tail -80` (the JSON is ~350 lines
    with peer_scan), which cut off the `date` field and left it guessing the
    filename — see drop_stale_contexts. Printing the absolute path last means it
    survives any `tail`, so Step 2 never has to reconstruct the name.
    """
    print(f'context_path: {out_path}')


TITLE_TEMPLATES = {
    ('hk', 'open'):  '📊 港股开盘快报｜{date} 09:30',
    ('hk', 'mid'):   '☕ 港股午盘快报｜{date} 12:00',
    ('hk', 'pm'):    '🌤 港股午后快报｜{date} 13:30',
    ('hk', 'close'): '🔔 港股收盘日报｜{date}',
    ('us', 'open'):  '🌅 美股开盘快报｜{date} 09:30 ET',
    ('us', 'close'): '🌙 美股收盘日报｜{date}',
}

COMMIT_PHASE_CN = {
    'open': '开盘', 'mid': '午盘', 'pm': '午后', 'close': '收盘',
}


def run_analyze(market):
    script = DATA_DIR / f'analyze_{market}_stocks.py'
    try:
        r = subprocess.run(
            ['python3', str(script), '--wechat', '--md-table'],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', 'analyze script timeout (120s)'
    except Exception as e:
        return -1, '', f'analyze script error: {e}'


def parse_signals(stdout):
    """Count WATCH/STOP/TRIM markers in the signals section."""
    counts = {'watch': 0, 'stop': 0, 'trim': 0}
    in_signals = False
    for line in stdout.splitlines():
        if '⚠️ 信号' in line or '信号' == line.strip():
            in_signals = True
            continue
        if in_signals:
            if line.startswith('📉') or line.startswith('📰') or not line.strip():
                if line.startswith('📉') or line.startswith('📰'):
                    break
                continue
            if 'WATCH' in line:
                counts['watch'] += 1
            elif 'STOP' in line:
                counts['stop'] += 1
            elif 'TRIM' in line:
                counts['trim'] += 1
    return counts


def parse_anomalies(stdout):
    """Find tickers with ≥3% intraday move from md-table holdings rows.

    Row shape (7 cols, both markets, since 2026-05-21):
      HK: `| 00100 | 60 | 822.83 | 722.00 | +5.1% | -12.2% | -6,050 |`
      US: `| RKLB |  5 |  71.00 | 134.28 | +0.0% | +89.1% |   +316 |`
    Cell[0]=ticker, [1]=shares, [2]=cost, [3]=price, [4]=today%,
    [5]=pnl%, [6]=pnl_abs ($).
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
        direction = 1 if sign == '+' else -1
        anomalies.append({
            'ticker':   ticker,
            'move_pct': direction * pct,
            'reason':   '跳空/异动' if pct >= 5 else '日内大幅波动',
        })
    return anomalies


def parse_hk_indices(stdout):
    """Extract 恒指 / 恒科 day move from HK script header."""
    m = re.search(r'恒指\s+[\d,]+\s+[▲▼]([\d\.]+)%\s+恒科\s+[\d,]+\s+[▲▼]([\d\.]+)%', stdout)
    if not m:
        return None
    hsi_pct, hstech_pct = float(m.group(1)), float(m.group(2))
    if '恒指 ' in stdout:
        hsi_dir = -1 if '恒指' in stdout and '▼' in stdout.split('恒指')[1].split('恒科')[0] else 1
        hstech_dir = -1 if '▼' in stdout.split('恒科')[1][:30] else 1
        return {'hsi_pct': hsi_dir * hsi_pct, 'hstech_pct': hstech_dir * hstech_pct}
    return None


def collect_peers(market):
    """Peer/rotation data for this market's holdings, for the 板块全景 section.

    The Mode 6 SKILL asks for a sector Top 5 but preflight never supplied the
    numbers, so the agent had to improvise a peer fetch at report time. Peer
    trouble must never fail the report: any problem degrades to an empty scan.
    """
    leg = 'hk_stocks' if market == 'hk' else 'us_stocks'
    try:
        portfolio = json.loads((WS / 'portfolio.json').read_text())
        # Scope to this market's leg *before* fetching: filtering the result
        # afterwards would still pay the full cross-market network fan-out.
        # stdout is the context JSON the agent parses; diagnostics go to stderr.
        return peer_scan.collect(portfolio, log=lambda m: print(m, file=sys.stderr),
                                 legs=(leg,))
    except Exception as e:
        print(f'   ⚠️  peer scan skipped: {e}', file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    args = parser.parse_args()

    if (args.market, args.phase) not in TITLE_TEMPLATES:
        print(f'❌ invalid market+phase combo: {args.market}/{args.phase}', file=sys.stderr)
        return 2

    today = datetime.now().strftime('%Y-%m-%d')

    # --- Holiday/weekend gate (before any fetch): on a closed market, skip the
    # price refresh entirely (stale closes must NOT be written as a new session)
    # and write a market_closed sentinel with NO raw_wechat_block — the report
    # watchdog treats a blockless context as "never ran" and won't re-send. ---
    reason = _market_closed_reason(args.market, args.phase)
    if reason:
        result = {'status': 'market_closed', 'market': args.market,
                  'phase': args.phase, 'date': today, 'reason': reason, 'skip': True}
        TMP.mkdir(parents=True, exist_ok=True)
        drop_stale_contexts(args.market, args.phase, today)
        out_path = context_path(args.market, args.phase, today)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        market_cn = '港股' if args.market == 'hk' else '美股'
        print(f'=== MARKET CLOSED — {market_cn}今日{reason} ({today}) ===')
        print('SKIP：不要生成报告、不要调用任何 send/postflight、本回合到此结束。')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        announce_context_path(out_path)
        return 0

    rc, stdout, stderr = run_analyze(args.market)

    if rc != 0:
        result = {
            'status': 'preflight_failed',
            'market': args.market,
            'phase':  args.phase,
            'error':  stderr[-500:] if stderr else f'rc={rc}',
        }
        TMP.mkdir(parents=True, exist_ok=True)
        drop_stale_contexts(args.market, args.phase, today)
        out_path = context_path(args.market, args.phase, today)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        announce_context_path(out_path)
        return 1

    signals = parse_signals(stdout)
    anomalies = parse_anomalies(stdout)
    indices = parse_hk_indices(stdout) if args.market == 'hk' else None
    peers = collect_peers(args.market)

    title = TITLE_TEMPLATES[(args.market, args.phase)].format(date=today)
    market_cn = '港股' if args.market == 'hk' else '美股'
    commit_msg = f'portfolio: {market_cn}{COMMIT_PHASE_CN[args.phase]}价格更新'

    result = {
        'status':             'ok',
        'market':             args.market,
        'phase':              args.phase,
        'date':               today,
        'generated_at':       datetime.now().isoformat(timespec='seconds'),
        'raw_wechat_block':   stdout.strip(),
        'title':              title,
        'commit_msg':         commit_msg,
        'signal_count':       signals,
        'anomalies':          anomalies,
        'index_direction':    indices,
        'peer_scan':          peers,
        'needs_risk_section': (signals['stop'] + signals['trim']) >= 2,
    }

    TMP.mkdir(parents=True, exist_ok=True)
    drop_stale_contexts(args.market, args.phase, today)
    out_path = context_path(args.market, args.phase, today)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    announce_context_path(out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
