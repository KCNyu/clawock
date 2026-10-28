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
clawock strategy-lab evolution rsi   # one strategy's record, run by run
clawock strategy-lab row-edits       # row edits the lab has proposed, for review
clawock strategy-lab verify          # the ledger against the lab's boundaries
clawock strategy-lab sources         # what each signal source declares
```

## Live composition

`clawock.plugin_host.live` mounts the `live` rows once per process and hands out
their services:

| Service | Provider | Contract | Read by |
|---|---|---|---|
| `factors` | `strategies/plugins/quant_factors.py` | `signals(bars)`, `short_history(bars)`, `rsi(closes, period)`, `atr(bars, period)`; config `sigma_target` | `decision/signals.compute_signals` and `compute_short_history_signals`, and through them the quant refresh, both radars, the watch list, the brief's add side, the pre-position lane and `evaluate-add-shapes` |
| `daily_bars` | `strategies/plugins/daily_bars.py` | `fetch(code, cnt)`; config `adjustment` (`qfq` or `raw`) | `decision/signals.fetch_bars`, and through it the quant refresh, both radars, the provisional setups, the watch list, the strategy escalations and `evaluate-add-shapes --source tencent` |

| `sentiment` | `strategies/plugins/sentiment.py` | `attention(workspace, recent_moves)`, `statements(workspace)`, each answering `{status, reading, age_hours, detail}`; config `stale_after_hours` | `harness/brief_preflight.load_macro_and_sentiment` and `load_influencer_feed` |

| `scans` | `strategies/plugins/morning_scans.py` | `path(workspace, scan)`, `document(path)` answering `{status, payload, error}`, and the brief's reads `macro(workspace)` and `em_news(workspace)`; config `stale_after_hours` | `harness/brief_preflight` (macro, Eastmoney news), `evidence/intraday_information`, `evidence/news_evidence_graph`, `publish/dashboard` (the regime badge) |
| `strategy_scores` | `strategy_lab/plugins/strategy_scores.py` | `read(workspace, tickers)`: each lab strategy's score and rank per stored name under the row's registered parameters, with the lab's standing; `status` is `ok` or `unavailable` | `harness/brief_preflight`, which puts it in the brief context's `research` bundle as `strategy_scores` |

### Which rows declare measurements

There are thirteen live rows; classification follows the data the row emits,
not whether it contains arithmetic. Measurement adapters declare their output
too. Policy and evaluation services do not claim to be new measured signals.

| Live row | Kind and boundary |
|---|---|
| `factors` | Signal source: factor values and technical setup measurements; declared field units and history windows |
| `daily-bars` | Signal source: dated OHLC input adapter, qfq/raw basis; no volume output |
| `add-policy` | Policy: tranche terms and caps, not a measured score |
| `add-alpha` | Policy: gates and setup terms from supplied measurements |
| `left-side` | Policy: configured observation ladder; no standalone measurement claim |
| `add-side` | Policy projection: joins existing readings and classifies opportunity |
| `preposition` | Signal source and policy: projects own-instrument factors, then applies authorized setup rules |
| `intraday-policy` | Policy: holding-strategy exceptions and escalation rules |
| `bar-signals` | Signal source: liquidity/volatility estimators, units and missing windows |
| `signal-panel` | Historical evaluator: panel statistics, not a decision score or settlement owner |
| `sentiment` | Signal source: measured attention and filtered statements with freshness/status |
| `morning-scans` | Signal source: macro/news projections; raw document reads leave freshness to the reader |
| `strategy-scores` | Signal source: registered strategy scores/ranks plus explicitly historical lab standing |

A source declaration validates required text and uniqueness; it does not infer
undocumented behavior from arbitrary Python. Recorded output tests and boundary
regressions check the shipped implementations against the declarations. Malformed configured live lists are not silently replaced with defaults;
only an absent file or absent `live` key uses the shipped defaults.

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
it held before the move stayed in the module as `legacy_*` until 2026-10-12,
compared with the plugin on every prefix of every stored series, and was then
removed: the plugin is the only implementation.

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
service's attribute, and setting one sets the service's. Deleting a name
through the view puts back the value a write through it covered (how pytest
>= 9.2 undoes `monkeypatch.setattr` on a module), so the plugin's own global
is never removed by an undo. The readers are
unchanged and run whatever module the row names. The policy files
(`config/add-alpha-policy.json`, `left-side-policy.json`,
`preposition-policy.json`, `intraday-strategy-policies.json`) are read by the
same code as before and are not part of the row.

Inside the plugin package, `add_alpha`, `add_side` and `preposition` name
`add_policy` (and `left_side` for `add_side`) through the live kernel, too.
Their `inject` declarations stop those readers when a dependency is withdrawn.
`preposition` also declares and reads `factors`. Replacing a policy row therefore
changes its internal readers as well as the compatibility import path.

The code each module held before the move stayed in its old package as
`legacy_<module>.py`, and every call the test suite made into a plugin was also
made into the legacy function: the two had to agree on the value (floats
exact), the error and the state of their arguments. The legacy modules and that
comparison were removed on 2026-10-12, before `add_alpha`, `preposition` and
`bar_signals` had run in a production brief; the last comparison was a replay
of the stored 2026-10-12 brief context and the 28 stored bar series. The
plugins are the only implementation.

Removing the second implementation removed the comparison with it. What
checks these modules now:

- the four signal sources have recorded outputs (see *Recorded outputs*
  below), compared exactly on every run of the suite;
- the six policy modules (`add_policy`, `add_alpha`, `left_side`, `add_side`,
  `preposition`, `intraday_policy`) and `signal_panel` have their own unit
  tests and nothing recorded. A change that those tests do not exercise is no
  longer caught by a second copy disagreeing.

### A row that fails

A workspace with no file, or no `live` list, runs the shipped rows. A `live`
list that is present and malformed is an error at first use.

Rows are mounted together when the first service is read, and they fail one at
a time. A row whose module does not import, whose config is refused, or whose
declaration is incomplete is recorded with its error; the others are mounted
as if it were not listed. Reading a service that row would have provided
raises and names the row and the error. So does reading the service of a
plugin that declared, in `inject`, that it needs the failed one: it is left
waiting. A reader of any other service is not affected.

This does not cover a plugin that imports a sibling module directly:
`add_side` imports `add_policy`, so if `add_policy` does not import, neither
does `add_side`, and both rows fail.

`plugin_host.live.health()` lists every row as `mounted`, `waiting` or
`failed`, and `ops/system_check.py` prints it as `live plugin rows`. A reader
that asks for a missing service still fails loudly: nothing falls back to
another implementation.

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

| `ctx.on()` / `ctx.emit()` | `ctx.on(event, handler)`, `ctx.emit(event, payload)`, module-level `emits = (...)` | a listener is an effect; an emitter names its events as it names its services |

A plugin is any importable module with `apply(ctx, config)` and, optionally,
`name`, `inject`, `emits` and `SIGNAL_SOURCE`. `ctx.get()` refuses a service
the plugin did not declare, and `ctx.emit()` an event it did not declare.

### Events

Dispatch is synchronous: `emit` calls every listener in the order they
registered and returns their answers. A listener's exception reaches the
emitter. That is the whole of it; Cordis's `waterfall` and `bail`, async fibers
and scoped services are not implemented, because every path that mounts
plugins is one bounded, single-threaded process with nothing to await.

Services are pulled: a plugin can be asked, and cannot be told. Events exist
for the one place that needed telling. The lab announces two things to
whatever is mounted beside it:

| Event | When | A listener may |
|---|---|---|
| `strategy-lab/proposal` | before a proposal is written to the ledger | observe it, or raise to keep it off the record |
| `strategy-lab/registration` | before a cleared candidate's parameters are registered | observe it, or raise to refuse the registration |

A listener can refuse and cannot grant. The lab's own checks run whatever a
listener answers, so no plugin can make the lab register something its gate
did not clear. No listener is shipped.

## Signal sources

A signal source is a plugin whose readings reach a decision. Each carries a
module-level `SIGNAL_SOURCE`, and a row marked `"signal_source": true` is not
mounted unless that declaration passes `plugin_host/declarations.validate`.
Eight are shipped (`clawock strategy-lab sources` lists them):

| Row | Family | Reads | Without its inputs |
|---|---|---|---|
| `factors` (live) | `factor` | daily bars from `daily_bars` (forward-adjusted) or `memory/bars` (raw) | `signals()` is `None` below 30 usable bars, `short_history()` below 20; above that an unmeasurable field is null |
| `daily-bars` (live) | `technical` | Tencent daily OHLC, qfq or raw per the row's adjustment; no volume | a failed fetch is an empty list with the reason on stderr; invalid price rows are dropped; old numbers are never served |
| `bar-signals` (live) | `technical` | daily bars and the index of the session | an undefined estimator is null, never zero; the two moments are left out of the row |
| `preposition` (live) | `technical` | latest completed-session bars of the held names from `memory/bars` (raw), the `factors` service, and the authorised policy in `config/preposition-policy.json` | a name whose bars are missing, stale or suspect is `unavailable` with the reason; an unmeasurable field is null and its setup is refused; old numbers are never served |
| `rsi` (research) | `strategy` | closes up to the signal session, `period` and `direction` from the row | null below `period + 1` closes; the name is not ranked that session |
| `sentiment` (live) | `sentiment` | `sentiment.json` and `influencer_feed.json`, produced off-host | the reading is empty and `status` says `missing`, `stale` or `unreadable` |
| `morning-scans` (live) | `sentiment` | `macro.json` and `em_news.json` for the brief; every scan file as a document for the other readers | the same four statuses; a file that cannot be parsed has no payload |
| `strategy-scores` (live) | `strategy` | `memory/bars`, the research rows and the lab record | `status: unavailable` with the reason |

The shape is the same for every family:

```python
SIGNAL_SOURCE = {
    'id': 'factors',
    'family': 'factor',            # factor | technical | strategy | sentiment
    'summary': '...',
    'inputs': [{'name': 'bars', 'what': '...', 'source': '...'}],
    'outputs': [{'field': 'rsi14', 'unit': 'index 0-100',
                 'window': '14 sessions, Wilder smoothing',
                 'missing': 'null below 15 closes'}],
    'missing': {'policy': 'null',  # null | omitted | refused
                'detail': '...', 'serves_stale': False},
}
```

Every output states its unit, its window and what it holds when it cannot be
measured. `missing.serves_stale` must be `False`: a source may answer null,
leave the reading out or refuse, and none of the three policies is "the last
value". `clawock strategy-lab sources` prints every mounted declaration.

One shape serves the four families because a reader asks the same three
questions of each. What differs between them is in `inputs` and in the
service's own methods, which the declaration does not try to describe.

The declarations are checked against what the code returns:
`tests/test_signal_sources.py` holds the factor row and the estimator row to
exactly the declared fields, and to the declared nulls on short series.

### Sentiment

The attention scan (`market_data/sentiment.py`) and the statement radar
(`automation/influencer.py`) run off-host and commit a file each. They stay
where they are: they are scheduled producers, not part of a composition a
brief mounts. The plugin is the other end, the read that decides whether a
file can be used today.

It has an interface of its own rather than a view of the old module. The
eight migrated modules each had many readers and a wide surface, so keeping
their import paths was the smaller change. This lane had two call sites and
one property worth a contract: an answer of `{}` could not say whether the
scan found nothing, did not run, or was too old. The service returns `status`
beside the reading. `brief_preflight` keeps its two function names, calls the
service, and prints the line and appends the issue it always did.

A reading older than `stale_after_hours` (36) is not served; the age is the
payload's own `generated_at`, never the file's mtime. Exactly 36 hours is
accepted; 36 hours and one second is stale. Exactly two hours ahead is tolerated;
further ahead or an unreadable timestamp is stale. Both configured age limits
must be positive finite numbers.

36 hours is longer than a trading day, so `macro()` also asks the trading
calendar (#2988): when a market's newest index close (HSI/HSTECH for HK;
VIX/SPX/Nasdaq for US, each row's own `as_of`) is older than
`sessions.latest_completed_session` for that market at read time, the snapshot
is stale and `detail.sessions_behind` names the market. A market with no dated
index row is judged by the clock alone. Every served row carries its `session`.
The brief omits a stale snapshot without an issue, and the rendered 大盘速读
then prints no readings line.

A failed statement source contributes no retained items. A failed relevance
filter publishes an empty feed with `llm_filter_status: failed`; the sentiment
reader also rejects older `failed_kept_previous` payloads and removes items
marked `retained_from_previous`. It reports source gaps in `degraded` rather
than presenting an old score as a current observation.

### Scan files

Six files are left by scheduled jobs and read by production paths: macro,
Eastmoney news, the attention scan, the statement radar, the US news digest
and the news evidence graph. The `morning-scans` row is the one read of them.
`scans.path(workspace, name)` is where each lives, and `scans.document(path)`
answers `ok` with the object, `missing`, or `unreadable` with the reason. A
file that cannot be parsed has no payload.

Before this row each reader decided for itself, and they disagreed: the
brief's macro loader reported whatever exception it ran into, the intraday
lane said `unreadable`, and the evidence graph recorded any file that existed
as `loaded`. They now give the same answer about the same file.

Freshness stays with the reader, because the readers differ on purpose. The
brief refuses a scan older than `stale_after_hours`; `scans.macro()` and
`scans.em_news()` apply that rule and do the brief's trimming. The intraday
lane judges each source against the session's open and reads documents only.

Not rows: the producers themselves (`market_data/sentiment.py`,
`market_data/macro.py`, `automation/influencer.py` and the others), which are
scheduled jobs, and `harness/_harness_common.GHA_DATA_FILES`, which is a list
of git paths to sync and not a read.

### Recorded outputs

`tests/fixtures/signal_sources/` holds three daily series and the two scan
files, copied from the workspace on 2026-10-12, and `goldens.json`: the factor
row at eight history lengths, the estimator row at four sessions, the RSI
score over the whole registered grid, and both sentiment readings. The suite
recomputes them and compares exactly, floats included. A deliberate change to
a source re-records the file (`CLAWOCK_WRITE_GOLDENS=1`), and the diff is the
statement of what moved.

Recording them found one thing the legacy comparison could not have: the
factor row depends on the interpreter. Python 3.12 made `sum` of floats
compensated, and a 20-session average that lands on a rounding boundary reads
one unit in its third decimal differently under 3.11. In the three recorded
series, 11 `ma20` cells do. The desk host and CI run 3.12 and the package still
installs on 3.11, so the file records both: `outputs` for the compensated sum, and `naive_sum` for the
cells that differ without it. The suite checks the interpreter it runs on and
the left-to-right sum on every run. The arithmetic itself is unchanged.

## Writing a plugin outside this repository

A row's `module` is an import path, so a plugin can be any installed package.

1. Write a module with `apply(ctx, config)`. Publish a service with
   `ctx.provide(name, service)`; name the services it reads in `inject` and the
   events it emits in `emits`. Register anything else through `ctx.effect` so
   that unmounting undoes it.
2. If its readings reach a decision, give it a `SIGNAL_SOURCE` and mark the row
   `"signal_source": true`.
3. Install it into the environment clawock runs in and add the row:
   `{"id": "my-source", "module": "my_package.source", "config": {...}}`.
4. `clawock strategy-lab list` shows whether it mounted and what it waits for;
   `clawock strategy-lab sources` prints its declaration.

What mounting does not give it:

- The research composition is mounted by `strategy-lab` and by the live
  `strategy_scores` reader. The latter reads registered scores and the historical
  lab ledger, never adopts candidate parameters or authorizes a trade.
- A strategy's score is ranked by the optimiser on history cut at the signal
  session; the plugin never sees a later bar.
- An optimiser's proposal is written through `strategy_lab/ledger.py`, which
  applies the boundaries below whoever produced it.
- A live row replaces what a production path computes. Adding or changing one
  is an edit to `config/strategy-plugins.json`, reviewed like any change to
  configuration; nothing mounts a live row on its own.

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

The evaluator hands a strategy only history up to its signal session. This
prevents accidental look-ahead through the scoring interface; it does not restrict
what trusted Python code could read from the filesystem.

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

The model is `config/cost-model.json`: a conditional account commission, sourced tax/fees and half an
assumed spread per side, no impact. Sized fills now use `costs.fill`, which applies minimum commissions and the
sourced regulatory tariff snapshot. Ranks use the config's explicit reference
notionals/share price and the more expensive side, including tax unless a ticker
has a verified exemption; they remain a proxy rather than an execution backtest.
Commission is the account's conditional monthly-allowance scenario. See
[the research cost contract](../design/intraday-strategy-research.md).

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

### How far the loop goes

The chain that runs every morning is: the optimiser searches the declared
grid, the registered gate judges the result, live alternates may object, the
ledger records the verdict, a cleared candidate is registered, and every later
run scores that registration on sessions it had not seen.

`clawock strategy-lab evolution <name>` reads that record back in order: each
run's verdict, what changed against the run before, each registration and its
score so far.

Both ends of that chain are attached.

**A proposed row edit.** The `promoter` row (`strategy_lab/plugins/row_edits.py`)
reads each registration's prospective score after every scheduled run. When
a registration whose parameters differ from the row's has at least
`min_prospective_sessions` (60) scored since it was registered, a bootstrap
interval of its mean rank IC above `prospective_ic_ci95_lower_gt` (0), and a
latest verdict that survives without the single-source names (below), the lab
writes one row to `memory/strategy-lab/row-edits.jsonl`: the parameters to move
from and to, the evidence, each check, `status: proposed` and
`live_permission: false`. `clawock strategy-lab row-edits` lists them. The lab
has no code that applies one; applying it is an edit to the row in
`config/strategy-plugins.json` that someone reviews. The two thresholds may be
raised in the row and not lowered below `boundaries.PROMOTION_FLOOR`.

**A production reader.** The live row `strategy-scores` scores stored series
only when their latest bar matches their market's latest completed session under each strategy's *registered* parameters, ranks
the cross-section, and attaches the lab's standing: latest verdict, whether it
survives the coverage check, each registration's score since, and proposed
row edits. The brief's preflight puts the held names' rows in the context's
`research` bundle. Missing, stale and unscorable requested names have null score and rank plus a
reason, and do not enter the ranking. An empty bar store is unavailable. The
returned `measurement` is each strategy's own declaration of score units and
window. Its historical lab standing is read from the same requested workspace
as its bars. It is a reading with `live_permission: false`; no add, cut
or size is computed from it. Because it reads the registered parameters only,
a candidate changes what production sees on the day the row is edited and not
before. The research rows are mounted when it is first read, so a research
plugin that does not import leaves this reading `unavailable` and every other
live row untouched.

What is still a person's step is the edit itself: reading the proposal,
changing the row, and review.

### Coverage sensitivity

`adjusted_bars` serves two kinds of name: those the provider answered
adjusted, and those it answered raw because its own record holds no corporate
action for them. The second kind rests on one provider. When a source reports
both, each proposal also carries `coverage_sensitivity`: the same search on
the adjusted names alone, with its status, interval and `verdict_survives`.
It is recorded beside the registered verdict, which it does not change. A failed
coverage check blocks the promoter from proposing a row edit.

On 2026-10-12 `rsi` was a candidate on 28 names (rank IC interval
[0.0171, 0.1117]) and was registered as momentum / 28. On the 16 adjusted
names alone the same search is refused, with an interval that spans zero. The
candidate depends on the 12 names with no action on record.

## Boundaries

### Trust and enforcement

These are in-process Python plugins, running with the host's filesystem and
import permissions. The kernel is not a sandbox. `inject` and ledger validators
constrain supported interfaces, not arbitrary Python, direct file writes or
monkey-patching. Install only trusted modules. The README's “no row can” claims
refer to ownership of the supported decision/settlement path, not isolation from
hostile code: reference prices, settlement outcomes and mandatory decision-ledger
writes have no plugin extension point. A research proposal is a separate record;
`optimize --no-ledger` does not bypass the production decision ledger.

The ledger checks `proposed`, `live_permission: false`, registrations and the
non-plugin promotion floor on every proposed-row write. It does not certify a
plugin's submitted evidence independently against bars. Changing that trust model
would require a separate process/permission boundary and independent replay.


`strategy_lab/boundaries.py` holds what the lab may never write down. It is
not a plugin and no row turns it off. `ledger.append` and `ledger.register`
apply it on every write, and `strategy-lab verify` (and the end of every
`record`) reads the files back and applies it again.

| Boundary | Where it is enforced |
|---|---|
| a proposal and a registration say `live_permission: false` | `boundaries.check_proposal`, `check_registration`; `verify` |
| `status` is the registered gate's verdict and nothing else | `check_proposal` |
| an alternate gate is never binding; a live one may only object | `check_proposal`; `walkforward._alternates` at mount |
| a live alternate may only add a check or tighten one | `walkforward._alternates` at mount |
| a row may tighten the registered gate and never lower it below `walkforward.FLOOR` | `walkforward.apply` at mount |
| a candidate was measured on bars that say they are adjusted, when the gate asks | `check_proposal`; `verify` |
| a registration belongs to a cleared candidate and carries its parameters | `check_registration`; `verify` |
| a row edit is only ever `proposed`, for a registration, on at least `PROMOTION_FLOOR` of prospective evidence, and not for a verdict that fails the coverage check | `check_row_edit` in `ledger.propose_row_edit`; `verify`; `promotion_thresholds` at mount |
| the production reader scores registered parameters only | `strategy_scores.read`; `tests/test_strategy_plugins.py` |
| a prospective score counts sessions after the registration only | `check_proposal`; `verify` |
| the lab writes no row and no live service | `tests/test_strategy_plugins.py`; `tests/package_edges.txt` prohibits production imports; the host mounts `strategy_scores` by name |

Lowering a floor is a change to `walkforward.py`, reviewed as code. A config
row cannot do it.

## Ledger

`optimize` and `record` append one row per proposal to
`memory/strategy-lab/ledger.jsonl`: status, failed checks, every alternate's
verdict, `live_review`, `prospective`, `coverage_sensitivity`, the measured
intervals, and the digest and basis of the bars served. `optimize --no-ledger` skips it. The file sits
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

## Intraday research service

The research-only `intraday-reversion` row provides `intraday_reversion.replay`.
`clawock strategy-lab intraday-replay <session.json>` sends a complete five-minute
session through the explicit research facade. It returns sized net-of-cost
round-trip evidence, never live permission or a daily optimiser registration.
Its bar contract, limits and LLM/presentation roadmap are in
[the design](../design/intraday-strategy-research.md); source research is in
[the report](../research/intraday-strategies.md).
