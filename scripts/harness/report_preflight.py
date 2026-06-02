#!/usr/bin/env python3
"""
report_preflight.py — Mode 6 (briefing) harness preflight.

Runs deterministic work for the 6 briefing crons:
  HK: 开盘 09:30 / 午盘 12:00 / 午后 13:30 / 收盘 16:00
  US: 开盘 09:30 ET / 收盘 16:00 ET

Each invocation:
  1. Runs analyze_{hk,us}_stocks.py --wechat (refreshes prices, writes portfolio.json)
  2. Captures full script output (LLM uses this VERBATIM as the data block)
  3. Parses signals (WATCH/STOP/TRIM counts) and direction hints
  4. Detects anomalies (≥3% intraday moves, big floating losses)
  5. Writes memory/.tmp/report-context-{market}-{phase}-{date}.json

Output keys:
  raw_wechat_block:   str (script stdout, paste verbatim)
  market:             "hk" | "us"
  phase:              "open" | "mid" | "pm" | "close"
  title:              suggested WeChat title
  commit_msg:         git commit message suffix
  signal_count:       {watch, stop, trim}
  anomalies:          list of {ticker, move_pct, reason}
  index_direction:    {hk_index_pct, hstech_pct} for HK; null for US
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

TITLE_TEMPLATES = {
    ('hk', 'open'):  '📊 港股开盘快报｜{date} 09:30',
    ('hk', 'mid'):   '☕ 港股午盘快报｜{date} 12:00',
    ('hk', 'pm'):    '🌤 港股午后快报｜{date} 13:30',
    ('hk', 'close'): '🔔 港股收盘日报｜{date}',
    ('us', 'open'):  '🌅 美股开盘快报｜{date} 21:30 CST',
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    parser.add_argument('--phase', choices=['open', 'mid', 'pm', 'close'], required=True)
    args = parser.parse_args()

    if (args.market, args.phase) not in TITLE_TEMPLATES:
        print(f'❌ invalid market+phase combo: {args.market}/{args.phase}', file=sys.stderr)
        return 2

    today = datetime.now().strftime('%Y-%m-%d')
    rc, stdout, stderr = run_analyze(args.market)

    if rc != 0:
        result = {
            'status': 'preflight_failed',
            'market': args.market,
            'phase':  args.phase,
            'error':  stderr[-500:] if stderr else f'rc={rc}',
        }
        TMP.mkdir(parents=True, exist_ok=True)
        (TMP / f'report-context-{args.market}-{args.phase}-{today}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    signals = parse_signals(stdout)
    anomalies = parse_anomalies(stdout)
    indices = parse_hk_indices(stdout) if args.market == 'hk' else None

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
        'needs_risk_section': (signals['stop'] + signals['trim']) >= 2,
    }

    TMP.mkdir(parents=True, exist_ok=True)
    out_path = TMP / f'report-context-{args.market}-{args.phase}-{today}.json'
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
