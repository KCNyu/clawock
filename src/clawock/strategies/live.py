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
"""
from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path

from clawock.strategies.kernel import Kernel
from clawock.workspace import workspace_root

CONFIG = Path('config') / 'strategy-plugins.json'

#: What runs when the workspace declares no live rows.
DEFAULT_ROWS = (
    {'id': 'factors', 'module': 'clawock.strategies.plugins.quant_factors',
     'config': {'sigma_target': 0.25}},
    {'id': 'daily-bars', 'module': 'clawock.strategies.plugins.daily_bars',
     'config': {'adjustment': 'qfq'}},
)


def rows(path: Path | None = None) -> list[dict]:
    path = Path(path) if path else workspace_root() / CONFIG
    if not path.exists():
        return [dict(row) for row in DEFAULT_ROWS]
    declared = json.loads(path.read_text(encoding='utf-8')).get('live')
    if declared is None:
        return [dict(row) for row in DEFAULT_ROWS]
    if not isinstance(declared, list) or not all(
            isinstance(row, dict) and isinstance(row.get('module'), str) for row in declared):
        raise ValueError(f'{path}: live must be a list of rows naming a module')
    return declared


@lru_cache(maxsize=4)
def _mounted(path: str, stamp) -> Kernel:
    kernel = Kernel()
    for row in rows(Path(path)):
        kernel.plugin(importlib.import_module(row['module']), row.get('config'))
    waiting = {fiber.name: fiber.missing for fiber in kernel.fibers if fiber.missing}
    if waiting:
        raise ValueError(f'{path}: live plugins are waiting for services nobody provides: {waiting}')
    return kernel


def kernel() -> Kernel:
    """The mounted live composition, remounted when the file changes."""
    path = workspace_root() / CONFIG
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = None
    return _mounted(str(path), stamp)


def service(name: str):
    mounted = kernel()
    if name not in mounted.services():
        raise ValueError(
            f'{workspace_root() / CONFIG}: no live row provides {name!r}; '
            f'provided: {sorted(mounted.services())}')
    return mounted.get(name)
