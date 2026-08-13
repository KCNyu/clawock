"""Declarative user/runtime profiles for the complete clawock product.

A profile selects values, resources, policies and presentation.  It never
loads Python from an instance namespace: lifecycle and strategy code belongs to
the root ``clawock`` distribution.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ENV_VAR = "CLAWOCK_PROFILE"
PROFILE_DIR = Path("config/profiles")
PROFILE_NAME = "profile.json"
_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_TOP_LEVEL = frozenset({
    "schema_version", "id", "locale", "timezone", "markets", "workflows",
    "resources", "policies", "templates", "delivery",
})
_MARKET_FIELDS = frozenset({"timezone", "label", "analysis_command", "skill"})
_WORKFLOW_FIELDS = frozenset({"enabled", "markets", "policy", "template"})
_DELIVERY_FIELDS = frozenset({"provider", "targets"})
_TARGET_FIELDS = frozenset({"source", "key"})


@dataclass(frozen=True)
class MarketProfile:
    key: str
    timezone: str
    label: str
    analysis_command: str
    skill: str | None = None


@dataclass(frozen=True)
class WorkflowProfile:
    key: str
    enabled: bool
    markets: tuple[str, ...]
    policy: str | None = None
    template: str | None = None


@dataclass(frozen=True)
class DeliveryTarget:
    source: str
    key: str | None = None


@dataclass(frozen=True)
class Profile:
    profile_id: str
    locale: str
    timezone: str
    markets: Mapping[str, MarketProfile]
    workflows: Mapping[str, WorkflowProfile]
    resources: Mapping[str, str]
    policies: Mapping[str, Any]
    templates: Mapping[str, str]
    delivery_provider: str
    delivery_targets: Mapping[str, DeliveryTarget]
    path: Path
    workspace: Path

    def resource_path(self, name: str) -> Path:
        """Resolve a declared workspace resource without permitting escape."""
        try:
            raw = self.resources[name]
        except KeyError as exc:
            raise ValueError(
                f"profile {self.profile_id!r} has no resource {name!r}"
            ) from exc
        resolved = (self.workspace / raw).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise ValueError(
                f"profile {self.profile_id!r} resource {name!r} escapes workspace"
            )
        return resolved


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"profile {label} must be an object")
    return value


def _known_fields(value: dict, allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"profile {label} has unknown fields: {unknown}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"profile {label} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _timezone(value: Any, label: str) -> str:
    name = _text(value, label)
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"profile {label} is not an IANA timezone: {name}") from exc
    return name


def _relative_path(value: Any, label: str) -> str:
    text = _text(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"profile {label} must stay inside the workspace")
    return path.as_posix()


def profile_path(workspace: Path | str, profile: Path | str | None = None) -> Path:
    root = Path(workspace).expanduser().resolve()
    selected = profile if profile is not None else os.environ.get(ENV_VAR)
    if selected is None or not str(selected).strip():
        raise ValueError(
            f"no clawock profile selected; pass --profile or set {ENV_VAR}"
        )
    candidate = Path(str(selected)).expanduser()
    if not candidate.is_absolute():
        if len(candidate.parts) == 1 and candidate.suffix != ".json":
            candidate = root / PROFILE_DIR / candidate / PROFILE_NAME
        else:
            candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("profile path must stay inside the workspace")
    return resolved


def load_profile(workspace: Path | str, profile: Path | str | None = None) -> Profile:
    root = Path(workspace).expanduser().resolve()
    path = profile_path(root, profile)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read clawock profile {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"clawock profile is not valid JSON: {exc}") from exc
    data = _object(payload, "root")
    _known_fields(data, _TOP_LEVEL, "root")
    if data.get("schema_version") != 1:
        raise ValueError("profile schema_version must be 1")
    profile_id = _text(data.get("id"), "id")
    if not _ID.fullmatch(profile_id):
        raise ValueError("profile id must match ^[a-z][a-z0-9_-]*$")
    locale = _text(data.get("locale"), "locale")
    timezone = _timezone(data.get("timezone"), "timezone")

    raw_markets = _object(data.get("markets"), "markets")
    if not raw_markets:
        raise ValueError("profile markets must not be empty")
    markets = {}
    for key, raw in raw_markets.items():
        market = _object(raw, f"markets.{key}")
        _known_fields(market, _MARKET_FIELDS, f"markets.{key}")
        markets[key] = MarketProfile(
            key=key,
            timezone=_timezone(market.get("timezone"), f"markets.{key}.timezone"),
            label=_text(market.get("label"), f"markets.{key}.label"),
            analysis_command=_text(
                market.get("analysis_command"), f"markets.{key}.analysis_command"
            ),
            skill=_optional_text(market.get("skill"), f"markets.{key}.skill"),
        )

    raw_workflows = _object(data.get("workflows"), "workflows")
    if not raw_workflows:
        raise ValueError("profile workflows must not be empty")
    workflows = {}
    for key, raw in raw_workflows.items():
        workflow = _object(raw, f"workflows.{key}")
        _known_fields(workflow, _WORKFLOW_FIELDS, f"workflows.{key}")
        enabled = workflow.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(f"profile workflows.{key}.enabled must be boolean")
        selected_markets = workflow.get("markets")
        if (not isinstance(selected_markets, list)
                or any(not isinstance(item, str) for item in selected_markets)
                or len(selected_markets) != len(set(selected_markets))):
            raise ValueError(
                f"profile workflows.{key}.markets must be unique market names"
            )
        unknown_markets = sorted(set(selected_markets) - set(markets))
        if unknown_markets:
            raise ValueError(
                f"profile workflows.{key} uses unknown markets: {unknown_markets}"
            )
        workflows[key] = WorkflowProfile(
            key=key, enabled=enabled, markets=tuple(selected_markets),
            policy=_optional_text(workflow.get("policy"), f"workflows.{key}.policy"),
            template=_optional_text(
                workflow.get("template"), f"workflows.{key}.template"
            ),
        )

    raw_resources = _object(data.get("resources"), "resources")
    resources = {
        key: _relative_path(value, f"resources.{key}")
        for key, value in raw_resources.items()
    }
    policies = _object(data.get("policies"), "policies")
    raw_templates = _object(data.get("templates"), "templates")
    templates = {
        key: _relative_path(value, f"templates.{key}")
        for key, value in raw_templates.items()
    }

    delivery = _object(data.get("delivery"), "delivery")
    _known_fields(delivery, _DELIVERY_FIELDS, "delivery")
    provider = _text(delivery.get("provider"), "delivery.provider")
    raw_targets = _object(delivery.get("targets"), "delivery.targets")
    targets = {}
    for key, raw in raw_targets.items():
        target = _object(raw, f"delivery.targets.{key}")
        _known_fields(target, _TARGET_FIELDS, f"delivery.targets.{key}")
        source = _text(target.get("source"), f"delivery.targets.{key}.source")
        if source not in {"runtime_job", "environment", "disabled"}:
            raise ValueError(
                f"profile delivery.targets.{key}.source is unsupported: {source}"
            )
        target_key = _optional_text(target.get("key"), f"delivery.targets.{key}.key")
        if source == "environment" and target_key is None:
            raise ValueError(
                f"profile delivery.targets.{key}.key is required for environment"
            )
        if source == "disabled" and target_key is not None:
            raise ValueError(
                f"profile delivery.targets.{key}.key is invalid when disabled"
            )
        targets[key] = DeliveryTarget(source=source, key=target_key)

    return Profile(
        profile_id=profile_id, locale=locale, timezone=timezone,
        markets=MappingProxyType(markets), workflows=MappingProxyType(workflows),
        resources=MappingProxyType(resources),
        policies=MappingProxyType(dict(policies)),
        templates=MappingProxyType(templates), delivery_provider=provider,
        delivery_targets=MappingProxyType(targets), path=path, workspace=root,
    )


def describe_profile(profile: Profile) -> dict:
    return {
        "schema_version": 1,
        "id": profile.profile_id,
        "path": str(profile.path),
        "locale": profile.locale,
        "timezone": profile.timezone,
        "markets": {
            key: {
                "timezone": value.timezone,
                "label": value.label,
                "analysis_command": value.analysis_command,
                "skill": value.skill,
            }
            for key, value in profile.markets.items()
        },
        "workflows": {
            key: {
                "enabled": value.enabled,
                "markets": list(value.markets),
                "policy": value.policy,
                "template": value.template,
            }
            for key, value in profile.workflows.items()
        },
        "resources": dict(profile.resources),
        "policies": dict(profile.policies),
        "templates": dict(profile.templates),
        "delivery": {
            "provider": profile.delivery_provider,
            "targets": {
                key: {"source": value.source, "key": value.key}
                for key, value in profile.delivery_targets.items()
            },
        },
    }
