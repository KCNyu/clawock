"""Free, key-less headline feeds read live by the intraday information lane.

docs/architecture/intraday-agent.md §6 tier 2. Each function is one request
and returns rows normalised to `{title, published_at, url, publisher}` with the
publisher's own timestamp (aware, ISO) — or raises, so the caller can say which
source did not answer instead of printing an empty list as "no news".

Google News reuses `sentiment.fetch_google_news` (the morning scan's fetcher);
only the time parsing and the in-window filter are added here.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from clawock.sessions import HKT

TIMEOUT_S = 6
UA = "Mozilla/5.0 (clawock intraday information lane)"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
THS_724 = "https://news.10jqka.com.cn/tapp/news/push/stock/"


class SourceError(RuntimeError):
    """The source answered, but not with a feed (status code, parse, refusal)."""


def _http_text(url, *, timeout=TIMEOUT_S):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def _rfc822(value):
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def google_news(query, *, language, timeout=TIMEOUT_S, limit=10, fetch=None):
    """Google News RSS for `query`; `language` is `en` or `zh`."""
    from clawock.market_data import sentiment  # noqa: PLC0415

    edition = ({"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"} if language == "zh"
               else {"hl": "en-US", "gl": "US", "ceid": "US:en"})
    items, status = (fetch or sentiment.fetch_google_news)(
        query, limit=limit, return_status=True, timeout=timeout, **edition)
    if status == "failed":
        raise SourceError("google news did not answer")
    rows = []
    for item in items:
        when = _rfc822(item.get("published"))
        rows.append({"title": item.get("title"), "published_at": when.isoformat() if when else None,
                     "url": item.get("url") or None, "publisher": item.get("source") or None})
    return rows


def yahoo_headlines(symbol, *, timeout=TIMEOUT_S, http_text=None):
    """Yahoo Finance headline RSS for one symbol (`RKLB`)."""
    text = (http_text or _http_text)(
        f"{YAHOO_RSS}?{urllib.parse.urlencode({'s': symbol, 'region': 'US', 'lang': 'en-US'})}",
        timeout=timeout)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        # A throttled answer is a one-line text body ("Edge: Too Many Requests").
        raise SourceError(f"not a feed: {text[:40]!r}") from exc
    rows = []
    for item in root.findall(".//item"):
        when = _rfc822(item.findtext("pubDate"))
        rows.append({"title": (item.findtext("title") or "").strip(),
                     "published_at": when.isoformat() if when else None,
                     "url": (item.findtext("link") or "").strip() or None,
                     "publisher": None})
    return rows


def ths_flashes(*, limit=30, timeout=TIMEOUT_S, http_text=None):
    """同花顺 7×24 flashes, market-level, newest first."""
    text = (http_text or _http_text)(
        f"{THS_724}?{urllib.parse.urlencode({'page': 1, 'tag': '', 'track': 'website', 'pagesize': limit})}",
        timeout=timeout)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise SourceError("not json") from exc
    if str(payload.get("code")) != "200":
        raise SourceError(f"code {payload.get('code')}")
    rows = []
    for row in (payload.get("data") or {}).get("list") or []:
        try:
            when = datetime.fromtimestamp(int(row.get("ctime")), HKT)
        except (TypeError, ValueError):
            when = None
        rows.append({"title": str(row.get("title") or "").strip(),
                     "published_at": when.isoformat() if when else None,
                     "url": row.get("url") or None, "publisher": row.get("source") or None})
    return rows
