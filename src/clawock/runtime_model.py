"""Contracts shared by external callers, validators and publishers."""
from __future__ import annotations

# Moved out of `harness` (#814). Nothing in here imports from clawock — it is
# the run request / receipt vocabulary, and `workflows.validators` needs the
# same `ValidationIssue` the harness produces. While it lived under `harness`,
# `workflows` had to import the harness to name a two-field dataclass, and that
# single import was half of a package cycle. `harness.model` re-exports it, so
# the name every caller already uses still resolves.

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


WORKFLOWS = ("brief", "report", "intraday")
# `render` is the brief's third phase: it turns the model's judgment into the
# published report. Every workflow has preflight/postflight; only the brief has
# something to render, and `harness.runner.PHASE_MODULES` is what says which
# (workflow, phase) pairs actually exist.
PHASES = ("preflight", "postflight", "render")


@dataclass(frozen=True)
class RunRequest:
    workflow: str
    phase: str
    workspace: Path
    argv: tuple[str, ...] = ()
    profile: str | None = None

    def __post_init__(self):
        if self.workflow not in WORKFLOWS:
            raise ValueError(f"unknown workflow: {self.workflow}")
        if self.phase not in PHASES:
            raise ValueError(f"unknown phase: {self.phase}")


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    media_type: str
    generation_id: str


@dataclass(frozen=True)
class ArtifactSet:
    """Correlated outputs from one agent run, pinned to one generation."""
    generation_id: str
    artifacts: tuple[Artifact, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.generation_id:
            raise ValueError("artifact set has no generation_id")
        mismatched = [a.name for a in self.artifacts
                      if a.generation_id != self.generation_id]
        if mismatched:
            raise ValueError(
                "mixed artifact generations: " + ", ".join(mismatched))


@dataclass(frozen=True)
class AgentRunRequest:
    """The deterministic inputs an external agent asks clawock to certify."""

    task: str
    workspace: Path
    context_files: tuple[str, ...]
    output_directory: Path
    metadata: Mapping[str, Any] = field(default_factory=dict)
    workflow: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ValueError("agent run task is empty")
        if not self.context_files:
            raise ValueError("agent run has no context files")
        if self.workflow:
            required = {"id", "version", "certificate", "parameters"}
            if set(self.workflow) != required:
                raise ValueError(
                    "workflow contract must contain exactly " + ", ".join(sorted(required))
                )
            if not all(
                isinstance(self.workflow.get(field), str) and self.workflow[field]
                for field in ("id", "version", "certificate")
            ):
                raise ValueError("workflow id, version and certificate are required")
            if not isinstance(self.workflow.get("parameters"), Mapping):
                raise ValueError("workflow parameters must be an object")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class RunReceipt:
    run_id: str
    generation_id: str
    status: str
    artifacts: ArtifactSet
    workflow: Mapping[str, Any] = field(default_factory=dict)
    validation_issues: tuple[ValidationIssue, ...] = ()
    publish_receipt: str | None = None
    publish_changed: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "generation_id": self.generation_id,
            "status": self.status,
            "created_at": self.created_at,
            "artifacts": [
                {
                    "name": artifact.name,
                    "path": str(artifact.path),
                    "media_type": artifact.media_type,
                    "generation_id": artifact.generation_id,
                }
                for artifact in self.artifacts.artifacts
            ],
            "workflow": dict(self.workflow),
            "validation_issues": [
                {"code": issue.code, "message": issue.message}
                for issue in self.validation_issues
            ],
            "publish": {
                "receipt": self.publish_receipt,
                "changed": self.publish_changed,
            },
        }


# The request's own file format. It lived in `harness.config`, which meant
# `workflows.improvements` had to import the harness to read a config file it
# also owns — the other half of the harness<->workflows cycle (#814). A request
# knowing how to load itself keeps both callers above the same definition.
import json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

CONFIG_NAME = "clawock.json"
