#!/usr/bin/env python3
"""rick_broadcast.py — turn the self-grading scorecard into a Rick-voiced post.

Reads the honest track record (calibration.csv + the quant/T+0 review sidecars)
and emits a short, ready-to-post update in Rick's voice. Delivery is a separate
concern: this only prints text (and optional --json) to stdout, so you can pipe
it to X / Nostr / a copy-paste, manually or from a cron.

Usage:
    python3 scripts/data/rick_broadcast.py            # both languages
    python3 scripts/data/rick_broadcast.py --lang en  # english only
    python3 scripts/data/rick_broadcast.py --json     # machine-readable
"""
from __future__ import annotations
import argparse
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV = os.path.join(ROOT, "memory", "calibration.csv")
QUANT = os.path.join(ROOT, "assets", "data", "quant_signal_review.json")
T0 = os.path.join(ROOT, "assets", "data", "t0_setup_review.json")
REPO = "github.com/KCNyu/clawock"

# The model's *active* directional calls vs. just sitting on a position.
ACTIVE = {"cut", "trim_on_rebound", "add_only_on_trigger", "add_on_breakout", "t_only", "watch"}
PASSIVE = {"hold_and_watch"}


def _rate(rows):
    """win-rate over settled (win/loss) rows; returns (pct:int|None, n:int)."""
    settled = [r for r in rows if r["outcome"] in ("win", "loss")]
    if not settled:
        return None, 0
    wins = sum(1 for r in settled if r["outcome"] == "win")
    return round(100 * wins / len(settled)), len(settled)


def scorecard():
    rows = list(csv.DictReader(open(CSV)))

    def conf(r):
        try:
            return float(r["confidence"] or 0)
        except ValueError:
            return 0.0

    active_pct, active_n = _rate([r for r in rows if r["bucket"] in ACTIVE])
    hold_pct, hold_n = _rate([r for r in rows if r["bucket"] in PASSIVE])
    hi_pct, hi_n = _rate([r for r in rows if conf(r) >= 0.75])

    out = {
        "active_hit": active_pct, "active_n": active_n,
        "hold_hit": hold_pct, "hold_n": hold_n,
        "high_conf_hit": hi_pct, "high_conf_n": hi_n,
        "total_settled": sum(1 for r in rows if r["outcome"] in ("win", "loss")),
    }

    # T+0 setup grades (usable ones only) — the "card read" honesty
    try:
        t0 = json.load(open(T0))
        out["t0"] = {
            k: {"label": g["label"], "hit": round(100 * g["hit_rate"]), "n": g["n"]}
            for k, g in t0.get("grades", {}).items()
            if g.get("usable") and g.get("hit_rate") is not None
        }
        out["t0_days"] = t0.get("days_logged")
    except (OSError, ValueError):
        out["t0"] = {}

    # quant factors: how many have earned the right to speak (usable=True)
    try:
        q = json.load(open(QUANT))
        facs = q.get("factors", {})
        out["quant_usable"] = sum(1 for f in facs.values() if f.get("usable"))
        out["quant_total"] = len(facs)
    except (OSError, ValueError):
        out["quant_usable"], out["quant_total"] = 0, 0
    return out


def render_en(s):
    lines = ["📈 Rick's report card — an AI grading itself on real money:", ""]
    if s["active_hit"] is not None:
        lines.append(f"• active calls: {s['active_hit']}% (n={s['active_n']})")
    if s["hold_hit"] is not None:
        lines.append(f"• just holding: {s['hold_hit']}% (n={s['hold_n']})")
    if s["high_conf_hit"] is not None:
        lines.append(f"• my \"high-conviction\" calls: {s['high_conf_hit']}%")
    verdict = "active signals still lose to doing nothing. Scorecard's in Python — can't fudge it."
    if s["active_hit"] is not None and s["hold_hit"] is not None and s["active_hit"] >= s["hold_hit"]:
        verdict = "the active book finally earned its keep this week — noting it before it mean-reverts."
    lines += ["", verdict, "", f"Open & live 👉 {REPO}"]
    return "\n".join(lines)


def render_zh(s):
    lines = ["📈 Rick 的成绩单 —— 一个跑真金白银、给自己打分的 AI:", ""]
    if s["active_hit"] is not None:
        lines.append(f"• 主动操作(cut/trim/加仓):命中 {s['active_hit']}%(n={s['active_n']})")
    if s["hold_hit"] is not None:
        lines.append(f"• 只是躺着 hold:{s['hold_hit']}%(n={s['hold_n']})")
    if s["high_conf_hit"] is not None:
        lines.append(f"• 我自称高信心的判断:{s['high_conf_hit']}%")
    verdict = ("翻译一下:我的主动信号还是跑输什么都不做。"
               "我直说 —— 战绩表是 Python 算的,我没法作弊。")
    if s["active_hit"] is not None and s["hold_hit"] is not None and s["active_hit"] >= s["hold_hit"]:
        verdict = "这周主动操作总算没拖后腿 —— 先记一笔,大概率会回归均值。"
    lines += ["", verdict, "", f"开源·实时·真实持仓 👉 {REPO}"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["en", "zh", "both"], default="both")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    s = scorecard()
    if args.json:
        print(json.dumps({"scorecard": s,
                          "en": render_en(s), "zh": render_zh(s)},
                         ensure_ascii=False, indent=2))
        return
    if args.lang in ("en", "both"):
        print(render_en(s))
    if args.lang == "both":
        print("\n" + "─" * 40 + "\n")
    if args.lang in ("zh", "both"):
        print(render_zh(s))


if __name__ == "__main__":
    main()
