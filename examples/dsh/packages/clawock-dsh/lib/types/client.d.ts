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
import type { BalanceResult, BalancesResult, EnrichedTrade, T1VerdictKind, TraceDecision, TraceT1 } from './types.ts';
/** Dictionary namespace declared by every registration in this bundle. */
export declare const LOCALE_NS = "clawock";
/**
 * Translate one dictionary key with optional `{name}` params. Hand-declared
 * rather than derived from the host's `TranslateNS<NS>`: that type needs the
 * `LocaleNamespaceMap` merge the locale plugin owns, and this file's rule is to
 * hand-declare what cannot be derived without a cross-plugin type import (the
 * same reason `sessionId` is declared, not derived).
 */
export type Translate = (key: string, params?: Record<string, unknown>) => string;
/**
 * This plugin's copy, in the locales the browser client ships (`zh`, `en` —
 * `dsh-client-locale`'s LOCALE_IDS). Keys are grouped by surface; the two
 * dictionaries must carry the same key set, which `tests/decision_studio_plugin.spec.js`
 * enforces so a missing translation cannot ship.
 */
export declare const dictionaries: Record<string, Record<string, string>>;
/**
 * Bind a dictionary to a lookup shaped exactly like the host's `t` seat, with
 * `{name}` interpolation. The host supplies the real one through the slot
 * registration (`locale: LOCALE_NS`); this factory exists so a render can be
 * exercised without a locale service — the same seam the tests use.
 */
export declare function createTranslator(dict: Record<string, string>): Translate;
/**
 * Window length in minutes → the label in the active locale, host string as
 * fallback. The structured fields are typed `| null` but read `== null`: a
 * host that predates them omits the key entirely, so the value that actually
 * arrives is `undefined`. Checking only for null rendered `NaN m` against a
 * previous-version host — the exact half-deployed case this fallback exists
 * for, caught by the projection test rather than in the browser.
 */
export declare function windowLabelOf(t: Translate, window: {
    label: string;
    durationMins?: number | null;
}): string;
/** The reset instant → the stamp in the active locale, host string as fallback. */
export declare function resetStampOf(t: Translate, window: {
    resetAt: string;
    resetAtMs?: number | null;
}, now: number): string;
/**
 * The T+1 verdict in the active locale. `verdictKind` is the stable code; a
 * host that predates it sends only the rendered text, which is passed through
 * rather than dropped — the same fallback rule as the balance windows.
 */
export declare function verdictOf(t: Translate, t1: {
    verdictKind?: T1VerdictKind | null;
    verdict: string;
}): string;
/** Every window of a snapshot, named and stamped for the active locale. */
export declare function windowsOf(t: Translate, result: BalanceResult, now: number): {
    label: string;
    percent: number | null;
    reset: string;
}[];
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
/** The foot button's owner share plus its inject face. */
export type BalanceSidebarActionProps = BalancesInjected & PropsStore<BalanceStore> & {
    /** Sidebar column state: false is the 56px rail (dot only). */
    wide: boolean;
    /** Dictionary seat from declaring `locale: LOCALE_NS` on the registration. */
    t: Translate;
};
/**
 * The sidebar-foot home of the balance chip: always mounted, independent of
 * any session. It headlines the same one provider (pinned or first row) with
 * the same dot/tier/stale colours and polls on the same cadence.
 *
 * The provider list opens as a trigger-owned popover, the interaction the
 * host's own foot occupant uses (ui-cordis `CordisPanel`): the row toggles it,
 * it is `position:fixed` above the row so the clipped sidebar column cannot
 * cut it, and only a pointerdown outside the row+popover root or Escape
 * dismisses it (ui-primitives `useDismissOnOutsidePointer`, heard in the
 * capture phase — see the effect). It used to select
 * a keyed `main` panel instead, which swapped the whole conversation column
 * for a mostly empty page — one click and the chat you were reading was gone
 * (and on a phone the panel opened squeezed beside the still-open drawer).
 * Pinning a row and the manual refresh happen inside the root, so they can
 * never close it.
 */
export declare function ProviderBalanceSidebarAction(props: BalanceSidebarActionProps): React.ReactElement;
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
export {};
