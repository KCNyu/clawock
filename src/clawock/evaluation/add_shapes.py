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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    parser.add_argument("--no-card", action="store_true", help="skip the run card")
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


if __name__ == "__main__":
    sys.exit(main())
