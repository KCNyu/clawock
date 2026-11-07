/**
 * The Workbench's one explicit view/overlay state machine.
 *
 * Why this file exists (kcn 2026-11-07): the page had accumulated one
 * `useState` per surface — `tab`, `view`, `selected`, two overview fold
 * booleans, the brief/log/timeline/picker data and a notice. Mutually
 * exclusive layers were then maintained by convention: every new control had
 * to remember which other setters to clear. One forgotten setter mounts two
 * detail layers at once (the #3282 acceptance found exactly that), and no test
 * could enumerate the states.
 *
 * Here a surface is a value in ONE state object, changed only by
 * `reduceWorkbench`. The legal edges are the table below, not scattered
 * branches. Illegal edges throw in development and tests; `WorkbenchPage`
 * calls the reducer with `strict: false` in production, where the edge is
 * ignored and logged instead (a stale async reply may race a layer change; a
 * page must not crash over it).
 *
 * Main states (mutually exclusive — at most one `phase`):
 *
 *   queue ──tab──> tasks | providers | overview
 *     │                              │
 *     │ open task                    ├─ open patrol  -> patrol
 *     │                              ├─ open stats   -> stats
 *     │                              └─ open history -> history
 *     v
 *   focus(task) ──back──> queue(tasks)      (or history when opened there)
 *   patrol/stats/history ──back──> queue(overview)
 *
 * Overlays do not replace the main state:
 *   sheet  (brief | log | timeline | picker) — only inside focus, one at a time
 *   toast  (one status line)                  — any phase, never changes it
 *
 * Every phase declares its entry/exit side effects in `WORKBENCH_EFFECTS`
 * (focus, scroll, subscription); `effectsFor` is the only place that decides
 * which ones a transition runs, and the page executes them in one effect.
 */
export type WorkbenchTab = 'tasks' | 'providers' | 'overview';
export type WorkbenchPhase = 'queue' | 'focus' | 'patrol' | 'stats' | 'history';
export type WorkbenchSheetKind = 'brief' | 'log' | 'timeline' | 'picker';
export interface WorkbenchToast {
    ok: boolean;
    text: string;
}
/** Where a task detail was opened from, so Back can return there (history is a layer). */
export interface WorkbenchOrigin {
    phase: 'queue' | 'history';
    tab: WorkbenchTab;
    /** The history row to focus after Back (null for the task queue). */
    taskId: string | null;
}
export interface WorkbenchState {
    phase: WorkbenchPhase;
    tab: WorkbenchTab;
    taskId: string | null;
    origin: WorkbenchOrigin | null;
    sheet: WorkbenchSheetKind | null;
    toast: WorkbenchToast | null;
}
export declare const WORKBENCH_TABS: readonly WorkbenchTab[];
export declare const WORKBENCH_SHEETS: readonly WorkbenchSheetKind[];
export declare const initialWorkbenchState: WorkbenchState;
export type WorkbenchAction = {
    type: 'TAB';
    tab: WorkbenchTab;
} | {
    type: 'SELECT_TASK';
    id: string;
} | {
    type: 'OPEN_TASK';
    id: string;
    mobile: boolean;
    from?: 'tasks' | 'history';
} | {
    type: 'OPEN_PATROL';
} | {
    type: 'OPEN_STATS';
} | {
    type: 'OPEN_HISTORY';
} | {
    type: 'BACK';
} | {
    type: 'OPEN_SHEET';
    sheet: WorkbenchSheetKind;
} | {
    type: 'CLOSE_SHEET';
} | {
    type: 'TOAST';
    ok: boolean;
    text: string;
} | {
    type: 'DISMISS_TOAST';
};
export type WorkbenchActionType = WorkbenchAction['type'];
/**
 * The legal edges, as data. `from` lists the phases an action may start in;
 * `guard` names the extra condition (the reducer and tests read the same
 * string, so the report and the implementation cannot drift).
 *
 * `to` is a description of the destination, not a literal state: the reducer
 * derives tab/taskId/origin/overlay from the current state.
 */
export declare const WORKBENCH_TRANSITIONS: Record<WorkbenchActionType, {
    from: readonly WorkbenchPhase[];
    to: string;
    guard?: string;
}>;
/** What a transition runs on entering/leaving a phase. Pure data; the page executes it. */
export type WorkbenchEffect = 'focus:task-title' | 'focus:patrol-back' | 'focus:stats-back' | 'focus:history-back' | 'focus:task-row' | 'focus:history-row' | 'focus:overview-entry' | 'focus:sheet-trigger' | 'focus:sheet-close' | 'scroll:layer-top' | 'scroll:queue-restore' | 'subscribe:queue' | 'subscribe:balances' | 'subscribe:stats';
export interface WorkbenchPhaseEffects {
    enter: readonly WorkbenchEffect[];
    exit: readonly WorkbenchEffect[];
}
export declare const WORKBENCH_EFFECTS: Record<WorkbenchPhase, WorkbenchPhaseEffects>;
/** Phase-aware subscriptions: only the visible surface keeps its channel warm. */
export declare function workbenchSubscriptions(state: WorkbenchState): {
    balances: boolean;
    stats: boolean;
    queue: boolean;
};
/** The one legality predicate. The reducer, the tests and the report all use it. */
export declare function isLegalWorkbenchAction(state: WorkbenchState, action: WorkbenchAction): boolean;
export interface WorkbenchReduceOptions {
    /** false = production: log the illegal edge and keep the current state. */
    strict?: boolean;
    log?: (message: string) => void;
}
/**
 * The single transition function. No other code may assign a view/overlay.
 */
export declare function reduceWorkbench(state: WorkbenchState, action: WorkbenchAction, options?: WorkbenchReduceOptions): WorkbenchState;
/**
 * Which effects a transition runs. Derived from the phase table plus the
 * focus-restore rule for Back and sheet close; no component invents its own.
 */
export declare function effectsFor(previous: WorkbenchState, next: WorkbenchState): readonly WorkbenchEffect[];
