"""Certified context assembly for portable and OpenClaw-backed runs.

OpenClaw uses different root-file allowlists for interactive chat, isolated
cron, heartbeat, bootstrap-pending and subagent sessions. Its skills catalog is
an index, not the selected skill body, and memory search remains a runtime tool
even where MEMORY.md is not injected. ``assemble`` reproduces an explicitly
named OpenClaw profile; ``assemble_explicit`` gives another runtime a neutral
file contract.

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
from typing import Any, Mapping


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
    resource = files("clawock.context").joinpath("manifest.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def profile_names() -> tuple[str, ...]:
    return tuple(load_manifest()["profiles"])


def _profile(manifest: dict, profile: str | None) -> tuple[str, dict]:
    selected = profile or manifest["default_profile"]
    try:
        return selected, manifest["profiles"][selected]
    except KeyError as exc:
        available = ", ".join(manifest["profiles"])
        raise ValueError(
            f"unknown OpenClaw context profile {selected!r}; available: {available}"
        ) from exc


def _read_required(path: Path, label: str) -> ContextDocument:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"required context {label} is missing: {path}") from exc
    if not text.strip():
        raise ValueError(f"required context {label} is empty: {path}")
    return ContextDocument(label, path, text)


def assemble(workspace, *, skills=(), profile: str | None = None) -> ContextBundle:
    """Assemble one exact bootstrap profile plus explicitly selected skills."""
    root = Path(workspace).expanduser().resolve()
    manifest = load_manifest()
    _, contract = _profile(manifest, profile)
    documents = tuple(
        _read_required(root / name, name) for name in contract["bootstrap"]
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


def audit(workspace, *, profile: str | None = None) -> dict:
    """Audit one OpenClaw context profile and its lazy capability roots."""
    root = Path(workspace).expanduser().resolve()
    manifest = load_manifest()
    profile_name, contract = _profile(manifest, profile)
    missing, empty, missing_capabilities = [], [], []
    for name in contract["bootstrap"]:
        path = root / name
        if not path.is_file():
            missing.append(name)
        elif not path.read_text(encoding="utf-8").strip():
            empty.append(name)
    for relative in contract.get("capability_paths", []):
        if not (root / relative).exists():
            missing_capabilities.append(relative)
    return {
        "runtime_contract": manifest["runtime_contract"],
        "verified_against": manifest["verified_against"],
        "profile": profile_name,
        "description": contract["description"],
        "bootstrap": contract["bootstrap"],
        "excluded": contract["excluded"],
        "conversation_history": contract["conversation_history"],
        "memory": contract["memory"],
        "skills": manifest["skills"],
        "tools": manifest["tools"],
        "memory_search": manifest["memory_search"],
        "startup_context": manifest["startup_context"],
        "missing": missing,
        "empty": empty,
        "missing_capabilities": missing_capabilities,
        "ok": not missing and not empty and not missing_capabilities,
    }


def load_prompt_report(path, *, session_key: str | None = None) -> dict:
    """Load a redacted OpenClaw system-prompt report or one sessions entry."""
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read OpenClaw prompt report: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenClaw prompt report is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("OpenClaw prompt report must be a JSON object")
    if "injectedWorkspaceFiles" in payload:
        return payload
    if isinstance(payload.get("systemPromptReport"), dict):
        return payload["systemPromptReport"]
    if session_key:
        entry = payload.get(session_key)
        if isinstance(entry, dict) and isinstance(entry.get("systemPromptReport"), dict):
            return entry["systemPromptReport"]
        raise ValueError(f"session has no systemPromptReport: {session_key}")
    raise ValueError(
        "report file contains multiple sessions; provide the exact session key"
    )


def skills_delivery(provider: str | None) -> str:
    """How a model backend receives the skills catalog.

    OpenClaw does not put the catalog in the system prompt for every backend.
    A CLI backend that owns its own skill loader is handed the same resolved
    snapshot out of band, so its prompt report shows zero skills while the
    session still carries all of them.
    """
    backends = load_manifest()["backends"]["skills_delivery"]
    normalized = (provider or "").strip().lower()
    for mode, providers in backends.items():
        if mode == "default":
            continue
        if normalized in providers:
            return mode
    return backends["default"]


def session_family(session_key: str | None) -> str | None:
    """The dialect a session key belongs to, ignoring the job or peer id.

    ``agent:main:cron:<job-uuid>`` is ``cron`` for every job because the
    projection is job-independent; ``agent:main:openclaw-weixin:direct:<peer>``
    is ``openclaw-weixin`` because the message tool schema is channel-sensitive.
    A named one-off session is its own family: two differently named sessions on
    the same backend were observed with different tool sets.
    """
    if not isinstance(session_key, str) or not session_key.strip():
        return None
    parts = [part for part in session_key.split(":") if part]
    if len(parts) < 3 or parts[0] != "agent":
        return session_key.strip()
    return parts[2]


def _prompt_report_projection(report: Mapping[str, Any]) -> dict:
    injected = report.get("injectedWorkspaceFiles")
    skills = report.get("skills")
    tools = report.get("tools")
    if not isinstance(injected, list) or not isinstance(skills, dict) or (
        not isinstance(tools, dict)
    ):
        raise ValueError("systemPromptReport is missing files, skills or tools")
    files = []
    for item in injected:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("systemPromptReport has an invalid workspace file entry")
        files.append({
            field: item.get(field)
            for field in ("name", "missing", "rawChars", "injectedChars", "truncated")
        })
    skill_entries = skills.get("entries")
    tool_entries = tools.get("entries")
    if not isinstance(skill_entries, list) or not isinstance(tool_entries, list):
        raise ValueError("systemPromptReport has invalid skill or tool entries")
    skill_names = [item.get("name") for item in skill_entries if isinstance(item, dict)]
    tool_contracts = {
        item.get("name"): {
            "summaryHash": item.get("summaryHash"),
            "schemaHash": item.get("schemaHash"),
        }
        for item in tool_entries
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    provider = report.get("provider")
    provider = provider.strip() if isinstance(provider, str) and provider.strip() else None
    return {
        "files": files,
        "skill_names": skill_names,
        "skills_hash": skills.get("hash"),
        "tool_contracts": tool_contracts,
        "provider": provider,
        "skills_delivery": skills_delivery(provider),
        "family": session_family(report.get("sessionKey")),
    }


def compare_prompt_reports(
    before: Mapping[str, Any], after: Mapping[str, Any], *, profile: str
) -> dict:
    """Compare the capability-bearing parts of two OpenClaw prompt reports."""
    manifest = load_manifest()
    _, contract = _profile(manifest, profile)
    baseline = _prompt_report_projection(before)
    candidate = _prompt_report_projection(after)
    expected_files = contract["bootstrap"]

    def files_ok(projected):
        return (
            [item["name"] for item in projected["files"]] == expected_files
            and not any(item.get("missing") or item.get("truncated") for item in projected["files"])
        )

    same_backend = baseline["skills_delivery"] == candidate["skills_delivery"]
    same_family = baseline["family"] == candidate["family"]
    comparable = same_backend and same_family
    checks = {
        "before_profile": files_ok(baseline),
        "after_profile": files_ok(candidate),
        "workspace_files": baseline["files"] == candidate["files"],
        "backend_dialect": same_backend,
        "session_family": same_family,
        # A capability diff is only attributable to a code change when both
        # sides speak the same backend and session dialect. Reporting these as
        # regressions across dialects would blame a deliberate runtime rule.
        "skills_catalog": None if not comparable else (
            baseline["skill_names"] == candidate["skill_names"]
            and baseline["skills_hash"] == candidate["skills_hash"]
        ),
        "tool_contracts": None if not comparable else (
            baseline["tool_contracts"] == candidate["tool_contracts"]
        ),
    }

    def side(projected):
        return {
            "files": [item["name"] for item in projected["files"]],
            "skills": len(projected["skill_names"]),
            "tools": len(projected["tool_contracts"]),
            "provider": projected["provider"],
            "skills_delivery": projected["skills_delivery"],
            "family": projected["family"],
        }

    return {
        "runtime_contract": manifest["runtime_contract"],
        "profile": profile,
        "comparable": comparable,
        "unattributable": (
            [] if comparable else ["skills_catalog", "tool_contracts"]
        ),
        "checks": checks,
        "before": side(baseline),
        "after": side(candidate),
        "ok": all(value is True for value in checks.values()),
    }


def verify_prompt_report(report: Mapping[str, Any], *, profile: str) -> dict:
    """Check one realized session against the profile it claims to be.

    ``compare_prompt_reports`` needs a pair, and ``audit`` only sees the
    workspace, so a single run that came out with no skills or a narrowed tool
    set had nowhere to fail. Backend dialect decides what is checkable: a
    runtime-plugin backend legitimately reports an empty catalog, so that check
    is reported as unverified rather than passed.
    """
    manifest = load_manifest()
    _, contract = _profile(manifest, profile)
    projected = _prompt_report_projection(report)
    expected_files = contract["bootstrap"]
    delivery = projected["skills_delivery"]
    checks: dict[str, bool | None] = {
        "bootstrap_files": (
            [item["name"] for item in projected["files"]] == expected_files
        ),
        "no_missing_document": not any(
            item.get("missing") for item in projected["files"]
        ),
        "no_truncation": not any(
            item.get("truncated") for item in projected["files"]
        ),
        "tools_present": bool(projected["tool_contracts"]),
        "skills_present": (
            None if delivery != "system-prompt" else bool(projected["skill_names"])
        ),
    }
    return {
        "runtime_contract": manifest["runtime_contract"],
        "profile": profile,
        "provider": projected["provider"],
        "skills_delivery": delivery,
        "family": projected["family"],
        "unverified": [
            name for name, value in checks.items() if value is None
        ],
        "checks": checks,
        "observed": {
            "files": [item["name"] for item in projected["files"]],
            "skills": len(projected["skill_names"]),
            "tools": len(projected["tool_contracts"]),
        },
        "ok": all(value for value in checks.values() if value is not None),
    }
