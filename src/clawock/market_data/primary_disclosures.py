"""Runtime-neutral collection of attributable primary disclosures.

This module owns source access and normalization only.  It does not resolve a
portfolio, classify an event as a trading candidate, inspect price reaction,
size exposure, persist cursors or alert a user.  Those are downstream policy
and instance concerns.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


HKT = timezone(timedelta(hours=8))
PER_REQUEST_TIMEOUT_S = 5
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
TENCENT_NEWS = "https://web.ifzq.gtimg.cn/appstock/news/info/search"
TENCENT_FILINGS_TYPE = 0
UA = "Mozilla/5.0 (clawock primary disclosure provider)"


def _http_json(url: str, *, headers=None, timeout=PER_REQUEST_TIMEOUT_S):
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


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


def tencent_symbol(issuer: str, market: str) -> str | None:
    issuer = str(issuer or "").strip()
    if not issuer:
        return None
    if market == "hk":
        digits = issuer.split(".")[0].zfill(5)
        return f"hk{digits}" if digits.isdigit() else None
    return f"us{issuer.upper()}"


def fetch_exchange(symbol, *, now, window_minutes, http=None):
    """Fetch normalized exchange/regulator announcements for one issuer."""
    http = http or _http_json
    payload = http(
        f"{TENCENT_NEWS}?{urllib.parse.urlencode({'symbol': symbol, 'n': 8, 'page': 1, 'type': TENCENT_FILINGS_TYPE})}"
    )
    rows = ((payload or {}).get("data") or {}).get("data") or []
    items = []
    for row in rows:
        when = _parse_tencent_time(row.get("time"))
        if when is None:
            continue
        age = _age_minutes(when, now)
        if age < 0 or age > window_minutes:
            continue
        title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        items.append({
            "published_at": when.isoformat(),
            "age_minutes": age,
            "title": title,
            "source_class": "exchange_filing",
            "evidence_tier": "primary",
            "source_url": row.get("url") or None,
            "accession": None,
            "form": None,
            "filing_items": None,
        })
    return items, None


def fetch_sec(issuer, *, now, window_minutes, http=None):
    """Fetch normalized SEC submissions for one reporting issuer."""
    from clawock.market_data import filings as fetch_us_filings  # noqa: PLC0415

    http = http or _http_json
    cik = fetch_us_filings.lookup_cik(issuer)
    if not cik:
        return [], f"no CIK for {issuer}"
    digits = re.sub(r"\D", "", str(cik))
    payload = http(
        SEC_SUBMISSIONS.format(cik=digits.zfill(10)),
        headers={"User-Agent": fetch_us_filings._load_user_agent()},
    )
    recent = ((payload or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accepted = recent.get("acceptanceDateTime") or []
    docs = recent.get("primaryDocDescription") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []
    filing_items = recent.get("items") or []
    items = []
    for index, form in enumerate(forms):
        when = _parse_sec_time(accepted[index] if index < len(accepted) else None)
        if when is None:
            continue
        age = _age_minutes(when, now)
        if age < 0 or age > window_minutes:
            continue
        description = docs[index] if index < len(docs) else ""
        accession = accessions[index] if index < len(accessions) else ""
        primary_doc = primary_docs[index] if index < len(primary_docs) else ""
        filed_items_text = filing_items[index] if index < len(filing_items) else ""
        archive_url = None
        if accession and primary_doc:
            archive_url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(digits)}/{str(accession).replace('-', '')}/{primary_doc}"
            )
        items.append({
            "published_at": when.isoformat(),
            "age_minutes": age,
            "title": re.sub(r"\s+", " ", f"{form} {description}").strip(),
            "source_class": "sec_filing",
            "evidence_tier": "primary",
            "source_url": archive_url,
            "accession": accession or None,
            "form": str(form or "") or None,
            "filing_items": str(filed_items_text or "") or None,
        })
    return items, None


def probe(issuers, *, market: str, now=None, window_minutes: int,
          budget_s: float, max_issuers: int, http=None, clock=None) -> dict:
    """Return normalized primary disclosures and honest source status.

    Every bound is supplied by the caller.  A provider must not smuggle one
    strategy's cadence, scope or freshness assumptions into another consumer.
    """
    issuer_list = list(dict.fromkeys(str(value) for value in (issuers or []) if value))
    now = now or datetime.now(timezone.utc)
    http = http or _http_json
    clock = clock or time.monotonic
    started = clock()
    chased, skipped = issuer_list[:max_issuers], issuer_list[max_issuers:]
    results = {}

    for issuer in chased:
        entry = {
            "status": "no_recent_disclosure", "events": [], "notes": [],
            "degraded_sources": [],
        }
        symbol = tencent_symbol(issuer, market)
        calls = (
            ("sec", (lambda t=issuer: fetch_sec(
                t, now=now, window_minutes=window_minutes, http=http
            )) if market == "us" else None),
            ("exchange", (lambda s=symbol: fetch_exchange(
                s, now=now, window_minutes=window_minutes, http=http
            )) if symbol else None),
        )
        for label, call in calls:
            if call is None:
                continue
            if (label == "exchange"
                    and any(row["source_class"] == "sec_filing" for row in entry["events"])):
                continue
            if clock() - started > budget_s:
                entry["notes"].append(f"{label}: skipped, time budget spent")
                entry["status"] = "degraded"
                entry["degraded_sources"].append(label)
                break
            try:
                items, note = call()
            except Exception as exc:  # noqa: BLE001 - evidence collection fails soft
                entry["notes"].append(f"{label}: {type(exc).__name__}")
                entry["status"] = "degraded"
                entry["degraded_sources"].append(label)
                continue
            if note:
                entry["notes"].append(f"{label}: {note}")
                # A failed ticker-to-CIK lookup is not evidence of no filing.
                if label == "sec":
                    entry["status"] = "degraded"
                    entry["degraded_sources"].append(label)
            entry["events"].extend(items)
        entry["events"].sort(key=lambda row: row.get("published_at") or "", reverse=True)
        entry["degraded_sources"] = sorted(set(entry["degraded_sources"]))
        if entry["events"] and not entry["degraded_sources"]:
            entry["status"] = "found"
        elif entry["status"] != "degraded":
            entry["status"] = "no_recent_disclosure"
        results[issuer] = entry

    payload = {
        "as_of": now.isoformat(),
        "window_minutes": window_minutes,
        "elapsed_s": round(clock() - started, 2),
        "issuers": results,
    }
    if skipped:
        payload["not_chased"] = skipped
    return payload
