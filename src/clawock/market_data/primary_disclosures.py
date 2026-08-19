"""Runtime-neutral collection of attributable primary disclosures.

This module owns source access and normalization only.  It does not resolve a
portfolio, classify an event as a trading candidate, inspect price reaction,
size exposure, persist cursors or alert a user. Those are downstream strategy,
lifecycle and provider concerns.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
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
FINNHUB_FILINGS = "https://finnhub.io/api/v1/stock/filings"
# Finnhub stamps `acceptedDate` in US market time, not UTC. Measured against the
# same filings from data.sec.gov on 2026-08-19: RKLB 8-K reads
# `2026-08-13T11:10:48Z` at SEC and `2026-08-13 07:10:48` at Finnhub — exactly
# EDT. Reading it as UTC would misplace every event by 4-5 hours, which for a
# 30-minute intraday window is the difference between "in this window" and not.
FINNHUB_TZ = ZoneInfo("America/New_York")
# One US session plus the pre/after-hours filing tails around it.
SESSION_LOOKBACK_MINUTES = 24 * 60
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


def _parse_finnhub_time(value):
    """Parse Finnhub's `acceptedDate` (US market time) into an aware UTC datetime."""
    try:
        naive = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    if naive.hour == 0 and naive.minute == 0 and naive.second == 0:
        # Finnhub uses midnight as a "date only" placeholder (that is exactly what
        # `filedDate` carries). Treating it as 00:00:00 ET would invent a precision
        # this row does not have.
        return None
    return naive.replace(tzinfo=FINNHUB_TZ).astimezone(timezone.utc)


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
    try:
        payload = http(
            SEC_SUBMISSIONS.format(cik=digits.zfill(10)),
            headers={"User-Agent": fetch_us_filings._load_user_agent()},
        )
    except urllib.error.HTTPError as exc:
        # A 403 on an unconfigured UA is a configuration error that will never
        # self-heal, not an upstream outage that might. Saying so is the whole
        # point: for weeks this lane reported a generic degradation and nobody
        # had a reason to look (#766).
        if exc.code == 403 and not fetch_us_filings.sec_user_agent_configured():
            return [], (
                "sec_user_agent_unconfigured: SEC refuses the default User-Agent "
                "(no deliverable contact address) — set SEC_USER_AGENT in .api_keys"
            )
        raise
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


def fetch_finnhub_filings(issuer, *, now, window_minutes, http=None, api_key=None,
                          session_lookback_minutes=None):
    """Third primary source: Finnhub's filing index, which keeps the accept time.

    Its role is deliberately narrow. Measured 2026-08-19: Finnhub **lags** —
    the Nasdaq mirror already listed SKHY's 08/19 6-K while Finnhub's newest
    row for that issuer was 08/14. So it is not a faster discovery source and
    must not be sold as one. What it uniquely provides when SEC direct is
    unreachable is the minute-level acceptance timestamp that the date-only
    mirror cannot supply, which is the whole difference between an event that
    can clear `filing_time_unavailable` and one that cannot.
    """
    from clawock.market_data.calendar import read_finnhub_key  # noqa: PLC0415

    http = http or _http_json
    key = api_key if api_key is not None else read_finnhub_key()
    if not key:
        return [], "no FINNHUB_API_KEY"
    # Deliberately wider than the caller's window. A filing the window rejects is
    # still the evidence that resolves a same-day mirror row's missing time — and
    # knowing it landed outside the window is the point. `probe` enforces the
    # real window once, after the two sources have been reconciled.
    session_lookback_minutes = (
        session_lookback_minutes if session_lookback_minutes is not None
        else max(window_minutes, SESSION_LOOKBACK_MINUTES)
    )
    query = urllib.parse.urlencode({"symbol": str(issuer).upper(), "token": key})
    payload = http(f"{FINNHUB_FILINGS}?{query}")
    rows = payload if isinstance(payload, list) else []
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = _parse_finnhub_time(row.get("acceptedDate"))
        if when is None:
            continue
        age = _age_minutes(when, now)
        if age < 0 or age > session_lookback_minutes:
            continue
        form = re.sub(r"\s+", " ", str(row.get("form") or "")).strip()
        filed = str(row.get("filedDate") or "")[:10] or None
        items.append({
            "published_at": when.isoformat(),
            "filed_date": filed,
            "age_minutes": age,
            "time_precision": "datetime",
            "freshness_status": "accepted_time_reported",
            "title": re.sub(r"\s+", " ", f"{form} {row.get('symbol') or issuer}").strip(),
            "source_class": "finnhub_filing",
            "evidence_tier": "primary",
            "source_url": row.get("reportUrl") or None,
            "accession": str(row.get("accessNumber") or "") or None,
            "form": form or None,
            "filing_items": None,
        })
    return items, None


def _filing_key(row):
    """Identity used to line a mirror row up with a timestamped one."""
    form = (row.get("form") or "").strip().upper()
    filed = str(row.get("filed_date") or "")[:10]
    return (form, filed) if form and filed else None


def upgrade_mirror_precision(events, *, now, window_minutes):
    """Let a timestamped source resolve the date-only mirror's missing time.

    The mirror is the fastest US source and the only one that had SKHY's 08/19
    6-K on the day, but it carries no acceptance time, so every row it finds is
    precomputed to `wait` behind `filing_time_unavailable`. When another source
    holds the same filing with a real timestamp, adopting it is a strict gain.

    Three rules keep it honest:

    * **Ambiguity is refused, not guessed.** (form, filed_date) is not unique —
      SKHY filed three 6-Ks on 2026-08-19 alone. More than one candidate match
      means we cannot say *which* filing the time belongs to, so the blocker
      stays. See clawock-json-repair-lossless-invariant.
    * A unique match whose real time falls **outside** the window drops the row:
      the mirror kept it only because it could not tell, and now we can.
    * No match changes nothing.

    Returns (events, notes).
    """
    timed = {}
    ambiguous = set()
    for row in events:
        if row.get("source_class") == "sec_filing_mirror":
            continue
        if row.get("time_precision") != "datetime" and not row.get("published_at"):
            continue
        key = _filing_key(row)
        if key is None:
            continue
        if key in timed:
            ambiguous.add(key)
        timed[key] = row

    kept, notes = [], []
    for row in events:
        if (row.get("source_class") != "sec_filing_mirror"
                or row.get("time_precision") != "date"):
            kept.append(row)
            continue
        key = _filing_key(row)
        match = timed.get(key) if key and key not in ambiguous else None
        if match is None:
            if key in ambiguous:
                notes.append(
                    f"precision: {key[0]} {key[1]} has multiple timestamped matches "
                    f"— refusing to guess which one, keeping the date-only blocker"
                )
            kept.append(row)
            continue
        when = datetime.fromisoformat(str(match["published_at"]))
        age = _age_minutes(when, now)
        if age < 0 or age > window_minutes:
            notes.append(
                f"precision: {key[0]} {key[1]} accepted at {match['published_at']} "
                f"— outside the {window_minutes}min window, dropping the mirror row"
            )
            continue
        upgraded = dict(row)
        upgraded.update({
            "published_at": match["published_at"],
            "age_minutes": age,
            "time_precision": "datetime",
            "freshness_status": "accepted_time_recovered_from_secondary_index",
            "precision_source": match.get("source_class"),
        })
        kept.append(upgraded)
    # One place enforces the window for the reconciled set. Rows that never had a
    # time (the mirror's own, when nothing resolved them) are not age-prunable and
    # keep their existing blocker instead.
    windowed = [
        row for row in kept
        if not isinstance(row.get("age_minutes"), (int, float))
        or 0 <= row["age_minutes"] <= window_minutes
    ]
    return windowed, notes


def probe(issuers, *, market: str, now=None, window_minutes: int,
          budget_s: float, max_issuers: int, http=None, clock=None,
          finnhub_key=None) -> dict:
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
            # Only consulted when SEC direct is unavailable: it is slower to see
            # a filing than either source above, so with SEC healthy it would
            # spend a request and a rate-limit slot to learn nothing new.
            ("finnhub", (lambda t=issuer: fetch_finnhub_filings(
                t, now=now, window_minutes=window_minutes, http=http,
                api_key=finnhub_key,
            )) if market == "us" else None),
            ("exchange", (lambda s=symbol: fetch_exchange(
                s, now=now, window_minutes=window_minutes, http=http
            )) if symbol else None),
        )
        for label, call in calls:
            if call is None:
                continue
            if (label in {"nasdaq_filing_mirror", "finnhub", "exchange"}
                    and any(row["source_class"] == "sec_filing" for row in entry["events"])):
                continue
            if (label == "exchange"
                    and any(row["source_class"] in {"sec_filing_mirror", "finnhub_filing"}
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
                # A source that returned a note did not answer cleanly — a failed
                # ticker-to-CIK lookup, a refused User-Agent or an absent API key
                # is not evidence of no filing. Only `sec` used to be held to this;
                # every note-returning source is now, so a keyless `finnhub` can
                # never be counted as a healthy fallback (#766).
                entry["notes"].append(f"{label}: {note}")
                entry["status"] = "degraded"
                entry["degraded_sources"].append(label)
            entry["events"].extend(items)
            if not note:
                entry["healthy_sources"].append(label)
        entry["events"], precision_notes = upgrade_mirror_precision(
            entry["events"], now=now, window_minutes=window_minutes
        )
        entry["notes"].extend(precision_notes)
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
        "budget_s": float(budget_s),
        "max_issuers": int(max_issuers),
    }
    # Policy-like scalar options can affect provider results and therefore the
    # cache identity.  Runtime injection hooks (http/clock) are deliberately
    # excluded: callables are neither stable nor JSON-serializable.
    probe_options = {
        key: value for key, value in sorted(kwargs.items())
        if isinstance(value, (str, int, float, bool, type(None)))
    }
    if probe_options:
        signature["probe_options"] = probe_options
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
