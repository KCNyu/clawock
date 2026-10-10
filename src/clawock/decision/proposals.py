"""An append-only record of what was proposed, under which method (#2844).

`decisions.jsonl` is the book of calls that were filed: a revised plan replaces
its rows, a refused plan never reaches it, and nothing in a row says how the
call was arrived at. That is enough to calibrate a hit rate on
action / driver / condition / regime. It is not enough to ask whether a method
the model changed to is better than the one it changed from, because both land
in the same group and the proposals the validator refused have no denominator.

This log keeps one immutable line per proposal as it was written:

* its method and hypothesis, each with an id derived from the text, so method
  A and method B never share an identity by accident;
* who wrote it — prompt digest, code commit, model when the runner says —
  recorded at the time, not reconstructed;
* the review it received: filed or refused, the objections the registered
  policy raised, the authorisation version;
* the computations it cited, embedded, because the receipt store is temporary.

Nothing here is rewritten. A re-run that changes nothing appends nothing
(`record_id` is the content's hash); a revision appends a new line beside the
old one, so a method cannot be edited after its outcome is known.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from clawock.decision import receipts
from clawock.safe_io import safe_write_json, temp_dir_lock

SCHEMA_VERSION = 1
UNKNOWN = "unknown"
_FOLD = re.compile(r"\s+")


def log_path(workspace) -> Path:
    return Path(workspace) / "memory" / "proposals.jsonl"


def _text_id(prefix: str, *parts) -> str:
    folded = "|".join(_FOLD.sub("", str(part or "").strip().rstrip("。.")).casefold() for part in parts)
    return f"{prefix}-{hashlib.sha256(folded.encode('utf-8')).hexdigest()[:12]}"


def method_version(method) -> str:
    """The identity of a method: a hash of its text with whitespace and a trailing sentence stop folded away, or `unknown` when the plan did not state one.

    Text, not a menu: a new method needs no registration, and two wordings
    that differ in substance are two methods.
    """
    if not isinstance(method, str) or not _FOLD.sub("", method).strip("。."):
        return UNKNOWN
    return _text_id("mv", method)


def hypothesis_id(ticker, hypothesis) -> str | None:
    if not isinstance(hypothesis, str) or not _FOLD.sub("", hypothesis).strip("。."):
        return None
    return _text_id("hyp", ticker, hypothesis)


def authorship(workspace, *, model: str | None = None,
               prompt_path: str = "skills/daily-deep-brief/SKILL.md") -> dict:
    """Who wrote this generation's proposals, as far as the harness can see.

    The model is recorded when the runner states it (`CLAWOCK_AUTHOR_MODEL`, or
    the caller's own knowledge) and is `unknown` otherwise: a model's
    description of itself inside its own output is not evidence of which
    model ran.
    """
    from clawock import code_identity  # noqa: PLC0415

    root = Path(workspace)
    return {
        "model": model or os.environ.get("CLAWOCK_AUTHOR_MODEL") or UNKNOWN,
        "prompt": code_identity.file_digest(root / prompt_path) or UNKNOWN,
        "code": code_identity.git_commit(root) or UNKNOWN,
    }


def _record(decision: dict, *, plan: dict, findings: list[dict], plan_status: str,
            author: dict, load_receipt, observation_snapshot=None) -> dict:
    blocking = receipts.blocking(findings)
    cited = []
    for receipt_id in decision.get("tool_receipts") or []:
        receipt = load_receipt(receipt_id) if load_receipt else None
        cited.append(receipt if isinstance(receipt, dict)
                     else {"receipt_id": receipt_id, "missing": True})
    body = {
        "schema_version": SCHEMA_VERSION,
        "plan_date": plan.get("date"),
        "context_generation_id": plan.get("context_generation_id"),
        "observation_snapshot": observation_snapshot,
        "decision_id": decision.get("decision_id"),
        "ticker": decision.get("ticker"),
        "leg": decision.get("leg"),
        "strategy_id": decision.get("strategy_id"),
        "action": decision.get("action"),
        "driven_by": decision.get("driven_by"),
        "regime": decision.get("regime"),
        "condition": decision.get("condition"),
        "size": decision.get("size"),
        "invalidation_price": decision.get("invalidation_price"),
        "confidence": decision.get("confidence"),
        "hypothesis": decision.get("hypothesis"),
        "hypothesis_id": hypothesis_id(decision.get("ticker"), decision.get("hypothesis")),
        "method": decision.get("method"),
        "method_version": method_version(decision.get("method")),
        "forecast": decision.get("forecast"),
        "falsifier": decision.get("thesis_invalidation"),
        "alternatives": decision.get("alternatives"),
        "tool_receipts": cited,
        # `refused`: a fact or feasibility finding stopped this decision.
        # `filed`: it passed both, whatever the policy thought of it.
        "status": "refused" if blocking else "filed",
        # Whether the plan it belongs to was published; a filed decision in a
        # failed plan was never shown to anyone.
        "plan_status": plan_status,
        "refusals": [{"channel": item["channel"], "code": item["code"]} for item in blocking],
        "objections": [item["code"] for item in receipts.objections(findings)],
        "agrees_with_policy": not receipts.objections(findings),
        "authorization_version": (decision.get("policy_review") or {}).get(
            "authorization_version"),
        "authorship": author,
    }
    digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {"record_id": f"prop-{digest[:16]}", **body}


def load(workspace) -> list[dict]:
    """Every recorded proposal, oldest first. A torn last line is skipped."""
    path = log_path(workspace)
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("record_id"):
            rows.append(row)
    return rows


def record(workspace, plan: dict, findings: list[dict], *, plan_status: str,
           author: dict | None = None, load_receipt=None, now=None, observation_snapshot=None) -> list[dict]:
    """Append this plan's proposals; returns the records that were new.

    `findings` is `packet.review_plan`'s output for the same plan (an empty
    list when there was no packet to review against, which is recorded as
    agreement with nothing: `objections` is then empty and
    `authorization_version` null).
    """
    if observation_snapshot:
        digest = hashlib.sha256(json.dumps(observation_snapshot, sort_keys=True,
                                          ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        relative = f"memory/proposal-inputs/{digest}.json"
        snapshot_path = Path(workspace) / relative
        with temp_dir_lock(snapshot_path, "proposalinputs"):
            if not snapshot_path.exists():
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                safe_write_json(snapshot_path, observation_snapshot)
            elif json.loads(snapshot_path.read_text()) != observation_snapshot:
                raise ValueError("frozen observation snapshot digest mismatch")
        observation_snapshot = {"sha256": digest, "path": relative}
    by_index: dict[int, list[dict]] = {}
    for item in findings or []:
        if item.get("index") is not None:
            by_index.setdefault(item["index"], []).append(item)
    author = author or authorship(workspace)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    fresh = []
    path = log_path(workspace)
    with temp_dir_lock(path, "proposals"):
        seen = {row["record_id"] for row in load(workspace)}
        for index, decision in enumerate(plan.get("decisions") or []):
            if not isinstance(decision, dict):
                continue
            row = _record(decision, plan=plan, findings=by_index.get(index, []),
                          plan_status=plan_status, author=author, load_receipt=load_receipt,
                          observation_snapshot=observation_snapshot)
            if row["record_id"] in seen:
                continue
            seen.add(row["record_id"])
            fresh.append({**row, "recorded_at": stamp})
        if fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Never append onto a torn final line: preserve it for recovery
            # and fail instead of silently losing the next record too.
            if path.exists() and path.stat().st_size:
                with path.open("rb") as prior:
                    prior.seek(-1, 2)
                    if prior.read(1) != b"\n":
                        raise ValueError("proposal log has an unterminated final line")
            with path.open("a", encoding="utf-8") as handle:
                for row in fresh:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    return fresh
