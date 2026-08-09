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

import json
from typing import Any


class ToolError(RuntimeError):
    """A tool refused. The message is shown to the caller verbatim."""


class BaseTool:
    """One callable capability, described well enough for an LLM to use it."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}
    # Read-only tools are safe to run speculatively or in parallel. Anything that
    # writes must say so, because the caller's batching depends on it.
    is_readonly: bool = True

    @classmethod
    def check_available(cls, workspace) -> bool:
        """Whether this tool can run against `workspace`.

        Returning False excludes it from the registry, which is far better than
        surfacing a missing-file traceback in the middle of a model turn.
        """
        return True

    def execute(self, workspace, **kwargs: Any) -> str:
        raise NotImplementedError

    # ── schema export ───────────────────────────────────────────────────────

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description.strip(),
                "parameters": self.parameters or {
                    "type": "object", "properties": {}, "required": []},
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description.strip(),
            "input_schema": self.parameters or {
                "type": "object", "properties": {}, "required": []},
        }


class ToolRegistry:
    """The tools available for one workspace."""

    def __init__(self, workspace):
        self.workspace = workspace
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> bool:
        if not tool.name:
            raise ValueError("a tool must have a name")
        if not type(tool).check_available(self.workspace):
            return False
        self._tools[tool.name] = tool
        return True

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ToolError(f"unknown tool: {name}")
        return self._tools[name]

    def call(self, name: str, **kwargs: Any) -> str:
        return self.get(name).execute(self.workspace, **kwargs)

    def schemas(self, dialect: str = "openai") -> list[dict[str, Any]]:
        render = {"openai": lambda t: t.to_openai_schema(),
                  "anthropic": lambda t: t.to_anthropic_schema()}[dialect]
        return [render(self._tools[name]) for name in self.names()]


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
