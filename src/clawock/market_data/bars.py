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
  clawock daily-bars --backfill            # fill every manifest symbol from START_DATE
  clawock daily-bars                       # incremental: append newly closed sessions
  clawock daily-bars --ticker 00100        # one symbol
  clawock daily-bars --repair --ticker X   # allow overwriting with an audit record
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.market_data import integrity as bar_checks
from clawock.market_data.eastmoney_http import em_get
from clawock.instruments import canonical_bar_manifest
from clawock.workspace import workspace_root

WS = workspace_root()
BARS_DIR = WS / "memory" / "bars"
HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")
# Decisions start 2026-05-17, so settlement alone would only need a margin before
# that. The floor is earlier because the Decision Mind trace view settles *fills*,
# and the fill log in portfolio.json goes back to 2025-12-23 — with the old
# 2026-05-01 floor, 51 of 100 fills had no canonical close to mark against and the
# panel fell back to snapshot `current_price`, the very field this store exists to
# replace. One month of margin below the oldest fill gives those a T-n context too.
START_DATE = "2025-12-01"
SCHEMA_VERSION = 1

# Pinned identities now come from config/instruments.json. `tencent` remains
# canonical and `em` remains the best-effort cross-audit source. The registry is
# the one reviewed location for load-bearing .OQ/.N/.AM suffixes, retirement
# declarations and display names.
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


#: Where a refused conflict is remembered. Append-only, one JSON object per
#: refusal, because the exit code and the stdout line the fetcher already
#: prints live in a cron log nobody reads twice: a source that disagrees once
#: a quarter and one that disagrees every week look identical there (#1146).
CONFLICT_LOG = WS / "memory" / "bar-conflicts.jsonl"

#: The closed vocabulary a refusal is classified into. Deliberately small, and
#: deliberately about the *shape* of the disagreement rather than its cause —
#: "the provider re-priced the whole bar by one ratio" is observable, "the
#: provider applied a split" is a guess about someone else's system.
CONFLICT_KINDS = (
    "impossible_bar",      # fails the structural check outright — never stored
    "uniform_rescale",     # every leg moved by the same ratio: adjustment signature
    "close_only",          # only the close moved: a settlement-price revision
    "rounding",            # every leg moved by < 5bp: precision, not information
    "bar_revision",        # anything else: a real disagreement about the session
)

#: Below this, a difference is precision rather than information. 5bp of a
#: HK$700 close is 35 cents — smaller than one tick on that board.
ROUNDING_REL_TOL = 5e-4
#: How close the four ratios must be to each other to read as one rescale.
RESCALE_REL_TOL = 1e-3


def classify_conflict(old: dict, fetched: dict) -> str:
    """Name the shape of a stored-vs-fetched disagreement.

    The store already refuses to overwrite; what it could not say is *what kind*
    of disagreement it refused. A weekly stream of `rounding` and a single
    `bar_revision` on a session the ledger settled against are the same line of
    output today, and they call for opposite responses.
    """
    legs = ("open", "high", "low", "close")
    moved = [k for k in legs
             if abs(old.get(k, 0) - fetched.get(k, 0)) > 1e-9]
    if not moved:
        return "rounding"
    relative = [
        abs(old[k] - fetched[k]) / abs(old[k])
        for k in legs
        if isinstance(old.get(k), (int, float)) and old.get(k)
    ]
    if relative and max(relative) < ROUNDING_REL_TOL:
        return "rounding"
    if moved == ["close"]:
        return "close_only"
    ratios = [
        fetched[k] / old[k]
        for k in legs
        if isinstance(old.get(k), (int, float)) and old.get(k)
        and isinstance(fetched.get(k), (int, float))
    ]
    if len(ratios) == len(legs):
        spread = max(ratios) - min(ratios)
        if spread <= RESCALE_REL_TOL * max(abs(r) for r in ratios):
            return "uniform_rescale"
    return "bar_revision"


def record_conflicts(ticker: str, conflicts: list[dict], path: Path | None = None) -> int:
    """Append refusals to the conflict log. Returns how many rows were written.

    Append-only and never read back by the fetcher: the point is that the rate
    of disagreement per source becomes a number someone can look at later
    (`clawock integrity` summarises it), not that this run behaves differently.
    """
    if not conflicts:
        return 0
    target = Path(path or CONFLICT_LOG)
    target.parent.mkdir(parents=True, exist_ok=True)
    seen_at = datetime.now(HKT).isoformat(timespec="seconds")
    with target.open("a", encoding="utf-8") as fh:
        for conflict in conflicts:
            row = dict(conflict)
            row["ticker"] = ticker
            row["seen_at"] = seen_at
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(conflicts)


def merge(ticker: str, fresh: list[dict], repair: bool) -> tuple[int, int, list[dict]]:
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
            conflicts.append({
                "date": d, "kind": "impossible_bar",
                "detail": f"insane OHLC {b} ({'; '.join(verdict['fatal'])})",
                "fetched": {k: b.get(k) for k in ("open", "high", "low", "close")},
            })
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
            conflicts.append({
                "date": d, "kind": classify_conflict(old, rec),
                "detail": (
                    f"stored O{old['open']}/H{old['high']}/L{old['low']}/C{old['close']} "
                    f"vs fetched O{rec['open']}/H{rec['high']}/L{rec['low']}/C{rec['close']}"),
                "stored": {k: old[k] for k in ("open", "high", "low", "close")},
                "fetched": {k: rec[k] for k in ("open", "high", "low", "close")},
            })
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help=f"fetch from {START_DATE}")
    ap.add_argument("--ticker", help="single ticker")
    ap.add_argument("--repair", action="store_true", help="allow overwriting a stored bar")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

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
        record_conflicts(t, conflicts)
        for c in conflicts:
            all_conflicts.append(f"{t} {c['date']} [{c['kind']}]: {c['detail']}")
        flag = f" ⚠ {len(conflicts)} conflict" if conflicts else ""
        print(f"  {t:6} +{added:3} bars, {revised} revised, {len(load_bars(t)['bars'])} total{flag}")

    print(f"\n{total_add} bars added, {total_rev} revised → {BARS_DIR}")
    if all_conflicts:
        print(f"\n⚠ {len(all_conflicts)} conflicts — stored bars disagree with the provider.")
        print(f"  Classified and appended to {CONFLICT_LOG}; `clawock integrity` counts them.")
        print("  Nothing was overwritten. Investigate, then re-run with --repair if the")
        print("  provider is right; the ledger settled against the stored values.")
        for c in all_conflicts[:20]:
            print(f"   {c}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
