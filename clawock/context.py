"""Portable assembly of the context OpenClaw gives a clawock agent.

OpenClaw cron currently injects five root Markdown files by hard-coded name.  It
does *not* inject MEMORY/HEARTBEAT/BOOTSTRAP, and its skills catalog is an index,
not the selected skill body.  Those runtime facts remain unchanged; this module
makes the same contract available to another runner and turns missing root files
from a silent quality regression into a named error.

Skill bodies stay lazy.  Loading every SKILL.md would both waste context and
change normal chat/tool behaviour, so callers must resolve the selected skills
explicitly after assembling the bootstrap.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class ContextDocument:
    name: str
    path: Path
    text: str


@dataclass(frozen=True)
class ContextBundle:
    documents: tuple[ContextDocument, ...]
    skills: tuple[ContextDocument, ...] = ()

    @property
    def text(self) -> str:
        parts = [f"# {doc.name}\n\n{doc.text.rstrip()}" for doc in self.documents]
        parts += [f"# Skill: {doc.name}\n\n{doc.text.rstrip()}" for doc in self.skills]
        return "\n\n".join(parts) + "\n"

    def manifest(self) -> dict:
        return {
            "bootstrap": [doc.name for doc in self.documents],
            "skills": [doc.name for doc in self.skills],
            "chars": len(self.text),
        }


def load_manifest() -> dict:
    resource = files("clawock").joinpath("context_manifest.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _read_required(path: Path, label: str) -> ContextDocument:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"required context {label} is missing: {path}") from exc
    if not text.strip():
        raise ValueError(f"required context {label} is empty: {path}")
    return ContextDocument(label, path, text)


def assemble(workspace, *, skills=()) -> ContextBundle:
    """Assemble the exact bootstrap allowlist plus explicitly selected skills."""
    root = Path(workspace).expanduser().resolve()
    manifest = load_manifest()
    documents = tuple(
        _read_required(root / name, name) for name in manifest["bootstrap"]
    )
    selected = []
    pattern = manifest["skills"]["body_pattern"]
    for name in dict.fromkeys(skills):
        relative = pattern.format(name=name)
        selected.append(_read_required(root / relative, str(name)))
    return ContextBundle(documents, tuple(selected))


def audit(workspace) -> dict:
    """Describe the OpenClaw-compatible contract without reading excluded files."""
    root = Path(workspace).expanduser().resolve()
    manifest = load_manifest()
    missing, empty = [], []
    for name in manifest["bootstrap"]:
        path = root / name
        if not path.is_file():
            missing.append(name)
        elif not path.read_text(encoding="utf-8").strip():
            empty.append(name)
    return {
        "runtime_contract": manifest["runtime_contract"],
        "bootstrap": manifest["bootstrap"],
        "excluded": manifest["excluded"],
        "skills": manifest["skills"],
        "missing": missing,
        "empty": empty,
        "ok": not missing and not empty,
    }
