"""Free, key-less headline feeds: Google News RSS, Yahoo Finance RSS, 同花顺 7×24.

Source access only (docs/architecture/harness.md § Live information sources):
each function is one request through the `http` seam and returns rows
`{title, published_at, url, publisher}` carrying the publisher's own timestamp
(aware ISO) — or raises, so a caller can say which source did not answer
instead of printing an empty list as "no news". Grading, windows, labels and
budgets belong to `clawock.evidence.live_sources`.

Google News shares its URL builder and parser with the morning sentiment scan
(`sentiment.google_news_url` / `parse_google_news`).
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
UA = "Mozilla/5.0 (clawock live information sources)"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
THS_724 = "https://news.10jqka.com.cn/tapp/news/push/stock/"


class SourceError(RuntimeError):
    """The source answered, but not with a feed (status code, parse, refusal)."""


def http_text(url, *, headers=None, timeout=TIMEOUT_S):
    """The default network seam: GET `url`, return the body as text."""
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def _rfc822(value):
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def google_news(query, *, language, http=None, timeout=TIMEOUT_S, limit=10):
    """Google News RSS for `query`; `language` is `en` or `zh` (simplified)."""
    from clawock.market_data import sentiment  # noqa: PLC0415

    edition = ({"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"} if language == "zh"
               else {"hl": "en-US", "gl": "US", "ceid": "US:en"})
    text = (http or http_text)(sentiment.google_news_url(query, **edition), timeout=timeout)
    try:
        items = sentiment.parse_google_news(text, limit)
    except ET.ParseError as exc:
        raise SourceError(f"not a feed: {text[:40]!r}") from exc
    rows = []
    for item in items:
        when = _rfc822(item.get("published"))
        rows.append({"title": item.get("title"), "published_at": when.isoformat() if when else None,
                     "url": item.get("url") or None, "publisher": item.get("source") or None})
    return rows


def yahoo_headlines(symbol, *, http=None, timeout=TIMEOUT_S):
    """Yahoo Finance headline RSS for one symbol (`RKLB`)."""
    text = (http or http_text)(
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


def ths_flashes(*, http=None, timeout=TIMEOUT_S, limit=30):
    """同花顺 7×24 flashes, market-level, newest first."""
    text = (http or http_text)(
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
