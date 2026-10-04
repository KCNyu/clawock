/**
 * The task chip's provider panel as data: every row it shows (a provider's
 * allowance, a live task, an ended one, a patrol round), its words, its state
 * role and its place — without React or the DOM. client.ts draws these rows in
 * dsh's sidebar; text.ts prints the same rows for a chat (OpenClaw's
 * `/dispatch-list`). One view model, two renderers: the chat reply cannot say
 * something the chip does not, or say it in other words.
 *
 * The parts a renderer draws for itself are named, not built here: a row's lead
 * glyph (`RowLead`), the fallback mark and the delivery receipts (`Fact`).
 */
import { type ProviderJoin } from './providers.ts';
import { type Translate } from './copy.ts';
import type { AgentQueue, BalanceResult, BalancesResult, DispatchTask, PatrolRound, TaskQueueResult } from './types.ts';
/** The four visual states one provider's reading can take. */
export type BalanceTone = 'ok' | 'low' | 'stale' | 'none';
/** Usage-direction colour tier of a used-percent reading. */
export type UsedLevel = 'ok' | 'mid' | 'low';
/**
 * Colour tier for one used-percent reading against the REMAINING-watermark
 * threshold (lowPct). kcn 的配色口径:已使用低 = 正常绿(--ok),逼近额度
 * 上限先黄(--warn)再红(--bad)。档位从既有 lowPct 派生,不新增配置:
 * warn at 100−2·lowPct, red inside 100−lowPct(默认 20 → 60% 黄 / 80% 红)。
 * 档位只决定颜色,绝不增删信息(kcn 反馈 #908:变红不许吃掉任何字段)。
 */
export declare function _usedLevel(percent: number | null, threshold: number): UsedLevel;
/**
 * Display projection of ONE provider's answer (test seam, like _displayEntry):
 * the chip and panel render only these fields, so the view never keeps
 * a second copy of the tone rules — the host already decided status and low.
 * The title is the whole hover story: split, quota windows, stale reason,
 * fetch time. Quota rows ('pct' unit) read as USED percent (kcn: 「已使用」
 * 比「剩余」直观), not money, and carry the second window ('周'/'本周') as a
 * muted pill suffix — both limits visible at the header without opening the
 * panel. An exhausted window gets no caption at all (kcn 反馈: 文案只会重复):
 * the reading itself says 100% and `reset` carries when it frees up.
 */
export declare function _rowDisplay(result: BalanceResult | null, t: Translate, now?: number): {
    tone: BalanceTone;
    value: string;
    sub: string | null;
    reset: string | null;
    level: UsedLevel | null;
    title: string;
};
/**
 * The one line a panel row says out loud when something is wrong — stale
 * reason, unconfigured key, insufficient money balance. A healthy number
 * earns no caption at all; null means silence. An exhausted quota window
 * is silence too (kcn 反馈): its 100% bar and reset stamp in the per-window
 * rows are the message; a caption would only replace them.
 */
export declare function _balanceNote(result: BalanceResult | null, t: Translate): string | null;
/** One provider row as the chip, the foot button and the panel render it. */
export type BalanceRow = BalancesResult['providers'][number] & {
    view: ReturnType<typeof _rowDisplay>;
    note: string | null;
};
/** A live task queued for something another task of its agent holds (the backlog patrol yields to). */
export declare const queuedFor: (task: DispatchTask) => boolean;
/**
 * Which run slot a live task holds: `SLOT=<agent>-<n>` (slots are per agent).
 * Anything else is shown verbatim under the task's own agent. (The shared
 * `slot-1..2` of the runners from before 2026-09-25, a bare number, had a
 * bucket of its own until 2026-09-27, when none was left.)
 */
export declare function _slotOf(task: DispatchTask): {
    agent: string;
    slot: string;
} | null;
export type SlotLane = {
    agent: string;
    used: number;
    max: number | null;
    tone: BalanceTone;
};
/**
 * Each agent's run slots, in the panel's order (providers.ts), limits.env's
 * agents and any agent seen holding one that limits.env does not name. A full lane with a task of that agent queued
 * is amber: that is the queue's reason at a glance. A host older than
 * slotLimits sends none: the lanes then come from the held slots alone,
 * without a maximum.
 */
export declare function _slotLanes(result: TaskQueueResult): SlotLane[];
export declare function laneText(t: Translate, lane: SlotLane): string;
export declare function durationOf(t: Translate, ms: number): string;
export declare function agoOf(t: Translate, ms: number): string;
/**
 * One live task's status phrase and its tone. One colour, one meaning:
 * 'ok' (the host's business blue) = holding its agent's lock and running,
 * 'stale' (the host's warn) = waiting for something (the lock, a slot,
 * memory, a quota reset, a retry), 'none' = neither yet (starting).
 */
export declare function _taskStatus(task: DispatchTask, t: Translate, now?: number, windows?: ReadonlyArray<{
    resetAtMs?: number | null;
}>): {
    tone: BalanceTone;
    text: string;
};
/** Keep the runner's execution verdict and the model's report in separate, named slots. */
export declare function executionText(state: string, t: Translate): string;
export declare function reportText(outcome: string, t: Translate, executionState?: string): string;
/**
 * An ended task's tone. Done is not blue (blue means running now) and not a
 * dot at all: ended rows speak in words. Not-done amber, failed red.
 */
export declare function endedTone(task: DispatchTask): BalanceTone;
export declare function patrolPhraseOf(result: TaskQueueResult, t: Translate, now: number): string;
/** The ops entry answered, and its installed copy is the repository's. '' when fine, else why not. */
export declare function opsProblem(result: TaskQueueResult, t: Translate): string;
/**
 * The chip's headline, the host badge's two parts: the label, and a count
 * (running · queued) at the trailing edge. No n/max: slots are per agent, so a
 * free slot of one agent is no room for another's task — the per-agent lanes
 * are in the title and on each group of the panel. The glyph badge carries
 * the one tone that matters most: red when the read failed, amber when a task
 * waits, blue when something runs.
 */
export declare function _queueHeadline(result: TaskQueueResult, t: Translate, now?: number): {
    tone: BalanceTone;
    value: string;
    sub: string;
    busy: boolean;
    title: string;
};
/** Executor names as their makers write them. */
export declare const AGENT_LABELS: Record<string, string>;
export declare const _agentLabel: (agent: string) => string;
/**
 * The model layer, read off the model id itself (never a hand-kept model
 * list), as its maker names it in full: `claude-opus-5-5` → Claude Opus 5.5 ·
 * `claude-haiku-4-5-20251001` → Claude Haiku 4.5 · `gpt-6-sol` → GPT-6 Sol ·
 * `opencode/nemotron-3-ultra-free` → Nemotron 3 Ultra. No letter tile in
 * front (kcn, 2026-09-27: the two-letter stand-in was noise); the room goes
 * to the whole name.
 */
export declare function _modelView(id: string): {
    label: string;
    family: string;
};
/** "Opus 5.5 · high", with the model the task will run on while it waits and the one it ran on after. */
export declare function modelLine(task: DispatchTask, _live: boolean): {
    model: string;
    effort: string;
    fallback: boolean;
};
/**
 * The notification layer: one receipt mark per channel the task asked for,
 * the channel's glyph followed by what its receipt says. Delivered = the
 * runner's NOTIFIED list (`openclaw message send` returned success for that
 * leg), failed = NOTIFY_FAILED, unknown = the task asked for the channel but
 * result.env holds no receipt for it (a runner older than the receipts, or a
 * leg that never ran). Colour is only the paint: the mark's glyph (✓ ✕ ?)
 * and its words say the same thing, and a mark is green only because a
 * receipt says so — never inferred from the task's own state.
 */
export type ReceiptState = 'sent' | 'failed' | 'unknown' | 'planned';
export declare function _notifyState(task: DispatchTask, ch: string, live: boolean): ReceiptState;
export declare function notifyChannels(task: DispatchTask): string[];
/**
 * A state's ROLE (2026-09-28 redesign, kcn: 「都是灰色 chip 没有区分度」). A role
 * is a colour AND a bed AND a glyph AND its word, so it survives a dark
 * theme and a greyscale screen: fill vs outline vs dashed edge, and a shape
 * per role. The colours are the host's role tokens (styles.module.css
 * `--tq-run|wait|bad` and the panel's text roles), nothing plugin-picked.
 *
 *   run       blue, filled bed, solid dot      holds its slot and runs
 *   queue     blue, outlined, ring             in line for its agent's lock or a slot
 *   sleep     amber, filled bed, moon          asleep until a quota window resets
 *   wait      amber, outlined, hourglass       any other wait (memory, retry, starting)
 *   done      neutral bed, check               ended, and the model reported done
 *   partial   amber, filled bed, half disc     ended but the work is not done (partial, blocked, no quota)
 *   fail      red, filled bed, cross           execution failed or timed out
 *   off       neutral, outlined, bar           cancelled / not running (patrol between rounds)
 *   unknown   neutral, dashed, question mark   nothing recorded to judge by
 *   fallback  amber, outlined, return arrow    ran on a fallback model (a mark on the model line)
 *
 * Done is deliberately NOT green: it rests on the model's own report. The one
 * green on a row is a delivery receipt (renderNotifyIcons).
 */
export type StateRole = 'run' | 'queue' | 'sleep' | 'wait' | 'done' | 'partial' | 'fail' | 'off' | 'unknown' | 'fallback';
export type GlyphPart = {
    d: string;
    paint: 'fill' | 'stroke';
};
export declare const STATE_ROLES: Record<StateRole, {
    bed: 'fill' | 'edge' | 'dashed';
    glyph: readonly GlyphPart[];
}>;
export type SlotChip = {
    text: string;
    role: StateRole;
    title?: string;
};
/** A BalanceTone (the dots, the rail badge) as the role it means. */
export declare const TONE_ROLE: Record<BalanceTone, StateRole>;
/**
 * An ended task's (or round's) ONE state: the runner's verdict and the
 * model's report folded into the role that most needs the reader. Both axes
 * stay readable: the chip's title says both, the detail layer shows both.
 */
export declare function _endedState(state: string, outcome: string, t: Translate): SlotChip;
/**
 * THE row grid (2026-09-28 redesign, kcn: 「很多地方都没有对齐显示导致 chip 过多显示杂乱」).
 * Every line of the open panel — a source's head, a section head, a live
 * task, an ended task, a patrol round — sits on the same five tracks
 * (styles.module.css `--tq-grid`), and every fact has ONE fixed cell:
 *
 *            lead   when       took       rest        aside
 *   line 1   glyph  name ─────────────────────────   state chip | value
 *   line 2          model (+ fallback mark) ───────   receipts | tries
 *   line 3          when       took                    cost
 *
 * `when`, `took` and `aside` are fixed widths, so a time, a duration, a cost,
 * a state are on one vertical line in every row that has them; a row without
 * a fact leaves its cell empty, never shifts the next one in. A head
 * (source/section) has a caption line in line 2 instead of facts.
 *
 * RESIDENT_CHIPS: a row carries at most ONE chip, its state. Everything else
 * is words in a fixed cell or a mark (receipts, fallback). What has no cell
 * here is not squeezed in, wrapped or ellipsised: it lives in the detail layer
 * one tap away (the report axis on its own, attempts' budget, the first queue
 * wait, the patrol tag, the session). ROW_KINDS says which facts each kind
 * shows; FACT_CELL where each one sits; the spec checks every rendered row
 * against both, and that no row has a second chip.
 */
export declare const FACT_ORDER: readonly ['model', 'filed', 'tries', 'receipt', 'when', 'took', 'cost'];
export type FactSlot = typeof FACT_ORDER[number];
export type RowKind = 'source' | 'head' | 'task' | 'ended' | 'round';
export declare const RESIDENT_CHIPS = 1;
/** Each fact's one cell: its line and its track (styles.module.css places `[data-tq-fact=…]` accordingly). */
export declare const FACT_CELL: Record<FactSlot, {
    line: 2 | 3;
    track: 'main' | 'full' | 'when' | 'took' | 'aside';
}>;
export declare const ROW_KINDS: Record<RowKind, {
    lead: boolean;
    value: boolean;
    facts: readonly FactSlot[];
}>;
/** A fact: its words, what a reader hears (the words with their unit), and a voice when it is a warning. */
export type Fact = {
    text: string;
    said?: string;
    title?: string;
    voice?: 'warn' | 'quiet';
    /** Filing evidence: words/links, not additional state chips. Same text in chat. */
    parts?: Array<{
        text: string;
        severity?: string;
        href?: string;
    }>;
    /** A mark after the words: the fallback model's return arrow (a role glyph, drawn by the renderer). */
    mark?: {
        role: StateRole;
        text: string;
        title: string;
    } | null;
    /** Delivery receipts, one per channel, in place of words (the renderer draws each channel's glyph). */
    receipts?: Array<{
        ch: string;
        state: ReceiptState;
    }> | null;
};
/** What the lead track shows: an executor, a section, or a source's own glyph. Drawn by the renderer. */
export type RowLead = {
    agent: string;
    size?: number;
} | {
    section: 'recent' | 'patrol';
} | {
    source: PanelSource;
};
export type RowView = {
    kind: RowKind;
    key: string;
    lead?: RowLead | null;
    name: string;
    value?: {
        text: string;
        tone: BalanceTone;
        level: UsedLevel | null;
    } | null;
    state: SlotChip | null;
    facts: Partial<Record<FactSlot, Fact | null>>;
    /** A head's line 2: what the source is (plan · slots · pool) or what a section is doing. Words, never chips. */
    caption?: Array<{
        text: string;
        voice?: 'warn';
        title?: string;
    }>;
    /** Opens the detail layer; a row without one is not a button. */
    open?: () => void;
    attrs?: Record<string, string | undefined>;
};
/** A clock for a fixed cell: "19:40" today, "10/4 19:40" another day. */
export declare function clockOf(ms: number, now: number): string;
/**
 * A live task's state chip: the short word (the group head already names the
 * agent), its role, and the whole phrase (_taskStatus: which lock, the wake
 * and the window it waits for) as the chip's title. A wake time is the 'when'
 * cell, where an ended task keeps when it ended.
 */
export declare function _taskState(task: DispatchTask, t: Translate, now?: number, windows?: ReadonlyArray<{
    resetAtMs?: number | null;
}>): {
    chip: SlotChip;
    when: Fact | null;
};
/** The model cell: the full model name and effort, and the fallback mark when it ran on another model. */
export declare function modelFact(task: DispatchTask, live: boolean, t: Translate): Fact | null;
/** The cost cell: the API-price estimate, 'free', or '—' when the model has no price row (title says which). */
export declare function costFact(task: DispatchTask, t: Translate, live: boolean): Fact | null;
/** A live task as a row: state chip; model, tries; when it wakes, how long, cost so far. */
export declare function taskRow(task: DispatchTask, t: Translate, now: number, open: (id: string) => void, windows?: ReadonlyArray<{
    resetAtMs?: number | null;
}>): RowView;
/** An ended task as a row: its one verdict; model and receipts; when, how long, what it cost. */
export declare function endedRow(task: DispatchTask, t: Translate, now: number, open: (id: string) => void): RowView;
/**
 * What a round routed through the filing gate, from the third `/` field patrol.sh writes
 * (`P1#2240 P2#2241 +2 digest +1 comment`, 2026-10-01): each issue with its severity, how many
 * findings went to the digest, how many were added to an issue on the same root cause. A P0 is
 * said as a warning. Null when the round filed nothing (or ran before the field existed).
 */
export declare function roundFiled(filed: string, t: Translate): Fact | null;
/** A finished patrol round as a row (rounds.tsv: `[preempted:|yielded:]STATE[/OUTCOME[/FILED]]`). */
export declare function roundRow(round: PatrolRound, t: Translate, now: number): RowView;
/** Patrol history is one semantic group, regardless of individual outcomes.
 * Up to four rounds stay visible; longer history keeps the newest round and
 * one disclosure for all older rounds, preserving chronological order.
 * Distinct ended tasks remain visible (the host already caps that list).
 */
export declare const FLAT_ROUNDS = 4;
export declare const RESIDENT_ROUNDS = 1;
/** A task the queue may reorder: waiting for the lock, current runner, not patrol, not protected. */
export declare const reorderable: (task: DispatchTask) => boolean;
/** Live tasks of one agent in the order they hold / will take its lock. */
export declare function groupOrder(tasks: DispatchTask[], queue: AgentQueue | undefined): DispatchTask[];
/** One line of the fused cell: a provider, an agent, or both joined (see providers.ts). */
export type PanelSource = {
    /** Stable key: the provider id, else the agent id. */
    key: string;
    label: string;
    join: ProviderJoin | null;
    provider: BalancesResult['providers'][number] | null;
    agent: string | null;
};
/**
 * The panel's sources in providers.ts's order (sourceRank: the paid,
 * exclusive allowances first, the free pool last, anything without a row
 * among the paid ones). A joined row with a dispatch agent renders with its
 * queue; an agent the queue reports that no row names gets a line of its own;
 * a provider without an agent renders when the balance answer has it. Agent
 * rows need a dispatcher (C3 ②: without one only providers render); a
 * provider row needs its provider.
 */
export declare function _panelSources(providers: BalancesResult['providers'], queue: TaskQueueResult | null): PanelSource[];
/** Where the free pool is: the model the latest opencode task used, and the next one in file order. */
export declare function _poolPosition(result: TaskQueueResult | null): {
    current: string;
    next: string;
    fromOrder: boolean;
} | null;
/**
 * A queue's state chip, the same on the folded line and on its group's head:
 * the ONE state that most needs the reader, with its count — asleep on quota,
 * then queued behind the lock or a slot, then another wait, then running. A
 * wait outranks running because a queue implies its holder runs. Idle is no
 * chip at all. `text` is every count (the line's aria-label and title).
 */
export declare function _queueState(t: Translate, tasks: DispatchTask[]): {
    text: string;
    chip: SlotChip | null;
};
/**
 * A source's value column: the allowance headline (used % of the first
 * window, or the balance) and its tone; for the free pool, "free" — where
 * the rotation stands is a fact of its group. `reset` (the headline window's,
 * resetStampOf) is read out in the line's label; the clocks themselves are
 * drawn once, on the group's window bars.
 */
export declare function sourceReading(source: PanelSource, row: BalanceRow | undefined, queue: TaskQueueResult | null, t: Translate): {
    value: string;
    reset: string | null;
    tone: BalanceTone;
    level: UsedLevel | null;
    title: string;
};
/** The patrol phase's role: running blue, giving way amber (a wait), between rounds off, stopped red. */
export declare const PATROL_ROLE: Record<string, StateRole>;
/** rounds.tsv's local "YYYY-MM-DD HH:MM:SS" as epoch ms, null when it is not one. */
export declare function localStampMs(stamp: string): number | null;
/**
 * Why the supervisor gives way, read off its journal line. The patterns are
 * the reasons the supervisor can actually write — `others_need_slot` and
 * `round_blocks_someone` in ops/host/patrol.sh, `memory_pressure_reason` in
 * ops/host/agent-dispatch/resource-pressure.sh — and the spec instantiates
 * every one of those templates from the files themselves (#2071):
 *   manual = a manual task waits for the lock or a slot the patrol would use
 *            (the id is that task, shown so the reader knows whom it waits for);
 *   slot   = the patrol's own admission: its agent's run slots are all taken;
 *   memory = admission deferred on memory headroom, pressure or telemetry.
 * `asking <round> to wrap up …: <demand>` is the grace before a preemption.
 */
export declare function _patrolReason(detail: string): {
    kind: 'manual' | 'slot' | 'memory' | 'memoryUnread' | 'other';
    task: string;
    wrapUp: boolean;
};
/** The supervisor's live status as the patrol head's caption: when the next round is, what it runs now, or why it gives way. */
export declare function patrolCaption(result: TaskQueueResult, t: Translate, now: number): NonNullable<RowView['caption']>;
/** The cost cell: an API-price estimate, 'free', or '—' when the model is unpriced; null when nothing was recorded. */
export declare function _costOf(task: DispatchTask): {
    short: string;
    kind: 'usd' | 'free' | 'unpriced';
} | null;
/**
 * A source as a row: the sidebar's folded line and its group's head in the
 * panel are this one view (the same glyph, name and value in the same
 * columns), so the line a reader taps is the line the panel opens on. The
 * folded line adds the queue's one state chip (its tasks are not on screen);
 * the head adds its caption — the plan, the run slots, the pool — in words.
 */
export declare function sourceView(source: PanelSource, row: BalanceRow | undefined, result: TaskQueueResult | null, t: Translate): RowView & {
    reading: ReturnType<typeof sourceReading>;
    queue: ReturnType<typeof _queueState> | null;
};
/** Provider rows with their display projection: what every surface of the cell reads. */
export declare function balanceRows(result: BalancesResult | null, t: Translate, now: number): BalanceRow[];
/** The provider windows of an agent (a quota wait names the reset it waits for). */
export declare function agentWindows(rows: ReadonlyMap<string, BalanceRow>, agent: string): ReadonlyArray<{
    resetAtMs?: number | null;
}> | undefined;
/**
 * The per-provider detail under its headline: quota providers get one line
 * per window — label / used / reset — so the 5h and week resets scan as a
 * column instead of drowning in a sentence. Money rows keep their
 * granted/topped-up split. A note does NOT suppress this detail when
 * readable windows exist (kcn 反馈 #908: 变色只改颜色,绝不动信息量)——
 * the watermark/stale caption rides along; only data-less abnormal rows
 * (unconfigured / fetch-failed) speak through the note alone.
 */
export type AllowanceDetail = {
    kind: 'windows';
    windows: Array<{
        label: string;
        percent: number | null;
        fill: number | null;
        reset: string;
        state: UsedLevel | 'stale';
    }>;
} | {
    kind: 'text';
    text: string;
} | null;
export declare function allowanceDetail(row: BalanceRow, t: Translate, now: number): AllowanceDetail;
/**
 * One provider group of the open panel (2026-09-28, kcn: 「任务现在和 provider
 * 那个上下好像都不明显了」). Two levels, never mixed: the allowance is the
 * group's head (name and reading, the caption, the window lines); the queue
 * that allowance feeds is a list below it, one step down.
 */
export type PanelGroup = {
    source: PanelSource;
    /** The group's head row: the source's folded line without its state chip (its tasks are right below). */
    head: RowView;
    row: BalanceRow | undefined;
    /** Abnormal balance rows say so, with the last good reading and when it was taken (① stale). */
    balanceNote: string | null;
    detail: AllowanceDetail;
    /** The lock held by a task of another listing, a quota stop: words under the head. */
    notes: string[];
    /** Live tasks of the agent, in the order they hold / will take its lock. */
    tasks: Array<{
        task: DispatchTask;
        row: RowView;
    }>;
};
export declare function panelGroup(source: PanelSource, result: TaskQueueResult | null, rows: ReadonlyMap<string, BalanceRow>, t: Translate, now: number, open: (id: string) => void): PanelGroup;
/** Ended work, newest first across agents: every ended task is resident (see RESIDENT_ROUNDS). */
export declare function recentSection(result: TaskQueueResult | null, t: Translate, now: number, open: (id: string) => void): {
    head: RowView;
    rows: RowView[];
} | null;
/**
 * Patrol coverage as two short tables behind one fold (2026-10-04 redesign, kcn: 「area 那个做的就
 * 很多很杂乱」). The fold's label is the headline, so a reader who never opens it still learns
 * whether anything is open; inside, every number has a column and is said once:
 *
 *   areas   open filed issues per area, most first, each with its share of the largest; the areas
 *           with none share one line. This is where findings belong, NOT where patrol looked
 *           (rounds.tsv has no area), and the one caption under the heading says so.
 *   lenses  one row per lens, most recently run first, so the gap in the rotation reads down the
 *           `when` column: last run, recorded attempts, open issues; under it the last round with
 *           its verdict and what it filed (the same words and links as a round row).
 *
 * What is wrong with the sources (unreadable history, inventory or issue labels) is `alerts`,
 * said only when it happens; the provenance every reading has (how many records, since when, the
 * issue snapshot's time) is the one `footnote` line. No count is inferred: unknown stays unknown.
 */
export type CoverageView = {
    title: string;
    /** The fold's label: the title and how many areas (or lenses) have open issues. */
    headline: string;
    alerts: string[];
    areaHeading: string;
    areaNote: string;
    /** Areas with open issues (or an unknown count), most first; `share` is the bar against the largest. */
    areas: Array<{
        name: string;
        open: string;
        share: number | null;
        href: string;
    }>;
    /** Areas with none, on one line. */
    clear: {
        label: string;
        names: Array<{
            name: string;
            href: string;
        }>;
    };
    lensHeading: string;
    lensNote: string;
    columns: {
        last: string;
        runs: string;
        open: string;
    };
    lenses: Array<{
        name: string;
        href: string;
        /** When it last ran, as a round row says it; null when no round is recorded. */
        when: Fact | null;
        runs: string;
        open: string;
        /** Open issues exist (the count is drawn strong); null when unknown. */
        hasOpen: boolean | null;
        /** The last round: its id, its verdict, what it filed. */
        last: {
            round: string;
            state: SlotChip | null;
            filed: Fact | null;
        } | null;
        /** In place of `last` when there is none. */
        none: string;
    }>;
    footnote: string;
    empty: string;
};
/**
 * Patrol: a section head (the phase as its state chip, the live status as its
 * caption), and one chronological history group. The raw supervisor journal
 * is not a task conclusion; the head already projects its useful status.
 */
export declare function patrolSection(result: TaskQueueResult | null, t: Translate, now: number): {
    head: RowView;
    rounds: RowView[];
    progress: CoverageView | null;
} | null;
/** The ops entry's footer: its version and runner api, or why it is missing / skewed. */
export declare function opsFooter(result: TaskQueueResult | null, t: Translate): {
    text: string;
    bad: boolean;
    version: string;
} | null;
/**
 * Why a half of the cell is not (fully) there: a failed or stale queue read, a
 * host without the dispatcher, a failed balance read. `error` is a transport
 * failure (the fetch never answered); an in-band failure arrives in the result.
 */
export declare function panelNotices(input: {
    queue: TaskQueueResult | null;
    queueError: string | null;
    balances: BalancesResult | null;
    balanceError: string | null;
    rowCount: number;
}, t: Translate): Array<{
    key: string;
    text: string;
    bad: boolean;
}>;
/** The whole open panel as data: title, notices, a group per source, recent, patrol, footer. */
export type PanelModel = {
    title: string;
    notices: Array<{
        key: string;
        text: string;
        bad: boolean;
    }>;
    /** Nothing to show yet (or at all) — said instead of the groups. */
    empty: string | null;
    groups: PanelGroup[];
    recent: ReturnType<typeof recentSection>;
    patrol: ReturnType<typeof patrolSection>;
    footer: ReturnType<typeof opsFooter>;
};
/** Both halves of the cell as one read left them: an answer, or why there is none. */
export type PanelInput = {
    balances: BalancesResult | null;
    balanceError: string | null;
    queue: TaskQueueResult | null;
    queueError: string | null;
};
export declare function panelModel(input: PanelInput, t: Translate, now: number, open?: (id: string) => void): PanelModel;
