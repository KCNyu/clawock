#!/usr/bin/env python3
"""rick_broadcast.py — turn the self-grading scorecard into a Rick-voiced post.

Reads the honest v2 decision ledger plus the quant/T+0 review sidecars
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
import json
import os
import sys
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
ROOT = str(_CHECKOUT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "data"))
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, os.path.join(ROOT, "src"))
from clawock import decision_v2  # noqa: E402
QUANT = os.path.join(ROOT, "assets", "data", "quant_signal_review.json")
T0 = os.path.join(ROOT, "assets", "data", "t0_setup_review.json")
REPO = "github.com/KCNyu/clawock"
DASH = "kcnyu.github.io/clawock"   # live dashboard — the clickable landing (has the card + links back to the repo)

# The model's *active* directional calls vs. just sitting on a position. Read the
# split from decision_v2 so the broadcast and the dashboard can never disagree on
# what "active" means — `watch` is a standing stance and belongs with the passives.
ACTIVE = decision_v2.ACTIVE_ACTIONS
PASSIVE = decision_v2.PASSIVE_ACTIONS


def _rate(rows):
    """win-rate over settled (win/loss) rows; returns (pct:int|None, n:int)."""
    settled = [r for r in rows if r["outcome"] in ("win", "loss")]
    if not settled:
        return None, 0
    wins = sum(1 for r in settled if r["outcome"] == "win")
    return round(100 * wins / len(settled)), len(settled)


def scorecard():
    rows = decision_v2.episode_representatives(decision_v2.load_decisions(), "t1")
    def pct(group):
        return (round(100 * sum((r.get("evaluation") or {}).get("outcome") == "win" for r in group) / len(group)), len(group)) if group else (None, 0)
    active_rows = [r for r in rows if r.get("action") in ACTIVE]
    active_pct, active_n = pct(active_rows)
    hold_pct, hold_n = pct([r for r in rows if r.get("action") in PASSIVE])
    hi_pct, hi_n = pct([r for r in active_rows if float(r.get("confidence") or 0) >= 0.75])

    out = {
        "active_hit": active_pct, "active_n": active_n,
        "hold_hit": hold_pct, "hold_n": hold_n,
        "high_conf_hit": hi_pct, "high_conf_n": hi_n,
        "total_settled": len(rows),
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
    lines = ["📈 Rick's recommendation report card — directional hit rates, graded by Python:", ""]
    if s["active_hit"] is not None:
        lines.append(f"• active calls: {s['active_hit']}% (n={s['active_n']})")
    if s["hold_hit"] is not None:
        lines.append(f"• just holding: {s['hold_hit']}% (n={s['hold_n']})")
    if s["high_conf_hit"] is not None:
        lines.append(f"• high-conviction active calls: {s['high_conf_hit']}% (n={s['high_conf_n']})")
    # Active calls and passive holds are different claim types over different sample
    # pools (decision_v2.compute_metrics treats them as separate), so ranking one
    # against the other is not a valid read — publish both, rank neither. "Python
    # keeps the scorecard" only means the model does not grade itself.
    verdict = ("active calls and passive holds are different bets on different samples — "
               "I publish both and rank neither. Python keeps the scorecard, I don't get to grade myself.")
    lines += ["", verdict, "", f"See it live 👉 {DASH}", f"⭐ open source 👉 {REPO}"]
    return "\n".join(lines)


def render_zh(s):
    lines = ["📈 Rick 的建议成绩单 —— Python 统计判断方向命中率:", ""]
    if s["active_hit"] is not None:
        lines.append(f"• 主动操作(cut/trim/加仓):命中 {s['active_hit']}%(n={s['active_n']})")
    if s["hold_hit"] is not None:
        lines.append(f"• 只是躺着 hold:{s['hold_hit']}%(n={s['hold_n']})")
    if s["high_conf_hit"] is not None:
        lines.append(f"• 高信心主动判断:{s['high_conf_hit']}%(n={s['high_conf_n']})")
    # 主动操作与被动持有是两类不同的赌注、不同的样本池,不做高下排名(见
    # decision_v2.compute_metrics 把两者当不同 claim)。
    verdict = ("主动操作和被动持有是两类不同的赌注、不同的样本 —— 两个数都摆出来,不做高下排名。"
               "战绩表是 Python 另算的,我评不了自己。")
    lines += ["", verdict, "", f"实时看板 👉 {DASH}", f"⭐ 开源 👉 {REPO}"]
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
