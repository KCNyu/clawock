"""config/models.toml: models, their parameters, and which scenario uses which.

Everything model-related elsewhere is *rendered* from this registry rather
than copied by hand: OpenClaw's provider tables and per-model defaults, the cron
contract's rotations, clawock's own MiniMax client and the dsh MiniMax catalog.
`ops/host/sync_models.py` writes the host files; the cron contract and the
client read the registry when they load.
"""
from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from pathlib import Path

from clawock.workspace import workspace_root

REGISTRY = Path('config') / 'models.toml'
# Keys of a [models.*] table that are registry vocabulary, not OpenClaw fields.
_MODEL_META = {'ref', 'params', 'runtime'}
_PROVIDER_META = {'aliases'}


@dataclass(frozen=True)
class Model:
    key: str
    provider: str
    id: str
    entry: dict      # OpenClaw provider model-table entry
    params: dict
    runtime: str | None

    @property
    def ref(self) -> str:
        return f'{self.provider}/{self.id}'


class Registry:
    def __init__(self, data: dict, source: Path | None = None):
        self.data, self.source = data, source
        self.providers = data.get('providers') or {}
        self.aliases = {alias: name for name, spec in self.providers.items()
                        for alias in spec.get('aliases') or ()}
        self.models = {}
        for key, spec in (data.get('models') or {}).items():
            provider, _, model_id = spec['ref'].partition('/')
            if provider not in self.providers or not model_id:
                raise ValueError(f'models.{key}: ref {spec["ref"]!r} needs a declared provider/id')
            entry = {'id': model_id, **{k: v for k, v in spec.items() if k not in _MODEL_META}}
            self.models[key] = Model(key, provider, model_id, entry, dict(spec.get('params') or {}),
                                     spec.get('runtime'))
        self.chains = data.get('chains') or {}
        for name in self.chains:
            self.chain(name)  # validate every reference up front

    # ── references ───────────────────────────────────────────────────────────

    def ref(self, item: str) -> str:
        """`flash` → `minimax/MiniMax-M3.1-Flash`; `flash@minimax-2` → `minimax-2/...`."""
        key, _, alias = item.partition('@')
        if key not in self.models:
            raise ValueError(f'unknown model {key!r}')
        model = self.models[key]
        if not alias:
            return model.ref
        if self.aliases.get(alias) != model.provider:
            raise ValueError(f'{item!r}: {alias!r} is not an alias of {model.provider!r}')
        return f'{alias}/{model.id}'

    def model(self, item: str) -> Model:
        return self.models[item.partition('@')[0]]

    def chain(self, name: str) -> dict:
        """Resolved scenario: model, fallbacks, candidates, thinking."""
        spec = self.chains.get(name)
        if not spec or not spec.get('models'):
            raise ValueError(f'unknown or empty chain {name!r}')
        rotation = [self.ref(item) for item in spec['models']]
        allowed = [self.ref(item) for item in spec.get('also_allowed') or ()]
        if len(set(rotation + allowed)) != len(rotation + allowed):
            raise ValueError(f'chain {name!r} lists a model twice')
        out = {'model': rotation[0], 'fallbacks': rotation[1:]}
        if len(rotation) > 1 or allowed:
            out['model_candidates'] = rotation + allowed
        if spec.get('thinking'):
            out['thinking'] = spec['thinking']
        return out

    # ── renderings ───────────────────────────────────────────────────────────

    def openclaw_providers(self) -> dict:
        """`models.providers` without credentials: {name: owned fields + models}."""
        out = {}
        for name, spec in self.providers.items():
            fields = {k: copy.deepcopy(v) for k, v in spec.items() if k not in _PROVIDER_META}
            fields['models'] = [copy.deepcopy(m.entry) for m in self.models.values()
                                if m.provider == name]
            out[name] = fields
            for alias in spec.get('aliases') or ():
                out[alias] = copy.deepcopy(fields)
        return out

    def openclaw_model_defaults(self) -> dict:
        """`agents.defaults.models`: per-model params and runtime."""
        out = {}
        for model in self.models.values():
            value = {}
            if model.runtime:
                value['agentRuntime'] = {'id': model.runtime}
            if model.params:
                value['params'] = copy.deepcopy(model.params)
            if value:
                out[model.ref] = value
        return out


def registry_path(workspace: str | Path | None = None) -> Path:
    return workspace_root(workspace) / REGISTRY


def load(path: str | Path | None = None, *, workspace: str | Path | None = None) -> Registry:
    source = Path(path) if path else registry_path(workspace)
    with open(source, 'rb') as handle:
        return Registry(tomllib.load(handle), source)
