# Intraday agent contract

The intraday (Mode 7) agent is one slot every 30 minutes: HK 8 per session, US
10 per night including the overnight job. This document is the contract every
change to it is checked against: what the model is given (ctx), what kcn is
sent (the card), who owns each step, what the system optimises, and which rules
are enforced by code rather than asked for in a prompt. It is updated in the
same PR as the code it describes; the status column says what is live.

Code: `src/clawock/harness/intraday_preflight.py`, `intraday_postflight.py`,
`intraday_watchdog.py`, `src/clawock/decision/add_side.py`; config
`config/intraday-delivery.json`, `config/intraday-strategy-policies.json`;
prompt `config/cron-payloads/intraday.md` and the Mode 7 section of both market
SKILLs. The ownership and silence history is in
[`harness.md`](harness.md#intraday-decision-and-delivery-boundary).

## 1. Objective

In priority order, and the order decides conflicts:

1. **Never a silent or empty slot.** Every open-market slot sends (kcn
   2026-09-25, `always_full: true`). A failed source, a failed check or a failed
   channel is stated on the card; it never turns into "no news" or "no card".
2. **Nothing on the card is wrong.** Every number on the card comes from the
   harness or is checked against the context; the analyzer table is sent byte
   for byte; stale information is labelled with its time.
3. **The model sees everything that could change this slot's judgment** —
   including the analyzer's own output (`analyzer_block`) — and can reach the
   rest by name. Brevity is a property of the card, never of the model's input.
4. **Signals are visible**: moves, triggers and add-side reads, in both
   directions ("跌不等于不能加").
5. **Readable card**: fixed block order, one meaning per symbol, repeats folded.

Token count is not a constraint (MiniMax M3, 1M window; a slot uses 2–5% of
it). Compliance is: a rule the model keeps breaking becomes a gate (§7).

## 2. Workflow and ownership

```
cron slot ─► preflight ───────────► model ────────► postflight ─────────► delivery ─────► watchdog ─► ledgers
             (harness,               (LLM)           (harness,             WeChat primary   (harness)
              deterministic)                          deterministic)        + Telegram
```

| Step | Owner | Does | On failure |
|---|---|---|---|
| cron slot | OpenClaw cron (`config/cron-schedules.json`, payload `config/cron-payloads/intraday.md`) | starts the turn at the slot time | watchdog judges the exact slot |
| preflight | harness | analyzer run → `analyzer_block`; signals/anomalies; plans, setups, radar, add-side reads; information lane; delta vs last delivery; soft candidates; card blocks; writes the context and prints the core packet | analyzer failure → `preflight_failed` (watchdog sends); any source failure → full card with a `⛔` line, never silence |
| model | LLM | reads the core packet, fetches references it needs, writes `▎我的看法` and the `下一触发：` line | no prose / stale prose → postflight `input_error`, watchdog sends the data block |
| postflight | harness | validates the prose (§7), assembles blocks per channel, sends, records | validation fail → data block + top banner (never empty); warn → sent with a banner |
| delivery | harness via OpenClaw channels | WeChat (primary), Telegram (mirror and backstop), each retried on its own | a failed channel is recorded per channel; the other still sends |
| watchdog | harness (`intraday_watchdog`) | checks the exact slot marker; resends the channel that did not land | WeChat-failed alert to Telegram at most once per market per day (#1861) |
| ledgers | harness | heartbeat, workflow outcomes, delivered-state cursor, dashboard data plane | a failed publish is its own state (`publish_failed`) |

The model never computes a number the harness can compute, never renders a data
block, and never sends a message. The harness never writes judgment: it does not
invent thresholds, does not rewrite the model's verdicts, and states what it
could not fetch.

## 3. Context layering (ctx for the model)

The split is by **whether the material can change this slot's judgment and
whether it dilutes attention**, not by size. Anything that can change the
judgment goes in the core packet however large it is. The reference layer is
lazy loading in the skills sense — an index in the core packet, content one
named call away — not truncation.

### Core packet (printed by `clawock intraday preflight --judgment-packet`)

| Field | What it answers |
|---|---|
| `index` | this slot's id and time, the last delivered slot, and the **reference list**: every reference entry's name, how to fetch it, a one-line description and its size |
| `analyzer_block` | the analyzer's stdout exactly — the only place signal reason lines live after the card folds them |
| `raw_wechat_block` | the card as kcn will read it (do not restate it) |
| `full_holdings` | every holding: price, day move, quote freshness, distance to plan trigger lines |
| `plan_context`, `plan_triggers`, `watch_levels` | open plans including 0-share watch decisions; triggers this slot's prices meet; the brief's watch lines |
| `holding_policies`, `strategy_*` | per-holding strategy exceptions, checks and escalations |
| `semantic_state` (seen sets), `semantic_delta`, `semantic_unchanged` | what was already delivered today, what changed since |
| `anomalies`, `signal_count`, `signals_detail` | this slot's moves and signals |
| `soft_candidates`, `add_side_reads` | edge candidates; add-side three-state reads (§5) |
| `information` | the information lane summary (§6): per source `as_of`, stale flag, top items |
| source health | `quote_coverage`, source errors, degraded issuers |

### Reference layer (addressable, same generation)

`clawock tool intraday_reference --arg market=<hk|us> --arg context_id=<id>
--arg name=<entry> [--arg ticker=<T>] [--arg since=<HH:MM>]` returns one entry
of the context written by the same preflight, optionally sliced to one ticker
or a time window; without a slice it returns the whole entry (one explicit
choice). Entries: `signals_detail` (full), `source_signals_detail`,
`peer_scan`, `t0_setups`, `early_trend_candidates`, `opportunity_radar`,
`provisional_setups`, `prior_semantic_state`, `headline_feed`, `mover_news`,
`known_catalysts`, `active_information_candidates`, `information_full` (§6).

### Invariants (gates)

- Every entry named in `index.references` resolves through the tool, and its
  content equals the same key in the context file on disk (the authority).
- An entry moved out of the core packet must be listed in the index; the core
  packet referencing a name the tool cannot resolve is red.
- `analyzer_block` is always in the core packet.

## 4. Card blocks (what kcn reads)

Order is the contract; a block with nothing to say is omitted, never printed
empty.

| # | Block | Answers | Omitted when | Owner |
|---|---|---|---|---|
| 1 | title | which market, which slot | never | analyzer |
| 2 | `P0：…` | did a strategy escalation newly fire | no new escalation (no separate top "conclusion" line) | harness |
| 3 | `变化：…` | why this slot differs from the last delivered one | never; unchanged slots say `变化：无（与上次送达相比…）` | harness |
| 4 | `⛔ 数据降级：…` | can I trust this card's data | all sources healthy | harness |
| 5 | index strip + `📊` | market and book | never | analyzer |
| 6 | holdings table | positions | never; **bytes never change** | analyzer |
| 7 | `↑ …` | which rows to look at (new move/trigger, unverified quote) | no such row; only kinds present | harness |
| 8 | `⚠️ 信号` | signals new today; ones already sent fold into `今日已报、仍在：…` | no signals | analyzer + harness fold |
| 9 | candidates | setups, trend, radar, primary information, plan triggers | none | harness |
| 10 | `🛰️ 加仓侧：…` | the add-side read per ticker: ticker, three-state, one-line why/needs | `add_side_reads.rows` empty | harness |
| 11 | `下一触发：…` | what would change the picture next | never on a prose card | model, validated |
| 12 | `▎我的看法` | the judgment | fail-closed card | model |
| 13 | `ℹ️ 校验提示` | advisory checker findings | none | harness |

Rules: `⛔` is only data health and `⚠️` only the analyzer's signal header (one
symbol, one meaning); the add-side line carries `三态都不是下单授权`; it lists at
most 4 tickers with `why`/`needs` cut to a fixed length and `…另有 N 条` beyond.
A failed check sends the data block with a `🔴` banner on top; an escalating
warning puts a `🟠` banner on top (not `⚠️`, which belongs to block 8).

**Channels.** WeChat bolds the table rows the `↑` line names as new move/trigger
(markdown `**` around each cell); Telegram always gets the plain table. The
data bytes of the table are identical on both channels: with `**` removed the
two payloads are equal (a gate).

## 5. Add-side policy (kcn 2026-09-25)

- **Evidence grades**: primary disclosure > authoritative news/catalyst >
  sentiment snapshot/soft news. Each row names its grade and sources (source,
  title, time) and what evidence is missing.
- News or sentiment **can** move a read from `wait` to `candidate`; the row then
  says where the evidence came from and what is missing.
- **A fall is not a veto.** A pullback candidate needs the thesis intact, news
  or primary support, and the price holding above an existing level; it always
  carries an invalidation level (below which the idea is wrong) and the size cap
  from `config/add-alpha-policy.json`. Only-a-breakout is not the rule either.
- **Discipline**: an unfinished `risk_rule` action downgrades the read and says
  why; it does not turn the lane into reject-only. A live thesis red line is
  still `reject`.
- **Bounds**: none of the three states is an order. The harness invents no
  threshold and does not rewrite the model's judgment; it supplies material and
  checks sources. Numbers that change money, thresholds or sizing are PRs left
  for kcn.

## 6. Information lane (free first)

| Tier | Path | Covers | Requests per slot | Freshness | Failure |
|---|---|---|---|---|---|
| 0 | files already written by the morning jobs: `assets/data/em_news.json`, `us_news_digest.json`, `sentiment.json`, `macro.json`, `news_evidence_graph.json`, `factor-snapshots/sentiment/<date>.json` | company news (HK), US digest, attention and headlines, macro, graded events | 0 (read only, never refetched) | written ~08:00 HKT; each item carries `as_of`; `stale` when written before the current session opened | missing/unreadable file → `⛔` line |
| 1 | existing free fetchers: `mover_evidence` (Tencent, SEC, exchange, Nasdaq halts), Eastmoney 7×24 flashes | mover catalysts; market-level flashes | a handful, movers only | live | per-ticker `degraded`, never "no news" |
| 2 | free public endpoints (HKEXnews, SEC full-text, Google News RSS, Yahoo RSS, Reddit JSON) | only where tiers 0–1 leave a stated gap | 0 by default | live | rate-limited, cached, timed out |
| 3 | Tavily (`skills/tavily-search`, `--bucket intraday`) | an anomaly's cause | only when `anomalies` is non-empty, once per ticker per session | live | `unavailable`/quota → `⛔ 源降级`, never "no news" |

Tavily's `intraday` bucket is 120 credits a month; one query every slot would
be ~400, so it is trigger-only and cached per ticker per session.

## 7. Compliance design: gate or prompt

A rule the model keeps breaking becomes a gate (a deterministic check in code,
with a test that goes red when the check is removed). A rule stays a prompt
when a check would cost more good reports than it saves, and the reason is
written down.

| Rule | Kind | Where | Why this kind |
|---|---|---|---|
| block order, symbols, table bytes | gate | `test_card_layout_contract`, `test_preflight_main_never_rewrites_the_analyzer_table` | the harness renders it; there is no model step to comply |
| a slot always sends | gate | `always_full` + `test_with_the_live_config_an_unchanged_healthy_slot_still_sends_honestly` | kcn final decision |
| `analyzer_block` stays in the model's view | gate | `test_the_model_packet_keeps_reason_lines_the_card_folded` | #1862 once removed it |
| alert slot names its movers and signal tickers | gate (escalating) | `intraday_postflight.validate` | naming what fired is what the slot is for |
| no field names / enum values in prose | gate (escalating) | `check_identifier_leak` | 2026-09-25 14:33 `semantic_unchanged`; an identifier is never trading language |
| pipeline words (`harness`, `packet`) | prompt + advisory | `check_pipeline_self_reference` | the sentence is usually a correct read in the wrong words; failing it would cost the analysis |
| numbers come from the context | advisory | `check_numeric_claims` | cannot tell a real number attached to the wrong thing |
| add-side line matches `add_side_reads` | gate | harness renders it; `test_add_side_line_copies_every_verdict_and_sits_before_the_judgment`, `test_preflight_prints_the_add_side_read_it_hands_the_model` | the model cannot rewrite a verdict it does not print |
| `下一触发` numbers and names exist in the context | gate (escalating) | `check_next_trigger`; `test_next_trigger_is_its_own_checked_block_above_the_judgment` | a structured line looks authoritative |
| a degraded source is stated | gate | preflight `⛔` lines; Tavily `unavailable` | "no news" and "not fetched" must not look the same |
| stale information is labelled | gate | harness renders `as_of` on every information item | the model cannot drop a label it does not print |

Compliance is measured on a fixed sample (HK 11:33 / 14:03 / 14:33, US 02:33,
one overnight slot) per violation class: block contract, unnamed mover, missing
source/time, field names or invented numbers, unstated degradation, stale shown
as live.

## 8. Status

| Part | Status |
|---|---|
| field-name gate, fold regression gate | live (#1870) |
| this contract | live (#1871) |
| core packet + reference tool | planned |
| add-side line (block 10; primary information moved to `📑`) | live (#1872) |
| `下一触发` line (block 11) | this PR |
| WeChat bold per channel, `🟠` warning banner | planned |
| information lane tiers 0–1, ETF/index lookup | planned |
| Tavily on anomalies | planned |
| add-side policy (§5) | planned |
