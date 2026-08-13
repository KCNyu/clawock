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
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.safe_io import safe_write_json


HKT = timezone(timedelta(hours=8))
PER_REQUEST_TIMEOUT_S = 5
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
TENCENT_NEWS = "https://web.ifzq.gtimg.cn/appstock/news/info/search"
TENCENT_FILINGS_TYPE = 0
NASDAQ_FILINGS = "https://api.nasdaq.com/api/company/{issuer}/sec-filings"
UA = "Mozilla/5.0 (clawock primary disclosure provider)"
CACHE_SCHEMA_VERSION = 1


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


def fetch_nasdaq_filings(issuer, *, now, window_minutes, http=None):
    """Fetch Nasdaq's free SEC-filing mirror when SEC direct is unavailable.

    Nasdaq exposes the filing date but not the SEC acceptance timestamp.  Same
    US-session-date rows are therefore useful primary documents, while their
    exact freshness remains explicitly unverified downstream.
    """
    http = http or _http_json
    payload = http(
        NASDAQ_FILINGS.format(issuer=urllib.parse.quote(str(issuer).upper()))
        + "?limit=10"
    )
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    session_date = now.astimezone(ZoneInfo("America/New_York")).date()
    items = []
    for row in rows:
        try:
            filed_date = datetime.strptime(str(row.get("filed")), "%m/%d/%Y").date()
        except (TypeError, ValueError):
            continue
        # A date-only mirror cannot honestly prove a rolling intraday window.
        # Keep only today's US filing date; callers must retain the precision
        # blocker before treating it as an exploration trigger.
        if filed_date != session_date:
            continue
        links = row.get("view") if isinstance(row.get("view"), dict) else {}
        source_url = links.get("htmlLink") or links.get("docLink") or None
        form = re.sub(r"\s+", " ", str(row.get("formType") or "")).strip()
        company = re.sub(r"\s+", " ", str(row.get("companyName") or "")).strip()
        items.append({
            "published_at": None,
            "filed_date": filed_date.isoformat(),
            "observed_at": now.isoformat(),
            "time_precision": "date",
            "freshness_status": "same_session_date_time_unavailable",
            "age_minutes": None,
            "title": re.sub(r"\s+", " ", f"{form} {company}").strip(),
            "source_class": "sec_filing_mirror",
            "evidence_tier": "primary",
            "source_url": source_url,
            "accession": None,
            "form": form or None,
            "filing_items": None,
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
            "degraded_sources": [], "healthy_sources": [],
        }
        symbol = tencent_symbol(issuer, market)
        calls = (
            ("sec", (lambda t=issuer: fetch_sec(
                t, now=now, window_minutes=window_minutes, http=http
            )) if market == "us" else None),
            ("nasdaq_filing_mirror", (lambda t=issuer: fetch_nasdaq_filings(
                t, now=now, window_minutes=window_minutes, http=http
            )) if market == "us" else None),
            ("exchange", (lambda s=symbol: fetch_exchange(
                s, now=now, window_minutes=window_minutes, http=http
            )) if symbol else None),
        )
        for label, call in calls:
            if call is None:
                continue
            if (label in {"nasdaq_filing_mirror", "exchange"}
                    and any(row["source_class"] == "sec_filing" for row in entry["events"])):
                continue
            if (label == "exchange"
                    and any(row["source_class"] == "sec_filing_mirror"
                            for row in entry["events"])):
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
            if not (label == "sec" and note):
                entry["healthy_sources"].append(label)
        entry["events"].sort(key=lambda row: row.get("published_at") or "", reverse=True)
        entry["degraded_sources"] = sorted(set(entry["degraded_sources"]))
        entry["healthy_sources"] = sorted(set(entry["healthy_sources"]))
        entry["partial_degradation"] = bool(
            entry["degraded_sources"] and entry["healthy_sources"]
        )
        if entry["events"]:
            entry["status"] = "found"
        elif entry["healthy_sources"]:
            entry["status"] = "no_recent_disclosure"
        else:
            entry["status"] = "degraded"
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


def probe_cached(issuers, *, market: str, now=None, window_minutes: int,
                 budget_s: float, max_issuers: int, cache_path,
                 cache_ttl_seconds: int = 300, **kwargs) -> dict:
    """A short retry cache with explicit collection provenance.

    The normal 30-minute cadence always outlives the cache.  Its purpose is to
    collapse an auto-retry or concurrent duplicate fetch, not to turn an old
    filing response into a fresh source check.
    """
    now = now or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    path = Path(cache_path)
    signature = {
        "market": market,
        "issuers": list(dict.fromkeys(str(value) for value in (issuers or []) if value)),
        "window_minutes": int(window_minutes),
        "max_issuers": int(max_issuers),
    }
    try:
        cached = json.loads(path.read_text()) if path.exists() else {}
        fetched_at = datetime.fromisoformat(
            str(cached.get("fetched_at") or "").replace("Z", "+00:00")
        )
        age_seconds = max(0, int((now - fetched_at).total_seconds()))
        payload = cached.get("payload")
        if (cached.get("schema_version") == CACHE_SCHEMA_VERSION
                and cached.get("signature") == signature
                and isinstance(payload, dict)
                and age_seconds <= cache_ttl_seconds):
            result = json.loads(json.dumps(payload))
            result["collection"] = {
                "cache_hit": True,
                "fetched_at": fetched_at.isoformat(),
                "age_seconds": age_seconds,
                "ttl_seconds": cache_ttl_seconds,
            }
            return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    result = probe(
        signature["issuers"], market=market, now=now,
        window_minutes=window_minutes, budget_s=budget_s,
        max_issuers=max_issuers, **kwargs,
    )
    result["collection"] = {
        "cache_hit": False,
        "fetched_at": now.isoformat(),
        "age_seconds": 0,
        "ttl_seconds": cache_ttl_seconds,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(str(path), {
            "schema_version": CACHE_SCHEMA_VERSION,
            "signature": signature,
            "fetched_at": now.isoformat(),
            "payload": {key: value for key, value in result.items() if key != "collection"},
        })
    except OSError:
        # Cache loss costs requests, never evidence.
        result["collection"]["write_error"] = True
    return result
