"""The conversation-verdict (schema_version 0) record shape and its validator.

Split out of `decision.record` to break a real import cycle (#814):
`record` appends through `decision.ledger`, and `ledger` had to reach back into
`record` to validate one row type — a dependency it papered over with a
function-level import. The schema depends on neither module, so both can sit
above it.

The vocabularies below are the frozen contract described in
docs/decision-mind-ledger.md; changing one changes what the ledger will accept.
"""
from __future__ import annotations

ACTIONS = {"buy", "add", "trim", "sell", "hold", "watch", "reject", "abstain"}


DRIVEN_BY = {"technical", "fundamental", "sentiment", "mixed"}


EMOTIONS = {"calm", "fomo", "revenge", "averaging_down", "fear", "euphoria", "mixed"}


# Which harness produced the verdict. `conversation` is the DSH default and
# the historical value; other harnesses pass their own so the ledger can say
# where a mind record came from. `brief` is the desk's daily plan writer and
# is not a valid record() value — it is produced by the brief postflight.
SOURCES = {"conversation", "openclaw", "claude", "codex", "cli"}


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

