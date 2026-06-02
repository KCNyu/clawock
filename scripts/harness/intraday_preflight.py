#!/usr/bin/env python3
"""
intraday_preflight.py — Mode 7 (intraday) harness preflight.

Runs deterministic work for the 2 intraday crons (every 30 min):
  HK 盘中盯盘:  */30 9-15 * * 1-5  Asia/Shanghai
  US 盘中盯盘:  */30 9-15 * * 1-5  America/New_York

Each invocation:
  1. Runs analyze_{hk,us}_stocks.py --wechat
  2. Captures stdout (LLM uses verbatim)
  3. Detects anomalies (≥3% move, RSI extremes from script signals)
  4. Decides should_alert: bool (true if any anomaly OR ≥2 signals)
  5. Writes memory/.tmp/intraday-context-{market}-{HHMM}.json

NB: Mode 7 is lightweight on purpose (every 30 min × 7 hrs × 2 markets = 28 runs/day).
    No git commit, no rich news block. Just data refresh + anomaly trigger.
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


def run_analyze(market):
    script = DATA_DIR / f'analyze_{market}_stocks.py'
    try:
        r = subprocess.run(
            ['python3', str(script), '--wechat', '--md-table', '--today-abs'],
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

    Row shape (7 cols, both markets; 成本 dropped + 今日$ added 2026-06-02):
      `| 00100 | 60 | 674.00 | -4.8% | -2,040 | -18.1% | -8,930 |`
    Columns are located by HEADER (代码 → ticker, 今日%/今日 → today move) rather
    than fixed index, so future column reorders don't silently break this.
    Header / separator rows are filtered.
    """
    anomalies = []
    pct_re = re.compile(r'([+\-])([\d\.]+)%')
    ticker_col, today_col = 0, None
    for line in stdout.splitlines():
        s = line.strip()
        if not s.startswith('|') or not s.endswith('|'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if '代码' in cells:  # header row → learn column positions
            ticker_col = cells.index('代码')
            today_col = next((i for i, h in enumerate(cells)
                              if h.startswith('今日') and '$' not in h), None)
            continue
        if today_col is None or len(cells) <= max(ticker_col, today_col):
            continue
        ticker = cells[ticker_col]
        if ticker.startswith(':') or set(ticker) <= set('-: '):  # separator
            continue
        today = cells[today_col]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['hk', 'us'], required=True)
    args = parser.parse_args()

    now = datetime.now()
    stamp = now.strftime('%Y-%m-%d_%H%M')
    rc, stdout, stderr = run_analyze(args.market)

    if rc != 0:
        result = {
            'status': 'preflight_failed',
            'market': args.market,
            'error':  stderr[-500:] if stderr else f'rc={rc}',
        }
        TMP.mkdir(parents=True, exist_ok=True)
        (TMP / f'intraday-context-{args.market}-{stamp}.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    signals, signals_detail = parse_signals(stdout)
    anomalies = parse_anomalies(stdout)

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
    }

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
