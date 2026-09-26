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
--arg entry=<name> [--arg ticker=<T>] [--arg since=<HH:MM>]` returns one entry
of the context written by the same preflight, optionally sliced to one ticker
or a time window; without a slice it returns the whole entry (one explicit
choice; the parameter is `entry`). Entries: `signals_detail`,
`source_signals_detail`, `peer_scan`, `t0_setups`, `early_trend_candidates`,
`opportunity_radar`, `provisional_setups`, `prior_semantic_state`,
`headline_feed`, `information_full`. `mover_news`, `known_catalysts` and
`active_information_candidates` stay in the core: they attribute this slot's
movers.

### Invariants (gates)

- Every entry named in `index.references` resolves through the tool, and its
  content equals the same key in the context file on disk (the authority).
- An entry moved out of the core packet must be listed in the index; the core
  packet referencing a name the tool cannot resolve is red.
- `analyzer_block` is always in the core packet.

Gates: `test_every_reference_the_core_packet_names_resolves_to_the_same_content`
(every index entry resolves through the tool to the on-disk content, pinned to
the context_id; slices are subsets; `analyzer_block` is never a reference),
`test_judgment_packet_preserves_every_decision_field` (core ∪ references is the
whole context, disjoint), `test_mode7_named_context_fields_reach_model` (every
field the prompt names is in the core or the index).

## 4. Card blocks (what kcn reads)

Order is the contract; a block with nothing to say is omitted, never printed
empty.

| # | Block | Answers | Omitted when | Owner |
|---|---|---|---|---|
| 1 | title | which market, which slot | never | analyzer |
| 2 | `P0：…` | did a strategy escalation newly fire | no new escalation (no separate top "conclusion" line) | harness |
| 3 | `变化：…` | why this slot differs from the last delivered one | never; unchanged slots say `变化：无（与上次送达相比…）` | harness |
| 4 | `⛔ 数据降级：…` | can I trust this card's data: unverified quotes once, with `（沿用上一笔，自 HH:MM 起）` while the same names carry over in the session (`carry_quote_gap`); holdings with incomplete strategy evidence only as a pointer; T+0 / information / search faults | all sources healthy | harness |
| 5 | index strip + `📊` | market and book | never | analyzer |
| 6 | holdings table | positions | never; **bytes never change** | analyzer |
| 7 | `↑ …` | which rows have a new move/trigger (unverified rows are block 4's, not repeated here) | no such row | harness |
| 8 | `⚠️ 信号` | signals new today; ones already sent fold into `今日已报、仍在：…` | no signals | analyzer + harness fold |
| 9 | candidates | setups, trend, radar, primary information, plan triggers; the `△ SEC直连降级、镜像已检查` line only when its list differs from the last delivered card this session, otherwise one `名单未变，不再逐档印` sentence (`partial_unchanged`) | none | harness |
| 10 | `🛰️ 加仓侧：…` | the add-side read per ticker: ticker, three-state, one-line why/needs; a holding whose strategy evidence is incomplete gets the reason here (`↳` under its row, or `观望：… → 本档不给尺寸`, not a verdict) | no rows and no evidence gap | harness |
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
two payloads are equal (gate:
`test_wechat_bolds_the_new_rows_and_both_channels_carry_the_same_table_bytes`).
The watchdog's backstop resend is the plain card on both channels.

## 5. Add-side policy (kcn 2026-09-25)

- **Evidence grades**: primary disclosure > authoritative news/catalyst >
  sentiment snapshot/soft news. Each row names its grade and sources (source,
  title, time) and what evidence is missing.
- News or sentiment **can** move a read from `wait` to `candidate`; the row then
  says where the evidence came from and what is missing.
- **A fall is not a veto.** A pullback candidate needs the thesis intact,
  supporting evidence (a primary interrupt, or an information item the evidence
  graph marks `positive` — unknown direction is colour, not support), the price
  below its 20-day high but above the prior 5-day low; it carries that 5-day low
  as its invalidation and `exploration_tranche_pct` from
  `config/add-alpha-policy.json` as its size cap. A daily-reset leveraged
  product needs more than soft evidence. Only-a-breakout is not the rule either.
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
| fixable findings (identifiers, `下一触发`, stale headline without time) are handed back **once** before sending | gate (revise-once) | `REVISABLE` in postflight; `test_a_fixable_finding_is_handed_back_once_then_the_slot_always_delivers` | a banner only labels the breach on kcn's card; one rewrite removes it, and the second call always delivers so the slot is never lost |
| pipeline words (`harness`, `packet`) | prompt + advisory | `check_pipeline_self_reference` | the sentence is usually a correct read in the wrong words; failing it would cost the analysis |
| numbers come from the context | advisory | `check_numeric_claims` | cannot tell a real number attached to the wrong thing |
| add-side line matches `add_side_reads` | gate | harness renders it; `test_add_side_line_copies_every_verdict_and_sits_before_the_judgment`, `test_preflight_prints_the_add_side_read_it_hands_the_model` | the model cannot rewrite a verdict it does not print |
| `下一触发` numbers and names exist in the context | gate (escalating) | `check_next_trigger`; `test_next_trigger_is_its_own_checked_block_above_the_judgment` | a structured line looks authoritative |
| a degraded source is stated | gate | preflight `⛔` lines; Tavily `unavailable` | "no news" and "not fetched" must not look the same |
| stale information is labelled | gate (escalating) | every item carries its `cite` with `截至`; `check_stale_citation` flags a stale title quoted without it (`test_quoting_a_stale_headline_without_its_time_is_flagged`) | a 08:10 headline at 23:00 must not read as live |
| an unreadable information source is stated | gate | `⛔ 资讯源未取到` (`test_a_degraded_information_source_is_on_the_card_and_the_lane_in_the_packet`) | not fetched ≠ no news |

Compliance is measured on a fixed sample (HK 11:33 / 14:03 / 14:33, US 02:33,
one overnight slot) per violation class: block contract, unnamed mover, missing
source/time, field names or invented numbers, unstated degradation, stale shown
as live.

## 8. Status

| Part | Status |
|---|---|
| field-name gate, fold regression gate | live (#1870) |
| this contract | live (#1871) |
| core packet + reference tool | live (#1882) |
| add-side line (block 10; primary information moved to `📑`) | live (#1872) |
| `下一触发` line (block 11) | live (#1873) |
| WeChat bold per channel, `🟠` warning banner | live (#1874) |
| information lane tiers 0–1 (`information` core, `information_full` reference, stale-quote gate) | live (#1885) |
| ETF/index lookup: index aliases + sector match market flashes (`test_an_index_fund_gets_what_the_market_said_about_its_index`) | live (#1886) |
| Tavily on anomalies (`anomaly_search`, once per ticker per session; `test_one_query_per_mover_per_session`, `test_a_search_that_did_not_answer_is_on_the_card`) | live (#1887) |
| add-side policy (§5): grades, pullback candidate, discipline downgrade (`test_a_fall_with_supporting_news_above_the_5_day_low_is_a_pullback_candidate`, `test_a_pullback_needs_support_a_held_level_and_more_than_soft_news_when_leveraged`, `test_an_unfinished_risk_rule_action_downgrades_regardless_of_how_good_it_looks`) | live (#1888) |
| F15/F16 (peer activation shape; cold-start campaign id) | live (#1889) |
| F17 (cold-start sizing branch) | open for kcn (#1890) — changes SPCX's suggested size |
| revise-once gate | live (#1891) |
| one ⛔ line with since-when; strategy-evidence reason on its 🛰️ row (`test_an_unverified_gap_says_since_when_instead_of_repeating`, `test_incomplete_strategy_evidence_sits_on_its_holding_not_the_banner`) | live (#1900) |
| SEC-mirror line only on a changed list (`test_the_sec_mirror_line_prints_only_when_its_list_changes`) | live (#1901) |

First measured night (US 2026-09-25 22:03 → 09-26 02:33, 10 slots, vs the
previous US night, same classifier): judgments with field names 7/9 → 1/10
delivered (3/10 first drafts; two were sent back once and passed on rewrite);
block-contract breaks 9/9 → 1/10 (22:03, the `⚠️` banner before #1874 went
live); every slot delivered on Telegram. The HK leg is first measured on the
next HK session.
