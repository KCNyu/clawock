"""Standalone workspace configuration and initialization."""
from __future__ import annotations

import json
from pathlib import Path

from clawock.harness.model import AgentRunRequest
from clawock.publish.store import write_generation


CONFIG_NAME = "clawock.json"
DEFAULT_CONTEXT = "CONTEXT.md"


def initialize(workspace: Path | str) -> Path:
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


def load_request(workspace: Path | str) -> AgentRunRequest:
    root = Path(workspace).expanduser().resolve()
    path = root / CONFIG_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"standalone workspace has no {CONFIG_NAME}: {root}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CONFIG_NAME} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"{CONFIG_NAME} requires schema_version 1")
    context = payload.get("context")
    if not isinstance(context, list) or not all(isinstance(item, str) for item in context):
        raise ValueError(f"{CONFIG_NAME} context must be a list of paths")
    output = payload.get("output_directory", ".clawock/runs")
    if not isinstance(output, str) or not output.strip():
        raise ValueError(f"{CONFIG_NAME} output_directory must be a relative path")
    output_path = Path(output)
    if output_path.is_absolute() or ".." in output_path.parts:
        raise ValueError(f"{CONFIG_NAME} output_directory must stay inside the workspace")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError(f"{CONFIG_NAME} metadata must be an object")
    output_resolved = (root / output_path).resolve()
    try:
        output_resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"{CONFIG_NAME} output_directory resolves outside the workspace") from exc
    return AgentRunRequest(
        task=str(payload.get("task", "")),
        workspace=root,
        context_files=tuple(context),
        output_directory=output_resolved,
        metadata=metadata,
    )
