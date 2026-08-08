"""Certified context assembly for portable and OpenClaw-backed runs.

OpenClaw *isolated cron* currently injects five root Markdown files by hard-coded
name. It does not inject MEMORY/HEARTBEAT/BOOTSTRAP in that profile, and its
skills catalog is an index, not the selected skill body. Those facts are not a
claim about normal interactive chat. ``assemble`` reproduces that compatibility
profile; ``assemble_explicit`` gives another runtime a neutral file contract.

Skill bodies stay lazy.  Loading every SKILL.md would both waste context and
change normal chat/tool behaviour, so callers must resolve the selected skills
explicitly after assembling the bootstrap.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class ContextDocument:
    name: str
    path: Path
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContextBundle:
    documents: tuple[ContextDocument, ...]
    skills: tuple[ContextDocument, ...] = ()

    @property
    def text(self) -> str:
        parts = [f"# {doc.name}\n\n{doc.text.rstrip()}" for doc in self.documents]
        parts += [f"# Skill: {doc.name}\n\n{doc.text.rstrip()}" for doc in self.skills]
        return "\n\n".join(parts) + "\n"

    def certificate(self) -> dict:
        """Content-addressed identity without a runtime-specific profile name."""
        return {
            "chars": len(self.text),
            "sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            "documents": [
                {"name": doc.name, "chars": len(doc.text), "sha256": doc.sha256}
                for doc in (*self.documents, *self.skills)
            ],
        }

    def manifest(self) -> dict:
        return {
            "bootstrap": [doc.name for doc in self.documents],
            "skills": [doc.name for doc in self.skills],
            **self.certificate(),
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


def assemble_explicit(workspace, documents) -> ContextBundle:
    """Assemble a runtime-neutral bundle from named workspace documents.

    OpenClaw's five-file bootstrap is one *profile*, not the definition of agent
    context. A standalone runner needs to say which files form its context
    without pretending to be OpenClaw or requiring OpenClaw's root filenames.
    Paths are workspace-relative and may not escape the workspace.
    """
    root = Path(workspace).expanduser().resolve()
    selected = []
    for raw in dict.fromkeys(str(item) for item in documents):
        relative = Path(raw)
        if relative.is_absolute():
            raise ValueError(f"context path must be workspace-relative: {raw}")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"context path escapes workspace: {raw}") from exc
        selected.append(_read_required(path, relative.as_posix()))
    if not selected:
        raise ValueError("at least one context document is required")
    return ContextBundle(tuple(selected))


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
