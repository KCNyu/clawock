# Intraday agent contract

The intraday (Mode 7) agent is one slot every 30 minutes: HK 8 per session, US
10 per night in daylight time and 8 in standard time, including the overnight job
(see the generated [schedule table](../operations/cron-schedules.md)). This document is the contract every
change to it is checked against: what the model is given (ctx), what kcn is
sent (the card), who owns each step, what the system optimises, and which rules
are enforced by code rather than asked for in a prompt. It is updated in the
same PR as the code it describes; the status column says what is live.

Code: `src/clawock/harness/intraday_preflight.py`, `intraday_postflight.py`,
`intraday_watchdog.py`, `src/clawock/decision/add_side.py`; config
`config/intraday-delivery.json`, `config/intraday-strategy-policies.json`;
prompt `config/cron-payloads/intraday.md` (the thin per-market entry: market,
paths, tool and delivery plumbing) and the one shared Mode 7 body
`skills/_shared/intraday-mode7.md` with its declared dependency
`skills/_shared/intraday-status-sidecar.md`. The slot reads both shared files in
its first tool batch; the Mode 7 section of each market SKILL is a route to the
body and is not loaded by the cron. The ownership and silence history is in
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

Token count is not a constraint (MiniMax-M3.1-Flash-Preview, 1M window; a slot uses 2–5% of
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
| ledgers | harness | heartbeat, workflow outcomes, delivered-state cursor, dashboard data plane | a failed publish is its own state (`publish_failed`); watchdog delivery confirmation cannot clear it (#2234) |

### Prompt files a slot loads

| File | Role | Loaded |
|---|---|---|
| `config/cron-payloads/intraday.md` | thin market entry, rendered per job with `market` / `market_name` / `skill`: the first-batch reads, CLI lines, artifact paths, exec/poll and delivery plumbing | the cron message itself |
| `skills/_shared/intraday-mode7.md` | the one Mode 7 body for HK and US: delivery-mode branches, reading order, add-side and strategy rules, attribution, and the only text of the `下一触发` level rule | `read` in the first tool batch |
| `skills/_shared/intraday-status-sidecar.md` | sidecar schema and length contract, a declared dependency of the body | `read` in the first tool batch |
| `skills/{hk,us}-stock-analysis/SKILL.md` | interactive Modes 1–6; its Mode 7 section is a route to the body | not loaded by the slot |

The skills catalog is an index: naming a file loads nothing, so the payload
orders the reads by absolute path
(`test_every_intraday_slot_reads_the_same_mode7_body_and_its_dependency`). A rule
that applies to both markets is written once in the body; a market difference is
a line under the body's 市场差异, and strategy thresholds stay in
`holding_policies` / `strategy_checks`.

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
| `anomalies`, `signal_count` | this slot's moves and signal count; `analyzer_block` above retains the signal reason lines. Full `signals_detail` is available in the reference layer |
| `soft_candidates`, `add_side_reads` | edge candidates; add-side three-state reads (§5) |
| `information` | the information lane summary (§6): per source `as_of`, stale flag, top items; `live` — tier 2 rows per holding with the publisher's own time |
| source health | `quote_coverage`, source errors, degraded issuers |

Which layer a field is in is declared, not inferred: `context/intraday_layers.py`
lists every context field in exactly one of `CORE_FIELDS`, `REFERENCE_ENTRIES`
or `CONTROL_ENTRIES`. Run control (`card_marks`, `heartbeat`) stays in the
context on disk for postflight and delivery and is not printed to the model;
the slot it carries is `index.slot`. `add_side_reads`, `holding_policies` and
the `strategy_*` fields are core by declaration and may not become references.

### Reference layer (addressable, same generation)

`clawock tool intraday_reference --arg market=<hk|us> --arg context_id=<id>
--arg entry=<name> [--arg ticker=<T>] [--arg since=<HH:MM>]` returns one entry
of the context written by the same preflight, optionally sliced to one ticker
or a time window. `since` is **HKT**, on the slot's date; if its clock is
later than the slot, it starts on the preceding date (US overnight slots).
Offset timestamps are compared as instants; date-only, missing or unparseable
times are excluded from a since window, and remain available without `since`.
The ticker and time filters apply together. Without a slice it returns the whole entry (one explicit
choice; the parameter is `entry`). Entries: `signals_detail`,
`source_signals_detail`, `peer_scan`, `t0_setups`, `early_trend_candidates`,
`opportunity_radar`, `provisional_setups`, `prior_semantic_state`,
`headline_feed`, `information_full`. `mover_news`, `known_catalysts` and
`active_information_candidates` stay in the core: they attribute this slot's
movers.

When to fetch is a rule, not "everything, every slot": `peer_scan` for a peer
or sector divergence/rotation read (one ticker's slice; the whole entry only
for a book-wide comparison), `source_signals_detail` to trace a signal before
strategy filtering or explain a strategy conflict (ordinary signal reasons are
in the core `analyzer_block`), `information_full` to check a source, time or
original text the summary does not carry, the rest by the judgment at hand. An
entry that was not fetched is not material the prose may conclude from. The
rule is written once, in step 2 of `skills/_shared/intraday-mode7.md`.

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
whole context, disjoint), `test_every_context_field_declares_its_layer` (every
field preflight writes is in one of the three tables; run control is not in the
packet; the add-side and strategy fields are), `test_mode7_named_context_fields_reach_model` (every
field the prompt names is in the core or the index).

## 4. Card blocks (what kcn reads)

Order is the contract; a block with nothing to say is omitted, never printed
empty.

| # | Block | Answers | Omitted when | Owner |
|---|---|---|---|---|
| 1 | title | which market, which slot | never | analyzer |
| 2 | `P0：…` | did a strategy escalation newly fire | no new escalation (no separate top "conclusion" line) | harness |
| 3 | `变化：…` | why this slot differs from the last delivered one; a soft candidate first seen this slot is named with what changed about it — `首次进入观察区间`, or `进入另一观察区间（日内 x%，此前报过 … 档）` for a ticker already watched today (`soft_candidate_changes`), never as a bare category | never; unchanged slots say `变化：无（与上次送达相比…）` | harness |
| 4 | `⛔ 数据降级：…` | can I trust this card's data: unverified quotes once, with `（沿用上一笔，自 HH:MM 起）` while the same names carry over in the session (`carry_quote_gap`); holdings with incomplete strategy evidence only as a pointer; T+0 / search faults; an unread information source is its own `⛔ 资讯缺口：<source> 未取到（不是无消息）` line, without the exception class (`information_gap_line`; the labels as collected stay in `information_full.degraded`) | all sources healthy | harness |
| 5 | index strip + `📊` | market and book | never | analyzer |
| 6 | holdings table | positions | never; **bytes never change** | analyzer |
| 7 | `↑ …` | which rows have a new move/trigger (unverified rows are block 4's, not repeated here) | no such row | harness |
| 8 | `⚠️ 信号` | signals new today, in full with their reason lines | no signal is new today (ones already sent are block 10's) | analyzer + harness fold |
| 9 | candidates | setups, trend, radar, primary information, plan triggers; the `△ SEC直连降级、镜像已检查` line only when its list differs from the last delivered card this session, otherwise one `名单未变，不再逐档印` sentence (`partial_unchanged`) | none | harness |
| 10 | `▎持续状态` | standing state, plain lines without icons, in this order: `今日已报、仍在：STOP? a、b；STOP-LOSS c` (signals delivered earlier this session, the level said once); the analyzer's `📉` book line (`亏损持仓 n/m｜…`); one row per held leveraged leg (map = `t0_setups.rows.<t>.leveraged`) — `<leg>：<underlying> x% → 2x 应 y%，实测 z%，差 d pp`, the underlying's move from the holdings table, the index strip, or today's bar in the daily bars the radar fetched this slot (no extra request), written with commas in the validator's derived-figure form (a `；` would end the sentence the gap is checked in); `今日涨跌本档未取到，不算差值` when no reading exists; `↳ 行情未证实` when a leg or underlying is in block 4; rows in `leverage_legs` | nothing standing: no folded signal, risk line or leveraged holding | analyzer + harness |
| 10b | `🛰️ 加仓侧：…` | the add-side read per ticker: ticker, three-state, one-line why/needs; a holding whose strategy evidence is incomplete gets the reason here (`↳` under its row, or `观望：… → 本档不给尺寸`, not a verdict) | no rows and no evidence gap Not part of layout A: header, icon, rows and position (the last data block) are as before it (kcn 2026-10-09: 「千万不要影响到我们的加仓侧」) | harness |
| 11 | `下一触发：…` | what would change the picture next | never on a prose card | model, validated |
| 12 | `▎我的看法` | the judgment | fail-closed card | model |
| 13 | `ℹ️ 校验提示` | advisory checker findings | none | harness |

Blocks 7–9 are this slot's news and block 10 is what stands (kcn 2026-10-09,
layout A of #2805): nothing in block 10 is dropped for being old, it is only
said once and without an icon per line.

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
  as its invalidation and the exploration tranche from
  `add_policy.tier_terms` (the number the brief packet sizes with) as its size
  cap. A daily-reset leveraged
  product needs more than soft evidence. Only-a-breakout is not the rule either.
- **Discipline**: an unfinished `risk_rule` action downgrades the read and says
  why; it does not turn the lane into reject-only. A live thesis red line is
  still `reject`.
- **Left side, observe mode (kcn 2026-09-26/27)**: a held, non-leveraged name
  that closes at least 2 ATR under its prior 20-day high while above MA200
  reads as `wait` with `kind: left_scale_in`; `why` starts with
  「左侧观察(不给尺寸)」 and `needs` names the first rung and the invalidation
  (intraday stop, or a close under MA200). It never becomes `candidate` and
  carries no `size_cap`: the price rule alone did not beat holding and only
  added right-side beta, so no size exists until the forward sample does. The
  thesis / information / peer gates are the brief packet's (`quant.left_side`).
  Shape, evidence and the pending kcn decision: `docs/architecture/harness.md`
  § Left side (observe mode).
- **One implementation**: the slot and the brief build the radar with the same
  `add_side.radar` and read it with the same `add_side.read_rows`; they differ
  only through `add_policy.ENTRY_PROFILES` (owner table and parameters:
  `docs/architecture/harness.md` § Add-side strategy).
- **Bounds**: none of the three states is an order. The harness invents no
  threshold and does not rewrite the model's judgment; it supplies material and
  checks sources. Numbers that change money, thresholds or sizing are PRs left
  for kcn.

## 6. Information lane (free first)

| Tier | Path | Covers | Requests per slot | Freshness | Failure |
|---|---|---|---|---|---|
| 0 | files already written by the morning jobs: `assets/data/em_news.json`, `us_news_digest.json`, `sentiment.json`, `macro.json`, `news_evidence_graph.json`, `factor-snapshots/sentiment/<HKT-date>.json` | company news (HK), US digest, attention and headlines, macro, graded events | 0 (read only, never refetched) | source health uses file write time; each headline's cite uses its own publication time; date-only or missing time is labelled unknown and old | missing/unreadable file → `⛔` line |
| 1 | existing free fetchers: `mover_evidence` (Tencent, SEC, exchange, Nasdaq halts), Eastmoney 7×24 flashes | mover catalysts; market-level flashes | a handful, movers only (7×24: 1, fetched inside the tier 2 lane) | live | per-ticker `degraded`, never "no news" |
| 2 | live free sources through `clawock.evidence.live_sources` (table below): HKEXnews, SEC EDGAR full-text search, Google News RSS, Yahoo Finance RSS, 同花顺 7×24 | every slot, every holding (kcn 2026-09-26: 实时越多越好 — not gated on a gap) | per market: one filing query (HKEXnews or EDGAR full-text) + one Google News query per issuer or theme, and one Yahoo RSS per US issuer + the two market-wide 7×24 feeds; HK index-fund legs share one theme query (`live_sources.plan()` prints the plan for the current book) | each item carries its publisher's time: `盘中实时` after the session open, `开盘前旧闻` before it | per source on the ⛔ line (`资讯源未取到：Google新闻（1/3 超时）…（不是无消息）`) and in `information.sources` |
| 3 | Tavily (`skills/tavily-search`, `--bucket intraday`) | an anomaly's cause | only when `anomalies` is non-empty, once per ticker per session | live | `unavailable`/quota → `⛔ 源降级`, never "no news" |

Tavily's `intraday` bucket is 120 credits a month; one query every slot would
be ~400, so it is trigger-only and cached per ticker per session.

**Tier 2 sources.** The module is harness-neutral (the brief and the report
call the same `collect`; ownership, interface and how to add a source are in
[`harness.md`](harness.md#live-information-sources)). The intraday slot starts
it before the analyzer — it needs only the book — so its waits overlap the quote
refresh, and joins it where the information lane is read. Limits (intraday):
6 s a request (同花顺 10 s), 12 s for the whole lane, ≤4 concurrent requests a
source, cache per session with a 20-minute TTL (a re-run of the slot reuses its
answers; the next slot asks again; items a feed stops listing stay for the
session). Queries are per issuer and per index theme, not per holding: RKLX
asks for RKLB, three HSTECH funds share one theme query, and an index fund gets
no filing or per-symbol lookup (the HK Finnhub lesson: 15 serial requests a slot,
no item in 81 contexts).

| Source | Endpoint | Requests a slot | Budget | Freshness | Failure | Sample (2026-09-26) |
|---|---|---|---|---|---|---|
| HKEXnews 披露易 (HK) | `www1.hkexnews.hk/ncms/json/eds/lcisehk7relsdc_<n>.json` — newest 500 announcements of every SEHK issuer | 1 (a 2nd/3rd page only if page 1 ends inside the window) | 3 | `relTime` HKT, minute; routine returns dropped by the HK triage rules | `HKEXnews披露易（…）`; an empty feed is a failure (HKEX never publishes an empty list) | 02208 `2026中期報告（財務報表/環境、社會及管治資料 - [中期/半年度報告]）`, 22/09 16:33 HKT |
| SEC EDGAR full-text search (US) | `efts.sec.gov/LATEST/search-index?ciks=<all issuers>&dateRange=custom` — a different host from data.sec.gov, so it still lists the day's filings when SEC direct is degraded | 1 for the whole book | 1 | filing **date** only: `今日提交、时刻未知` (never a minute), earlier days `开盘前旧闻`; Form 3/4/5, 144, 13G dropped | `SEC全文检索（…）` | CRCL `8-K（items 5.02, 7.01）`, filed 2026-09-25 |
| Google News RSS | `news.google.com/rss/search?q=<issuer> stock when:1d` (US, `US:en`); `<中文名> when:1d` / `<index theme> when:1d` (HK, `CN:zh-Hans`) | 1 per issuer/theme | 8 | `pubDate`, publisher named in the cite | `Google新闻（n/m …）` | 00100 `MINIMAX-W（00100.HK）：9月25日南向资金减持14.37万股`（搜狐网, 09-26 04:16 HKT） |
| Yahoo Finance RSS (US) | `feeds.finance.yahoo.com/rss/2.0/headline?s=<issuer>` | 1 per issuer (US 3) | 6 | `pubDate` | `Yahoo财经（…）`; a throttle page is a failure, not an empty feed | RKLB `MISSION SUCCESS: Rocket Lab Launches 97th Electron Mission`, 09-26 09:43 HKT |
| 同花顺 7×24 | `news.10jqka.com.cn/tapp/news/push/stock/` | 1 | 1 | `ctime`; merged into `market_flashes` only when 东财 did not say it (≥0.6 title similarity is a duplicate) | `同花顺7×24（…）` | `滴滴与杭州余杭达成战略合作，探索落地自动驾驶产业应用`（人民财讯, 09-26 13:24 HKT） |
| 东财 7×24 (tier 1) | `newsapi.eastmoney.com/kuaixun/…` via the Eastmoney gateway | 1 | 1 | `showtime` | `东财7×24（…）` as before | — |

Not wired: **Reddit** — its public JSON is 403 (`market_data/sentiment.py`);
the working `search.rss` answered once and then 429 five seconds later
(2026-09-26), the morning scan measured 1/10 answered on a paced sweep, it is
retail chatter rather than news (its 7-day counts already reach the lane as
`attention`), and `docs/legal/third-party-data.md` records that unauthenticated
public access is not a substitute for a compliant Reddit Data API setup —
adding 18 unauthenticated calls a day goes the wrong way. **Yahoo for HK**
symbols — `2208.HK` answered with 2025 headlines and the HSTECH ETFs with
nothing. **财联社电报** — `cls.cn/nodeapi/telegraphList` answers 404 and the
current endpoint needs a signed query; the host took 3–10 s to connect.
Paid sources are out.

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
| alert slot names its movers and at least one new signal ticker when present | gate (escalating) | `intraday_postflight.validate`; `intraday_delta.seen_signal_identities` also drives card folding | signal identity is (level, ticker), compared with this trading session’s delivered seen set; repeated signals stay in block 10 without forced prose (#2829) |
| no field names / enum values in prose | gate (escalating) | `check_identifier_leak` | 2026-09-25 14:33 `semantic_unchanged`; an identifier is never trading language |
| fixable findings (identifiers, `下一触发`, stale headline without time, a `▎我的看法` marker that does not open a line — #2049) are handed back **once** before sending | gate (revise-once) | `REVISABLE` in postflight; `test_a_fixable_finding_is_handed_back_once_then_the_slot_always_delivers` | a banner only labels the breach on kcn's card; one rewrite removes it, and the second call always delivers so the slot is never lost |
| pipeline words (`harness`, `packet`) | prompt + advisory | `check_pipeline_self_reference` | the sentence is usually a correct read in the wrong words; failing it would cost the analysis |
| numbers come from the context | advisory | `check_numeric_claims` | explicit units apply to core and reference fields alike; `range_used_atr` is a harness-derived multiple, not a percentage; cannot tell a real number attached to the wrong thing |
| add-side line matches `add_side_reads` | gate | harness renders it; `test_add_side_line_copies_every_verdict_and_sits_before_the_judgment`, `test_preflight_prints_the_add_side_read_it_hands_the_model` | the model cannot rewrite a verdict it does not print |
| `下一触发` names and levels are subject-scoped; proposed levels within ±5% of that subject's current quote are allowed — every such line, merged into one (#2077) | gate (escalating) | `check_next_trigger`; `test_next_trigger_is_its_own_checked_block_above_the_judgment`, `test_a_second_next_trigger_line_is_checked_and_never_reaches_the_card_raw` | a structured line looks authoritative |
| a degraded source is stated | gate | preflight `⛔` lines; Tavily `unavailable` | "no news" and "not fetched" must not look the same |
| stale information is labelled | gate (escalating) | every item carries its `cite` with a time or explicit time gap; `check_stale_citation` matches the cited title, not a ticker prefix (`test_quoting_a_stale_headline_without_its_time_is_flagged`, `test_a_live_timestamped_title_does_not_collide_with_old_same_ticker_title`); the market-level reference families carry the same `cite` and are in the gate's title list (`test_market_level_reference_rows_carry_a_cite_and_reach_the_label_gate`) | a 08:10 headline at 23:00 must not read as live |
| an unreadable information source is stated | gate | `⛔ 资讯缺口` (`test_a_degraded_information_source_is_on_the_card_and_the_lane_in_the_packet`; tier 2 per source: `test_a_source_that_did_not_answer_is_named_and_the_rest_still_land`) | not fetched ≠ no news |
| a live item is labelled with its own time | gate | tier 2 cite: publisher time + `盘中实时`/`开盘前旧闻`; a pre-open live title falls under `check_stale_citation` like the morning files | a headline fetched at 14:00 may have been written at 06:00 |

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
| every context field declares its layer; run control (`card_marks`, `heartbeat`) is not printed to the model | live (#2806) |
| reference entries have stated fetch conditions; the prompt no longer asks for the whole of `peer_scan` / `source_signals_detail` every slot while calling the layer on-demand | live (#2806) |
| `signals_detail` belongs only to the reference layer; signal reasons remain in core `analyzer_block` | live (#2107) |
| add-side line (block 10b; primary information moved to `📑`) | live (#1872) |
| `下一触发` line (block 11) | live (#1873; all lines checked #2077) |
| WeChat bold per channel, `🟠` warning banner | live (#1874) |
| information lane tiers 0–1 (`information` core, `information_full` reference, stale-quote gate) | live (#1885) |
| ETF/index lookup: index aliases + sector match market flashes (`test_an_index_fund_gets_what_the_market_said_about_its_index`) | live (#1886) |
| Tavily on anomalies (`anomaly_search`, once per ticker per session; `test_one_query_per_mover_per_session`, `test_a_search_that_did_not_answer_is_on_the_card`) | live (#1887) |
| add-side policy (§5): grades, pullback candidate, discipline downgrade (`test_a_fall_with_supporting_news_above_the_5_day_low_is_a_pullback_candidate`, `test_a_pullback_needs_support_a_held_level_and_more_than_soft_news_when_leveraged`, `test_an_unfinished_risk_rule_action_downgrades_regardless_of_how_good_it_looks`) | live (#1888) |
| F15/F16 (peer activation shape; cold-start campaign id) | live (#1889) |
| F17 (cold-start sizing branch) | live (#1890) — SPCX's cold-start slice sizes to 0 shares (one share > the 3% book cap) |
| revise-once gate | live (#1891) |
| signal prose coverage and card folding share the session’s delivered identities; new levels still require prose | live (#2829) |
| T+0 `range_used_atr` is an explicit multiple source for numeric claims | live (#2828) |
| stale-title matching respects full cited titles and timestamped live duplicates | live (#2106) |
| stale-quote gate reads full morning and live ticker rows, beyond the summary cap (`test_a_stale_live_title_beyond_the_summary_cap_is_held_to_the_label_rule`) | live (#2228) |
| reference since windows compare publication instants in HKT on the slot date, including overnight wrap (`test_reference_since_uses_hkt_dates_and_combines_the_ticker_filter`, `test_reference_since_wraps_the_us_slot_across_midnight`) | live (#2229) |
| one add-side implementation for brief and slot (`add_policy`, `add_side.radar`; `test_both_readers_build_the_same_radar_from_the_same_signals`, `test_the_entries_differ_only_in_how_sure_the_close_is`) | live (#1953) |
| left-side read, observe mode (`kind: left_scale_in`, `wait`, no size; `test_both_entries_read_the_left_ladder_as_an_unsized_wait`, `test_left_side_is_observed_and_recorded_never_sized`) | live (observe); sizing pending kcn |
| one ⛔ line with since-when; strategy-evidence reason on its 🛰️ row (`test_an_unverified_gap_says_since_when_instead_of_repeating`, `test_incomplete_strategy_evidence_sits_on_its_holding_not_the_banner`) | live (#1900) |
| SEC-mirror line only on a changed list (`test_the_sec_mirror_line_prints_only_when_its_list_changes`) | live (#1901) |
| `🔗` leveraged leg vs underlying (`test_a_leveraged_leg_sits_next_to_its_underlying_with_the_gap`, `test_preflight_prints_the_leverage_line_from_the_t0_map`) | live (#1902) |
| information lane tier 2: live free sources every slot, started before the analyzer, bounded (`test_the_live_information_lane_waits_alongside_the_analyzer_and_states_its_gaps`, `test_live_items_reach_the_lane_apart_from_the_morning_rows_with_their_own_time`, `test_nothing_waits_past_the_budget`); the same module feeds the brief and the report (`test_intraday_brief_and_report_all_go_through_the_one_collect`) | live (#1935) |
| tier 0 cites carry each item's own publication time, or explicitly mark missing precision (`test_a_morning_item_uses_its_own_date_not_the_file_write_time`) | live (#2103) |
| one shared Mode 7 body + thin market entry; the market SKILL is no longer loaded by the slot (`test_every_intraday_slot_reads_the_same_mode7_body_and_its_dependency`, `test_one_mode7_body_carries_the_add_side_rules_for_both_markets`) | live (#2807 step 1) |
| intraday `required_substrings`: 32 kept, each an interface token or an instruction nothing else checks before delivery; three wording locks dropped (an explanatory clause and two field names whose presence in the packet is declared in `intraday_layers.py`). Rules stated in both the cron payload and the shared body stay in the payload, where the live cron message is compared verbatim | closed (#2807 step 2) |

First measured night (US 2026-09-25 22:03 → 09-26 02:33, 10 slots, vs the
previous US night, same classifier): judgments with field names 7/9 → 1/10
delivered (3/10 first drafts; two were sent back once and passed on rewrite);
block-contract breaks 9/9 → 1/10 (22:03, the `⚠️` banner before #1874 went
live); every slot delivered on Telegram. The HK leg is first measured on the
next HK session.
