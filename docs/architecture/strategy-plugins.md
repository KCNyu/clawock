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
clawock strategy-lab record          # every strategy, into the ledger (the brief runs this)
clawock strategy-lab ledger          # recorded verdicts across runs
```

## Live composition

`clawock.plugin_host.live` mounts the `live` rows once per process and hands out
their services:

| Service | Provider | Contract | Read by |
|---|---|---|---|
| `factors` | `strategies/plugins/quant_factors.py` | `signals(bars)`, `short_history(bars)`, `rsi(closes, period)`, `atr(bars, period)`; config `sigma_target` | `decision/signals.compute_signals` and `compute_short_history_signals`, and through them the quant refresh, both radars, the watch list, the brief's add side, the pre-position lane and `evaluate-add-shapes` |
| `daily_bars` | `strategies/plugins/daily_bars.py` | `fetch(code, cnt)`; config `adjustment` (`qfq` or `raw`) | `decision/signals.fetch_bars`, and through it the quant refresh, both radars, the provisional setups, the watch list, the strategy escalations and `evaluate-add-shapes --source tencent` |

### Adjusted bars on the live path

Until 2026-10-12 `fetch_bars` asked two endpoints that both return raw prices:
`kline/kline` for Hong Kong, and the market-less `fqkline/get` for US names,
which answers a `qfq` request under `day`. A name that split inside the
400-session window had a factor row computed across the split. `daily_bars`
asks the per-market endpoint, `{hk,us}fqkline/get`, instead.

`memory/bars` is unchanged and stays raw: it settles nominal trigger prices.
The brief's add side and the pre-position lane compute from that store, so
they still read raw bars.

To go back, set the row's `adjustment` to `raw`. That restores the two
requests exactly; `tests/test_live_daily_bars.py` holds the URLs.

`decision.signals` keeps the two function names and delegates. The arithmetic
it held before is still there as `legacy_compute_signals` and
`legacy_compute_short_history_signals`, read only by
`tests/test_live_factors_equivalence.py`, which holds plugin and legacy to
identical output on every prefix of every series in `memory/bars` and on
generated series long enough for every setup to fire.

### The migrated modules

Eight modules are plugins mounted by `live` rows. Each row provides the module
itself as a service of the same name:

| Service | Plugin | The import path its readers keep |
|---|---|---|
| `add_policy` | `strategies/plugins/add_policy.py` | `decision.add_policy` |
| `add_alpha` | `strategies/plugins/add_alpha.py` | `decision.add_alpha` |
| `left_side` | `strategies/plugins/left_side.py` | `decision.left_side` |
| `add_side` | `strategies/plugins/add_side.py` | `decision.add_side` |
| `preposition` | `strategies/plugins/preposition.py` | `decision.preposition` |
| `intraday_policy` | `strategies/plugins/intraday_policy.py` | `decision.intraday_policy` |
| `bar_signals` | `strategies/plugins/bar_signals.py` | `market_data.bar_signals` |
| `signal_panel` | `strategy_lab/plugins/signal_panel.py` | `evaluation.signal_panel` |

The old import paths are views of the mounted service
(`plugin_host/facade.py`): reading `decision.add_policy.tranche_plan` reads the
service's attribute, and setting one sets the service's. The readers are
unchanged and run whatever module the row names. The policy files
(`config/add-alpha-policy.json`, `left-side-policy.json`,
`preposition-policy.json`, `intraday-strategy-policies.json`) are read by the
same code as before and are not part of the row.

Inside the plugin package, `add_alpha`, `add_side` and `preposition` import
`add_policy` and `left_side` as sibling modules, not through the kernel, so
replacing the `add_policy` row replaces what the readers call and not what
`add_side` calls internally. `preposition` reads the `factors` service.

The code each module held before the move is `legacy_<module>.py` in its old
package, unchanged apart from importing its legacy siblings. Nothing in
production reads it. `tests/legacy_shadow.py` wraps every public function of
the eight plugins for the whole test run: an outermost call into a plugin is
also made into the legacy function on a copy of the same arguments, and the
two must agree on the value (floats exact), the error, and the state they
leave their arguments in. `tests/test_migrated_plugins_equivalence.py` checks
the shadow itself and drives the plugins over the stored bars, the policy
files and the holdings. The legacy modules, the shadow and that test are
removed together in a separate change, once the plugins have run in
production.

A workspace with no file, or no `live` list, runs the shipped rows. A `live`
list that is present and malformed, leaves a plugin waiting for a service, or
omits a service a reader asks for, is an error at first use. Every live row is
mounted when the first service is read, so a row that fails to import stops
every reader of the composition.

### Where the kernel sits

`clawock.plugin_host` holds the kernel, the live composition and the facade.
It imports only `workspace`, so any package may read a service from it:
`market_data.bar_signals` and `evaluation.signal_panel` could not have read a
kernel that lived beside the plugins, because `strategies` imports
`market_data` and `strategy_lab` imports `evaluation`. Plugins are imported by
name from the row, so the import graph in `tests/package_edges.txt` shows the
readers depending on `plugin_host`, not on `strategies`. What a reader runs at
run time is decided by the row.

`clawock.strategies` holds plugins that need nothing above `market_data`. The
research plugins need `evaluation`, `evidence` and `decision`; they live in
`clawock.strategy_lab`.

## Primitives

`src/clawock/plugin_host/kernel.py` restates the Cordis primitives the dsh plugin
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
  settled session. Each answer is read as one of three bases
  (`market_data/tencent_daily.fetch_daily_with_basis` documents the shapes):

  | Basis | The answer | Served |
  |---|---|---|
  | `adjusted` | under `qfqday` | yes |
  | `no_action_on_record` | under `day`, every row carrying the provider's corporate-action slot, all of them empty: the raw series is the adjusted one | yes, listed apart in `basis` |
  | `unconfirmed` | under `day` without that record, or with an action on record the series was not adjusted for | no, listed in `left_out` |

  `no_action_on_record` is one provider's record of actions, not a second
  source. `corporate_actions_adjusted` is true when at least one series is
  served; an unconfirmed name is never part of the sample it describes. The
  series is not stored; `describe()` carries its digest.
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
`strategy_lab/plugins/signal_panel.py`), then walks forward: each refit sees only sessions
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
prospectively; the scheduled run does that for a candidate no live alternate
objects to (see below). Changing the registered parameters is an edit to the row,
reviewed like any configuration change. The rule is the one
`config/factor-universe.json` states for the factor universe: never infer live
permission from a retrospective backtest.

## Alternate gates

The gate can be adjusted without editing it. `gate_alternates` in the optimiser
row lists other threshold sets; each has an `id`, a `rationale` and only the
checks it changes, inheriting the rest from the registered gate.

Every proposal is judged by each alternate beside the registered gate. The
result is in `alternate_gates`: `would_pass`, `would_refuse_because`,
`agrees_with_registered`, `effect`, and `binding: false`. An alternate never
sets `status`. Promoting one is an edit that moves its thresholds into `gate`.

### Live effect

An alternate's `effect` is `record` (the default) or `live`.

- `record`: the verdict is written beside the proposal and nothing acts on it.
- `live`: a refusal is an objection. The proposal's `live_review` lists the
  live alternates, their `objections`, and `cleared`, which is true only when
  the registered gate passed and no live alternate objects.

A live alternate may only add a check or tighten one. A row with `effect:
live` that drops `corporate_actions_adjusted`, raises `pbo_lt`, or lowers any
other bar is refused at mount. So a live alternate can keep a candidate from
being cleared and cannot clear what the registered gate refuses.

What `cleared` leads to is registration, below. It does not change `status`,
and `live_permission` stays `false` on the proposal and on the registration.

Two alternates are shipped. `statistics-only` (`record`) drops
`corporate_actions_adjusted`, so a run on a source that cannot claim adjustment
still records what the statistics alone would have concluded. `net-of-cost`
(`live`) adds `oos_net_excess_ci95_lower_gt: 0`.

## The scheduled run

`clawock strategy-lab record` optimises every mounted strategy, appends each
verdict to the ledger, and registers what is cleared. One strategy failing does
not stop the others.

The daily brief runs it after delivery, before its commit
(`brief_postflight.record_strategy_lab`). Preflight has by then appended the
sessions that closed since the last brief to `memory/bars`, and the adjusted
series are cut at that store, so each run sees completed sessions only. The
brief's commit stages `memory/`, which publishes the ledger and the
registrations. The run is bounded at 300 seconds and a failure is a warning: it
never blocks the commit. It does not run on a dry run or when the brief's
status is `fail`.

### Registration and prospective scoring

A cleared candidate's selected parameters are written once to
`memory/strategy-lab/registrations.jsonl`, with `after_session`: the latest bar
that run was served. Every later run scores each registration on the signal
sessions after `after_session` only and reports it in `prospective` (sessions
and mean rank IC). Those sessions did not exist when the parameters were
chosen, which is the measurement a retrospective search cannot give.

Nothing reads `prospective` to change a parameter. Changing the registered
parameters is still an edit to the row.

## Ledger

`optimize` and `record` append one row per proposal to
`memory/strategy-lab/ledger.jsonl`: status, failed checks, every alternate's
verdict, `live_review`, `prospective`, the measured intervals, and the digest
and basis of the bars served. `optimize --no-ledger` skips it. The file sits
beside `memory/backtests` as run-time evidence of research;
`memory/proposals.jsonl` is the book's decision proposals and is a different
record.

`strategy-lab ledger` reports, per strategy, candidates and cleared candidates
over distinct inputs, refusals by check, objections by live alternate, and for
each alternate how often it would have passed and how often it disagreed with
the registered gate. A rerun of the same strategy, parameters, space, settings
and bars counts once, by its latest row.

A gate or alternate naming a check that does not exist is refused at mount.

## Adding a strategy

1. Write a module with `inject = ('strategies',)` and an `apply` that registers
   a `StrategySpec` through `ctx.effect`.
2. Add its row to `config/strategy-plugins.json` with the registered `params`
   and the `space`. The registered parameters must be a point of the space.
3. `clawock strategy-lab optimize <name>`.
