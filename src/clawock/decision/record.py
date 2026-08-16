#!/usr/bin/env python3
"""Append a conversation investment verdict to the decision ledger.

The decision-mind ledger (docs/decision-mind-ledger.md) freezes the mind
(bull/bear/thesis/invalidation) and emotion pressure at decision time, then
lets the existing daily settlement machinery account for it. Records written
here also carry the legacy ``condition``/``execution`` fields so the desk's
normal ``settle_decisions`` round-trip treats them like any other decision.

Usage:
  clawock record --subject 00100 --market HK --currency HKD \
    --action reject --confidence 0.65 --driven-by fundamental \
    --bull "营收 +159% YoY" --bear "资不抵债" --thesis "先活下来" \
    --invalidation "站回 340" --invalidation "缩量企稳" \
    --emotion averaging_down --note "摊本冲动被压过,忍住没加"

  # Another harness (OpenClaw / Claude Code / Codex / CLI) records its own
  # conversation verdicts into the same ledger:
  clawock record --source openclaw --subject 00100 --market HK ...
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from clawock.decision import ledger as decision_v2

ACTIONS = {"buy", "add", "trim", "sell", "hold", "watch", "reject", "abstain"}
DRIVEN_BY = {"technical", "fundamental", "sentiment", "mixed"}
EMOTIONS = {"calm", "fomo", "revenge", "averaging_down", "fear", "euphoria", "mixed"}
# Which harness produced the verdict. `conversation` is the DSH default and
# the historical value; other harnesses pass their own so the ledger can say
# where a mind record came from. `brief` is the desk's daily plan writer and
# is not a valid record() value — it is produced by the brief postflight.
SOURCES = {"conversation", "openclaw", "claude", "codex", "cli"}
MIND_SCHEMA_VERSION = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def validate_mind_record(record: dict) -> list[str]:
    """Return human-readable issues; empty means the record is appendable."""
    issues: list[str] = []
    subject = record.get("subject") or {}
    for field in ("ticker", "market", "currency"):
        if not isinstance(subject.get(field), str) or not subject.get(field, "").strip():
            issues.append(f"subject.{field} is required")
    if record.get("action") not in ACTIONS:
        issues.append(f"action must be one of {sorted(ACTIONS)}")
    if record.get("source") not in SOURCES:
        issues.append(f"source must be one of {sorted(SOURCES)}")
    confidence = record.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        issues.append("confidence must be between 0 and 1")
    if record.get("driven_by") not in DRIVEN_BY:
        issues.append(f"driven_by must be one of {sorted(DRIVEN_BY)}")
    mind = record.get("mind") or {}
    for side in ("bull", "bear"):
        case = mind.get(side) or {}
        if not isinstance(case.get("summary"), str) or not case.get("summary", "").strip():
            issues.append(f"mind.{side}.summary is required (opposing case is mandatory)")
    if not isinstance(mind.get("invalidation"), list) or not mind.get("invalidation"):
        issues.append("mind.invalidation must be a non-empty list of observable conditions")
    emotion = record.get("emotion") or {}
    if emotion.get("pressure") not in EMOTIONS:
        issues.append(f"emotion.pressure must be one of {sorted(EMOTIONS)}")
    return issues


def build_record(args) -> dict:
    subject = {"ticker": args.subject, "market": args.market, "currency": args.currency}
    decided_at = _now_iso()
    source = getattr(args, "source", "conversation")
    decision_id = "dec-" + decision_v2._stable_id(source, args.subject, decided_at, size=12)
    mind = {
        "bull": {"summary": args.bull, "evidence": args.bull_evidence},
        "bear": {"summary": args.bear, "evidence": args.bear_evidence},
        "thesis": args.thesis,
        "invalidation": args.invalidation,
    }
    record = {
        "schema_version": MIND_SCHEMA_VERSION,
        "decision_id": decision_id,
        "subject": subject,
        "decided_at": decided_at,
        "source": source,
        "action": args.action,
        "confidence": args.confidence,
        "driven_by": args.driven_by,
        "mind": mind,
        "emotion": {"pressure": args.emotion, "note": args.note},
        # Legacy-compatible fields so daily settlement round-trips process this
        # record like any other decision (docs/decision-mind-ledger.md).
        "condition": {"description": args.invalidation[0] if args.invalidation else "",
                      "price": None, "type": "manual"},
        # A no-op verdict (reject/hold/watch/abstain) is "executed" when it is
        # respected — no order was placed, which is the decision itself. Order
        # actions start unknown until marked via `clawock mark-followed`.
        "execution": {
            "status": "followed" if args.action in {"reject", "hold", "watch", "abstain"} else "unknown",
            "source": source, "detected_at": None,
        },
        "accounting": {
            "trigger": {"status": "pending", "condition": args.invalidation[0] if args.invalidation else ""},
            "execution": {"executed": None},
            "outcome": {"grade": "pending"},
        },
    }
    return record


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clawock record")
    ap.add_argument("--ledger", type=Path, default=None,
                    help="decisions.jsonl path (default: the workspace ledger)")
    ap.add_argument("--source", default="conversation", choices=sorted(SOURCES),
                    help="which harness produced this verdict (conversation=DSH)")
    ap.add_argument("--subject", required=True, help="ticker, e.g. 00100")
    ap.add_argument("--market", default="HK", help="market, e.g. HK or US")
    ap.add_argument("--currency", default="HKD", help="quote currency")
    ap.add_argument("--action", required=True, choices=sorted(ACTIONS))
    ap.add_argument("--confidence", type=float, required=True)
    ap.add_argument("--driven-by", default="mixed", choices=sorted(DRIVEN_BY))
    ap.add_argument("--bull", required=True, help="supporting case summary")
    ap.add_argument("--bear", required=True, help="opposing case summary (mandatory)")
    ap.add_argument("--bull-evidence", action="append", default=[])
    ap.add_argument("--bear-evidence", action="append", default=[])
    ap.add_argument("--thesis", default="")
    ap.add_argument("--invalidation", action="append", required=True,
                    help="observable falsification condition; repeatable")
    ap.add_argument("--emotion", default="calm", choices=sorted(EMOTIONS))
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)

    record = build_record(args)
    issues = validate_mind_record(record)
    if issues:
        for issue in issues:
            print(f"record rejected: {issue}", file=sys.stderr)
        return 1

    rows = decision_v2.load_decisions(args.ledger)
    rows.append(record)
    decision_v2.write_decisions(rows, args.ledger)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"appended {record['decision_id']} ({len(rows)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
