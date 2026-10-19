#!/usr/bin/env python3
"""Render config/models.toml into the host's model configuration.

    sync_models.py              # check: which sections differ, exit 1 if any
    sync_models.py --apply      # write them, then say what to restart
    sync_models.py --effective  # what chat, every cron job and dsh use right now

Owned and rewritten from the registry:

- `~/.openclaw/openclaw.json`: per provider `baseUrl`/`api`/`authHeader`/
  `timeoutSeconds`/`models` (credentials and any other key are kept);
  `agents.defaults.models`; `agents.defaults.model` (chain `chat`);
  heartbeat / subagents model; memory-core dreaming model and its subagent
  allowlist (chain `dreaming`).
- each dsh profile's MiniMax provider: `baseURL` and the `models` list.

The cron contract and clawock's MiniMax client read the registry themselves
(`chain` in config/cron-schedules.json, `clawock.automation.llm`); after a chain
change run `ops/host/sync_cron_payloads.py --apply` to push it to the live jobs.
Nothing is restarted here. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / 'src'))
from clawock.model_registry import load  # noqa: E402
from clawock.providers.openclaw import read_jobs, read_runs, runtime_paths  # noqa: E402

DSH_PROFILES = Path.home() / '.dsh' / 'profiles'
PROVIDER_OWNED = ('baseUrl', 'api', 'authHeader', 'timeoutSeconds', 'models')


# ── OpenClaw ─────────────────────────────────────────────────────────────────

def render_openclaw(config: dict, registry) -> dict:
    """`config` with every registry-owned section replaced."""
    out = json.loads(json.dumps(config))
    providers = out.setdefault('models', {}).setdefault('providers', {})
    for name, owned in registry.openclaw_providers().items():
        current = providers.get(name, {})
        merged = {k: v for k, v in current.items() if k not in PROVIDER_OWNED}
        merged.update(owned)
        # Keep the file's key order; new keys go last.
        providers[name] = {**{k: merged[k] for k in current if k in merged}, **merged}
    defaults = out.setdefault('agents', {}).setdefault('defaults', {})
    defaults['models'] = registry.openclaw_model_defaults()
    chat = registry.chain('chat')
    defaults['model'] = {'primary': chat['model'], 'fallbacks': chat['fallbacks']}
    defaults.setdefault('heartbeat', {})['model'] = registry.chain('heartbeat')['model']
    defaults.setdefault('subagents', {})['model'] = registry.chain('subagents')['model']
    dreaming = registry.chain('dreaming')
    memory = out.setdefault('plugins', {}).setdefault('entries', {}).setdefault('memory-core', {})
    memory.setdefault('config', {}).setdefault('dreaming', {})['model'] = dreaming['model']
    memory.setdefault('subagent', {})['allowedModels'] = [dreaming['model'], *dreaming['fallbacks']]
    return out


def openclaw_sections(config: dict) -> dict:
    """The owned sections, for a readable diff."""
    defaults = config.get('agents', {}).get('defaults', {})
    memory = config.get('plugins', {}).get('entries', {}).get('memory-core', {})
    out = {f'models.providers.{name}': {k: v for k, v in spec.items() if k in PROVIDER_OWNED}
           for name, spec in config.get('models', {}).get('providers', {}).items()}
    out.update({
        'agents.defaults.models': defaults.get('models'),
        'agents.defaults.model': defaults.get('model'),
        'agents.defaults.heartbeat.model': defaults.get('heartbeat', {}).get('model'),
        'agents.defaults.subagents.model': defaults.get('subagents', {}).get('model'),
        'memory-core dreaming.model': memory.get('config', {}).get('dreaming', {}).get('model'),
        'memory-core subagent.allowedModels': memory.get('subagent', {}).get('allowedModels'),
    })
    return out


# ── dsh ──────────────────────────────────────────────────────────────────────

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


def render_dsh(text: str, registry) -> str:
    """The profile with its MiniMax provider's baseURL and models list rendered."""
    lines = text.split('\n')
    head = [i for i, line in enumerate(lines) if re.fullmatch(r'\s*minimax:\s*', line)]
    if len(head) != 1:
        raise ValueError(f'expected one `minimax:` provider block, found {len(head)}')
    start, base = head[0], _indent(lines[head[0]])
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > base):
        end += 1
    block = lines[start:end]
    spec = registry.providers['minimax']
    url = [i for i, line in enumerate(block) if line.strip().startswith('baseURL:')]
    key = [i for i, line in enumerate(block) if line.strip() == 'models:']
    if len(url) != 1 or len(key) != 1:
        raise ValueError('MiniMax block needs exactly one baseURL and one models key')
    block[url[0]] = block[url[0]].split('baseURL:')[0] + f"baseURL: {spec['baseUrl']}"
    key_at = key[0]
    first = next(i for i in range(key_at + 1, len(block))
                 if block[i].strip() and not block[i].lstrip().startswith('#'))
    item = _indent(block[first])
    stop = key_at + 1
    while stop < len(block) and (not block[stop].strip() or _indent(block[stop]) > item or (
            _indent(block[stop]) == item and block[stop].lstrip()[:1] in ('-', '#'))):
        stop += 1
    while stop > key_at + 1 and (not block[stop - 1].strip()):
        stop -= 1
    pad = ' ' * item
    rendered = []
    for model in registry.models.values():
        if model.provider == 'minimax':
            rendered += [f'{pad}- id: {model.id}', f'{pad}  name: {model.id}',
                         f"{pad}  contextWindow: {model.entry['contextWindow']}",
                         f"{pad}  maxTokens: {model.entry['maxTokens']}"]
    block[key_at + 1:stop] = rendered
    return '\n'.join(lines[:start] + block + lines[end:])


# ── driver ───────────────────────────────────────────────────────────────────

def plan(registry, openclaw_config: Path | None = None, dsh_profiles: Path = DSH_PROFILES):
    """[(path, current_text, rendered_text, changed_section_names)] for present files."""
    out = []
    config_path = openclaw_config or runtime_paths().config_file
    if config_path.exists():
        current = config_path.read_text()
        config = json.loads(current)
        rendered = render_openclaw(config, registry)
        before, after = openclaw_sections(config), openclaw_sections(rendered)
        changed = [name for name in after if before.get(name) != after[name]]
        out.append((config_path, current,
                    json.dumps(rendered, indent=2, ensure_ascii=False) + '\n' if changed else current,
                    changed))
    for profile in ('web', 'headless'):
        path = dsh_profiles / profile / 'cordis.patch.yml'
        if path.exists():
            current = path.read_text()
            rendered = render_dsh(current, registry)
            out.append((path, current, rendered, ['minimax provider'] if rendered != current else []))
    return out


def write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + '.sync-models.tmp')
    tmp.write_text(text)
    os.chmod(tmp, path.stat().st_mode & 0o777)
    tmp.replace(path)


def effective(registry, openclaw_config: Path | None = None) -> dict:
    out = {}
    config_path = openclaw_config or runtime_paths().config_file
    if config_path.exists():
        out['chat'] = json.loads(config_path.read_text()).get('agents', {}).get(
            'defaults', {}).get('model')
    cron = []
    for job in read_jobs('sqlite').entries:
        payload = job.get('payload') or {}
        runs = read_runs(job.get('id') or '', 'sqlite').entries
        last = runs[-1] if runs else {}
        cron.append({'name': job.get('name'), 'model': payload.get('model'),
                     'fallbacks': payload.get('fallbacks'),
                     'last_run': '/'.join(str(last.get(k)) for k in ('provider', 'model'))
                                 + f" ({last.get('status')})" if last else None})
    out['cron'] = sorted(cron, key=lambda job: job['name'] or '')
    for profile in ('web', 'headless'):
        path = DSH_PROFILES / profile / 'cordis.patch.yml'
        if path.exists():
            out[f'dsh_{profile}'] = re.findall(r'^\s*- id: (MiniMax-\S+)$', path.read_text(), re.M)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--effective', action='store_true')
    args = parser.parse_args(argv)
    registry = load(_CHECKOUT / 'config' / 'models.toml')
    if args.effective:
        print(json.dumps(effective(registry), ensure_ascii=False, indent=2))
        return 0
    drift = 0
    for path, current, rendered, changed in plan(registry):
        if not changed:
            print(f'ok     {path}')
            continue
        drift += 1
        if args.apply:
            write(path, rendered)
            print(f'wrote  {path}: {", ".join(changed)}')
        else:
            print(f'DRIFT  {path}: {", ".join(changed)}')
    if args.apply and drift:
        print('next: `openclaw gateway restart` (no cron in flight) for openclaw.json; '
              'restart dsh for a profile')
    return 1 if drift and not args.apply else 0


if __name__ == '__main__':
    sys.exit(main())
