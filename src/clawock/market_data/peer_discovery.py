#!/usr/bin/env python3
"""Suggest same-industry peers without changing the curated peer map.

US suggestions come from Finnhub's peer-symbol endpoint. HK suggestions come
from East Money's F10 industry-comparison report, which answers the whole
question in one call: given ``00100.HK`` it returns the industry it is filed
under and every other HK listing in it, with market cap to rank them by.

This module is deliberately fail-safe: source failures are diagnosed on stderr
and always become an empty suggestion list.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

import requests

from clawock.market_data.eastmoney_http import em_get
from clawock.workspace import workspace_root


WS = workspace_root(Path.cwd())
API_KEYS_PATH = WS / ".api_keys"


MAX_AUTO_PEERS = 6
TIMEOUT = 10

# US same-industry peers via Finnhub are live and verified.
#
# HK was blocked for months on the wrong endpoint. The quote API's board
# constituent query (``clist/get?fs=b:HK28``) does not accept the ``HK\d+``
# board-code family that ``slist/get`` hands back, and no selector spelling
# fixes that. The F10 industry-comparison report does not need one: filter
# ``RPT_PCF10_INDUSTRY_SCALE`` by ``SECUCODE`` and East Money returns the
# holding's industry plus its HK constituents ranked by market cap, in a single
# call — 176 rows for 00100 (软件服务), verified live.
#
# The flag stays off anyway, and not because the mechanism is unproven.
# ``peer_residuals.load_rule_config`` refuses to load unless
# ``automatic_hk_peer_discovery`` is false: the peer-residual rules
# (leader_continuation / laggard_avoidance / mean_reversion) were pre-registered
# against the curated peer universe in ``memory/peer-map.json``. Turning
# discovery on silently re-registers them against a different universe, which
# invalidates the prospective evidence collected so far. That is a research
# decision, taken deliberately with a re-registration, not a wiring change —
# see #1122. Until then HK holdings get no auto peers and make no East Money
# calls per scan.
HK_AUTO_PEERS_ENABLED = False

FINNHUB_PEERS_URL = "https://finnhub.io/api/v1/stock/peers"
EM_HK_INDUSTRY_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
# 规模对比: the industry peer table behind the F10 page's 行业对比 tab. Chosen over
# the valuation/growth reports because it is the only one carrying market cap,
# and "the six biggest names in this industry" is the peer set a human would
# pick — a PE-ranked list would hand back whichever six are cheapest today.
EM_HK_INDUSTRY_REPORT = "RPT_PCF10_INDUSTRY_SCALE"
# 8xxxx is the RMB counter of a dual-counter listing (80700 is 00700's), the
# same company twice. Zero-padding keeps GEM codes like 08083 out of this.
EM_HK_DUAL_COUNTER = re.compile(r"^8\d{4}$")
# The report's rows are not all companies: it ends with aggregates such as
# 行业平均, which carry a label where the code belongs. Measured live on 00100 —
# 行业平均 was the sixth "peer" until this existed.
EM_HK_CODE = re.compile(r"^\d{5}$")


def _diag(ticker: str, message: str) -> None:
    print(f"suggest_peers.py: {ticker}: {message}", file=sys.stderr)


def _rows(payload):
    diff = ((payload or {}).get("data") or {}).get("diff") or []
    return list(diff.values()) if isinstance(diff, dict) else diff


def _norm_hk(ticker: object) -> str:
    value = str(ticker or "").strip()
    return value.zfill(5) if value.isdigit() else value.upper()


def _norm_us(ticker: object) -> str:
    return str(ticker or "").strip().upper()


def _excluded(ticker: str, region: str, curated_tickers: Iterable[object]) -> set[str]:
    norm = _norm_hk if region == "hk" else _norm_us
    return {norm(ticker), *(norm(value) for value in curated_tickers or [])}


def _response_json(response, source: str):
    if response is None:
        raise RuntimeError(f"{source} returned no response")
    status = getattr(response, "status_code", 200)
    if status >= 400:
        raise RuntimeError(f"{source} HTTP {status}")
    return response.json()


def _api_key(name: str) -> str:
    try:
        for line in API_KEYS_PATH.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() == name:
                    return value.strip()
    except OSError:
        pass
    return ""


def _suggest_us(ticker: str, curated_tickers: Iterable[object]) -> list[dict]:
    symbol = _norm_us(ticker)
    key = _api_key("FINNHUB_API_KEY")
    if not key:
        _diag(symbol, "Finnhub API key unavailable")
        return []

    response = requests.get(
        FINNHUB_PEERS_URL,
        params={"symbol": symbol, "token": key},
        timeout=TIMEOUT,
    )
    symbols = _response_json(response, "Finnhub peers")
    if not isinstance(symbols, list) or not symbols:
        _diag(symbol, "Finnhub peers returned an empty or malformed payload")
        return []

    blocked = _excluded(symbol, "us", curated_tickers)
    out = []
    seen = set()
    for raw in symbols:
        candidate = _norm_us(raw)
        if not candidate or candidate in blocked or candidate in seen:
            continue
        seen.add(candidate)
        # /stock/peers returns symbols only. `clawock fetch-peers` supplies the feed
        # company name during the shared pricing pass; the symbol is a safe
        # fallback if that feed omits its name.
        out.append({
            "ticker": candidate,
            "region": "us",
            "name": candidate,
            "source": "finnhub",
        })
        if len(out) == MAX_AUTO_PEERS:
            break
    if not out:
        _diag(symbol, "Finnhub returned no additional uncurated peers")
    return out


def _suggest_hk(ticker: str, curated_tickers: Iterable[object]) -> list[dict]:
    """Same-industry HK peers, ranked by market cap, in one East Money call.

    The report is keyed by the holding itself: filtering ``SECUCODE`` to
    ``00100.HK`` returns one row per company in 00100's industry, each carrying
    the industry name and the peer's code, name and market cap. There is no
    board code in the chain at all, which is why this works where the quote
    API's ``fs=b:HK28`` constituent query never did.
    """
    symbol = _norm_hk(ticker)

    response = em_get(
        EM_HK_INDUSTRY_URL,
        params={
            "reportName": EM_HK_INDUSTRY_REPORT,
            "columns": ("SECUCODE,SECURITY_CODE,TYPE_ID,TYPE_NAME,"
                        "CORRE_SECURITY_CODE,CORRE_SECUCODE,CORRE_SECURITY_NAME,"
                        "HKTOTAL_MARKET_CAP"),
            "filter": f'(SECUCODE="{symbol}.HK")',
            "pageNumber": "1",
            "pageSize": "50",
            # Ranked here rather than in Python: the report is paged, so sorting
            # after the fetch would rank page one instead of the industry.
            "sortColumns": "HKTOTAL_MARKET_CAP",
            "sortTypes": "-1",
            "source": "F10",
            "client": "PC",
        },
        headers={"Referer": "https://emweb.securities.eastmoney.com/"},
        timeout=TIMEOUT,
        label="auto-peer HK industry peers",
    )
    payload = _response_json(response, "East Money HK industry comparison")
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = (result or {}).get("data") or []
    if not rows:
        _diag(symbol, "East Money returned no HK industry comparison rows")
        return []

    industry = str((rows[0] or {}).get("TYPE_NAME") or "").strip()
    blocked = _excluded(symbol, "hk", curated_tickers)
    out = []
    seen = set()
    for row in rows:
        candidate = _norm_hk(row.get("CORRE_SECURITY_CODE"))
        name = str(row.get("CORRE_SECURITY_NAME") or "").strip()
        if not candidate or not name or candidate in blocked or candidate in seen:
            continue
        # The dual counter is the same issuer trading in RMB; as a peer it is a
        # copy of a name already in the list, and as a residual it would be that
        # name's own FX basis.
        if EM_HK_DUAL_COUNTER.match(candidate):
            continue
        if not EM_HK_CODE.match(candidate):
            continue
        seen.add(candidate)
        out.append({
            "ticker": candidate,
            "region": "hk",
            "name": name,
            "source": "eastmoney",
            "industry": industry,
        })
        if len(out) == MAX_AUTO_PEERS:
            break
    if not out:
        _diag(symbol, f"East Money industry {industry or '?'} returned no eligible HK peers")
    return out


def suggest_auto_peers(ticker, region, curated_tickers) -> list[dict]:
    """Return up to six uncurated same-industry peers; never raise.

    An unavailable key, timeout, HTTP/JSON/source-shape error, or empty source
    all degrade to ``[]``. The curated caller can therefore continue unchanged.
    """
    try:
        normalized_region = str(region or "").strip().lower()
        if normalized_region == "us":
            return _suggest_us(ticker, curated_tickers)
        if normalized_region == "hk":
            if not HK_AUTO_PEERS_ENABLED:
                # The source works (see the flag's comment); what is off is the
                # switch, because turning it on re-registers the peer-residual
                # rules against a different peer universe.
                _diag(str(ticker),
                      "HK auto-peers held off pending peer-residual rule "
                      "re-registration (#1122); skipping")
                return []
            return _suggest_hk(ticker, curated_tickers)
        _diag(str(ticker), f"unsupported region {region!r}")
        return []
    except Exception as exc:
        _diag(str(ticker), f"auto peer source failed: {exc}")
        return []
