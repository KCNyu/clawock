"""HK derived research candidates from existing quotes or a licensed snapshot."""
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from clawock.safe_io import to_strict_finite_number
from clawock.sessions import HKT, HK_HALF_DAYS, latest_completed_session

MAX_BYTES = 8 * 1024 * 1024
POLICY = {"min_market_cap_hkd": 15_000_000_000, "min_price_hkd": 2,
          "min_turnover_hkd": 20_000_000, "min_change_pct": -3,
          "max_change_pct": 5, "max_candidates": 6, "max_per_sector": 1}


def unavailable(code="redistribution_permission_missing"):
    return {"schema_version": 1, "market": "HK", "status": "unavailable",
            "research_only": True, "candidates": [], "reason_code": code,
            "degraded": ["港股候选不可用：" + {
                "redistribution_permission_missing": "尚无已核验的自动采集与公开衍生结论发布授权",
                "authorized_snapshot_invalid": "授权快照、场次、账本或配置未通过核验",
            }[code]],
            "requirements": ["允许自动采集及公开衍生结论和证券身份发布的授权",
                             "普通股证券身份及行业覆盖", "最新已完成交易场次的收盘快照"]}


def _read(path, limit=MAX_BYTES):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds byte budget")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _text(doc, key, limit=160):
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("missing or invalid " + key)
    return value.strip()


def _authorization(auth, now):
    if auth.get("schema_version") != 1:
        raise ValueError("invalid authorization schema")
    for key in ("source_id", "source_name", "terms_url", "clause", "reviewed_by"):
        _text(auth, key, 1000 if key in {"terms_url", "clause"} else 160)
    if not auth["terms_url"].startswith("https://"):
        raise ValueError("terms reference must be HTTPS")
    # An operator's verified receipt is evidence routing, not a grant of rights.
    if any(auth.get(key) is not True for key in
           ("automated_acquisition", "public_derived_candidates", "public_security_metadata")):
        raise ValueError("permission scope missing")
    today = now.astimezone(HKT).date()
    if not date.fromisoformat(auth["reviewed_on"]) <= today <= date.fromisoformat(auth["valid_until"]):
        raise ValueError("authorization expired or future")


def screen_snapshot(snapshot, auth, portfolio, registry, *, now, receipt_hash):
    _authorization(auth, now)
    if snapshot.get("schema_version") != 1 or snapshot.get("source_id") != auth["source_id"]:
        raise ValueError("snapshot source mismatch")
    source = {k: auth[k] for k in ("source_id", "source_name", "terms_url", "clause")}
    return _screen(snapshot, source, portfolio, registry, now=now, receipt_hash=receipt_hash)


def _screen(snapshot, source, portfolio, registry, *, now, receipt_hash=None):
    from clawock.market_data.discovery_common import excluded_exposure, MISSING

    session = latest_completed_session("HK", at=now)
    if session is None or snapshot.get("session_date") != session.isoformat():
        raise ValueError("snapshot not latest completed session")
    observed = datetime.fromisoformat(snapshot["observed_at"])
    close_hour = 12 if session.isoformat() in HK_HALF_DAYS else 16
    if (observed.tzinfo is None or observed > now or observed.astimezone(HKT).date() != session
            or observed.astimezone(HKT).hour < close_hour):
        raise ValueError("unverified closing observation")
    rows = snapshot.get("rows")
    # Empty/malformed feed is unavailable, never a successful empty screen.
    if not isinstance(rows, list) or not 1 <= len(rows) <= 15000:
        raise ValueError("invalid snapshot rows")
    blocked = excluded_exposure(portfolio, registry)
    blocked = {s.zfill(5) if s.isdigit() else s for s in blocked}
    rejected = Counter()
    eligible = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("malformed row")
        ticker = _text(raw, "ticker")
        if not re.fullmatch(r"[0-9]{5}", ticker) or ticker == "00000" or ticker in seen:
            raise ValueError("invalid or duplicate ticker")
        seen.add(ticker)
        if ticker in blocked:
            rejected["held_or_underlying"] += 1
            continue
        if raw.get("security_type") != "ordinary_share":
            rejected["security_type"] += 1
            continue
        name, sector, industry = [_text(raw, k) for k in ("name", "sector", "industry")]
        values = [to_strict_finite_number(raw.get(k)) for k in
                  ("market_cap_hkd", "price_hkd", "turnover_hkd", "change_pct")]
        if any(v is None for v in values):
            raise ValueError("missing screening metrics")
        cap, price, turnover, change = values
        if (cap < POLICY["min_market_cap_hkd"] or price < POLICY["min_price_hkd"]
                or turnover < POLICY["min_turnover_hkd"]
                or not POLICY["min_change_pct"] <= change <= POLICY["max_change_pct"]):
            rejected["snapshot_filters"] += 1
            continue
        eligible.append((turnover, {
            "ticker": ticker, "market": "HK", "name": name,
            "sector": sector, "sector_label": sector, "industry": industry,
            "state": "needs_entry_gate", "allowed": False,
            "reason": "收盘快照通过规模、流动性与涨跌幅筛选；跨板块待研究",
            "evidence": {"source": source["source_id"], "retrieved_at": now.isoformat(),
                         "observed_at": observed.isoformat(), "session_date": session.isoformat(),
                         "freshness": "latest_completed_session",
                         **({"authorization_sha256": receipt_hash} if receipt_hash else {})},
            "missing_evidence": list(MISSING),
            "next_action": "核验报价与一手披露，运行 entry-gate，再决定是否深研",
            "quote_request": {"ticker": ticker, "region": "hk"},
            "research_route": "entry-gate -> hk-stock-analysis full-report",
        }))
    counts = Counter()
    selected = []
    for _, row in sorted(eligible, key=lambda pair: (-pair[0], pair[1]["ticker"])):
        if counts[row["sector"]] < POLICY["max_per_sector"]:
            selected.append(row)
            counts[row["sector"]] += 1
        if len(selected) == POLICY["max_candidates"]:
            break
    return {"schema_version": 1, "market": "HK", "research_only": True,
            "status": "ok" if selected else "no_candidates", "generated_at": now.isoformat(),
            "candidates": selected, "scanned_count": len(rows), "eligible_count": len(eligible),
            "rejections": dict(rejected), "policy": dict(POLICY),
            "publication": "derived_candidates_and_security_metadata_only",
            "source": dict(source),
            "limitations": ["收盘快照只生成研究候选，不是实时交易信号；不发布原始行情",
                            "不承诺港股全市场覆盖",
                            "目标价与评级缺失；候选不授权交易"]}


def collect(workspace, *, now=None):
    from clawock.instruments import load_registry

    base = Path(workspace) / ".cache" / "hk-discovery"
    auth_path = base / "authorization.json"
    if not auth_path.exists():
        return _collect_live(workspace, now=now or datetime.now(timezone.utc))
    now = now or datetime.now(timezone.utc)
    try:
        auth, receipt_hash = _read(auth_path, limit=16384)
        _authorization(auth, now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return unavailable()
    try:
        snapshot, _ = _read(base / "snapshot.json")
        portfolio, _ = _read(Path(workspace) / "portfolio.json")
        registry = load_registry(Path(workspace) / "config/instruments.json", missing_ok=True)
        return screen_snapshot(snapshot, auth, portfolio, registry, now=now, receipt_hash=receipt_hash)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return unavailable("authorized_snapshot_invalid")

def _collect_live(workspace, *, now):
    import requests

    from clawock.instruments import load_registry
    from .hk_discovery_live import SOURCE, fetch_quotes, parse_quotes
    from .discovery_common import excluded_exposure

    result = {'schema_version': 1, 'market': 'HK', 'research_only': True,
              'status': 'incomplete', 'candidates': [], 'generated_at': now.isoformat(),
              'source': dict(SOURCE), 'publication': 'derived_candidates_and_security_metadata_only',
              'coverage': 'curated_ordinary_shares_not_full_market'}
    try:
        config, _ = _read(Path(workspace) / 'config/hk-discovery-universe.json')
        if config.get('schema_version') != 1 or not 1 <= len(config['securities']) <= 100:
            raise ValueError('invalid universe')
        universe = {}
        for row in config['securities']:
            ticker = _text(row, 'ticker')
            if not re.fullmatch(r'[0-9]{5}', ticker) or ticker == '00000' or ticker in universe:
                raise ValueError('invalid universe ticker')
            if row.get('security_type') != 'ordinary_share':
                raise ValueError('nonordinary universe entry')
            universe[ticker] = {k: _text(row, k) for k in ('ticker', 'sector', 'industry', 'security_type')}
        portfolio, _ = _read(Path(workspace) / 'portfolio.json')
        registry = load_registry(Path(workspace) / 'config/instruments.json', missing_ok=True)
        excluded_exposure(portfolio, registry)  # Fail closed before network on unknown exposure.
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {**result, 'reason_code': 'invalid_discovery_inputs',
                'degraded': ['港股发现缺少有效股票池、持仓或底层暴露元数据']}
    try:
        rows, stamps, failed = parse_quotes(fetch_quotes(list(universe)), universe, now)
    except (requests.RequestException, ValueError, TypeError):
        return {**result, 'reason_code': 'quote_source_failed',
                'degraded': ['Tencent 港股批量行情失败；未完成筛选']}
    result['missing'] = failed
    result['requested_count'] = len(universe)
    if not rows:
        return {**result, 'reason_code': 'no_usable_closing_quotes', 'scanned_count': 0,
                'degraded': ['Tencent 港股缺少可用收盘报价：' + ', '.join(sorted(failed))]}
    snapshot = {'session_date': latest_completed_session('HK', at=now).isoformat(),
                'observed_at': min(stamps[r['ticker']] for r in rows), 'rows': rows}
    screened = _screen(snapshot, SOURCE, portfolio, registry, now=now)
    result.update(screened)
    for candidate in result['candidates']:
        candidate['evidence']['observed_at'] = stamps[candidate['ticker']]
    # The curated pool is useful but never a complete market scan.
    result['status'] = 'partial'
    result['degraded'] = ['港股仅覆盖配置的跨行业普通股池，非全市场扫描']
    if failed:
        result['degraded'].append('Tencent 港股缺失或无效收盘报价：' + ', '.join(sorted(failed)))
    return result
