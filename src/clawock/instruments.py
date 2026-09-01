"""Canonical instrument metadata shared by dashboard, risk, quant and brief.

The JSON file is deliberately data-only so exchange suffixes, leverage and
look-through relationships can be reviewed without importing a consumer.
Validation is dependency-free because every host-side safety gate imports this
module and CI intentionally installs only the project's minimal dependencies.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


from clawock.workspace import engine_config, workspace_root

WS = workspace_root()
REGISTRY_FILE = WS / "config" / "instruments.json"
SCHEMA_FILE = engine_config("instruments.schema.json")
SCHEMA_VERSION = 1

REQUIRED_FIELDS = {
    "name",
    "region",
    "currency",
    "venue",
    "venue_suffix",
    "tencent_symbol",
    "eastmoney_secid",
    "sector",
    "themes",
    "factor",
    "leverage_multiple",
    "underlying",
    "one_x_substitute",
    "signal_symbol",
    "listing_date",
    "peer_bucket",
    "retired",
}
ACTIVE_REQUIRED_VALUES = {
    "name",
    "region",
    "currency",
    "venue",
    "tencent_symbol",
    "sector",
    "themes",
    "factor",
    "leverage_multiple",
    "peer_bucket",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_registry(doc: Any) -> list[str]:
    """Return every schema/relationship error; an empty list means valid."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["registry must be an object"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    instruments = doc.get("instruments")
    if not isinstance(instruments, dict) or not instruments:
        return errors + ["instruments must be a non-empty object"]

    for symbol, meta in instruments.items():
        where = f"instruments.{symbol}"
        if not isinstance(symbol, str) or not symbol:
            errors.append("instrument symbol must be a non-empty string")
            continue
        if not isinstance(meta, dict):
            errors.append(f"{where} must be an object")
            continue
        missing = sorted(REQUIRED_FIELDS - set(meta))
        extra = sorted(set(meta) - REQUIRED_FIELDS)
        if missing:
            errors.append(f"{where} missing fields: {', '.join(missing)}")
        if extra:
            errors.append(f"{where} unknown fields: {', '.join(extra)}")
        if meta.get("region") not in {"US", "HK"}:
            errors.append(f"{where}.region must be US or HK")
        expected_currency = {"US": "USD", "HK": "HKD"}.get(meta.get("region"))
        if expected_currency and meta.get("currency") != expected_currency:
            errors.append(f"{where}.currency must be {expected_currency}")
        if meta.get("region") == "US":
            suffix = meta.get("venue_suffix")
            if not isinstance(suffix, str) or not suffix.startswith("."):
                errors.append(f"{where}.venue_suffix must pin a US exchange suffix")
            expected_tencent = f"us{symbol}{suffix}" if isinstance(suffix, str) else None
            if meta.get("tencent_symbol") != expected_tencent:
                errors.append(
                    f"{where}.tencent_symbol must match pinned venue: {expected_tencent}"
                )
        elif meta.get("venue") == "HKEX":
            if meta.get("venue_suffix") is not None:
                errors.append(f"{where}.venue_suffix must be null for HKEX")
            if meta.get("tencent_symbol") != f"hk{symbol}":
                errors.append(f"{where}.tencent_symbol must be hk{symbol}")
        secid = meta.get("eastmoney_secid")
        if secid is not None and (
            not isinstance(secid, str) or not secid.endswith(f".{symbol}")
        ):
            errors.append(f"{where}.eastmoney_secid must end with .{symbol}")
        if not isinstance(meta.get("themes"), list) or not meta.get("themes"):
            errors.append(f"{where}.themes must be a non-empty list")
        elif len(meta["themes"]) != len(set(meta["themes"])):
            errors.append(f"{where}.themes must not contain duplicates")
        leverage = meta.get("leverage_multiple")
        if not isinstance(leverage, (int, float)) or isinstance(leverage, bool) or leverage < 1:
            errors.append(f"{where}.leverage_multiple must be a number >= 1")
        listing_date = meta.get("listing_date")
        # #647: the short-history gate (#608) depends on this field being
        # present and recent — a null listing_date makes it fail closed and
        # silent. It is registry data hygiene now, not an optional field.
        if not isinstance(listing_date, str) or not _DATE_RE.fullmatch(listing_date):
            errors.append(f"{where}.listing_date must be YYYY-MM-DD (non-null)")
        if not isinstance(meta.get("retired"), bool):
            errors.append(f"{where}.retired must be boolean")
        for field in ("name", "venue", "sector", "factor", "peer_bucket"):
            if not isinstance(meta.get(field), str) or not meta.get(field):
                errors.append(f"{where}.{field} must be a non-empty string")

    for symbol, meta in instruments.items():
        # ``underlying`` may be an index/private factor with no listed registry
        # entry. The actionable 1x substitute and quant signal proxy must always
        # resolve to a concrete registered instrument.
        for field in ("one_x_substitute", "signal_symbol"):
            target = meta.get(field)
            if target and target not in instruments:
                errors.append(f"instruments.{symbol}.{field} references unknown {target}")
        if meta.get("leverage_multiple", 1) > 1 and not meta.get("underlying"):
            errors.append(f"instruments.{symbol} leveraged instrument needs underlying")
        if meta.get("one_x_substitute"):
            target = instruments.get(meta["one_x_substitute"], {})
            if target.get("leverage_multiple") != 1:
                errors.append(
                    f"instruments.{symbol}.one_x_substitute must have leverage_multiple=1"
                )
            if target.get("factor") != meta.get("factor"):
                errors.append(
                    f"instruments.{symbol}.one_x_substitute must share look-through factor"
                )
    return errors


def load_registry(path: Path | str = REGISTRY_FILE,
                  *, missing_ok: bool = False) -> dict[str, dict]:
    """The book's instruments.

    `missing_ok` separates two things this used to conflate (#356). An ABSENT
    registry means the workspace has registered nothing yet — true of any book
    that is not this one — and must not stop the module from importing, because
    every host-side gate imports it. A MALFORMED registry is corruption and
    still raises: degrading there would publish numbers against metadata nobody
    validated.
    """
    path = Path(path)
    if missing_ok and not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read instrument registry {path}: {exc}") from exc
    errors = validate_registry(doc)
    if errors:
        raise ValueError("invalid instrument registry: " + "; ".join(errors))
    return doc["instruments"]


def validate_active_holdings(
    portfolio: dict, registry: dict[str, dict] | None = None
) -> list[str]:
    """Fail closed when a live holding lacks metadata needed by consumers."""
    registry = registry or load_registry()
    errors: list[str] = []
    for bucket, expected_region in (("us_stocks", "US"), ("hk_stocks", "HK")):
        holdings = portfolio.get("portfolios", {}).get(bucket, {}).get("holdings", [])
        for holding in holdings:
            if (holding.get("shares") or 0) <= 0:
                continue
            symbol = holding.get("ticker")
            meta = registry.get(symbol)
            if not meta:
                errors.append(f"active {bucket} holding {symbol!r} missing from registry")
                continue
            if meta.get("region") != expected_region:
                errors.append(
                    f"active {symbol} registry region {meta.get('region')} != {expected_region}"
                )
            empty = sorted(
                field for field in ACTIVE_REQUIRED_VALUES if meta.get(field) in (None, "", [])
            )
            if empty:
                errors.append(f"active {symbol} missing required values: {', '.join(empty)}")
            if meta.get("retired"):
                errors.append(f"active {symbol} is declared retired")
    return errors


# Import must not depend on this book having a registry. Every host-side safety
# gate imports this module, so raising here took the whole toolchain down for any
# workspace but this one — `brief_preflight`, `report_preflight` and
# `intraday_preflight` all died at import against a foreign book (#356).
#
# Absence yields an empty registry, and that is not silent: `validate_active_holdings`
# then reports every live holding as unregistered, which system_check raises as
# CRITICAL. A book with holdings and no registry gets a loud, accurate, actionable
# message instead of a stack trace from an import.
INSTRUMENTS = load_registry(missing_ok=True)


def get(symbol: str, *, registry: dict[str, dict] | None = None) -> dict | None:
    return (INSTRUMENTS if registry is None else registry).get(symbol)


def require(symbol: str) -> dict:
    meta = get(symbol)
    if meta is None:
        raise KeyError(f"instrument {symbol!r} missing from canonical registry")
    return meta


def market_for_symbol(symbol: str) -> str:
    """The trading calendar this symbol settles on: ``'hk'`` or ``'us'``.

    The registry's ``region`` is the single source; the fallbacks only exist so
    a symbol that predates or outruns the registry still lands deterministically
    instead of raising in an offline reviewer. Bare digit codes are HKEX stock
    codes, ``HS*`` index proxies (HSTECH) ride the HK calendar, everything else
    alphabetic is assumed US-listed — the same assumption every history row
    writer already makes.
    """
    region = str((get(str(symbol)) or {}).get("region") or "").lower()
    if region in ("hk", "us"):
        return region
    code = str(symbol or "")
    if code.isdigit() or code.upper().startswith("HS"):
        return "hk"
    return "us"


def is_leveraged(symbol: str) -> bool:
    meta = get(symbol)
    return bool(meta and meta["leverage_multiple"] > 1)


_LEVERAGED_NAME_MARKERS = (
    "倍", "direxion", "t-rex", "defiance", "proshares",
    "2x long", "3x long", "daily target", "xl二", "xl三", "xl两", "两倍",
)


def is_leveraged_holding(
    holding: dict, *, registry: dict[str, dict] | None = None
) -> bool:
    """Classify a live holding conservatively when registry coverage lags.

    Registered metadata remains authoritative. The explicit holding flag and
    name fallback cover a newly listed leveraged product before its registry PR
    lands, so a safety consumer never silently treats an unknown 2x/3x name as 1x.
    """
    if holding.get("is_leveraged_etf") is True:
        return True
    symbol = str(holding.get("ticker") or "")
    meta = get(symbol, registry=registry)
    if meta is not None:
        return float(meta.get("leverage_multiple") or 1) > 1
    name = str(holding.get("name") or holding.get("stock_name") or "").casefold()
    return (
        any(marker.casefold() in name for marker in _LEVERAGED_NAME_MARKERS)
        or re.search(r"(?<!\w)[23]\s*[x×](?!\w)", name) is not None
    )


def look_through(
    symbol: str, *, max_hops: int = 3,
    registry: dict[str, dict] | None = None,
) -> dict:
    """Resolve a holding to the issuer whose news, filings and earnings move it.

    A 2x single-stock ETF publishes nothing of its own: PLTU is moved by PLTR,
    MSFU by MSFT. An index or sector fund has no issuer at all — SOXL follows SOXX
    follows SEMICONDUCTOR, and none of those file anything — so asking a news or
    earnings source about it returns either nothing or marketing copy.

    Returns ``kind`` of ``issuer`` (holding reports for itself), ``look_through``
    (with ``issuer`` set to the company it tracks), or ``index_fund`` (no issuer;
    ``tracks`` names what it follows).

    This is the single home for the rule: it was independently reimplemented for
    the intraday catalyst probe, the earnings calendar and the news digest, and a
    fourth copy would eventually disagree with the other three.
    """
    chain: list[str] = []
    current = str(symbol or "")
    if not current:
        return {"kind": "index_fund", "issuer": None, "tracks": None, "chain": chain}
    for _ in range(max_hops):
        meta = get(current, registry=registry) or {}
        underlying = meta.get("underlying")
        if not underlying or underlying in chain:
            break
        chain.append(current)
        current = str(underlying)
    if not chain:
        return {"kind": "issuer", "issuer": str(symbol), "tracks": None, "chain": chain}
    final = get(current, registry=registry)
    no_issuer = (
        final is None                       # a label like NASDAQ_100, not a security
        or final.get("venue") == "INDEX"    # an index
        or bool(final.get("underlying"))    # still a fund after max_hops
    )
    if no_issuer:
        return {"kind": "index_fund", "issuer": None, "tracks": current, "chain": chain}
    return {"kind": "look_through", "issuer": current, "tracks": current, "chain": chain}


def issuer_for(symbol: str) -> str | None:
    """The reporting issuer behind a holding, or None when there is none."""
    return look_through(symbol)["issuer"]


def canonical_bar_manifest() -> dict[str, dict]:
    """Compatibility view used by the canonical raw-bar writer."""
    out: dict[str, dict] = {}
    for symbol, meta in INSTRUMENTS.items():
        if not meta.get("tencent_symbol") or not meta.get("eastmoney_secid"):
            continue
        out[symbol] = {
            "leg": meta["region"],
            "tencent": meta["tencent_symbol"],
            "em": meta["eastmoney_secid"],
            "name": meta["name"],
            "retired": meta["retired"],
        }
    return out


def leveraged_symbols() -> set[str]:
    return {s for s, meta in INSTRUMENTS.items() if meta["leverage_multiple"] > 1}


def leverage_map() -> dict[str, float]:
    return {
        s: meta["leverage_multiple"]
        for s, meta in INSTRUMENTS.items()
        if meta["leverage_multiple"] > 1
    }


def one_x_swap_map() -> dict[str, str]:
    return {
        s: meta["one_x_substitute"]
        for s, meta in INSTRUMENTS.items()
        if meta.get("one_x_substitute")
    }


def compute_lookthrough_exposure(portfolio: dict) -> dict[str, dict]:
    """Gross exposure and HHI by canonical sector and underlying factor."""
    result: dict[str, dict] = {"us": {}, "hk": {}}
    for region in ("us_stocks", "hk_stocks"):
        key = "us" if region == "us_stocks" else "hk"
        active = [
            h
            for h in portfolio["portfolios"][region].get("holdings", [])
            if (h.get("shares") or 0) > 0
        ]
        by_factor: dict[str, dict] = {}
        by_sector: dict[str, dict] = {}
        capital_total = sum(float(h.get("current_value") or 0) for h in active)
        mapped_capital = 0.0
        for holding in active:
            value = float(holding.get("current_value") or 0)
            meta = get(holding["ticker"])
            if not meta:
                factor = f"UNMAPPED:{holding['ticker']}"
                sector = "Other"
                multiple = 1.0
            else:
                factor = meta["factor"]
                sector = meta["sector"]
                multiple = float(meta["leverage_multiple"])
                mapped_capital += value
            gross = value * multiple
            for mapping, label in ((by_factor, factor), (by_sector, sector)):
                row = mapping.setdefault(
                    label, {"capital_value": 0.0, "gross_value": 0.0, "tickers": []}
                )
                row["capital_value"] += value
                row["gross_value"] += gross
                row["tickers"].append(holding["ticker"])

        gross_total = sum(row["gross_value"] for row in by_factor.values())

        def serialize(mapping: dict[str, dict], label_key: str) -> list[dict]:
            rows = []
            for label, row in mapping.items():
                pct = row["gross_value"] / gross_total * 100 if gross_total else 0.0
                rows.append(
                    {
                        label_key: label,
                        "capital_value": round(row["capital_value"], 2),
                        "gross_value": round(row["gross_value"], 2),
                        "gross_pct": round(pct, 2),
                        "tickers": sorted(row["tickers"]),
                    }
                )
            return sorted(rows, key=lambda row: row["gross_pct"], reverse=True)

        factor_rows = serialize(by_factor, "factor")
        sector_rows = serialize(by_sector, "sector")
        result[key] = {
            "capital_value": round(capital_total, 2),
            "gross_value": round(gross_total, 2),
            "metadata_coverage_pct": (
                round(mapped_capital / capital_total * 100, 2)
                if capital_total
                else 100.0
            ),
            "factor_hhi": round(
                sum((row["gross_pct"] / 100) ** 2 for row in factor_rows), 4
            ),
            "sector_hhi": round(
                sum((row["gross_pct"] / 100) ** 2 for row in sector_rows), 4
            ),
            "factors": factor_rows,
            "sectors": sector_rows,
        }
    return result


def main() -> int:
    portfolio_path = WS / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    errors = validate_active_holdings(portfolio)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    active = sum(
        1
        for bucket in ("us_stocks", "hk_stocks")
        for holding in portfolio["portfolios"][bucket]["holdings"]
        if (holding.get("shares") or 0) > 0
    )
    print(
        f"instrument registry OK: {len(INSTRUMENTS)} instruments, "
        f"{active} active holdings fully mapped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
