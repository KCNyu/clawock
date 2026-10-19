#!/usr/bin/env python3
"""Make every copy of a model id / the MiniMax endpoint follow config/models.json.

    sync_model_refs.py              # check: list drift, exit 1 on any
    sync_model_refs.py --apply      # rewrite drifted copies, then check again
    sync_model_refs.py --effective  # what chat, cron and dsh run with right now

`config/models.json` holds values only. *Where* each value lives is the table
in `targets()` below, so a new copy is one line there. The 2026-10-19 id switch
missed `agents.defaults.models` (the id is a JSON key) and both dsh profiles;
a string search for the old id finds only part of the copies.

Rewrites are textual, so each file keeps its own formatting. An old literal that
also appears somewhere unbound blocks the rewrite. Every file is validated
before any is written. Host files are skipped when absent, so CI checks the
repository half. Nothing is restarted: after --apply run
`ops/host/sync_cron_payloads.py --apply` (cron contract), `openclaw gateway
restart` (openclaw.json, no cron in flight) or restart dsh (profiles).
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from clawock.providers.openclaw import read_jobs, read_runs, runtime_paths  # noqa: E402

TRUTH = ROOT / 'config' / 'models.json'
DSH_PROFILES = Path.home() / '.dsh' / 'profiles'


@dataclass
class Target:
    """One file and the values it must carry.

    `json`: dotted path → value (`*` = every dict value, `[n]` = list index).
    `keys`: dotted path → (regex, value): the one key there matching regex.
    `consts`: Python `NAME = '...'` assignments.
    `yaml_minimax`: field → value for the MiniMax M3.x entry of a dsh profile.
    """
    path: Path
    json: dict = field(default_factory=dict)
    keys: dict = field(default_factory=dict)
    consts: dict = field(default_factory=dict)
    yaml_minimax: dict = field(default_factory=dict)
    host: bool = False


def load_truth(path: Path = TRUTH) -> dict:
    truth = json.loads(path.read_text())
    if truth.get('schema_version') != 2:
        raise ValueError(f'{path}: unsupported schema_version')
    return truth


def targets(truth: dict, root: Path = ROOT, openclaw_config: Path | None = None,
            dsh_profiles: Path = DSH_PROFILES):
    minimax = truth['minimax']
    primary = f"minimax/{minimax['model']}"
    retry = f"minimax-2/{minimax['model']}"
    luna, sol = truth['cron']['codex_fallback'], truth['cron']['codex_candidate']
    openclaw_config = openclaw_config or runtime_paths().config_file

    yield Target(root / 'config/cron-schedules.json', json={
        'payload_profiles.*.model': primary,
        'payload_profiles.*.fallbacks[0]': retry,
        'payload_profiles.*.fallbacks[1]': luna,
        'payload_profiles.*.model_candidates[0]': primary,
        'payload_profiles.*.model_candidates[1]': retry,
        'payload_profiles.*.model_candidates[2]': luna,
        'payload_profiles.*.model_candidates[3]': sol,
    })
    yield Target(root / 'src/clawock/automation/llm.py', consts={
        'MINIMAX_MODEL': minimax['model'],
        'MINIMAX_BASE': minimax['anthropic_base'],
    })
    # models[1] in each provider is the MiniMax-M3 rollback entry: unbound.
    provider_tables = {}
    for provider in ('minimax', 'minimax-2'):
        provider_tables.update({
            f'models.providers.{provider}.baseUrl': minimax['anthropic_base'],
            f'models.providers.{provider}.models[0].id': minimax['model'],
            f'models.providers.{provider}.models[0].name': minimax['display_name'],
        })
    yield Target(openclaw_config, host=True, json={
        **provider_tables,
        'agents.defaults.model.primary': primary,
        'agents.defaults.model.fallbacks[0]': truth['chat']['fallback'],
        'agents.defaults.heartbeat.model': primary,
        'agents.defaults.subagents.model': primary,
        'plugins.entries.memory-core.config.dreaming.model': primary,
        'plugins.entries.memory-core.subagent.allowedModels[0]': primary,
    }, keys={
        'agents.defaults.models': (r'^minimax/MiniMax-M3\.', primary),
    })
    for profile in ('web', 'headless'):
        yield Target(dsh_profiles / profile / 'cordis.patch.yml', host=True, yaml_minimax={
            'id': minimax['model'],
            'name': minimax['model'],
            'baseURL': minimax['anthropic_base'],
        })


# ── reading ──────────────────────────────────────────────────────────────────

_STEP = re.compile(r'^([^\[\]]*)((?:\[\d+\])*)$')


def _walk(node, steps, label=''):
    """(label, value) for every match of a dotted path."""
    if not steps:
        yield label, node
        return
    name, index = _STEP.match(steps[0]).groups()
    if name == '*':
        children = list(node.items()) if isinstance(node, dict) else []
    else:
        children = [(name, node[name])] if isinstance(node, dict) and name in node else []
    for key, child in children:
        here = f'{label}.{key}' if label else key
        for i in map(int, re.findall(r'\d+', index)):
            if not isinstance(child, list) or i >= len(child):
                break
            child, here = child[i], f'{here}[{i}]'
        else:
            yield from _walk(child, steps[1:], here)


def _const_line(name):
    return re.compile(rf"^(?P<pre>{name} = ')(?P<value>[^']*)(?P<post>')$", re.MULTILINE)


def _yaml_line(field_name):
    # The MiniMax M3.x entry only: `MiniMax-M3` itself is the rollback id, and
    # the baseURL line is the one pointing at minimax.
    value = r'\S*minimax\S*' if field_name == 'baseURL' else r'MiniMax-M3\.\S+'
    prefix = r'\s*- id: ' if field_name == 'id' else rf'\s*{field_name}: '
    return re.compile(rf'^(?P<pre>{prefix})(?P<value>{value})(?P<post>)$', re.MULTILINE)


def inspect(target: Target):
    """[(where, current, expected)] for one target; [] for an absent host file."""
    if not target.path.exists():
        if target.host:
            return []
        return [('-', '<missing file>', 'present')]
    text = target.path.read_text()
    rows = []
    if target.json or target.keys:
        data = json.loads(text)
        for path, expected in target.json.items():
            found = list(_walk(data, path.split('.')))
            rows += found and [(where, value, expected) for where, value in found] \
                or [(path, '<no match>', expected)]
        for path, (pattern, expected) in target.keys.items():
            for where, table in _walk(data, path.split('.')):
                hits = [key for key in table if re.search(pattern, key)]
                rows.append((f'{where} key', hits[0] if len(hits) == 1 else f'<{len(hits)} keys>',
                             expected))
    for lines, make in ((target.consts, _const_line), (target.yaml_minimax, _yaml_line)):
        for name, expected in lines.items():
            hits = list(make(name).finditer(text))
            rows.append((name, hits[0]['value'] if len(hits) == 1 else f'<{len(hits)} lines>',
                         expected))
    return rows


# ── writing ──────────────────────────────────────────────────────────────────

def _rewritten(target: Target, rows) -> str:
    text = target.path.read_text()
    line_names = set(target.consts) | set(target.yaml_minimax)
    json_rows = [row for row in rows if row[0] not in line_names]
    bound, renames = {}, {}
    for where, current, expected in json_rows:
        bound[current] = bound.get(current, 0) + 1
        if current != expected:
            if current.startswith('<'):
                raise ValueError(f'{target.path}: {where} has no single value ({current})')
            renames.setdefault(current, set()).add(expected)
    for old, new in renames.items():
        if len(new) != 1:
            raise ValueError(f'{target.path}: {old!r} would become several values {sorted(new)}')
        literal = json.dumps(old, ensure_ascii=False)
        if text.count(literal) != bound[old]:
            raise ValueError(f'{target.path}: {literal} appears {text.count(literal)}x but only '
                             f'{bound[old]} are bound; refusing to touch an unbound copy')
        text = text.replace(literal, json.dumps(new.pop(), ensure_ascii=False))
    if json_rows:
        json.loads(text)
    for lines, make in ((target.consts, _const_line), (target.yaml_minimax, _yaml_line)):
        for name, expected in lines.items():
            hits = list(make(name).finditer(text))
            if len(hits) != 1:
                raise ValueError(f'{target.path}: {name} matches {len(hits)} lines')
            hit = hits[0]
            text = text[:hit.start()] + hit['pre'] + expected + hit['post'] + text[hit.end():]
    return text


def apply(all_targets) -> list[Path]:
    pending = {}
    for target in all_targets:
        rows = inspect(target)
        if any(current != expected for _, current, expected in rows):
            pending[target.path] = _rewritten(target, rows)
    for path, text in pending.items():
        tmp = path.with_name(path.name + '.sync-model-refs.tmp')
        tmp.write_text(text)
        os.chmod(tmp, path.stat().st_mode & 0o777)
        tmp.replace(path)
    return list(pending)


# ── what is actually running ─────────────────────────────────────────────────

def effective(truth: dict, openclaw_config: Path | None = None) -> dict:
    out = {'truth': {key: value for key, value in truth.items()
                     if key not in ('schema_version', 'description')}}
    config = openclaw_config or runtime_paths().config_file
    if config.exists():
        defaults = json.loads(config.read_text()).get('agents', {}).get('defaults', {})
        out['chat'] = {'primary': defaults.get('model', {}).get('primary'),
                       'fallbacks': defaults.get('model', {}).get('fallbacks')}
    cron = []
    for job in read_jobs('sqlite').entries:
        payload = job.get('payload') or {}
        runs = read_runs(job.get('id') or job.get('jobId') or '', 'sqlite').entries
        last = runs[-1] if runs else {}
        cron.append({'name': job.get('name'), 'enabled': job.get('enabled'),
                     'model': payload.get('model'), 'fallbacks': payload.get('fallbacks'),
                     'last_run': {key: last.get(key) for key in ('provider', 'model', 'status')}})
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
    truth = load_truth()
    if args.effective:
        print(json.dumps(effective(truth), ensure_ascii=False, indent=2))
        return 0
    if args.apply:
        for path in apply(targets(truth)):
            print(f'rewrote {path}')
    drift = 0
    for target in targets(truth):
        rows = inspect(target)
        bad = [row for row in rows if row[1] != row[2]]
        drift += len(bad)
        state = 'absent' if not rows else 'DRIFT' if bad else 'ok'
        print(f'{state:6} {target.path}  ({len(rows)} copies)')
        for where, current, expected in bad:
            print(f'         {where}: {current!r} -> {expected!r}')
    return 1 if drift else 0


if __name__ == '__main__':
    sys.exit(main())
