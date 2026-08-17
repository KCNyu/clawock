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
import type { EnrichedTrade, TraceDecision, TraceT1 } from './types.ts';
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
export declare function createDecisionMindStore(): import("@deepseek-ai/dsh-client-runtime/client").EngineStoreHandle<DecisionMindState, {
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
export declare function DecisionMind(props: DecisionMindProps): React.ReactElement;
/** Services required by the registration and the mounted Remote face. */
export declare const inject: string[];
/** Client contribution context: the face the slot renderer hands us. */
interface ClientContributionContext {
    slots: {
        inject: (name: string, register: () => unknown) => unknown;
        register: (definition: Record<string, unknown>, component: unknown) => unknown;
    };
    remote: TypertClientRemote;
    get: (name: string) => Record<string, (...args: unknown[]) => Promise<unknown>>;
}
/** Register the Decision Mind tab into the conversation view ring. */
export declare function apply(ctx: Context & ClientContributionContext): Promise<void>;
export {};
