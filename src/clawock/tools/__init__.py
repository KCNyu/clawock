"""A tool contract, so the context protocol stops being prose plus a shell.

`skills/daily-deep-brief/SKILL.md` drives a genuinely good lazy-load protocol —
generation-pinned manifest, typed decision packet, per-section queries, hash
validation, a hard per-query byte budget. The protocol is not the problem. The
problem was how the model reached it: markdown told it to run a Python file from
the KCNyu source checkout. The implementation and the tool schema now both ship
in the wheel.

That makes the skill the only machine-unreadable copy of the interface, forces
the cron payload to know internal file layout, and leaves any non-OpenClaw
runner to re-derive the protocol from prose — which is exactly why
The KCNyu brief-fallback command cannot do the lazy queries and degrades to one
chat() call.

The contract here is deliberately small, and modelled on what a function-calling
API actually needs:

    name / description / parameters (JSON Schema) / is_readonly / execute()

plus `check_available()`, so a tool whose dependencies are missing is excluded
from the registry rather than exploding inside a model turn.

What this is NOT: a per-turn context assembler. Our context is precompiled to
disk with a manifest so postflight can validate a report against the exact facts
the model saw. Compaction that silently drops tool results would break that
audit chain, so the tools read the precompiled protocol — they do not replace it.
"""
from __future__ import annotations

from clawock.tools.base import BaseTool, ToolError, ToolRegistry  # noqa: F401

import json
from typing import Any








def build_registry(workspace, tools=None) -> ToolRegistry:
    """Registry for a workspace, skipping tools whose dependencies are absent."""
    from clawock.tools import context_tools

    registry = ToolRegistry(workspace)
    for tool in (tools if tools is not None else context_tools.TOOLS):
        registry.register(tool() if isinstance(tool, type) else tool)
    return registry


def describe(workspace, dialect: str = "openai") -> str:
    """The tool contract as JSON — what a runner hands to a model."""
    return json.dumps(build_registry(workspace).schemas(dialect),
                      ensure_ascii=False, indent=2)
