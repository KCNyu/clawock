"""The live composition: the plugins the brief, report and intraday paths run on.

`config/strategy-plugins.json` carries two lists. `plugins` is the research
composition `strategy-lab` mounts. `live` is this one: each row provides a
service a production path reads through `service()`. Changing what those paths
compute is an edit to a row, reviewed like any configuration change.

A checkout without the file, or with a file that has no `live` list, runs the
rows shipped here, so a book that never configured plugins computes what it
always did. A `live` list that is present and wrong is an error at first use:
a production path that silently fell back would be running something other
than what the file says.

Rows fail one at a time. A row whose module does not import, whose config is
refused or whose declaration is incomplete is recorded with its error and the
rest are mounted; `service()` then raises for the services that row would have
provided, and for those of any plugin that declared it needed them, naming the
row and the error. A reader of an unaffected service is not stopped by it.
`health()` lists every row, so a broken one can be seen before a reader asks.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from clawock.plugin_host import declarations, rows as composition
from clawock.plugin_host.kernel import ACTIVE, DISPOSED, Kernel
from clawock.workspace import workspace_root

CONFIG = Path('config') / 'strategy-plugins.json'

#: What runs when the workspace declares no live rows.
DEFAULT_ROWS = (
    {'id': 'factors', 'module': 'clawock.strategies.plugins.quant_factors',
     'config': {'sigma_target': 0.25}, 'signal_source': True},
    {'id': 'daily-bars', 'module': 'clawock.strategies.plugins.daily_bars',
     'config': {'adjustment': 'qfq'}, 'signal_source': True},
    {'id': 'add-policy', 'module': 'clawock.strategies.plugins.add_policy'},
    {'id': 'add-alpha', 'module': 'clawock.strategies.plugins.add_alpha'},
    {'id': 'left-side', 'module': 'clawock.strategies.plugins.left_side'},
    {'id': 'add-side', 'module': 'clawock.strategies.plugins.add_side'},
    {'id': 'preposition', 'module': 'clawock.strategies.plugins.preposition', 'signal_source': True},
    {'id': 'intraday-policy', 'module': 'clawock.strategies.plugins.intraday_policy'},
    {'id': 'bar-signals', 'module': 'clawock.strategies.plugins.bar_signals',
     'signal_source': True},
    {'id': 'signal-panel', 'module': 'clawock.strategy_lab.plugins.signal_panel'},
    {'id': 'sentiment', 'module': 'clawock.strategies.plugins.sentiment',
     'config': {'stale_after_hours': 36}, 'signal_source': True},
    {'id': 'morning-scans', 'module': 'clawock.strategies.plugins.morning_scans',
     'config': {'stale_after_hours': 36}, 'signal_source': True},
    {'id': 'strategy-scores', 'module': 'clawock.strategy_lab.plugins.strategy_scores',
     'signal_source': True},
)


def rows(path: Path | None = None) -> list[dict]:
    path = Path(path) if path else workspace_root() / CONFIG
    if not path.exists():
        return [dict(row) for row in DEFAULT_ROWS]
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise ValueError(f'{path}: configuration must be an object')
    if 'live' not in document:
        return [dict(row) for row in DEFAULT_ROWS]
    declared = document['live']
    if not isinstance(declared, list) or not all(
            isinstance(row, dict) and isinstance(row.get('module'), str) for row in declared):
        raise ValueError(f'{path}: live must be a list of rows naming a module')
    return declared


class Mounted:
    """The kernel, and what became of each row."""

    def __init__(self, path: str):
        self.kernel = Kernel()
        self.rows: list[dict] = []
        for row in rows(Path(path)):
            entry = {'id': row.get('id'), 'module': row['module'], 'error': None, 'fiber': None}
            self.rows.append(entry)
            try:
                entry['fiber'] = composition.mount(self.kernel, row)
            except Exception as exc:
                # The row is out; what it had registered was rolled back by the
                # kernel. The others are mounted as if it were not listed.
                entry['error'] = f'{type(exc).__name__}: {exc}'

    def health(self) -> list[dict]:
        providers = self.kernel.services()
        out = []
        for entry in self.rows:
            fiber = entry['fiber']
            waiting = list(fiber.missing) if fiber else []
            error = entry['error'] or (fiber.error if fiber else None)
            out.append({
                'id': entry['id'], 'module': entry['module'],
                'state': ('failed' if error else 'disposed' if fiber and fiber.state == DISPOSED
                          else 'waiting' if waiting else 'mounted'),
                'error': error, 'waiting_for': waiting,
                'provides': sorted(name for name, owner in providers.items()
                                   if fiber and owner == fiber.name),
            })
        return out


@lru_cache(maxsize=4)
def _mounted(path: str, stamp) -> Mounted:
    return Mounted(path)


def _current() -> Mounted:
    path = workspace_root() / CONFIG
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = None
    return _mounted(str(path), stamp)


def kernel() -> Kernel:
    """The mounted live composition, remounted when the file changes."""
    return _current().kernel


def health() -> list[dict]:
    """Every live row: mounted, waiting for a service, or failed and why."""
    return _current().health()


def signal_sources() -> dict[str, dict]:
    """{row id: its declaration} for the mounted rows that are signal sources."""
    out = {}
    for entry in _current().rows:
        fiber = entry['fiber']
        declaration = fiber and fiber.state == ACTIVE and declarations.of(fiber.plugin)
        if declaration:
            out[entry['id']] = declaration
    return out


def service(name: str):
    mounted = _current()
    if name not in mounted.kernel.services():
        unhealthy = {row['id'] or row['module']: row['error'] or f"waiting for {row['waiting_for']}"
                     for row in mounted.health() if row['state'] != 'mounted'}
        raise ValueError(
            f'{workspace_root() / CONFIG}: no live row provides {name!r}; '
            f'provided: {sorted(mounted.kernel.services())}'
            + (f'; rows not mounted: {unhealthy}' if unhealthy else ''))
    return mounted.kernel.get(name)
