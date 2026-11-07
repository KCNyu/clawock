#!/usr/bin/env node
/**
 * Workbench view/overlay state machine: the transition table, not the page.
 *
 * Run: node tests/workbench_fsm.spec.js
 * CI:  ci.yml's Decision Studio plugin job runs it with the plugin contract.
 *
 * The point of this file is that every (state, action) pair is enumerated.
 * Legal pairs must land in a state that still satisfies the invariants; every
 * other pair must throw in strict mode and be ignored (logged) in production
 * mode. A test that only walks the happy path would let the next control add
 * an `if (openA && !openB)` exception again.
 */
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const test = require("node:test");

const PLUGIN = path.join(__dirname, "..", "examples", "dsh", "packages", "clawock-dsh");

let machine = null;
async function loadMachine() {
  if (machine !== null) return machine;
  let entry = null;
  globalThis.window = { __ModuleLoader__: { load(value) { entry = value; } } };
  await import(pathToFileURL(path.join(PLUGIN, "lib", "client.js")).href);
  assert.ok(entry, "client.js registers through the module loader");
  const react = {
    createElement: () => ({}), useEffect() {}, useId() { return "t"; },
    useRef() { return { current: null }; }, useState(value) { return [value, () => {}]; },
  };
  machine = entry.factory((id) => {
    if (id === "react") return react;
    if (id === "react-dom") return { createPortal: (children) => children };
    if (id === "@deepseek-ai/dsh-client-store") {
      return { defineStore: (spec) => ({ spec, create: () => ({ getSnapshot: () => spec.init(), subscribe: () => () => {} }) }) };
    }
    throw new Error("unexpected require in the state-machine test: " + id);
  });
  return machine;
}

const TABS = ["tasks", "providers", "overview"];
const PHASES = ["queue", "focus", "patrol", "stats", "history"];
const SHEETS = [null, "brief", "log", "timeline", "picker"];

function makeState(overrides = {}) {
  return {
    phase: "queue", tab: "tasks", taskId: null, origin: null, sheet: null, toast: null,
    ...overrides,
  };
}

function actions() {
  const list = [];
  for (const tab of TABS) list.push({ label: "TAB " + tab, action: { type: "TAB", tab } });
  list.push({ label: "SELECT_TASK t1", action: { type: "SELECT_TASK", id: "t1" } });
  list.push({ label: "OPEN_TASK mobile", action: { type: "OPEN_TASK", id: "t1", mobile: true, from: "tasks" } });
  list.push({ label: "OPEN_TASK desktop", action: { type: "OPEN_TASK", id: "t1", mobile: false, from: "tasks" } });
  list.push({ label: "OPEN_TASK from history", action: { type: "OPEN_TASK", id: "t1", mobile: true, from: "history" } });
  list.push({ label: "OPEN_PATROL", action: { type: "OPEN_PATROL" } });
  list.push({ label: "OPEN_STATS", action: { type: "OPEN_STATS" } });
  list.push({ label: "OPEN_HISTORY", action: { type: "OPEN_HISTORY" } });
  list.push({ label: "BACK", action: { type: "BACK" } });
  for (const sheet of SHEETS.slice(1)) list.push({ label: "OPEN_SHEET " + sheet, action: { type: "OPEN_SHEET", sheet } });
  list.push({ label: "CLOSE_SHEET", action: { type: "CLOSE_SHEET" } });
  list.push({ label: "TOAST", action: { type: "TOAST", ok: true, text: "recorded" } });
  list.push({ label: "DISMISS_TOAST", action: { type: "DISMISS_TOAST" } });
  return list;
}

/** Independent reference predicate: deliberately not `isLegalWorkbenchAction`. */
function expectedLegal(state, action) {
  const sheetFree = state.sheet === null;
  switch (action.type) {
    case "TAB":
      return state.phase === "queue" && TABS.includes(action.tab) && sheetFree;
    case "SELECT_TASK":
      return (state.phase === "queue" || state.phase === "focus") && sheetFree && action.id !== "";
    case "OPEN_TASK":
      if (action.from === "history") return state.phase === "history" && sheetFree && action.id !== "";
      if (state.phase === "focus") return sheetFree && action.id !== "";
      return state.phase === "queue" && (state.tab === "tasks" || state.tab === "overview") && sheetFree && action.id !== "";
    case "OPEN_PATROL":
    case "OPEN_STATS":
    case "OPEN_HISTORY":
      return state.phase === "queue" && state.tab === "overview" && sheetFree;
    case "BACK":
      return ["focus", "patrol", "stats", "history"].includes(state.phase) && sheetFree;
    case "OPEN_SHEET":
      return sheetFree && SHEETS.slice(1).includes(action.sheet)
        && (state.phase === "focus" || (state.phase === "queue" && state.tab === "tasks" && state.taskId !== null));
    case "CLOSE_SHEET":
      return state.sheet !== null && (state.phase === "focus" || state.phase === "queue");
    case "TOAST":
      return action.text !== "";
    case "DISMISS_TOAST":
      return state.toast !== null;
    default:
      return false;
  }
}

function stateMatrix() {
  const states = [];
  for (const phase of PHASES) {
    for (const tab of TABS) {
      for (const sheet of SHEETS) {
        for (const taskId of [null, "t1"]) {
          for (const toast of [null, { ok: true, text: "x" }]) {
            const origin = phase === "focus"
              ? (tab === "overview" ? { phase: "history", tab: "overview", taskId: "h1" } : { phase: "queue", tab, taskId: null })
              : phase === "history" ? { phase: "queue", tab: "overview", taskId: null } : null;
            // Only reachable combinations: a sheet lives inside focus, or in
            // the desktop Tasks column with a selected task.
            if (sheet !== null && phase !== "focus" && !(phase === "queue" && tab === "tasks" && taskId !== null)) continue;
            states.push(makeState({ phase, tab, sheet, taskId, toast, origin }));
          }
        }
      }
    }
  }
  return states;
}

function assertInvariants(next, label) {
  assert.ok(PHASES.includes(next.phase), label + ": phase stays in the set");
  assert.ok(TABS.includes(next.tab), label + ": tab stays in the set");
  assert.ok(next.sheet === null || ((next.phase === "focus"
    || (next.phase === "queue" && next.tab === "tasks" && next.taskId !== null)) && SHEETS.includes(next.sheet)),
    label + ": a sheet exists only over a visible detail");
  assert.ok(next.toast === null || (typeof next.toast.text === "string" && next.toast.text !== ""),
    label + ": a toast carries text");
  assert.ok(next.taskId === null || typeof next.taskId === "string", label + ": task id is a string");
}

test("workbench FSM: the table covers every action exactly once", async () => {
  const api = await loadMachine();
  const types = [...new Set(actions().map((entry) => entry.action.type))].sort();
  assert.deepEqual(Object.keys(api.WORKBENCH_TRANSITIONS).sort(), types,
    "each action has one table row and the table has no orphan row");
  for (const type of types) {
    const row = api.WORKBENCH_TRANSITIONS[type];
    assert.ok(Array.isArray(row.from) && row.from.length > 0, type + ": from is a non-empty phase list");
    assert.ok(row.from.every((phase) => PHASES.includes(phase)), type + ": from names real phases");
    assert.equal(typeof row.to, "string", type + ": to is documented");
    assert.ok(row.to.length > 0, type + ": to is not empty");
  }
  assert.deepEqual(Object.keys(api.WORKBENCH_EFFECTS).sort(), [...PHASES].sort(),
    "each phase declares its entry/exit effects");
  for (const phase of PHASES) {
    const effects = api.WORKBENCH_EFFECTS[phase];
    assert.ok(Array.isArray(effects.enter) && Array.isArray(effects.exit), phase + ": enter and exit are arrays");
  }
});

test("workbench FSM: every legal pair passes and every illegal pair is rejected", async () => {
  const api = await loadMachine();
  const states = stateMatrix();
  const allActions = actions();
  let legal = 0;
  let illegal = 0;
  for (const state of states) {
    for (const { label, action } of allActions) {
      const want = expectedLegal(state, action);
      const where = label + " from " + state.phase + "/" + state.tab + " sheet=" + String(state.sheet)
        + " toast=" + (state.toast === null ? "null" : "set");
      assert.equal(api.isLegalWorkbenchAction(state, action), want, "predicate disagrees: " + where);
      if (!want) {
        illegal += 1;
        assert.throws(() => api.reduceWorkbench(state, action), /illegal workbench transition/,
          "illegal transition was not rejected: " + where);
        const logged = [];
        const same = api.reduceWorkbench(state, action, { strict: false, log: (line) => logged.push(line) });
        assert.equal(same, state, "production mode must keep the current state: " + where);
        assert.equal(logged.length, 1, "production mode logs the rejected edge exactly once: " + where);
        assert.match(logged[0], /illegal workbench transition/, "log names the illegal edge: " + where);
        continue;
      }
      legal += 1;
      const next = api.reduceWorkbench(state, action);
      assertInvariants(next, where);
    }
  }
  assert.ok(legal > 100, "legal matrix is not vacuous (" + legal + " pairs)");
  assert.ok(illegal > 1000, "illegal matrix is not vacuous (" + illegal + " pairs)");
});

test("workbench FSM: the four detail layers are exclusive and Back restores the origin", async () => {
  const api = await loadMachine();
  let state = api.reduceWorkbench(api.initialWorkbenchState, { type: "TAB", tab: "overview" });
  state = api.reduceWorkbench(state, { type: "OPEN_PATROL" });
  assert.equal(state.phase, "patrol");
  state = api.reduceWorkbench(state, { type: "BACK" });
  assert.deepEqual([state.phase, state.tab], ["queue", "overview"], "patrol returns to Overview");
  state = api.reduceWorkbench(state, { type: "OPEN_STATS" });
  assert.equal(state.phase, "stats");
  state = api.reduceWorkbench(state, { type: "BACK" });
  state = api.reduceWorkbench(state, { type: "OPEN_HISTORY" });
  assert.equal(state.phase, "history");
  // A history row opens focus; Back returns to History, not to the queue.
  state = api.reduceWorkbench(state, { type: "OPEN_TASK", id: "h1", mobile: true, from: "history" });
  assert.equal(state.phase, "focus");
  assert.deepEqual(state.origin, { phase: "history", tab: "overview", taskId: "h1" });
  state = api.reduceWorkbench(state, { type: "BACK" });
  assert.deepEqual([state.phase, state.tab, state.taskId], ["history", "overview", "h1"]);
  // Only one layer can be entered: Patrol cannot be opened from focus/stats.
  assert.throws(() => api.reduceWorkbench(makeState({ phase: "stats", tab: "overview" }), { type: "OPEN_PATROL" }),
    /illegal workbench transition/);
  assert.throws(() => api.reduceWorkbench(makeState({ phase: "focus", tab: "tasks", taskId: "t1" }), { type: "OPEN_STATS" }),
    /illegal workbench transition/);
});

test("workbench FSM: overlays do not block the main phase", async () => {
  const api = await loadMachine();
  let state = makeState({ phase: "focus", tab: "tasks", taskId: "t1", origin: { phase: "queue", tab: "tasks", taskId: null } });
  state = api.reduceWorkbench(state, { type: "OPEN_SHEET", sheet: "brief" });
  assert.equal(state.phase, "focus");
  assert.equal(state.sheet, "brief");
  state = api.reduceWorkbench(state, { type: "TOAST", ok: true, text: "recorded" });
  assert.equal(state.phase, "focus", "a toast never changes the phase");
  assert.equal(state.sheet, "brief", "a toast does not replace an open sheet");
  assert.equal(state.toast.text, "recorded");
  assert.throws(() => api.reduceWorkbench(state, { type: "BACK" }), /illegal workbench transition/,
    "Back is blocked while the sheet is open; Escape closes the sheet first");
  state = api.reduceWorkbench(state, { type: "DISMISS_TOAST" });
  state = api.reduceWorkbench(state, { type: "CLOSE_SHEET" });
  assert.equal(state.sheet, null);
  assert.equal(state.phase, "focus");
  state = api.reduceWorkbench(state, { type: "BACK" });
  assert.deepEqual([state.phase, state.tab], ["queue", "tasks"]);
});

test("workbench FSM: effects name the focus and scroll each edge runs", async () => {
  const api = await loadMachine();
  const queue = api.initialWorkbenchState;
  const focus = api.reduceWorkbench(queue, { type: "OPEN_TASK", id: "t1", mobile: true, from: "tasks" });
  const focusEffects = api.effectsFor(queue, focus);
  assert.ok(focusEffects.includes("focus:task-title"), "entering focus focuses the title");
  assert.ok(focusEffects.includes("scroll:layer-top"), "entering a layer starts at the top");
  const back = api.reduceWorkbench(focus, { type: "BACK" });
  const backEffects = api.effectsFor(focus, back);
  assert.ok(backEffects.includes("focus:task-row"), "Back restores the task row");
  assert.ok(backEffects.includes("scroll:queue-restore"), "Back restores the queue scroll position");
  const overview = api.reduceWorkbench(api.reduceWorkbench(queue, { type: "TAB", tab: "overview" }), { type: "OPEN_PATROL" });
  const patrolBack = api.reduceWorkbench(overview, { type: "BACK" });
  assert.ok(api.effectsFor(overview, patrolBack).includes("focus:overview-entry"),
    "Back from a layer restores the overview entry");
  const sheet = api.reduceWorkbench(focus, { type: "OPEN_SHEET", sheet: "log" });
  assert.ok(api.effectsFor(focus, sheet).includes("focus:sheet-close"), "opening a sheet focuses its close control");
  assert.ok(api.effectsFor(sheet, focus).includes("focus:sheet-trigger"), "closing a sheet restores its trigger");
  const history = api.reduceWorkbench(api.reduceWorkbench(queue, { type: "TAB", tab: "overview" }), { type: "OPEN_HISTORY" });
  const fromHistory = api.reduceWorkbench(history, { type: "OPEN_TASK", id: "h1", mobile: true, from: "history" });
  const backToHistory = api.reduceWorkbench(fromHistory, { type: "BACK" });
  const effects = api.effectsFor(fromHistory, backToHistory);
  assert.ok(effects.includes("focus:history-row"), "Back from a history-opened task restores the history row");
  assert.ok(!effects.includes("focus:task-row"), "it must not try to focus a task row that is not mounted");
});

test("workbench FSM: subscriptions follow the visible surface", async () => {
  const api = await loadMachine();
  assert.deepEqual(api.workbenchSubscriptions(makeState({ phase: "queue", tab: "providers" })),
    { balances: true, stats: false, queue: true });
  assert.deepEqual(api.workbenchSubscriptions(makeState({ phase: "queue", tab: "overview" })),
    { balances: false, stats: true, queue: true });
  assert.deepEqual(api.workbenchSubscriptions(makeState({ phase: "stats", tab: "overview" })),
    { balances: false, stats: true, queue: true });
  assert.deepEqual(api.workbenchSubscriptions(makeState({ phase: "focus", tab: "tasks" })),
    { balances: false, stats: false, queue: true });
});
