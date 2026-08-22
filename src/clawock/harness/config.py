"""Standalone workspace configuration and initialization.

`CONFIG_NAME` and `load_request` moved to `clawock.runtime_model` (#814) — a
request knowing how to read its own file lets `workflows.improvements` reach it
without importing the harness. Re-exported here because that is the name every
existing caller uses.
"""
from __future__ import annotations

from clawock.runtime_model import CONFIG_NAME  # noqa: F401
from clawock.workflows.request import load_request  # noqa: F401

import json
from pathlib import Path

from clawock.harness.model import AgentRunRequest
from clawock.publish.store import write_generation


DEFAULT_CONTEXT = "CONTEXT.md"


def initialize(workspace: Path | str, *, workflow: str | None = None) -> Path:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / CONFIG_NAME).exists():
        raise ValueError(f"refusing to overwrite existing {CONFIG_NAME}: {root}")
    config = {
        "schema_version": 1,
        "task": "Produce a concise answer grounded in the supplied context.",
        "context": [DEFAULT_CONTEXT],
        "output_directory": ".clawock/runs",
    }
    if workflow:
        from clawock.workflows import load_workflow

        pack = load_workflow(workflow)
        config["workflow"] = workflow
        config["task"] = pack.descriptor["task"]
    writes = {
        str(root / CONFIG_NAME): json.dumps(config, ensure_ascii=False, indent=2) + "\n",
    }
    # A plugin normally joins an existing agent workspace. Preserve its files
    # and reuse an existing CONTEXT.md instead of requiring an empty directory
    # or replacing context that the external runtime already owns.
    if not (root / DEFAULT_CONTEXT).exists():
        writes[str(root / DEFAULT_CONTEXT)] = (
            "# Context\n\n"
            "Replace this file with the facts and instructions the runtime should use.\n"
        )
    local_ignore = root / ".clawock" / ".gitignore"
    if not local_ignore.exists():
        writes[str(local_ignore)] = "*\n!.gitignore\n"
    write_generation(writes)
    return root


