"""Pure signal mechanics for point-in-time primary disclosures.

The caller supplies both evidence and policy.  This module performs no fetch,
workspace read, portfolio discovery, sizing, persistence, delivery or alerting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class InformationPolicy:
    positive_markers: tuple[str, ...]
    negative_markers: tuple[str, ...]
    eligible_markers: tuple[str, ...]
    ignored_markers: tuple[str, ...]
    categories: tuple[tuple[str, tuple[str, ...]], ...]
    hot_reaction_pct: float
    contradicted_reaction_pct: float


def _first_marker(text: str, markers: Iterable[str]) -> str | None:
    folded = text.casefold()
    return next((marker for marker in markers if marker.casefold() in folded), None)


def evaluate(event: Mapping, reaction_pct, policy: InformationPolicy) -> dict | None:
    """Map one normalized event and a reaction into a bounded signal.

    ``None`` means the caller's policy says the event is not strategy-relevant;
    it does not mean the provider found no disclosure.
    """
    detail = str(event.get("title") or "")
    ignored = _first_marker(detail, policy.ignored_markers)
    positive = _first_marker(detail, policy.positive_markers)
    negative = _first_marker(detail, policy.negative_markers)
    eligible = positive or negative or _first_marker(detail, policy.eligible_markers)
    if ignored or not eligible:
        return None

    if negative:
        direction, explicit_marker = "negative", negative
    elif positive:
        direction, explicit_marker = "positive", positive
    else:
        direction, explicit_marker = "unknown", eligible

    category = "material_disclosure"
    for name, markers in policy.categories:
        if _first_marker(detail, markers):
            category = name
            break

    blockers = ["candidate_is_not_order_authority"]
    if direction == "negative":
        disposition = "reject"
        blockers.append("adverse_primary_disclosure")
    elif direction != "positive":
        disposition = "wait"
        blockers.append("needs_detail_extraction")
    elif not isinstance(reaction_pct, (int, float)):
        disposition = "candidate"
        blockers.append("price_reaction_unavailable")
    elif reaction_pct >= policy.hot_reaction_pct:
        disposition = "wait"
        blockers.append("price_already_reacted")
    elif reaction_pct <= policy.contradicted_reaction_pct:
        disposition = "wait"
        blockers.append("tape_contradicts_positive_event")
    else:
        disposition = "candidate"

    detail_status = "explicit" if direction != "unknown" else "needs_detail_extraction"
    return {
        "direction": direction,
        "category": category,
        "detail": detail,
        "explicit_marker": explicit_marker,
        "detail_status": detail_status,
        "disposition": disposition,
        "blockers": blockers,
        "falsifier": (
            "price rejects the disclosure or a later primary filing reverses the detail"
            if direction == "positive" else
            "a later primary filing resolves or reverses the adverse/unknown detail"
        ),
        "next_evidence": (
            "independent support plus non-overheated price confirmation"
            if detail_status == "explicit" else
            "extract the attributable filing detail before any directional action"
        ),
        "judge_contract": {
            "allowed": ["candidate", "wait", "reject"],
            "may_upgrade": False,
            "precomputed": disposition,
        },
    }
