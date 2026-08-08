"""Render workflow artifact schemas for external runtime dialects.

The canonical files stay full JSON Schema and remain the contract clawock uses
after an agent returns an artifact. Runtime structured-output features commonly
accept only a subset. A projection can relax generation-time constraints, but it
must never replace canonical post-generation validation.
"""
from __future__ import annotations

import json
from typing import Any

from .registry import load_workflow


DIALECTS = ("canonical", "codex")

# OpenAI Structured Outputs supports only a subset of JSON Schema. These
# assertions are still enforced by clawock after Codex returns decision.json.
_CODEX_OMIT = {
    "$schema",
    "$id",
    "uniqueItems",
    "minLength",
    "maxLength",
}


def _codex_projection(value: Any) -> Any:
    if isinstance(value, list):
        return [_codex_projection(item) for item in value]
    if not isinstance(value, dict):
        return value

    projected: dict[str, Any] = {}
    for key, item in value.items():
        if key in _CODEX_OMIT:
            continue
        if key == "const":
            projected["enum"] = [_codex_projection(item)]
            continue
        if key == "oneOf":
            projected["anyOf"] = _codex_projection(item)
            continue
        projected[key] = _codex_projection(item)
    return projected


def render_workflow_schema(
    workflow_id: str, artifact: str, *, dialect: str = "canonical"
) -> dict[str, Any]:
    """Return one packaged artifact schema without mutating its canonical form."""
    if dialect not in DIALECTS:
        raise ValueError(
            f"unknown schema dialect {dialect!r}; available: {', '.join(DIALECTS)}"
        )
    pack = load_workflow(workflow_id)
    relative = pack.descriptor["schemas"].get(artifact)
    if not isinstance(relative, str):
        available = ", ".join(sorted(pack.descriptor["schemas"]))
        raise ValueError(
            f"workflow {workflow_id!r} has no schema for {artifact!r}; "
            f"available: {available}"
        )
    schema = json.loads(pack.resource.joinpath(relative).read_text(encoding="utf-8"))
    return schema if dialect == "canonical" else _codex_projection(schema)
