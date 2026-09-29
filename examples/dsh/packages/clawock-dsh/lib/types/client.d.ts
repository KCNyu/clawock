/**
 * clawock-dsh browser bundle: the Decision Mind conversation-view tab.
 *
 * One organic view — the decision trace: real fills as the spine, the shared
 * decision ledger (memory/decisions.jsonl) soft-paired (±3 days) as the "why"
 * layer, and canonical bar closes (memory/bars/, never snapshot current_price
 * — see readBarCloses) as the T+1 verdict. Fills without a decision say so
 * explicitly. Visual language: modern SaaS on DSH tokens, with the P&L
 * figure as the focal number and a GitHub-style vertical timeline in the
 * expandable detail.
 *
 * Official client discipline (`packages/client/AGENTS.md` in the Harness
 * tree), all four rules this file has to satisfy:
 *   - registration happens inside `apply` through `ctx.slots.register`, and
 *     the module body has no side effects — styles arrive as a CSS Modules
 *     import, whose `<style data-plugin>` tag the loader owns and removes on
 *     unload;
 *   - the store is an exported `createDecisionMindStore()` factory called in
 *     `apply`, never a module-level handle (a disguised singleton);
 *   - live data reaches render through the props shares only, so the trace
 *     cache lives in the apply closure and is read through `inject`;
 *   - components take named props and the wire types from `./types.ts`.
 */
import type { Context } from '@deepseek-ai/cordis';
import type { TypertClientRemote } from '@deepseek-ai/dsh-typert-protocol';
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots';
import * as React from 'react';
import type { BalancesResult, EnrichedTrade, QueueActionResult, T1VerdictKind, TaskQueueResult, TraceDecision, TraceT1 } from './types.ts';
import { type Translate } from './copy.ts';
export { LOCALE_NS, type Translate, dictionaries, createTranslator, windowLabelOf, resetStampOf, windowsOf } from './copy.ts';
export { type BalanceTone, type UsedLevel, _usedLevel, _rowDisplay, _balanceNote, _slotOf, _slotLanes, _taskStatus, _queueHeadline, _agentLabel, _modelView, type ReceiptState, _notifyState, type StateRole, STATE_ROLES, _endedState, FACT_ORDER, type FactSlot, type RowKind, RESIDENT_CHIPS, FACT_CELL, ROW_KINDS, _taskState, type PanelSource, _panelSources, _poolPosition, _queueState, _patrolReason, _costOf } from './panel.ts';
/**
 * The T+1 verdict in the active locale. `verdictKind` is the stable code; a
 * host that predates it sends only the rendered text, which is passed through
 * rather than dropped — the same fallback rule as the balance windows.
 */
export declare function verdictOf(t: Translate, t1: {
    verdictKind?: T1VerdictKind | null;
    verdict: string;
}): string;
/** The four trace filters offered above the list. */
export type TraceFilter = 'all' | 'miss' | 'sold' | 'dec';
/**
 * Per-session UI state that survives tab unmounts: the ring remounts the view
 * on every switch (`only: active.id`), so open row / filter / batch / folded
 * days / scroll position must live in the registration store (kept alive for
 * the registration's lifetime), not in component state.
 */
export interface DecisionMindState {
    filter: TraceFilter;
    open: string | null;
    visibleDateCount: number;
    foldedDates: string[];
    scrollTop: number;
}
/**
 * Store factory — called once inside `apply`. Never a module-level handle:
 * the module cache would make it a singleton shared across plugin reloads.
 */
export declare function createDecisionMindStore(): import("@deepseek-ai/dsh-client-store").EngineStoreHandle<DecisionMindState, {
    setFilter: (draft: DecisionMindState, value: TraceFilter) => void;
    toggleOpen: (draft: DecisionMindState, key: string) => void;
    showMoreDates: (draft: DecisionMindState, count: number) => void;
    resetDates: (draft: DecisionMindState) => void;
    toggleDate: (draft: DecisionMindState, date: string) => void;
    setScrollTop: (draft: DecisionMindState, value: number) => void;
}>;
/** The registration's store handle type — the props store share derives from it. */
export type DecisionMindStore = ReturnType<typeof createDecisionMindStore>;
/** One fetched trace result, kept across tab mounts by the apply closure. */
export interface TraceSnapshot {
    workspaceKey: string;
    signature: string;
    trades: EnrichedTrade[];
    rate: number | null;
}
/** What the registration's `inject` factory hands the view. */
export interface DecisionMindInjected {
    /** The last snapshot this registration fetched, or null on a cold mount. */
    cachedTraces: () => TraceSnapshot | null;
    /** Fetch traces; `changed` is false when the host answered the same signature. */
    fetchTraces: () => Promise<{
        snapshot: TraceSnapshot;
        changed: boolean;
    }>;
}
/**
 * The view's props. The store share is derived from the declared handle
 * (`PropsStore`); `sessionId` is the session-scope runtime seat, hand-declared
 * because deriving it would need `SlotMap['conversation.view']` from the
 * conversation package — a cross-plugin value/type import the client rules
 * forbid.
 */
export type DecisionMindProps = PropsStore<DecisionMindStore> & DecisionMindInjected & {
    sessionId: string;
    /** Dictionary seat from declaring `locale: LOCALE_NS` on the registration. */
    t: Translate;
};
/**
 * The T+1 tone is decided host-side (`t1ToneOf` in ledger.ts) and shipped on
 * the trace as `t1.tone`. These two helpers only map that single reading onto
 * the two CSS vocabularies used here — the trace node's win/loss and the
 * chip's up/down. They deliberately take no thresholds: three independent
 * dead zones used to colour the same fill grey-"持平" in the chip and red in
 * the node, and to paint a buy at exactly 0% green while the text read 跌.
 */
export declare function t1NodeClass(tone: TraceT1['tone']): string;
export declare function t1ChipClass(tone: TraceT1['tone']): 'up' | 'down' | 'flat';
/** Dashboard-parity money formatter (test seam). */
export declare function _fmtMoney(value: number | null, currency?: string): string;
/** Dashboard-parity percentage formatter (test seam). */
export declare function _fmtPct(value: number | null, digits?: number): string;
/** One row of the list: the wire trade projected onto what the view renders. */
export interface DisplayEntry {
    ticker: string;
    market: string;
    currency: string;
    date: string | null;
    action: string;
    shares: number;
    price: number | null;
    realizedPnl: number | null;
    note: string | null;
    t1: TraceT1 | null;
    holdPnl: number | null;
    decision: TraceDecision | null;
    /**
     * 'add' | 'reduce' decided host-side (see EnrichedTrade.side), or null when
     * the payload carried no side at all.
     *
     * Nullable on purpose. Defaulting an unknown side to 'add' silently files
     * every sell under buys and the sell scorecard then reads a confident
     * "判出 0/0 笔卖出" — wrong, not degraded. Null keeps those fills out of both
     * sides and makes the header say how many it could not place.
     */
    side: 'add' | 'reduce' | null;
}
/** Display projection of one trace (test seam). */
export declare function _displayEntry(trace: EnrichedTrade): DisplayEntry;
/** Stable row identities are derived before filtering, so switching filters
 * cannot remount the same trade and discard its expanded state (#1603). */
export declare function _traceKeys(traces: DisplayEntry[]): Map<DisplayEntry, string>;
/** What the header chip's `inject` factory hands the component. */
export interface BalancesInjected {
    /** The last multi-provider answer this registration fetched, or null cold. */
    cachedBalances: () => BalancesResult | null;
    /** Fetch all providers; `force` bypasses the host TTLs (the manual refresh). */
    fetchBalances: (force: boolean) => Promise<BalancesResult>;
    /** Hear answers fetched by a sibling surface; returns the unsubscribe. */
    subscribeBalances?: (listener: (result: BalancesResult) => void) => () => void;
}
/**
 * Which provider the pill headlines. null = auto (first configured row);
 * a click on a panel row pins that provider. Registration-store state, so
 * the choice survives the ring's remounts.
 */
export interface BalanceUiState {
    selected: string | null;
}
/** Store factory — called inside `apply`, never a module-level handle. */
export declare function createBalanceStore(): import("@deepseek-ai/dsh-client-store").EngineStoreHandle<BalanceUiState, {
    select: (draft: BalanceUiState, provider: string) => void;
}>;
/** The chip's registration store handle type (derived, like DecisionMind's). */
export type BalanceStore = ReturnType<typeof createBalanceStore>;
export type BalanceChipProps = BalancesInjected & PropsStore<BalanceStore> & {
    sessionId: string;
    /** Dictionary seat from declaring `locale: LOCALE_NS` on the registration. */
    t: Translate;
};
export declare function ProviderBalanceChip(props: BalanceChipProps): React.ReactElement;
/** Foot-action id of the balance surface (a stable DOM contract for probes). */
export declare const BALANCE_PANEL = "clawock-provider-balance";
/** What the task chip's `inject` factory hands the component. */
export interface TaskQueueInjected {
    /** The last answer this registration fetched, or null cold. */
    cachedTaskQueue: () => TaskQueueResult | null;
    /** Read the queue; `force` bypasses the short host cache (the manual refresh). */
    fetchTaskQueue: (force: boolean) => Promise<TaskQueueResult>;
    /**
     * One write (or on-demand read) through the host's versioned ops entry.
     * Optional: without it the panel is read-only.
     */
    runQueueAction?: (action: string, id: string, arg: string) => Promise<QueueActionResult>;
}
/** The one door to dsh's own file preview (right sidebar), or why it cannot open (see apply). */
export type OpenFile = (path: string) => {
    ok: true;
} | {
    ok: false;
    reason: 'no-service' | 'no-session' | 'error';
    message?: string;
};
/** `4200` → `4.2k`, `83123861` → `83.1M`: token counts read at a glance, exact value in the aria text. */
export declare function _fmtTokens(n: number): string;
/**
 * The file-preview address of a path read through one session — dsh-util-workspace-path's
 * `sessionFileAddress` grammar (an absolute path keeps its leading `/`, hence `…/<id>//root/…`).
 * The preview claims only this scope: `file/absolute/…` answered "no registered tab type claims"
 * on the live host (2026-09-27), so the brief opens in the conversation's own sidebar.
 */
export declare function _sessionFileAddress(sessionId: string, path: string): string;
/**
 * The detail layer's order (2026-09-28, kcn: 「问题在详情页……信息没有秩序」). The layer
 * holds what the row cannot: the whole status sentence, the allowance the task
 * burns and when it resets, where the free pool stands, the first queue wait,
 * the budgets and the raw record. It is read top-down in SECTIONS order; a
 * section with nothing to say is not drawn. Each section is a caption and a
 * list of fields on THE row grid (--tq-grid): the label on the `when` track
 * (the name's edge), the value over took…rest, and — for a fact a task can
 * change — its control on the `aside` track, where the list keeps the state
 * chip. So a control sits beside the number it changes, and its confirmation
 * directly under that line.
 *
 *   status     glyph · name · the row's own state chip; the full sentence under it
 *   summary    (ended) the closing report — what happened comes before how
 *   view       read-only: the brief and the log; what they open unfolds right here
 *   run        what the next attempt runs with — model, place in line, deadline,
 *              retries, quota resumes — each with its control when writable
 *   allowance  who runs it and what pays: agent and slot, the plan; while live also the
 *              windows with their resets (the list's own window lines), the free pool's
 *              position and a quota stop — they describe now, not an ended run
 *   time       queued, first queue wait, started, running for / took, wakes, ended
 *   usage      tries (when no budget says it), stalls, cost, tokens
 *   notify     one line per channel, the list's receipt mark and its words (one field, no caption)
 *   end        the task-ending writes (wrap up, cancel), or retry once it ended
 *   raw        FOLDED (the list's one disclosure rule: raw source folds): the
 *              runner's latest log line, the runner api, session and task ids
 *
 * DETAIL_ACTIONS says what each action is — `view` reads (a filled, quiet
 * pill), `write` changes the queue (an outlined control beside its fact),
 * `danger` ends work (red, last) — and where it lives. The spec checks every
 * rendered section, field and pill against these tables.
 */
export type DetailSection = 'status' | 'summary' | 'view' | 'run' | 'allowance' | 'time' | 'usage' | 'notify' | 'end' | 'raw';
export declare const DETAIL_SECTIONS: Record<'live' | 'ended', readonly DetailSection[]>;
export declare const DETAIL_FIELDS: Partial<Record<DetailSection, readonly string[]>>;
export declare const DETAIL_FOLDED: readonly DetailSection[];
export type ActionKind = 'view' | 'write' | 'danger';
export declare const DETAIL_ACTIONS: Record<string, {
    kind: ActionKind;
    home: string;
}>;
/** What one action's answer says, in the reader's words (the ops entry's own message otherwise). */
export declare function _describeAction(result: QueueActionResult, t: Translate): string;
export type ProviderPanelProps = BalancesInjected & PropsStore<BalanceStore> & TaskQueueInjected & {
    /** Sidebar column state: false is the 56px rail (one glyph + a status badge). */
    wide: boolean;
    t: Translate;
    /** dsh's own file preview (see apply); absent in tests and on hosts without it. */
    openFile?: OpenFile;
};
/**
 * The sidebar-foot provider panel (2026-09-27): the balance chip and the
 * dispatch queue as ONE cell, `provider-balance`. Folded, it is one line per
 * source — provider or agent name first, its reading and reset, then who
 * burns that allowance (the agent's queue) or where its key comes from. Any
 * line opens the panel on that source's group: the allowance (windows with
 * their resets, or money), then the queue that allowance feeds. The rail
 * keeps one glyph whose badge warns when a window is at its threshold or a
 * task sleeps on quota. Both halves keep their own read and cadence.
 */
export declare function ProviderPanelSidebarAction(props: ProviderPanelProps): React.ReactElement;
export declare function DecisionMind(props: DecisionMindProps): React.ReactElement;
/**
 * `layout` is listed even though the plugin only *probes* it, and that is not
 * an oversight — it is the one thing `ctx.get` cannot do here. The probe runs
 * inside `apply`, and `ctx.get` does not wait: it returns `undefined` when the
 * providing fiber has not activated yet, so the chip silently fell back to the
 * session-header seat (verified live, 2026-09-19 — `[data-clawock-action]`
 * count 0 while the header chip rendered). `inject` is the mechanism that
 * holds the plugin until the service exists.
 *
 * The cost is real and accepted: on a host with no `layout` at all, the whole
 * client half waits and the Decision Mind tab does not mount either. Every
 * shipped host provides it, and the alternative trades a hypothetical
 * older-host degradation for a measured one on the host we run.
 */
export declare const inject: string[];
/** Client contribution context: the face the slot renderer hands us. */
interface ClientContributionContext {
    slots: {
        inject: (name: string, register: () => unknown) => unknown;
        register: (definition: Record<string, unknown>, component: unknown) => unknown;
    };
    remote: TypertClientRemote;
    /** Locale registry: this bundle owns one dictionary namespace (see LOCALE_NS). */
    locale: {
        register: (ns: string, dicts: Record<string, Record<string, string>>) => () => void;
    };
    /** Injected host layout face; `selectPanel` exists only where `main` is keyed (DSH >= 0.1.5-rc.1). */
    layout?: LayoutProbe;
    /** Service lookup; each call site narrows the face it asked for. */
    get: (name: string) => unknown;
}
/** `selectPanel` exists only where `main` is keyed (DSH >= 0.1.5-rc.1). */
type LayoutProbe = {
    selectPanel?: (panelId: string | null) => void;
};
/** Register the Decision Mind tab into the conversation view ring. */
export declare function apply(ctx: Context & ClientContributionContext): Promise<void>;
