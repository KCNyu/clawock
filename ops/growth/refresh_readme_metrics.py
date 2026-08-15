#!/usr/bin/env python3
"""Refresh the metrics placeholders in the READMEs from the live ledger.

Reads memory/decisions.jsonl, assets/data/shadow_portfolio.json and
assets/data/dashboard.json, recomputes every published figure, rewrites the
<!-- CW_M:key -->...<!-- /CW_M:key --> placeholders in README.zh.md (and
README.md once it carries them), and writes assets/data/readme_metrics.json
for audit. Idempotent: leaves the files untouched when nothing changed.

Invoked by .github/workflows/screenshot-refresh.yml (README Refresh) on a
weekly schedule (Sundays 22:00 UTC); the numbers in the READMEs are therefore
never older than the last refresh. Exit codes: 0 = changed, 1 = nothing
changed (the workflow tolerates 1; its commit step decides), 2 = error.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))
from clawock.decision import ledger  # noqa: E402

PLACEHOLDER = re.compile(r"<!-- CW_M:(\w+) -->.*?<!-- /CW_M:\1 -->", re.S)


def _ci(pct: float, n: int) -> str:
    """Normal-approximation 95% CI, rounded to whole percents."""
    p = pct / 100.0
    se = math.sqrt(p * (1 - p) / n)
    lo = max(0.0, (p - 1.96 * se) * 100)
    hi = min(100.0, (p + 1.96 * se) * 100)
    return f"{round(lo)}%–{round(hi)}%"


def _pct(group) -> tuple:
    if not group:
        return None, 0
    wins = sum(1 for r in group if (r.get("evaluation") or {}).get("outcome") == "win")
    return round(100 * wins / len(group)), len(group)


def _refresh() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-plane",
        default=str(_ROOT / "assets" / "data"),
        help="directory holding data-plane artifacts (dashboard.json, shadow_portfolio.json); "
        "defaults to the checkout's assets/data",
    )
    args = parser.parse_args()
    dp = Path(args.data_plane)

    rows = ledger.load_decisions()
    episodes = ledger.episode_representatives(rows, "t1")
    settled = [e for e in episodes if (e.get("evaluation") or {}).get("outcome") in ("win", "loss")]

    active = [r for r in episodes if r.get("action") in ledger.ACTIVE_ACTIONS]
    passive = [r for r in episodes if r.get("action") in ledger.PASSIVE_ACTIONS]
    hi = [r for r in active if float(r.get("confidence") or 0) >= 0.75]

    active_pct, active_n = _pct(active)
    hold_pct, hold_n = _pct(passive)
    hi_pct, hi_n = _pct(hi)

    first_day = min(r["created_at"] for r in rows)
    days = (datetime.now(datetime.fromisoformat(first_day).tzinfo)
            - datetime.fromisoformat(first_day)).days

    from collections import Counter
    exec_status = Counter((r.get("execution") or {}).get("status") for r in rows)
    followed = exec_status.get("followed", 0)
    not_followed = exec_status.get("not_followed", 0)
    unknown = exec_status.get("unknown", 0)

    dashboard = json.loads((dp / "dashboard.json").read_text())
    return_pct = dashboard["net_principal_return"]["combined_usd"]["return_pct"]

    metrics = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": datetime.now().strftime("%Y-%m"),
        "days": days,
        "rows": len(rows),
        "settled": len(settled),
        "active_pct": active_pct,
        "active_n": active_n,
        "hold_pct": hold_pct,
        "hold_n": hold_n,
        "hi_pct": hi_pct,
        "hi_n": hi_n,
        "active_ci": _ci(active_pct, active_n) if active_pct is not None else None,
        "hi_ci": _ci(hi_pct, hi_n) if hi_pct is not None else None,
        "return_pct": f"{return_pct:.2f}",
        "followed": followed,
        "not_followed": not_followed,
        "unknown": unknown,
    }

    values = {
        "as_of": str(metrics["as_of"]),
        "days": str(metrics["days"]),
        "settled": str(metrics["settled"]),
        "rows": str(metrics["rows"]),
        "active_pct": f"{metrics['active_pct']}%",
        "active_n": str(metrics["active_n"]),
        "hold_pct": f"{metrics['hold_pct']}%",
        "hold_n": str(metrics["hold_n"]),
        "hi_pct": f"{metrics['hi_pct']}%",
        "hi_n": str(metrics["hi_n"]),
        "active_ci": str(metrics["active_ci"]),
        "hi_ci": str(metrics["hi_ci"]),
        "return_pct": f"{metrics['return_pct']}%".replace("-", "\u2212"),
        "followed": str(metrics["followed"]),
        "not_followed": str(metrics["not_followed"]),
        "unknown": str(metrics["unknown"]),
    }

    changed = False
    for readme in ("README.zh.md", "README.md"):
        path = _ROOT / readme
        if not path.exists():
            continue
        text = path.read_text()
        if "CW_M:" not in text:
            continue
        def _sub(m: re.Match) -> str:
            key = m.group(1)
            return f"<!-- CW_M:{key} -->{values[key]}<!-- /CW_M:{key} -->"
        updated = PLACEHOLDER.sub(_sub, text)
        if updated != text:
            path.write_text(updated)
            changed = True
            print(f"{readme}: metrics refreshed")
        else:
            print(f"{readme}: unchanged")

    audit = _ROOT / "assets/data/readme_metrics.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(audit.read_text()) if audit.exists() else None
    # `generated_at` is always fresh, so it must not drive the change decision:
    # an unchanged week must produce no rewrite, no commit, and exit 1
    # ("nothing changed") — otherwise the no-change path is unreachable and the
    # workflow commits a pointless audit churn every week.
    _stable = lambda m: {k: v for k, v in m.items() if k != "generated_at"}  # noqa: E731
    if (prev is None) or _stable(prev) != _stable(metrics):
        audit.write_text(json.dumps(metrics, ensure_ascii=False, indent=1) + "\n")
        changed = True

    print(json.dumps(metrics, ensure_ascii=False))
    return 0 if changed else 1


def main() -> int:
    """Entry point: keep the exit-code contract explicit.

    0 = changed, 1 = nothing changed (READMEs already current; the workflow's
    commit step makes the final call), 2 = unexpected error. A traceback must
    never be indistinguishable from "no change".
    """
    try:
        return _refresh()
    except Exception as exc:  # noqa: BLE001 — any failure must fail the step loudly
        print(f"refresh_readme_metrics: error: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
