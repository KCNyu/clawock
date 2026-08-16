"""Non-held AI watch list — 观察池扫描,只报机会、绝不下单授权(#556).

`config/watch-list.json` 列出 kcn 关注但未持仓的名字(智谱 02513 / 迅策 03317)。
brief preflight 每天对这些名字做一次价格面扫描:突破 / 接近突破 / 5d 大涨
才出现在 context 的 `watch_list` 段,LLM 把它写进"新机会"节。观察池名字
绝不进入 decisions(不进 `_constraints` / plan / add 授权)。

数据源与持仓扫描完全一致(compute_signals / 短历史降级),零新抓取成本。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from clawock.decision import signals as quant_signals
from clawock.market_data import sessions as trading_calendar
from clawock.portfolio.instruments import get as get_instrument
from clawock.workspace import workspace_root

# 出现门槛:距 20 日高 ≤5%、或 5d 收益 ≥8%(次新无前高数据时只看 5d)。
# NEAR_HIGH_PCT 的单一真源在 add-alpha-policy.json 的 `opportunity_near_pct`
# (#621)——radar 与 watch list 同读一个值,改配置两边同时生效;
# STRONG_5D_PCT 的单一真源在 `strong_5d_pct`(#640)。下面两个常量只是
# 配置缺失时的 fallback 默认值。
NEAR_HIGH_PCT = 5.0
STRONG_5D_PCT = 8.0


def _watch_list_path() -> Path:
    """Config path, resolved at call time (#620: import must not depend on cwd)."""
    return workspace_root(Path.cwd()) / "config" / "watch-list.json"


def _policy_near_pct() -> float:
    """`opportunity_near_pct` from add-alpha-policy.json, default NEAR_HIGH_PCT.

    Explicit None check, never `X or DEFAULT` (#649): a config value of 0 is a
    legal threshold ("只有真突破算机会") and must not be swallowed into the
    default. The literal key keeps the policy-key parity trip-wire alive.
    """
    try:
        policy = json.loads(
            (workspace_root(Path.cwd()) / "config" / "add-alpha-policy.json")
            .read_text(encoding="utf-8"))
        raw = policy.get("opportunity_near_pct")
        if raw is not None:
            return float(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return NEAR_HIGH_PCT


def _policy_strong_5d_pct() -> float:
    """`strong_5d_pct` from add-alpha-policy.json, default STRONG_5D_PCT (#640)."""
    try:
        policy = json.loads(
            (workspace_root(Path.cwd()) / "config" / "add-alpha-policy.json")
            .read_text(encoding="utf-8"))
        raw = policy.get("strong_5d_pct")
        if raw is not None:
            return float(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return STRONG_5D_PCT


def watch_tickers() -> list[str]:
    """Registered watch-list tickers (fail-soft: a broken config is empty)."""
    try:
        doc = json.loads(_watch_list_path().read_text())
        return [str(t) for t in (doc.get("tickers") or []) if t]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def collect() -> dict:
    """Scan watch-list names on completed bars; never raises, never authorizes.

    Returns ``{"rows": [...], "errors": [...]}`` where a row is present only
    when the name is breaking out, within near-high % of its 20d high, or up
    ≥STRONG_5D_PCT over 5 sessions. A watch-list ticker missing from
    instruments.json (or without a canonical Tencent symbol) is reported in
    `errors` — a typo must not be a permanent silent no-scan (#602).
    """
    rows, errors = [], []
    near_pct = _policy_near_pct()
    strong_5d_pct = _policy_strong_5d_pct()
    for ticker in watch_tickers():
        meta = get_instrument(ticker) or {}
        code = meta.get("tencent_symbol")
        if not code:
            errors.append({'ticker': ticker,
                           'error': 'missing instruments.json entry or Tencent symbol'})
            continue
        try:
            bars = quant_signals.fetch_bars(code, 400)
            # "On completed bars" is a real filter, not a docstring promise
            # (#621): an intraday re-run must not read the still-open bar as a
            # completed daily candle.
            region = meta.get('region')
            expected = (trading_calendar.latest_completed_session(region)
                        if region else None)
            if expected:
                bars = [
                    bar for bar in bars
                    if bar.get('date') is not None
                    and date.fromisoformat(str(bar['date'])[:10]) <= expected
                ]
            sig = quant_signals.compute_signals(bars)
            if sig is None and quant_signals.is_short_history_candidate(
                    meta, date.today()):
                # Only a genuinely-new name may use the 20-bar short view; a
                # partial-feed mature name stays on the 30-bar gate (#608).
                sig = quant_signals.compute_short_history_signals(bars)
        except Exception as exc:  # noqa: BLE001 — one dead feed must not blank the rest
            errors.append({'ticker': ticker,
                           'error': f'{type(exc).__name__}: {exc}'[:200]})
            continue
        if not sig:
            continue
        close = sig.get("close")
        prior = sig.get("prior_20d_high")
        if close is None:
            continue
        pct_from_high = (close / prior - 1) * 100 if prior and prior > 0 else None
        closes = [b.get("close") for b in bars if b.get("close") is not None]
        ret_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else None
        if prior is not None and close > prior:
            state = "breakout"
        elif pct_from_high is not None and pct_from_high >= -near_pct:
            state = "near_breakout"
        elif ret_5d is not None and ret_5d >= strong_5d_pct:
            state = "strong"
        else:
            continue
        rows.append({
            "ticker": ticker,
            "name": meta.get("name") or ticker,
            "close": close,
            "prior_20d_high": prior,
            "pct_from_high": (round(pct_from_high, 2)
                              if pct_from_high is not None else None),
            "ret_5d": round(ret_5d, 2) if ret_5d is not None else None,
            "state": state,
        })
    rows.sort(key=lambda row: (
        row["state"] != "breakout",
        -(row["ret_5d"] or 0),
    ))
    result = {"rows": rows}
    if errors:
        result["errors"] = errors
    return result


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
