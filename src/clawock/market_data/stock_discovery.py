"""Free, holding-independent US equity discovery; outputs research ideas only.

One Nasdaq exchange-wide snapshot, deterministic liquidity filters and sector
breadth. No LLM, key, paid fallback, portfolio writes or trading authority.
Provider retrieval time never stands in for an observation timestamp.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from clawock.safe_io import to_strict_finite_number
from clawock.workspace import workspace_root

URL = "https://api.nasdaq.com/api/screener/stocks"
MAX_ROWS = 15000
MAX_BYTES = 8 * 1024 * 1024
SECTOR_LABELS = {
    "Technology": "科技", "Finance": "金融", "Health Care": "医疗",
    "Consumer Discretionary": "可选消费", "Consumer Staples": "必选消费",
    "Industrials": "工业", "Energy": "能源", "Utilities": "公用事业",
    "Real Estate": "房地产", "Telecommunications": "通信",
    "Basic Materials": "基础材料",
}
MISSING = ["报价时点与交易场次核验", "一手披露与商业模式", "估值与下行风险", "entry-gate 硬否决"]


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise ValueError("stock discovery policy requires schema_version 1")
    if not isinstance(policy.get("enabled"), bool):
        raise ValueError("enabled must be boolean")
    for key, upper in (("max_candidates", 12), ("max_per_sector", 2)):
        value = policy.get(key)
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError(f"{key} must be an integer in 1..{upper}")
    for key in ("min_market_cap_usd", "min_price_usd", "min_turnover_proxy_usd",
                "min_change_pct", "max_change_pct"):
        value = to_strict_finite_number(policy.get(key))
        if value is None or (not key.endswith("change_pct") and value <= 0):
            raise ValueError(f"invalid {key}")
        if not isinstance(policy[key], (int, float)) or isinstance(policy[key], bool):
            raise ValueError(f"{key} must be a number")
    if policy["min_change_pct"] > policy["max_change_pct"]:
        raise ValueError("inverted change bounds")


def _number(value):
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("$", "").replace("%", "")
    return to_strict_finite_number(value)


def excluded_exposure(portfolio, registry):
    """Exclude actual holdings and their known underlying/1x/signal exposures."""
    blocked = set()
    if not isinstance(portfolio, dict) or not isinstance(portfolio.get("portfolios"), dict):
        raise ValueError("portfolio missing portfolios")
    for book in portfolio["portfolios"].values():
        if not isinstance(book, dict) or not isinstance(book.get("holdings"), list):
            raise ValueError("invalid region book")
        for holding in book["holdings"]:
            if not isinstance(holding, dict):
                raise ValueError("invalid holding row")
            shares = to_strict_finite_number(holding.get("shares"))
            if shares is None or shares < 0:
                raise ValueError("invalid holding shares")
            if shares == 0:
                continue
            symbol = str(holding.get("ticker") or "").strip().upper()
            if not symbol:
                raise ValueError("active holding missing ticker")
            blocked.add(symbol)
            meta = registry.get(symbol)
            if not isinstance(meta, dict):
                raise ValueError("active holding missing exposure metadata")
            for key in ("underlying", "one_x_substitute", "signal_symbol"):
                if meta.get(key):
                    blocked.add(str(meta[key]).upper())
    return blocked


def screen_snapshot(payload, portfolio, registry, policy, *, retrieved_at):
    """Pure screen; missing inputs fail, sector caps precede output truncation."""
    validate_policy(policy)
    blocked = excluded_exposure(portfolio, registry)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Nasdaq snapshot missing data")
    # download=true has data.rows; the table variant omits sector and volume.
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise ValueError("Nasdaq snapshot empty, malformed or exceeds row budget")
    required = {"symbol", "name", "sector", "industry", "marketCap", "lastsale", "volume", "pctchange"}
    if not any(isinstance(row, dict) and required <= set(row) for row in rows):
        raise ValueError("Nasdaq snapshot missing screening columns")
    rejected = Counter()
    eligible = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            rejected["malformed"] += 1
            continue
        ticker = str(raw.get("symbol") or "").strip().upper()
        name = str(raw.get("name") or "").strip()
        sector = str(raw.get("sector") or "").strip()
        industry = str(raw.get("industry") or "").strip()
        if ticker in blocked:
            rejected["held_or_underlying"] += 1
            continue
        if ticker in seen:
            rejected["duplicate"] += 1
            continue
        seen.add(ticker)
        # Conservative security classification: no warrants, units, funds,
        # acquisition shells or preferreds masquerading as new companies.
        if (not re.fullmatch(r"[A-Z]{1,5}(?:[.-][A-Z])?", ticker)
                or not re.search(r"common stock|ordinary shares|depositary", name, re.I)
                or re.search(r"warrant|preferred|acquisition|\bunits?\b|\bfund\b|\bETF\b", name, re.I)
                or industry == "Blank Checks"):
            rejected["security_type"] += 1
            continue
        if len(name) > 160 or len(industry) > 160 or sector not in SECTOR_LABELS or not industry:
            rejected["missing_sector_or_industry"] += 1
            continue
        cap, price, volume, change = [_number(raw.get(key)) for key in
                                      ("marketCap", "lastsale", "volume", "pctchange")]
        if any(value is None for value in (cap, price, volume, change)):
            rejected["missing_metrics"] += 1
            continue
        turnover = price * volume
        if (not math.isfinite(turnover) or cap < policy["min_market_cap_usd"] or price < policy["min_price_usd"]
                or volume <= 0 or turnover < policy["min_turnover_proxy_usd"]
                or not policy["min_change_pct"] <= change <= policy["max_change_pct"]):
            rejected["snapshot_filters"] += 1
            continue
        eligible.append({
            "ticker": ticker, "market": "US", "name": name,
            "sector": sector, "sector_label": SECTOR_LABELS[sector], "industry": industry,
            "state": "needs_entry_gate", "allowed": False,
            "reason": "公开快照符合规模、流动性与涨跌幅筛选；跨板块研究候选",
            "snapshot_metrics": {"market_cap_usd": cap, "price_usd": price,
                                 "volume_shares": volume, "change_pct": change,
                                 "turnover_proxy_usd": turnover},
            "evidence": {"source": "nasdaq_screener", "url": URL,
                         "retrieved_at": retrieved_at, "observed_at": None,
                         "source_as_of": str(data.get("asOf"))[:160] if data.get("asOf") is not None else None,
                         "freshness": "unverified"},
            "missing_evidence": list(MISSING),
            "next_action": "核验报价与一手披露，运行 entry-gate，再决定是否深研",
            "quote_request": {"ticker": ticker, "region": "us"},
            "research_route": "entry-gate -> us-stock-analysis full-report",
        })
    # Breadth is an explicit constraint, not an LLM promise. Larger turnover
    # gets research attention within each sector; it is not an alpha score.
    eligible.sort(key=lambda r: (-r["snapshot_metrics"]["turnover_proxy_usd"], r["ticker"]))
    counts = defaultdict(int)
    selected = []
    for row in eligible:
        if counts[row["sector"]] >= policy["max_per_sector"]:
            continue
        selected.append(row)
        counts[row["sector"]] += 1
        if len(selected) >= policy["max_candidates"]:
            break
    return {
        "schema_version": 1, "status": "ok" if selected else "no_candidates",
        "generated_at": retrieved_at, "market": "US", "research_only": True,
        "universe": "Nasdaq public US-listed equity snapshot, independent of holdings",
        "policy": dict(policy), "scanned_count": len(rows), "eligible_count": len(eligible),
        "rejections": dict(sorted(rejected.items())), "candidates": selected,
        "limitations": ["快照行情时间未核验；先研究，不作为实时交易信号",
                        "成交额为末价×股数的筛选代理，不是实际成交金额",
                        "美股筛选仅覆盖美国上市股票",
                        "无可靠 analyst 一致预期源；目标价与评级缺失"],
    }


def unavailable(reason):
    return {"schema_version": 1, "status": "unavailable", "research_only": True,
            "candidates": [], "degraded": [reason]}


def fetch_snapshot():
    import requests

    response = requests.get(URL, params={"download": "true", "limit": MAX_ROWS},
                            headers={"User-Agent": "Mozilla/5.0",
                                     "Accept": "application/json",
                                     "Origin": "https://www.nasdaq.com"},
                            timeout=(4, 12))
    response.raise_for_status()
    if len(response.content) > MAX_BYTES:
        raise ValueError("Nasdaq snapshot exceeds byte budget")
    return response.json()


def collect(workspace: Path, *, fetcher=None, market="US"):
    """No last-good fallback: failures stay distinct from an empty screen."""
    from clawock.instruments import load_registry
    from clawock.market_data import hk_discovery

    if market == "HK":
        return hk_discovery.collect(workspace)
    if market == "all":
        us = collect(workspace, fetcher=fetcher, market="US")
        hk = hk_discovery.collect(workspace)
        candidates = (us.get("candidates") or []) + hk["candidates"]
        statuses = {us["status"], hk["status"]}
        status = ("ok" if candidates else "unavailable" if "unavailable" in statuses
                  else "no_candidates" if "no_candidates" in statuses else us["status"])
        return {**us, "market": "all", "status": status, "candidates": candidates,
                "markets": {"US": {"status": us["status"]}, "HK": hk}}
    if market != "US":
        raise ValueError("market must be US, HK or all")
    workspace = Path(workspace)
    try:
        policy_path = workspace / "config" / "stock-discovery.json"
        if not policy_path.exists():
            return {"status": "unconfigured", "research_only": True, "candidates": []}
        policy = json.loads(policy_path.read_text())
        validate_policy(policy)
        if not policy["enabled"]:
            return {"status": "disabled", "research_only": True, "candidates": []}
        portfolio = json.loads((workspace / "portfolio.json").read_text())
        registry = load_registry(workspace / "config" / "instruments.json", missing_ok=True)
        # Validate book before spending a request, and never emit held names on
        # unreadable ledger/registry data.
        excluded_exposure(portfolio, registry)
        payload = (fetcher or fetch_snapshot)()
        return screen_snapshot(payload, portfolio, registry, policy,
                               retrieved_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        return unavailable(f"Nasdaq discovery failed ({type(exc).__name__})")


def candidate_lines(discovery, *, limit=3):
    """Shared bounded presentation; queue highlights never authorize a trade."""
    if not discovery or discovery.get("status") in {"unconfigured", "disabled"}:
        return []
    lines = ["持仓外新标的（待研究）"]
    if discovery.get("market") == "HK" and discovery.get("status") == "unavailable":
        return lines + discovery.get("degraded", [])
    if (discovery.get("markets") or {}).get("US", discovery).get("status") == "unavailable":
        lines.append("Nasdaq 候选源未取到；本次无法推荐美股新标的")
    inbox = discovery.get("inbox") or {}
    if inbox.get("status") == "ok":
        lines.append(f"研究收件箱共 {inbox['total']} 项；仅突出新候选与到期复查。")
        for row in inbox["rows"][:limit]:
            tag = "到期复查" if row["due"] else "新候选"
            lines.append(f"- {row['market']} {row['ticker']} · {row['sector_label']}：{tag} / {row['status_label']}"
                         f"（最近发现 {row['last_seen']}）")
            if row.get("gate_artifact"):
                reference = (f"[已有入场核验产物]({row['gate_url']})" if row.get("gate_url")
                             else f"本机核验产物：`{row['gate_artifact']}`")
                lines.append("  " + reference
                             + (" · 最近核验通过（仍不授权交易）" if (row.get("gate") or {}).get("cleared")
                                else " · 尚未通过或已过期"))
        if not inbox["rows"]:
            lines.append("本次没有新候选或到期复查项。")
        if inbox["matching"] > limit:
            lines.append("更多条目见 clawock research-inbox list --highlights。")
    else:
        if inbox:
            lines.append("研究收件箱不可用；以下为本次发现，未覆盖已有研究状态。")
        rows = discovery.get("candidates") or []
        if not rows and discovery.get("status") != "unavailable":
            lines.append("本次快照没有符合筛选条件的持仓外候选")
        for row in rows[:limit]:
            lines.append(f"- {row['ticker']} · {row['sector_label']}：核验报价、一手披露及入场否决后再深研")
    if (discovery.get("markets") or {}).get("HK", {}).get("status") == "unavailable":
        lines.extend(discovery["markets"]["HK"]["degraded"])
    if discovery.get("market") == "HK" or (discovery.get("markets") or {}).get("HK", {}).get("status") in {"ok", "no_candidates"}:
        lines.append("港股：获授权收盘快照的衍生研究候选，不发布原始行情；仍须 entry-gate。")
    if discovery.get("market") != "HK":
        lines.append("Nasdaq 公开快照，行情时间未核验；目标价/评级缺失，候选不授权交易")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clawock discover-stocks", description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit structured research candidates")
    parser.add_argument("--market", choices=["US", "HK", "all"], default="all")
    args = parser.parse_args(argv)
    workspace = workspace_root()
    result = collect(workspace, market=args.market)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          "\n".join(candidate_lines(result, limit=12)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
