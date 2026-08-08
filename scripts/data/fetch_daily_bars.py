#!/usr/bin/env python3
"""
fetch_daily_bars.py — the canonical daily OHLC store the decision ledger settles against.

Why this exists
---------------
Trigger verdicts and T+1 marks used to come from `memory/snapshots/{date}.json`. That
file is a *portfolio* snapshot written by whichever cron ran, so its prices carry the
vintage of the fetch, not of a trading session:

  * `current_price` for 00100 across 15 snapshots was the previous close 7 times, that
    day's close 3 times, and an intraday print 5 times;
  * `day_high` / `day_low` are carried forward for live positions — 00100 showed the
    identical (738.0, 744.5, 731.0) on 05-20, 05-21, 05-22 and 05-25 while its real
    ranges those days were nothing alike.

Settling against that invented triggers that never fired (07226 05-27 read a stored
high of 4.192 vs a real 3.96) and dropped ones that did (00100 05-18 read 744.5 vs a
real 827.5, discarding a winner).

Contract
--------
* **Raw, never adjusted** (`fqt=0`): a trigger price is a historical nominal price. An
  adjusted series would silently re-price every past condition.
* **Session-dated**: `date` is the exchange session, not the fetching host's HKT day.
* **Completed sessions only**: today is never written — the session must have closed.
* **Immutable**: an existing bar is never silently overwritten. A changed value is a
  provider revision and needs `--repair`, which records the old value and a reason.
* **Fixed symbol manifest**: symbols are pinned, never guessed at fetch time. US tickers
  need their exchange suffix or Tencent silently returns a *single* bar instead of the
  series — `usSOXL` gives 1 row, `usSOXL.AM` gives 51. Guessing `.OQ` for SOXL/ROBN
  (both `.AM`) looks like "no data" rather than an error. Suffixes below were taken
  from Tencent's own `qt` self-report, not from a heuristic.
* **Tencent is canonical, by necessity not preference**: `push2his.eastmoney.com` is
  IP-blocked from this host — it answers the first probe (a brief allow window that
  reads as success) and then returns nothing, which is exactly how it fooled an
  earlier attempt here. `qt.gtimg.cn` / `web.ifzq.gtimg.cn` are the reachable ones.
  Where both answered, they agreed exactly on 00100 (05-18 high 827.5, 05-21 high
  755.0, 05-22 close 768.5), which is what re-opened the stale-range bug.

Usage
  fetch_daily_bars.py --backfill            # fill every manifest symbol from START_DATE
  fetch_daily_bars.py                       # incremental: append newly closed sessions
  fetch_daily_bars.py --ticker 00100        # one symbol
  fetch_daily_bars.py --repair --ticker X   # allow overwriting with an audit record
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bar_checks  # noqa: E402  shared "is this bar believable" contract
from _em_http import em_get  # noqa: E402  统一请求节流出口

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
BARS_DIR = WS / "memory" / "bars"
HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")
START_DATE = "2026-05-01"          # decisions start 2026-05-17; a margin gives T-n context
SCHEMA_VERSION = 1

# Pinned identities now come from config/instruments.json. `tencent` remains
# canonical and `em` remains the best-effort cross-audit source. The registry is
# the one reviewed location for load-bearing .OQ/.N/.AM suffixes, retirement
# declarations and display names.
from instrument_registry import canonical_bar_manifest  # noqa: E402

MANIFEST: dict[str, dict] = canonical_bar_manifest()


def bars_path(ticker: str) -> Path:
    return BARS_DIR / f"{ticker}.json"


def load_bars(ticker: str) -> dict:
    p = bars_path(ticker)
    if not p.exists():
        m = MANIFEST.get(ticker, {})
        return {"schema_version": SCHEMA_VERSION, "ticker": ticker, "leg": m.get("leg"),
                "tencent": m.get("tencent"), "em_audit_secid": m.get("em"),
                "adjustment": "raw", "source": "tencent",
                "retired": bool(m.get("retired", False)), "bars": {}}
    return json.loads(p.read_text())


def write_bars(ticker: str, doc: dict) -> None:
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    doc["bars"] = dict(sorted(doc["bars"].items()))
    bars_path(ticker).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")


def _sync_manifest_flags(ticker: str) -> None:
    """Persist manifest-declared flags (currently `retired`) into an existing bar JSON
    without needing a successful fetch. merge() already does this on a non-empty fetch;
    this covers the empty-fetch path so a newly declared retirement is not lost."""
    if not bars_path(ticker).exists():
        return
    doc = load_bars(ticker)
    want = bool(MANIFEST[ticker].get("retired", False))
    if bool(doc.get("retired", False)) != want:
        doc["retired"] = want
        write_bars(ticker, doc)


def _last_closed_session(leg: str) -> str:
    """The newest session that is certainly finished, in that market's own calendar.

    Never write today's bar while it can still move — that is the exact defect this
    store exists to remove. HK closes 16:00 HKT; US closes 16:00 ET.
    """
    if leg == "HK":
        now = datetime.now(HKT)
        cutoff = now.date() if now.hour >= 17 else (now.date() - timedelta(days=1))
    else:
        now = datetime.now(ET)
        cutoff = now.date() if now.hour >= 17 else (now.date() - timedelta(days=1))
    return cutoff.isoformat()


def _rows_to_bars(rows: list) -> list[dict]:
    out = []
    for r in rows:
        if len(r) < 5:
            continue
        try:
            out.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                        "high": float(r[3]), "low": float(r[4])})
        except (ValueError, TypeError):
            continue
    return out


def fetch_tencent(sym: str, beg: str, end: str) -> list[dict]:
    """Canonical: Tencent unadjusted daily bars.

    `kline/kline` returns the `day` series, which is unadjusted — that is what a
    historical trigger price must be compared against. `fqkline/get?...,qfq` returns
    a *forward-adjusted* series and must never be used here: it would silently
    re-price every past condition through later splits.
    """
    import urllib.request
    url = ("https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
           f"?param={sym},day,{beg},{end},640")
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            j = json.loads(resp.read())
    except Exception as e:
        print(f"    tencent {sym} failed: {type(e).__name__}", file=sys.stderr)
        return []
    node = (j.get("data") or {}).get(sym) or {}
    if not isinstance(node, dict):
        return []
    # Only ever the unadjusted key. If Tencent hands back qfqday instead, that is an
    # adjusted series and we refuse it rather than quietly settling against it.
    return _rows_to_bars(node.get("day") or [])


def fetch_em_audit(secid: str, beg: str, end: str) -> list[dict]:
    """Cross-audit only, best-effort. push2his is IP-blocked here and usually returns
    nothing; when it does answer, disagreement is worth knowing about."""
    r = em_get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={"secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56",
                "klt": "101", "fqt": "0",
                "beg": beg.replace("-", ""), "end": end.replace("-", ""), "lmt": "1000"},
    )
    if r is None:
        return []
    out = []
    for k in ((r.json().get("data") or {}).get("klines") or []):
        p = k.split(",")
        if len(p) < 5:
            continue
        try:
            out.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                        "high": float(p[3]), "low": float(p[4])})
        except ValueError:
            continue
    return out


def sane(b: dict) -> bool:
    """low <= open,close <= high, and nothing free.

    Detection now lives in `bar_checks` so this store and the live-quote paths
    share one definition. The policy stays here and is unchanged: a bar that
    cannot be true of any session is refused. What changed is that a *degenerate*
    bar (o==h==l==c) is no longer indistinguishable from a healthy one — see
    `merge`, which stores it with a flag instead of pretending it had a range.
    """
    return bar_checks.is_structurally_sane(b)


def merge(ticker: str, fresh: list[dict], repair: bool) -> tuple[int, int, list[str]]:
    doc = load_bars(ticker)
    doc.setdefault("tencent", MANIFEST[ticker]["tencent"])
    # The manifest is the declaration; docs written before it existed get it here.
    doc["retired"] = bool(MANIFEST[ticker].get("retired", False))
    bars = doc["bars"]
    last_closed = _last_closed_session(doc.get("leg") or MANIFEST[ticker]["leg"])
    now = datetime.now(HKT).isoformat(timespec="seconds")
    added = revised = 0
    conflicts: list[str] = []
    for b in fresh:
        d = b["date"]
        if d > last_closed:
            continue                      # session not finished — never store a live bar
        verdict = bar_checks.check_bar(b)
        if verdict["fatal"]:
            conflicts.append(f"{d}: insane OHLC {b} ({'; '.join(verdict['fatal'])})")
            continue
        rec = {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
               "source": "tencent", "adjustment": "raw", "fetched_at": now}
        # A bar whose OHLC collapsed to a single price is legitimate for a halted
        # or untraded session and is also the signature of a frozen provider
        # quote. We cannot tell which from the bar alone, so it is stored with
        # the flag rather than dropped (settlement still needs the close) — and
        # never silently, because a trigger that "fired" inside a zero-width
        # range is not evidence of anything.
        if "degenerate_range" in verdict["flags"]:
            rec["degenerate"] = True
        old = bars.get(d)
        if old is None:
            bars[d] = rec
            added += 1
            continue
        same = all(abs(old[k] - rec[k]) < 1e-9 for k in ("open", "high", "low", "close"))
        if same:
            continue
        # A stored bar changed. That is either a provider revision or a source bug; it is
        # never something to apply silently — the ledger already settled against the old one.
        if not repair:
            conflicts.append(
                f"{d}: stored O{old['open']}/H{old['high']}/L{old['low']}/C{old['close']} "
                f"vs fetched O{rec['open']}/H{rec['high']}/L{rec['low']}/C{rec['close']}")
            continue
        rec["revised_from"] = {k: old[k] for k in ("open", "high", "low", "close")}
        rec["revised_at"] = now
        rec["revision_reason"] = "explicit --repair"
        bars[d] = rec
        revised += 1
    write_bars(ticker, doc)
    return added, revised, conflicts


def incremental_beg(ticker: str) -> str:
    """Where an incremental fetch should start for one ticker: just before its own
    newest bar, never a fixed window off today.

    A fixed 10-day lookback silently turns any outage longer than the window into a
    permanent hole: the writer resumes, appends only the recent tail, and the store
    ends up `06-01, 07-06…07-15`. Nothing then reports it — freshness only ever looks
    *after* the newest bar, so the store reads as current while a month of sessions
    is missing, and every decision in that month settles as `bar_missing` forever.
    Anchoring to the ticker's own newest bar means the gap is simply fetched. Merging
    is immutable and idempotent, so an overlapping range costs one request and
    changes nothing.
    """
    doc = load_bars(ticker)
    bars = doc.get("bars") or {}
    if not bars:
        return START_DATE
    # Two days of overlap so a provider revision to the last stored session is still
    # seen (and reported as a conflict) rather than skipped past.
    return max(START_DATE,
               (date.fromisoformat(max(bars)) - timedelta(days=2)).isoformat())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help=f"fetch from {START_DATE}")
    ap.add_argument("--ticker", help="single ticker")
    ap.add_argument("--repair", action="store_true", help="allow overwriting a stored bar")
    args = ap.parse_args()

    tickers = [args.ticker] if args.ticker else list(MANIFEST)
    unknown = [t for t in tickers if t not in MANIFEST]
    if unknown:
        print(f"not in manifest (add it explicitly, never guess): {unknown}", file=sys.stderr)
        return 2

    end = datetime.now(HKT).date().isoformat()
    total_add = total_rev = 0
    all_conflicts: list[str] = []
    for t in tickers:
        m = MANIFEST[t]
        beg = START_DATE if args.backfill else incremental_beg(t)
        fresh = fetch_tencent(m["tencent"], beg, end)
        if not fresh:
            print(f"  {t:6} ✗ tencent returned nothing ({m['tencent']})")
            # A retirement declaration must still land: a retired line usually returns
            # an empty fetch — the very case `retired` exists for — and settlement reads
            # it only from the bar JSON, which merge() (skipped here) is what writes.
            _sync_manifest_flags(t)
            continue
        added, revised, conflicts = merge(t, fresh, args.repair)
        total_add += added
        total_rev += revised
        for c in conflicts:
            all_conflicts.append(f"{t} {c}")
        flag = f" ⚠ {len(conflicts)} conflict" if conflicts else ""
        print(f"  {t:6} +{added:3} bars, {revised} revised, {len(load_bars(t)['bars'])} total{flag}")

    print(f"\n{total_add} bars added, {total_rev} revised → {BARS_DIR}")
    if all_conflicts:
        print(f"\n⚠ {len(all_conflicts)} conflicts — stored bars disagree with the provider.")
        print("  Nothing was overwritten. Investigate, then re-run with --repair if the")
        print("  provider is right; the ledger settled against the stored values.")
        for c in all_conflicts[:20]:
            print(f"   {c}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
