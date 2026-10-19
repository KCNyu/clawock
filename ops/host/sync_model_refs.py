#!/usr/bin/env python3
"""Keep every copy of a model id / MiniMax endpoint equal to config/models.json.

    sync_model_refs.py              # --check: report drift, exit 1 on any
    sync_model_refs.py --apply      # rewrite drifted locations, then re-check
    sync_model_refs.py --effective  # what is configured and what cron last used

The truth file declares *where* each value lives, not just what it is: the
2026-10-19 id switch missed `agents.defaults.models` (the id is a JSON key) and
both dsh profiles, because a string search for the old id found only half of the
places. A binding is one of

- `json`: a dotted path (`*` = every dict value, `[n]` = list index) whose
  string value must equal the rendered template;
- `json_key`: exactly one key under `path` matching `match` must equal it;
- `line`: exactly one line matching `match` (named groups pre/value/post).

Rewrites are textual so a file's own formatting survives: in a JSON file every
occurrence of the old literal must belong to a binding being changed, otherwise
the rewrite is refused. Host files (`"host": true`, `~/...`) are skipped when
absent, so CI checks the repo half only. openclaw.json changes need
`openclaw gateway restart`; cron-schedules.json changes need
`ops/host/sync_cron_payloads.py --apply`; dsh profile changes need a dsh
restart. This tool restarts nothing. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUTH = ROOT / 'config' / 'models.json'
OPENCLAW_DB = Path('~/.openclaw/state/openclaw.sqlite').expanduser()
_STEP = re.compile(r'^(?P<name>[^\[\]]*)(?P<index>(?:\[\d+\])*)$')


def load_truth(path: Path = TRUTH) -> dict:
    truth = json.loads(path.read_text())
    if truth.get('schema_version') != 1:
        raise ValueError(f'{path}: unsupported schema_version')
    return truth


def render(template: str, values: dict) -> str:
    return template.format(**values)


def resolve_file(name: str, root: Path = ROOT) -> Path:
    return Path(name).expanduser() if name.startswith('~') or name.startswith('/') else root / name


def _expand(node, steps):
    """Yield (concrete_path_tuple, value) for every match of `steps`."""
    if not steps:
        yield (), node
        return
    head, rest = steps[0], steps[1:]
    match = _STEP.match(head)
    if not match:
        raise ValueError(f'bad path step {head!r}')
    name, index = match['name'], [int(i) for i in re.findall(r'\[(\d+)\]', match['index'])]
    if name == '*':
        children = list(node.items()) if isinstance(node, dict) else []
    elif name:
        children = [(name, node[name])] if isinstance(node, dict) and name in node else []
    else:
        children = [(None, node)]
    for key, child in children:
        for i in index:
            if not isinstance(child, list) or i >= len(child):
                child = KeyError
                break
            child = child[i]
        if child is KeyError:
            continue
        for path, value in _expand(child, rest):
            yield ((key, *index), *path), value


def _json_locations(data, binding):
    """[(label, current_value)] for one json / json_key binding."""
    steps = binding['path'].split('.')
    found = list(_expand(data, steps))
    if binding['kind'] == 'json':
        return [(_label(path), value) for path, value in found]
    pattern = re.compile(binding['match'])
    out = []
    for path, value in found:
        keys = [k for k in (value or {}) if pattern.search(k)] if isinstance(value, dict) else []
        if len(keys) != 1:
            out.append((_label(path) + f' key~{binding["match"]}', f'<{len(keys)} matching keys>'))
        else:
            out.append((_label(path) + f' key~{binding["match"]}', keys[0]))
    return out


def _label(path):
    parts = []
    for step in path:
        key, *index = step
        parts.append((key or '') + ''.join(f'[{i}]' for i in index))
    return '.'.join(p for p in parts if p)


def inspect(truth: dict, root: Path = ROOT, include_host: bool = True):
    """Every bound location as dicts: file, where, current, expected, ok."""
    values = truth['values']
    rows = []
    for binding in truth['bindings']:
        if binding.get('host') and not include_host:
            continue
        path = resolve_file(binding['file'], root)
        expected = render(binding['value'], values)
        base = {'file': binding['file'], 'binding': binding, 'path': path, 'expected': expected}
        if not path.exists():
            if binding.get('host'):
                rows.append({**base, 'where': binding.get('path') or binding.get('match'),
                             'current': None, 'ok': None})
                continue
            rows.append({**base, 'where': '-', 'current': '<missing file>', 'ok': False})
            continue
        text = path.read_text()
        if binding['kind'] in ('json', 'json_key'):
            found = _json_locations(json.loads(text), binding)
            if not found:
                rows.append({**base, 'where': binding['path'], 'current': '<no match>', 'ok': False})
            for where, current in found:
                rows.append({**base, 'where': where, 'current': current, 'ok': current == expected})
        elif binding['kind'] == 'line':
            pattern = re.compile(binding['match'], re.MULTILINE)
            hits = list(pattern.finditer(text))
            where = binding['match']
            if len(hits) != 1:
                rows.append({**base, 'where': where, 'current': f'<{len(hits)} matching lines>',
                             'ok': False})
            else:
                rows.append({**base, 'where': where, 'current': hits[0]['value'],
                             'ok': hits[0]['value'] == expected})
        else:
            raise ValueError(f'unknown binding kind {binding["kind"]!r}')
    return rows


def _rewrite(path: Path, rows) -> str:
    """New text for one file with its drifted rows fixed, or raise. `rows` are
    all the bound rows of this file, so an unbound copy of an old literal can be
    told apart from a bound one."""
    text = path.read_text()
    json_rows = [row for row in rows if row['binding']['kind'] != 'line']
    pairs, bound = {}, {}
    for row in json_rows:
        bound[row['current']] = bound.get(row['current'], 0) + 1
        if row['ok']:
            continue
        old = row['current']
        if not isinstance(old, str) or old.startswith('<'):
            raise ValueError(f'{path}: {row["where"]} has no single value to rewrite ({old})')
        pairs.setdefault(old, set()).add(row['expected'])
    for old, news in pairs.items():
        if len(news) != 1:
            raise ValueError(f'{path}: {old!r} would map to several values {sorted(news)}')
        literal = json.dumps(old, ensure_ascii=False)
        replacement = json.dumps(news.pop(), ensure_ascii=False)
        if text.count(literal) != bound[old]:
            raise ValueError(f'{path}: {literal} occurs {text.count(literal)}x but {bound[old]} '
                             'are bound; refusing a rewrite that would touch an unbound copy')
        text = text.replace(literal, replacement)
    if json_rows:
        json.loads(text)
    for row in rows:
        if row['binding']['kind'] != 'line' or row['ok']:
            continue
        hits = list(re.compile(row['binding']['match'], re.MULTILINE).finditer(text))
        if len(hits) != 1:
            raise ValueError(f'{path}: {row["where"]} matches {len(hits)} lines')
        hit = hits[0]
        text = text[:hit.start()] + hit['pre'] + row['expected'] + hit['post'] + text[hit.end():]
    return text


def apply(truth: dict, root: Path = ROOT, include_host: bool = True):
    """Rewrite drifted files; returns the files changed. Every file is fully
    validated before any is written."""
    by_file = {}
    for row in inspect(truth, root, include_host):
        if row['ok'] is not None:
            by_file.setdefault(row['path'], []).append(row)
    pending = {path: _rewrite(path, rows) for path, rows in by_file.items()
               if not all(row['ok'] for row in rows)}
    for path, new_text in pending.items():
        tmp = path.with_name(path.name + '.sync-model-refs.tmp')
        tmp.write_text(new_text)
        os.chmod(tmp, path.stat().st_mode & 0o777)
        tmp.replace(path)
    return list(pending)


def effective(truth: dict) -> dict:
    """What OpenClaw, the cron jobs and dsh are configured with now, and what
    the latest cron runs actually used (read-only)."""
    out = {'truth': truth['values']}
    config = Path('~/.openclaw/openclaw.json').expanduser()
    if config.exists():
        data = json.loads(config.read_text())
        defaults = data.get('agents', {}).get('defaults', {})
        out['openclaw_chat'] = {
            'primary': defaults.get('model', {}).get('primary'),
            'fallbacks': defaults.get('model', {}).get('fallbacks'),
            'heartbeat': defaults.get('heartbeat', {}).get('model'),
            'subagents': defaults.get('subagents', {}).get('model'),
            'dreaming': data.get('plugins', {}).get('entries', {}).get('memory-core', {})
                            .get('config', {}).get('dreaming', {}).get('model'),
        }
    if OPENCLAW_DB.exists():
        db = sqlite3.connect(f'file:{OPENCLAW_DB}?mode=ro', uri=True)
        jobs = {}
        for job_id, name, enabled, model, fallbacks in db.execute(
                'select job_id, name, enabled, payload_model, payload_fallbacks_json from cron_jobs'):
            jobs[job_id] = {'name': name, 'enabled': bool(enabled), 'model': model,
                            'fallbacks': json.loads(fallbacks) if fallbacks else None}
        for job_id, provider, model, status, ts in db.execute(
                'select job_id, provider, model, status, max(run_at_ms) from cron_run_logs '
                'group by job_id'):
            if job_id in jobs:
                jobs[job_id]['last_run'] = {'provider': provider, 'model': model, 'status': status,
                                            'run_at_ms': ts}
        out['openclaw_cron'] = sorted(jobs.values(), key=lambda job: job['name'] or '')
    for profile in ('web', 'headless'):
        path = Path(f'~/.dsh/profiles/{profile}/cordis.patch.yml').expanduser()
        if path.exists():
            out[f'dsh_{profile}_minimax_ids'] = re.findall(r'^\s*- id: (MiniMax-\S+)$', path.read_text(),
                                                           re.MULTILINE)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--effective', action='store_true')
    parser.add_argument('--repo-only', action='store_true', help='skip host files')
    args = parser.parse_args(argv)
    truth = load_truth()
    if args.effective:
        print(json.dumps(effective(truth), ensure_ascii=False, indent=2))
        return 0
    include_host = not args.repo_only
    if args.apply:
        for path in apply(truth, include_host=include_host):
            print(f'rewrote {path}')
    rows = inspect(truth, include_host=include_host)
    drift = [row for row in rows if row['ok'] is False]
    for row in rows:
        mark = {True: 'ok   ', False: 'DRIFT', None: 'skip '}[row['ok']]
        detail = '' if row['ok'] else f"  current={row['current']!r} expected={row['expected']!r}"
        print(f"{mark} {row['file']}  {row['where']}{detail}")
    print(f'{len(rows) - len(drift)} ok/skipped, {len(drift)} drifted')
    return 1 if drift else 0


if __name__ == '__main__':
    sys.exit(main())
