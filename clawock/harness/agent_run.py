"""The deterministic lifecycle surface called by an external agent runtime."""
from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4

from clawock.context import ContextBundle, assemble_explicit
from clawock.harness.model import (
    AgentRunRequest,
    Artifact,
    ArtifactSet,
    RunReceipt,
    ValidationIssue,
)
from clawock.publish import ArtifactStore


MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class PreparedRun:
    """A context-pinned handoff from clawock to the calling external agent."""

    request: AgentRunRequest
    context: ContextBundle
    run_id: str
    generation_id: str

    def __post_init__(self) -> None:
        for label, value in (("run_id", self.run_id), ("generation_id", self.generation_id)):
            if not (
                len(value) == 32
                and all(character in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{label} must be a 32-character lowercase hex ID")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "generation_id": self.generation_id,
            "task": self.request.task,
            "output_directory": str(self.request.output_directory),
            "context": {
                "certificate": self.context.certificate(),
                "documents": [
                    {"name": document.name, "sha256": document.sha256,
                     "text": document.text}
                    for document in self.context.documents
                ],
                "skills": [
                    {"name": skill.name, "sha256": skill.sha256,
                     "text": skill.text}
                    for skill in self.context.skills
                ],
            },
            "metadata": dict(self.request.metadata),
            "workflow": dict(self.request.workflow),
        }


class ArtifactValidator(Protocol):
    name: str

    def validate(self, artifacts: Mapping[str, str]) -> tuple[ValidationIssue, ...]:
        ...


class CoreArtifactValidator:
    """Reject output that cannot be safely stored as one useful generation."""

    name = "core"

    def validate(self, artifacts: Mapping[str, str]) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if not artifacts:
            issues.append(ValidationIssue(
                "empty_generation", "external agent supplied no artifacts"))
        for name, content in artifacts.items():
            path = Path(name)
            if (
                not name
                or path == Path(".")
                or path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != name
            ):
                issues.append(ValidationIssue(
                    "unsafe_artifact_path",
                    f"artifact path is not a canonical generation-relative path: {name}",
                ))
            if path == Path(MANIFEST_NAME):
                issues.append(ValidationIssue(
                    "reserved_artifact_name", f"{MANIFEST_NAME} is owned by clawock"))
            if not content.strip():
                issues.append(ValidationIssue(
                    "empty_artifact", f"artifact is empty: {name}"))
        return tuple(issues)


def _media_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "text/plain"


class AgentRun:
    """Certify and publish an external agent's artifacts without running it.

    OpenClaw, Hermes, Claude Code, Codex or another runtime owns the model,
    conversation, memory, skills, tools and repair loop. It calls ``prepare``
    before producing output and ``publish`` after producing or repairing files.
    """

    def __init__(self, *, validators: tuple[ArtifactValidator, ...] = ()) -> None:
        self.validators = (CoreArtifactValidator(), *validators)

    def prepare(self, request: AgentRunRequest, *, run_id: str | None = None,
                generation_id: str | None = None) -> PreparedRun:
        return PreparedRun(
            request=request,
            context=assemble_explicit(request.workspace, request.context_files),
            run_id=run_id or uuid4().hex,
            generation_id=generation_id or uuid4().hex,
        )

    def _issues(
        self, prepared: PreparedRun, artifacts: Mapping[str, str]
    ) -> tuple[ValidationIssue, ...]:
        workflow_validators: tuple[ArtifactValidator, ...] = ()
        if prepared.request.workflow:
            # Lazy to keep the generic harness model independent at import time.
            # The package API and CLI must enforce the same workflow contract;
            # requiring every caller to remember to inject these validators would
            # make the most important gates optional by accident.
            from clawock.workflows import validators_for

            workflow_validators = validators_for(prepared.request.workflow)
        return tuple(
            issue
            for validator in (*self.validators, *workflow_validators)
            for issue in validator.validate(artifacts)
        )

    def publish(self, prepared: PreparedRun, artifacts: Mapping[str, str],
                store: ArtifactStore) -> RunReceipt:
        issues = self._issues(prepared, artifacts)
        members = tuple(
            Artifact(name, Path(name), _media_type(name), prepared.generation_id)
            for name in artifacts
        )
        artifact_set = ArtifactSet(prepared.generation_id, members)
        artifact_set.validate()
        if issues:
            return RunReceipt(
                run_id=prepared.run_id,
                generation_id=prepared.generation_id,
                status="rejected",
                artifacts=artifact_set,
                validation_issues=issues,
            )

        manifest = {
            "schema_version": 1,
            "run_id": prepared.run_id,
            "generation_id": prepared.generation_id,
            "context": prepared.context.certificate(),
            "artifacts": [
                {"name": name, "generation_id": prepared.generation_id}
                for name in artifacts
            ],
            "producer_metadata": dict(prepared.request.metadata),
            "workflow": dict(prepared.request.workflow),
        }
        files: Mapping[str, str] = {
            **artifacts,
            MANIFEST_NAME: json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        }
        published = store.publish(files, label=f"clawock run {prepared.run_id}")
        final_artifacts = ArtifactSet(prepared.generation_id, (
            *members,
            Artifact(MANIFEST_NAME, Path(MANIFEST_NAME),
                     "application/json", prepared.generation_id),
        ))
        final_artifacts.validate()
        return RunReceipt(
            run_id=prepared.run_id,
            generation_id=prepared.generation_id,
            status="published",
            artifacts=final_artifacts,
            publish_receipt=published.receipt,
            publish_changed=published.changed,
        )
