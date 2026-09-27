"""Left-side scale-in: buying into weakness, in rungs, inside an unbroken trend.

kcn 2026-09-26: 「我个人偏左侧交易…这套也要进策略，不能只有右侧确认」. Every
existing add setup waits for confirmation — `trend_pullback` needs the MA20
reclaimed, `confirmed_breakout` a close over the 20-day high, `oversold_reclaim`
a close over yesterday's high. This family does not: it places resting
`price_below` rungs under a weak print and lets the weakness fill them.

What the initial evidence showed (``clawock evaluate-add-shapes --campaigns``,
Tencent daily bars 2023-07..2026-09, 27 input names, 21 with IS history,
IS < 2025-07-01 ≤ OOS, one split):

* permissionless deep dip (the shape #819 rejected) — OOS max drawdown −15.8%
  of book at 1%/unit: rejected again;
* the same dip **only above MA200, non-leveraged** — OOS mean return per
  campaign 2.18%, with a 90% month-block interval of -0.17% to 5.08%; return
  per unit deployed 0.64% versus 1.70% for the baseline. This does not
  establish an edge for live sizing;
* the same rule on daily-reset leveraged products — negative in both halves:
  excluded, not half-sized (the 2x decay is what a 20-session wait pays).

What decided its live form (kcn 2026-09-27: 「还是要加上，只是看怎么用」 — the
direction is settled; the question was the shape). Same run, non-leveraged,
daily P&L of the left family against the right family (`right`):

* correlation 0.57 OOS (0.60 IS), monthly 0.77; left's beta on right 0.78 and
  its annualised alpha after that beta -0.72% of book per 1% unit. Adding a
  sleeve improves Sharpe only if its Sharpe exceeds corr × Sharpe(right)
  (0.62 OOS); left's is 0.42. Every weight tried (0.25/0.5/1) lowered the
  combined Sharpe (the run card's ``left_vs_right``). The combined family's
  positive CI lower bound is more campaigns pooled, not diversification;
* a one-off look per rung: the third rung is the weakest in both halves (unit
  return to exit IS 3.6/3.9/0.19%, OOS 1.56/0.23/-0.69%).

The price rule alone therefore has no edge to size, and the one thing that
could give it one — the thesis/information/peer gates the packet applies — has
no history to replay. So the live form is ``mode: observe``: both entries
print the ladder, the packet records which gate held it (`observe`), and the
brief appends that to `assets/data/left_side_history.jsonl`, which is the
forward sample a sized form would have to be judged on. ``scale_in_setup``
refuses to produce an authorising setup until the policy says ``authorize``,
which is kcn's call along with the size.

So the family is narrow on purpose. Weakness is measured in ATRs below the
prior 20-day high, so a 2x-volatile name needs a 2x-deeper fall; the trend
permission is price above MA200; a thesis that is not ``intact`` or a negative
information reading blocks it upstream (``packet``), because a fall that is the
thesis breaking is value destruction, not sentiment.

Rungs are anchored to the prior 20-day high and ATR, both known at the signal
close, so the ladder is a pure function of today's row plus how many rungs the
ledger says were already filled — no hidden state. Everything here is pure
except the two file edges, `load_policy` and `record_history`.
"""
from __future__ import annotations

import hashlib
import json

from clawock.safe_io import to_number as _number
from clawock.workspace import workspace_root

SETUP_ID = "left_scale_in"
TIER = "left_scale_in"
# Relative to the workspace, resolved per call: a run against another
# workspace (CLAWOCK_WORKSPACE) must not read or write this checkout's files.
POLICY_FILE = "config/left-side-policy.json"
HISTORY = "assets/data/left_side_history.jsonl"
# Which gate held a fired ladder back, in the order the packet checks them.
GATES = ("leveraged_excluded", "thesis_not_intact", "negative_information",
         "peer_laggard")


def load_policy(path=None) -> dict:
    """`{"left_side": {...}}` from the one owner file; `{}` when unreadable
    (no ladder is then placed anywhere, which is the safe failure)."""
    try:
        doc = json.loads((path or workspace_root() / POLICY_FILE).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"left_side": doc.get("left_side") or {}}


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
    # `observe` (the live mode) never produces a setup the packet could size.
    if terms.get("mode", "observe") != "authorize":
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


def observe(row: dict, policy: dict, *, leveraged: bool, thesis_state: str | None,
            blockers=()) -> dict | None:
    """What the ladder says for one holding and which gate would hold it back.

    None when the price condition did not fire. Otherwise the rungs, the
    invalidation, the MA200 floor and ``gate``: the first of `GATES` that
    applies (None = every gate passed). ``blockers`` are the packet's
    add-authority blockers; only the negative-information and persistent-peer-
    laggard ones are read here. Never sizes, never authorises.
    """
    terms = _terms(policy)
    if terms is None:
        return None
    levels = ladder(row, policy)
    if levels is None:
        return None
    blockers = set(blockers or ())
    gate = None
    if leveraged and terms.get("leveraged", "exclude") == "exclude":
        gate = "leveraged_excluded"
    elif (terms.get("requires_thesis") == "intact"
          and (thesis_state or "unknown") != "intact"):
        gate = "thesis_not_intact"
    elif "negative_information" in blockers:
        gate = "negative_information"
    elif "peer_laggard_avoidance" in blockers:
        gate = "peer_laggard"
    return {
        "mode": terms.get("mode", "observe"),
        "gate": gate,
        "rungs": levels["rungs"],
        "invalidation_price": levels["invalidation_price"],
        "trend_floor": levels["trend_floor"],
        "depth_atr": levels["depth_atr"],
        "close": _number(row.get("close")),
        "authorization": None,
    }


def history_row(packet: dict) -> dict:
    """One `left_side_history.jsonl` row: every holding whose ladder fired in
    this packet, with the gate that held it. Written every brief day, fired or
    not, so a quiet day is a recorded zero rather than a gap."""
    fired = {
        ticker: {"leg": row.get("leg"), **obs}
        for ticker, row in sorted(((packet or {}).get("tickers") or {}).items())
        if (obs := (row.get("quant") or {}).get("left_side"))
    }
    return {
        "as_of": str((packet or {}).get("date") or "")[:10],
        "generation_id": ((packet or {}).get("_meta") or {}).get("generation_id"),
        "rows": fired,
    }


def record_history(packet: dict, path=None) -> dict:
    """Replace today's row in the forward sample (one row per brief date)."""
    from clawock import history_store

    row = history_row(packet)
    if not row["as_of"]:
        return row
    target = path or workspace_root() / HISTORY
    kept = [old for old in history_store.load_series(target)
            if str(old.get("as_of") or "")[:10] != row["as_of"]]
    history_store.write_series(target, kept + [row])
    return row
