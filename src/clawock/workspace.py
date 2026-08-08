#!/usr/bin/env python3
"""Where the book lives.

Every module resolves its workspace as `Path(__file__).resolve().parents[2]`,
in 42 places. That is why this repository can only ever operate on the tree it
sits in: the code is welded to one ledger, and pointing it at another portfolio
means editing source.

`workspace_root()` keeps the same default and adds one override,
`CLAWOCK_WORKSPACE`, so the computation can run against a foreign workspace
without touching the modules. Unset, behaviour is byte-identical to before —
the live checkout and every cron path are unaffected.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "CLAWOCK_WORKSPACE"

# Files a workspace must have before the loop can do anything at all. Kept
# small on purpose: this is "can it run", not "is it healthy" — system_check.py
# owns the second question and is far stricter.
REQUIRED = ("portfolio.json", "config/instruments.json")


def engine_config(name: str) -> Path:
    """A config file that ships with the ENGINE rather than with a book (#356).

    `config/` holds two different kinds of thing, and conflating them is what
    made a foreign workspace unable to start:

    * **schemas** — `instruments.schema.json` and friends describe the FORMAT.
      Every book uses the identical file, so requiring each one to carry a copy
      is asking users to vendor our validation rules.
    * **book data** — `instruments.json`, `factor-universe.json`,
      `entry-gate-vetoes.json`. These are the user's content and stay in the
      workspace, where absence means "not configured yet", not "engine broken".

    Schemas resolve here, from the checkout this module ships in. Deliberately
    NOT workspace-first-with-fallback: a fallback would silently apply this
    repository's data to someone else's book, which is worse than a clear error.
    """
    return Path(__file__).resolve().parents[1] / "config" / name


def workspace_root(default: Path | str | None = None) -> Path:
    """The workspace to operate on.

    Args:
        default: what to use when the env var is unset. Callers pass their own
            `parents[2]` so the fallback stays exactly what it was.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    if default is not None:
        return Path(default).resolve()
    return Path(__file__).resolve().parents[2]


def missing_pieces(root: Path | str) -> list[str]:
    """Which required files a candidate workspace lacks."""
    root = Path(root)
    return [name for name in REQUIRED if not (root / name).exists()]


def describe(root: Path | str) -> dict:
    """A runnability report for one workspace. No network, no mutation."""
    import json

    root = Path(root)
    report: dict = {
        "workspace": str(root),
        "exists": root.is_dir(),
        "missing": missing_pieces(root) if root.is_dir() else list(REQUIRED),
        "holdings": None,
        "problems": [],
    }
    if not report["exists"]:
        report["problems"].append(f"{root} is not a directory")
        return report

    for name in report["missing"]:
        report["problems"].append(f"missing {name}")

    portfolio = root / "portfolio.json"
    if portfolio.exists():
        try:
            data = json.loads(portfolio.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            report["problems"].append(f"portfolio.json is unreadable: {exc}")
            return report
        legs = (data or {}).get("portfolios")
        if not isinstance(legs, dict):
            report["problems"].append("portfolio.json has no `portfolios` object")
            return report
        total = 0
        for leg, bucket in legs.items():
            holdings = (bucket or {}).get("holdings")
            if not isinstance(holdings, list):
                report["problems"].append(f"{leg}.holdings is not a list")
                continue
            for holding in holdings:
                for field in ("ticker", "shares", "cost_basis"):
                    if field not in (holding or {}):
                        report["problems"].append(
                            f"{leg} holding {(holding or {}).get('ticker', '?')} "
                            f"is missing `{field}`")
                total += 1
        report["holdings"] = total
        if total == 0:
            report["problems"].append("portfolio.json declares no holdings")
    return report
