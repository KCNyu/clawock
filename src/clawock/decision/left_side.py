"""Left-side scale-in: buying into weakness, in rungs, inside an unbroken trend.

kcn 2026-09-26: 「我个人偏左侧交易…这套也要进策略，不能只有右侧确认」. Every
existing add setup waits for confirmation — `trend_pullback` needs the MA20
reclaimed, `confirmed_breakout` a close over the 20-day high, `oversold_reclaim`
a close over yesterday's high. This family does not: it places resting
`price_below` rungs under a weak print and lets the weakness fill them.

What the evidence allowed (``clawock evaluate-add-shapes --campaigns``, Tencent
daily bars 2023-07..2026-09, 28 names, IS < 2025-07-01 ≤ OOS, pre-registered):

* permissionless deep dip (the shape #819 rejected) — OOS max drawdown −15.8%
  of book at 1%/unit: rejected again;
* the same dip **only above MA200, non-leveraged** — mean return per campaign
  above the unconditional baseline in both halves, with the 90% month-block
  bootstrap lower bound above zero in both;
* the same rule on daily-reset leveraged products — negative in both halves:
  excluded, not half-sized (the 2x decay is what a 20-session wait pays).

So the family is narrow on purpose. Weakness is measured in ATRs below the
prior 20-day high, so a 2x-volatile name needs a 2x-deeper fall; the trend
permission is price above MA200; a thesis that is not ``intact`` or a negative
information reading blocks it upstream (``packet``), because a fall that is the
thesis breaking is value destruction, not sentiment.

Rungs are anchored to the prior 20-day high and ATR, both known at the signal
close, so the ladder is a pure function of today's row plus how many rungs the
ledger says were already filled — no hidden state. Everything here is pure.
"""
from __future__ import annotations

import hashlib
import json

from clawock.safe_io import to_number as _number

SETUP_ID = "left_scale_in"
TIER = "left_scale_in"


def _terms(policy: dict) -> dict | None:
    terms = (policy or {}).get("left_side") or {}
    return terms if terms.get("enabled") else None


def ladder(row: dict, policy: dict) -> dict | None:
    """Rungs and invalidation for one name at one close, or None.

    ``row`` is a `signals.compute_signals` row (``close``, ``ma200``,
    ``atr14_pct``, ``prior_20d_high``). Returns ``{"rungs": [...],
    "invalidation_price", "depth_atr", "atr"}`` with only the rungs that sit
    above the invalidation.
    """
    terms = _terms(policy)
    if terms is None:
        return None
    close = _number(row.get("close"))
    ma200 = _number(row.get("ma200"))
    atr_pct = _number(row.get("atr14_pct"))
    high = _number(row.get("prior_20d_high"))
    if not close or not atr_pct or not high or high <= 0:
        return None
    if terms.get("permission") == "close_above_ma200":
        if not ma200 or close <= ma200:
            return None
    atr = atr_pct / 100 * close
    depth = (high - close) / atr
    min_depth = float(terms["min_depth_atr"])
    if depth < min_depth:
        return None
    step = float(terms["ladder_atr"])
    first = high - min_depth * atr
    # Two exits, as pre-registered: an intraday hard stop a fixed number of
    # ATRs under the first rung, and a trend break judged on the CLOSE (a close
    # under MA200 withdraws the permission the ladder was placed under). An
    # intraday MA200 touch is not a trend break — folding MA200 into the
    # intraday stop was measured and cut the hit rate to ~31%.
    invalidation = first - float(terms["stop_atr_below_first"]) * atr
    rungs = [first - i * step * atr for i in range(int(terms["max_tranches"]))]
    rungs = [price for price in rungs if price > invalidation]
    if not rungs:
        return None
    return {
        "rungs": [round(price, 4) for price in rungs],
        "invalidation_price": round(invalidation, 4),
        "trend_floor": (round(ma200, 4)
                        if terms.get("permission") == "close_above_ma200" else None),
        "depth_atr": round(depth, 2),
        "atr": atr,
    }


def scale_in_setup(
    row: dict,
    policy: dict,
    *,
    ticker: str,
    market: str,
    leveraged: bool,
    used_tranches: int = 0,
    as_of: str | None = None,
) -> dict | None:
    """A packet setup for the next unfilled rung, or None.

    Leveraged products are excluded outright (evidence above). ``used_tranches``
    comes from the decision ledger's followed adds under this campaign id.
    """
    terms = _terms(policy)
    if terms is None or (leveraged and terms.get("leveraged", "exclude") == "exclude"):
        return None
    levels = ladder(row, policy)
    if levels is None:
        return None
    rungs = levels["rungs"]
    policy_hash = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:8]
    next_rung = min(int(used_tranches), len(rungs) - 1)
    return {
        "setup_id": SETUP_ID,
        "campaign_id": f"{str(market).upper()}:{ticker}:left:p1:{policy_hash}",
        "label": "左侧分批",
        # A resting buy under the print: the weakness fills it, no reclaim asked.
        "entry_type": "price_below",
        "entry_price": rungs[next_rung],
        "invalidation_price": levels["invalidation_price"],
        "max_tranches": len(rungs),
        "rungs": rungs,
        "authority_tier": TIER,
        "authority_sources": ["left_side_weakness"],
        "evidence_families": ["technical_weakness"],
        "valid_for_sessions": int(terms["valid_for_sessions"]),
        "evaluation_sessions": int(terms["evaluation_sessions"]),
        "signal_date": str(as_of or row.get("as_of") or "")[:10] or None,
        "depth_atr": levels["depth_atr"],
        **({"trend_floor": levels["trend_floor"]} if levels["trend_floor"] else {}),
        "detail": (
            f"收盘低于前 20 日高 {levels['depth_atr']:g} 个 ATR、仍在 MA200 上方；"
            f"分 {len(rungs)} 档挂低吸，每档间隔 {terms['ladder_atr']:g} ATR，"
            f"盘中跌破 {levels['invalidation_price']:g}（首档下 "
            f"{terms['stop_atr_below_first']:g} ATR）或收盘跌破 MA200"
            + (f" {levels['trend_floor']:g}" if levels["trend_floor"] else "")
            + " 即失效"
        ),
    }
