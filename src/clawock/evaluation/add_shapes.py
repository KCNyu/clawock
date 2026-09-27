#!/usr/bin/env python3
"""What each add-side entry shape has actually been worth on this book's bars.

Why this exists
---------------
On 2026-09-05 kcn asked whether adds should only follow breakouts —
「加仓不仅仅看追高趋势吧」/「甚至在跌也有可能应该加仓」— and the honest answer
required a measurement, not a citation. #856 had measured "deep dip" and
rejected it, but the shape kcn was describing (a pullback *inside* an uptrend)
had never been sampled at all. `add_side.py` says so in its own comments: the
`wait_rebreak` state "was dropped wholesale, so the desk never collected a
single sample to test whether 'buy the dip inside an uptrend' holds".

The answer got computed once in a terminal, which is exactly how #856's numbers
ended up quoted as fact with no way to re-derive them. So it lives here instead,
runs from the canonical bar store, and writes a run card.

What it measures
----------------
Four shapes, each evaluated at the close that formed them, against forward
returns at T+1 / T+5 / T+20:

* **breakout** — close above the prior 20-day high, `zscore20` below the policy's
  `early_no_chase_zscore`. The one shape #819/#856 measured positive.
* **breakout_overheated** — the same close, above that z ceiling. What the
  no-chase filter demotes to `wait_rebreak`.
* **pullback_in_uptrend** — inside 8% of the prior 20-day high, above the 50-day
  mean, with the 20-day mean above the 50-day. The shape that had no samples.
* **deep_dip** — more than 8% below the prior 20-day high. What #856 rejected.

And the number without which none of the four means anything: the unconditional
forward return of the same names over the same window. A shape that "hits 50% at
T+20" is worth nothing if a random session in this book hits 50.1%.

What it cannot tell you
-----------------------
Stated here rather than in a footnote, because these limits are larger than the
differences between three of the four rows:

* **Overlapping samples.** Every session of every name is a candidate, so a
  90-session run of one name contributes ~90 correlated observations. The `n`
  columns are event counts, not independent votes; the effective sample is far
  smaller and this module does not estimate it.
* **Survivorship.** The bar store holds names the desk currently follows.
  Anything cut before the store existed is absent, and its outcome with it.
* **One regime.** The window is a single up-market for a high-beta book; every
  row's mean is inflated by the same drift, which is what the baseline row is
  for. Cross-regime behaviour is not observable here at all.

`clawock evaluate-add-alpha` is the walk-forward evaluator with a proper
out-of-sample discipline. This is the cheap descriptive pass that answers "which
shapes are even worth walking forward", and it should never be quoted as if it
were the other one.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from clawock.evidence import run_card
from clawock.workspace import workspace_root

WS = workspace_root()
BARS_DIR = WS / "memory" / "bars"
POLICY_FILE = WS / "config" / "add-alpha-policy.json"
CAMPAIGN_POLICY_FILE = WS / "config" / "add-shapes-experiment.json"

HORIZONS = (1, 5, 20)
#: Shapes are defined against the same 20-day level the add side uses, so this
#: table stays comparable with `add_side.classify_level`.
LOOKBACK = 20
#: The dip boundary #856 used, kept identical so the two runs are comparable.
DEEP_DIP_PCT = 8.0
MIN_BARS = 60


def _load_series(path: Path) -> list[dict] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if doc.get("retired"):
        return None
    bars = doc.get("bars") or {}
    rows = []
    for day in sorted(bars):
        bar = bars[day]
        if not isinstance(bar, dict) or bar.get("close") is None:
            continue
        rows.append({
            "date": day,
            "close": float(bar["close"]),
            "high": float(bar.get("high") or bar["close"]),
            "open": float(bar.get("open") or bar["close"]),
            "low": float(bar.get("low") or bar["close"]),
        })
    return rows or None


def classify_shape(closes: list[float], prior_high: float, zscore: float | None,
                   *, no_chase_z: float) -> str | None:
    """Which entry shape this close forms, or None when it forms none."""
    close = closes[-1]
    if prior_high <= 0:
        return None
    pct_from_high = (close / prior_high - 1) * 100
    if close > prior_high:
        if zscore is not None and zscore >= no_chase_z:
            return "breakout_overheated"
        return "breakout"
    if pct_from_high <= -DEEP_DIP_PCT:
        return "deep_dip"
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    if ma50 is not None and close > ma50 and ma20 > ma50:
        return "pullback_in_uptrend"
    return None


def collect(bars_by_name: dict[str, list[dict]], *, no_chase_z: float) -> dict:
    """Forward returns per shape, plus the unconditional baseline."""
    shapes: dict[str, list[dict]] = {}
    baseline: dict[int, list[float]] = {h: [] for h in HORIZONS}
    names = 0
    for name, bars in sorted(bars_by_name.items()):
        if len(bars) < MIN_BARS:
            continue
        names += 1
        closes = [bar["close"] for bar in bars]
        for i in range(MIN_BARS, len(bars) - 1):
            forward = {h: (closes[i + h] / closes[i] - 1) * 100
                       for h in HORIZONS if i + h < len(closes)}
            if not forward:
                continue
            for h, value in forward.items():
                baseline[h].append(value)
            window = closes[:i + 1]
            prior_high = max(bar["high"] for bar in bars[i - LOOKBACK:i])
            mean20 = sum(window[-20:]) / 20
            deviation = (sum((x - mean20) ** 2 for x in window[-20:]) / 20) ** 0.5
            zscore = (window[-1] - mean20) / deviation if deviation else None
            shape = classify_shape(window, prior_high, zscore, no_chase_z=no_chase_z)
            if shape:
                shapes.setdefault(shape, []).append(
                    {"name": name, "date": bars[i]["date"], **forward})
    return {"shapes": shapes, "baseline": baseline, "names": names}


def _summarise(rows: list[dict] | list[float]) -> dict:
    out = {}
    for h in HORIZONS:
        values = ([row[h] for row in rows if h in row]
                  if rows and isinstance(rows[0], dict) else list(rows))
        if not values:
            continue
        out[f"t{h}"] = {
            "n": len(values),
            "hit_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
            "mean_pct": round(statistics.mean(values), 3),
            "median_pct": round(statistics.median(values), 3),
        }
    return out


def summarise(collected: dict) -> dict:
    shapes = {name: _summarise(rows)
              for name, rows in sorted(collected["shapes"].items())}
    baseline = {}
    for h in HORIZONS:
        values = collected["baseline"][h]
        if values:
            baseline[f"t{h}"] = {
                "n": len(values),
                "hit_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
                "mean_pct": round(statistics.mean(values), 3),
                "median_pct": round(statistics.median(values), 3),
            }
    return {"shapes": shapes, "baseline": baseline, "names": collected["names"]}


def render(summary: dict) -> str:
    lines = [
        f"add-side entry shapes — {summary['names']} names from the canonical bar store",
        "",
        f"{'shape':22s}" + "".join(f"  T+{h:<2d} hit / mean".ljust(24) for h in HORIZONS),
    ]
    order = ["breakout", "breakout_overheated", "pullback_in_uptrend", "deep_dip"]
    rows = [(name, summary["shapes"][name]) for name in order
            if name in summary["shapes"]]
    rows.append(("(baseline: any session)", summary["baseline"]))
    for name, seat in rows:
        line = f"{name:22s}"
        for h in HORIZONS:
            cell = seat.get(f"t{h}")
            line += ("  n=%-4d %5.1f%% %+6.2f%%   " % (
                cell["n"], cell["hit_rate"] * 100, cell["mean_pct"])
                if cell else "  —".ljust(24))
        lines.append(line)
    lines += [
        "",
        "Event counts overlap heavily (every session of every name is a candidate),",
        "the universe is survivorship-limited to names the desk still follows, and the",
        "window is one up-market regime. Read the rows against the baseline, never alone.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Campaign simulation (kcn 2026-09-26: 更激进 / 左侧 / 同一套规则)
#
# The shape table above answers "which closes are worth walking forward"; it
# cannot answer the questions a sizing change has to: what a *campaign* (entry,
# rungs, invalidation, evaluation window) returns per unit deployed, how deep
# the book's mark-to-market drawdown gets with several campaigns open at once,
# how often each family fires, how much it trades, and what the worst single
# name costs. `simulate` answers those with the production primitives — the
# setups come from `signals.compute_signals`, the right-side breakout's levels
# from `add_alpha.confirmation_levels`, the left side's rungs from
# `left_side.ladder` — so the rule measured is the rule the packet applies.
#
# Discipline (same limits as the module docstring, plus):
# * the split date is fixed before looking; parameters are the policy file's,
#   not fitted here;
# * fills are next-session and gap-aware (a stop gapped through exits at the
#   open; a `price_below` rung fills at min(open, rung) when the low reaches it);
# * the evaluation window closes a campaign for measurement — production does
#   not sell an add after N sessions, it judges it then;
# * one campaign per name per family at a time; units are a fixed fraction of
#   one book so families compare on the same scale.

SPLIT_DATE = "2025-07-01"


def _prepare(bars: list[dict]) -> list[dict | None]:
    from clawock.decision import signals

    rows: list[dict | None] = [None] * len(bars)
    for i in range(30, len(bars)):
        rows[i] = signals.compute_signals(bars[: i + 1])
    return rows


def _right_entry(sig: dict, no_chase_z: float):
    """(setup_id, invalidation) for the production right-side setups."""
    from clawock.decision import add_alpha

    for setup in sig.get("technical_setups") or []:
        stop = setup.get("invalidation_price")
        if stop and stop < sig["close"]:
            return setup["setup_id"], stop
    close, high, z = sig["close"], sig.get("prior_20d_high"), sig.get("zscore20")
    if high and close > high and (z is None or z < no_chase_z):
        levels = add_alpha.confirmation_levels(sig)
        if levels and levels["invalidation_price"] < close:
            return "technical_breakout", levels["invalidation_price"]
    return None


def _run_campaigns(name, bars, sigs, family, *, policy, no_chase_z, unit, pnl, out):
    from clawock.decision import left_side

    kind = family["kind"]
    horizon = family["horizon"]
    camp = None
    pending = None
    for i, bar in enumerate(bars):
        before = camp["value"] if camp else 0.0
        added = 0.0
        if pending is not None:
            if pending[0] == "open" and camp is None:
                _, setup_id, stop, limit, anchor = pending
                fill = bar["open"] if limit is None else (
                    min(bar["open"], limit) if bar["low"] <= limit else None)
                if fill is not None and (stop is None or fill > stop):
                    camp = {"name": name, "setup": setup_id,
                            "signal_date": bars[i - 1]["date"], "start": i,
                            "stop": stop if stop is not None else float("-inf"),
                            "units": [(fill, unit)], "traded": unit,
                            "pnl": 0.0, "value": unit, "worst": 0.0, "anchor": anchor}
                    before, added = 0.0, unit
            elif pending[0] == "rung" and camp is not None:
                limit = pending[1]
                if bar["low"] <= limit and min(bar["open"], limit) > camp["stop"]:
                    fill = min(bar["open"], limit)
                    camp["units"].append((fill, unit))
                    camp["traded"] += unit
                    added = unit
            elif pending[0] == "pyramid" and camp is not None and bar["open"] > camp["stop"]:
                camp["units"].append((bar["open"], unit))
                camp["traded"] += unit
                added = unit
            pending = None
        sig = sigs[i]
        if camp is None:
            if sig is None or i + 1 >= len(bars):
                continue
            if kind in ("right", "right_pyramid"):
                entry = _right_entry(sig, no_chase_z)
                if entry:
                    pending = ("open", entry[0], entry[1], None, sig)
            elif kind == "baseline":
                pending = ("open", "baseline", None, None, sig)
            elif kind == "left":
                levels = left_side.ladder(sig, family.get("policy") or policy)
                if levels:
                    pending = ("open", "left_scale_in", levels["invalidation_price"],
                               levels["rungs"][0], {**sig, "trend_floor": levels["trend_floor"]})
            continue
        exit_px = None
        if bar["open"] <= camp["stop"]:
            exit_px = bar["open"]
        elif bar["low"] <= camp["stop"]:
            exit_px = camp["stop"]
        price = exit_px if exit_px is not None else bar["close"]
        value = sum(size * price / fill for fill, size in camp["units"])
        day = value - before - added
        camp["value"] = value
        camp["pnl"] += day
        camp["worst"] = min(camp["worst"], camp["pnl"])
        pnl[bar["date"]] = pnl.get(bar["date"], 0.0) + day
        held = i - camp["start"]
        # Left side: a close under MA200 withdraws the permission (exit at that
        # close); the floor is re-read each session, as the packet re-reads it.
        trend_break = (kind == "left" and exit_px is None and sig is not None
                       and camp["anchor"].get("trend_floor") is not None
                       and sig.get("ma200") and bar["close"] < sig["ma200"])
        if exit_px is not None or trend_break or held >= horizon or i == len(bars) - 1:
            camp["reason"] = ("stop" if exit_px is not None
                              else "trend_break" if trend_break
                              else "window" if held >= horizon else "open_at_end")
            camp["exit_date"] = bar["date"]
            camp["deployed"] = sum(size for _, size in camp["units"])
            camp["traded"] += camp["value"]
            camp["return"] = camp["pnl"] / camp["deployed"]
            out.append(camp)
            camp = None
            continue
        if sig is None:
            continue
        if kind == "left":
            levels = left_side.ladder(sig, family.get("policy") or policy)
            used = len(camp["units"])
            if levels and used < len(levels["rungs"]):
                pending = ("rung", levels["rungs"][used])
        elif kind == "right_pyramid" and len(camp["units"]) < family["max_units"]:
            atr = (camp["anchor"].get("atr14_pct") or 0) / 100 * camp["anchor"]["close"]
            if atr and bar["close"] >= camp["units"][-1][0] + 0.5 * atr:
                camp["stop"] = max(camp["stop"], bar["close"] - 2 * atr)
                pending = ("pyramid",)


def _campaign_metrics(campaigns: list[dict], pnl: dict, sessions: int) -> dict:
    if not campaigns:
        return {"campaigns": 0}
    cumulative = peak = drawdown = 0.0
    for day in sorted(pnl):
        cumulative += pnl[day]
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    by_name, worst_name = {}, {}
    for camp in sorted(campaigns, key=lambda row: row["signal_date"]):
        by_name[camp["name"]] = by_name.get(camp["name"], 0.0) + camp["pnl"]
        worst_name[camp["name"]] = min(worst_name.get(camp["name"], 0.0),
                                       by_name[camp["name"]])
    returns = [camp["return"] for camp in campaigns]
    deployed = sum(camp["deployed"] for camp in campaigns)
    years = max(len(pnl), 1) / 252
    return {
        "campaigns": len(campaigns),
        "per_100_name_sessions": round(100 * len(campaigns) / max(sessions, 1), 2),
        "hit_rate": round(sum(camp["pnl"] > 0 for camp in campaigns) / len(campaigns), 3),
        "mean_return_per_campaign_pct": round(100 * statistics.mean(returns), 2),
        "return_per_unit_deployed_pct": round(100 * cumulative / deployed, 2) if deployed else None,
        "total_pnl_pct_of_book": round(100 * cumulative, 2),
        "max_drawdown_pct_of_book": round(100 * drawdown, 2),
        "turnover_per_year_x_book": round(sum(c["traded"] for c in campaigns) / years, 2),
        "worst_name_pct_of_book": round(100 * min(worst_name.values()), 2),
        "worst_campaign_pct_of_book": round(100 * min(c["worst"] for c in campaigns), 2),
        "avg_units": round(sum(len(c["units"]) for c in campaigns) / len(campaigns), 2),
        "stopped_share": round(sum(c["reason"] == "stop" for c in campaigns) / len(campaigns), 3),
    }


def _month_block_ci(campaigns: list[dict], *, draws: int = 2000, seed: int = 7):
    """90% interval of the mean campaign return, resampling signal months."""
    import random

    by_month: dict[str, list[float]] = {}
    for camp in campaigns:
        by_month.setdefault(camp["signal_date"][:7], []).append(camp["return"])
    months = sorted(by_month)
    if len(months) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        values = [v for month in (rng.choice(months) for _ in months) for v in by_month[month]]
        means.append(sum(values) / len(values))
    means.sort()
    return [round(100 * means[int(0.05 * draws)], 2), round(100 * means[int(0.95 * draws)], 2)]


def simulate(prepared: dict, *, policy: dict, no_chase_z: float,
             split: str = SPLIT_DATE, unit: float = 0.01) -> dict:
    """Pre-registered family comparison, in-sample vs out-of-sample."""
    from clawock.instruments import is_leveraged_holding

    left_policy = dict(policy)
    left_policy["left_side"] = {**(policy.get("left_side") or {}), "enabled": True}
    nofilter_policy = dict(left_policy)
    nofilter_policy["left_side"] = {**left_policy["left_side"], "permission": "none"}
    horizon_left = int(left_policy["left_side"].get("evaluation_sessions") or 20)
    families = {
        "baseline": {"kind": "baseline", "horizon": 20},
        "right": {"kind": "right", "horizon": 20},
        "right_pyramid": {"kind": "right_pyramid", "horizon": 20, "max_units": 3},
        "left": {"kind": "left", "horizon": horizon_left, "policy": left_policy},
        "left_no_ma200": {"kind": "left", "horizon": horizon_left, "policy": nofilter_policy},
    }
    leveraged = {name for name in prepared if is_leveraged_holding({"ticker": name})}
    periods = {"in_sample": ("0000", split), "out_of_sample": (split, "9999")}
    result: dict = {"split": split, "unit_pct_of_book": unit * 100, "families": {}}
    runs = {}
    for fam_name, family in families.items():
        for name, entry in prepared.items():
            camps, pnl = [], {}
            _run_campaigns(name, entry["bars"], entry["sigs"], family, policy=policy,
                           no_chase_z=no_chase_z, unit=unit, pnl=pnl, out=camps)
            runs[(fam_name, name)] = (camps, pnl)
    combos = {fam: {"all": None, "non_leveraged": lambda n: n not in leveraged,
                    "leveraged": lambda n: n in leveraged} for fam in families}
    combos["right+left_non_leveraged"] = {"all": None}
    # The policy's proposed sizes: right-side setups at `technical`, left rungs
    # at `left_scale_in` (both as a share of the book). P&L is linear in the
    # unit, so a run at `unit` rescales exactly; the drawdown of the sum is
    # recomputed, not added.
    table = ((policy.get("sizing") or {}).get("tranche_book_pct") or {})
    scale = {"right": float(table.get("technical", unit)) / unit,
             "left": float(table.get("left_scale_in", unit)) / unit}
    combos["proposed_sizing"] = {"all": None}
    for fam_name, slices in combos.items():
        seat = result["families"].setdefault(fam_name, {})
        for slice_name, keep in slices.items():
            for period_name, (lo, hi) in periods.items():
                campaigns, pnl, sessions = [], {}, 0
                for name, entry in prepared.items():
                    if keep and not keep(name):
                        continue
                    members = ([fam_name] if fam_name in families
                               else ["right"] + (["left"] if name not in leveraged else []))
                    for member in members:
                        camps, daily = runs[(member, name)]
                        factor = scale[member] if fam_name == "proposed_sizing" else 1.0
                        campaigns += [
                            c if factor == 1.0 else {
                                **c, "pnl": c["pnl"] * factor, "worst": c["worst"] * factor,
                                "deployed": c["deployed"] * factor,
                                "traded": c["traded"] * factor}
                            for c in camps if lo <= c["signal_date"] < hi]
                        for day, value in daily.items():
                            if lo <= day < hi:
                                pnl[day] = pnl.get(day, 0.0) + value * factor
                    sessions += sum(1 for bar, sig in zip(entry["bars"], entry["sigs"])
                                    if sig and lo <= bar["date"] < hi)
                cell = _campaign_metrics(campaigns, pnl, sessions)
                if campaigns:
                    cell["mean_return_ci90_pct"] = _month_block_ci(campaigns)
                seat.setdefault(slice_name, {})[period_name] = cell
    return result


def render_campaigns(result: dict) -> str:
    keys = ("campaigns", "per_100_name_sessions", "hit_rate",
            "mean_return_per_campaign_pct", "mean_return_ci90_pct",
            "return_per_unit_deployed_pct", "total_pnl_pct_of_book",
            "max_drawdown_pct_of_book", "turnover_per_year_x_book",
            "worst_name_pct_of_book", "worst_campaign_pct_of_book", "avg_units")
    lines = [f"add campaigns — split {result['split']}, unit {result['unit_pct_of_book']:g}% of book",
             "family / slice / period: " + " ".join(keys)]
    for fam, slices in result["families"].items():
        for slice_name, periods in slices.items():
            for period, cell in periods.items():
                lines.append(f"{fam:26s} {slice_name:14s} {period:14s} "
                             + " ".join(str(cell.get(k)) for k in keys))
    return "\n".join(lines)


def _tencent_series() -> dict[str, list[dict]]:
    """Longer qfq/day bars for every bar-store name, from the production fetcher."""
    from clawock.decision import signals

    out = {}
    for path in sorted(BARS_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("retired") or not doc.get("tencent"):
            continue
        bars = signals.fetch_bars(doc["tencent"], 800)
        if bars:
            out[path.stem] = bars
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='clawock evaluate-add-shapes', description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    parser.add_argument("--no-card", action="store_true", help="skip the run card")
    parser.add_argument("--campaigns", action="store_true",
                        help="run the campaign simulation (right / left / combined, IS vs OOS)")
    parser.add_argument("--source", choices=("store", "tencent"), default="store",
                        help="bars: memory/bars (default) or a longer Tencent fetch "
                             "(MA200 needs ~200 sessions before the left side can fire)")
    parser.add_argument("--split", default=SPLIT_DATE, help="first out-of-sample signal date")
    args = parser.parse_args(argv)

    started = time.time()
    try:
        policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        policy = {}
    no_chase_z = float(policy.get("early_no_chase_zscore") or 2.0)

    bars_by_name = {}
    for path in sorted(BARS_DIR.glob("*.json")):
        series = _load_series(path)
        if series:
            bars_by_name[path.stem] = series
    if not bars_by_name:
        print(f"no readable bars under {BARS_DIR}", file=sys.stderr)
        return 1

    if args.campaigns:
        return _main_campaigns(args, policy, no_chase_z, bars_by_name, started)

    summary = summarise(collect(bars_by_name, no_chase_z=no_chase_z))
    print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json
          else render(summary))

    if not args.no_card:
        card = run_card.record(
            "add_shapes",
            params={"horizons": list(HORIZONS), "lookback": LOOKBACK,
                    "deep_dip_pct": DEEP_DIP_PCT, "no_chase_z": no_chase_z,
                    "min_bars": MIN_BARS},
            inputs=[{"symbol": name, "source": "memory/bars",
                     "first": series[0]["date"], "last": series[-1]["date"],
                     "bars": len(series)}
                    for name, series in sorted(bars_by_name.items())],
            metrics=summary,
            code_files=[__file__],
            config_files=[str(POLICY_FILE)],
            notes=[
                "Descriptive pass, not walk-forward: clawock evaluate-add-alpha is "
                "the out-of-sample evaluator and this must not be quoted as one.",
                "Samples overlap (every session of every name is a candidate), the "
                "universe is survivorship-limited, and the window is one regime.",
            ],
            started_at=started,
        )
        print(f"\nrun card: {card}")
    return 0


def _main_campaigns(args, policy, no_chase_z, bars_by_name, started) -> int:
    # Candidate terms are kept outside the live add policy. Running this
    # evaluator must not enable a strategy or alter a published size.
    candidate = json.loads(CAMPAIGN_POLICY_FILE.read_text(encoding="utf-8"))
    policy = {**policy, **candidate}
    series = _tencent_series() if args.source == "tencent" else bars_by_name
    prepared = {name: {"bars": bars, "sigs": _prepare(bars)}
                for name, bars in series.items() if len(bars) >= MIN_BARS}
    result = simulate(prepared, policy=policy, no_chase_z=no_chase_z, split=args.split)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
          else render_campaigns(result))
    if not args.no_card:
        card = run_card.record(
            "add_campaigns",
            params={"split": args.split, "source": args.source, "unit_pct_of_book": 1.0,
                    "right_window": 20, "no_chase_z": no_chase_z,
                    "left_side": policy.get("left_side"),
                    "parameter_fit": "none; policy-file values, split fixed before the run"},
            inputs=[{"symbol": name, "source": args.source, "first": entry["bars"][0]["date"],
                     "last": entry["bars"][-1]["date"], "bars": len(entry["bars"]),
                     "digest": run_card.series_digest(entry["bars"])}
                    for name, entry in sorted(prepared.items())],
            metrics=result,
            code_files=[__file__],
            config_files=[str(POLICY_FILE), str(CAMPAIGN_POLICY_FILE)],
            notes=[
                "Campaign returns are measured at the evaluation window; production does "
                "not sell an add at the window, it judges it there.",
                "Current-universe names only (survivorship); samples overlap across names.",
                "Leveraged = registry leverage_multiple > 1 (is_leveraged_holding).",
            ],
            started_at=started,
        )
        print(f"\nrun card: {card}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
