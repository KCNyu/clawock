# Strategy plugins

A strategy, the bars it reads and the evaluator that scores it are separate
plugins, composed by rows in `config/strategy-plugins.json`. The layer is
research: nothing in the brief, report or intraday paths mounts it, and nothing
it produces carries live permission.

```bash
clawock strategy-lab list            # mounted plugins, services, strategies
clawock strategy-lab optimize rsi    # walk-forward search → a proposal
```

## Primitives

`src/clawock/strategies/kernel.py` restates the Cordis primitives the dsh plugin
under `examples/dsh/` is built on. Strategies stay in Python because they have
to run inside this package's data and gates.

| Cordis / dsh | Here | Meaning |
|---|---|---|
| a row in `cordis.patch.yml` | a row in `config/strategy-plugins.json` (`module`, `config`) | mounts one plugin; the module may live outside this package |
| fiber | `Fiber`, returned by `Kernel.plugin()` | one mounted plugin: its config, declared dependencies and registrations |
| `provide` / `inject` | `ctx.provide(name, service)`, module-level `inject = (...)` | mount order is irrelevant; a fiber waits for its services and stops when one is withdrawn |
| `ctx.effect()` | `ctx.effect(execute, label)` | every registration records its undo; unmounting runs them in reverse |
| `fiber.update(config)` | `Fiber.update(config)` | a parameter change is a restart under the new config |

A plugin is any importable module with `apply(ctx, config)` and, optionally,
`name` and `inject`. `ctx.get()` refuses a service the plugin did not declare.
Event dispatch (`emit`, `waterfall`), async fibers and scoped services are not
implemented.

## Services

| Service | In-tree provider | Contract |
|---|---|---|
| `strategies` | `strategies/registry.py` | `register(StrategySpec)`; a spec is `score(bars, params) -> float \| None` (higher is more bullish), its registered `params` and the `space` an optimiser may search |
| `bars` | `strategies/plugins/ledger_bars.py` | `tickers()`, `series(ticker)`, `describe()`; reads `memory/bars`, which is raw and reports `corporate_actions_adjusted: false` |
| `optimizer` | `strategies/plugins/walkforward.py` | `run(strategy) -> proposal` |

`strategies/plugins/rsi.py` is the one strategy shipped. Its arithmetic is
`decision.signals._rsi14`; the plugin adds the registered parameters
(`period: 14`, `direction: reversion`), the grid and the orientation.

A strategy is handed the history up to its signal session and nothing later, so
it cannot read ahead however it is written.

## What an optimisation may conclude

`optimize` scores every point of the declared grid by daily rank IC against the
forward return (entry at the first close after the signal session, as in
`evaluation/signal_panel.py`), then walks forward: each refit sees only sessions
whose forward return had closed, and is scored on the next block against the
registered parameters.

The output is a proposal with `live_permission: false`, always. Its `status` is
`candidate` only when every gate check passes, otherwise `refused` with the
failed checks listed:

| Check (row config `gate`) | Why |
|---|---|
| `min_oos_sessions` | too few walk-forward sessions to read |
| `oos_ic_ci95_lower_gt` | the selected parameters must have an edge, by stationary block bootstrap |
| `oos_lift_ci95_lower_gt` | and must beat the registered parameters, not just differ |
| `pbo_lt` | CSCV probability of backtest overfitting over the whole grid (`evaluation/cscv.py`); unmeasured fails |
| `corporate_actions_adjusted` | the bars source must say it is adjusted |

A `candidate` is a reason to pre-register the parameters and score them
prospectively. Changing the registered parameters is an edit to the row,
reviewed like any configuration change. The rule is the one
`config/factor-universe.json` states for the factor universe: never infer live
permission from a retrospective backtest.

## Adding a strategy

1. Write a module with `inject = ('strategies',)` and an `apply` that registers
   a `StrategySpec` through `ctx.effect`.
2. Add its row to `config/strategy-plugins.json` with the registered `params`
   and the `space`. The registered parameters must be a point of the space.
3. `clawock strategy-lab optimize <name>`.
