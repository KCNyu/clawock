"""Portable, generation-bound context artifacts for the daily deep brief.

The complete preflight context remains the audit record. The model-facing
boundary is a compact manifest plus a fixed core and independently loadable
feature bundles. Adding a new feature therefore cannot silently grow the
always-loaded prompt: unassigned fields go to the ``extras`` bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from copy import deepcopy
from pathlib import Path


SCHEMA_VERSION = 1
ALWAYS_LOADED_BUDGET_BYTES = 128 * 1024
SINGLE_BUNDLE_BUDGET_BYTES = 96 * 1024
TARGET_REDUCTION_PCT = 60.0

# These fields are required for every decision. They are copied byte-for-byte
# (as JSON values) into core; budget enforcement may never trim them.
CORE_FIELDS = (
    "generated_at",
    "date",
    "fx",
    "portfolio_path",
    "snapshot_path",
    "portfolio",
    "book_totals",
    "concentration",
    "lookthrough_exposure",
    "risk_guardrail",
    "risk_discipline",
    "integrity",
    "thesis_registry",
    "research_surface",
    "issues",
)

BUNDLE_FIELDS = {
    "risk_detail": (
        "breakeven_math",
        "risk_metrics",
    ),
    "research": (
        "quant_signals",
        "quant_signal_review",
        "cross_sectional_factor",
        "peer_residual",
        "t0_setups",
        "t0_setup_review",
        "us_fundamentals",
        "peer_scan",
    ),
    "evidence": (
        "catalysts",
        "news_evidence_graph",
    ),
    "market": (
        "macro",
        "sentiment",
        "influencer",
        "em_news",
    ),
    "calibration": (
        "retrospective",
        "decision_metrics",
        "reflections",
    ),
}


def _compact(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _bytes(value) -> int:
    return len(_compact(value).encode("utf-8"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_immutable(path: Path, text: str) -> None:
    """Create a content-addressed run artifact; never replace different bytes."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(f"immutable brief context artifact changed: {path}")
        return
    _atomic_write(path, text)


def compute_generation_id(context: dict) -> str:
    source = {key: value for key, value in context.items() if key != "generation_id"}
    return _sha256_text(_compact(source))[:16]


def _field_summary(field: str, value):
    if not isinstance(value, dict):
        return {"type": type(value).__name__, "items": len(value)} if isinstance(
            value, list
        ) else {"type": type(value).__name__}
    summary = {
        key: value[key]
        for key in (
            "status",
            "ok",
            "as_of",
            "generated_at",
            "fetched_at",
            "error_count",
            "warn_count",
            "breach_count",
            "open_count",
            "prior_plan_date",
            "settled_episodes",
        )
        if key in value and not isinstance(value[key], (dict, list))
    }
    for key in ("events", "decisions", "rows", "findings", "errors"):
        if isinstance(value.get(key), list):
            summary[f"{key}_count"] = len(value[key])
    if field == "news_evidence_graph":
        summary["actionable_event_ids"] = [
            event.get("event_id")
            for event in value.get("events") or []
            if event.get("actionable_escalation") and event.get("event_id")
        ]
    return summary


def _artifact(path: Path, fields: tuple[str, ...], context: dict, generation_id: str):
    payload = {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "generation_id": generation_id,
            "fields": list(fields),
        },
        **{field: deepcopy(context[field]) for field in fields if field in context},
    }
    text = _compact(payload) + "\n"
    _write_immutable(path, text)
    summaries = {
        field: _field_summary(field, context[field])
        for field in fields
        if field in context
    }
    freshness = {
        field: {
            key: summary[key]
            for key in ("as_of", "generated_at", "fetched_at")
            if key in summary
        }
        for field, summary in summaries.items()
        if any(key in summary for key in ("as_of", "generated_at", "fetched_at"))
    }
    return {
        "path": str(path),
        "generation_id": generation_id,
        "fields": [field for field in fields if field in context],
        "bytes": len(text.encode("utf-8")),
        "sha256": _sha256_text(text),
        "freshness": freshness,
        "summary": summaries,
    }


def _tool_artifact(path: Path, payload: dict, generation_id: str):
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict) or meta.get("generation_id") != generation_id:
        raise ValueError(f"brief tool artifact generation mismatch: {path.name}")
    text = _compact(payload) + "\n"
    size = len(text.encode("utf-8"))
    if size > SINGLE_BUNDLE_BUDGET_BYTES:
        raise ValueError(
            "daily brief tool artifact exceeds per-query source budget "
            f"({SINGLE_BUNDLE_BUDGET_BYTES} bytes): {path.name}={size}"
        )
    _write_immutable(path, text)
    return {
        "path": str(path),
        "generation_id": generation_id,
        "schema_version": meta.get("schema_version"),
        "kind": meta.get("kind"),
        "bytes": size,
        "sha256": _sha256_text(text),
    }


def write_run_bundle(
    context: dict,
    audit_path: Path,
    *,
    tool_artifacts: dict[str, dict] | None = None,
) -> tuple[dict, dict]:
    """Write full audit JSON plus budgeted model-facing artifacts.

    Returns ``(generation-stamped context, manifest)``. Raises ValueError when
    action-critical core + manifest exceeds the model boundary budget.
    """
    stamped = deepcopy(context)
    generation_id = compute_generation_id(stamped)
    stamped["generation_id"] = generation_id

    audit_text = json.dumps(stamped, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(audit_path, audit_text)
    run_root = audit_path.with_suffix("")
    artifact_dir = run_root / generation_id
    immutable_audit_path = artifact_dir / "audit.json"
    _write_immutable(immutable_audit_path, audit_text)

    core_fields = tuple(field for field in CORE_FIELDS if field in stamped)
    core = _artifact(
        artifact_dir / "core.json", core_fields, stamped, generation_id
    )

    bundles = {}
    assigned = set(core_fields) | {"generation_id"}
    for name, configured_fields in BUNDLE_FIELDS.items():
        fields = tuple(field for field in configured_fields if field in stamped)
        assigned.update(fields)
        bundles[name] = _artifact(
            artifact_dir / f"{name}.json", fields, stamped, generation_id
        )

    extras = tuple(sorted(set(stamped) - assigned))
    if extras:
        bundles["extras"] = _artifact(
            artifact_dir / "extras.json", extras, stamped, generation_id
        )
    oversized = {
        name: entry["bytes"]
        for name, entry in bundles.items()
        if entry["bytes"] > SINGLE_BUNDLE_BUDGET_BYTES
    }
    if oversized:
        raise ValueError(
            "daily brief lazy bundle exceeds per-load budget "
            f"({SINGLE_BUNDLE_BUDGET_BYTES} bytes): {oversized}"
        )

    tools = {
        name: _tool_artifact(
            artifact_dir / f"{name}.json", payload, generation_id
        )
        for name, payload in (tool_artifacts or {}).items()
    }

    section_bytes = {
        key: _bytes(value)
        for key, value in stamped.items()
        if key != "generation_id"
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generation_id": generation_id,
        "date": stamped.get("date"),
        "audit": {
            "path": str(immutable_audit_path),
            "latest_path": str(audit_path),
            "bytes": len(audit_text.encode("utf-8")),
            "sha256": _sha256_text(audit_text),
        },
        "core": core,
        "bundles": bundles,
        "tools": tools,
        "source_section_bytes": section_bytes,
        "budget": {
            "max_always_loaded_bytes": ALWAYS_LOADED_BUDGET_BYTES,
            "max_single_bundle_bytes": SINGLE_BUNDLE_BUDGET_BYTES,
            "always_loaded_bytes": 0,
            "estimated_tokens": 0,
            "target_reduction_pct": TARGET_REDUCTION_PCT,
            "actual_reduction_pct": 0,
            "target_met": False,
        },
    }

    # The manifest describes its own boundary size. Iterate until the digit count
    # stabilizes, then write exactly the bytes that were measured.
    manifest_path = run_root / "manifest.json"
    for _ in range(6):
        manifest_text = _compact(manifest) + "\n"
        always_loaded = core["bytes"] + len(manifest_text.encode("utf-8"))
        audit_bytes = len(audit_text.encode("utf-8"))
        reduction = 100.0 * (1.0 - always_loaded / audit_bytes) if audit_bytes else 0.0
        next_budget = {
            **manifest["budget"],
            "always_loaded_bytes": always_loaded,
            # Stable same-fixture estimate for the mixed CJK/ASCII payload. The
            # hard invariant remains serialized UTF-8 bytes.
            "estimated_tokens": math.ceil(always_loaded / 3),
            "actual_reduction_pct": round(reduction, 1),
            "target_met": (
                reduction >= TARGET_REDUCTION_PCT
                or audit_bytes <= ALWAYS_LOADED_BUDGET_BYTES
            ),
        }
        if next_budget == manifest["budget"]:
            break
        manifest["budget"] = next_budget
    manifest_text = _compact(manifest) + "\n"
    measured = core["bytes"] + len(manifest_text.encode("utf-8"))
    if measured > ALWAYS_LOADED_BUDGET_BYTES:
        raise ValueError(
            "daily brief always-loaded context exceeds budget: "
            f"{measured}>{ALWAYS_LOADED_BUDGET_BYTES} bytes"
        )
    _atomic_write(manifest_path, manifest_text)
    manifest["manifest_path"] = str(manifest_path)
    return stamped, manifest


def validate_run_bundle(audit_path: Path, manifest_path: Path) -> list[str]:
    """Validate hashes and generation identity across one preflight run."""
    issues = []
    try:
        audit_text = audit_path.read_text(encoding="utf-8")
        audit = json.loads(audit_text)
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
    except Exception as exc:
        return [f"context generation bundle 解析失败: {exc}"]

    generation_id = audit.get("generation_id")
    if not generation_id or manifest.get("generation_id") != generation_id:
        issues.append("context generation_id 缺失或 manifest 跨代")
    if manifest.get("audit", {}).get("sha256") != _sha256_text(audit_text):
        issues.append("context generation audit hash 不匹配")

    core_entry = manifest.get("core") or {}
    entries = [core_entry, *(manifest.get("bundles") or {}).values()]
    covered = set()
    core_payload = None
    for entry in entries:
        path = Path(entry.get("path") or "")
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except Exception as exc:
            issues.append(f"context generation artifact 不可读: {path}: {exc}")
            continue
        if entry.get("sha256") != _sha256_text(text):
            issues.append(f"context generation artifact hash 不匹配: {path.name}")
        if payload.get("_meta", {}).get("generation_id") != generation_id:
            issues.append(f"context generation artifact 跨代: {path.name}")
        covered.update(entry.get("fields") or [])
        if entry is core_entry:
            core_payload = payload

    expected = set(audit) - {"generation_id"}
    if covered != expected:
        issues.append(
            "context generation manifest 字段覆盖不完整: "
            f"missing={sorted(expected - covered)}, extra={sorted(covered - expected)}"
        )
    if core_payload is not None:
        for field in CORE_FIELDS:
            if field in audit and core_payload.get(field) != audit[field]:
                issues.append(
                    f"context generation core 行动字段与 audit 不一致: {field}"
                )
    measured = core_entry.get("bytes", 0) + len(manifest_text.encode("utf-8"))
    budget = manifest.get("budget") or {}
    if (
        measured != budget.get("always_loaded_bytes")
        or measured > budget.get("max_always_loaded_bytes", 0)
    ):
        issues.append(
            "context generation always-loaded budget 记录不匹配或已超限"
        )
    oversized = {
        name: entry.get("bytes", 0)
        for name, entry in (manifest.get("bundles") or {}).items()
        if entry.get("bytes", 0) > budget.get("max_single_bundle_bytes", 0)
    }
    if oversized:
        issues.append(
            f"context generation lazy bundle 已超单次加载预算: {oversized}"
        )
    for name, entry in (manifest.get("tools") or {}).items():
        path = Path(entry.get("path") or "")
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except Exception as exc:
            issues.append(f"context tool artifact 不可读: {name}: {exc}")
            continue
        if entry.get("sha256") != _sha256_text(text):
            issues.append(f"context tool artifact hash 不匹配: {name}")
        if (
            entry.get("generation_id") != generation_id
            or payload.get("_meta", {}).get("generation_id") != generation_id
        ):
            issues.append(f"context tool artifact 跨代: {name}")
    return issues


def read_artifact(manifest_path: Path, kind: str) -> str:
    """Read one generation-checked core/bundle for model consumption."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = (
        manifest.get("core") or {}
        if kind == "core"
        else (manifest.get("bundles") or {}).get(kind) or {}
    )
    if not entry:
        raise ValueError(f"unknown brief context artifact: {kind}")
    path = Path(entry["path"])
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    generation_id = manifest.get("generation_id")
    if (
        entry.get("generation_id") != generation_id
        or payload.get("_meta", {}).get("generation_id") != generation_id
        or entry.get("sha256") != _sha256_text(text)
    ):
        raise ValueError(f"brief context artifact failed generation/hash check: {kind}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--core", action="store_true")
    group.add_argument("--bundle", choices=tuple(BUNDLE_FIELDS) + ("extras",))
    args = parser.parse_args()
    print(read_artifact(args.manifest, "core" if args.core else args.bundle), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
