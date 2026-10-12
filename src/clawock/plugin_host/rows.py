"""Mounting one row of a composition.

A row names a module and, optionally, its config:

    {"id": "factors", "module": "clawock.strategies.plugins.quant_factors",
     "config": {"sigma_target": 0.25}, "signal_source": true}

The module may live outside this package: anything importable that exposes
`apply(ctx, config)` is a plugin, with optional `name`, `inject`, `emits` and
`SIGNAL_SOURCE`. `signal_source: true` on the row is the composition saying
"this row's readings reach a decision", and such a row is not mounted unless
its module carries a declaration that passes `declarations.validate`. A module
that carries one is checked whether or not the row asks.
"""
from __future__ import annotations

import importlib

from clawock.plugin_host import declarations
from clawock.plugin_host.kernel import Fiber, Kernel


def mount(kernel: Kernel, row: dict) -> Fiber:
    module = importlib.import_module(row['module'])
    declaration = declarations.of(module, row['module'])
    if row.get('signal_source') and declaration is None:
        raise declarations.DeclarationError(
            f"{row['module']}: the row says signal_source and the module has no SIGNAL_SOURCE")
    return kernel.plugin(module, row.get('config'))
