# Strategy plugins

A strategy, the bars it reads and the evaluator that scores it are separate
plugins, composed by rows in `config/strategy-plugins.json`. The file holds two
compositions:

- `live` is what the brief, report and intraday paths compute with.
- `plugins` is research. `strategy-lab` mounts it, and nothing it produces
  carries live permission.

```bash
clawock strategy-lab list            # mounted plugins, services, strategies
clawock strategy-lab optimize rsi    # walk-forward search → a proposal
clawock strategy-lab ledger          # recorded verdicts across runs
```

## Live composition

`clawock.strategies.live` mounts the `live` rows once per process and hands out
their services. One row is shipped:

| Service | Provider | Contract | Read by |
|---|---|---|---|
| `factors` | `strategies/plugins/quant_factors.py` | `signals(bars)`, `short_history(bars)`, `rsi(closes, period)`, `atr(bars, period)`; config `sigma_target` | `decision/signals.compute_signals` and `compute_short_history_signals`, and through them the quant refresh, both radars, the watch list, the brief's add side, the pre-position lane and `evaluate-add-shapes` |

`decision.signals` keeps the two function names and delegates. The arithmetic
it held before is still there as `legacy_compute_signals` and
`legacy_compute_short_history_signals`, read only by
`tests/test_live_factors_equivalence.py`, which holds plugin and legacy to
identical output on every prefix of every series in `memory/bars` and on
generated series long enough for every setup to fire.

A workspace with no file, or no `live` list, runs the shipped rows. A `live`
list that is present and malformed, or leaves a plugin waiting for a service,
is an error at first use.

`clawock.strategies` imports only `market_data` and `workspace`, so `decision`
can depend on it. The research plugins need `evaluation` and `evidence`, which
depend on `decision`; they live in `clawock.strategy_lab`.

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
| `factors` | `strategies/plugins/quant_factors.py` | the same module the live rows mount |
| `strategies` | `strategies/registry.py` | `register(StrategySpec)`; a spec is `score(bars, params) -> float \| None` (higher is more bullish), its registered `params` and the `space` an optimiser may search |
| `bars` | `strategy_lab/plugins/adjusted_bars.py` (mounted), `strategy_lab/plugins/ledger_bars.py` | `tickers()`, `series(ticker)`, `leg(ticker)`, `describe()` |
| `costs` | `strategy_lab/plugins/registered_costs.py` | `side_bps(leg)`, `describe()`; `config/cost-model.json` through `clawock.costs.CostModel` |
| `optimizer` | `strategy_lab/plugins/walkforward.py` | `run(strategy) -> proposal` |

Two plugins provide `bars`, and a composition mounts one:

- `adjusted_bars` fetches Tencent's forward-adjusted daily series
  (`{hk,us}fqkline/get`) for the names in `memory/bars`, cut at each name's last
  settled session. It reports `corporate_actions_adjusted: true` only for
  series the provider sent under `qfqday`. A name answered under `day` is left
  out and listed in `left_out`: the provider does that for names with no
  corporate action on record and for names it did not adjust, and the answer
  does not say which. The series is not stored; `describe()` carries its digest.
- `ledger_bars` reads `memory/bars`, which is raw, and reports
  `corporate_actions_adjusted: false`. It needs no network.

`strategies/plugins/rsi.py` is the one strategy shipped. Its arithmetic is
the `factors` service's RSI; the plugin adds the registered parameters
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

## Net of cost

The rank IC is gross. Each proposal also carries `net_of_cost`: the same picks
held as a portfolio — the better half of the scored names, equal-weighted, for
the horizon — against the equal-weight of all of them. A tranche replaces the
one formed a horizon earlier and pays `costs.side_bps` on each name that enters
or leaves; the comparison is charged nothing. The block reports the mean excess
per session before and after that charge, its bootstrap interval, the turnover,
and the cost model used.

The model is `config/cost-model.json`: an assumed commission plus half an
assumed spread per side, no impact. The minimum commission is not applied,
because a rank portfolio has no order size.

The registered gate does not read `net_of_cost`. The check
`oos_net_excess_ci95_lower_gt` exists for alternates only.

A `candidate` is a reason to pre-register the parameters and score them
prospectively. Changing the registered parameters is an edit to the row,
reviewed like any configuration change. The rule is the one
`config/factor-universe.json` states for the factor universe: never infer live
permission from a retrospective backtest.

## Alternate gates

The gate can be adjusted without editing it. `gate_alternates` in the optimiser
row lists other threshold sets; each has an `id`, a `rationale` and only the
checks it changes, inheriting the rest from the registered gate.

Every proposal is judged by each alternate beside the registered gate. The
result is in `alternate_gates`: `would_pass`, `would_refuse_because`,
`agrees_with_registered`, and `binding: false`. An alternate never sets
`status`, and nothing outside `strategy-lab` reads it. Promoting one is an edit
that moves its thresholds into `gate`.

Two are shipped. `statistics-only` drops `corporate_actions_adjusted`, so a run
on a source that cannot claim adjustment still records what the statistics
alone would have concluded. `net-of-cost` adds `oos_net_excess_ci95_lower_gt: 0`.

## Ledger

Each `optimize` appends one row to `memory/strategy-lab/ledger.jsonl`: status,
failed checks, every alternate's verdict, the measured intervals, and the
digest of the bars served. `--no-ledger` skips it. The file sits beside
`memory/backtests` as run-time evidence of research; `memory/proposals.jsonl`
is the book's decision proposals and is a different record.

`strategy-lab ledger` reports, per strategy, candidates over distinct inputs,
refusals by check, and for each alternate how often it would have passed and
how often it disagreed with the registered gate. A rerun of the same strategy,
parameters, space, settings and bars counts once, by its latest row.

A gate or alternate naming a check that does not exist is refused at mount.

## Adding a strategy

1. Write a module with `inject = ('strategies',)` and an `apply` that registers
   a `StrategySpec` through `ctx.effect`.
2. Add its row to `config/strategy-plugins.json` with the registered `params`
   and the `space`. The registered parameters must be a point of the space.
3. `clawock strategy-lab optimize <name>`.
