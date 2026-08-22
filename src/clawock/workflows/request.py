"""Reading a standalone workspace's `clawock.json` into an AgentRunRequest.

Lives in `workflows` rather than beside the dataclass because resolving the
declared workflow needs `workflow_contract`, and a model that reached up for
that would put the foundation layer above the package it depends on — the cycle
this move was meant to remove (#814). `CONFIG_NAME` stays in
`clawock.runtime_model`: it is a filename, with no dependencies at all.

`harness.config` re-exports both, because that is where every existing caller
names them.
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.runtime_model import CONFIG_NAME, AgentRunRequest
from clawock.workflows.registry import workflow_contract


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
    workflow = payload.get("workflow")
    workflow_parameters = payload.get("workflow_parameters", {})
    if workflow is None:
        if workflow_parameters:
            raise ValueError(
                f"{CONFIG_NAME} workflow_parameters require a workflow"
            )
        contract = {}
    elif not isinstance(workflow, str) or not workflow.strip():
        raise ValueError(f"{CONFIG_NAME} workflow must be a non-empty string")
    elif not isinstance(workflow_parameters, dict):
        raise ValueError(f"{CONFIG_NAME} workflow_parameters must be an object")
    else:


        contract = workflow_contract(workflow, workflow_parameters)
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
        workflow=contract,
    )
