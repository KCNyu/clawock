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

export type WorkbenchTab = 'tasks' | 'providers' | 'overview'
export type WorkbenchPhase = 'queue' | 'focus' | 'patrol' | 'stats' | 'history'
export type WorkbenchSheetKind = 'brief' | 'log' | 'timeline' | 'picker'

export interface WorkbenchToast {
  ok: boolean
  text: string
}

/** Where a task detail was opened from, so Back can return there (history is a layer). */
export interface WorkbenchOrigin {
  phase: 'queue' | 'history'
  tab: WorkbenchTab
  /** The history row to focus after Back (null for the task queue). */
  taskId: string | null
}

export interface WorkbenchState {
  phase: WorkbenchPhase
  tab: WorkbenchTab
  taskId: string | null
  origin: WorkbenchOrigin | null
  sheet: WorkbenchSheetKind | null
  toast: WorkbenchToast | null
}

export const WORKBENCH_TABS: readonly WorkbenchTab[] = ['tasks', 'providers', 'overview']
export const WORKBENCH_SHEETS: readonly WorkbenchSheetKind[] = ['brief', 'log', 'timeline', 'picker']

export const initialWorkbenchState: WorkbenchState = {
  phase: 'queue',
  tab: 'tasks',
  taskId: null,
  origin: null,
  sheet: null,
  toast: null,
}

export type WorkbenchAction =
  | { type: 'TAB'; tab: WorkbenchTab }
  | { type: 'SELECT_TASK'; id: string }
  | { type: 'OPEN_TASK'; id: string; mobile: boolean; from?: 'tasks' | 'history' }
  | { type: 'OPEN_PATROL' }
  | { type: 'OPEN_STATS' }
  | { type: 'OPEN_HISTORY' }
  | { type: 'BACK' }
  | { type: 'OPEN_SHEET'; sheet: WorkbenchSheetKind }
  | { type: 'CLOSE_SHEET' }
  | { type: 'TOAST'; ok: boolean; text: string }
  | { type: 'DISMISS_TOAST' }

export type WorkbenchActionType = WorkbenchAction['type']

/**
 * The legal edges, as data. `from` lists the phases an action may start in;
 * `guard` names the extra condition (the reducer and tests read the same
 * string, so the report and the implementation cannot drift).
 *
 * `to` is a description of the destination, not a literal state: the reducer
 * derives tab/taskId/origin/overlay from the current state.
 */
export const WORKBENCH_TRANSITIONS: Record<WorkbenchActionType, {
  from: readonly WorkbenchPhase[]
  to: string
  guard?: string
}> = {
  TAB: { from: ['queue'], to: 'queue(tab)', guard: 'sheet === null' },
  SELECT_TASK: { from: ['queue', 'focus'], to: 'same phase(id)', guard: 'sheet === null; id not empty' },
  OPEN_TASK: {
    from: ['queue', 'focus', 'history'],
    to: 'focus(id) | queue(tasks, id)',
    guard: 'queue.tab in tasks|overview | history; sheet === null; id not empty',
  },
  OPEN_PATROL: { from: ['queue'], to: 'patrol', guard: 'tab === overview && sheet === null' },
  OPEN_STATS: { from: ['queue'], to: 'stats', guard: 'tab === overview && sheet === null' },
  OPEN_HISTORY: { from: ['queue'], to: 'history', guard: 'tab === overview && sheet === null' },
  BACK: { from: ['focus', 'patrol', 'stats', 'history'], to: 'queue | history', guard: 'sheet === null' },
  OPEN_SHEET: { from: ['queue', 'focus'], to: 'same phase + sheet(kind)', guard: 'sheet === null && kind in WORKBENCH_SHEETS; queue also needs tasks tab + selected task (desktop detail column)' },
  CLOSE_SHEET: { from: ['queue', 'focus'], to: 'same phase', guard: 'sheet !== null' },
  TOAST: { from: ['queue', 'focus', 'patrol', 'stats', 'history'], to: 'same phase + toast', guard: 'text not empty' },
  DISMISS_TOAST: { from: ['queue', 'focus', 'patrol', 'stats', 'history'], to: 'same phase', guard: 'toast !== null' },
}

/** What a transition runs on entering/leaving a phase. Pure data; the page executes it. */
export type WorkbenchEffect =
  | 'focus:task-title'
  | 'focus:patrol-back'
  | 'focus:stats-back'
  | 'focus:history-back'
  | 'focus:task-row'
  | 'focus:history-row'
  | 'focus:overview-entry'
  | 'focus:sheet-trigger'
  | 'focus:sheet-close'
  | 'scroll:layer-top'
  | 'scroll:queue-restore'
  | 'subscribe:queue'
  | 'subscribe:balances'
  | 'subscribe:stats'

export interface WorkbenchPhaseEffects {
  enter: readonly WorkbenchEffect[]
  exit: readonly WorkbenchEffect[]
}

export const WORKBENCH_EFFECTS: Record<WorkbenchPhase, WorkbenchPhaseEffects> = {
  queue: {
    enter: ['scroll:queue-restore', 'subscribe:queue'],
    exit: ['scroll:layer-top'],
  },
  focus: {
    enter: ['focus:task-title', 'scroll:layer-top', 'subscribe:queue'],
    exit: ['focus:task-row'],
  },
  patrol: {
    enter: ['focus:patrol-back', 'scroll:layer-top', 'subscribe:queue'],
    exit: ['focus:overview-entry'],
  },
  stats: {
    enter: ['focus:stats-back', 'scroll:layer-top', 'subscribe:stats'],
    exit: ['focus:overview-entry'],
  },
  history: {
    enter: ['focus:history-back', 'scroll:layer-top', 'subscribe:queue'],
    exit: ['focus:overview-entry'],
  },
}

/** Phase-aware subscriptions: only the visible surface keeps its channel warm. */
export function workbenchSubscriptions(state: WorkbenchState): { balances: boolean; stats: boolean; queue: boolean } {
  return {
    balances: state.phase === 'queue' && state.tab === 'providers',
    stats: state.phase === 'stats' || (state.phase === 'queue' && state.tab === 'overview'),
    queue: true,
  }
}

function tabOfHistory(): WorkbenchTab { return 'overview' }

/** The one legality predicate. The reducer, the tests and the report all use it. */
export function isLegalWorkbenchAction(state: WorkbenchState, action: WorkbenchAction): boolean {
  const edge = WORKBENCH_TRANSITIONS[action.type]
  if (edge === undefined || !edge.from.includes(state.phase)) return false
  switch (action.type) {
    case 'TAB':
      return WORKBENCH_TABS.includes(action.tab) && state.sheet === null
    case 'SELECT_TASK':
      return state.sheet === null && typeof action.id === 'string' && action.id !== ''
    case 'OPEN_TASK':
      if (state.sheet !== null) return false
      if (typeof action.id !== 'string' || action.id === '') return false
      if (action.from === 'history') return state.phase === 'history'
      if (state.phase === 'focus') return true
      return state.phase === 'queue' && (state.tab === 'tasks' || state.tab === 'overview')
    case 'OPEN_PATROL':
    case 'OPEN_STATS':
    case 'OPEN_HISTORY':
      return state.phase === 'queue' && state.tab === 'overview' && state.sheet === null
    case 'BACK':
      return state.sheet === null
    case 'OPEN_SHEET':
      return state.sheet === null && WORKBENCH_SHEETS.includes(action.sheet)
        && (state.phase === 'focus' || (state.phase === 'queue' && state.tab === 'tasks' && state.taskId !== null))
    case 'CLOSE_SHEET':
      return state.sheet !== null && (state.phase === 'focus' || state.phase === 'queue')
    case 'TOAST':
      return typeof action.text === 'string' && action.text !== ''
    case 'DISMISS_TOAST':
      return state.toast !== null
    default:
      return false
  }
}

export interface WorkbenchReduceOptions {
  /** false = production: log the illegal edge and keep the current state. */
  strict?: boolean
  log?: (message: string) => void
}

function illegal(state: WorkbenchState, action: WorkbenchAction): string {
  return 'illegal workbench transition: ' + action.type + ' at ' + state.phase + '/' + state.tab
    + ' sheet=' + String(state.sheet)
}

/**
 * The single transition function. No other code may assign a view/overlay.
 */
export function reduceWorkbench(
  state: WorkbenchState,
  action: WorkbenchAction,
  options: WorkbenchReduceOptions = {},
): WorkbenchState {
  const strict = options.strict !== false
  if (!isLegalWorkbenchAction(state, action)) {
    const message = illegal(state, action)
    if (strict) throw new Error(message)
    ;(options.log ?? ((line: string): void => {
      if (typeof console !== 'undefined' && typeof console.warn === 'function') console.warn(line)
    }))(message)
    return state
  }
  switch (action.type) {
    case 'TAB':
      return { ...state, tab: action.tab, toast: state.toast }
    case 'SELECT_TASK':
      return { ...state, taskId: action.id, sheet: null, toast: null }
    case 'OPEN_TASK': {
      if (state.phase === 'focus') {
        return { ...state, taskId: action.id, sheet: null, toast: null }
      }
      const fromHistory = state.phase === 'history'
      const origin: WorkbenchOrigin = {
        phase: fromHistory ? 'history' : 'queue',
        tab: fromHistory ? tabOfHistory() : state.tab,
        taskId: fromHistory ? action.id : null,
      }
      return {
        ...state,
        phase: action.mobile ? 'focus' : 'queue',
        // On desktop the detail is the Tasks column; opening a history row
        // must show that column instead of leaving the reader on Overview.
        tab: action.mobile ? state.tab : 'tasks',
        taskId: action.id,
        origin,
        sheet: null,
        toast: null,
      }
    }
    case 'OPEN_PATROL':
    case 'OPEN_STATS':
    case 'OPEN_HISTORY':
      return {
        ...state,
        phase: action.type === 'OPEN_PATROL' ? 'patrol' : action.type === 'OPEN_STATS' ? 'stats' : 'history',
        origin: { phase: 'queue', tab: 'overview', taskId: null },
        sheet: null,
        toast: null,
      }
    case 'BACK': {
      const origin = state.origin
      if (state.phase === 'focus' && origin !== null && origin.phase === 'history') {
        return {
          ...state, phase: 'history', tab: 'overview', taskId: origin.taskId, origin: null, sheet: null, toast: null,
        }
      }
      return {
        ...state,
        phase: 'queue',
        tab: state.phase === 'focus' && origin !== null ? origin.tab : 'overview',
        // Desktop keeps the selection in the column; mobile unmounts the layer.
        taskId: state.phase === 'focus' ? state.taskId : origin?.taskId ?? null,
        origin: null,
        sheet: null,
        toast: null,
      }
    }
    case 'OPEN_SHEET':
      return { ...state, sheet: action.sheet }
    case 'CLOSE_SHEET':
      return { ...state, sheet: null }
    case 'TOAST':
      return { ...state, toast: { ok: action.ok, text: action.text } }
    case 'DISMISS_TOAST':
      return { ...state, toast: null }
    default:
      return state
  }
}

/**
 * Which effects a transition runs. Derived from the phase table plus the
 * focus-restore rule for Back and sheet close; no component invents its own.
 */
export function effectsFor(previous: WorkbenchState, next: WorkbenchState): readonly WorkbenchEffect[] {
  const effects: WorkbenchEffect[] = []
  if (previous.phase !== next.phase) {
    // focus -> history returns to the row that opened the detail, not the task
    // row that no longer exists; do not run the focus->queue restore first.
    if (!(previous.phase === 'focus' && next.phase === 'history')) {
      effects.push(...WORKBENCH_EFFECTS[previous.phase].exit)
    }
    effects.push(...WORKBENCH_EFFECTS[next.phase].enter)
  }
  if (previous.sheet === null && next.sheet !== null) effects.push('focus:sheet-close')
  if (previous.sheet !== null && next.sheet === null) effects.push('focus:sheet-trigger')
  if (next.phase === 'history' && previous.phase === 'focus') effects.push('focus:history-row')
  if (next.phase === 'queue' && previous.phase === 'focus' && next.origin === null && next.taskId !== null) {
    effects.push('focus:task-row')
  }
  return [...new Set(effects)]
}
