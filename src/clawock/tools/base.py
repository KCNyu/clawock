"""The tool vocabulary: what a capability is, and how a registry holds them.

Split out of `tools/__init__` to break an import cycle (#814). Every tool module
imports `BaseTool` and `ToolError` from the package, and the package imported
the tool modules back to build the registry. The shape is common enough to read
as idiomatic — `build_registry` defers its import inside the function, so it
works — but it is still a cycle, and it costs one file to remove: these
definitions have no dependencies, so both sides can sit above them.

`clawock.tools` re-exports all three; that is the name every tool module and
caller already uses.
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
