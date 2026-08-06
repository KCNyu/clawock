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

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
sys.path.insert(0, str(_CHECKOUT / "scripts" / "data"))

HKT = timezone(timedelta(hours=8))
MAX_MOVERS = 4
# Room is allocated by class, not evenly: an interrupt is what actually gets
# written into the report, so it gets the slots and the characters. A context item
# is background and keeps one slot. Titles are the payload — a HK placement notice
# truncated at 90 characters ("…完成配售35,600,000股新A类股份；(2) 根据一般授权完成发行6,500百万…")
# loses the number that made it matter.
MAX_INTERRUPT_ITEMS = 3
MAX_CONTEXT_ITEMS = 1
MAX_ITEMS_PER_TICKER = MAX_INTERRUPT_ITEMS + MAX_CONTEXT_ITEMS
MAX_FLASHES = 3
INTERRUPT_TITLE_CHARS = 160
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
TRIAGE_FILE = WS / "config" / "filing-triage.json"
NASDAQ_HALTS = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
INTERRUPT = "interrupt"
CONTEXT = "context"
NOISE = "noise"


def _http_json(url: str, *, headers=None, timeout=PER_REQUEST_TIMEOUT_S):
    """The single network seam, so tests never touch the network."""
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def _http_text(url: str, *, timeout=PER_REQUEST_TIMEOUT_S) -> str:
    """Text seam for feeds that are not JSON (the halt RSS)."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def _truncate(text, limit=TITLE_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
            "raw_title": str(row.get("title") or ""),
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
            "raw_title": f"{form} {description}".strip(),
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


def load_triage(path: Path = TRIAGE_FILE) -> dict:
    doc = json.loads(path.read_text())
    for rule in doc["rules"]:
        rule["_re"] = re.compile(rule["pattern"])
    return doc


try:
    TRIAGE = load_triage()
except (OSError, json.JSONDecodeError, re.error):  # pragma: no cover - config guard
    TRIAGE = {"default_class": CONTEXT, "rules": []}


def classify(title: str, market: str, triage: dict | None = None) -> tuple[str, str | None]:
    """First matching rule wins; an unmatched title stays `context`, never dropped.

    The book is mostly funds and large caps, so the win here is subtraction: the
    live probes came back full of `翌日披露报表` and `Form 4`, which explain no
    intraday move and were crowding out anything that does.
    """
    triage = triage or TRIAGE
    text = str(title or "")
    for rule in triage.get("rules", []):
        if rule.get("market") not in (None, market):
            continue
        matcher = rule.get("_re") or re.compile(rule["pattern"])
        if matcher.search(text):
            return rule["class"], rule["id"]
    return triage.get("default_class", CONTEXT), None


def probe_targets(ticker: str, market: str) -> dict:
    """Where a mover's catalyst actually lives.

    Eight of twelve positions are funds. A 2x single-stock ETF files nothing that
    explains its own move — the issuer it tracks does. An index or sector fund has
    no issuer at all; say so rather than probing a shell and reporting
    `no_recent_filing` as if a company had gone quiet.

    Resolution itself lives in instrument_registry.look_through, shared with the
    earnings calendar and the news digest.
    """
    try:
        import instrument_registry  # noqa: PLC0415

        resolved = instrument_registry.look_through(ticker)
    except Exception:  # noqa: BLE001 — never break a reporting cron
        return {"issuer": ticker, "via": None, "kind": "issuer"}
    if resolved["kind"] == "issuer":
        return {"issuer": ticker, "via": None, "kind": "issuer"}
    if resolved["kind"] == "index_fund":
        return {"issuer": None, "via": resolved["tracks"], "kind": "index_fund",
                "chain": resolved["chain"]}
    return {"issuer": resolved["issuer"], "via": ticker, "kind": "look_through",
            "chain": resolved["chain"]}


def _parse_halt_time(halt_date, halt_time):
    """Nasdaq publishes halt times in US market time, so read them as ET."""
    try:
        naive = datetime.strptime(
            f"{halt_date.strip()} {str(halt_time).strip()[:8]}", "%m/%d/%Y %H:%M:%S"
        )
    except (TypeError, ValueError, AttributeError):
        return None
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        return naive.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 — tz database missing; UTC beats dropping the halt
        return naive.replace(tzinfo=timezone.utc)


def halts(symbols, *, now, window, http_text=None) -> dict:
    """US trading halts for held names — one shared request for the whole book.

    Nasdaq publishes every US halt (including LULD pauses, which is what actually
    bites a 2x single-stock ETF) as a structured feed. HK has no free equivalent
    wired: an HK suspension arrives as an announcement instead, and the triage
    rules mark those `interrupt`.
    """
    wanted = {str(s).upper() for s in symbols if s}
    if not wanted:
        return {"status": "not_checked", "halted": []}
    fetch = http_text or _http_text
    try:
        raw = fetch(NASDAQ_HALTS)
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "reason": type(exc).__name__, "halted": []}
    halted = []
    for chunk in re.findall(r"<item>(.*?)</item>", raw, re.S):
        def field(name, text=chunk):
            found = re.search(rf"<ndaq:{name}>(.*?)</ndaq:{name}>", text, re.S)
            return found.group(1).strip() if found else ""

        symbol = field("IssueSymbol").upper()
        if symbol not in wanted:
            continue
        when = _parse_halt_time(field("HaltDate"), field("HaltTime"))
        age = _age_minutes(when, now) if when else None
        if age is not None and (age < 0 or age > window):
            continue
        halted.append({
            "ticker": symbol,
            "halted_at": when.isoformat() if when else None,
            "age_minutes": age,
            "reason_code": field("ReasonCode"),
            "resumption_date": field("ResumptionDate") or None,
            "resumption_trade_time": field("ResumptionTradeTime") or None,
        })
    return {"status": "checked", "halted": halted}


def probe(movers, *, market, now=None, window_minutes=WINDOW_MINUTES,
          budget_s=TOTAL_BUDGET_S, http=None, http_text=None, clock=None) -> dict:
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
        target = probe_targets(ticker, market)
        if target["kind"] == "index_fund":
            # No issuer behind an index or sector fund: chasing filings here would
            # manufacture a "no_recent_filing" that reads like a company gone quiet.
            entry["status"] = "index_fund_no_issuer"
            entry["notes"].append(f"tracks {target['via']}; no issuer files for it")
            entry["target"] = target
            results[ticker] = entry
            continue
        issuer = target["issuer"]
        symbol = tencent_symbol(issuer, market)
        # On the US leg SEC and Tencent report the same filing twice ("SCHEDULE
        # 13G" / "Form SC 13G"). SEC is the authority, so Tencent's filing feed is
        # only consulted when SEC produced nothing — one event, one line.
        for label, call in (
            ("sec", (lambda t=issuer: _sec_items(t, now=now, window=window_minutes, http=http))
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
        interrupts, context_items, suppressed = [], [], 0
        for item in entry["items"]:
            signal, rule = classify(item["title"], market)
            if signal == NOISE:
                suppressed += 1
                continue
            item["signal"], item["triage_rule"] = signal, rule
            if signal == INTERRUPT:
                # re-truncate at the wider limit: this one goes in the report
                item["title"] = _truncate(item.get("raw_title") or item["title"],
                                          INTERRUPT_TITLE_CHARS)
                interrupts.append(item)
            else:
                context_items.append(item)
        for bucket in (interrupts, context_items):
            bucket.sort(key=lambda row: (row["tier"] != PRIMARY, row["age_minutes"]))
        entry["items"] = (interrupts[:MAX_INTERRUPT_ITEMS]
                          + context_items[:MAX_CONTEXT_ITEMS])
        if len(interrupts) > MAX_INTERRUPT_ITEMS:
            entry["more_interrupts"] = len(interrupts) - MAX_INTERRUPT_ITEMS
        if suppressed:
            entry["suppressed_noise"] = suppressed
        if entry["items"]:
            entry["status"] = "found"
        elif entry["status"] != "degraded":
            entry["status"] = "no_recent_filing"
        entry["target"] = target
        results[ticker] = entry

    flashes, flash_note = _market_flashes(
        [name for name in names.values() if name], now=now, window=window_minutes
    )
    halt_symbols = []
    if market == "us":
        # A halt is a low-probability event for large caps, so this is not worth a
        # request on every slot. The exception is the leveraged sleeve: a 2x
        # single-stock ETF gets LULD-paused when its underlying gaps, which is the
        # only realistic halt path in this book. Ask only then.
        halt_symbols = sorted({
            symbol for ticker in chased
            if (results.get(ticker, {}).get("target") or {}).get("kind") == "look_through"
            for symbol in (ticker, (results.get(ticker, {}).get("target") or {}).get("issuer"))
            if symbol
        })
    payload = {
        "as_of": now.isoformat(),
        "window_minutes": window_minutes,
        "elapsed_s": round(clock() - started, 2),
        "tickers": results,
        "market_flashes": flashes,
        "halts": halts(halt_symbols, now=now, window=window_minutes, http_text=http_text),
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
