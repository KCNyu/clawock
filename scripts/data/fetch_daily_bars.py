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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _em_http import em_get  # noqa: E402  统一防封出口(串行+抖动+session)

WS = Path(__file__).resolve().parents[2]
BARS_DIR = WS / "memory" / "bars"
HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")
START_DATE = "2026-05-01"          # decisions start 2026-05-17; a margin gives T-n context
SCHEMA_VERSION = 1

# Pinned identities. `tencent` is canonical; `em` is the cross-audit secid (116=HK,
# 105=NASDAQ, 106=NYSE, 107=US other) and is best-effort only — push2his is blocked
# from this host. US suffixes come from Tencent's own qt self-report: .OQ=NASDAQ,
# .N=NYSE, .AM=NYSE American. They are NOT guessable — SOXL and ROBN are .AM, and
# asking for `usSOXL` (no suffix) returns exactly one bar rather than an error.
MANIFEST: dict[str, dict] = {
    # HK leg
    "00100": {"leg": "HK", "tencent": "hk00100", "em": "116.00100", "name": "MINIMAX-W"},
    "02208": {"leg": "HK", "tencent": "hk02208", "em": "116.02208", "name": "金风科技"},
    "03032": {"leg": "HK", "tencent": "hk03032", "em": "116.03032", "name": "恒生科技ETF"},
    "03033": {"leg": "HK", "tencent": "hk03033", "em": "116.03033", "name": "南方恒科"},
    "07226": {"leg": "HK", "tencent": "hk07226", "em": "116.07226", "name": "恒科两倍看多"},
    # US leg — suffix is load-bearing, see above
    "CRCL":  {"leg": "US", "tencent": "usCRCL.N",   "em": "106.CRCL",  "name": "Circle"},
    "MSFT":  {"leg": "US", "tencent": "usMSFT.OQ",  "em": "105.MSFT",  "name": "Microsoft"},
    "MSFU":  {"leg": "US", "tencent": "usMSFU.OQ",  "em": "107.MSFU",  "name": "MSFT 2x"},
    "PLTR":  {"leg": "US", "tencent": "usPLTR.OQ",  "em": "105.PLTR",  "name": "Palantir"},
    "PLTU":  {"leg": "US", "tencent": "usPLTU.OQ",  "em": "107.PLTU",  "name": "PLTR 2x"},
    "RKLB":  {"leg": "US", "tencent": "usRKLB.OQ",  "em": "105.RKLB",  "name": "Rocket Lab"},
    "RKLX":  {"leg": "US", "tencent": "usRKLX.OQ",  "em": "107.RKLX",  "name": "RKLB 2x"},
    "ROBN":  {"leg": "US", "tencent": "usROBN.AM",  "em": "107.ROBN",  "name": "HOOD 2x"},
    "SKHY":  {"leg": "US", "tencent": "usSKHY.OQ",  "em": "105.SKHY",  "name": "SK海力士 (listed 07-10)"},
    # "SK海力士-WI" — a when-issued line that stopped trading once SKHY listed. Its only
    # bar is 2026-07-10; a 07-13 decision on it has no session to grade against, and that
    # is a real fact about the instrument, not a data gap to paper over.
    "SKHYV": {"leg": "US", "tencent": "usSKHYV.OQ", "em": "105.SKHYV", "name": "SK海力士-WI (when-issued, retired)"},
    "SOXL":  {"leg": "US", "tencent": "usSOXL.AM",  "em": "107.SOXL",  "name": "SOXL 3x"},
    "SPCH":  {"leg": "US", "tencent": "usSPCH.AM",  "em": "107.SPCH",  "name": "SpaceX hold (listed 06-15)"},
    "SPCX":  {"leg": "US", "tencent": "usSPCX.OQ",  "em": "107.SPCX",  "name": "SpaceX 2x (listed 06-12)"},
}


def bars_path(ticker: str) -> Path:
    return BARS_DIR / f"{ticker}.json"


def load_bars(ticker: str) -> dict:
    p = bars_path(ticker)
    if not p.exists():
        m = MANIFEST.get(ticker, {})
        return {"schema_version": SCHEMA_VERSION, "ticker": ticker, "leg": m.get("leg"),
                "tencent": m.get("tencent"), "em_audit_secid": m.get("em"),
                "adjustment": "raw", "source": "tencent", "bars": {}}
    return json.loads(p.read_text())


def write_bars(ticker: str, doc: dict) -> None:
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    doc["bars"] = dict(sorted(doc["bars"].items()))
    bars_path(ticker).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")


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
    """low <= open,close <= high, and nothing free."""
    return (b["low"] <= b["open"] <= b["high"] and b["low"] <= b["close"] <= b["high"]
            and b["low"] > 0 and b["high"] > 0)


def merge(ticker: str, fresh: list[dict], repair: bool) -> tuple[int, int, list[str]]:
    doc = load_bars(ticker)
    doc.setdefault("tencent", MANIFEST[ticker]["tencent"])
    bars = doc["bars"]
    last_closed = _last_closed_session(doc.get("leg") or MANIFEST[ticker]["leg"])
    now = datetime.now(HKT).isoformat(timespec="seconds")
    added = revised = 0
    conflicts: list[str] = []
    for b in fresh:
        d = b["date"]
        if d > last_closed:
            continue                      # session not finished — never store a live bar
        if not sane(b):
            conflicts.append(f"{d}: insane OHLC {b}")
            continue
        rec = {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
               "source": "tencent", "adjustment": "raw", "fetched_at": now}
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

    beg = START_DATE if args.backfill else (datetime.now(HKT).date() - timedelta(days=10)).isoformat()
    end = datetime.now(HKT).date().isoformat()
    total_add = total_rev = 0
    all_conflicts: list[str] = []
    for t in tickers:
        m = MANIFEST[t]
        fresh = fetch_tencent(m["tencent"], beg, end)
        if not fresh:
            print(f"  {t:6} ✗ tencent returned nothing ({m['tencent']})")
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
