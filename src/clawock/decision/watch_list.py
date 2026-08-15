"""Non-held AI watch list — 观察池扫描,只报机会、绝不下单授权(#556).

`config/watch-list.json` 列出 kcn 关注但未持仓的名字(智谱 02513 / 迅策 03317)。
brief preflight 每天对这些名字做一次价格面扫描:突破 / 接近突破 / 5d 大涨
才出现在 context 的 `watch_list` 段,LLM 把它写进"新机会"节。观察池名字
绝不进入 decisions(不进 `_constraints` / plan / add 授权)。

数据源与持仓扫描完全一致(compute_signals / 短历史降级),零新抓取成本。
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.workspace import workspace_root
from clawock.decision import signals as quant_signals
from clawock.portfolio.instruments import get as get_instrument

WS = workspace_root(Path.cwd())
WATCH_LIST = WS / "config" / "watch-list.json"

# 出现门槛:距 20 日高 ≤5%、或 5d 收益 ≥8%(次新无前高数据时只看 5d)
NEAR_HIGH_PCT = 5.0
STRONG_5D_PCT = 8.0


def watch_tickers() -> list[str]:
    """Registered watch-list tickers (fail-soft: a broken config is empty)."""
    try:
        doc = json.loads(WATCH_LIST.read_text())
        return [str(t) for t in (doc.get("tickers") or []) if t]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def collect() -> dict:
    """Scan watch-list names on completed bars; never raises, never authorizes.

    Returns ``{"rows": [...]}`` where a row is present only when the name is
    breaking out, within NEAR_HIGH_PCT of its 20d high, or up ≥STRONG_5D_PCT
    over 5 sessions. Each row: ticker / name / close / prior_20d_high /
    pct_from_high / ret_5d / state(breakout | near_breakout | strong).
    """
    rows = []
    short_history = getattr(quant_signals, "compute_short_history_signals", None)
    for ticker in watch_tickers():
        meta = get_instrument(ticker) or {}
        code = meta.get("tencent_symbol")
        if not code:
            continue
        try:
            bars = quant_signals.fetch_bars(code, 400)
            sig = quant_signals.compute_signals(bars)
            if sig is None and short_history is not None:
                sig = short_history(bars)
        except Exception:  # noqa: BLE001 — one dead feed must not blank the rest
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
        elif pct_from_high is not None and pct_from_high >= -NEAR_HIGH_PCT:
            state = "near_breakout"
        elif ret_5d is not None and ret_5d >= STRONG_5D_PCT:
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
    return {"rows": rows}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
