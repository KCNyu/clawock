#!/usr/bin/env python3
"""Suggest same-industry peers without changing the curated peer map.

US suggestions come from Finnhub's peer-symbol endpoint. HK suggestions use
East Money to resolve the holding's industry board and then list that board's
HK constituents. This module is deliberately fail-safe: source failures are
diagnosed on stderr and always become an empty suggestion list.
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

# US same-industry peers via Finnhub are live and verified. HK is NOT wired yet:
# East Money HK industry boards use ``HK\d+`` codes (00100's 软件服务 board is
# HK28), not the A-share ``BK\d+``, and the board-constituent endpoint
# ``clist/get?fs=b:HK28`` returns no rows — the HK constituent query is still
# unresolved against live data. ``_suggest_hk`` keeps the resolved parts (industry
# lookup + board match with the corrected code shape) behind this flag so it is
# ready once the constituent endpoint is confirmed; until then HK holdings get no
# auto peers and, importantly, make no wasted East Money calls per scan.
HK_AUTO_PEERS_ENABLED = False

FINNHUB_PEERS_URL = "https://finnhub.io/api/v1/stock/peers"
EM_STOCK_INFO_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EM_STOCK_BOARDS_URL = "https://push2.eastmoney.com/api/qt/slist/get"
EM_BOARD_CONSTITUENTS_URL = "https://push2.eastmoney.com/api/qt/clist/get"


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
    symbol = _norm_hk(ticker)
    secid = f"116.{symbol}"

    info_response = em_get(
        EM_STOCK_INFO_URL,
        params={
            "fltt": "2",
            "invt": "2",
            "secid": secid,
            "fields": "f57,f58,f127",
        },
        timeout=TIMEOUT,
        label="auto-peer HK industry",
    )
    info = (_response_json(info_response, "East Money stock info").get("data") or {})
    industry = str(info.get("f127") or "").strip()
    if not industry:
        _diag(symbol, "East Money returned no industry")
        return []

    boards_response = em_get(
        EM_STOCK_BOARDS_URL,
        params={
            "fltt": "2",
            "invt": "2",
            "secid": secid,
            "spt": "3",
            "pi": "0",
            "pz": "200",
            "po": "1",
            "fields": "f12,f14",
        },
        headers={"Referer": "https://quote.eastmoney.com/"},
        timeout=TIMEOUT,
        label="auto-peer HK board",
    )
    boards = _rows(_response_json(boards_response, "East Money stock boards"))
    if not boards:
        _diag(symbol, "East Money returned no board memberships")
        return []

    def board_match(row):
        name = re.sub(r"\s+", "", str(row.get("f14") or ""))
        target = re.sub(r"\s+", "", industry)
        return name == target

    board = next((row for row in boards if board_match(row)), None)
    board_code = str((board or {}).get("f12") or "")
    # HK industry boards are HK\d+ (e.g. HK28); A-share boards are BK\d+.
    if not re.fullmatch(r"(?:BK|HK)\d+", board_code):
        _diag(symbol, f"East Money could not map industry {industry!r} to a board")
        return []

    constituents_response = em_get(
        EM_BOARD_CONSTITUENTS_URL,
        params={
            "pn": "1",
            "pz": "200",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f20",
            "fs": f"b:{board_code}",
            "fields": "f12,f13,f14",
        },
        headers={"Referer": f"https://quote.eastmoney.com/bk/90.{board_code}.html"},
        timeout=TIMEOUT,
        label="auto-peer HK constituents",
    )
    rows = _rows(_response_json(constituents_response, "East Money constituents"))
    if not rows:
        _diag(symbol, f"East Money board {board_code} returned no constituents")
        return []

    blocked = _excluded(symbol, "hk", curated_tickers)
    out = []
    seen = set()
    for row in rows:
        # f13 is East Money's market id. Requiring 116 prevents an A-share
        # industry board with the same display name from leaking into HK peers.
        if str(row.get("f13") or "") != "116":
            continue
        candidate = _norm_hk(row.get("f12"))
        name = str(row.get("f14") or "").strip()
        if not candidate or not name or candidate in blocked or candidate in seen:
            continue
        seen.add(candidate)
        out.append({
            "ticker": candidate,
            "region": "hk",
            "name": name,
            "source": "eastmoney",
        })
        if len(out) == MAX_AUTO_PEERS:
            break
    if not out:
        _diag(symbol, f"East Money board {board_code} returned no eligible HK peers")
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
                _diag(str(ticker),
                      "HK auto-peers not wired yet (East Money board-constituent "
                      "endpoint unresolved); skipping")
                return []
            return _suggest_hk(ticker, curated_tickers)
        _diag(str(ticker), f"unsupported region {region!r}")
        return []
    except Exception as exc:
        _diag(str(ticker), f"auto peer source failed: {exc}")
        return []
