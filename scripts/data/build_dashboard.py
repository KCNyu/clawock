#!/usr/bin/env python3
"""
build_dashboard.py — aggregates portfolio.json + snapshots + plans into a single
JSON the static dashboard (docs/ via Jekyll Pages) consumes.

Output: assets/data/dashboard.json

Run after each portfolio mutation (cron commit) so Pages stays fresh.
"""
import csv
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Strict YYYY-MM-DD.json — rejects baselines/backups/archives that share the
# snapshots dir (e.g. 2026-05-16-saturday-baseline.json caused duplicate 5-16
# rows in the equity curve before this filter was added).
SNAPSHOT_FNAME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.json$')

WS_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = WS_ROOT / 'assets' / 'data'
OUT_FILE = OUT_DIR / 'dashboard.json'

# ── Anti-bloat caps ──────────────────────────────────────────────────────
# Dashboard only embeds the most recent snapshots + plan summaries.
# Older history lives on disk; if dashboard ever needs full history, load lazily.
MAX_SNAPSHOTS_EMBEDDED = 90        # ≈ 4 months of trading days (kept in dashboard.json)
MAX_PLANS_EMBEDDED     = 5         # last 5 plans (each can be a few KB)
MAX_PLAN_BYTES         = 4096      # cap each plan blob to 4KB; if larger, just keep summary
MAX_OUT_BYTES          = 200_000   # final dashboard.json hard cap (~200KB)


def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'  warn: failed to load {path}: {e}', file=sys.stderr)
        return None


def trim_holding(h, currency):
    """Trim a holding dict to UI-relevant fields."""
    return {
        'ticker': h.get('ticker') or h.get('code'),
        'name': h.get('name') or h.get('stock_name', ''),
        'currency': currency,
        'shares': h.get('shares', 0),
        'cost_basis': round(h.get('cost_basis') or 0, 4),
        'current_price': round(h.get('current_price') or 0, 4),
        'current_value': round(h.get('current_value') or 0, 2),
        'today_change': round(h.get('today_change') or 0, 2),
        'today_change_pct': round(h.get('today_change_pct') or 0, 2),
        'day_high': round(h.get('day_high') or 0, 4),
        'day_low': round(h.get('day_low') or 0, 4),
        'pnl_abs': round(h.get('pnl_abs') or 0, 2),
        'pnl_percent': round(h.get('pnl_percent') or 0, 2),
        'is_active': (h.get('shares') or 0) > 0,
        'trades_count': len(h.get('trades') or []),
    }


def compute_hhi(holdings):
    """HHI = Σ weight²; return (hhi, top2, weights[], total_value)."""
    active = [h for h in holdings if h['is_active'] and h['current_value'] > 0]
    total = sum(h['current_value'] for h in active)
    if total <= 0:
        return {'hhi': 0, 'top2': 0, 'positions': [], 'total': 0}
    weights = []
    for h in active:
        w = h['current_value'] / total
        weights.append({
            'ticker': h['ticker'],
            'name': h['name'],
            'value': h['current_value'],
            'weight': round(w, 4),
        })
    weights.sort(key=lambda x: -x['weight'])
    hhi = round(sum(w['weight'] ** 2 for w in weights), 4)
    top2 = round(sum(w['weight'] for w in weights[:2]), 4)
    return {'hhi': hhi, 'top2': top2, 'positions': weights, 'total': round(total, 2)}


def hhi_verdict(hhi, top2):
    if hhi < 0.15 and top2 < 0.40:
        return {'level': 'healthy', 'label': '健康', 'color': '#4ade80'}
    if hhi < 0.25 and top2 < 0.60:
        return {'level': 'moderate', 'label': '偏集中', 'color': '#facc15'}
    if hhi < 0.40 and top2 < 0.75:
        return {'level': 'concentrated', 'label': '集中风险', 'color': '#fb923c'}
    return {'level': 'danger', 'label': '危险集中', 'color': '#ef4444'}


def build_holdings_history(snapshot_paths, days=10):
    """Extract per-ticker current_price series from the last N snapshots.

    Returns { ticker: [price_or_null, ...] } in chronological order. Tickers
    that are missing from a given day get null, so the array length is constant
    and the frontend can simply slice it.

    Used by the holdings table to render a 7d sparkline next to each row.
    """
    paths = snapshot_paths[-days:]
    out = {}
    for p in paths:
        d = load_json(p)
        if not d:
            continue
        for region in ('us_stocks', 'hk_stocks'):
            for h in (d.get('portfolios', {}).get(region, {}).get('holdings') or []):
                t = h.get('ticker') or h.get('code')
                if not t:
                    continue
                out.setdefault(t, []).append(h.get('current_price'))
    # Right-align: if a ticker appeared late, pad the head with None so length matches paths
    n = len(paths)
    for t, arr in out.items():
        if len(arr) < n:
            arr[:0] = [None] * (n - len(arr))
        out[t] = arr[-n:]  # safety cap
    return out


def _aggregate_indices(us_pf, hk_pf):
    """Combine US + HK leg indices into one flat dict for the dashboard.

    portfolio.json stores them per-leg (legacy: only US leg was read), so HK
    indices (HSI/HSTECH) were invisible to the frontend even though they're
    fetched daily by analyze_hk_stocks.py. Normalize key shape to:

        { TICKER: {name, price, prev_close, change_pct, source} }

    where TICKER is NDX/SPX/HSI/HSTECH/etc.
    """
    out = {}
    for leg in (us_pf or {}, hk_pf or {}):
        idx = leg.get('indices_snapshot') or {}
        for k, v in idx.items():
            if not isinstance(v, dict):
                continue
            # Different sources use chg_pct vs change_pct — normalize
            normalized = {
                'name':       v.get('name', k),
                'price':      v.get('price'),
                'prev_close': v.get('prev_close'),
                'change_pct': v.get('change_pct') if v.get('change_pct') is not None else v.get('chg_pct'),
                'source':     v.get('source', 'unknown'),
            }
            out[k] = normalized
    return out


def load_snapshots():
    """Returns recent-N snapshot summaries (NOT full holdings). Capped at MAX_SNAPSHOTS_EMBEDDED."""
    paths = sorted(
        p for p in glob.glob(str(WS_ROOT / 'memory' / 'snapshots' / '*.json'))
        if SNAPSHOT_FNAME_RE.match(os.path.basename(p))
    )
    # Keep only the most recent N — chronological order so dashboard line chart still ascends
    paths = paths[-MAX_SNAPSHOTS_EMBEDDED:]
    results = []
    for p in paths:
        d = load_json(p)
        if not d:
            continue
        fname = os.path.basename(p)
        # filename: YYYY-MM-DD.json or YYYY-MM-DD-tag.json
        date = fname.split('.')[0].split('-')
        date = '-'.join(date[:3]) if len(date) >= 3 else fname
        pf = d.get('portfolios', {})
        us = pf.get('us_stocks', {})
        hk = pf.get('hk_stocks', {})
        us_val = us.get('total_current_value', 0) or 0
        hk_val = hk.get('total_current_value', 0) or 0
        us_real = us.get('realized_pnl', 0) or 0
        hk_real = hk.get('realized_pnl', 0) or 0
        results.append({
            'date': date,
            'file': fname,
            'us_total_value': us_val,
            'us_total_cost': us.get('total_cost', 0),
            'us_total_pnl': us.get('total_pnl', 0),
            'us_today_change': us.get('today_total_change', 0),
            'us_realized': us_real,
            'us_equity': round(us_val + us_real, 2),
            'hk_total_value': hk_val,
            'hk_total_cost': hk.get('total_cost', 0),
            'hk_total_pnl': hk.get('total_pnl', 0),
            'hk_today_change': hk.get('today_total_change', 0),
            'hk_realized': hk_real,
            'hk_equity': round(hk_val + hk_real, 2),
        })
    return results


def load_plans():
    """Recent-N plan summaries. Large plans get trimmed to bullet list."""
    paths = sorted(glob.glob(str(WS_ROOT / 'memory' / '*-plan.json')))
    paths = paths[-MAX_PLANS_EMBEDDED:]
    results = []
    for p in paths:
        d = load_json(p)
        if not d:
            continue
        fname = os.path.basename(p)
        date = fname.replace('-plan.json', '')
        raw = json.dumps(d, ensure_ascii=False)
        if len(raw.encode('utf-8')) > MAX_PLAN_BYTES:
            # Plan too big — keep only top-level summary fields (actions count, tldr)
            actions = d.get('actions') or d.get('plan') or []
            d = {
                'date': d.get('date', date),
                'actions_count': len(actions),
                'tldr': d.get('summary') or d.get('tldr') or '',
                'has_retrospective': bool(d.get('retrospective')),
                'context': d.get('context', {}),
                'truncated': True,
                'original_bytes': len(raw),
            }
        results.append({'date': date, 'file': fname, 'plan': d})
    return results


def total_plans_count():
    return len(glob.glob(str(WS_ROOT / 'memory' / '*-plan.json')))


def total_snapshots_count():
    return sum(
        1 for p in glob.glob(str(WS_ROOT / 'memory' / 'snapshots' / '*.json'))
        if SNAPSHOT_FNAME_RE.match(os.path.basename(p))
    )


# ── Dashboard v2 NEW field computers ─────────────────────────────────────
# Each function MUST swallow internal exceptions and return its empty/null
# default so a partial failure can't take down the whole dashboard build.

def _pct_change(curr, prev):
    """(curr - prev) / prev * 100, rounded to 2 decimals; None if prev <= 0 or invalid."""
    try:
        if prev is None or curr is None:
            return None
        prev = float(prev)
        if prev == 0:
            return None
        return round((float(curr) - prev) / abs(prev) * 100, 2)
    except Exception:
        return None


def compute_delta(snapshots):
    """Equity rolling-window % change vs today.

    snapshots is the same list build_dashboard already prepares: ascending date,
    so today = snapshots[-1], yesterday = snapshots[-2], etc.
    """
    empty = {
        'us': {'today_pct': None, '7d_pct': None, '30d_pct': None},
        'hk': {'today_pct': None, '7d_pct': None, '30d_pct': None},
    }
    try:
        if not snapshots:
            return empty
        n = len(snapshots)
        today = snapshots[-1]

        def at(offset_back, key):
            idx = n - 1 - offset_back
            if idx < 0:
                return None
            return snapshots[idx].get(key)

        def region(value_key):
            today_v = today.get(value_key)
            return {
                'today_pct': _pct_change(today_v, at(1, value_key)) if n >= 2 else None,
                '7d_pct':    _pct_change(today_v, at(7, value_key)) if n >= 8 else None,
                '30d_pct':   _pct_change(today_v, at(30, value_key)) if n >= 31 else None,
            }
        return {
            'us': region('us_equity'),
            'hk': region('hk_equity'),
        }
    except Exception as e:
        print(f'  warn: compute_delta failed: {e}', file=sys.stderr)
        return empty


def compute_today_movers(us_h, hk_h):
    """abs(today_change_pct) >= 3.0 holdings across both regions, top 10 by abs."""
    try:
        items = []
        for h in (us_h or []):
            pct = h.get('today_change_pct')
            if pct is None:
                continue
            if abs(pct) >= 3.0:
                items.append({
                    'ticker': h.get('ticker'),
                    'name': h.get('name', ''),
                    'region': 'us',
                    'today_change_pct': round(pct, 2),
                    'current_price': h.get('current_price'),
                })
        for h in (hk_h or []):
            pct = h.get('today_change_pct')
            if pct is None:
                continue
            if abs(pct) >= 3.0:
                items.append({
                    'ticker': h.get('ticker'),
                    'name': h.get('name', ''),
                    'region': 'hk',
                    'today_change_pct': round(pct, 2),
                    'current_price': h.get('current_price'),
                })
        items.sort(key=lambda x: -abs(x['today_change_pct']))
        return items[:10]
    except Exception as e:
        print(f'  warn: compute_today_movers failed: {e}', file=sys.stderr)
        return []


def _latest_brief_context():
    """Return (path, dict) of newest memory/.tmp/brief-context-*.json by mtime, or (None, None)."""
    try:
        paths = glob.glob(str(WS_ROOT / 'memory' / '.tmp' / 'brief-context-*.json'))
        if not paths:
            return None, None
        latest = max(paths, key=os.path.getmtime)
        return latest, load_json(latest)
    except Exception as e:
        print(f'  warn: _latest_brief_context failed: {e}', file=sys.stderr)
        return None, None


def load_sector_scan():
    """Read the freshest sector-scan-*.json written by daily-deep-brief LLM.

    LLM writes today's sector overview (theme / top movers / self position /
    attribution / narrative) to memory/.tmp/sector-scan-{date}.json after
    running Step 3 板块全景 tavily-search. We pick the newest by mtime to
    cover overnight edge cases. Non-fatal on any error (returns {}).
    """
    try:
        paths = glob.glob(str(WS_ROOT / 'memory' / '.tmp' / 'sector-scan-*.json'))
        if not paths:
            return {}
        latest = max(paths, key=os.path.getmtime)
        data = load_json(latest)
        if not isinstance(data, dict):
            return {}
        # Stamp where it came from so frontend can show "as of {date}"
        data.setdefault('_source', os.path.basename(latest))
        return data
    except Exception as e:
        print(f'  warn: load_sector_scan failed: {e}', file=sys.stderr)
        return {}


def load_tmp_sidecar(prefix, max_age_days=None):
    """Freshest memory/.tmp/{prefix}-*.json by mtime, stamped with _source + _stale.

    Used for LLM-narrative sidecars the cron AGENT writes during Step 3 (behavioral
    review / bear cases / status banner / movers attribution). The LLM runs inside
    the gateway/GHA where API keys live — those keys NEVER touch these files or
    dashboard.json (published to public Pages), only the narrative text does.
    Non-fatal on any error (returns {}). If max_age_days is set, marks _stale=True
    when the file's mtime is older, so the frontend can grey it out instead of
    showing day-old critique as if it were current.
    """
    try:
        paths = glob.glob(str(WS_ROOT / 'memory' / '.tmp' / f'{prefix}-*.json'))
        if not paths:
            return {}
        latest = max(paths, key=os.path.getmtime)
        data = load_json(latest)
        if not isinstance(data, dict):
            return {}
        data.setdefault('_source', os.path.basename(latest))
        if max_age_days is not None:
            age_days = (time.time() - os.path.getmtime(latest)) / 86400.0
            data['_stale'] = age_days > max_age_days
        return data
    except Exception as e:
        print(f'  warn: load_tmp_sidecar({prefix}) failed: {e}', file=sys.stderr)
        return {}


_REVIEW_TAGS = {'edge', 'bias', 'warning'}
_SUSPECT_DOLLAR = re.compile(r'[\$＄]\s?\d')  # raw $amount


def _clean_str(v, maxlen):
    """Return a trimmed, length-capped non-empty str, else None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s[:maxlen] if s else None


def validate_insights(data, known_tickers):
    """Schema + sanity gate for the agent-written daily insights sidecar.

    The sidecar is LLM-authored, so anything malformed or hallucinated must be
    DROPPED here (→ card hides) rather than published to the public dashboard.json.
    Bad entries are dropped individually; a field only survives if its core content
    is present and sane. `known_tickers` (live holdings) blocks bear_cases on names
    that aren't even in the book. Returns the cleaned, render-ready dict.
    """
    out = {'behavioral_review': None, 'bear_cases': [], 'hidden_concentration': None}
    if not isinstance(data, dict):
        return out
    # behavioral_review — verdict + tagged points; calibration is %-based, so a raw
    # $amount in a review point is a hallucination → drop that point.
    br = data.get('behavioral_review')
    if isinstance(br, dict):
        verdict = _clean_str(br.get('verdict'), 120)
        pts = []
        for p in (br.get('points') or [])[:8]:
            if not isinstance(p, dict):
                continue
            txt = _clean_str(p.get('text'), 220)
            if not txt:
                continue
            if _SUSPECT_DOLLAR.search(txt):
                print(f'  warn: insights dropped review point w/ suspect $amount: {txt[:42]}', file=sys.stderr)
                continue
            tag = (p.get('tag') or '').strip().lower()
            pts.append({'text': txt, 'tag': tag if tag in _REVIEW_TAGS else 'bias'})
        if verdict and pts:
            out['behavioral_review'] = {'verdict': verdict, 'points': pts}
    # bear_cases — ticker must be a real holding
    for c in (data.get('bear_cases') or [])[:5]:
        if not isinstance(c, dict):
            continue
        tk = _clean_str(c.get('ticker'), 12)
        thesis = _clean_str(c.get('thesis'), 220)
        if not tk or not thesis:
            continue
        if known_tickers and tk not in known_tickers:
            print(f'  warn: insights dropped bear_case for unknown ticker {tk}', file=sys.stderr)
            continue
        out['bear_cases'].append({
            'ticker': tk,
            'thesis': thesis,
            'falsifier': _clean_str(c.get('falsifier'), 160) or '',
            'watch': _clean_str(c.get('watch'), 120) or '',
        })
    # hidden_concentration — needs headline + a plausible 0-100 exposure_pct
    hc = data.get('hidden_concentration')
    if isinstance(hc, dict):
        headline = _clean_str(hc.get('headline'), 120)
        try:
            pct = float(hc.get('exposure_pct'))
        except (TypeError, ValueError):
            pct = None
        if headline and pct is not None and 0 <= pct <= 100:
            out['hidden_concentration'] = {
                'headline': headline,
                'factor': _clean_str(hc.get('factor'), 40) or '',
                'exposure_pct': round(pct),
                'detail': _clean_str(hc.get('detail'), 220) or '',
            }
    return out


def validate_intraday_insights(data, known_tickers):
    """Schema + sanity gate for the intraday sidecar (status_banner + per-mover
    attribution). Mover notes only survive for tickers that actually exist in the
    book. Returns {status_banner, movers}."""
    out = {'status_banner': None, 'movers': {}}
    if not isinstance(data, dict):
        return out
    out['status_banner'] = _clean_str(data.get('status_banner'), 160)
    mv = data.get('movers')
    if isinstance(mv, dict):
        for tk, note in mv.items():
            tkc = _clean_str(tk, 12)
            notec = _clean_str(note, 120)
            if not tkc or not notec:
                continue
            if known_tickers and tkc not in known_tickers:
                continue
            out['movers'][tkc] = notec
    return out


# Tickers we treat as leveraged ETFs even when context doesn't tag them.
_LEVERAGED_TICKERS = {'SOXL', 'TQQQ', 'MSFU', 'PLTU', 'ROBN', 'RKLX', '07226'}


def extract_anomalies(brief_ctx, us_h, hk_h):
    """Risk signals derived from the latest brief-context.

    Recognized types:
      - rsi_overbought          (rsi >= 70 in any embedded indicator block)
      - peer_divergence         (divergence_signal present, severity by gap pp)
      - high_weight_loss        (concentration weight >= 25% AND holding pnl_percent <= -10)
      - leveraged_etf_stop      (leveraged ticker w/ self_pnl_pct <= -15 OR today_change_pct <= -8)
      - no_context              (single entry, fallback when no context file found)
    """
    try:
        if not brief_ctx:
            return [{
                'type': 'no_context',
                'ticker': '',
                'detail': 'no brief-context-*.json found in memory/.tmp/',
                'severity': 'low',
            }]
        out = []
        holdings_by_ticker = {}
        for h in (us_h or []):
            holdings_by_ticker[str(h.get('ticker') or '').upper()] = h
        for h in (hk_h or []):
            holdings_by_ticker[str(h.get('ticker') or '')] = h

        # NOTE: peer_divergence is no longer injected into anomalies. It now has
        # its own 『同行背离 Peer Divergence』card (Market tab) fed by the single
        # source extract_peer_divergence() below — avoids the old double-compute +
        # the UI-layer filter that hid it. holdings_by_ticker above is still used
        # by the high_weight_loss / leveraged guards.

        # high_weight_loss anomalies (concentration top tickers w/ deep loss)
        conc = brief_ctx.get('concentration') or {}
        for region in ('us', 'hk'):
            region_conc = conc.get(region) or {}
            weights = region_conc.get('weights') or []
            for w in weights:
                tk = str(w.get('ticker') or '')
                weight_pct = w.get('weight_pct') or 0
                if weight_pct < 25:
                    continue
                h = holdings_by_ticker.get(tk.upper()) or holdings_by_ticker.get(tk)
                if not h:
                    continue
                pnl_pct = h.get('pnl_percent')
                if pnl_pct is not None and pnl_pct <= -10:
                    sev = 'high' if (weight_pct >= 40 or pnl_pct <= -20) else 'medium'
                    out.append({
                        'type': 'high_weight_loss',
                        'ticker': tk,
                        'detail': f'weight {weight_pct:.1f}% + pnl {pnl_pct:.1f}%',
                        'severity': sev,
                    })

        # leveraged_etf_stop anomalies — read from the same brief peer_scan snapshot as
        # extract_peer_divergence(). The peer_divergence refactor (3f507d3) dropped this
        # definition but left the loop, so the whole function raised NameError and silently
        # produced no anomalies. (2026-05-30 fix)
        peer_scan = brief_ctx.get('peer_scan') or {}
        peer_items = peer_scan.items() if isinstance(peer_scan, dict) else []
        for ticker, v in peer_items:
            tk_str = str(ticker or '').upper()
            if tk_str not in _LEVERAGED_TICKERS:
                continue
            if not isinstance(v, dict):
                continue
            # 优先用 portfolio 实时 pnl/today，brief peer_scan 快照可能陈旧（5/28 错位价残留会触发假止损）。
            h_live = holdings_by_ticker.get(tk_str) or holdings_by_ticker.get(str(ticker))
            if isinstance(h_live, dict) and h_live.get('pnl_percent') is not None:
                self_pnl = h_live.get('pnl_percent')
                self_today = h_live.get('today_change_pct')
            else:
                self_pnl = v.get('self_pnl_pct')
                self_today = v.get('self_pct_1d')
            triggered = False
            detail_bits = []
            if isinstance(self_pnl, (int, float)) and self_pnl <= -15:
                triggered = True
                detail_bits.append(f'pnl {self_pnl:.1f}%')
            if isinstance(self_today, (int, float)) and self_today <= -8:
                triggered = True
                detail_bits.append(f'today {self_today:.1f}%')
            if triggered:
                sev = 'high' if (isinstance(self_pnl, (int, float)) and self_pnl <= -25) else 'medium'
                out.append({
                    'type': 'leveraged_etf_stop',
                    'ticker': str(ticker),
                    'detail': 'leveraged ETF: ' + ', '.join(detail_bits),
                    'severity': sev,
                })

        # rsi_overbought — only fire if brief_ctx carries an rsi block; current
        # context files don't, but keep the scanner so future preflight runs work.
        def _scan_rsi(node):
            if isinstance(node, dict):
                tk = node.get('ticker') or node.get('symbol')
                rsi = node.get('rsi') or node.get('rsi_14') or node.get('RSI')
                if tk and isinstance(rsi, (int, float)) and rsi >= 70:
                    out.append({
                        'type': 'rsi_overbought',
                        'ticker': str(tk),
                        'detail': f'RSI {rsi:.1f} >= 70',
                        'severity': 'high' if rsi >= 80 else 'medium',
                    })
                for v in node.values():
                    _scan_rsi(v)
            elif isinstance(node, list):
                for it in node:
                    _scan_rsi(it)
        try:
            _scan_rsi(brief_ctx.get('us_fundamentals'))
            _scan_rsi(brief_ctx.get('indicators'))
        except Exception:
            pass

        return out
    except Exception as e:
        print(f'  warn: extract_anomalies failed: {e}', file=sys.stderr)
        return []


def extract_peer_divergence(brief_ctx, us_h=None, hk_h=None):
    """List of divergence_signal=true peer scan rows from brief context.

    与 extract_anomalies 同源（都读 brief peer_scan 快照），故套同样的实时守卫：
    peer 报价缺失(0.0) 或快照 self 与 portfolio 实时 today_change 符号相反 → 跳过，
    避免 5/28 错位价残留泄漏到 dashboard 的背离卡。
    """
    try:
        if not brief_ctx:
            return []
        holdings_by_ticker = {}
        for h in (us_h or []):
            holdings_by_ticker[str(h.get('ticker') or '').upper()] = h
        for h in (hk_h or []):
            holdings_by_ticker[str(h.get('ticker') or '')] = h
        peer_scan = brief_ctx.get('peer_scan') or {}
        if isinstance(peer_scan, dict):
            items = peer_scan.items()
        elif isinstance(peer_scan, list):
            items = [(p.get('ticker'), p) for p in peer_scan]
        else:
            return []
        out = []
        for ticker, v in items:
            if not isinstance(v, dict):
                continue
            if not v.get('divergence_signal'):
                continue
            self_pct = v.get('self_pct_1d')
            best_peer = None
            best_peer_name = None
            peer_pct = None
            best_gap = None
            for p in (v.get('listed_peers') or []):
                pp = p.get('pct_1d')
                if pp is None or self_pct is None:
                    continue
                gap = pp - self_pct  # peer beating self → positive
                if best_gap is None or abs(gap) > abs(best_gap):
                    best_gap = gap
                    best_peer = p.get('ticker')
                    best_peer_name = p.get('name')
                    peer_pct = pp
            try:
                self_pct_v = round(float(self_pct), 2) if self_pct is not None else None
            except Exception:
                self_pct_v = None
            try:
                peer_pct_v = round(float(peer_pct), 2) if peer_pct is not None else None
            except Exception:
                peer_pct_v = None
            try:
                div_pp = round(float(best_gap), 2) if best_gap is not None else None
            except Exception:
                div_pp = None
            # 实时守卫（同 extract_anomalies）：peer 报价缺失(0.0) 或快照陈旧(与实时今日反号) → 跳过
            if peer_pct_v == 0.0:
                continue
            h_live = holdings_by_ticker.get(str(ticker).upper()) or holdings_by_ticker.get(str(ticker))
            live_today = h_live.get('today_change_pct') if isinstance(h_live, dict) else None
            if (isinstance(live_today, (int, float)) and isinstance(self_pct_v, (int, float))
                    and live_today * self_pct_v < 0 and abs(live_today - self_pct_v) >= 4):
                continue
            out.append({
                'ticker': str(ticker),
                'self_pct_1d': self_pct_v,
                'best_peer': best_peer or '',
                'best_peer_name': best_peer_name or '',
                'peer_pct_1d': peer_pct_v,
                'divergence_pp': div_pp,
            })
        return out
    except Exception as e:
        print(f'  warn: extract_peer_divergence failed: {e}', file=sys.stderr)
        return []


_CALIB_BUCKETS = ['cut', 'trim_on_rebound', 'hold_and_watch', 't_only', 'add_only_on_trigger']
_CALIB_BANDS = [
    ('0-50%',  0.0, 0.5),
    ('50-60%', 0.5, 0.6),
    ('60-70%', 0.6, 0.7),
    ('70-80%', 0.7, 0.8),
    ('80-100%', 0.8, 1.0001),
]


def _read_calibration_rows():
    """Returns list of dict rows from memory/calibration.csv, or []."""
    path = WS_ROOT / 'memory' / 'calibration.csv'
    try:
        if not path.exists():
            return []
        with open(path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        print(f'  warn: _read_calibration_rows failed: {e}', file=sys.stderr)
        return []


def _to_float(s):
    try:
        if s is None or s == '':
            return None
        return float(s)
    except Exception:
        return None


def compute_calibration():
    """Brier + per-band + per-bucket accuracy from calibration.csv (resolved rows only, ≤30d)."""
    bands_empty = [{'band': b[0], 'n': 0, 'actual_win_rate': 0.0} for b in _CALIB_BANDS]
    per_bucket_empty = {b: {'n': 0, 'win_rate': 0.0} for b in _CALIB_BUCKETS}
    empty = {
        'brier_30d': None,
        'samples': 0,
        'bands': bands_empty,
        'per_bucket': per_bucket_empty,
        'vs_baseline': None,
    }
    try:
        rows = _read_calibration_rows()
        if not rows:
            return empty
        # Resolved = outcome in {win, loss, flat} (skip pending/blank).
        # 30d window: keep rows whose plan_date is within 30 days of today.
        today = datetime.now(timezone.utc).date()
        resolved = []
        for r in rows:
            outcome = (r.get('outcome') or '').strip().lower()
            if outcome not in ('win', 'loss', 'flat'):
                continue
            try:
                pd = datetime.strptime(r.get('plan_date', '')[:10], '%Y-%m-%d').date()
            except Exception:
                continue
            if (today - pd).days > 30:
                continue
            resolved.append((r, outcome))

        n = len(resolved)
        if n == 0:
            return empty

        # Brier: (confidence - actual)^2, actual ∈ {1 for win, 0 for loss/flat}
        brier_sum = 0.0
        brier_count = 0
        for r, outcome in resolved:
            conf = _to_float(r.get('confidence'))
            if conf is None:
                continue
            actual = 1.0 if outcome == 'win' else 0.0
            brier_sum += (conf - actual) ** 2
            brier_count += 1
        brier_30d = round(brier_sum / brier_count, 4) if (brier_count >= 5) else None

        # Bands
        bands_out = []
        for label, lo, hi in _CALIB_BANDS:
            wins = 0
            total = 0
            for r, outcome in resolved:
                conf = _to_float(r.get('confidence'))
                if conf is None:
                    continue
                if lo <= conf < hi:
                    total += 1
                    if outcome == 'win':
                        wins += 1
            win_rate = round(wins / total, 4) if total else 0.0
            bands_out.append({'band': label, 'n': total, 'actual_win_rate': win_rate})

        # Per-bucket
        per_bucket = {}
        for b in _CALIB_BUCKETS:
            wins = 0
            total = 0
            for r, outcome in resolved:
                if (r.get('bucket') or '').strip() == b:
                    total += 1
                    if outcome == 'win':
                        wins += 1
            win_rate = round(wins / total, 4) if total else 0.0
            per_bucket[b] = {'n': total, 'win_rate': win_rate}

        # vs_baseline: LLM decision win-rate vs passive "hold everything" baseline
        # (wins whenever the asset rose). Regime-robust edge check. Recover the asset's
        # return from the stored benefit% (pnl_5d): benefit = ret for hold/add, -ret for
        # cut/trim. alpha_pp < 0 = active calls did worse than doing nothing.
        _SELL = {'cut', 'trim_on_rebound'}
        llm_w = base_w = base_n = 0
        for r, outcome in resolved:
            ben = _to_float(r.get('pnl_5d'))
            if ben is None:
                continue
            ret = -ben if (r.get('bucket') or '').strip() in _SELL else ben
            base_n += 1
            llm_w += 1 if outcome == 'win' else 0
            base_w += 1 if ret > 0 else 0
        vs_baseline = None
        if base_n:
            llm_wr = llm_w / base_n
            base_wr = base_w / base_n
            vs_baseline = {
                'n': base_n,
                'llm_win_rate': round(llm_wr, 4),
                'hold_baseline_win_rate': round(base_wr, 4),
                'alpha_pp': round((llm_wr - base_wr) * 100, 1),
            }

        return {
            'brier_30d': brier_30d,
            'samples': n,
            'bands': bands_out,
            'per_bucket': per_bucket,
            'vs_baseline': vs_baseline,
        }
    except Exception as e:
        print(f'  warn: compute_calibration failed: {e}', file=sys.stderr)
        return empty


def recent_actions_from_csv(limit=20):
    """Last `limit` rows of calibration.csv, most recent plan_date first."""
    try:
        rows = _read_calibration_rows()
        if not rows:
            return []
        # Sort by plan_date desc (string sort works for YYYY-MM-DD); stable for ties.
        rows.sort(key=lambda r: r.get('plan_date', ''), reverse=True)
        out = []
        for r in rows[:limit]:
            outcome = (r.get('outcome') or '').strip().lower()
            if outcome not in ('win', 'loss', 'flat', 'pending'):
                outcome = 'pending'
            out.append({
                'date': r.get('plan_date', ''),
                'ticker': r.get('ticker', ''),
                'bucket': r.get('bucket', ''),
                'confidence': _to_float(r.get('confidence')),
                'trigger_type': r.get('trigger_type', ''),
                'outcome': outcome,
                'pnl_5d': _to_float(r.get('pnl_5d')),
                'followed': (r.get('followed') or 'unknown').strip().lower(),
                'driven_by': (r.get('driven_by') or '').strip().lower(),
            })
        return out
    except Exception as e:
        print(f'  warn: recent_actions_from_csv failed: {e}', file=sys.stderr)
        return []


_CALIB_TRIGGERS = ['price_above', 'price_below', 'open', 'manual', 'index_breakdown']


def compute_calibration_by_trigger(window_days=30):
    """Per-trigger_type win/loss/pending breakdown — answers 'which trigger
    pattern is bleeding'. Counts pending separately (gives texture beyond 30d
    Brier which only sees resolved rows).
    """
    empty = {t: {'n_resolved': 0, 'n_pending': 0, 'wins': 0, 'losses': 0,
                 'win_rate': None, 'avg_confidence': None} for t in _CALIB_TRIGGERS}
    try:
        rows = _read_calibration_rows()
        if not rows:
            return empty
        today = datetime.now(timezone.utc).date()
        out = {t: {'n_resolved': 0, 'n_pending': 0, 'wins': 0, 'losses': 0,
                   'conf_sum': 0.0, 'conf_n': 0} for t in _CALIB_TRIGGERS}
        for r in rows:
            try:
                pd = datetime.strptime(r.get('plan_date', '')[:10], '%Y-%m-%d').date()
            except Exception:
                continue
            if (today - pd).days > window_days:
                continue
            trig = (r.get('trigger_type') or '').strip()
            if trig not in out:
                continue
            outcome = (r.get('outcome') or '').strip().lower()
            conf = _to_float(r.get('confidence'))
            if conf is not None:
                out[trig]['conf_sum'] += conf
                out[trig]['conf_n'] += 1
            if outcome in ('win', 'loss', 'flat'):
                out[trig]['n_resolved'] += 1
                if outcome == 'win':
                    out[trig]['wins'] += 1
                elif outcome == 'loss':
                    out[trig]['losses'] += 1
            elif outcome == 'pending':
                out[trig]['n_pending'] += 1
        result = {}
        for t, agg in out.items():
            decided = agg['wins'] + agg['losses']
            wr = round(agg['wins'] / decided, 4) if decided else None
            avg_c = round(agg['conf_sum'] / agg['conf_n'], 3) if agg['conf_n'] else None
            result[t] = {
                'n_resolved': agg['n_resolved'],
                'n_pending': agg['n_pending'],
                'wins': agg['wins'],
                'losses': agg['losses'],
                'win_rate': wr,
                'avg_confidence': avg_c,
            }
        return result
    except Exception as e:
        print(f'  warn: compute_calibration_by_trigger failed: {e}', file=sys.stderr)
        return empty


_CALIB_DRIVERS = ['technical', 'catalyst', 'sentiment', 'influencer', 'macro', 'peer']


def compute_calibration_by_driver(window_days=30):
    """Per-driven_by win/loss/pending breakdown — answers 'which DATA SOURCE has edge'.
    driven_by attributes each call to technical/catalyst/sentiment/influencer/macro/peer.
    This is the number that tells us whether the news feed (sentiment/influencer/catalyst)
    actually beats coin-flip vs plain technical calls (2026-05-30). Mirrors
    compute_calibration_by_trigger; rows with blank driven_by (legacy) are skipped."""
    empty = {t: {'n_resolved': 0, 'n_pending': 0, 'wins': 0, 'losses': 0,
                 'win_rate': None, 'avg_confidence': None} for t in _CALIB_DRIVERS}
    try:
        rows = _read_calibration_rows()
        if not rows:
            return empty
        today = datetime.now(timezone.utc).date()
        out = {t: {'n_resolved': 0, 'n_pending': 0, 'wins': 0, 'losses': 0,
                   'conf_sum': 0.0, 'conf_n': 0} for t in _CALIB_DRIVERS}
        for r in rows:
            try:
                pd = datetime.strptime(r.get('plan_date', '')[:10], '%Y-%m-%d').date()
            except Exception:
                continue
            if (today - pd).days > window_days:
                continue
            drv = (r.get('driven_by') or '').strip()
            if drv not in out:
                continue
            outcome = (r.get('outcome') or '').strip().lower()
            conf = _to_float(r.get('confidence'))
            if conf is not None:
                out[drv]['conf_sum'] += conf
                out[drv]['conf_n'] += 1
            if outcome in ('win', 'loss', 'flat'):
                out[drv]['n_resolved'] += 1
                if outcome == 'win':
                    out[drv]['wins'] += 1
                elif outcome == 'loss':
                    out[drv]['losses'] += 1
            elif outcome == 'pending':
                out[drv]['n_pending'] += 1
        result = {}
        for t, agg in out.items():
            decided = agg['wins'] + agg['losses']
            wr = round(agg['wins'] / decided, 4) if decided else None
            avg_c = round(agg['conf_sum'] / agg['conf_n'], 3) if agg['conf_n'] else None
            result[t] = {
                'n_resolved': agg['n_resolved'],
                'n_pending': agg['n_pending'],
                'wins': agg['wins'],
                'losses': agg['losses'],
                'win_rate': wr,
                'avg_confidence': avg_c,
            }
        return result
    except Exception as e:
        print(f'  warn: compute_calibration_by_driver failed: {e}', file=sys.stderr)
        return empty


def compute_weight_confidence(portfolio, window_days=30):
    """Per-ticker current_weight × avg_confidence (last N days), to spot
    'high weight + low confidence' red flags at a glance.
    Output: list[{ticker, region, weight_pct, avg_confidence, n_actions, quadrant}]
    quadrant ∈ {high_risk, conviction, low_conv_small, comfort}:
      high_risk      = weight ≥ 0.20 AND conf < 0.65   ← user's red zone
      conviction     = weight ≥ 0.20 AND conf ≥ 0.65
      low_conv_small = weight < 0.20 AND conf < 0.65
      comfort        = weight < 0.20 AND conf ≥ 0.65
    """
    try:
        rows = _read_calibration_rows()
        today = datetime.now(timezone.utc).date()
        # Aggregate avg confidence per ticker over window
        conf_acc = {}  # ticker -> [sum, count]
        for r in rows:
            try:
                pd = datetime.strptime(r.get('plan_date', '')[:10], '%Y-%m-%d').date()
            except Exception:
                continue
            if (today - pd).days > window_days:
                continue
            tk = (r.get('ticker') or '').strip()
            c = _to_float(r.get('confidence'))
            if not tk or c is None:
                continue
            acc = conf_acc.setdefault(tk, [0.0, 0])
            acc[0] += c
            acc[1] += 1

        # Compute per-region weights from active holdings
        out = []
        for region_key, region_label in (('us_stocks', 'us'), ('hk_stocks', 'hk')):
            pf = (portfolio.get('portfolios') or {}).get(region_key, {}) or {}
            holdings = [h for h in pf.get('holdings', []) if (h.get('shares') or 0) > 0]
            total = sum((h.get('current_value') or 0) for h in holdings)
            if total <= 0:
                continue
            for h in holdings:
                tk = h.get('ticker') or h.get('code')
                if not tk:
                    continue
                weight = (h.get('current_value') or 0) / total
                acc = conf_acc.get(tk)
                avg_c = round(acc[0] / acc[1], 3) if acc and acc[1] > 0 else None
                n = acc[1] if acc else 0
                # quadrant only meaningful when we have a confidence reading
                if avg_c is None:
                    quad = 'no_data'
                elif weight >= 0.20 and avg_c < 0.65:
                    quad = 'high_risk'
                elif weight >= 0.20:
                    quad = 'conviction'
                elif avg_c < 0.65:
                    quad = 'low_conv_small'
                else:
                    quad = 'comfort'
                out.append({
                    'ticker': tk,
                    'region': region_label,
                    'weight_pct': round(weight * 100, 2),
                    'avg_confidence': avg_c,
                    'n_actions': n,
                    'quadrant': quad,
                })
        # Sort: high_risk first, then by weight desc
        rank = {'high_risk': 0, 'conviction': 1, 'low_conv_small': 2, 'comfort': 3, 'no_data': 4}
        out.sort(key=lambda x: (rank.get(x['quadrant'], 9), -x['weight_pct']))
        return out
    except Exception as e:
        print(f'  warn: compute_weight_confidence failed: {e}', file=sys.stderr)
        return []


def compute_plan_timeline(plans, limit=15):
    """Join recent_plans[].plan.actions with calibration.csv outcomes by
    (date, ticker, bucket) so the dashboard can show 'what I planned + why +
    what happened'. Returns most-recent-first.
    """
    try:
        if not plans:
            return []
        rows = _read_calibration_rows()
        # Build index: (date, ticker, bucket) -> calibration row
        cal_idx = {}
        for r in rows:
            key = (r.get('plan_date', '')[:10], (r.get('ticker') or '').strip(),
                   (r.get('bucket') or '').strip())
            if key[0] and key[1] and key[2]:
                cal_idx[key] = r

        out = []
        # plans is ascending date — reverse so newest first
        for entry in reversed(plans):
            date = entry.get('date', '')
            plan = entry.get('plan') or {}
            # plan can be the trimmed-summary dict (no actions field) — skip
            actions = plan.get('actions') if isinstance(plan, dict) else None
            if not isinstance(actions, list):
                continue
            for a in actions:
                if not isinstance(a, dict):
                    continue
                tk = (a.get('ticker') or '').strip()
                bk = (a.get('bucket') or '').strip()
                cal = cal_idx.get((date, tk, bk))
                outcome = (cal.get('outcome') if cal else None) or 'pending'
                followed_raw = (cal.get('followed') if cal else '') or 'unknown'
                followed = followed_raw.strip().lower().split(' ', 1)[0]  # strip trailing "(auto)"
                if followed not in ('true', 'false', 'unknown'):
                    followed = 'unknown'
                out.append({
                    'date': date,
                    'ticker': tk,
                    'bucket': bk,
                    'trigger_type': a.get('trigger_type') or '',
                    'trigger_price': a.get('trigger_price'),
                    'trigger_condition': a.get('trigger_condition') or '',
                    'size_pct': a.get('size_pct'),
                    'size_shares': a.get('size_shares'),
                    'confidence': a.get('confidence'),
                    'rationale': (a.get('rationale') or '').strip(),
                    'outcome': outcome.strip().lower() if isinstance(outcome, str) else 'pending',
                    'pnl_5d': _to_float(cal.get('pnl_5d')) if cal else None,
                    'followed': followed,
                })
                if len(out) >= limit:
                    return out
        return out
    except Exception as e:
        print(f'  warn: compute_plan_timeline failed: {e}', file=sys.stderr)
        return []


def _series_extremes(series):
    """series = list of (date, value). Returns all-time peak / trough and the
    worst peak-to-trough drawdown (with the dates that bracket it).

    `current` is the last point; `current_dd_pct` is its retracement from the
    running peak; `at_low` flags that today IS the lowest point in the series.
    """
    pts = [(d, float(v)) for d, v in series if v is not None]
    if not pts:
        return None
    peak = pts[0][1]
    peak_date = pts[0][0]
    dd_peak_date = peak_date          # peak that precedes the worst trough
    worst = 0.0
    worst_trough_date = pts[0][0]
    worst_peak_date = pts[0][0]
    for d, v in pts:
        if v > peak:
            peak = v
            peak_date = d
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < worst:
                worst = dd
                worst_trough_date = d
                worst_peak_date = peak_date
    hi = max(pts, key=lambda x: x[1])
    lo = min(pts, key=lambda x: x[1])
    cur_date, cur = pts[-1]
    cur_dd = round((cur - peak) / peak * 100, 2) if peak > 0 else None
    peak_at_worst = next((v for d, v in pts if d == worst_peak_date), None)
    trough_at_worst = next((v for d, v in pts if d == worst_trough_date), None)
    max_dd_abs = (round(peak_at_worst - trough_at_worst, 2)
                  if peak_at_worst is not None and trough_at_worst is not None else None)
    return {
        'peak': {'value': round(hi[1], 2), 'date': hi[0]},
        'trough': {'value': round(lo[1], 2), 'date': lo[0]},
        'current': {'value': round(cur, 2), 'date': cur_date},
        'current_dd_pct': cur_dd,           # retracement of today from running peak
        'max_dd_pct': round(worst, 2),
        'max_dd_abs': max_dd_abs,
        'max_dd_peak_date': worst_peak_date,
        'max_dd_trough_date': worst_trough_date,
        'at_low': abs(cur - lo[1]) < 1e-6,  # today == all-time low in window
    }


def compute_drawdown(snapshots, fx_rate=None):
    """All-time peak / trough / max-drawdown per region AND combined.

    Basis = equity (market value + cumulative realized) so selling a position
    doesn't masquerade as a drawdown. Combined series folds US→HKD at the
    current fx_rate (HKD peg barely moves, so a constant rate is fine).

    Legacy keys kept for back-compat:
      `max_pct_30d_*` = worst peak-to-trough retracement over the window.
      `current_pct_*` = (today - 30d-ago) / 30d-ago * 100.
    New keys: `us` / `hk` / `combined` → see `_series_extremes`.
    """
    empty = {
        'max_pct_30d_hk': None,
        'max_pct_30d_us': None,
        'current_pct_hk': None,
        'current_pct_us': None,
        'us': None,
        'hk': None,
        'combined': None,
        'basis': 'equity (market value + realized)',
    }
    try:
        if not snapshots:
            return empty
        n = len(snapshots)
        window = snapshots[-30:] if n >= 30 else snapshots[:]

        def max_drawdown_pct(key):
            peak = None
            worst = None
            for s in window:
                v = s.get(key)
                if v is None:
                    continue
                try:
                    v = float(v)
                except Exception:
                    continue
                if peak is None or v > peak:
                    peak = v
                if peak and peak > 0:
                    dd = (v - peak) / peak * 100
                    if worst is None or dd < worst:
                        worst = dd
            return round(worst, 2) if worst is not None else None

        # current vs 30d-ago using min(29, n-1) offset back from today
        offset = min(29, n - 1)
        base_idx = (n - 1) - offset
        today = snapshots[-1]
        base = snapshots[base_idx]

        def current_pct(key):
            t = today.get(key)
            b = base.get(key)
            if t is None or b is None:
                return None
            try:
                t = float(t); b = float(b)
            except Exception:
                return None
            if b == 0:
                return None
            return round((t - b) / abs(b) * 100, 2)

        # All-time extremes (over every embedded snapshot, not just the 30d window).
        us_series = [(s.get('date'), s.get('us_equity')) for s in snapshots]
        hk_series = [(s.get('date'), s.get('hk_equity')) for s in snapshots]
        combined = None
        if fx_rate and fx_rate > 0:
            comb_series = []
            for s in snapshots:
                ue, he = s.get('us_equity'), s.get('hk_equity')
                if ue is None or he is None:
                    continue
                comb_series.append((s.get('date'), ue * fx_rate + he))
            combined = _series_extremes(comb_series)
            if combined:
                combined['currency'] = 'HKD'
                combined['fx_usdhkd'] = round(fx_rate, 4)

        us_ext = _series_extremes(us_series)
        if us_ext:
            us_ext['currency'] = 'USD'
        hk_ext = _series_extremes(hk_series)
        if hk_ext:
            hk_ext['currency'] = 'HKD'

        return {
            'max_pct_30d_hk': max_drawdown_pct('hk_equity'),
            'max_pct_30d_us': max_drawdown_pct('us_equity'),
            'current_pct_hk': current_pct('hk_equity'),
            'current_pct_us': current_pct('us_equity'),
            'us': us_ext,
            'hk': hk_ext,
            'combined': combined,
            'basis': 'equity (market value + realized)',
        }
    except Exception as e:
        print(f'  warn: compute_drawdown failed: {e}', file=sys.stderr)
        return empty


# ───────────────────────────────────────────────────────────────────────────
# v2.1: broker-style analytics
# ───────────────────────────────────────────────────────────────────────────

# Sector / theme map (hardcoded — peer-map.json doesn't carry sector explicitly)
SECTOR_MAP = {
    # US
    'NVDA': 'Semiconductor',  'SOXL': 'Semiconductor ETF',
    'RKLB': 'Aerospace',      'RKLX': 'Aerospace',
    'CRCL': 'Crypto / Stablecoin',
    'OKLO': 'Nuclear / Energy',
    'QQQ':  'Index ETF',      'TQQQ': 'Index ETF',
    'TCOM': 'Travel / Online',
    'HOOD': 'Fintech',        'ROBN': 'Fintech',
    'PLTU': 'AI / Defense',
    'MSFU': 'Tech Mega-cap',
    # HK
    '00100': 'AI / 大模型',
    '02208': '新能源',
    '03032': '恒生科技 ETF', '07226': '恒生科技 ETF',
    '03033': '恒生科技 ETF',
    '07709': 'KR ADR (旧仓)', '07747': 'KR ADR (旧仓)',
}

# 2x/3x leveraged ETF set
LEVERAGED_TICKERS = {'SOXL', 'TQQQ', 'PLTU', 'RKLX', 'ROBN', 'MSFU', '07226'}


def compute_sector_exposure(portfolio):
    """Group active holdings by sector, with % of region book."""
    result = {'us': [], 'hk': []}
    try:
        for region in ('us_stocks', 'hk_stocks'):
            r_key = 'us' if region == 'us_stocks' else 'hk'
            holdings = portfolio['portfolios'][region].get('holdings', [])
            active = [h for h in holdings if h.get('shares', 0) > 0]
            total_value = sum(h.get('current_value', 0) or 0 for h in active)
            if total_value <= 0:
                continue
            by_sector = {}
            for h in active:
                sec = SECTOR_MAP.get(h['ticker'], 'Other')
                bucket = by_sector.setdefault(sec, {'value': 0.0, 'tickers': []})
                bucket['value'] += (h.get('current_value') or 0)
                bucket['tickers'].append(h['ticker'])
            for sec, info in by_sector.items():
                result[r_key].append({
                    'sector': sec,
                    'value': round(info['value'], 2),
                    'pct': round(info['value'] / total_value * 100, 2),
                    'tickers': info['tickers'],
                })
            result[r_key].sort(key=lambda x: x['pct'], reverse=True)
    except Exception as e:
        print(f'  warn: compute_sector_exposure failed: {e}', file=sys.stderr)
    return result


def compute_leveraged_etf_exposure(portfolio, fx_rate):
    """Percent of book in 2x/3x leveraged ETFs, per region + combined (USD-base)."""
    out = {'us_pct': None, 'hk_pct': None, 'combined_pct': None, 'tickers': []}
    try:
        us_active = [h for h in portfolio['portfolios']['us_stocks'].get('holdings', [])
                     if h.get('shares', 0) > 0]
        hk_active = [h for h in portfolio['portfolios']['hk_stocks'].get('holdings', [])
                     if h.get('shares', 0) > 0]

        us_total = sum(h.get('current_value', 0) or 0 for h in us_active)
        hk_total = sum(h.get('current_value', 0) or 0 for h in hk_active)
        us_lev   = sum(h.get('current_value', 0) or 0 for h in us_active if h['ticker'] in LEVERAGED_TICKERS)
        hk_lev   = sum(h.get('current_value', 0) or 0 for h in hk_active if h['ticker'] in LEVERAGED_TICKERS)

        if us_total > 0: out['us_pct'] = round(us_lev / us_total * 100, 2)
        if hk_total > 0: out['hk_pct'] = round(hk_lev / hk_total * 100, 2)

        if fx_rate and fx_rate > 0 and (us_total + hk_total) > 0:
            us_usd_total = us_total
            hk_usd_total = hk_total / fx_rate
            us_usd_lev   = us_lev
            hk_usd_lev   = hk_lev / fx_rate
            combined_total = us_usd_total + hk_usd_total
            combined_lev   = us_usd_lev   + hk_usd_lev
            if combined_total > 0:
                out['combined_pct'] = round(combined_lev / combined_total * 100, 2)

        out['tickers'] = sorted(set(
            h['ticker'] for h in us_active + hk_active if h['ticker'] in LEVERAGED_TICKERS
        ))
    except Exception as e:
        print(f'  warn: compute_leveraged_etf_exposure failed: {e}', file=sys.stderr)
    return out


def compute_all_time_extremes(portfolio, top_n=3):
    """Top-N winners + bottom-N losers across all active holdings (by pnl_percent)."""
    out = {'winners': [], 'losers': []}
    try:
        rows = []
        for region in ('us_stocks', 'hk_stocks'):
            r_key = 'us' if region == 'us_stocks' else 'hk'
            for h in portfolio['portfolios'][region].get('holdings', []):
                if h.get('shares', 0) <= 0:
                    continue
                p = h.get('pnl_percent')
                if p is None:
                    continue
                rows.append({
                    'ticker':      h['ticker'],
                    'name':        h.get('stock_name') or h.get('name', h['ticker']),
                    'region':      r_key,
                    'pnl_percent': round(float(p), 2),
                    'pnl_abs':     h.get('pnl_abs'),
                    'current_value': h.get('current_value'),
                })
        rows.sort(key=lambda x: x['pnl_percent'], reverse=True)
        out['winners'] = rows[:top_n]
        out['losers']  = sorted(rows, key=lambda x: x['pnl_percent'])[:top_n]
    except Exception as e:
        print(f'  warn: compute_all_time_extremes failed: {e}', file=sys.stderr)
    return out


def compute_today_ranges(portfolio, top_n=8):
    """Today's high-low spread as % of current price, sorted desc."""
    rows = []
    try:
        for region in ('us_stocks', 'hk_stocks'):
            r_key = 'us' if region == 'us_stocks' else 'hk'
            for h in portfolio['portfolios'][region].get('holdings', []):
                if h.get('shares', 0) <= 0:
                    continue
                hi = h.get('day_high'); lo = h.get('day_low'); cur = h.get('current_price')
                if hi is None or lo is None or cur is None or cur <= 0:
                    continue
                try:
                    hi = float(hi); lo = float(lo); cur = float(cur)
                except Exception:
                    continue
                if hi == lo:
                    continue
                rows.append({
                    'ticker':    h['ticker'],
                    'region':    r_key,
                    'high':      round(hi, 4),
                    'low':       round(lo, 4),
                    'current':   round(cur, 4),
                    'range_pct': round((hi - lo) / cur * 100, 2),
                })
    except Exception as e:
        print(f'  warn: compute_today_ranges failed: {e}', file=sys.stderr)
    rows.sort(key=lambda x: x['range_pct'], reverse=True)
    return rows[:top_n]


def compute_realized_vs_unrealized(portfolio, fx_rate):
    """Realized + unrealized split per region + combined (USD-base)."""
    out = {
        'us': {'realized': None, 'unrealized': None},
        'hk': {'realized': None, 'unrealized': None},
        'combined_usd': {'realized': None, 'unrealized': None},
    }
    try:
        us = portfolio['portfolios']['us_stocks']
        hk = portfolio['portfolios']['hk_stocks']
        out['us']['realized']   = us.get('total_realized_pnl') or us.get('realized_pnl') or 0.0
        out['us']['unrealized'] = us.get('total_pnl') or 0.0
        out['hk']['realized']   = hk.get('total_realized_pnl') or hk.get('realized_pnl') or 0.0
        out['hk']['unrealized'] = hk.get('total_pnl') or 0.0
        if fx_rate and fx_rate > 0:
            out['combined_usd']['realized'] = round(
                out['us']['realized'] + out['hk']['realized'] / fx_rate, 2)
            out['combined_usd']['unrealized'] = round(
                out['us']['unrealized'] + out['hk']['unrealized'] / fx_rate, 2)
    except Exception as e:
        print(f'  warn: compute_realized_vs_unrealized failed: {e}', file=sys.stderr)
    return out


def compute_capital_deployed(portfolio, fx_rate):
    """资本基准（"自己曾经拥有过的钱"） per region + combined USD-eq.

    Formula (option C, 2026-05-22 决定):
      basis = current_cost_basis(active holdings) + cumulative realized_pnl

    Why C 而不是 Σbuys：Σbuys 会把 rotation churn 重复计算（同一笔钱在 07709
    海力士里反复买卖每次都计入）。C 是没有完整 cash-flow log 的个人 tracker
    最诚实的"capital basis"近似 —— 代表"现在场上的钱 + 历史已兑现拿出来的"。
    雪球非 TWR 模式逻辑类似。

    行业标准 TWR / MWR 需要每日 portfolio value + 时间戳现金流（含
    deposit/withdrawal），我们没有这个数据。

    See 2026-05-22 conversation with kcn (rotation churn 问题).
    """
    out = {
        'us':  {'native': None, 'usd': None},
        'hk':  {'native': None, 'usd': None},
        'combined_usd': None,
    }

    try:
        us = portfolio['portfolios']['us_stocks']
        hk = portfolio['portfolios']['hk_stocks']

        us_cur  = us.get('total_cost', 0) or 0
        us_real = us.get('realized_pnl', 0) or 0
        hk_cur  = hk.get('total_cost', 0) or 0
        hk_real = hk.get('realized_pnl', 0) or 0

        out['us']['native'] = round(us_cur + us_real, 2)
        out['hk']['native'] = round(hk_cur + hk_real, 2)
        out['us']['usd'] = out['us']['native']  # US native is USD
        if fx_rate and fx_rate > 0:
            out['hk']['usd'] = round(out['hk']['native'] / fx_rate, 2)
            out['combined_usd'] = round(out['us']['usd'] + out['hk']['usd'], 2)
    except Exception as e:
        print(f'  warn: compute_capital_deployed failed: {e}', file=sys.stderr)
    return out


def compute_net_principal_return(portfolio, fx_rate):
    """复利口径："自有现金"的真实回报 per region + combined USD-eq.

    Formula (2026-05-29 决定，与 capital_deployed 的 option-C 并列、互补):
      净投入本金 net_principal = current_cost_basis(active) − cumulative realized_pnl
      总收益    total_profit  = unrealized_pnl + realized_pnl
      回报率    return_pct    = total_profit / net_principal × 100

    Why 这个口径：active trader 会把卖出回笼的现金（含已兑现利润）反复滚进
    新仓。`cost − realized` 还原的是"还压在场上的自有现金净额"——把赚到又滚
    回去的利润从分母里剔除，于是 return_pct 反映自有资金的复利增速（赢家立刻
    再投会把这个数顶得很高，这正是复利效应，不是错算）。

    与 capital_deployed(cost+realized) 的关系：那个用"我曾经拥有过的钱"做分母
    （保守、不会过 100% churn），这个用"我净掏的钱"做分母（激进、体现滚动复利）。
    两个并排给 kcn 看，一上一下夹住真实回报。See 2026-05-29 conversation.

    net_principal ≤ 0 ⇒ 已收回的现金 ≥ 投入，纯用利润在玩，return_pct 无意义置 None。

    true_principal override (2026-05-29)：若 region 配了 `true_principal`（从交易
    现金流账本反推的峰值净投入＝实际自掏现金），优先用它当分母——net_principal
    (cost−realized) 会被频繁 churn 把分母做小、return_pct 虚高（US 一度到 142%）。
    true_principal 是更诚实的"我实际投了多少"。net_principal 仍照算并保留在输出里
    供参考；combined 也跟随用各 region 实际分母（denom）。
    """
    out = {
        'us':  {'net_principal': None, 'total_profit': None, 'return_pct': None},
        'hk':  {'net_principal': None, 'total_profit': None, 'return_pct': None},
        'combined_usd': {'net_principal': None, 'total_profit': None, 'return_pct': None},
        'formula': '回报率 = (浮动 + 已实现) ÷ 本金；本金优先用 true_principal（峰值净投入），否则用 净投入本金=累计成本−已实现',
    }

    def _region(pf):
        cost = pf.get('total_cost', 0) or 0
        real = pf.get('realized_pnl', 0) or 0
        unrl = pf.get('total_pnl', 0) or 0
        net_principal = round(cost - real, 2)
        total_profit = round(real + unrl, 2)
        true_p = pf.get('true_principal')
        denom = round(true_p, 2) if (true_p and true_p > 0) else net_principal
        ret = round(total_profit / denom * 100, 2) if denom and denom > 0 else None
        res = {
            'net_principal': net_principal,
            'total_profit':  total_profit,
            'return_pct':    ret,
            'return_basis':  'true_principal' if (true_p and true_p > 0) else 'net_principal',
            '_denom':        denom,
        }
        if true_p and true_p > 0:
            res['true_principal'] = round(true_p, 2)
            # 自洽跳闸：true_principal=峰值净投入，理应 ≥ 当前净投入(cost−realized)。
            # 若反超，说明加仓/补流水后常量没重算 → 警告（不阻断，回报率仍出）。
            if net_principal > true_p + 1:
                print(f'  warn: true_principal({true_p}) < net_principal({net_principal}) — 常量疑似过期，'
                      f'改持仓后请按现金流账本重算 true_principal', file=sys.stderr)
        return res

    try:
        out['us'] = _region(portfolio['portfolios']['us_stocks'])
        out['hk'] = _region(portfolio['portfolios']['hk_stocks'])
        if fx_rate and fx_rate > 0:
            np_usd = round(out['us']['_denom'] + out['hk']['_denom'] / fx_rate, 2)
            tp_usd = round(out['us']['total_profit'] + out['hk']['total_profit'] / fx_rate, 2)
            out['combined_usd'] = {
                'net_principal': np_usd,
                'total_profit': tp_usd,
                'return_pct': round(tp_usd / np_usd * 100, 2) if np_usd > 0 else None,
            }
        # _denom 仅用于 combined 计算，不外泄到输出
        for r in ('us', 'hk'):
            out[r].pop('_denom', None)
    except Exception as e:
        print(f'  warn: compute_net_principal_return failed: {e}', file=sys.stderr)
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    portfolio = load_json(WS_ROOT / 'portfolio.json')
    if not portfolio:
        print('FATAL: portfolio.json missing', file=sys.stderr)
        return 1

    us_pf = portfolio['portfolios']['us_stocks']
    hk_pf = portfolio['portfolios']['hk_stocks']

    us_h = [trim_holding(h, 'USD') for h in us_pf.get('holdings', [])]
    hk_h = [trim_holding(h, 'HKD') for h in hk_pf.get('holdings', [])]

    us_conc = compute_hhi(us_h)
    hk_conc = compute_hhi(hk_h)
    us_conc['verdict'] = hhi_verdict(us_conc['hhi'], us_conc['top2'])
    hk_conc['verdict'] = hhi_verdict(hk_conc['hhi'], hk_conc['top2'])

    fx_cache = load_json(WS_ROOT / '.cache' / 'fx_rate.json') or {}

    snapshots = load_snapshots()
    plans = load_plans()

    out = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        'last_updated': portfolio.get('last_updated', ''),
        'fx': {
            'usdhkd': fx_cache.get('rate'),
            'source': fx_cache.get('source'),
            'fetched_at': fx_cache.get('fetched_at'),
        },
        'totals': {
            'us': {
                'value_usd': us_pf.get('total_current_value', 0),
                'cost_usd': us_pf.get('total_cost', 0),
                'pnl_usd': us_pf.get('total_pnl', 0),
                'pnl_pct': us_pf.get('total_pnl_percent', 0),
                'today_change_usd': us_pf.get('today_total_change', 0),
                'realized_usd': us_pf.get('realized_pnl', 0),
            },
            'hk': {
                'value_hkd': hk_pf.get('total_current_value', 0),
                'cost_hkd': hk_pf.get('total_cost', 0),
                'pnl_hkd': hk_pf.get('total_pnl', 0),
                'pnl_pct': hk_pf.get('total_pnl_percent', 0),
                'today_change_hkd': hk_pf.get('today_total_change', 0),
                'realized_hkd': hk_pf.get('realized_pnl', 0),
            },
        },
        'concentration': {
            'us': us_conc,
            'hk': hk_conc,
        },
        'holdings': {
            # Only ship live positions to the client — shares=0 (fully-exited) names keep
            # their trades[] in portfolio.json for realized-P&L, but the frontend never
            # renders them (every consumer filters is_active), so excluding them here just
            # trims dashboard.json. Intermediate us_h/hk_h above stay full for compute_hhi.
            'us': [h for h in us_h if (h.get('shares') or 0) > 0],
            'hk': [h for h in hk_h if (h.get('shares') or 0) > 0],
        },
        'snapshots': snapshots,
        'snapshots_total': total_snapshots_count(),
        'snapshots_embedded_cap': MAX_SNAPSHOTS_EMBEDDED,
        'plans_count': total_plans_count(),
        'recent_plans': plans,
        'recent_plans_cap': MAX_PLANS_EMBEDDED,
        'indices': _aggregate_indices(us_pf, hk_pf),
        'market_context': load_sector_scan() or portfolio.get('market_context', {}),
        'holdings_history': build_holdings_history(
            sorted(
                p for p in glob.glob(str(WS_ROOT / 'memory' / 'snapshots' / '*.json'))
                if SNAPSHOT_FNAME_RE.match(os.path.basename(p))
            ),
            days=10,
        ),
    }

    # ── Dashboard v2 NEW fields (additive; never replace existing keys) ─
    brief_ctx_path, brief_ctx = _latest_brief_context()
    out['delta'] = compute_delta(snapshots)
    out['today_movers'] = compute_today_movers(us_h, hk_h)
    out['anomalies'] = extract_anomalies(brief_ctx, us_h, hk_h)

    # ── LLM narrative sidecars (agent-written in Step 3; text-only, no keys) ──
    # Each sidecar is validated (validate_insights / validate_intraday_insights)
    # before it reaches dashboard.json: malformed / hallucinated content is dropped
    # so the card hides instead of publishing bad data. Anti-hallucination cross-check
    # is against the live book's tickers.
    known_tickers = {h.get('ticker') for h in (us_h + hk_h) if h.get('ticker')}
    # daily insights (brief): behavioral_review / bear_cases / hidden_concentration.
    # 7d stale guard so a missed brief doesn't show week-old critique as current.
    _insights = load_tmp_sidecar('insights', max_age_days=7)
    _ins = validate_insights({} if _insights.get('_stale') else _insights, known_tickers)
    out['behavioral_review'] = _ins['behavioral_review']
    out['bear_cases'] = _ins['bear_cases']
    out['hidden_concentration'] = _ins['hidden_concentration']
    out['insights_meta'] = {
        'source': _insights.get('_source'),
        'stale': _insights.get('_stale', True if not _insights else False),
    }
    # intraday insights (every 30min): status_banner + per-mover attribution.
    _intra = load_tmp_sidecar('intraday-insights', max_age_days=1)
    _intra_v = validate_intraday_insights({} if _intra.get('_stale') else _intra, known_tickers)
    out['status_banner'] = _intra_v['status_banner']
    out['status_banner_meta'] = {
        'source': _intra.get('_source'),
        'generated_at': _intra.get('generated_at'),
        'stale': _intra.get('_stale', True if not _intra else False),
    }
    # Merge validated mover attribution onto the deterministic movers list (by ticker).
    for _m in out['today_movers']:
        _note = _intra_v['movers'].get(_m.get('ticker'))
        if _note:
            _m['note'] = _note
    out['peer_divergence'] = {
        'as_of': (brief_ctx or {}).get('date')
                 or ((brief_ctx or {}).get('generated_at') or '')[:10],
        'items': extract_peer_divergence(brief_ctx, us_h, hk_h),
    }
    out['calibration'] = compute_calibration()
    out['calibration_by_trigger'] = compute_calibration_by_trigger()
    out['calibration_by_driver'] = compute_calibration_by_driver()
    out['recent_plan_actions'] = recent_actions_from_csv(limit=20)
    out['plan_timeline'] = compute_plan_timeline(plans, limit=15)
    out['weight_confidence'] = compute_weight_confidence(portfolio)
    # v2.1: broker-style analytics
    fx_rate = (out.get('fx') or {}).get('usdhkd')
    out['drawdown'] = compute_drawdown(snapshots, fx_rate)
    out['sector_exposure'] = compute_sector_exposure(portfolio)
    out['leveraged_etf'] = compute_leveraged_etf_exposure(portfolio, fx_rate)
    # Tier 2: pull pre-computed risk metrics (from portfolio_risk_metrics.py)
    risk_path = WS_ROOT / 'assets' / 'data' / 'risk.json'
    if risk_path.exists():
        try:
            out['risk'] = json.loads(risk_path.read_text())
        except Exception as e:
            print(f'  warn: risk.json parse fail: {e}', file=sys.stderr)
            out['risk'] = None
    else:
        out['risk'] = None

    # Risk guardrail card — recompute from the LIVE portfolio via the canonical
    # brief_preflight.compute_risk_guardrail (single source of truth) so the dashboard
    # always shows current breaches, not whatever the last brief-context captured.
    # Leverage dial (lev_regime.json) — embed for the 🧭 card AND feed the guardrail
    # recompute so the dashboard's leveraged-ETF cap matches the tightened regime cap.
    lev_regime = None
    lr_path = WS_ROOT / 'assets' / 'data' / 'lev_regime.json'
    if lr_path.exists():
        try:
            lev_regime = json.loads(lr_path.read_text())
        except Exception as e:
            print(f'  warn: lev_regime.json parse fail: {e}', file=sys.stderr)
    out['lev_regime'] = lev_regime

    try:
        sys.path.insert(0, str(WS_ROOT / 'scripts' / 'harness'))
        from brief_preflight import compute_risk_guardrail, compute_concentration
        _gr_hk = portfolio['portfolios']['hk_stocks']['holdings']
        _gr_us = portfolio['portfolios']['us_stocks']['holdings']
        out['risk_guardrail'] = compute_risk_guardrail(
            _gr_hk, _gr_us, compute_concentration(_gr_hk), compute_concentration(_gr_us),
            out.get('risk') or {}, lev_regime=lev_regime)
    except Exception as e:
        print(f'  warn: risk_guardrail compute fail: {e}', file=sys.stderr)
        out['risk_guardrail'] = None

    # Embed GH Action outputs into dashboard.json so the static page can render them
    def _embed(key, fname):
        path = WS_ROOT / 'assets' / 'data' / fname
        if path.exists():
            try:
                out[key] = json.loads(path.read_text())
                return
            except Exception as e:
                print(f'  warn: {fname} parse fail: {e}', file=sys.stderr)
        out[key] = None

    _embed('catalysts', 'catalysts.json')              # fetch_catalysts.py + brief preflight [11/11]
    _embed('benchmark', 'benchmark.json')              # fetch_benchmark_history.py: SPY/HSI/HSTECH daily close
    _embed('us_news_digest', 'us_news_digest.json')    # GH Action news-digest.yml (xiaomi)
    _embed('sentiment', 'sentiment.json')              # GH Action sentiment-scan.yml
    _embed('macro', 'macro.json')                      # GH Action macro-scan.yml
    _embed('influencer_feed', 'influencer_feed.json')  # GH Action influencer-scan.yml (Trump/Musk/Serenity)

    # Regime badge: reuse the brief's classifier on the embedded macro so the dashboard
    # shows the same risk_on/neutral/risk_off the brief acts on (2026-05-30). Defensive
    # import — never break the build if the harness module is unavailable.
    out['regime'] = None
    try:
        if out.get('macro'):
            _harness = WS_ROOT / 'scripts' / 'harness'
            if str(_harness) not in sys.path:
                sys.path.insert(0, str(_harness))
            from brief_preflight import _classify_regime
            out['regime'] = _classify_regime(out['macro'])
    except Exception as e:
        print(f'  warn: regime classify failed: {e}', file=sys.stderr)

    out['all_time_extremes'] = compute_all_time_extremes(portfolio, top_n=3)
    out['today_ranges'] = compute_today_ranges(portfolio, top_n=8)
    out['realized_vs_unrealized'] = compute_realized_vs_unrealized(portfolio, fx_rate)
    out['capital_deployed'] = compute_capital_deployed(portfolio, fx_rate)
    out['net_principal_return'] = compute_net_principal_return(portfolio, fx_rate)
    if brief_ctx_path:
        print(f'  brief-context source: {os.path.basename(brief_ctx_path)}')

    # Serialize with no indentation to save bytes; pretty-print only if under budget
    payload_min = json.dumps(out, ensure_ascii=False)
    payload_pretty = json.dumps(out, ensure_ascii=False, indent=2)
    payload = payload_pretty if len(payload_pretty.encode('utf-8')) <= MAX_OUT_BYTES else payload_min
    size_bytes = len(payload.encode('utf-8'))

    if size_bytes > MAX_OUT_BYTES:
        # Last resort: drop recent_plans entirely + keep snapshot summaries only
        print(f'⚠️  payload still {size_bytes} bytes > {MAX_OUT_BYTES} cap — dropping recent_plans', file=sys.stderr)
        out['recent_plans'] = []
        out['recent_plans_dropped'] = True
        payload = json.dumps(out, ensure_ascii=False)
        size_bytes = len(payload.encode('utf-8'))

    from safe_io import safe_write_text
    safe_write_text(str(OUT_FILE), payload)

    print(f'✓ wrote {OUT_FILE} ({size_bytes:,} bytes)')
    print(f'  US: {len(us_h)} holdings, {len([h for h in us_h if h["is_active"]])} active, value ${us_conc["total"]:.0f}')
    print(f'  HK: {len(hk_h)} holdings, {len([h for h in hk_h if h["is_active"]])} active, value HK${hk_conc["total"]:.0f}')
    print(f'  Snapshots: {len(snapshots)} embedded / {out["snapshots_total"]} on disk')
    print(f'  Plans: {len(plans)} embedded / {out["plans_count"]} on disk')
    print(f'  Snapshots: {len(snapshots)} | Plans: {len(plans)}')
    print(f'  FX USDHKD: {fx_cache.get("rate")} ({fx_cache.get("source")})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
