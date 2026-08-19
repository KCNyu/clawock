#!/usr/bin/env python3
"""
clawock filings — SEC EDGAR fundamentals + filings fetcher (no API key required)

Covers gaps in US market data: 10-K/10-Q sections, Form 4 insider trades,
13F institutional holdings, and XBRL-derived key financials. All free, direct
from SEC.

SEC EDGAR rules respected:
  - User-Agent required (configured via SEC_USER_AGENT in .api_keys, or default)
  - Rate limit: <= 10 req/sec (we use 8 to leave margin)

Endpoints used:
  1. company_tickers.json          – ticker → CIK lookup (cached locally)
  2. submissions/CIK{cik}.json     – filings index per company
  3. xbrl/companyfacts/CIK{cik}    – all XBRL facts (financials in raw form)
  4. xbrl/companyconcept/.../{tag} – single concept time series
  5. Archives/edgar/data/{cik}/... – filing primary document URL

Usage:
  clawock filings RKLB                       # summary: latest filings + key financials
  clawock filings RKLB --filings             # full recent filings list
  clawock filings RKLB --filings 10-K,10-Q   # only specific forms
  clawock filings RKLB --form4               # insider Form 4 transactions
  clawock filings RKLB --financials          # key XBRL concepts
  clawock filings RKLB --json                # machine-readable JSON to stdout
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests

from clawock.workspace import workspace_root

WS_ROOT = workspace_root(Path.cwd())
API_KEYS_PATH = WS_ROOT / '.api_keys'
CACHE_DIR = WS_ROOT / '.cache'
TICKER_CACHE = CACHE_DIR / 'sec_tickers.json'
CACHE_TTL_DAYS = 7   # ticker → CIK map; SEC updates infrequently

TIMEOUT      = 15
MIN_INTERVAL = 0.125   # 8 req/sec ceiling (SEC allows 10)

_last_call = 0.0


def _load_user_agent() -> str:
    """SEC requires User-Agent: 'Name email@domain'. Read from .api_keys or env."""
    try:
        with API_KEYS_PATH.open() as f:
            for line in f:
                line = line.strip()
                if line.startswith('SEC_USER_AGENT='):
                    return line.split('=', 1)[1].strip().strip('"\'')
    except FileNotFoundError:
        pass
    env_ua = os.environ.get('SEC_USER_AGENT', '').strip()
    if env_ua:
        return env_ua
    return UNCONFIGURED_SEC_USER_AGENT


# SEC's access policy wants a real, deliverable contact address in the
# User-Agent. This default has neither a name nor a reachable mailbox, and SEC
# rejects it — measured 2026-08-19, same URL and second, only the UA changed:
#
#   'clawock-research/0.1 clawock@users.noreply.github.com'  -> 403 (this value)
#   'Clawock Research clawock@users.noreply.github.com'      -> 403
#   'clawock-research/0.1 <deliverable mailbox>'             -> 200
#   'Clawock Research kcn <deliverable mailbox>'             -> 200
#
# The deciding factor is the mailbox domain: @users.noreply.github.com does not
# receive mail. So this is not a "works but impolite" fallback — it is a
# guaranteed 403, and for weeks it read downstream as an ordinary upstream
# outage. Keep the constant nameable so a degraded source can say *why*.
UNCONFIGURED_SEC_USER_AGENT = 'clawock-research/0.1 clawock@users.noreply.github.com'


def sec_user_agent_configured() -> bool:
    """False when nothing set SEC_USER_AGENT, i.e. SEC will refuse every call."""
    return _load_user_agent() != UNCONFIGURED_SEC_USER_AGENT


SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': _load_user_agent(),
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'data.sec.gov',
})


def _throttle():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _get(url: str, host: Optional[str] = None) -> Optional[requests.Response]:
    _throttle()
    headers = dict(SESSION.headers)
    if host:
        headers['Host'] = host
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code == 200:
            return r
        if r.status_code == 404:
            return None
        print(f"  ⚠️  SEC {r.status_code}: {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ⚠️  SEC request failed: {e}", file=sys.stderr)
        return None


# ── ticker → CIK lookup ──────────────────────────────────────────────────────

def _load_ticker_map() -> Dict[str, str]:
    """Returns {TICKER: 'CIK0001234567'} (10-digit zero-padded)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if TICKER_CACHE.exists():
        age_days = (time.time() - TICKER_CACHE.stat().st_mtime) / 86400
        if age_days < CACHE_TTL_DAYS:
            with TICKER_CACHE.open() as f:
                return json.load(f)

    r = _get('https://www.sec.gov/files/company_tickers.json', host='www.sec.gov')
    if not r:
        if TICKER_CACHE.exists():
            with TICKER_CACHE.open() as f:
                return json.load(f)
        return {}
    raw = r.json()
    mapping = {entry['ticker'].upper(): f"CIK{int(entry['cik_str']):010d}"
               for entry in raw.values()}
    with TICKER_CACHE.open('w') as f:
        json.dump(mapping, f)
    return mapping


def lookup_cik(ticker: str) -> Optional[str]:
    mapping = _load_ticker_map()
    return mapping.get(ticker.upper())


# ── filings ──────────────────────────────────────────────────────────────────

def get_filings(ticker: str, form_types: Optional[List[str]] = None,
                limit: int = 10) -> List[Dict]:
    """
    Recent filings list. form_types filters: ['10-K', '10-Q', '8-K', '4', '13F-HR'].
    Each entry: {form, filing_date, accession, primary_doc, primary_doc_url, report_date}
    """
    cik = lookup_cik(ticker)
    if not cik:
        return []
    r = _get(f'https://data.sec.gov/submissions/{cik}.json')
    if not r:
        return []
    d = r.json().get('filings', {}).get('recent', {})
    forms       = d.get('form', [])
    dates       = d.get('filingDate', [])
    accs        = d.get('accessionNumber', [])
    primaries   = d.get('primaryDocument', [])
    descs       = d.get('primaryDocDescription', [])
    report_dates = d.get('reportDate', [])
    items       = d.get('items', [])

    cik_num = int(cik.replace('CIK', ''))
    out: List[Dict] = []
    for i, form in enumerate(forms):
        if form_types and form not in form_types:
            continue
        acc_clean = accs[i].replace('-', '')
        out.append({
            'form':         form,
            'filing_date':  dates[i],
            'report_date':  report_dates[i] if i < len(report_dates) else '',
            'accession':    accs[i],
            'primary_doc':  primaries[i] if i < len(primaries) else '',
            'description':  descs[i] if i < len(descs) else '',
            'items':        items[i] if i < len(items) else '',
            'primary_doc_url': (
                f'https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_clean}/'
                f'{primaries[i]}' if i < len(primaries) else ''
            ),
            'filing_index_url': (
                f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany'
                f'&CIK={cik_num}&type={form}&dateb=&owner=include&count=10'
            ),
        })
        if len(out) >= limit:
            break
    return out


# ── XBRL financials ──────────────────────────────────────────────────────────

# Standard us-gaap concept tags worth fetching for any operating company.
KEY_CONCEPTS = [
    'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
    'CostOfRevenue', 'GrossProfit',
    'OperatingIncomeLoss', 'NetIncomeLoss',
    'EarningsPerShareBasic', 'EarningsPerShareDiluted',
    'Assets', 'Liabilities', 'StockholdersEquity',
    'CashAndCashEquivalentsAtCarryingValue',
    'NetCashProvidedByUsedInOperatingActivities',
    'ResearchAndDevelopmentExpense',
]


def get_company_facts(ticker: str) -> Optional[Dict]:
    """Returns full XBRL companyfacts blob — large, contains all reported concepts."""
    cik = lookup_cik(ticker)
    if not cik:
        return None
    r = _get(f'https://data.sec.gov/api/xbrl/companyfacts/{cik}.json')
    return r.json() if r else None


def _latest_value(facts: Dict, concept: str, periods: int = 4) -> List[Dict]:
    """Extract the latest `periods` USD values for a concept; returns list of {value, end, fp, form}."""
    section = facts.get('facts', {}).get('us-gaap', {}).get(concept)
    if not section:
        return []
    # Prefer USD; if missing, take whatever single unit is there
    units = section.get('units', {})
    chosen = units.get('USD') or units.get('USD/shares') or next(iter(units.values()), [])
    sorted_entries = sorted(chosen, key=lambda x: x.get('end', ''), reverse=True)
    seen = set()
    out: List[Dict] = []
    for e in sorted_entries:
        key = (e.get('end'), e.get('fp'), e.get('form'))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            'value':  e.get('val'),
            'end':    e.get('end'),
            'fp':     e.get('fp'),         # FY / Q1 / Q2 / Q3
            'form':   e.get('form'),       # 10-K / 10-Q
            'filed':  e.get('filed'),
        })
        if len(out) >= periods:
            break
    return out


def get_key_financials(ticker: str) -> Dict:
    """
    Extract the most useful concepts. Returns:
      {concept: [{value, end, fp, form, filed}, ...]} sorted newest first.
    Skips concepts the company never reported.
    """
    facts = get_company_facts(ticker)
    if not facts:
        return {}
    out: Dict[str, List[Dict]] = {}
    for c in KEY_CONCEPTS:
        vals = _latest_value(facts, c, periods=4)
        if vals:
            out[c] = vals
    # Pick the better revenue tag — fallback to alt if primary empty
    if 'Revenues' not in out and 'RevenueFromContractWithCustomerExcludingAssessedTax' in out:
        out['Revenues'] = out.pop('RevenueFromContractWithCustomerExcludingAssessedTax')
    return out


# ── insider trades ───────────────────────────────────────────────────────────

def get_form4_trades(ticker: str, limit: int = 20) -> List[Dict]:
    """
    Form 4 (Statement of changes in beneficial ownership) — insider buys/sells.
    Returns filing metadata; parsing each XML for actual share count is left to
    the caller (links provided).
    """
    return get_filings(ticker, form_types=['4', '4/A'], limit=limit)


# ── 13F (only useful for hedge funds / asset managers — but here for completeness)

def get_13f_filings(ticker: str, limit: int = 10) -> List[Dict]:
    return get_filings(ticker, form_types=['13F-HR', '13F-HR/A'], limit=limit)


# ── CLI / formatters ─────────────────────────────────────────────────────────

def _fmt_num(v) -> str:
    if v is None:
        return 'n/a'
    if not isinstance(v, (int, float)):
        return str(v)
    abs_v = abs(v)
    if abs_v >= 1e9:  return f'{v/1e9:>8.2f}B'
    if abs_v >= 1e6:  return f'{v/1e6:>8.2f}M'
    if abs_v >= 1e3:  return f'{v/1e3:>8.2f}K'
    return f'{v:>10.2f}'


def _print_filings(ticker: str, filings: List[Dict]):
    if not filings:
        print(f"  no filings found for {ticker}")
        return
    print(f"\n  Recent filings for {ticker}:")
    print(f"  {'Form':<10} {'Filed':<12} {'Report':<12} {'Description':<40}")
    print(f"  {'-'*10} {'-'*12} {'-'*12} {'-'*40}")
    for f in filings:
        desc = (f['description'] or f['items'] or '')[:38]
        print(f"  {f['form']:<10} {f['filing_date']:<12} {f['report_date']:<12} {desc:<40}")
        if f['primary_doc_url']:
            print(f"    → {f['primary_doc_url']}")


def _print_financials(ticker: str, financials: Dict):
    if not financials:
        print(f"  no XBRL data for {ticker} (may not report under US-GAAP)")
        return
    print(f"\n  Key financials for {ticker} (latest 4 periods):")
    for concept, entries in financials.items():
        print(f"\n  {concept}:")
        for e in entries:
            label = f"{e['fp']} {e['end']}" if e['fp'] else e['end']
            print(f"    {label:<20} {_fmt_num(e['value']):>14}  ({e['form']}, filed {e['filed']})")


def summarize(ticker: str, as_json: bool = False) -> Dict:
    """Default: top 5 filings + key financials snapshot."""
    cik = lookup_cik(ticker)
    if not cik:
        result = {'ticker': ticker, 'error': 'CIK not found (delisted? non-US? typo?)'}
        if not as_json:
            print(f"  ✗ {ticker}: CIK lookup failed")
        return result

    filings = get_filings(ticker, form_types=['10-K', '10-Q', '8-K'], limit=5)
    financials = get_key_financials(ticker)

    result = {
        'ticker':     ticker,
        'cik':        cik,
        'as_of':      datetime.now(timezone.utc).isoformat(),
        'recent_filings': filings,
        'key_financials': financials,
    }
    if as_json:
        return result

    print(f"\n{'═'*72}")
    print(f"  SEC EDGAR snapshot: {ticker} ({cik})")
    print(f"{'═'*72}")
    _print_filings(ticker, filings)
    _print_financials(ticker, financials)
    print(f"\n{'═'*72}\n")
    return result


def _parse_args(argv: List[str]) -> Tuple[str, str, Optional[List[str]], bool]:
    args = [a for a in argv if not a.startswith('--')]
    as_json = '--json' in argv

    if not args:
        print(__doc__)
        sys.exit(1)
    ticker = args[0].upper()

    if '--filings' in argv:
        idx = argv.index('--filings')
        # Optional form-type list right after --filings
        types = None
        if idx + 1 < len(argv) and not argv[idx + 1].startswith('--'):
            types = [t.strip().upper() for t in argv[idx + 1].split(',')]
        return ticker, 'filings', types, as_json
    if '--form4' in argv:
        return ticker, 'form4', None, as_json
    if '--financials' in argv:
        return ticker, 'financials', None, as_json
    if '--13f' in argv:
        return ticker, '13f', None, as_json
    return ticker, 'summary', None, as_json


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '-h' in argv or '--help' in argv:
        print(__doc__)
        return 0
    ticker, mode, form_types, as_json = _parse_args(argv)

    if mode == 'summary':
        result = summarize(ticker, as_json=as_json)
    elif mode == 'filings':
        filings = get_filings(ticker, form_types=form_types, limit=20)
        result = {'ticker': ticker, 'filings': filings}
        if not as_json:
            _print_filings(ticker, filings)
    elif mode == 'form4':
        trades = get_form4_trades(ticker, limit=30)
        result = {'ticker': ticker, 'form4': trades}
        if not as_json:
            print(f"\n  Form 4 (insider) filings for {ticker}:")
            _print_filings(ticker, trades)
    elif mode == 'financials':
        fin = get_key_financials(ticker)
        result = {'ticker': ticker, 'key_financials': fin}
        if not as_json:
            _print_financials(ticker, fin)
    elif mode == '13f':
        thirteen = get_13f_filings(ticker, limit=20)
        result = {'ticker': ticker, 'filings_13f': thirteen}
        if not as_json:
            _print_filings(ticker, thirteen)
    else:
        result = {}

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
