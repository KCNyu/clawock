#!/usr/bin/env python3
"""Catalyst probe for the names an intraday slot flagged.

When a holding moves abnormally, the loop that detects the move should also
capture what was actually published — not leave the model to improvise a reason
from a daily digest built hours earlier.

Design constraints, all enforced here rather than requested in a prompt:

* **Mover-scoped.** Nothing moved, nothing fetched. The caller passes the tickers
  the slot already flagged, and the probe caps how many it will chase.
* **Bounded.** Per-request timeout, a total wall-clock budget, a cap on items per
  ticker and a truncated title. A 2200-character report cannot carry five
  headlines, and a context nobody reads is waste.
* **Primary versus supporting.** Exchange and regulator filings are `primary`;
  broker notes, media and market flashes are `supporting`. Only a primary item may
  ever be treated as a hard catalyst — the catalyst gate still decides whether an
  action is allowed.
* **Silence is stated, not implied.** No item found reads `no_recent_filing`, so an
  empty block can never be mistaken for "no news".
* **Fails soft.** Any endpoint failure degrades to `degraded` with a reason. A news
  probe must never slow or red a market-reporting cron.

Request budget at a 30-minute cadence: at most `MAX_MOVERS` tickers × 2 endpoints
plus one shared market-flash call — a handful of requests per slot. SEC documents
10 req/s (this repo throttles to 8), and the Tencent quote hosts are already
called every slot by the analyze scripts, so the cadence is nowhere near any
published limit. The real risks are shape changes and timeouts, which is why every
path fails soft.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / "scripts" / "data"))

HKT = timezone(timedelta(hours=8))
MAX_MOVERS = 4
MAX_ITEMS_PER_TICKER = 3
MAX_FLASHES = 3
TITLE_CHARS = 90
WINDOW_MINUTES = 240
PER_REQUEST_TIMEOUT_S = 5
TOTAL_BUDGET_S = 20
UA = "Mozilla/5.0 (clawock intraday catalyst probe)"
TENCENT_NEWS = "https://web.ifzq.gtimg.cn/appstock/news/info/search"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
# Tencent type=0 is the exchange/regulator filing feed (HKEX announcements for HK,
# SEC forms for US), timestamped to the second. type=1 is broker research and media.
TENCENT_FILINGS_TYPE = 0
TENCENT_NEWS_TYPE = 1
PRIMARY = "primary"
SUPPORTING = "supporting"


def _http_json(url: str, *, headers=None, timeout=PER_REQUEST_TIMEOUT_S):
    """The single network seam, so tests never touch the network."""
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def _truncate(text) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1] + "…"


def _age_minutes(when: datetime, now: datetime) -> int:
    return int((now - when).total_seconds() // 60)


def _parse_tencent_time(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
    except (TypeError, ValueError):
        return None


def _parse_sec_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def tencent_symbol(ticker: str, market: str) -> str | None:
    """Map a workspace ticker onto the Tencent symbol space."""
    ticker = str(ticker or "").strip()
    if not ticker:
        return None
    if market == "hk":
        digits = ticker.split(".")[0].zfill(5)
        return f"hk{digits}" if digits.isdigit() else None
    return f"us{ticker.upper()}"


def _tencent_items(symbol, feed_type, tier, source_class, *, now, window, http):
    payload = http(
        f"{TENCENT_NEWS}?{urllib.parse.urlencode({'symbol': symbol, 'n': 8, 'page': 1, 'type': feed_type})}"
    )
    rows = ((payload or {}).get("data") or {}).get("data") or []
    items = []
    for row in rows:
        when = _parse_tencent_time(row.get("time"))
        if when is None:
            continue
        age = _age_minutes(when, now)
        if age < 0 or age > window:
            continue
        items.append({
            "published_at": when.isoformat(),
            "age_minutes": age,
            "title": _truncate(row.get("title")),
            "tier": tier,
            "source_class": source_class,
            "url": row.get("url") or None,
        })
    return items


def _sec_items(ticker, *, now, window, http):
    import fetch_us_filings  # noqa: PLC0415 — optional, only needed on the US leg

    cik = fetch_us_filings.lookup_cik(ticker)
    if not cik:
        return [], f"no CIK for {ticker}"
    # lookup_cik already returns the `CIK##########` form; prepending our own
    # prefix produced `CIKCIK…` and a silent 404 on every US mover.
    digits = re.sub(r"\D", "", str(cik))
    payload = http(
        SEC_SUBMISSIONS.format(cik=digits.zfill(10)),
        headers={"User-Agent": fetch_us_filings._load_user_agent()},
    )
    recent = ((payload or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accepted = recent.get("acceptanceDateTime") or []
    docs = recent.get("primaryDocDescription") or []
    items = []
    for index, form in enumerate(forms):
        when = _parse_sec_time(accepted[index] if index < len(accepted) else None)
        if when is None:
            continue
        age = _age_minutes(when, now)
        if age < 0 or age > window:
            continue
        description = docs[index] if index < len(docs) else ""
        items.append({
            "published_at": when.isoformat(),
            "age_minutes": age,
            "title": _truncate(f"{form} {description}".strip()),
            "tier": PRIMARY,
            "source_class": "sec_filing",
            "url": None,
        })
    return items, None


def _market_flashes(names, *, now, window):
    """Market-wide 7x24 flashes, kept only when they name a holding."""
    try:
        import fetch_em_news  # noqa: PLC0415

        rows = fetch_em_news.em_fast_news(limit=20) or []
    except Exception as exc:  # noqa: BLE001 — supporting colour, never fatal
        return [], f"em flash unavailable: {type(exc).__name__}"
    out = []
    for row in rows:
        title = str(row.get("title") or "")
        matched = sorted({name for name in names if name and name in title})
        if not matched:
            continue
        when = _parse_tencent_time(row.get("date") or row.get("time"))
        age = _age_minutes(when, now) if when else None
        if age is not None and (age < 0 or age > window):
            continue
        out.append({
            "published_at": when.isoformat() if when else None,
            "age_minutes": age,
            "title": _truncate(title),
            "tier": SUPPORTING,
            "source_class": "market_flash",
            "matched": matched,
        })
        if len(out) >= MAX_FLASHES:
            break
    return out, None


def holding_names(tickers) -> dict:
    """Ticker → display name, for matching a market-wide flash to a holding."""
    try:
        import instrument_registry  # noqa: PLC0415

        return {
            ticker: (instrument_registry.get(str(ticker)) or {}).get("name")
            for ticker in tickers
        }
    except Exception:  # noqa: BLE001
        return {}


def probe(movers, *, market, now=None, window_minutes=WINDOW_MINUTES,
          budget_s=TOTAL_BUDGET_S, http=None, clock=None) -> dict:
    """Catalyst evidence for the flagged tickers. Never raises."""
    tickers = [str(t) for t in (movers or []) if t]
    if not tickers:
        return {}
    now = now or datetime.now(timezone.utc)
    http = http or _http_json
    clock = clock or time.monotonic
    started = clock()
    chased, skipped = tickers[:MAX_MOVERS], tickers[MAX_MOVERS:]
    names = holding_names(chased)

    results = {}
    for ticker in chased:
        entry = {"status": "no_recent_filing", "items": [], "notes": []}
        symbol = tencent_symbol(ticker, market)
        # On the US leg SEC and Tencent report the same filing twice ("SCHEDULE
        # 13G" / "Form SC 13G"). SEC is the authority, so Tencent's filing feed is
        # only consulted when SEC produced nothing — one event, one line.
        for label, call in (
            ("sec", (lambda t=ticker: _sec_items(t, now=now, window=window_minutes, http=http))
             if market == "us" else None),
            ("filings", (lambda s=symbol: (_tencent_items(
                s, TENCENT_FILINGS_TYPE, PRIMARY, "exchange_filing",
                now=now, window=window_minutes, http=http), None)) if symbol else None),
            ("research", (lambda s=symbol: (_tencent_items(
                s, TENCENT_NEWS_TYPE, SUPPORTING, "broker_or_media",
                now=now, window=window_minutes, http=http), None)) if symbol else None),
        ):
            if call is None:
                continue
            if (label == "filings" and market == "us"
                    and any(row["source_class"] == "sec_filing" for row in entry["items"])):
                continue
            if clock() - started > budget_s:
                entry["notes"].append(f"{label}: skipped, time budget spent")
                entry["status"] = "degraded"
                break
            try:
                items, note = call()
            except Exception as exc:  # noqa: BLE001 — a dead endpoint must not red a cron
                entry["notes"].append(f"{label}: {type(exc).__name__}")
                entry["status"] = "degraded"
                continue
            if note:
                entry["notes"].append(f"{label}: {note}")
            entry["items"].extend(items)
        entry["items"].sort(key=lambda row: (row["tier"] != PRIMARY, row["age_minutes"]))
        entry["items"] = entry["items"][:MAX_ITEMS_PER_TICKER]
        if entry["items"]:
            entry["status"] = "found"
        elif entry["status"] != "degraded":
            entry["status"] = "no_recent_filing"
        results[ticker] = entry

    flashes, flash_note = _market_flashes(
        [name for name in names.values() if name], now=now, window=window_minutes
    )
    payload = {
        "as_of": now.isoformat(),
        "window_minutes": window_minutes,
        "elapsed_s": round(clock() - started, 2),
        "tickers": results,
        "market_flashes": flashes,
    }
    if skipped:
        payload["not_chased"] = skipped
    if flash_note:
        payload["notes"] = [flash_note]
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market", choices=("us", "hk"), required=True)
    parser.add_argument("--tickers", required=True, help="comma-separated movers")
    parser.add_argument("--window-minutes", type=int, default=WINDOW_MINUTES)
    args = parser.parse_args(argv)
    payload = probe(
        [t.strip() for t in args.tickers.split(",") if t.strip()],
        market=args.market, window_minutes=args.window_minutes,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
