#!/usr/bin/env python3
"""
fetch_catalysts.py — pull the next 14 days of market-moving events for the brief.

Sources:
  • US holdings earnings — Finnhub /calendar/earnings (single symbol per call).
    Only queries non-leveraged tickers (leveraged ETFs have no own earnings).
  • Fed FOMC meetings — hardcoded 2026 schedule (federalreserve.gov fomccalendars),
    filtered to within window.
  • Macro events — hardcoded "rule-based" generators:
      - NFP (first Friday of each month) — most reliable rule
      - CPI (BLS schedule, hardcoded 2026 release dates)
      - PCE (last business day + 25d, but we use known BEA schedule)
      - GDP (advance/2nd/3rd estimates; hardcoded 2026 release dates)

Writes:  assets/data/catalysts.json
Modes:
  clawock catalysts            # 14d window, write file + summary
  clawock catalysts --json     # print final JSON to stdout and write file
  clawock catalysts --days 30  # custom window
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import requests

from clawock import instruments as instrument_registry
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS_ROOT = workspace_root(Path.cwd())
OUT_FILE = WS_ROOT / 'assets' / 'data' / 'catalysts.json'
API_KEYS_FILE = WS_ROOT / '.api_keys'
# Dated company events no vendor supplies (Stock Connect effective dates, lockup
# expiries, mainnet launches). Hand-maintained; see the file's own _meta.
SCHEDULED_FILE = WS_ROOT / 'memory' / 'scheduled_catalysts.json'

UA = 'clawock-catalysts/0.1'
HEADERS = {'User-Agent': UA}
TIMEOUT = 10

# Earnings tickers are derived from portfolio.json, never hand-synced. The old
# hardcoded list was stamped 2026-05-19 and had drifted: it still named exited
# positions and, worse, dropped every leveraged ETF without substituting the
# company whose earnings actually gaps it. Holding MSFU with MSFT's report date
# missing is the failure this exists to prevent.
PORTFOLIO_FILE = WS_ROOT / 'portfolio.json'


def earnings_issuer(ticker):
    """The company whose earnings moves this holding, or None if there is none.

    Thin wrapper over the registry's canonical look-through so the rule lives in
    one place (see instrument_registry.look_through).
    """
    return instrument_registry.issuer_for(ticker)


def us_earnings_tickers(portfolio=None):
    """US names to query, looked through to the issuer that actually reports."""
    if portfolio is None:
        try:
            portfolio = json.loads(PORTFOLIO_FILE.read_text())
        except (OSError, ValueError):
            return []
    out = []
    for book in (portfolio.get('portfolios') or {}).values():
        for holding in (book or {}).get('holdings') or []:
            ticker = holding.get('ticker')
            meta = instrument_registry.get(ticker) or {}
            if (holding.get('shares') or 0) <= 0 or meta.get('region') != 'US':
                continue
            issuer = earnings_issuer(ticker)
            if issuer and issuer not in out:
                out.append(issuer)
    return sorted(out)

# 2026 FOMC meeting dates (rate-decision second day)
# Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_2026 = [
    {'start': '2026-01-27', 'end': '2026-01-28'},
    {'start': '2026-03-17', 'end': '2026-03-18'},
    {'start': '2026-04-28', 'end': '2026-04-29'},
    {'start': '2026-06-16', 'end': '2026-06-17'},
    {'start': '2026-07-28', 'end': '2026-07-29'},
    {'start': '2026-09-15', 'end': '2026-09-16'},
    {'start': '2026-10-27', 'end': '2026-10-28'},
    {'start': '2026-12-08', 'end': '2026-12-09'},
]

# BLS CPI release schedule 2026 (typically 13-15 of each month, 8:30 ET)
# Source: bls.gov/schedule/news_release/cpi.htm
CPI_2026 = [
    '2026-01-14', '2026-02-12', '2026-03-12', '2026-04-15',
    '2026-05-13', '2026-06-11', '2026-07-15', '2026-08-12',
    '2026-09-11', '2026-10-15', '2026-11-13', '2026-12-10',
]

# BEA GDP release schedule 2026 (advance/2nd/3rd estimates per quarter)
# Source: bea.gov/news/schedule
GDP_2026 = [
    {'date': '2026-01-29', 'detail': 'Q4 2025 GDP advance estimate'},
    {'date': '2026-02-26', 'detail': 'Q4 2025 GDP 2nd estimate'},
    {'date': '2026-03-26', 'detail': 'Q4 2025 GDP 3rd estimate'},
    {'date': '2026-04-29', 'detail': 'Q1 2026 GDP advance estimate'},
    {'date': '2026-05-28', 'detail': 'Q1 2026 GDP 2nd estimate'},
    {'date': '2026-06-25', 'detail': 'Q1 2026 GDP 3rd estimate'},
    {'date': '2026-07-30', 'detail': 'Q2 2026 GDP advance estimate'},
    {'date': '2026-08-27', 'detail': 'Q2 2026 GDP 2nd estimate'},
    {'date': '2026-09-24', 'detail': 'Q2 2026 GDP 3rd estimate'},
    {'date': '2026-10-29', 'detail': 'Q3 2026 GDP advance estimate'},
    {'date': '2026-11-25', 'detail': 'Q3 2026 GDP 2nd estimate'},
    {'date': '2026-12-22', 'detail': 'Q3 2026 GDP 3rd estimate'},
]

# BEA PCE release schedule 2026 (~last business day + 25d of month)
PCE_2026 = [
    '2026-01-30', '2026-02-27', '2026-03-27', '2026-04-30',
    '2026-05-29', '2026-06-26', '2026-07-31', '2026-08-28',
    '2026-09-25', '2026-10-30', '2026-11-25', '2026-12-22',
]


def read_finnhub_key():
    """Parse .api_keys to find FINNHUB_API_KEY."""
    try:
        with open(API_KEYS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('FINNHUB_API_KEY='):
                    return line.split('=', 1)[1].strip()
    except FileNotFoundError:
        # No key file is a normal deployment, and every caller handles None.
        # Warning here put a line on stderr for each probe on CI, which is how a
        # warning channel stops being read.
        pass
    except Exception as e:
        print(f'  warn: read .api_keys failed: {e}', file=sys.stderr)
    return None


def fetch_earnings_for_ticker(ticker, frm, to, api_key):
    """One Finnhub call. Returns list of earnings dicts (may be empty) or None on error."""
    if not api_key:
        return None, 'no FINNHUB_API_KEY'
    try:
        url = 'https://finnhub.io/api/v1/calendar/earnings'
        r = requests.get(
            url,
            params={'from': frm, 'to': to, 'symbol': ticker, 'token': api_key},
            headers=HEADERS, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None, f'HTTP {r.status_code}: {r.text[:150]}'
        j = r.json()
        rows = j.get('earningsCalendar') or []
        return rows, None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def fetch_earnings(window_start, window_end):
    """Pull earnings for every non-leveraged US active ticker."""
    api_key = read_finnhub_key()
    out_rows = []
    errors = {}
    queried = []
    for ticker in us_earnings_tickers():
        queried.append(ticker)
        rows, err = fetch_earnings_for_ticker(ticker, window_start, window_end, api_key)
        if err:
            errors[ticker] = err
            continue
        for r in rows or []:
            time_str = (r.get('hour') or '').lower()  # 'bmo' / 'amc' / 'dmh' / ''
            out_rows.append({
                'ticker':            ticker,
                'name':              r.get('symbol', ticker),
                'date':              r.get('date'),
                'time':              time_str or 'unknown',
                'eps_estimate':      r.get('epsEstimate'),
                'eps_actual':        r.get('epsActual'),
                'revenue_estimate_m': round(r['revenueEstimate'] / 1_000_000, 2)
                                      if r.get('revenueEstimate') else None,
                'quarter':           r.get('quarter'),
                'year':              r.get('year'),
            })
    out_rows.sort(key=lambda x: x.get('date') or '')
    return out_rows, errors, queried


def fomc_in_window(window_start, window_end):
    """Return FOMC entries whose 2nd-day rate decision falls in window."""
    out = []
    for m in FOMC_2026:
        end = m['end']
        if window_start <= end <= window_end:
            out.append({
                'date':   end,
                'type':   'rate_decision',
                'detail': f'FOMC {m["start"]} to {m["end"]} meeting; rate decision + Powell presser on {end}',
            })
    out.sort(key=lambda x: x['date'])
    return out


def _first_friday(year, month):
    """First Friday of (year, month) as YYYY-MM-DD string."""
    d = date(year, month, 1)
    # weekday(): Monday=0 ... Friday=4 ... Sunday=6
    offset = (4 - d.weekday()) % 7
    return (d + timedelta(days=offset)).isoformat()


def _month_name(month):
    return ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
            'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][month]


def _prior_month_label(date_str):
    """Given report release YYYY-MM-DD, return the prior month label (e.g. 'May')."""
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d').date()
        prev = (d.replace(day=1) - timedelta(days=1))
        return _month_name(prev.month)
    except Exception:
        return ''


def macro_in_window(window_start, window_end):
    """Compose macro events from rule-generators + hardcoded BLS/BEA schedules."""
    out = []

    # NFP — first Friday of each month
    start_dt = datetime.strptime(window_start, '%Y-%m-%d').date()
    end_dt   = datetime.strptime(window_end,   '%Y-%m-%d').date()
    # Walk through every month that overlaps window
    y, m = start_dt.year, start_dt.month
    while date(y, m, 1) <= end_dt:
        ff = _first_friday(y, m)
        if window_start <= ff <= window_end:
            prior_mo = _month_name((m - 1) or 12)
            out.append({
                'date':   ff,
                'type':   'NFP',
                'detail': f'{prior_mo} jobs report (Non-Farm Payrolls); BLS 8:30 ET',
            })
        # advance month
        if m == 12:
            y += 1; m = 1
        else:
            m += 1

    # CPI
    for ds in CPI_2026:
        if window_start <= ds <= window_end:
            out.append({
                'date':   ds,
                'type':   'CPI',
                'detail': f'{_prior_month_label(ds)} CPI release (BLS 8:30 ET)',
            })

    # PCE
    for ds in PCE_2026:
        if window_start <= ds <= window_end:
            out.append({
                'date':   ds,
                'type':   'PCE',
                'detail': f'{_prior_month_label(ds)} PCE price index (BEA, Fed preferred inflation gauge)',
            })

    # GDP
    for g in GDP_2026:
        if window_start <= g['date'] <= window_end:
            out.append({
                'date':   g['date'],
                'type':   'GDP',
                'detail': g['detail'],
            })

    out.sort(key=lambda x: x['date'])
    return out


def _highest_impact(catalysts, today_iso):
    """Pick the highest-impact event within 7d. Priority: FOMC > CPI > NFP > earnings > others."""
    cutoff = (datetime.strptime(today_iso, '%Y-%m-%d').date() + timedelta(days=7)).isoformat()

    def in_7d(d):
        return d and today_iso <= d <= cutoff

    for e in catalysts['fomc']:
        if in_7d(e['date']):
            return f'FOMC {e["date"]} (rate decision)'
    cpi_hits = [e for e in catalysts['macro_events']
                if e['type'] == 'CPI' and in_7d(e['date'])]
    if cpi_hits:
        return f'CPI {cpi_hits[0]["date"]}'
    nfp_hits = [e for e in catalysts['macro_events']
                if e['type'] == 'NFP' and in_7d(e['date'])]
    if nfp_hits:
        return f'NFP {nfp_hits[0]["date"]}'
    earn_hits = [e for e in catalysts['earnings'] if in_7d(e['date'])]
    if earn_hits:
        e = earn_hits[0]
        return f'{e["ticker"]} earnings {e["date"]} ({e["time"]})'
    other = [e for e in catalysts['macro_events'] if in_7d(e['date'])]
    if other:
        return f'{other[0]["type"]} {other[0]["date"]}'
    return None


def scheduled_in_window(window_start, window_end, path=SCHEDULED_FILE):
    """Hand-maintained company events, filtered to the window.

    An entry whose date is unknown is kept regardless of the window and carries
    `date: null`. That is the point of the file: the brief must be able to say
    "生效日未确认" from data instead of inventing a date, which is what produced
    three contradictory dates for one event on 2026-08-06.

    Returns `(events, error)`. A malformed file must not take the whole catalyst
    step down — the automatic categories are still worth publishing — but it must
    not vanish silently either: a JSON typo in a hand-edited file would otherwise
    drop every scheduled event with nothing anywhere saying so. The error rides
    out in `catalysts.json.error`, which preflight already surfaces.
    """
    try:
        with open(path, encoding='utf-8') as fh:
            entries = (json.load(fh) or {}).get('events') or []
    except FileNotFoundError:
        return [], None
    except (OSError, ValueError) as exc:
        return [], f'{type(exc).__name__}: {exc}'
    out = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get('ticker'):
            continue
        date = entry.get('date')
        confidence = entry.get('date_confidence') or 'unconfirmed'
        # A date that is present but outside the window is simply not due yet.
        if date and not (window_start <= date <= window_end):
            continue
        # Guard the one rule the file exists to enforce: no date, no confidence
        # claim. A stray "confirmed" with a null date would let the brief cite a
        # certainty that does not exist.
        if not date:
            confidence = 'unconfirmed'
        out.append({
            'ticker': entry['ticker'],
            'name': entry.get('name') or entry['ticker'],
            'type': entry.get('type') or 'other',
            'date': date,
            'date_confidence': confidence,
            'detail': entry.get('detail') or '',
            'source': entry.get('source') or '',
        })
    ordered = sorted(out, key=lambda e: (e['date'] is None, e['date'] or '', e['ticker']))
    return ordered, None


def build_catalysts(days):
    today = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
    today_dt = datetime.strptime(today, '%Y-%m-%d').date()
    end_iso = (today_dt + timedelta(days=days)).isoformat()

    errors = {}

    earnings, e_errors, queried = fetch_earnings(today, end_iso)
    if e_errors:
        errors['earnings'] = e_errors

    fomc = fomc_in_window(today, end_iso)
    macro = macro_in_window(today, end_iso)
    scheduled, s_error = scheduled_in_window(today, end_iso)
    if s_error:
        errors['scheduled_events'] = s_error

    catalysts = {
        'earnings':      earnings,
        'fomc':          fomc,
        'macro_events':  macro,
    }
    highest = _highest_impact(catalysts, today)

    out = {
        'generated_at':       datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'lookback_window_days': days,
        'window_start':       today,
        'window_end':         end_iso,
        'earnings_queried':   queried,
        'earnings':           earnings,
        'fomc':               fomc,
        'macro_events':       macro,
        'scheduled_events':   scheduled,
        'summary': {
            'earnings_count':           len(earnings),
            'fomc_in_window':           len(fomc),
            'macro_count':              len(macro),
            'scheduled_count':          len(scheduled),
            'scheduled_undated':        sum(1 for e in scheduled if not e['date']),
            'highest_impact_within_7d': highest,
        },
    }
    if errors:
        out['error'] = errors
    return out


def print_summary(out):
    print(f'=== catalysts ({out["window_start"]} to {out["window_end"]}) ===')
    print(f'Earnings queried: {", ".join(out["earnings_queried"])}')
    print(f'Earnings hits:    {len(out["earnings"])}')
    for e in out['earnings']:
        eps = e.get('eps_estimate')
        rev = e.get('revenue_estimate_m')
        print(f'  {e["date"]}  {e["ticker"]:6s} {e["time"]:4s}  '
              f'EPS est {eps if eps is not None else "n/a"}  '
              f'Rev est {f"${rev}M" if rev is not None else "n/a"}')
    print(f'FOMC in window:   {len(out["fomc"])}')
    for f in out['fomc']:
        print(f'  {f["date"]}  {f["detail"]}')
    print(f'Macro events:     {len(out["macro_events"])}')
    for m in out['macro_events']:
        print(f'  {m["date"]}  {m["type"]:5s} {m["detail"][:100]}')
    print(f'Highest impact within 7d: {out["summary"]["highest_impact_within_7d"] or "(none)"}')
    if 'error' in out:
        print(f'\nErrors:')
        for section, errs in out['error'].items():
            for k, v in errs.items():
                print(f'  {section}/{k}: {v}')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Fetch upcoming catalysts (14d default)')
    ap.add_argument('--days', type=int, default=14, help='lookback window in days')
    ap.add_argument('--json', action='store_true',
                    help='print final JSON to stdout, do not write file')
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        out = build_catalysts(args.days)
    except Exception as e:
        # last-resort: don't crash preflight
        out = {
            'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'lookback_window_days': args.days,
            'earnings': [], 'fomc': [], 'macro_events': [],
            'summary': {
                'earnings_count': 0, 'fomc_in_window': 0,
                'macro_count': 0, 'highest_impact_within_7d': None,
            },
            'error': {'fatal': f'{type(e).__name__}: {e}'},
        }

    # Always persist the file — even in --json mode. brief_preflight [11/11] calls
    # this with --json to capture the data into context, and that call MUST also
    # refresh assets/data/catalysts.json (build_dashboard embeds it). The old early
    # return on --json meant nothing in the daily pipeline ever rewrote the file →
    # the dashboard Catalysts card froze at whenever someone last ran it bare.
    safe_write_json(str(OUT_FILE), out)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print_summary(out)
        print(f'\nwrote {OUT_FILE} ({OUT_FILE.stat().st_size:,} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
