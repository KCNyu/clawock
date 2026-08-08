"""Discovery and installation for package-owned workflow/skill packs."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from clawock.publish.store import write_generation


PACKS_PACKAGE = "clawock.workflows.packs"
WORKFLOW_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


@dataclass(frozen=True)
class WorkflowPack:
    """One immutable workflow contract shipped inside the installed wheel."""

    descriptor: Mapping[str, Any]
    resource: Any

    @property
    def workflow_id(self) -> str:
        return str(self.descriptor["id"])

    @property
    def version(self) -> str:
        return str(self.descriptor["version"])

    @property
    def certificate(self) -> str:
        return hashlib.sha256(_canonical(self.descriptor).encode()).hexdigest()

    def contract(self, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
        parameters = {
            name: spec["default"]
            for name, spec in self.descriptor.get("parameters", {}).items()
        }
        for name, value in (overrides or {}).items():
            spec = self.descriptor.get("parameters", {}).get(name)
            if not isinstance(spec, dict):
                raise ValueError(f"unknown workflow parameter: {name}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"workflow parameter {name} must be numeric")
            if spec.get("type") == "integer" and not isinstance(value, int):
                raise ValueError(f"workflow parameter {name} must be an integer")
            if value < spec["minimum"] or value > spec["maximum"]:
                raise ValueError(
                    f"workflow parameter {name} must be between "
                    f"{spec['minimum']} and {spec['maximum']}"
                )
            parameters[name] = value
        return {
            "id": self.workflow_id,
            "version": self.version,
            "certificate": self.certificate,
            "parameters": parameters,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**dict(self.descriptor), "certificate": self.certificate}


def _validate_descriptor(payload: Any, expected_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"workflow descriptor is not an object: {expected_id}")
    required = {
        "schema_version", "id", "version", "title", "description", "task", "skill",
        "artifacts", "schemas", "stages", "parameters",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"workflow {expected_id} missing fields: {missing}")
    if payload.get("schema_version") != 1:
        raise ValueError(f"workflow {expected_id} requires schema_version 1")
    if payload.get("id") != expected_id or not WORKFLOW_NAME.fullmatch(expected_id):
        raise ValueError(f"workflow id must match its package directory: {expected_id}")
    if payload.get("skill") != "SKILL.md":
        raise ValueError(f"workflow {expected_id} must expose SKILL.md")
    if not isinstance(payload.get("task"), str) or not payload["task"].strip():
        raise ValueError(f"workflow {expected_id} has no agent task")
    required_artifacts = (payload.get("artifacts") or {}).get("required")
    if not isinstance(required_artifacts, list) or not required_artifacts:
        raise ValueError(f"workflow {expected_id} has no required artifacts")
    schemas = payload.get("schemas")
    if not isinstance(schemas, dict) or set(required_artifacts) - set(schemas):
        raise ValueError(f"workflow {expected_id} has no schema for every required artifact")
    for name, spec in payload.get("parameters", {}).items():
        if not isinstance(spec, dict) or not {
            "type", "default", "minimum", "maximum", "description"
        } <= set(spec):
            raise ValueError(f"workflow {expected_id} parameter is invalid: {name}")
    return payload


def list_workflows() -> tuple[WorkflowPack, ...]:
    root = files(PACKS_PACKAGE)
    packs = []
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        descriptor = resource.joinpath("workflow.json")
        if not resource.is_dir() or not descriptor.is_file():
            continue
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
        packs.append(WorkflowPack(_validate_descriptor(payload, resource.name), resource))
    return tuple(packs)


def load_workflow(workflow_id: str) -> WorkflowPack:
    for pack in list_workflows():
        if pack.workflow_id == workflow_id:
            return pack
    available = ", ".join(pack.workflow_id for pack in list_workflows()) or "none"
    raise ValueError(f"unknown workflow {workflow_id!r}; available: {available}")


def workflow_contract(
    workflow_id: str, overrides: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return load_workflow(workflow_id).contract(overrides)


def _resource_files(resource: Any, prefix: str = "") -> dict[str, str]:
    output: dict[str, str] = {}
    for child in resource.iterdir():
        # Package/import debris is not part of the Agent Skill. In an extracted
        # wheel Python may create __pycache__ beside these resources before the
        # user installs them; trying to decode that binary as UTF-8 both leaks an
        # implementation detail and makes installation fail.
        if child.name == "__pycache__" or child.name == "__init__.py":
            continue
        relative = f"{prefix}{child.name}"
        if child.is_dir():
            output.update(_resource_files(child, relative + "/"))
        elif child.is_file():
            output[relative] = child.read_text(encoding="utf-8")
    return output


def install_workflow(
    workflow_id: str, skill_root: Path | str, *, force: bool = False
) -> Path:
    """Install one pack as a standard Agent Skill without runtime mutation.

    The caller chooses the skill root. ``<workspace>/.agents/skills`` works as a
    cross-runtime project location and is also discovered by current OpenClaw.
    Existing skills are never overwritten unless the caller explicitly asks.
    """
    pack = load_workflow(workflow_id)
    destination = Path(skill_root).expanduser().resolve() / workflow_id
    if destination.exists() and not force:
        raise ValueError(f"refusing to overwrite existing workflow skill: {destination}")
    writes = {
        str(destination / name): content
        for name, content in _resource_files(pack.resource).items()
    }
    write_generation(writes)
    return destination
