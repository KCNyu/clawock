# Harness architecture

clawock is an agent-native decision-workflow plugin kit backed by a verifiable
harness. It packages reusable skills, tool contracts and decision workflows for
external agents. It is not an agent orchestration framework: it does not
implement model routing, a ReAct loop or conversation memory. The external
agent/runtime remains complete in itself.

The runtime is intentionally external. OpenClaw, Hermes, Claude Code, Codex,
LangGraph or another runner may own the conversation, model and tools; clawock
calls clawock for workflow steps, certified input, deterministic reconciliation,
validation, outcome evaluation and publication receipts.

A generation is the correlated audit unit emitted by one workflow run, not the
product itself. The product-level loop is evidence → debate/workflow → decision →
execution/outcome → bounded, reviewable improvement proposal.

## Ownership

| Layer | Owns | Current location |
|---|---|---|
| Plugin/harness core | portable skills/workflows, generation-pinned artifact contract, validation/reconciliation, context assembly, tool schemas, evaluation contracts | `src/clawock/` + portable skill/workflow packages (in progress) |
| Profile | portfolio data, schedules, policy values, selected skills/persona, delivery targets and presentation resources | root data + `config/profiles/` + referenced resources |
| Runtime adapters | conversations, scheduling, delivery, run history | OpenClaw today; provider interfaces in `src/clawock/providers/` |
| Lifecycle runtime | market refresh, `.tmp` artifacts, publication, heartbeats and watchdogs | `src/clawock/{harness,automation}/` in the root wheel |

Reusable investment strategies remain product code under `src/clawock/decision/`,
even when the first consumer is the live KCNyu desk. Package lifecycle modules
bind those strategies into phases and provider-backed delivery; profiles only
select values and resources. The full provider → strategy → lifecycle rule is
documented in
[`product-profile-operations.md`](../reference/product-profile-operations.md#evidence-strategy-and-profile-rule).

The public CLI is the stable driver boundary:

```text
clawock init <workspace>
clawock workflow list|show|install
clawock run prepare --workspace <workspace>
clawock run publish --workspace <workspace> --request <json> --artifact <name=path>
clawock context audit|assemble|compare|verify
clawock brief preflight|postflight
clawock report preflight|postflight
clawock intraday preflight|postflight
```

`init` and `run` are package-native and work from an installed wheel outside the
repository. The control direction is external agent → clawock, like an
agent-native business CLI. `run prepare` emits certified input; the calling agent
keeps its own model, conversation, memory, skills, tools and repair loop; `run
publish` validates/reconciles its files and atomically emits generation-pinned
artifacts plus a receipt. clawock never launches the agent.

`clawock workflow install investment-decision --workspace <workspace>` exports
the package-owned pack to `<workspace>/.agents/skills/investment-decision` as a
standard Agent Skill (`SKILL.md`, progressive references and assets). Current
OpenClaw also [discovers project-agent skills](https://docs.openclaw.ai/skills)
from `.agents/skills`; other
skills-compatible runtimes can consume the same directory without a fork. The
installed skill tells the current agent how to call the CLI—it does not delegate
to a clawock-owned model.

The first shipped workflow pins its ID, semantic version, whole-pack certificate
and bounded parameters into the prepared request. Its deterministic validator
requires supporting and opposing evidence, linked bull/bear cases, thesis
invalidation conditions, a bounded action, confidence provenance and exact
order/FX arithmetic. A prompt cannot waive those gates.

Version 1.1 adds the bounded feedback loop without turning clawock into an
agent. An observed outcome is source-linked and reconciled across price and FX;
the evaluator reports a direction-adjusted basis-point result with an explicit
not-realized-P&L caveat. That evaluation, or a rejected validation receipt, can
anchor a proposal that changes only parameters already bounded by the pack.
Proposal review certifies an exact hash, apply records before/after overrides,
and rollback refuses to overwrite later drift. No command launches a model,
rewrites a skill, or lets a proposal accept itself.
The shipped parameters govern evidence/provenance strictness only; they do not
add or tune factors, catalysts, signals, entries, exits or portfolio rules. The
calling runtime's existing investment strategy remains the decision source.

The live workflow phase commands dispatch directly to package-owned lifecycle
modules selected by a declarative profile. The wheel contains the complete
implementation but no user's portfolio or generated state.

## Add-side strategy: one owner, three entries

The add side (evidence tiers, triggers, tranche sizing) has one implementation.
The policy **data** is `config/add-alpha-policy.json`; the **code** is pure
functions under `src/clawock/decision/` that read no file, clock or network —
each caller loads the policy and the context it already holds and passes them in.

| Piece | Owner | Consumers |
|---|---|---|
| defaults for omitted keys, entry profiles, per-tier size, tranche sizing | `decision/add_policy.py` (`READ_DEFAULTS`, `ENTRY_PROFILES`, `read_params`, `tier_terms`, `tranche_plan`) | brief packet, brief opportunity read, intraday add-side read |
| evidence families and authority tier | `decision/add_alpha.py` (`classify_authority`, `confirmation_setup`) | brief packet; `evaluate-add-alpha` walk-forward |
| opportunity radar and the three-state reads | `decision/add_side.py` (`radar`, `read_through`, `read_rows`) | `brief_preflight._opportunity_reads` (entry `brief`), `intraday_preflight` (entry `intraday`) |
| left-side scale-in ladder (rungs under the 20-day high, MA200 permission, invalidation) and its gates, **observe mode** | `decision/left_side.py` (`ladder`, `observe`, `record_history`); rule data `config/left-side-policy.json` | both radars (`left_policy`), brief packet `quant.left_side`, `assets/data/left_side_history.jsonl`, `evaluate-add-shapes --campaigns` |
| setup detection over bars | `decision/signals.py` (`compute_signals`) | quant refresh, both radars, `evaluate-add-shapes` |

Entries differ only through `add_policy.ENTRY_PROFILES` and their inputs, never
through a harness branch or a second threshold:

| Parameter | `brief` | `intraday` |
|---|---|---|
| `close_confirmed` (wording of a breakout read) | `True` — settled bars | `False` — live print, close pending |
| price series | `memory/bars`, leveraged products read through their registry `signal_symbol` when it has bars (`add_side.read_through`) | the slot's cached bars for `signals.universe_details` (same read-through) |
| `information_lane` (graded news into `read_rows`) | no — the brief writes the morning files; its decision path uses the evidence graph via `classify_authority` | yes — `information.summary` |
| `anomalies` / `mover_news` | no | yes |
| `leveraged`, `policy` | from the registry / the policy file | same |

A threshold only one entry should apply belongs in the policy file as a key, not
in a caller. Parity is pinned by behaviour, not by searching source:
`test_both_readers_build_the_same_radar_from_the_same_signals` and
`test_the_entries_differ_only_in_how_sure_the_close_is`.

### Left side (observe mode)

kcn 2026-09-26 「我个人偏左侧交易…不能只有右侧确认」, and 2026-09-27 「还是要加上，
只是看怎么用，不可能只有单边右侧交易是好的」: the direction is settled (the 09-27
rejections on #2005/#1968 are withdrawn). What follows is the shape it runs in.

**Live form: `mode: observe`.** When a held, non-leveraged name closes at least
`min_depth_atr` ATRs under its prior 20-day high while above MA200, both entries
print a `wait` row with `kind: left_scale_in`, the first rung and the
invalidation (`test_both_entries_read_the_left_ladder_as_an_unsized_wait`); the
brief packet records `quant.left_side` — rungs, invalidation, MA200 floor and the
first gate that would hold it back (`leveraged_excluded`, `thesis_unrecorded`, `thesis_not_intact`,
`negative_information`, `peer_laggard`, or none) — and never adds it to
`technical.setups`, so it cannot size or authorise
(`test_left_side_is_observed_and_recorded_never_sized`). Every brief appends one
row per date to `assets/data/left_side_history.jsonl`, a quiet day included.
kcn may trade the printed ladder at kcn's own discretion; the system gives no size.

Why this shape and not a sized one (run card `add_campaigns-20260927-12aa143a`
in `memory/backtests/`, 27 Tencent names, split 2025-07-01, non-leveraged OOS):

| Measure | Value | Reading |
|---|---|---|
| left alone, per unit deployed | 0.64% vs always-in baseline 1.70% | no timing edge from price alone |
| daily P&L correlation left↔right² | 0.57 (IS 0.60; monthly 0.77) | same trades, not a hedge |
| left's beta on right / alpha after beta² | 0.78 / −0.72% of book a year at a 1% unit | more of the right side, slightly worse |
| Sharpe hurdle `corr × Sharpe(right)` vs Sharpe(left)² | 0.62 vs 0.42 (IS 1.33 vs 1.28) | adding left lowers risk-adjusted return |
| right + left at weight 0 / 0.25 / 0.5 / 1² | Sharpe 1.08 / 1.00 / 0.91 / 0.79; drawdown −1.79 / −2.47 / −3.30 / −5.45% | P&L rises only by taking more risk |
| months right lost (7)¹ | left lost too, −5.87% of book | amplifies right's bad months |
| per rung, unit return to exit¹ | IS 3.6 / 3.9 / 0.19%, OOS 1.56 / 0.23 / −0.69% | the third rung is the weakest in both halves |
| five 3-month walk-forward folds, left mean¹ | 7.89 / −0.80 / −4.10 / 6.10 / 0.86% | regime-dependent |

¹ One-off analysis on the same series, not in the card.
² From the `left_vs_right` block, which `evaluate-add-shapes --campaigns` gained
later the same day (#2040); the card predates it and holds only `families`, so
these rows are not in it. `clawock evaluate-add-shapes --campaigns --source tencent`
prints the block again, on the data of the day it runs, not these exact figures.
The unmarked row and the figures quoted below are in the card's `families`
(#2185).

The combined family's OOS interval turning positive (+0.05% lower bound, 401 vs
172 campaigns) is more campaigns pooled into one mean, not diversification. The
`proposed_sizing` row is a linear rescale of fixed units and is not a tradeable
forecast. The one plausible source of an edge the price test cannot see is the
packet's thesis / information / peer gates, which have no point-in-time history
before 2026-07/08; they can only be measured forward, which is what the history
file is for.

Forms not taken, and what each costs:

- *Joint budget with the right side, allocated by marginal contribution* — the
  allocation this evidence gives left is zero; taking it would be the rejection
  again under another name.
- *Separate small sized family now* — adds right-side beta with negative alpha
  and unreplayed gates; small size bounds the loss but not the fact that it is
  unsupported.
- *Narrow gate opened live, gate measured afterwards* — the gate is the
  hypothesis; sizing before it has a sample commits money to the hypothesis.
- Cost of `observe`: no system-sized left trade until the sample exists, and
  kcn's own left trades are outside the ledger's campaign ids.

Still rejected, not reopened: the MA200-free deep dip (`left_no_ma200`, OOS
drawdown −14.93% of book), the left rule on daily-reset leveraged products
(negative in both halves), and right-side pyramiding (marginal unit no better
than random entry).

**Pending kcn decision** (recommended values, not applied): switch
`left_side.mode` to `authorize` once `left_side_history.jsonl` holds at least 20
gate-passed ladders whose first rung filled, their 20-session mean return per
unit is above the always-in baseline over the same dates, and gate-passed beats
gate-blocked; then authorise **rung 1 only** (rungs 2–3 stay printed, not sized),
non-leveraged, at 0.25% of the market book per campaign inside the existing
`exploration_max_book_pct`, not in addition to it. Each number in that sentence —
the 20, the rung count, the 0.25% and the shared cap — is kcn's to set. The
left terms live in `config/left-side-policy.json`, not in
`add-alpha-policy.json`, because that file's hash is the exploration campaign id;
editing it would reset every one-tranche-per-policy count.

## Intraday decision and delivery boundary

The full contract — context layering, card blocks, workflow ownership,
objective and compliance gates — is [`intraday-agent.md`](intraday-agent.md).

The preflight gives the model its complete decision context. It includes every
open plan (including zero-share watch decisions), watch levels, all held-name
peer scans, source status, setup and T+0 reads, prior semantic state, a compact
all-holdings sweep, and soft candidates. The 3% anomaly threshold guarantees an
alert; it does not decide the model's agenda. Soft candidates include 1.5–3%
moves and names near the existing 20-day radar level. The model judges which
candidate matters, how primary evidence changes the thesis, and how plans and
strategy metadata constrain an action. Brief WeChat copy is a separate output
constraint. Reducing noise means fewer user wake-ups, not fewer decision inputs.

A full card follows a fixed layout contract (the block list lives above
`compose_card` in `intraday_preflight.py`; `test_card_layout_contract` and
`test_preflight_main_never_rewrites_the_analyzer_table` enforce it): title, a
P0 line only when one newly fired, the 变化 line, `⛔ 数据降级` lines
(unverified quotes said once, with since when the same names have been
carried), then the analyzer's market strip, book line and holdings table
**byte for byte**, one `↑` pointer line naming the rows with a new
move/trigger, the `🔗` line setting each held leveraged leg against its
underlying's move and the gap in pp, the signal block with signals already
delivered this session folded into one `今日已报、仍在` line, the candidate
sections, the model's `▎我的看法` after the whole data block, and advisory
checker findings last. `⛔` is only data
health and `⚠️` only the analyzer's signal header. All of this is copy only:
the model still reads the full `signals_detail`, `source_signals_detail`,
`full_holdings` and `quote_coverage`.

The shared HK/US delta compares stable condition identities, including the
first appearance of a soft candidate or a breach that trading day, plan status and
source health. Breaches compare as the session's seen set, so a ticker flickering
across a bucket edge back to a state already delivered today stays quiet. The first session slot, a material condition change, or incomplete
evidence gets a full card. **The 2026-09-24 silence contract was overturned by kcn on 2026-09-25 (「全部都正常发」, as in the 2026-07-27 removal of the intraday delta gate); `always_full` is on and is final, and the silence code below runs only when that config is explicitly set to false:
every slot sends the full card; an unchanged one says `变化：无…` and its
judgment may be one honest line (`本档无实质变化…`), which is exempt from the
60-character floor, while claiming a new move on it is flagged.** With the
switch off, a healthy unchanged slot records a `no_change`
heartbeat and exact-slot marker without sending to WeChat or Telegram. A slot
with only a new soft candidate asks the model to choose whether to speak; an
exact `SILENT` response records the same audited quiet outcome. The watchdog
accepts only that matching marker; a failed postflight or missing marker
remains eligible for its normal fallback. The
`always_full` switch in `config/intraday-delivery.json` can still force every
slot's full card. Portfolio `strategy` selects declarative exception values in
`config/intraday-strategy-policies.json`; the harness has no ticker-specific
investment branch. Escalation rules name a `subject` (`holding`, or its registry
`signal_symbol` as `underlying`) rather than a ticker, so every holding that
selects a strategy is checked against its own instruments. The silent outcome is
filed in the workflow-outcome ledger as final `no_change` with
`primary_delivery=not_required`, not as a pending or failed send. The analyzer's
generic headline feed stays out of the card but reaches the model as
`headline_feed`. A future maximum silent-streak heartbeat would need its own
config and an auditable cursor; none is enabled by default.

## Live information sources

Live free news and disclosures are a harness-neutral module, not a feature of
one lifecycle (kcn 2026-09-26: every entry that writes a judgment should be able
to use them, in any combination). `clawock.evidence.live_sources` owns the
logic; each harness only chooses sources, limits and labels and decides what
reaches its model.

| Layer | Owns | Where |
|---|---|---|
| source adapter | one request through the `http` seam, parse to raw rows | `market_data/tencent_news.py` (Tencent per-symbol search: type 0 announcements for `primary_disclosures.fetch_exchange`, type 1 media for `mover_evidence`; request, HKT time and window in one place), `market_data/primary_disclosures.py` (HKEXnews, EDGAR full-text search), `market_data/live_news.py` (Google News — URL/parser shared with `sentiment.py` —, Yahoo Finance RSS, 同花顺 7×24), `market_data/eastmoney_news.py` (东财 7×24, its own throttled gateway) |
| normalisation | publisher's own time, grade from the source's class, filing noise dropped by `config/filing-triage.json`, a `cite` that says which side of the caller's `fresh_since` the item is on; output `{source, grade, title, published_at \| filed_date, url, publisher, signal, stale, cite}` and per source `{status, as_of, stale, requests, cached, items}` | `live_sources.normalize` / `collect` |
| trimming | bounded per-ticker rows for a core packet; the whole list for a reference layer | `live_sources.summarize` (caller picks `per_ticker`) |
| budgets | per-request timeout, per-source timeout, wall-clock budget, per-source concurrency, per-source request budget, cache TTL — all in `Limits`, passed by the caller | `live_sources.Limits` |

Interface: `collect(market, tickers, *, targets, names, window_minutes, now,
http, sources, limits, fresh_since, labels, cache_path, session)`. It never
raises and never waits past `limits.budget_s`; a source that fails or times out
is named in `degraded` (not fetched is never "no news"). `clawock live-sources`
is the same call as a subprocess for a preflight that runs each collector as
its own process.

| Entry | How it calls | Sources | Freshness label | What reaches the model | A failed source |
|---|---|---|---|---|---|
| intraday slot | in-process, started before the analyzer, cache per session (`memory/.tmp/intraday-live-news-<m>.json`, TTL 20 min) | all six | `盘中实时` / `开盘前旧闻` against the session open | `information.live` (4 rows a name), 同花顺 flashes merged into `market_flashes`; everything in reference `information_full.live` | `⛔ 资讯源未取到：…（不是无消息）` on the card + `information.sources` |
| brief | `clawock live-sources --market both --fresh-since last_close` as a WAVE1 node | HKEXnews, SEC full-text, Google News, Yahoo RSS | `上次收盘后` / `上次收盘前旧闻` against each market's last close | context `live_information` (bundle `evidence`); packet `information.live` per name, summary `live` (two cites) and `live_information` (source health) | in `live_information.<m>.degraded` and the packet's source health — **not** a preflight issue (an issue exits the preflight 1, which the cron reads as a failed tool); the command itself failing is an issue |
| report | in-process after the analyzer, alongside the peer scan and mover probe | as the brief | against the session open | context `live_information` (`summary`, `sources`, `degraded`) | `live_information.degraded` |

Why the brief and the report leave out the two 7×24 feeds: the brief's em-news
node already writes Eastmoney's 7×24 into `em_news.json` in the same run, and a
market-level flash scroll is what an open session watches — per-name filings and
news are what a pre-open or phase report writes about. That is the criterion
for a market-level feed: an entry takes it only if it has no 7×24 product of its
own and is read while the market trades.

Adding a source: an adapter in `market_data` (one request, raw rows, raises on
a non-answer); one `Source` row in `live_sources.SOURCES` (label, grade,
markets, scope) and its planning rule in `live_sources.plan`; its request budget
and, if slow, its timeout in `Limits`; a row in the source table of
[`intraday-agent.md`](intraday-agent.md) §6; and here, the entries that take it.
A source is added to an entry by naming it in that entry's source tuple
(`BRIEF_LIVE_SOURCES`, `REPORT_LIVE_SOURCES`; intraday takes all).

## Capabilities: one owner, any entry

Every capability below has one implementation. An entry — `brief`, `report`,
`intraday`, or a new one — composes the ones it needs and passes what differs
as arguments. It never copies a capability, and it never imports a sibling
entry's module to reach one (kcn 2026-09-26). Entry modules
(`harness/{brief,report,intraday}_*`) are glue: they choose inputs,
parameters and what reaches their model.

| Capability | Owner | Consumers | What an entry passes |
|---|---|---|---|
| analyzer run and its stdout (holdings table, signals, ≥3% movers) | `market_data/{hk,us}_analysis` via `_harness_common.run_analyze`; parsers `_harness_common.parse_signal_lines` / `parse_holdings_anomalies` / `parse_holdings_rows` | report, intraday | market |
| quote freshness (which holdings this run's fetch actually stamped) | `_harness_common.quote_coverage` over each holding's `data_source` | report (context + a `⛔` line in the block, #2176), intraday | market, portfolio path, run start |
| peer scan | `market_data/peer_scan.collect` | brief, report, intraday, dashboard, context tools | portfolio, legs |
| provenance code identity | `code_identity.git_commit` / `file_digest` | run cards, scorecard provenance | explicit workspace / file; short commit or null, sha256 prefix unchanged; `tests/test_code_identity.py` pins one owner |
| daily bars | settled raw store `market_data/bars.py` (`memory/bars`); live forward-adjusted series `decision/signals.fetch_bars` | ledger settlement, add-side radar, regime, quant refresh | symbol, count |
| history session keys | `decision/session_history.normalize_days` | setup and factor review | explicit source dates, otherwise nearby local daily-close evidence; legacy files remain unchanged |
| live news and disclosures | `evidence/live_sources` + adapters (§ Live information sources) | brief, report, intraday | sources, `Limits`, `fresh_since`, labels |
| Tencent per-symbol news/announcements | `market_data/tencent_news` | `primary_disclosures` (type 0), `mover_evidence` (type 1) | symbol, feed type, window, `http` |
| mover evidence | `market_data/mover_evidence.probe` | report, intraday | tickers, market |
| add side | § Add-side strategy | brief, intraday | `add_policy.ENTRY_PROFILES[entry]` |
| open plans and their triggers | `decision/plans` (`open_decisions_context`, `triggered_conditions`) | brief, report, intraday | leg, today, quotes |
| decisions ledger | `decision/ledger` (`load_decisions`, `write_decisions`) | brief postflight, dashboard, settlement, plans | path |
| trading-prose vocabulary | `prose_validation` (pure identifier/pipeline checks); `automation/output_validate.validate_sections(trading_prose=True)` | weekly generation/repair and harness postflights | text, label; harness preserves its advisory policy |
| placeholder / length / numeric checks | `harness/validation` (`FORBIDDEN_PHRASES`, `REPORT_CHAR_LIMITS`, `is_hard_char_limit`, `check_numeric_claims`, `categorize_issues`) | every postflight | critical keywords, `warn_max` |
| remaining-position day P&L and quote session | `portfolio/math.day_pnl` / `holding_session` | HK/US quote writers, aggregates, integrity, dashboard session labels | held shares, raw current quote, previous close, same-session fills; oldest shares consumed first on sales; realized sells stay in the realized ledger |
| two-currency book totals | `decision/book.pnl_totals` | brief preflight, plan normalization/validation, fallback card | finite HKD/USD legs, positive USDHKD; historical runtime records stay unchanged |
| brief card | `harness/brief_card.build_brief_card` (card file → plan fallback, harness-owned candidate section, `brief_url`) | brief postflight (primary send), brief watchdog (backstop), `brief_render` (link) | date, packet |
| send transaction | `_watchdog_common.send_under_claim` (mark mid-send → send → receipt → release only if the receipt landed); claim/receipt names in `automation/delivery_receipts` | brief, report, intraday postflights | claim path (None = no claim), send, receipt writer |
| per-channel send policy | `_watchdog_common.send_per_policy` | every postflight | kind, message, per-channel renders |
| watchdog in-flight wait | `_watchdog_common.wait_out_inflight` / `log_after_wait` over `attempt_still_running` | report, intraday watchdogs | refresh, budget, poll, log fields |
| regeneration window | `_watchdog_common.same_generation_window` | report, intraday watchdogs | `window_s`, `backward_s` |
| workflow outcomes | `automation/workflow_outcomes` | brief and report pre/postflights, watchdogs (`_watchdog_common`), cron heartbeat, dashboard | job, slot, stage |
| schedule contract | `scheduling.load_contract` (cron timeouts against watchdog judgement times) | ops, watchdogs, tests | — |

Parameters (windows, freshness, budgets, concurrency, timeouts, TTLs) are
module constants or a dataclass the caller passes (`live_sources.Limits`).
Per-profile values are declarative config under `config/`. None of them is a
literal inside one entry's `main`.

### Adding a capability: where it must be registered

1. Code in `src/clawock/<plane>/`. Network and file IO goes in a
   `market_data` adapter. Rules in `decision` / `evidence` take their inputs
   as arguments. An entry module holds only glue.
2. Parameters go in a module constant, a caller-passed dataclass, or `config/`,
   as above.
3. A row in the table above: owner, consumers, what an entry passes.
4. The plane's own registry, where one exists:
   - a live source: § Live information sources;
   - an add-side key: `config/add-alpha-policy.json` and
     `add_policy.READ_DEFAULTS`;
   - an intraday card block or context field:
     [`intraday-agent.md`](intraday-agent.md) status table, the
     `compose_card` block list, `context/intraday_layers.py`;
   - a brief context field: `context/brief.py` `CORE_FIELDS` (budget-checked);
   - anything that prints the brief time:
     `test_every_artifact_that_prints_the_brief_time_reads_the_constant`.
5. A send goes through `send_under_claim` with a `delivery_receipts` name. A
   watchdog holds an in-flight slot with `wait_out_inflight`.
6. Tests: one behaviour test per consumer entry. When two entries share a
   capability, add a parity test fed the same input (see
   `test_both_readers_build_the_same_radar_from_the_same_signals`,
   `test_forbidden_phrases`, `test_tencent_news`).

### Known forks still open

Recorded so nobody copies from them. Each needs either a file another
change is holding, or a behaviour decision; a refactor cannot settle it
alone.

- `intraday_preflight` imports `parse_hk_indices` from `report_preflight`, and
  both preflights carry a `collect_peers` wrapper. They differ only in the
  failure value (`{}` vs `{'_error': …}`). Both belong in `_harness_common`.
- `intraday_postflight` imports `can_silence` from `intraday_preflight`.
- `brief_preflight._fetch_hk_results_notices` builds its own Tencent
  announcement request (type 0, `n=20`) instead of going through
  `market_data/tencent_news`.
- `BRIEF_LIVE_SOURCES` and `REPORT_LIVE_SOURCES` are the same tuple, declared
  in each entry.
- `brief_preflight` nodes carry their subprocess timeouts as literals inside
  each `_node_*`. A per-node table next to `NODE_ORDER` would let
  `scheduling.load_contract` check them against the cron timeout.
- Tencent daily-kline readers: `decision/signals.fetch_bars`,
  `decision/regime.fetch_hstech` / `fetch_us`, `market_data/benchmarks`,
  `market_data/peer_quotes.tencent_closes`, `portfolio/risk`,
  `market_data/bars.fetch_tencent`, `evaluation/combined_regime.fetch`. They
  differ in behaviour, not just in spelling:
  - the window end: each one computes it (today, or the caller's), never a
    literal — a pinned end froze combined_regime's HK legs for months (#2177);
  - a non-object symbol node raises in some and reads as empty in others;
  - `portfolio/risk` prefers `day` over `qfqday` on the forward-adjusted
    endpoint;
  - transport, timeout and retry differ.

  Merging them means choosing one behaviour.
- Watchdog slot identity: `report_watchdog.marker_matches_slot` has no
  future-skew bound; `intraday_watchdog`'s rejects a marker dated more than
  `MARKER_FUTURE_SKEW_MS` ahead. The freshness and regeneration windows
  differ on purpose (hours-apart phases vs 30-minute slots).
- `decisions.jsonl` readers: `ledger.load_decisions` raises on a corrupt
  line, `plans._load_ledger` skips it, and `publish/decision_map.build`
  parses inline and raises on a missing file.

## Context contract

OpenClaw 2026.7.1 does not have one universal context allowlist. Normal chat
injects the five identity/tool bootstrap files plus `HEARTBEAT.md` and
`MEMORY.md`; isolated cron injects only the five-file runtime allowlist;
heartbeat-light keeps only `HEARTBEAT.md`; bootstrap-pending and subagent runs
have their own rules. `src/clawock/context/manifest.json` records each profile, the
lazy skill/memory capability roots, conversation-history ownership and the rule
that clawock never narrows OpenClaw's tools implicitly.

`clawock context audit` fails visibly when an injected file is missing/empty or
when moving `skills/`, `MEMORY.md` or `memory/` would silently remove
catalog/search capability. With no `--profile` it audits every profile and fails
if any one of them does — a file that only the interactive profile requires is
not covered by auditing isolated-cron alone. This is broader than comparing prompt text:
the skills catalog contains metadata rather than skill bodies, memory search can
remain available where `MEMORY.md` is not injected, and session history belongs
to the runtime rather than the bootstrap bundle.

`clawock context assemble` gives another runner the equivalent bootstrap. Skill
bodies remain lazy: the catalog is only an index, and only an explicitly selected
`skills/{name}/SKILL.md` is added. This preserves normal chat context and avoids
silently loading every skill into every run.

The runtime-required root files and capability directories must not move before
every active profile passes its parity gate. The manifest owns the portable
definition and audit gate; it cannot make an OpenClaw binary consume a different
path. The full adapter and cron cutover contract is in
[`openclaw-adapter.md`](openclaw-adapter.md).

Standalone runs instead list context files in `clawock.json`. Every document and
the assembled bundle receive SHA-256 certification in the runtime request and
published manifest. The command protocols are specified in
[`runtime-protocol.md`](runtime-protocol.md).

## Artifact contract

An `ArtifactSet` has one `generation_id`, and every member must carry the same
ID. This is the runtime-neutral seam after model deliberation: a runner may use
OpenClaw, a direct API or an interactive coding agent, but validation and publish
must reject artifacts mixed across generations.

## Workflow pack contract

Package data under `src/clawock/workflows/packs/<workflow-id>/` owns reusable
semantics:

```text
investment-decision/
├── SKILL.md
├── workflow.json
├── agents/openai.yaml
├── references/decision-contract.md
├── references/decision.schema.json
├── references/outcome.schema.json
├── references/improvement-proposal.schema.json
├── assets/decision.example.json
└── assets/outcome.example.json
```

`workflow.json` is the machine-readable discovery and parameter contract;
`SKILL.md` follows the open [Agent Skills specification](https://agentskills.io/specification)
and is the runtime-facing procedure; references and assets are loaded
progressively. Python validators remain package code so neither a runtime nor a
profile can silently edit financial or provenance invariants by changing prose.


Intraday status sidecar text normalization is owned by
`evidence/intraday_status.py`: both postflight and dashboard publication use its
160-character banner and 120-character mover limits, trimming valid text rather
than rejecting the whole sidecar for length. Postflight owns the generation timestamp;
the publisher additionally filters mover identities against the current book.
