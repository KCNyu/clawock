#!/usr/bin/env node
/**
 * Decision Mind plugin tests (clawock-dsh node + client halves).
 *
 * Run: node tests/decision_studio_plugin.spec.js
 * CI: ci.yml runs it when plugin files change.
 *
 * What is verified without a browser:
 *   - scan.js: workspace run listing, run-id path-safety boundary
 *   - ledger.js: decision ledger / portfolio / plan readers over OpenClaw
 *     desk files (whatever OpenClaw produces, this plugin can show)
 *   - client.js: module-loader registration, mounted Remote face, display
 *     projection, and a stub-react render of the ledger cards
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const test = require("node:test");

const PLUGIN = path.join(__dirname, "..", "examples", "dsh", "packages", "clawock-dsh");

// The balance reader keeps each provider's last good reading under this directory so another
// process can fall back on it. Tests must neither read this machine's readings nor leave theirs.
process.env.CLAWOCK_DSH_STATE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-state-"));
process.on("exit", () => fs.rmSync(process.env.CLAWOCK_DSH_STATE_DIR, { recursive: true, force: true }));

// No `document` global here on purpose: the bundle must load with no DOM at
// all (#729 — nothing may touch `document` at module scope). The CSS-contract
// test below installs a scoped stub for the one assertion that needs the tag.
async function withDocumentStub(run) {
  const tags = [];
  const previous = Object.prototype.hasOwnProperty.call(globalThis, "document")
    ? globalThis.document : undefined;
  globalThis.document = {
    createElement() { return { dataset: {}, textContent: "" }; },
    querySelector() { return null; },
    head: { appendChild(el) { tags.push(el); } },
  };
  try { return await run(tags); } finally {
    if (previous === undefined) delete globalThis.document; else globalThis.document = previous;
  }
}

function makeDesk() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-mind-"));
  fs.mkdirSync(path.join(root, "memory"), { recursive: true });
  fs.writeFileSync(path.join(root, "memory", "decisions.jsonl"), [
    JSON.stringify({
      decision_id: "dec-legacy1", plan_date: "2026-08-10", ticker: "00100", leg: "HK",
      action: "trim_on_rebound", confidence: 0.7, driven_by: "technical",
      condition: { description: "跌破 730 减 20 股", price: 730.0, type: "price_below" },
      evaluation: { outcome: "not_triggered", status: "not_triggered" },
      execution: { status: "unknown" },
    }),
    JSON.stringify({
      schema_version: 0, decision_id: "dec-conv1", source: "conversation",
      subject: { ticker: "00100", market: "HK", currency: "HKD" },
      decided_at: "2026-08-16T13:45:00+08:00", action: "reject", confidence: 0.65,
      driven_by: "fundamental",
      mind: { bull: { summary: "营收 +159%", evidence: [] }, bear: { summary: "资不抵债", evidence: [] },
              thesis: "先活下来", invalidation: ["站回 340"] },
      emotion: { pressure: "averaging_down", note: "忍住没加" },
      execution: { status: "unknown" },
    }),
    "not valid json line that must be skipped",
    "",
  ].join("\n"));
  fs.writeFileSync(path.join(root, "portfolio.json"), JSON.stringify({
    last_updated: "2026-08-16 13:42 HKT",
    portfolios: {
      hk_stocks: { currency: "HKD", holdings: [
        { ticker: "00100", name: "MINIMAX-W", shares: 120, cost_basis: 553.08, current_price: 329.0, pnl_percent: -40.5,
          trades: [
            { date: "2026-08-04", action: "buy", shares: 20, price: 230.0, note: "用户报告成交(微信,15:31 HKT)" },
            { date: "2026-07-10", action: "buy", shares: 20, price: 260.0, note: "解禁二次探底加仓" },
          ] },
      ] },
      us_stocks: { currency: "USD", holdings: [
        { ticker: "NVDA", shares: 0, current_price: 213.0, pnl_percent: 0 },
        { ticker: "PLTU", shares: 5, current_price: 49.24, pnl_percent: 0,
          trades: [
            { date: "2026-08-13", action: "sell", shares: 5, price: 50, realized_pnl: 45.21428571428572, note: "用户报告成交(微信),$50 卖出剩余 5 股,PLTU 清仓" },
            { date: "2026-08-08", action: "sell", shares: 5, price: 49.0, realized_pnl: 40.21, note: "用户报告成交(微信,01:08 HKT),PLTU 减仓 50%" },
          ] },
      ] },
    },
  }));
  fs.writeFileSync(path.join(root, "memory", "2026-08-10-plan.json"), JSON.stringify({
    schema_version: 2, title: "盘前 plan", decisions: [{ ticker: "00100" }, { ticker: "07226" }],
  }));
  fs.writeFileSync(path.join(root, "memory", "2026-08-15-plan.json"), JSON.stringify({
    schema_version: 2, decisions: [],
  }));
  return root;
}

test("scan: run ids are the path-safety boundary", async () => {
  const scan = await import(pathToFileURL(path.join(PLUGIN, "lib", "scan.js")).href);
  for (const bad of ["..", "../secret", "abc", "", null, 42]) {
    assert.throws(() => scan.getRun("/tmp", bad), TypeError, `run id ${JSON.stringify(bad)} must be rejected`);
  }
});

test("ledger: reads decisions.jsonl, skips malformed lines, keeps desk entries", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = makeDesk();
  try {
    const { entries } = ledger.readLedger(root);
    assert.equal(entries.length, 2, "malformed line must be skipped, not fatal");
    const conv = entries.find((d) => d.source === "conversation");
    assert.equal(conv.mind.bear.summary, "资不抵债");
    assert.equal(conv.emotion.pressure, "averaging_down");
    const brief = entries.find((d) => d.plan_date === "2026-08-10");
    assert.equal(brief.action, "trim_on_rebound");
    assert.deepEqual(ledger.readLedger(path.join(root, "nope")).entries, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("ledger: unreadable decisions preserve portfolio traces and the ledger path", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = makeDesk();
  const ledgerPath = path.join(root, "memory", "decisions.jsonl");
  try {
    fs.unlinkSync(ledgerPath);
    fs.mkdirSync(ledgerPath);
    assert.deepEqual(ledger.readLedger(root), { entries: [], path: ledgerPath });
    assert.ok(ledger.readTraces(root).trades.length > 0);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("ledger: portfolio summarizes holdings per book", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = makeDesk();
  try {
    const { books, lastUpdated } = ledger.readPortfolio(root);
    assert.equal(lastUpdated, "2026-08-16 13:42 HKT");
    assert.equal(books.length, 2, "books with no positions must be dropped, held books kept");
    const us = books.find((b) => b.name === "us_stocks");
    assert.equal(us.holdings.length, 1, "zero-share NVDA row must be dropped, PLTU kept");
    assert.equal(us.holdings[0].ticker, "PLTU");
    const hk = books.find((b) => b.name === "hk_stocks");
    assert.equal(hk.currency, "HKD");
    assert.equal(hk.holdings.length, 1);
    assert.equal(hk.holdings[0].ticker, "00100");
    assert.equal(hk.holdings[0].pnlPct, -40.5);
    // actual operations flattened across books, newest first
    const { trades } = ledger.readPortfolio(root);
    assert.equal(trades.length, 4);
    assert.equal(trades[0].ticker, "PLTU"); // 2026-08-13 newest
    assert.equal(trades[0].realizedPnl.toFixed(2), "45.21");
    assert.equal(trades[0].market, "US");
    assert.equal(trades[3].ticker, "00100");
    assert.deepEqual(ledger.readPortfolio(path.join(root, "nope")).books, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("ledger: malformed shares cannot reject the portfolio or traces wire (#1821)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const { TYPERT } = await import(pathToFileURL(path.join(PLUGIN, "lib", "typert.host.js")).href);
  const root = makeDesk();
  try {
    const file = path.join(root, "portfolio.json");
    const doc = JSON.parse(fs.readFileSync(file, "utf8"));
    const holdings = doc.portfolios.us_stocks.holdings;
    holdings.push({ ticker: "BAD", shares: "20股", trades: [
      { date: "2026-08-14", action: "buy", shares: "abc", price: 10 },
    ] });
    holdings[1].trades.push({ date: "2026-08-15", action: "buy", shares: "20", price: 51 });
    fs.writeFileSync(file, JSON.stringify(doc));

    const portfolio = ledger.readPortfolio(root);
    assert.equal(portfolio.books.find((b) => b.name === "us_stocks").holdings.length, 1);
    assert.equal(portfolio.trades.length, 5, "only the malformed fill is skipped");
    assert.equal(portfolio.trades[0].shares, 20, "numeric strings remain valid");
    assert.ok(portfolio.trades.every((t) => Number.isFinite(t.shares)));
    const traces = ledger.readTraces(root);
    for (const [method, result] of [["portfolio", portfolio], ["traces", traces]]) {
      const invocation = TYPERT.invocations.find((i) => i.id === `clawock-dsh#clawockStudio/${method}`);
      const wire = JSON.parse(JSON.stringify({ workspaceKey: "test", signature: "test", ...result }));
      assert.equal(invocation.result.create().safeParse(wire).success, true, `${method} strict wire must accept surviving rows`);
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("ledger: a book sold down to zero keeps its trades (#1530)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = makeDesk();
  try {
    const file = path.join(root, "portfolio.json");
    const doc = JSON.parse(fs.readFileSync(file, "utf8"));
    for (const h of doc.portfolios.us_stocks.holdings) h.shares = 0;
    fs.writeFileSync(file, JSON.stringify(doc));
    const { books, trades } = ledger.readPortfolio(root);
    assert.deepEqual(books.map((b) => b.name), ["hk_stocks"], "the emptied book is still not shown");
    assert.equal(trades.length, 4, "the emptied book's fills must stay on the trade log");
    const usRealized = trades.filter((t) => t.currency === "USD").reduce((s, t) => s + t.realizedPnl, 0);
    assert.equal(usRealized.toFixed(2), "85.42");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("ledger: plans list newest first with decision counts", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = makeDesk();
  try {
    const { plans } = ledger.readPlans(root);
    assert.equal(plans.length, 2);
    assert.equal(plans[0].date, "2026-08-15");
    assert.equal(plans[0].decisions, 0);
    assert.equal(plans[1].date, "2026-08-10");
    assert.equal(plans[1].decisions, 2);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

let importCounter = 0;
function clientUrl() {
  importCounter += 1;
  return pathToFileURL(path.join(PLUGIN, "lib", "client.js")).href + "?v=" + importCounter;
}

// Effect cleanups the stub collects: the view's poll effect arms a real
// interval, and a leaked one would keep the test runner's loop alive.
let reactEffectCleanups = [];
function disposeReactEffects() {
  for (const cleanup of reactEffectCleanups) {
    if (typeof cleanup === "function") cleanup();
  }
  reactEffectCleanups = [];
}

function makeReactStub() {
  let reactIdCounter = 0;

  // Cursor-based slots: useState(n) binds to slot n for EVERY render, so a
  // setter write survives re-renders the way React state does. Callers that
  // render the same component twice and want fresh state call _resetCursor()
  // first (the old append-per-render behaviour, kept for older tests).
  const slots = [];
  let cursor = 0;
  return {
    _resetCursor() { cursor = 0; },
    createElement(type, props, ...children) {
      if (typeof type === "function") {
        // Mini-renderer: invoke function components so their subtrees appear.
        return type(Object.assign({}, props, { children }));
      }
      return { type, props: props || {}, children };
    },
    useState(initial) {
      const index = cursor++;
      if (index >= slots.length) slots.push(typeof initial === "function" ? initial() : initial);
      return [
        slots[index],
        (updater) => {
          slots[index] = typeof updater === "function" ? updater(slots[index]) : updater;
        },
      ];
    },
    useEffect(fn) {
      reactEffectCleanups.push(fn()); // runs like a mount; cleanup is collected
    },
    useRef(initial) {
      // The views use refs for roots, mount flags and timers; without a DOM
      // the scroll/outside-click effects simply do nothing. Keep each ref
      // stable across renders as React does: detail requests use it to reject
      // replies that arrive after another task has opened.
      const index = cursor++;
      if (index >= slots.length) slots.push({ current: initial === undefined ? null : initial });
      return slots[index];
    },
    useId() {
      // React 18 has it; the balance glyph keys its SVG mask on it so two
      // mounted glyphs cannot share one document-global id.
      return "t" + (reactIdCounter += 1);
    },
  };
}

/** Balance fixtures: per-provider rows and the whole-chip envelope. */
const AS_OF = "2026-08-23T10:00:00.000Z";
/** The one reset-stamp format every provider shares (balance.ts formatReset). */
const RESET_STAMP = /^(今天|明天|\d{1,2}\/\d{1,2} 周[日一二三四五六]) \d{2}:\d{2}$/;
const DS_ROW_OK = {
  provider: "deepseek", label: "DeepSeek",
  result: { configured: true, snapshot: { isAvailable: true, unit: "money", currency: "CNY", totalBalance: "110.00", grantedBalance: "10.00", toppedUpBalance: "100.00", asOf: AS_OF, note: "", windows: [] }, status: "fresh", low: false, message: null, threshold: 20, refreshMs: 60000 },
};
const MM_ROW_OK = {
  provider: "minimax", label: "MiniMax",
  result: { configured: true, snapshot: { isAvailable: true, unit: "pct", currency: "", totalBalance: "24", grantedBalance: "", toppedUpBalance: "", asOf: AS_OF, note: "5h 窗口已使用 24% · 周窗口已使用 10%", windows: [{ label: "5h", percent: 24, resetAt: "21:00" }, { label: "周", percent: 10, resetAt: "周四 21:00" }] }, status: "fresh", low: false, message: null, threshold: 20, refreshMs: 60000 },
};
const CL_ROW_OK = {
  provider: "claude", label: "Claude",
  result: { configured: true, snapshot: { isAvailable: true, unit: "pct", currency: "", totalBalance: "36", grantedBalance: "", toppedUpBalance: "", asOf: AS_OF, note: "会话窗口已使用 36% · 本周已使用 69%", windows: [{ label: "会话", percent: 36, resetAt: "10:00" }, { label: "本周", percent: 69, resetAt: "周四 10:00" }] }, status: "fresh", low: false, message: null, threshold: 20, refreshMs: 60000 },
};
const CX_ROW_OK = {
  provider: "codex", label: "Codex",
  result: { configured: true, snapshot: { isAvailable: true, unit: "pct", currency: "", totalBalance: "18", grantedBalance: "", toppedUpBalance: "", asOf: AS_OF, note: "5h 窗口已使用 18% · 周窗口已使用 41%", windows: [{ label: "5h", percent: 18, resetAt: "15:00" }, { label: "周", percent: 41, resetAt: "周四 10:00" }] }, status: "fresh", low: false, message: null, threshold: 20, refreshMs: 300000 },
};
const BALANCES_OK = { providers: [DS_ROW_OK, MM_ROW_OK, CL_ROW_OK, CX_ROW_OK], refreshMs: 60000 };
const QUIET_BALANCES = { providers: [], refreshMs: 60000 };
/** The balances channel stub for renders that don't exercise the chip. */
function balanceProps() {
  return { cachedBalances: () => null, fetchBalances: async () => QUIET_BALANCES };
}
/** Chip selection store stub: same surface the registration store provides. */
function makeBalanceStoreStub(initial = null) {
  let s = { selected: initial };
  return {
    useStore: (sel) => sel(s),
    actions: { select(provider) { s = { ...s, selected: provider }; } },
    _get: () => s,
  };
}

/** defineStore surface from the runtime stub: the factory builds its store
 *  handle at apply time, so the stub must provide the contract. */
function makeRuntimeStub(counter) {
  return {
    defineStore(spec) {
      if (counter) counter.calls += 1;
      return {
        spec,
        create: () => ({
          getSnapshot: () => spec.init(),
          subscribe: () => () => {},
          actions: {},
        }),
      };
    },
  };
}

/** Per-session store stub mirroring the DSH PropsStore share
 *  (`useStore` selector + baked `actions`), so tests can drive the view's
 *  UI state exactly the way the real slot renderer would. */
function makeStoreStub() {
  let s = { filter: "all", open: null, visibleDateCount: 3, foldedDates: [], scrollTop: 0 };
  const actions = {
    setFilter: (f) => { s = { ...s, filter: f }; },
    toggleOpen: (key) => { s = { ...s, open: s.open === key ? null : key }; },
    showMoreDates: (n) => { s = { ...s, visibleDateCount: s.visibleDateCount + n }; },
    resetDates: () => { s = { ...s, visibleDateCount: 3 }; },
    toggleDate: (date) => {
      s = { ...s, foldedDates: s.foldedDates.includes(date)
        ? s.foldedDates.filter((d) => d !== date)
        : [...s.foldedDates, date] };
    },
    setScrollTop: (v) => { s = { ...s, scrollTop: v }; },
  };
  return { useStore: (sel) => sel(s), actions };
}

/**
 * The `t` seat the host synthesizes from `locale: LOCALE_NS`, built from the
 * bundle's own zh dictionary. Tests render the zh surface by default (the
 * assertions are written against it); the en dictionary gets its own test.
 */
function translatorFor(api, locale = "zh") {
  return api.createTranslator(api.dictionaries[locale]);
}


async function loadClient() {
  let loaded = null;
  globalThis.window = { __ModuleLoader__: { load(entry) { loaded = entry; } } };
  await import(clientUrl());
  assert.ok(loaded, "client.js must register through the module loader");
  // The client portals its foot panel to <body> through react-dom. The test
  // tree is not a DOM, so transparently answer that module for every caller's
  // require function; createPortal returns its children unchanged.
  const factory = loaded.factory;
  return {
    ...loaded,
    factory(requireFn) {
      return factory((id) => (id === "react-dom" ? { createPortal: (children) => children } : requireFn(id)));
    },
  };
}

test("client: registers the Decision Mind tab and mounts the remote face", async () => {
  const loaded = await loadClient();
  assert.equal(loaded.id, "clawock-dsh");
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  // `layout` stays listed although the plugin only probes it. `ctx.get` cannot
  // replace it here: the probe runs inside apply, and ctx.get does not wait —
  // it returned undefined and dropped the chip into the header seat (measured
  // live 2026-09-19). The seat assertions further down are what pin the probe.
  // `locale` is a hard dependency too: without the registry there is no `t`
  // seat, and every registration in this bundle declares the namespace.
  assert.deepEqual(api.inject, ["slots", "remote", "layout", "locale"]);

  const remoteFace = {
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
    traces: async () => ({ ok: true, value: { workspaceKey: "ws1", signature: "sig1", trades: [], rate: null } }),
    get: async (runId) => ({ ok: true, value: { runId } }),
    balance: async () => ({ ok: true, value: BALANCES_OK }),
  };
  const ctx = {
    effect() {},
    // This bundle owns one dictionary namespace; `apply` must register it on
    // the caller's fiber (the effect's disposer) rather than module state.
    locale: {
      register(ns, dicts) {
        assert.equal(ns, api.LOCALE_NS, "apply must register this bundle's namespace");
        assert.deepEqual(Object.keys(dicts).sort(), ["en", "zh"], "both shipped locales");
        return () => {};
      },
    },
    // The injected face is absent here, which is exactly the pre-0.1.5 host
    // the header chip exists for.
    get() { return remoteFace; },
    slots: {
      inject(name, fn) { (this._seats ??= []).push(name); (this._fns ??= []).push(fn); },
      register(definition, Component) { (this._regs ??= []).push({ definition, Component }); },
    },
    remote: {
      $mount: async (descriptors) => {
        // Eleven: the eight read methods, taskStats (the chip's lazy stats read),
        // queueAction (the task chip's one write door) and workbenchAction
        // (the workbench's continue/modify/stop presets through dispatch.sh).
        assert.equal(descriptors.descriptors.length, 11);
        const queueDesc = descriptors.descriptors.find((d) => d.method === "taskQueue");
        assert.ok(queueDesc, "taskQueue descriptor present (hand-carried wire, see build.mjs)");
        assert.equal(queueDesc.parameters.length, 1, "taskQueue(force) must declare its argument");
        const workbenchDesc = descriptors.descriptors.find((d) => d.method === "workbenchAction");
        assert.ok(workbenchDesc, "workbenchAction descriptor present (hand-carried wire, see build.mjs)");
        assert.deepEqual(workbenchDesc.parameters.map((p) => p.name), ["action", "id"],
          "workbenchAction(action, id) must declare both arguments");
        const statsDesc = descriptors.descriptors.find((d) => d.method === "taskStats");
        assert.ok(statsDesc, "taskStats descriptor present (hand-carried wire, see build.mjs)");
        assert.deepEqual(statsDesc.parameters.map((p) => p.name), ["days", "since", "patrol"],
          "taskStats(days, since, patrol) must declare all three arguments");
        const actionDesc = descriptors.descriptors.find((d) => d.method === "queueAction");
        assert.ok(actionDesc, "queueAction descriptor present (hand-carried wire, see build.mjs)");
        assert.deepEqual(actionDesc.parameters.map((p) => p.name), ["action", "id", "arg"],
          "queueAction(action, id, arg) must declare all three arguments");
        // gateway invoke() validates args against descriptor.parameters.length —
        // get(runId) must declare its argument or every call would throw.
        const getDesc = descriptors.descriptors.find((d) => d.method === "get");
        assert.ok(getDesc, "get descriptor present");
        assert.equal(getDesc.parameters.length, 1, "get(runId) must declare its argument");
        assert.equal(getDesc.parameters[0].name, "runId");
        // The balance box rides the same Remote face: its descriptor must
        // declare the force argument the host's balance(force) takes.
        const balDesc = descriptors.descriptors.find((d) => d.method === "balance");
        assert.ok(balDesc, "balance descriptor present");
        assert.equal(balDesc.parameters.length, 1, "balance(force) must declare its argument");
        assert.equal(balDesc.parameters[0].name, "force");
      },
    },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  // Two registrations, two different seats: the tab ring carries Decision
  // Mind ONLY (the standalone 余额 tab lasted one session), and account
  // status lives in the session header's utilities seat as app chrome.
  assert.deepEqual(ctx.slots._seats, ["conversation.view", "conversation.session.header.utilities"],
    "tab ring for decisions, utilities seat for account chrome — nothing else");
  assert.equal(ctx.slots._regs.length, 2, "tab + header utility, nothing else");
  const registered = ctx.slots._regs.find((r) => r.definition.id === "decision-studio").definition;
  const chipReg = ctx.slots._regs.find((r) => r.definition.id === "provider-balance");
  assert.ok(chipReg, "the balance chip is registered");
  assert.equal(registered.order, 30);
  assert.equal(registered.label(), "Decision Mind");
  assert.equal(chipReg.definition.name, "conversation.session.header.utilities",
    "the chip must ride the utilities seat, never the tab ring");
  assert.equal(chipReg.definition.order, 90);
  for (const reg of ctx.slots._regs) {
    assert.equal(reg.definition.locale, api.LOCALE_NS,
      reg.definition.id + " must declare the dictionary namespace or its copy cannot translate");
  }
  // Official registration store: UI state survives the ring's unmount/remount.
  assert.ok(registered.store, "registration must declare a per-session store");
  assert.deepEqual(registered.store.spec.init(), { filter: "all", open: null, visibleDateCount: 3, foldedDates: [], scrollTop: 0 });

  const injected = registered.inject("s1");
  // The inject face is the view's only live-data channel: a snapshot reader
  // plus a fetch that reports whether the host answered actually changed.
  assert.equal(typeof injected.cachedTraces, "function");
  assert.equal(typeof injected.fetchTraces, "function");
  assert.equal(injected.cachedBalance === undefined && injected.cachedBalances === undefined, true,
    "Decision Mind carries no balance channel — trading semantics only");
  assert.equal(injected.cachedTraces(), null, "a fresh registration has no snapshot yet");
  const first = await injected.fetchTraces();
  assert.deepEqual(first.snapshot.trades, []);
  assert.equal(first.changed, true, "the first fetch is always a change (cold mount)");
  assert.ok(injected.cachedTraces(), "the fetched snapshot is cached in the apply closure");
  const second = await injected.fetchTraces();
  assert.equal(second.changed, false, "the same workspace signature must not re-render");
  // #2670: the FX provenance label moves with the clock while the signature
  // stays put; the panel must be told, or the staleness warning never prints.
  const sameSignature = remoteFace.traces;
  remoteFace.traces = async () => ({ ok: true, value: { workspaceKey: "ws1", signature: "sig1", trades: [], rate: null,
    rateSource: "Frankfurter · 10-06 · ⚠ 缓存 120h 未刷新" } });
  const aged = await injected.fetchTraces();
  assert.equal(aged.changed, true, "a changed rateSource under an unchanged signature is a change");
  assert.equal((await injected.fetchTraces()).changed, false, "and once shown, the same label is not");
  remoteFace.traces = sameSignature;
  assert.equal((await injected.fetchTraces()).changed, true, "the label going away again is also a change");

  // The chip's inject face owns the balance channel with its own cache.
  const balInjected = chipReg.definition.inject("s1");
  assert.equal(typeof balInjected.cachedBalances, "function");
  assert.equal(balInjected.cachedBalances(), null, "a fresh registration has no balances answer yet");
  const bal = await balInjected.fetchBalances(false);
  assert.deepEqual(bal.providers.map((r) => r.provider), ["deepseek", "minimax", "claude", "codex"],
    "stable display order across the four providers");
  assert.equal(bal.providers[0].result.snapshot.totalBalance, "110.00");
  assert.ok(balInjected.cachedBalances(), "the fetched answer is cached in the apply closure");
  // The chip's pinned-provider choice is registration-store state.
  assert.deepEqual(chipReg.definition.store.spec.init(), { selected: null });
});

test("client: _displayEntry projects a trace with its decision and T+1", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  const withDec = api._displayEntry({
    ticker: "PLTU", market: "US", currency: "USD", date: "2026-08-13",
    action: "sell", shares: 5, price: 50, realizedPnl: 45.21, note: "清仓",
    t1: { date: "2026-08-14", price: 49.24, delta: -1.52, verdict: "卖对", tone: "win" },
    decision: { planDate: "2026-08-10", action: "trim_on_rebound", confidence: 0.6,
      drivenBy: "technical", rationale: "浮盈保护", execution: "followed",
      condition: "反弹至 50 减仓" },
  });
  assert.equal(withDec.ticker, "PLTU");
  assert.equal(withDec.realizedPnl, 45.21);
  assert.equal(withDec.t1.verdict, "卖对");
  assert.equal(withDec.decision.action, "trim_on_rebound");

  const bare = api._displayEntry({
    ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-15",
    action: "buy", shares: 10, price: 8.77, realizedPnl: null,
  });
  assert.equal(bare.ticker, "SPCH");
  assert.equal(bare.decision, null);
  assert.equal(bare.t1, null);
  assert.equal(bare.realizedPnl, null);
  assert.equal(bare.reconstructed, false);
});

test("readTraces: a reconstructed opening lot is labelled, never T+1-judged (#3118)", async () => {
  // portfolio.json carries nine pre-ledger lots (#462): price solved from cost,
  // date a sort placeholder. Marked against the next close, 07747's 81.85 lot
  // read as 「跌 64.9%」 on a −0.28% session.
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-recon-"));
  try {
    fs.mkdirSync(path.join(root, "memory", "bars"), { recursive: true });
    fs.writeFileSync(path.join(root, "portfolio.json"), JSON.stringify({
      portfolios: { hk_stocks: { currency: "HKD", holdings: [
        { ticker: "07747", shares: 400, current_price: 30, trades: [
          { date: "2025-12-23", action: "buy", shares: 200, price: 81.85, reconstructed: true,
            note: "建仓早于本账本;日期为排序占位" },
          { date: "2025-12-29", action: "buy", shares: 200, price: 28.5 },
        ] },
      ] } },
    }));
    const bar = (close) => ({ open: close, high: close, low: close, close });
    fs.writeFileSync(path.join(root, "memory", "bars", "07747.json"), JSON.stringify({ bars: {
      "2025-12-23": bar(28.8), "2025-12-24": bar(28.72), "2025-12-30": bar(29.07) } }));
    const trades = ledger.readTraces(root).trades;
    const lot = trades.find((t) => t.date === "2025-12-23");
    const fill = trades.find((t) => t.date === "2025-12-29");
    assert.equal(lot.reconstructed, true);
    assert.equal(lot.t1, null, "an opening lot has no fill for the next close to mark");
    assert.equal(fill.reconstructed, undefined, "a real fill carries no flag");
    assert.ok(fill.t1, "a real fill beside it is still judged");

    const loaded = await loadClient();
    const api = loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return makeReactStub();
      throw new Error(`unexpected require: ${s}`);
    });
    const shown = api._displayEntry(lot);
    assert.equal(shown.reconstructed, true);
    const t = translatorFor(api);
    assert.match(t("trace.reconstructedFill"), /建仓占位/);
    assert.match(t("trace.t1Reconstructed"), /不判 T\+1/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("client: P&L formatting matches the dashboard", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  assert.equal(api._fmtMoney(99.99, "USD"), "$99.99");
  assert.equal(api._fmtMoney(1234.56, "USD"), "$1,235");
  assert.equal(api._fmtMoney(-99.99, "HKD"), "−HK$99.99");
  assert.equal(api._fmtMoney(-7269, "USD"), "−$7,269");
  assert.equal(api._fmtPct(6.86, 1), "+6.9%");
  assert.equal(api._fmtMoney(null, "USD"), "—");
  assert.equal(api._fmtPct(12.345), "+12.35%");
  assert.equal(api._fmtPct(0.5), "+0.50%");
  assert.equal(api._fmtPct(null), "—");
  // One loss, one glyph: the rate under an amount reads with the same minus (#2957).
  assert.equal(api._fmtPct(-7.269), "−7.27%");
  assert.equal(api._fmtPct(-7.26, 1), "−7.3%");
});

test("client: trace keys stay stable when a filter removes earlier same-day rows", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const traces = [
    { ticker: "SPCH", date: "2026-09-19", shares: 10, action: "buy" },
    { ticker: "SPCH", date: "2026-09-19", shares: 10, action: "sell" },
    { ticker: "SPCH", date: "2026-09-19", shares: 10, action: "buy" },
  ];

  const keys = api._traceKeys(traces);
  const sold = traces.filter((trace) => trace.action === "sell");

  assert.equal(keys.get(sold[0]), keys.get(traces[1]));
  assert.notEqual(keys.get(traces[0]), keys.get(traces[2]),
    "duplicate same-day fills still need distinct stable keys");
});

test("client: a fill with no price renders a dash, not the word null (#1590)", async () => {
  // ledger.ts `num()` turns a missing, empty or non-numeric trade price into
  // null, and the row and its detail concatenated it raw: "10 @null",
  // "买入 10 股 @ $null".
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const remoteFace = {
    traces: async () => ({ ok: true, value: { workspaceKey: "ws1", signature: "sig-null-price", trades: [
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-15", action: "buy",
        shares: 10, price: null, realizedPnl: null, note: null, t1: null, holdPnl: null,
        side: "add", decision: null },
    ], rate: 7.8473 } }),
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    slots: {
      inject(name, fn) { (this._fns ??= []).push(fn); },
      register(definition, Component) { this._regs ??= []; this._regs.push({ definition, Component }); },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const reg = ctx.slots._regs.find((r) => r.definition.id === "decision-studio");
  const injected = reg.definition.inject("s1");
  const store = makeStoreStub();
  const render = () => reg.Component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces,
    fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const text = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join(" ");
  };

  render();
  await tick(); await tick(); await tick();
  const folded = text(render());
  assert.match(folded, /10 @—/, `the folded row must show a dash for the missing price: ${folded}`);
  // Expand the row using its stable business key.
  store.actions.toggleOpen("SPCH2026-08-1510:buy:0");
  const expanded = text(render());
  assert.match(expanded, /买入 10 股 @ —/, `the detail must show a dash for the missing price: ${expanded}`);
  assert.doesNotMatch(expanded, /null/, `no rendered text may say null: ${expanded}`);
});

test("client: renders the single decision-trace view from the mounted remote", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  const remoteFace = {
    traces: async () => ({ ok: true, value: { workspaceKey: "ws1", signature: "sig1", trades: [
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-15", action: "buy",
        shares: 10, price: 8.77, realizedPnl: null, note: "无限子弹流继续摊本(微信 00:26 HKT)",
        t1: null, holdPnl: -28.0, side: "add",
        decision: { planDate: "2026-08-14", action: "cut", confidence: 0.82,
          drivenBy: "risk_rule", rationale: "超限硬止损", execution: "unknown",
          sizeShares: 200, plannedPrice: 9.21,
          // Host-computed: the plan says cut (reduce), the fill buys (add).
          alignment: "opposite" } },
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-07", action: "buy",
        shares: 20, price: 5.88, realizedPnl: null, note: "用户报告成交(01:34 HKT)", side: "add",
        t1: { date: "2026-08-10", price: 5.6, delta: -4.76, verdict: "跌", tone: "loss" } },
      { ticker: "PLTU", market: "US", currency: "USD", date: "2026-08-13", action: "sell",
        shares: 5, price: 50, realizedPnl: 45.21428571428572, note: "PLTU 清仓", side: "reduce",
        t1: { date: "2026-08-14", price: 49.24, delta: -1.52, verdict: "卖对", tone: "win" },
        decision: { planDate: "2026-08-10", action: "trim_on_rebound", confidence: 0.6,
          drivenBy: "technical", rationale: "浮盈保护", execution: "followed",
          condition: "反弹至 50 减仓",
          // Host-computed: trim_on_rebound and sell are both reduces.
          alignment: "same" } },
    ], rate: 7.8473 } }),
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    slots: {
      inject(name, fn) { (this._fns ??= []).push(fn); },
      register(definition, Component) { this._regs ??= []; this._regs.push({ definition, Component }); },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const __ds = ctx.slots._regs.find((r) => r.definition.id === "decision-studio");
  const component = __ds.Component;
  const injected = __ds.definition.inject("s1");

  const store = makeStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  let tree = component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  await tick(); await tick(); await tick();
  tree = component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });

  const collectText = () => {
    const text = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { text.push(node); return; }
      (node.children || []).forEach(walk);
      walk(node.props && node.props.value);
      walk(node.props && node.props.label);
    })(tree);
    return text.join(" ");
  };

  // Single view: title + stats + all fills as trace rows.
  const joined = collectText();
  assert.match(joined, /决策轨迹/);
  assert.match(joined, /已实现 \(USD 等值\)/);
  assert.match(joined, /T\+1 卖飞\/卖对/);
  // The denominator must be rendered, not implied (#710), and it must be the
  // denominator the ratio is actually a fraction of (#741): the label used to
  // read "基于 39 笔" while showing only sell-side verdicts, counting buys in.
  assert.match(joined, /判出 \d+\/\d+ 笔卖出/,
    "the T+1 scorecard must show what it is computed over, per side");
  assert.doesNotMatch(joined, /判出 0\/0 笔卖出/,
    "a fixture with a sell in it must not report zero sells");

  // The chip tone must come from the host's `tone`, not from a threshold the
  // client re-derives (#713). It rides `data-tone` rather than a class name:
  // class names are hashed CSS-module identities and asserting on them would
  // be asserting on the build, not on behaviour.
  const classes = [];
  const tones = [];
  (function walkClass(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walkClass); return; }
    if (typeof node === "string") return;
    const cn = node.props && node.props.className;
    if (typeof cn === "string") classes.push(cn);
    const tone = node.props && node.props["data-tone"];
    if (typeof tone === "string") tones.push(tone);
    (node.children || []).forEach(walkClass);
  })(tree);
  assert.ok(tones.includes("up"), `a tone:"win" trace must render an up chip, got: ${tones.join(", ")}`);
  assert.ok(!classes.some((c) => /undefined|null/.test(c)),
    `no className may contain undefined — a fixture missing t1.tone would show up here: ${classes.filter((c) => /undefined|null/.test(c)).join(", ")}`);
  // Every rendered class token must be a hashed CSS-module name. A `cx()`
  // token with no rule in styles.module.css renders verbatim, so this is the
  // gate that catches a class the stylesheet no longer defines.
  const unhashed = classes.flatMap((c) => c.split(" ")).filter((t) => t !== "" && !/^[A-Za-z0-9_-]+_[a-z0-9-]+$/.test(t));
  assert.deepEqual(unhashed, [], `class tokens with no stylesheet rule: ${unhashed.join(", ")}`);
  assert.match(joined, /SPCH/);
  assert.match(joined, /买入/);
  assert.match(joined, /10 @8.77/);
  assert.match(joined, /PLTU/);
  assert.match(joined, /卖出/);
  assert.match(joined, /\$45.21/);        // realized P&L matches dashboard money formatting
  assert.match(joined, /卖对/);           // T+1 verdict chip
  assert.doesNotMatch(joined, /\+\+/);   // header stat must not double-prepend the sign

  // Filter: 无当日计划 keeps only SPCH fills without a decision.
  const findButton = (label) => {
    let found = null;
    (function collect(node) {
      if (node == null || found) return;
      if (Array.isArray(node)) { node.forEach(collect); return; }
      if (node.type === "button") {
        const t = (node.children || []).filter((c) => typeof c === "string").join("");
        if (t.indexOf(label) === 0) found = node;
      }
      (node.children || []).forEach(collect);
    })(tree);
    return found;
  };
  findButton("无当日计划").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  const joinedMiss = collectText();
  assert.match(joinedMiss, /SPCH/);
  assert.doesNotMatch(joinedMiss, /PLTU/); // PLTU has a decision → filtered out

  // Expand a row: the trace detail shows plan → execution → P&L.
  findButton("全部").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  const cell = [];
  (function collect(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(collect); return; }
    if (node.props && node.props["data-cell"] === "trace") cell.push(node);
    (node.children || []).forEach(collect);
  })(tree);
  assert.ok(cell.length >= 2, "trace rows present");
  cell[0].props.onClick();
  await tick();
  tree = component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  const joined2 = collectText();
  assert.match(joined2, /决策轨迹 · /);       // expand header
  assert.match(joined2, /割肉/);               // plan action
  assert.match(joined2, /当时的计划/);
  assert.match(joined2, /真实成交/);
  // #741: the row is a completed fill, so the ledger's own execution.status may
  // not be rendered as that fill's 执行 verdict — "未执行" on a real buy read as
  // a contradiction. It survives as the plan's self-report, labelled as such.
  assert.match(joined2, /账本自评/);
  assert.doesNotMatch(joined2, /(^|[^自])执行\s/, "execution.status must not head a node on this row");
  // #741: the plan-vs-fill relation is stated, not left to be inferred. The
  // fixture plans 割肉 and buys — a reversal.
  assert.match(joined2, /与计划反向/);
  // #741: per-fill realized money and position-level floating percent are
  // different quantities and never share the 盈亏 label. This row is unclosed,
  // so it shows the position's figure, marked as the position's.
  assert.match(joined2, /该持仓当前浮动/);
  assert.doesNotMatch(joined2, /盈亏\s*[-+\d]/, "a bare 盈亏 label may not carry either figure");
  disposeReactEffects();
});

test("T+1 reading: one host-side dead zone drives chip, node and verdict (#665/#713)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const { t1ToneOf, t1VerdictOf } = ledger;

  // Direction stays action-aware (#665): a rise is good for the buyer, bad
  // for anyone who just sold.
  assert.equal(t1ToneOf("buy", 5.0), "win");
  assert.equal(t1ToneOf("buy", -4.76), "loss");
  assert.equal(t1ToneOf("sell", 5.0), "loss");
  assert.equal(t1ToneOf("sell", -1.52), "win");
  assert.equal(t1ToneOf("cut", 2.0), "loss");
  assert.equal(t1ToneOf("trim_on_rebound", -2.0), "win");

  // #713: the dead zone is now ONE band, applied to every action and to the
  // verdict text as well. These two cases are the ones that used to disagree.
  //  - sell at +0.5%: chip said flat/"持平" while the trace node was painted red
  //  - buy at exactly 0%: verdict said 跌 while the node was painted green
  assert.equal(t1ToneOf("sell", 0.5), "flat");
  assert.equal(t1VerdictOf("sell", 0.5), "持平");
  assert.equal(t1ToneOf("buy", 0.5), "flat");
  assert.equal(t1VerdictOf("buy", 0.5), "持平");
  assert.equal(t1ToneOf("buy", 0), "flat");
  assert.equal(t1VerdictOf("buy", 0), "持平");
  assert.equal(t1ToneOf("add", 0.5), "flat");

  // Outside the band the verdict text and the tone agree by construction.
  for (const [action, delta, tone, verdict] of [
    ["buy", 4.0, "win", "涨"],
    ["buy", -4.0, "loss", "跌"],
    ["sell", 4.0, "loss", "卖飞"],
    ["sell", -4.0, "win", "卖对"],
  ]) {
    assert.equal(t1ToneOf(action, delta), tone, `${action} ${delta} tone`);
    assert.equal(t1VerdictOf(action, delta), verdict, `${action} ${delta} verdict`);
  }

  // The client only maps that single reading onto its two CSS vocabularies —
  // it must not re-derive a threshold of its own.
  assert.equal(api.t1NodeClass("win"), "win");
  assert.equal(api.t1NodeClass("loss"), "loss");
  assert.equal(api.t1NodeClass("flat"), "");
  assert.equal(api.t1ChipClass("win"), "up");
  assert.equal(api.t1ChipClass("loss"), "down");
  assert.equal(api.t1ChipClass("flat"), "flat");
  assert.equal(api.t1Tone, undefined, "the client-side threshold helper must be gone (#713)");
  assert.equal(api.t1ChipTone, undefined, "the client-side chip threshold helper must be gone (#713)");
});

test("client: an unreadable workspace says so instead of printing a $0 ledger (#2180)", async () => {
  const loaded = await loadClient();
  const react = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return react;
    throw new Error(`unexpected require: ${s}`);
  });
  // What readTraces answers when portfolio.json is missing or does not parse.
  const remoteFace = {
    traces: async () => ({ ok: true, value: { workspaceKey: "ws1", signature: "sig0", trades: [], rate: null, rateSource: null, lastUpdated: null } }),
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const reg = ctx.slots._regs.find((r) => r.definition.id === "decision-studio");
  const injected = reg.definition.inject("s1");
  const store = makeStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const render = () => reg.Component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  render();
  await tick(); await tick(); await tick();
  react._resetCursor(); // same state slots, as a real re-render
  const text = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { text.push(node); return; }
    (node.children || []).forEach(walk);
  })(render());
  const joined = text.join(" ");
  assert.match(joined, /读不到工作区的 portfolio\.json/);
  assert.doesNotMatch(joined, /\$0|没有符合条件的成交/);
  assert.equal(injected.cachedTraces(), null, "an unread ledger must not be cached as an empty one");
});

test("client: trace list batches older days behind 'show earlier' and folds by day", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  // 5 distinct date groups → default renders the newest 3 (AAA/BBB/CCC),
  // DDD/EEE stay behind the "show earlier" batch. This is the anti-jank fold:
  // the first paint must not be a 100-cell wall, and "see everything" must
  // never mean one giant wall at once (#702 Phase 2).
  const mk = (ticker, date) => ({ ticker, market: "US", currency: "USD", date, action: "buy", shares: 1, price: 10, realizedPnl: null });
  const trades = [
    mk("AAA", "2026-08-15"),
    mk("BBB", "2026-08-14"),
    mk("CCC", "2026-08-13"),
    mk("DDD", "2026-08-10"),
    mk("EEE", "2026-08-05"),
  ];

  const remoteFace = {
    traces: async () => ({ ok: true, value: { workspaceKey: "ws1", signature: "sig1", trades, rate: null } }),
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const __ds = ctx.slots._regs.find((r) => r.definition.id === "decision-studio");
  const component = __ds.Component;
  const injected = __ds.definition.inject("s1");

  const store = makeStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const render = () => component({ sessionId: "s1", t: translatorFor(api), cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  let tree = render();
  await tick(); await tick(); await tick();
  tree = render();

  const collectText = () => {
    const text = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { text.push(node); return; }
      (node.children || []).forEach(walk);
      walk(node.props && node.props.value);
      walk(node.props && node.props.label);
    })(tree);
    return text.join(" ");
  };
  const findButton = (label) => {
    let found = null;
    (function collect(node) {
      if (node == null || found) return;
      if (Array.isArray(node)) { node.forEach(collect); return; }
      if (node.type === "button") {
        const t = (node.children || []).filter((c) => typeof c === "string").join("");
        if (t.indexOf(label) === 0) found = node;
      }
      (node.children || []).forEach(collect);
    })(tree);
    return found;
  };

  // Folded default: newest 3 groups only, older fills not in the DOM.
  const joined = collectText();
  assert.match(joined, /AAA/);
  assert.match(joined, /BBB/);
  assert.match(joined, /CCC/);
  assert.doesNotMatch(joined, /DDD/);
  assert.doesNotMatch(joined, /EEE/);

  // The batch button advertises exactly what's hidden, then reveals it.
  const more = findButton("显示更早");
  assert.ok(more, "batch button must be present when older days exist");
  assert.match(joined, /显示更早的 2 笔成交/);
  more.props.onClick();
  await tick();
  tree = render();
  const joinedAll = collectText();
  assert.match(joinedAll, /DDD/);
  assert.match(joinedAll, /EEE/);
  assert.match(joinedAll, /收起,只显示最近 3 组/);

  // Day-header accordion: fold the newest day → its cell leaves the DOM but
  // the header (and the count) stays; unfold restores it.
  const dayHeader = (() => {
    let found = null;
    (function collect(node) {
      if (node == null || found) return;
      if (Array.isArray(node)) { node.forEach(collect); return; }
      if (node.props && typeof node.props["data-day"] === "string") found = node;
      (node.children || []).forEach(collect);
    })(tree);
    return found;
  })();
  assert.ok(dayHeader, "day headers are foldable");
  dayHeader.props.onClick();
  await tick();
  tree = render();
  const foldedText = collectText();
  assert.doesNotMatch(foldedText, /AAA/, "folded day's cell must leave the DOM");
  assert.match(foldedText, /2026-08-15/, "folded day's header must stay");
  dayHeader.props.onClick();
  await tick();
  tree = render();
  assert.match(collectText(), /AAA/, "unfolding restores the cell");
  disposeReactEffects();
});

test("client: the bundle loads with no DOM and owns no module-level state (#729)", async () => {
  // Two module-scope rules at once, both regressions this plugin actually had:
  // the bundle used to inject a <style> tag while the module was evaluating,
  // and it used to build its store handle at module scope (a singleton across
  // plugin reloads). `loadClient` runs with no `document` global at all.
  assert.equal(globalThis.document, undefined, "the spec must not leave a DOM lying around");
  const counter = { calls: 0 };
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub(counter);
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  assert.equal(counter.calls, 0, "no store may exist before apply() runs");
  assert.equal(typeof api.createDecisionMindStore, "function", "the store must be an exported factory");

  const ctx = {
    effect() {}, get() { return { traces: async () => ({ ok: true, value: { trades: [] } }) }; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register() {} },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  assert.equal(counter.calls, 2, "apply() creates exactly two store handles (Decision Mind + chip selection)");
  const one = api.createDecisionMindStore();
  const two = api.createDecisionMindStore();
  assert.notEqual(one, two, "each factory call must yield its own handle, never a shared singleton");
  const chipA = api.createBalanceStore();
  const chipB = api.createBalanceStore();
  assert.notEqual(chipA, chipB, "the chip store is also per-call, never a module singleton");
  assert.deepEqual(chipA.spec.init(), { selected: null });
});

test("client: stylesheet is loader-owned and keeps the dark-theme and tone contract (#704/#685/#729)", async () => {
  // The stylesheet arrives as a CSS Modules import: the emitted code injects
  // one <style data-plugin="clawock-dsh"> tag, which is how the DSH module
  // loader knows the tag is ours and removes it when the package unloads.
  // Class names are hashed, so every selector assertion is hash-agnostic.
  const injected = await withDocumentStub(async (collected) => {
    const loaded = await loadClient();
    loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return makeReactStub();
      throw new Error(`unexpected require: ${s}`);
    });
    return collected;
  });
  assert.equal(injected.length, 1, "exactly one stylesheet tag");
  const [tag] = injected;
  assert.equal(tag.dataset.plugin, "clawock-dsh",
    "the tag must carry the plugin id — that attribute is the loader's unload handle (#729)");
  assert.equal(tag.dataset.pluginCss, "clawock-dsh/styles.module.css",
    "and the per-file id that makes re-evaluation idempotent");
  const css = tag.textContent;
  assert.ok(css.length > 1000, "the factory must inject a real stylesheet");
  const hashed = (...names) => new RegExp(names.map((n) => `\\.[A-Za-z0-9_-]+_${n}`).join(" ?"));
  assert.match(css, /body\[data-ds-dark-theme\] \.[A-Za-z0-9_-]+_dmt\{/, "dark-theme override block required (#704)");
  assert.match(css, hashed("t1"), "T+1 chip block required (#685)");
  assert.match(css, /_t1\.[A-Za-z0-9_-]+_up\{/, "T+1 up tone class required (#685)");
  assert.match(css, /_t1\.[A-Za-z0-9_-]+_down\{/, "T+1 down tone class required (#685)");
  assert.match(css, /_detail\{[^}]*grid-template-rows:0fr/, "folded detail must default to 0fr");
  assert.match(css, hashed("stats"), "header stats block required");
  assert.match(css, hashed("filters"), "filter row block required");
  // The balance capsule is part of the same sheet contract: its classes must
  // exist (a cx() token with no rule renders verbatim, unhashed) and the low
  // state's red dot must be selectable through the stable data attribute.
  assert.match(css, hashed("bchip"), "header balance chip block required");
  assert.match(css, hashed("bchip-dot"), "per-provider chip dot required");
  assert.match(css, hashed("bchip-sub"), "weekly sub-reading class required");
  assert.match(css, hashed("bchip-reset"), "headline-window reset stamp class required (kcn: 用尽也要能看到什么时候重置)");
  assert.match(css, hashed("bp"), "provider panel block required");
  assert.match(css, hashed("bp-row"), "panel per-provider row required");
  assert.match(css, hashed("bal-rf"), "ghost refresh button required");
  assert.match(css, hashed("bal-lead"), "sidebar balance glyph wrapper required");
  assert.match(css, hashed("bal-glyph"), "sidebar balance gauge required");
  assert.match(css, hashed("bal-badge"), "sidebar balance status badge required");
  assert.match(css, hashed("bp-win-bar"), "per-window progress bar required");
  // Colour tiers are part of the contract (kcn 确认保留): the pill number and
  // the bar fill both key off the usage direction (ok green / mid yellow /
  // low red) — colour only, never at the cost of information (#908).
  assert.match(css, /_bchip-v\[data-used-level=ok\]/, "pill green tier selector required");
  assert.match(css, /_bchip-v\[data-used-level=mid\]/, "pill yellow tier selector required");
  assert.match(css, /_bp-win-fill\[data-balance-state=mid\]/, "bar approach-band selector required");
  assert.match(css, /_bp-win-fill\[data-balance-state=low\]/, "bar watermark selector required");
  // lightningcss minifies the attribute selector's quotes away; the
  // contract is the data attribute itself, not its quoting.
  assert.match(css, /_bchip-v\[data-balance-state=low\]/, "chip low value selector required");
  assert.match(css, /_bp\[data-open=false\]/, "closed-panel state selector required");
  assert.doesNotMatch(fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8"), /IntersectionObserver/,
    "the drawer portal replaces the old visibility observer; no observer should remain");
  assert.match(css, /_bp\[data-open=true\]\{opacity:1;pointer-events:auto\}/,
    "an opened glass popover must become visible and interactive on its first tap");
  // Tier colours must NOT paint over a stale reading (数字不可信优先于用量档,
  // 与面板 bp-win-fill 的既有优先级一致)。These attr rules share specificity
  // and co-occur on one element, so source order decides: stale must come last.
  const idxOf = (re) => { const m = re.exec(css); return m === null ? -1 : m.index; };
  const chipStale = idxOf(/_bchip-v\[data-balance-state=stale\]/);
  const chipLow = idxOf(/_bchip-v\[data-used-level=low\]/);
  assert.ok(chipLow > -1 && chipStale > chipLow, "high usage stays red unless stale");
  const chipMid = idxOf(/_bchip-v\[data-used-level=mid\]/);
  assert.ok(chipStale > -1 && chipStale > chipMid,
    "stale yellow must out-rank the pill's usage tiers in source order");
  const fillStale = idxOf(/_bp-win-fill\[data-balance-state=stale\]/);
  const fillMid = idxOf(/_bp-win-fill\[data-balance-state=mid\]/);
  assert.ok(fillStale > -1 && fillStale > fillMid,
    "bar stale yellow must keep out-ranking usage tiers in source order");
  // The panel's reading cell carries both attributes too (#2338): its stale
  // rule sat between the tiers, so a stale reading at >=80% used painted red
  // in the row while the pill above it painted the same reading yellow.
  // The legacy header popover's rows are the third surface of the same reading.
  assert.match(css, /_bp-v\[data-used-level=mid\]/, "legacy panel row yellow tier selector required");
  assert.match(css, /_bp-v\[data-used-level=low\]/, "legacy panel row red tier selector required");
  const bpStale = idxOf(/_bp-v\[data-balance-state=stale\]/);
  const bpLow = idxOf(/_bp-v\[data-used-level=low\]/);
  assert.ok(bpStale > -1 && bpLow > -1 && bpStale > bpLow,
    "legacy panel stale yellow must out-rank its usage tiers in source order");
  assert.match(css, hashed("skel"), "cold-start skeleton block required");
  // The host publishes a font stack but no font-size tokens. The plugin's
  // seven whole-pixel roles are shared by the board and both sidebar chips;
  // half-pixel aliases and inline sizes would restart the old size drift.
  const LADDER = {
    "fs-micro": "10px", "fs-xs": "11px", "fs-sm": "12px",
    "fs-md": "13px", "fs-lg": "14px", "fs-xl": "15px", "fs-2xl": "16px",
  };
  for (const [name, value] of Object.entries(LADDER)) {
    assert.match(css, new RegExp(`--${name}:\\s*${value.replace(".", "\\.")}`),
      `type ladder must define --${name} as ${value} (#1216)`);
  }
  // The balance capsule renders outside .dmt, so it needs the ladder in its
  // own scope — a token that resolves nowhere renders as the browser default.
  assert.match(css, /\.[A-Za-z0-9_-]+_dmt,\s*\.[A-Za-z0-9_-]+_pbc,\s*\.[A-Za-z0-9_-]+_wb\{[^}]*--fs-micro/,
    "the ladder must be declared for both roots, not just the board (#1216)");
  assert.doesNotMatch(css, /--fs-(?:nano|caption|(?:xs|sm|md|lg|xl)-l):/,
    "half-step aliases must not return to the ladder");
  const rawSizes = [
    ...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g),
    ...css.matchAll(/font:(?:\s*\d+)?\s*(\d+(?:\.\d+)?)px\//g),
  ].map((m) => m[0]);
  assert.deepEqual(rawSizes, [],
    `font sizes must come from the ladder, not inline px: ${rawSizes.join(", ")} (#1216)`);
  // The 390px WebKit baseline clipped both ticker and fill price in the
  // flex row. The two-row grid gives each data field its own cell and keeps
  // the trailing P&L visible; the cells must not silently fall back to flex.
  assert.match(css, /_main\{[^}]*grid-template-columns:7px minmax\(0,1fr\) max-content[^}]*display:grid/,
    "phone trade headline needs independent ticker and P&L columns");
  assert.match(css, /_main\s+\.[A-Za-z0-9_-]+_qty\{grid-area:2\/3;justify-self:end/,
    "phone fill quantity and price must get the trailing second-row cell");
  assert.match(css, /_pc\{[^}]*overflow-wrap:anywhere/,
    "long trigger/evidence chip text must wrap inside its card");
  assert.match(css, /_fill-v\{[^}]*flex-wrap:wrap/,
    "plan-alignment chip must wrap as an intact box beside a long fill");
  for (const [selector, role] of [["tin", "radius-card"], ["group", "radius-card"],
    ["dbody", "radius-inset"], ["pc", "radius-chip"], ["empty", "radius-card"]]) {
    assert.match(css, new RegExp(`_${selector}\\{[^}]*border-radius:var\\(--${role}\\)`),
      `${selector} must use the shared card role ${role}`);
  }
  assert.match(css, /@media \(pointer:coarse\)\{[^}]*_ft[^}]*min-height:44px/,
    "phone filters and folds need finger-sized targets");
  assert.match(css, /--canvas:var\(--dsw-static-neutral-bluish-75/,
    "Decision Mind canvas must use the host's neutral scale");
  // The host's business blue is brand paint for the material (canvas, glows) — never there —
  // but it is also the host's state token for "running" (kcn 2026-09-26: healthy/running uses
  // --dsw-alias-state-business-primary, not a plugin-made green). It may appear exactly once:
  // as the task chip's --tq-run role, which no material rule reads.
  const runRole = css.match(/--tq-run:var\(--dsw-alias-state-business-primary\)/g) ?? [];
  assert.equal(runRole.length, 1, "the task chip names business blue once, as its running role");
  assert.doesNotMatch(css.replace(/--tq-run:var\(--dsw-alias-state-business-primary\)/, ""),
    /--glow-[123]:|radial-gradient\(|#f0f2f7|--dsw-alias-state-business-primary/i,
    "plugin-owned blue canvas, blue-violet glow pools and brand paint must stay out of the material");
  for (const token of ["glass-fill-card", "glass-fill-header", "glass-fill-chip",
    "glass-fill-popover", "glass-saturate", "glass-rim", "glass-border"]) {
    assert.match(css, new RegExp(`--${token}:`), `${token} must remain available to the board and opened popovers`);
  }
  assert.match(css, /_dmt,\.[A-Za-z0-9_-]+_pbc(?:,\.[A-Za-z0-9_-]+_wb)?\{[^}]*--glass-fill-popover/,
    "the glass recipe must resolve in both the tab and opened sidebar popovers");
  // The live DSH foot entry sits beside Settings: 42px row, 16px glyph at
  // x+8, 14/22 label; Cordis uses the same row geometry. Its material must
  // disappear completely until the anchored popover opens. Check the built
  // bundle, not only source text, so an overriding rule cannot fake this.
  const openedPanel = css.match(/_pbc \.[A-Za-z0-9_-]+_bp\{([^}]*)\}/)?.[1];
  assert.ok(openedPanel, "the compiled popover rule must exist");
  for (const declaration of ["background:var(--glass-sheen), var(--glass-fill-popover)",
    "backdrop-filter:blur(var(--glass-popover-blur))", "box-shadow:var(--glass-float-shadow)"]) {
    assert.ok(openedPanel.includes(declaration), `the opened popover must retain ${declaration}`);
  }
  assert.match(css, /_cell:hover\{background:var\(--row-hover\)/,
    "the large row's hover fill must preserve semantic text contrast");
  assert.match(css, /_cell:active\{background:var\(--row-press\)/,
    "the large row's pressed fill must preserve semantic text contrast");
  assert.match(css, /@media \(width<=520px\)\{[^}]*_bp\{--glass-fill-popover:color-mix\(in srgb, var\(--surface\) 97%, transparent\)/,
    "phone popovers need a stronger fill from the shared host surface");
  // The three host-layout contracts this tab lives inside. Each of them was a
  // visible defect before 2026-08-22, and none is observable from the rendered
  // tree — they are properties of the sheet, so this is where they are pinned.
  //
  // 1. One width axis. The sticky header used to be full-bleed (1152px at a
  //    1440px window) over a 760px list, which is what read as "the floating
  //    bar is too wide". Header column and list column must both be the
  //    Harness's own --dsh-chat-content-width.
  assert.match(css, /--col:var\(--dsh-chat-content-width/,
    "the tab's column must be the Harness's own content width, not a local number");
  assert.match(css, /_tin\{[^}]*max-width:calc\(var\(--col\)/,
    "the header card must ride that width (minus the list's own side padding)");
  assert.match(css, /_list\{[^}]*max-width:var\(--col\)/,
    "the list must ride the same width as the header");
  // 2. The composer floats over this scroller; ConversationRoot publishes its
  //    live height and every view has to pad by it or the last rows sit under
  //    the input card.
  assert.match(css, /_list\{[^}]*var\(--dsh-composer-height/,
    "the list must clear the floating composer");
  // 2b. Only the filter row is allowed to hold the viewport: the stat card
  //     scrolls away with the content. A sticky header that stays is 100px of
  //     permanently parked chrome on a tab whose whole job is a scrollable list.
  assert.match(css, /_bar\{[^}]*position:sticky/,
    "the filter row must be the sticky part of the header");
  assert.doesNotMatch(css, /_top\{[^}]*position:sticky/,
    "the stat card must scroll away rather than park itself over the list");
  // 3. A closed row reserves no space. `grid-template-rows:0fr` collapses the
  //    content but not the padding of the box it is on, so the detail's own
  //    padding has to stay zero (it lives on .dbody, mounted only while open).
  //    That padding was ~27px of dead band under every collapsed row.
  assert.match(css, /_dinner\{[^}]*padding:0[;}]/,
    "the collapsed detail box may not carry padding — it would reserve height");
});

test("readTraces: a close outside the T+1 window is not a T+1 verdict (#710)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-t1-"));
  const bars = path.join(root, "memory", "bars");
  fs.mkdirSync(bars, { recursive: true });
  const desk = (tradeDate, tradePrice = 100) => fs.writeFileSync(path.join(root, "portfolio.json"), JSON.stringify({
    portfolios: { hk_stocks: { currency: "HKD", holdings: [
      { ticker: "00700", shares: 10, current_price: 100,
        trades: [{ date: tradeDate, action: "buy", shares: 10, price: tradePrice }] },
    ] } },
  }));
  // Closes come from the canonical bar store, not from portfolio snapshots
  // (#717): one file per ticker, keyed by exchange session.
  const closes = {};
  const close = (date, price) => {
    closes[date] = { open: price, high: price, low: price, close: price };
    fs.writeFileSync(path.join(bars, "00700.json"), JSON.stringify({ bars: closes }));
  };
  const dropClose = (date) => {
    delete closes[date];
    fs.writeFileSync(path.join(bars, "00700.json"), JSON.stringify({ bars: closes }));
  };
  const t1Of = () => ledger.readTraces(root).trades[0].t1;
  try {
    // Next calendar day — the plain T+1 case.
    desk("2026-08-10");
    close("2026-08-11", 110);
    assert.ok(t1Of(), "an adjacent close is a T+1 verdict");
    assert.equal(t1Of().delta, 10);
    desk("2026-08-10", 0);
    assert.equal(t1Of(), null, "a zero-price fill is unjudgeable, not an infinite win");

    // Friday fill settling against Monday: 3 days, still T+1.
    dropClose("2026-08-11");
    desk("2026-08-07");
    close("2026-08-10", 110);
    assert.ok(t1Of(), "a weekend gap is still T+1 (Fri fill → Mon close)");

    // The regression this guards: the only close we own is months later. It
    // used to be returned and rendered under a literal "T+1" label — on live
    // data that reached +144 days for fills predating the snapshot series.
    dropClose("2026-08-10");
    desk("2026-03-02");
    close("2026-08-10", 110);
    assert.equal(t1Of(), null, "a close +161 days out must not be a T+1 verdict (#710)");

    // And the boundary itself: 4 days in, 5 days out.
    dropClose("2026-08-10");
    desk("2026-08-10");
    close("2026-08-14", 110);
    assert.ok(t1Of(), "4 calendar days is inside the window");
    dropClose("2026-08-14");
    close("2026-08-15", 110);
    assert.equal(t1Of(), null, "5 calendar days is outside the window");

    // dayGap must be real calendar arithmetic, not the ordering key: the
    // ordering key puts 2026-08-31 → 2026-09-01 two "days" apart.
    assert.equal(ledger.dayGap("2026-08-31", "2026-09-01"), 1);
    assert.equal(ledger.dayGap("2026-07-28", "2026-08-01"), 4);
    assert.equal(ledger.dayGap("2026-12-31", "2027-01-01"), 1);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("readBarCloses: T+1 marks against the canonical bar store, never snapshots (#717)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-bars-"));
  fs.mkdirSync(path.join(root, "memory", "bars"), { recursive: true });
  fs.mkdirSync(path.join(root, "memory", "snapshots"), { recursive: true });
  try {
    fs.writeFileSync(path.join(root, "portfolio.json"), JSON.stringify({
      portfolios: { us_stocks: { currency: "USD", holdings: [
        { ticker: "NVDA", shares: 10, current_price: 213,
          trades: [{ date: "2026-08-10", action: "buy", shares: 10, price: 200 }] },
      ] } },
    }));
    // The snapshot says one thing (a stale carried-forward 213 — the real
    // shape of the bug: NVDA sat frozen at 213 for five sessions), the
    // canonical bar says another. The view must read the bar.
    fs.writeFileSync(path.join(root, "memory", "snapshots", "2026-08-11.json"), JSON.stringify({
      portfolios: { us: { holdings: [{ ticker: "NVDA", current_price: 213 }] } },
    }));
    fs.writeFileSync(path.join(root, "memory", "bars", "NVDA.json"), JSON.stringify({
      bars: { "2026-08-11": { open: 219, high: 226, low: 218, close: 220.61 } },
    }));

    const t1 = ledger.readTraces(root).trades[0].t1;
    assert.ok(t1, "a bar close inside the window is a T+1 verdict");
    assert.equal(t1.price, 220.61, "the T+1 price is the canonical bar close, not the snapshot quote");
    assert.equal(t1.delta, 10.31, "delta is marked against the bar close");

    // Only `close` counts — high/low get revised by the provider and are not
    // what a T+1 mark settles against (all 19 conflicts seen on the 2026-08-17
    // backfill were high/low, zero were close).
    fs.writeFileSync(path.join(root, "memory", "bars", "NVDA.json"), JSON.stringify({
      bars: { "2026-08-11": { open: 219, high: 999, low: 1, close: 220.61 } },
    }));
    assert.equal(ledger.readTraces(root).trades[0].t1.delta, 10.31, "a high/low revision must not move the T+1 mark");

    // No bar file for the ticker = no verdict. It must not fall back to the
    // snapshot that is sitting right there.
    fs.rmSync(path.join(root, "memory", "bars", "NVDA.json"));
    assert.equal(ledger.readTraces(root).trades[0].t1, null,
      "without a canonical bar there is no T+1 — never a snapshot fallback");

    // The ticker is a path component; it must be constrained before the join.
    const escaped = ledger.readBarCloses(root, ["../../../etc/passwd", "NVDA"]);
    assert.deepEqual(Object.keys(escaped), [], "a traversal-shaped ticker reads nothing");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("freshness: signature moves on each of the four data sources", async () => {
  const freshness = await import(pathToFileURL(path.join(PLUGIN, "lib", "freshness.js")).href);
  const root = makeDesk();
  const barsDir = path.join(root, "memory", "bars");
  fs.mkdirSync(barsDir, { recursive: true });
  try {
    const before = freshness.workspaceSignature(root);
    assert.ok(before.length > 0);
    assert.equal(before.split("|").length, 4, "shape: portfolio stat | bars digest | decisions stat | fx stat");
    assert.equal(before.split("|")[1], "none", "no bar files yet → the bars term is 'none'");

    // portfolio.json 变化 → 签名变(内容长度不同,size 兜底 mtime 同刻度)
    fs.writeFileSync(path.join(root, "portfolio.json"), JSON.stringify({ last_updated: "changed" }));
    const afterPortfolio = freshness.workspaceSignature(root);
    assert.notEqual(afterPortfolio, before, "portfolio.json change must move the signature");

    // 新 ticker 的 bar 文件落盘(T+1 数据源)→ 签名变
    const barPath = path.join(barsDir, "00700.json");
    fs.writeFileSync(barPath, JSON.stringify({ bars: { "2026-08-14": { close: 100 } } }));
    const afterBars = freshness.workspaceSignature(root);
    assert.notEqual(afterBars, afterPortfolio, "a NEW bar file must move the signature");

    // #711:改写一个【已存在】的 bar 文件(文件名不变)也必须让签名变。
    // 这是两条真实路径:每日写入把新收盘的 session 追加进每个 ticker 的文件,
    // `--repair` 就地修订一根旧 bar。任何只看文件名的签名都会漏掉这两种。
    const beforeRewrite = freshness.workspaceSignature(root);
    fs.writeFileSync(barPath, JSON.stringify({
      bars: { "2026-08-14": { close: 100 }, "2026-08-17": { close: 111 } },
    }));
    assert.notEqual(
      freshness.workspaceSignature(root), beforeRewrite,
      "appending a session to an EXISTING bar file must move the signature (#711)",
    );

    // decisions.jsonl 变化(软配对源)→ 签名变
    const beforeLedger = freshness.workspaceSignature(root);
    fs.writeFileSync(path.join(root, "memory", "decisions.jsonl"), JSON.stringify({ decision_id: "x" }) + "\n");
    assert.notEqual(freshness.workspaceSignature(root), beforeLedger, "decisions.jsonl change must move the signature");

    // fx-rates.jsonl 变化(FX 通道,#838)→ 签名变
    const beforeFx = freshness.workspaceSignature(root);
    fs.writeFileSync(path.join(root, "memory", "fx-rates.jsonl"), '{"day":"2026-08-21","rate":7.8438,"source":"Frankfurter"}\n');
    assert.notEqual(freshness.workspaceSignature(root), beforeFx, "fx-rates.jsonl change must move the signature (#838)");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("freshness: an unchanged signature stops answering from the cache once it is a minute old (#2639)", async () => {
  // The FX line's "cache Nh not refreshed" warning is computed from the clock.
  // A signature-only cache froze the first answer for exactly as long as the
  // FX ledger stayed unwritten — the condition the warning is about.
  const freshness = await import(pathToFileURL(path.join(PLUGIN, "lib", "freshness.js")).href);
  let clock = 1_000_000;
  const cache = freshness.createTraceCache(freshness.TRACE_TTL_MS, () => clock);
  cache.set("/ws", "sig", { rateSource: "Frankfurter · 10-05" });
  assert.deepEqual(cache.get("/ws", "sig"), { rateSource: "Frankfurter · 10-05" });
  clock += freshness.TRACE_TTL_MS - 1;
  assert.notEqual(cache.get("/ws", "sig"), undefined, "a hit inside the minute must stay a hit");
  assert.equal(cache.get("/ws", "moved"), undefined, "a moved signature is still a miss");
  clock += 1;
  assert.equal(cache.get("/ws", "sig"), undefined, "the same signature must be recomputed after the ttl");
});

test("readFxRate: last valid line wins; missing/malformed degrade to null (#838)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-fx-"));
  const memory = path.join(root, "memory");
  fs.mkdirSync(memory, { recursive: true });
  try {
    assert.equal(ledger.readFxRate(root), null, "no file → null");
    const fxPath = path.join(memory, "fx-rates.jsonl");
    fs.writeFileSync(fxPath, [
      '{"day":"2026-08-19","rate":7.8437,"source":"Frankfurter"}',
      'not json at all',
      '{"day":"2026-08-20","rate":7.8416,"source":"Frankfurter"}',
      "",
    ].join("\n"));
    const got = ledger.readFxRate(root);
    assert.equal(got.rate, 7.8416, "the last valid line wins");
    assert.equal(got.source, "Frankfurter");
    // A non-positive or non-numeric rate reads as absent, never as a number.
    fs.writeFileSync(fxPath, '{"day":"2026-08-21","rate":0,"source":"x"}\n');
    assert.equal(ledger.readFxRate(root), null, "rate 0 → null");
    fs.writeFileSync(fxPath, '{"day":"2026-08-21","rate":"abc","source":"x"}\n');
    assert.equal(ledger.readFxRate(root), null, "non-numeric rate → null");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test("fx provenance: the rate names its source, its day, a fallback and a stopped refresh (#2569)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-fx-"));
  fs.mkdirSync(path.join(root, "memory"), { recursive: true });
  const fxPath = path.join(root, "memory", "fx-rates.jsonl");
  const now = Date.parse("2026-10-05T01:00:00Z");
  try {
    fs.writeFileSync(fxPath, '{"day":"2026-10-02","fallback_used":false,"fetched_at":"2026-10-02T00:03:33+00:00","pair":"USDHKD","rate":7.8472,"source":"Frankfurter"}\n');
    const fx = ledger.readFxRate(root);
    assert.deepEqual(fx, { rate: 7.8472, source: "Frankfurter", day: "2026-10-02", fetchedAt: "2026-10-02T00:03:33+00:00", fallbackUsed: false });
    assert.equal(ledger.fxProvenance(fx, now), "Frankfurter · 10-02", "73h old is inside the 96h reading window");
    assert.equal(ledger.fxProvenance(fx, now + 48 * 3600000), "Frankfurter · 10-02 · ⚠ 缓存 121h 未刷新");
    assert.equal(ledger.fxProvenance({ ...fx, fallbackUsed: true }, now), "Frankfurter · 10-02 · 回退值");
    // No day on the row: the HKT date of the fetch. No clock at all: say so, never guess fresh.
    assert.equal(ledger.fxProvenance({ ...fx, day: null, fetchedAt: "2026-10-02T17:30:00+00:00" }, now), "Frankfurter · 10-03");
    assert.equal(ledger.fxProvenance({ ...fx, day: null, fetchedAt: null, source: null }, now), "日期未知");
    fs.writeFileSync(fxPath, '{"day":"2026-10-02","pair":"USDCNY","rate":7.1,"source":"x"}\n');
    assert.equal(ledger.readFxRate(root), null, "another pair is not the USDHKD rate");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("readTraces: bull/bear fall back to the debate prose, as the site's row does (#2571)", async () => {
  const ledger = await import(pathToFileURL(path.join(PLUGIN, "lib", "ledger.js")).href);
  const root = makeDesk();
  try {
    fs.appendFileSync(path.join(root, "memory", "decisions.jsonl"), JSON.stringify({
      decision_id: "dec-debate1", plan_date: "2026-08-04", ticker: "00100", leg: "HK", action: "buy",
      rationale: "回踩 230 承接", debate: { bull: "南向持续承接", bear: "解禁抛压未完", judge: "小仓试" },
      execution: { status: "unknown" },
    }) + "\n");
    const fill = ledger.readTraces(root).trades.find((t) => t.date === "2026-08-04");
    assert.equal(fill.decision.planDate, "2026-08-04", "the fill pairs with the debate row");
    assert.equal(fill.decision.bull, "南向持续承接");
    assert.equal(fill.decision.bear, "解禁抛压未完");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("balance: a 200 without an amount is a failed read, not a healthy row (#2572)", async () => {
  const balance = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const originalFetch = globalThis.fetch;
  let body = {};
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  try {
    const deps = { credentials: { resolve: async () => ({ value: "sk-test" }) } };
    for (const drifted of [{}, { balance_infos: [] }, { is_available: true, balances: [{ currency: "CNY", total_balance: "9.00" }] }]) {
      body = drifted;
      const cold = await balance.createBalanceService(deps, { threshold: 10, refreshMs: 60000 }).get(true);
      assert.equal(cold.status, "failed", JSON.stringify(drifted));
      assert.equal(cold.snapshot, null);
      assert.match(cold.message, /没有返回金额/);
    }
    // After a good read the drift keeps the last number and marks it stale.
    const service = balance.createBalanceService(deps, { threshold: 10, refreshMs: 60000 });
    body = { is_available: true, balance_infos: [{ currency: "CNY", total_balance: "110.00" }] };
    assert.equal((await service.get(true)).status, "fresh");
    body = {};
    const drifted = await service.get(true);
    assert.equal(drifted.status, "stale");
    assert.equal(drifted.snapshot.totalBalance, "110.00");
    // An explicit refusal stays the vendor's own verdict (#2263), amount or not.
    body = { is_available: false };
    const refused = await balance.createBalanceService(deps, { threshold: 10, refreshMs: 60000 }).get(true);
    assert.equal(refused.status, "fresh");
    assert.equal(refused.snapshot.isAvailable, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("freshness: trace cache is signature-keyed and µs-hit", async () => {
  const freshness = await import(pathToFileURL(path.join(PLUGIN, "lib", "freshness.js")).href);
  const cache = freshness.createTraceCache();
  const value = { trades: [{ ticker: "A" }] };

  assert.equal(cache.get("/ws", "sig1"), undefined, "cold cache must miss");
  cache.set("/ws", "sig1", value);
  assert.equal(cache.get("/ws", "sig1"), value, "same signature must hit the same object");
  assert.equal(cache.get("/ws", "sig2"), undefined, "moved signature must miss");
  assert.equal(cache.get("/other", "sig1"), undefined, "workspace is part of the key");

  // workspaceKey: opaque hash, no host path on the wire
  const key = freshness.workspaceKeyOf("/tmp/ws-a");
  assert.match(key, /^[0-9a-f]{12}$/);
  assert.notEqual(key, freshness.workspaceKeyOf("/tmp/ws-b"));
});

test("balance: a leading ~ in a configured path expands, anything else is literal", async () => {
  const balance = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const home = os.homedir();
  // The defaults are home-relative and the profile row is hand-written YAML,
  // so `~/.claude/...` is the natural override; taken literally it would read a
  // file actually named `~`.
  assert.equal(balance.expandHome("~"), home);
  assert.equal(balance.expandHome("~/.claude/.credentials.json"), path.join(home, ".claude", ".credentials.json"));
  assert.equal(balance.expandHome("~/.local/bin/codex"), path.join(home, ".local", "bin", "codex"));
  // Not a home reference: a bare path, a `~` inside a path, another user's
  // `~name` form (unsupported on purpose — it needs a passwd lookup).
  assert.equal(balance.expandHome("/usr/local/bin/codex"), "/usr/local/bin/codex");
  assert.equal(balance.expandHome("/opt/~backup/x.json"), "/opt/~backup/x.json");
  assert.equal(balance.expandHome("~root/.claude/.credentials.json"), "~root/.claude/.credentials.json");
  assert.equal(balance.expandHome("./relative.json"), "./relative.json");
});

test("balance: file-backed defaults belong to the active user, not this machine's home", async () => {
  const balance = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const home = os.homedir();
  // The package is published to npm. A literal absolute home would ship this
  // host's layout as everyone's, and would read the wrong account under a
  // different uid; each stays overridable from the profile row.
  //
  // The shape is asserted rather than every literal: one of the three names
  // another runtime's own directory, and spelling it here would put this file
  // in the host-coupling ratchet's scan for no gain (the source constant is
  // where that name belongs).
  const openclawConfig = balance.DEFAULT_OPENCLAW_CONFIG_PATH;
  assert.equal(path.dirname(path.dirname(openclawConfig)), home,
    "the gateway config sits one directory below the active home");
  assert.match(path.basename(openclawConfig), /\.json$/, "the gateway config is a json file");
  assert.equal(balance.DEFAULT_CLAUDE_CREDENTIALS_PATH, path.join(home, ".claude", ".credentials.json"));
  assert.equal(balance.DEFAULT_CODEX_COMMAND, path.join(home, ".local", "bin", "codex"));
  for (const value of [
    openclawConfig,
    balance.DEFAULT_CLAUDE_CREDENTIALS_PATH,
    balance.DEFAULT_CODEX_COMMAND,
  ]) {
    assert.equal(path.isAbsolute(value), true, "a default path must still be absolute");
    assert.equal(value.startsWith(home + path.sep), true, "every default hangs off the active home");
  }
});

test("balance: the gateway owns its row config instead of a module-level handoff", async () => {
  // #1480-style regression guard. The config used to travel through a
  // module-level `pendingConfig` that apply() assigned just before ctx.plugin
  // built the service, and the balance method read it lazily on first call —
  // so a second apply() (or a second row) could overwrite the config of a
  // gateway whose balance() had not run yet. cordis constructs a class plugin
  // as `new Plugin(ctx, config)`, so the instance can just keep it.
  const mod = await import(pathToFileURL(path.join(PLUGIN, "lib", "index.js")).href);
  const upstream = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    upstream.push(String(url));
    return {
      ok: true,
      status: 200,
      json: async () => ({ is_available: true, balance_infos: [{ currency: "CNY", total_balance: "9.00" }] }),
    };
  };
  try {
    const built = [];
    const ctxFor = (config) => ({
      credentials: { resolve: async () => undefined },
      plugin: (Plugin, received) => { built.push({ Plugin, received, config }); },
    });
    const first = { balanceThreshold: 7 };
    const second = { balanceThreshold: 99 };
    mod.apply(ctxFor(first), first);
    mod.apply(ctxFor(second), second);
    assert.equal(built.length, 2);
    assert.equal(built[0].received, first, "apply must forward its own config to ctx.plugin");
    assert.equal(built[1].received, second, "a second apply must not rewrite the first one's config");
    // Build BOTH gateways the way cordis does (`new Plugin(ctx, config)`)
    // before either reads its balances, then read them. That ordering is the
    // whole point: the balance services are built lazily on the first
    // balance() call, so a module-level handoff only misbehaves once a later
    // apply/construct has run in between. `reflect.provide` is what the cordis
    // Service base calls to register the key on the owning context.
    const gateways = built.map(({ Plugin, config }) => ({
      config,
      gateway: new Plugin({
        credentials: { resolve: async () => undefined },
        reflect: { provide() {} },
      }, config),
    }));
    for (const { config, gateway } of gateways) {
      const answer = await gateway.balance(false);
      assert.equal(answer.providers[0].result.threshold, config.balanceThreshold,
        "the gateway must read the threshold it was constructed with");
    }
  } finally {
    if (realFetch === undefined) delete globalThis.fetch; else globalThis.fetch = realFetch;
  }
});

test("locale: both dictionaries carry the same keys, and no copy is hardcoded", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const zh = Object.keys(api.dictionaries.zh).sort();
  const en = Object.keys(api.dictionaries.en).sort();
  // A key in one language and not the other renders as the raw key in that
  // locale — the failure mode a translation change ships by accident.
  assert.deepEqual(en, zh, "zh and en must cover exactly the same keys");
  assert.ok(zh.length > 90, `expected the whole surface, found ${zh.length} keys`);
  assert.deepEqual(Object.keys(api.dictionaries).sort(), ["en", "zh"],
    "the browser client ships exactly these two locales (dsh-client-locale LOCALE_IDS)");
  // kcn 2026-11-07 saw "Patrol idle" while the supervisor was in a 12h free-pool
  // cooldown and read it as not running. The Chinese label already said
  // 等下一轮; English now says waiting too, so the phase does not imply stopped.
  assert.equal(api.dictionaries.en["queue.patrolState.waiting"], "waiting",
    "English must say waiting, not idle, between patrol rounds");
  for (const [locale, dict] of Object.entries(api.dictionaries)) {
    for (const [key, value] of Object.entries(dict)) {
      assert.equal(typeof value, "string", `${locale}.${key} must be a string`);
      assert.notEqual(value.trim(), "", `${locale}.${key} must not be empty`);
      // Every {name} in a template must be one the call site passes; a stray
      // brace is how a param silently renders literally.
      for (const [, name] of value.matchAll(/\{(\w+)\}/g)) {
        assert.match(name, /^[a-zA-Z]+$/, `${locale}.${key}: suspicious param {${name}}`);
      }
    }
  }
  // Missing key → the key itself, never a blank or a crash.
  assert.equal(api.createTranslator(api.dictionaries.en)("nope.missing"), "nope.missing");
  // Params interpolate; an unknown param keeps its placeholder rather than
  // printing "undefined" into the UI.
  const t = api.createTranslator({ "x.y": "{a}/{b}" });
  assert.equal(t("x.y", { a: 1, b: 2 }), "1/2");
  assert.equal(t("x.y", { a: 1 }), "1/{b}");
});

test("locale: the same number renders in the active language", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const answer = () => ({
    configured: true, status: "fresh", low: true, message: null, threshold: 20,
    snapshot: {
      isAvailable: true, unit: "pct", currency: "", totalBalance: "82", grantedBalance: "",
      toppedUpBalance: "", asOf: "2026-09-19T00:00:00.000Z",
      note: "5h 已用 82%,今天 19:09 重置",
      // Structured: the client renders the label and the reset itself, so the
      // host's own formatting never reaches the screen.
      windows: [{ label: "5h", percent: 82, resetAt: "今天 19:09", durationMins: 300, resetAtMs: Date.now() + 3600_000 }],
    },
  });
  const zhRow = api._rowDisplay(answer(), api.createTranslator(api.dictionaries.zh));
  const enRow = api._rowDisplay(answer(), api.createTranslator(api.dictionaries.en));
  assert.match(zhRow.title, /5h 已用 82%/, "zh names the window from durationMins");
  assert.match(zhRow.title, /(今天|明天) \d{2}:\d{2} 重置/, "zh stamps the reset from resetAtMs");
  assert.doesNotMatch(zhRow.title, /"今天 19:09"/, "the fixture's host string is not what rendered");
  assert.match(enRow.title, /5h 82% used/, "en names the same window in English");
  assert.match(enRow.title, /resets (today|tomorrow) \d{2}:\d{2}/, "en stamps the same reset in English");
  assert.notEqual(zhRow.title, enRow.title, "the locale must actually change the rendering");
  // The low sentence is localized too, and keeps the host's own vendor detail
  // verbatim — a provider's error text is not ours to translate.
  const stale = { ...answer(), status: "stale", message: "429 too many requests" };
  assert.match(api._balanceNote(stale, api.createTranslator(api.dictionaries.en)),
    /Refresh failed \(429 too many requests\); showing the reading of .*\d{2}:\d{2}/);
});

test("locale: a previous-version host omits the structured fields and still renders", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  // The two halves deploy independently: a client bundle swap lands on the next
  // page load, a host change needs a dsh restart. So the client WILL meet a
  // host that sends only `label` / `resetAt` / `verdict` — the keys are absent,
  // not null — and must render exactly what that host formatted.
  const legacy = {
    configured: true, status: "fresh", low: false, message: null, threshold: 20,
    snapshot: {
      isAvailable: true, unit: "pct", currency: "", totalBalance: "76", grantedBalance: "",
      toppedUpBalance: "", asOf: "2026-09-19T00:00:00.000Z",
      note: "周 已用 76%,9/21 周一 00:00 重置",
      windows: [{ label: "周", percent: 76, resetAt: "9/21 周一 00:00" }],
    },
  };
  const t = api.createTranslator(api.dictionaries.en);
  // An overdrawn balance keeps its minus outside the currency symbol (#2957).
  const overdrawn = { ...legacy, snapshot: { ...legacy.snapshot, unit: "money", currency: "USD",
    totalBalance: "-12.34", windows: [] } };
  assert.equal(api._rowDisplay(overdrawn, t).value, "−$12.34");
  const row = api._rowDisplay(legacy, t);
  assert.match(row.title, /周 76% used/, "the host's label is passed through, not turned into NaN");
  assert.match(row.title, /resets 9\/21 周一 00:00/, "the host's stamp is passed through");
  assert.doesNotMatch(row.title, /NaN|undefined/);
  assert.equal(row.sub, null, "one window means no second reading");
  const dual = { ...legacy, snapshot: { ...legacy.snapshot, windows: [
    { label: "周", percent: 76, resetAt: "9/21 周一 00:00" },
    { label: "5h", percent: 12, resetAt: "" },
  ] } };
  assert.match(api._rowDisplay(dual, t).sub, /· 5h 12%/);
  // Same rule for the T+1 verdict: `verdictKind` absent → the host's text.
  assert.equal(api.verdictOf(t, { verdict: "卖飞" }), "卖飞");
  assert.equal(api.verdictOf(t, { verdictKind: "soldEarly", verdict: "卖飞" }), "sold too early");
  assert.equal(api.verdictOf(api.createTranslator(api.dictionaries.zh), { verdictKind: "soldEarly", verdict: "卖飞" }), "卖飞");
});

test("balance: CNY picking, tolerant parsing and the service's polite-cadence states", async () => {
  const balance = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const { createBalanceService, parseBalancePayload, pickCnyBalanceInfo } = balance;

  // Entry picking: CNY preferred case-insensitively; the first entry is the
  // fallback; an empty payload reads as absent, never as a throw.
  const infos = [
    { currency: "USD", total_balance: "5.00" },
    { currency: "cny", total_balance: "110.00" },
  ];
  assert.equal(pickCnyBalanceInfo(infos).currency, "cny");
  assert.equal(pickCnyBalanceInfo([{ currency: "USD" }]).currency, "USD");
  assert.equal(pickCnyBalanceInfo(undefined), undefined);
  assert.equal(pickCnyBalanceInfo([]), undefined);

  // Parsing is tolerant: a shape drift degrades to '' / false instead of
  // throwing, so the box reads empty rather than crashing the tab.
  const parsed = parseBalancePayload({
    is_available: true,
    balance_infos: [{ currency: "CNY", total_balance: "110.00", granted_balance: "10.00", topped_up_balance: "100.00" }],
  }, "2026-08-23T10:00:00.000Z");
  assert.equal(parsed.totalBalance, "110.00");
  assert.equal(parsed.grantedBalance, "10.00");
  assert.equal(parsed.isAvailable, true);
  const degraded = parseBalancePayload({ nope: true }, "2026-08-23T10:00:00.000Z");
  assert.equal(degraded.totalBalance, "");
  // #2263: a missing flag is not the vendor saying "unusable" — only an explicit false is.
  assert.equal(degraded.isAvailable, true);
  assert.equal(parseBalancePayload({ is_available: false }, "2026-08-23T10:00:00.000Z").isAvailable, false);
  assert.equal(parseBalancePayload({
    balance_infos: [{ currency: "CNY", total_balance: "110.00" }],
  }, "2026-08-23T10:00:00.000Z").isAvailable, true);

  // Service: key from the credentials seam, TTL cache, forced refresh,
  // in-flight join, stale retention and the host-side low reading.
  let upstreamCalls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    upstreamCalls += 1;
    assert.match(String(url), /\/user\/balance$/);
    assert.equal(init.headers.authorization, "Bearer sk-test");
    return new Response(JSON.stringify({
      is_available: true,
      balance_infos: [{ currency: "CNY", total_balance: "9.00", granted_balance: "0.00", topped_up_balance: "9.00" }],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const service = createBalanceService({ credentials: { resolve: async () => ({ value: "sk-test" }) } }, { threshold: 10, refreshMs: 60000 });

    const fresh = await service.get(false);
    assert.equal(fresh.status, "fresh");
    assert.equal(fresh.snapshot.totalBalance, "9.00");
    assert.equal(fresh.low, true, "9 ≤ 10 must read low, decided host-side");
    assert.equal(fresh.threshold, 10);

    const cached = await service.get(false);
    assert.equal(cached.status, "cached");
    assert.equal(upstreamCalls, 1, "the TTL window serves from cache");

    const forced = await service.get(true);
    assert.equal(forced.status, "fresh");
    assert.equal(upstreamCalls, 2, "force bypasses the TTL");

    // Two concurrent callers join one upstream request.
    const [a, b] = await Promise.all([service.get(true), service.get(true)]);
    assert.equal(a.snapshot.totalBalance, "9.00");
    assert.equal(b.snapshot.totalBalance, "9.00");
    assert.equal(upstreamCalls, 3, "a racing poll joins the in-flight run");

    // A manual refresh racing a poll inside the TTL must not join the poll's
    // cached answer (#1567): it waits for the poll, then fetches itself.
    const [poll, manual, late] = await Promise.all([service.get(false), service.get(true), service.get(false)]);
    assert.equal(poll.status, "cached");
    assert.equal(manual.status, "fresh", "a forced refresh never reads as cached");
    assert.equal(late.status, "fresh", "a poll after the manual click joins the forced run");
    assert.equal(upstreamCalls, 4, "the forced run is one upstream request");

    // A failed refresh keeps the last good snapshot and reports stale —
    // a transient 429 cannot erase a real number.
    globalThis.fetch = async () => { throw new Error("down"); };
    const stale = await service.get(true);
    assert.equal(stale.status, "stale");
    assert.equal(stale.snapshot.totalBalance, "9.00");
    assert.match(stale.message, /down/);

    // The failure outlives the call that saw it (#1546): a non-forced read
    // inside the TTL still says stale, from cache, until a refresh succeeds.
    const staleCached = await service.get(false);
    assert.equal(staleCached.status, "stale", "a failed refresh must not read as cached");
    assert.equal(staleCached.snapshot.totalBalance, "9.00");
    assert.match(staleCached.message, /down/);
    assert.equal(upstreamCalls, 4, "the stale answer is served without hitting upstream");
    globalThis.fetch = async () => {
      upstreamCalls += 1;
      return new Response(JSON.stringify({
        is_available: true,
        balance_infos: [{ currency: "CNY", total_balance: "8.00" }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    };
    const recovered = await service.get(true);
    assert.equal(recovered.status, "fresh");
    assert.equal((await service.get(false)).status, "cached", "a successful refresh clears the stale mark");
  } finally {
    globalThis.fetch = originalFetch;
  }

  // No key anywhere → in-band no-key, never a throw.
  const noKeyService = createBalanceService({ credentials: { resolve: async () => undefined } });
  const noKey = await noKeyService.get(false);
  assert.equal(noKey.status, "no-key");
  assert.equal(noKey.status, "no-key");
  assert.equal(noKey.configured, false);
  assert.equal(noKey.snapshot, null);
  assert.match(noKey.message, /未配置/);

  // --- MiniMax: Token Plan quota windows, USED-percent display direction ---
  const { createMinimaxService, parseMinimaxRemains, windowUsedPercent } = balance;

  // The upstream percent field reports REMAINING and is complemented; raw
  // counts already are consumption and divide as-is; unreadable stays null.
  assert.equal(windowUsedPercent({ current_interval_remaining_percent: 88.4 }), 100 - 88.4);
  assert.equal(windowUsedPercent({ current_interval_remaining_percent: 0 }), 100, "a fresh window reads as fully unused");
  assert.equal(windowUsedPercent({ current_interval_total_count: 5000000, current_interval_usage_count: 1250000 }), 25);
  assert.equal(windowUsedPercent({ current_interval_total_count: 0, current_interval_usage_count: 0 }), null);
  assert.equal(windowUsedPercent({}), null);

  // The general bucket is the text/coding plan every account carries.
  const mmParsed = parseMinimaxRemains({
    base_resp: { status_code: 0, status_msg: "success" },
    model_remains: [
      { model: "video", current_interval_remaining_percent: 40 },
      { model: "general", current_interval_remaining_percent: 76.4, current_weekly_remaining_percent: 90, end_time: Date.now() + 3600_000 },
    ],
  }, AS_OF);
  assert.equal(mmParsed.unit, "pct");
  assert.equal(mmParsed.totalBalance, "24", "remaining 76.4 → used 23.6, rounded for display only");
  assert.deepEqual(mmParsed.windows.map((w) => [w.label, w.percent]), [["5h", 24], ["周", 10]]);
  assert.match(mmParsed.windows[0].resetAt, RESET_STAMP);
  assert.throws(() => parseMinimaxRemains({ base_resp: { status_code: 0 } }, AS_OF), /model_remains/);
  // Epoch seconds AND milliseconds both read; garbage does not crash.
  const withReset = parseMinimaxRemains({
    base_resp: { status_code: 0 },
    model_remains: [{ model: "general", current_interval_remaining_percent: 50, end_time: 1785196800000 }],
  }, AS_OF);
  assert.match(withReset.windows[0].resetAt, RESET_STAMP);

  // The live payload (2026-09-13) names the bucket `model_name`, not `model`,
  // and puts the video bucket first: matching on `model` alone silently read
  // the video plan. Interval bounds carry resets; the plan's five-hour
  // window is independent of a shortened/extended interval.
  const now = new Date(2026, 8, 13, 20, 0).getTime();
  const live = parseMinimaxRemains({
    base_resp: { status_code: 0, status_msg: "success" },
    model_remains: [
      { model_name: "video", current_interval_remaining_percent: 5 },
      {
        model_name: "general",
        start_time: new Date(2026, 8, 13, 16, 0).getTime(), end_time: new Date(2026, 8, 13, 20, 0).getTime() + 4 * 3600_000,
        current_interval_remaining_percent: 100,
        weekly_start_time: new Date(2026, 8, 7, 0, 0).getTime(), weekly_end_time: new Date(2026, 8, 14, 0, 0).getTime(),
        current_weekly_remaining_percent: 17,
      },
    ],
  }, AS_OF, now);
  assert.deepEqual(live.windows.map((w) => [w.label, w.percent, w.resetAt]),
    [["5h", 0, "明天 00:00"], ["周", 83, "明天 00:00"]]);
  assert.equal(live.note, "5h 已用 0%,明天 00:00 重置 · 周 已用 83%,明天 00:00 重置");

  const shortInterval = parseMinimaxRemains({model_remains: [{model_name: "general",
    start_time: now, end_time: now + 4 * 3600_000, current_interval_remaining_percent: 81}]}, AS_OF, now);
  assert.equal(shortInterval.windows[0].label, "5h");
  assert.equal(shortInterval.windows[0].resetAtMs, now + 4 * 3600_000);
  assert.throws(() => parseMinimaxRemains({model_remains: [{model_name: "video", current_interval_remaining_percent: 99}]}, AS_OF), /general/);

  let minimaxCalls = 0;
  globalThis.fetch = async (url, init) => {
    minimaxCalls += 1;
    assert.match(String(url), /\/v1\/token_plan\/remains$/);
    assert.equal(init.headers.authorization, "Bearer mm-test");
    // A HTTP-200 body can still be a business failure — the envelope decides.
    return new Response(JSON.stringify({
      base_resp: { status_code: 1004, status_msg: "login fail" },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const mmService = createMinimaxService({ credentials: { resolve: async () => ({ value: "mm-test" }) } });
    const authFail = await mmService.get(true);
    assert.equal(authFail.status, "failed");
    assert.match(authFail.message, /无效或已过期/);
    assert.match(authFail.message, /login fail/, "the upstream reason rides along");

    globalThis.fetch = async () => new Response(JSON.stringify({
      base_resp: { status_code: 0, status_msg: "success" },
      model_remains: [{ model: "general", current_interval_remaining_percent: 12 }],
    }), { status: 200, headers: { "content-type": "application/json" } });
    const lowQuota = await createMinimaxService({ credentials: { resolve: async () => ({ value: "mm-test" }) } }).get(true);
    assert.equal(lowQuota.status, "fresh");
    assert.equal(lowQuota.low, true, "remaining 12% → used 88% ≥ 100−20, the watermark in used direction");
    assert.equal(lowQuota.snapshot.unit, "pct");
  } finally {
    globalThis.fetch = originalFetch;
  }

  // MiniMax with no key configured ANYWHERE (seam, env, then the gateway
  // config fallback) is an honest panel row, not an error. That fallback must
  // be pointed at a missing file — the real one carries the production key.
  const mmMissing = { credentials: { resolve: async () => undefined }, env: {} };
  const savedEnv = process.env.MINIMAX_API_KEY;
  delete process.env.MINIMAX_API_KEY;
  try {
    const mmNoKey = await createMinimaxService(
      { credentials: { resolve: async () => undefined } },
      { openclawConfigPath: "/nonexistent/provider-keys.json" },
    ).get(false);
    assert.equal(mmNoKey.status, "no-key");
    assert.match(mmNoKey.message, /未配置/);
  } finally {
    if (savedEnv !== undefined) process.env.MINIMAX_API_KEY = savedEnv;
  }

  // The openclaw-config fallback: when seam and env are both empty, the
  // gateway's own models.providers.<name>.apiKey answers.
  const osMod = await import("node:os");
  const fsMod = await import("node:fs");
  const pathMod = await import("node:path");
  const tmpCfg = fsMod.mkdtempSync(pathMod.join(osMod.tmpdir(), "pb-"));
  const cfgPath = pathMod.join(tmpCfg, "gateway-keys.json");
  fsMod.writeFileSync(cfgPath, JSON.stringify({ models: { providers: { minimax: { apiKey: "mm-from-openclaw" } } } }));
  let sawAuth = "";
  globalThis.fetch = async (url, init) => {
    sawAuth = init.headers.authorization;
    return new Response(JSON.stringify({
      base_resp: { status_code: 0, status_msg: "success" },
      model_remains: [{ model: "general", current_interval_remaining_percent: 50 }],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const mmFallback = await createMinimaxService(
      { credentials: { resolve: async () => undefined } },
      { openclawConfigPath: cfgPath },
    ).get(true);
    assert.equal(sawAuth, "Bearer mm-from-openclaw", "key resolved from the openclaw gateway config");
    assert.equal(mmFallback.status, "fresh");
  } finally {
    globalThis.fetch = originalFetch;
    fsMod.rmSync(tmpCfg, { recursive: true, force: true });
  }

  // Since 2026-11 `openclaw config patch` writes provider keys as secret
  // references instead of strings. The fallback must resolve them through
  // `secrets.providers.<provider>` — a JSON file plus an absolute JSON
  // pointer id — and keep the plain string shape working (pinned above).
  const refTmp = fsMod.mkdtempSync(pathMod.join(osMod.tmpdir(), "mmref-"));
  const refCfgPath = pathMod.join(refTmp, "gateway-keys.json");
  const secretsPath = pathMod.join(refTmp, "credentials.json");
  fsMod.writeFileSync(secretsPath, JSON.stringify({
    models: { providers: { minimax: { apiKey: "mm-from-secrets" } } },
  }));
  const refConfig = (apiKey, localProvider) => JSON.stringify({
    models: { providers: { minimax: { apiKey } } },
    secrets: { providers: { local: localProvider } },
  });
  const ref = { source: "file", provider: "local", id: "/models/providers/minimax/apiKey" };
  let sawRefAuth = "";
  globalThis.fetch = async (url, init) => {
    sawRefAuth = init.headers.authorization;
    return new Response(JSON.stringify({
      base_resp: { status_code: 0, status_msg: "success" },
      model_remains: [{ model: "general", current_interval_remaining_percent: 50 }],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    fsMod.writeFileSync(refCfgPath, refConfig(ref, { source: "file", path: secretsPath, mode: "json" }));
    const mmRef = await createMinimaxService(
      { credentials: { resolve: async () => undefined } },
      { openclawConfigPath: refCfgPath },
    ).get(true);
    assert.equal(sawRefAuth, "Bearer mm-from-secrets", "the secret reference resolves through secrets.providers.local");
    assert.equal(mmRef.status, "fresh");

    // A reference whose provider file is missing is a failed read, not
    // "not configured": the key IS configured, it just cannot be read.
    fsMod.writeFileSync(refCfgPath, refConfig(ref, {
      source: "file", path: pathMod.join(refTmp, "gone.json"), mode: "json",
    }));
    const mmGone = await createMinimaxService(
      { credentials: { resolve: async () => undefined } },
      { openclawConfigPath: refCfgPath },
    ).get(true);
    assert.equal(mmGone.status, "failed");
    assert.match(mmGone.message, /密钥文件不存在/);

    // ... and so is an id the file does not carry.
    fsMod.writeFileSync(refCfgPath, refConfig(
      { source: "file", provider: "local", id: "/models/providers/minimax/nope" },
      { source: "file", path: secretsPath, mode: "json" },
    ));
    const mmMissingId = await createMinimaxService(
      { credentials: { resolve: async () => undefined } },
      { openclawConfigPath: refCfgPath },
    ).get(true);
    assert.equal(mmMissingId.status, "failed");
    assert.match(mmMissingId.message, /找不到段/);

    // JSON.parse diagnostics can quote the input, which is a credential file.
    // Exercise both the newly supported secret file and the gateway config.
    for (const target of [secretsPath, refCfgPath]) {
      fsMod.writeFileSync(refCfgPath, refConfig(ref, { source: "file", path: secretsPath }));
      fsMod.writeFileSync(target, 'sekret');
      const failed = await createMinimaxService(
        { credentials: { resolve: async () => undefined } },
        { openclawConfigPath: refCfgPath },
      ).get(true);
      assert.equal(failed.status, "failed");
      assert.match(failed.message, /读不出来/);
      assert.ok(!JSON.stringify(failed).includes("sekret"),
        "credential parse errors must not reach the balance response");
    }

  } finally {
    globalThis.fetch = originalFetch;
    fsMod.rmSync(refTmp, { recursive: true, force: true });
  }
});

test("balance: claude subscription windows via the OAuth usage endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const balance = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const { createClaudeService, parseClaudeUsage, readClaudeCredentials } = balance;
  const osMod = await import("node:os");
  const fsMod = await import("node:fs");
  const pathMod = await import("node:path");

  // Credentials file parsing: tolerant of absence.
  assert.equal(readClaudeCredentials("/nonexistent/creds.json"), undefined);

  const tmp = fsMod.mkdtempSync(pathMod.join(osMod.tmpdir(), "pc-"));
  const credsPath = pathMod.join(tmp, ".credentials.json");
  const future = Date.now() + 3600_000;
  const past = Date.now() - 1000;
  fsMod.writeFileSync(credsPath, JSON.stringify({
    claudeAiOauth: { accessToken: "sk-ant-oat01-test", refreshToken: "ort01", expiresAt: future, subscriptionType: "max" },
  }));

  // utilization IS the used percent (kcn: 「已使用」直观) — rendered verbatim,
  // no complementing anywhere.
  const usageBody = {
    five_hour: { utilization: 36, resets_at: "2026-08-24T02:00:00Z" },
    seven_day: { utilization: 69 },
  };
  let sawHeaders = {};
  globalThis.fetch = async (url, init) => {
    sawHeaders = init.headers;
    assert.match(String(url), /api\.anthropic\.com\/api\/oauth\/usage$/);
    return new Response(JSON.stringify(usageBody), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const svc = createClaudeService(
      { credentials: { resolve: async () => undefined } },
      { credentialsPath: credsPath, usageUrl: "https://api.anthropic.com/api/oauth/usage" },
    );
    const fresh = await svc.get(true);
    assert.equal(fresh.status, "fresh");
    assert.equal(fresh.snapshot.unit, "pct");
    assert.equal(fresh.snapshot.totalBalance, "36", "utilization reads through untouched");
    // Same labels as every other provider: the window's length names it.
    assert.deepEqual(fresh.snapshot.windows.map((w) => [w.label, w.percent]), [["5h", 36], ["周", 69]]);
    assert.match(fresh.snapshot.windows[0].resetAt, RESET_STAMP);
    assert.match(fresh.snapshot.note, /5h 已用 36%/);
    assert.match(fresh.snapshot.note, /周 已用 69%/, "note mirrors the weekly window");
    assert.equal(sawHeaders["anthropic-beta"], "oauth-2025-04-20", "the beta header is required");
    assert.equal(sawHeaders.authorization, "Bearer sk-ant-oat01-test");

    // Expired login → honest failed row telling kcn to re-run claude once.
    fsMod.writeFileSync(credsPath, JSON.stringify({
      claudeAiOauth: { accessToken: "stale", refreshToken: "r", expiresAt: past },
    }));
    const expired = await createClaudeService(
      { credentials: { resolve: async () => undefined } },
      { credentialsPath: credsPath, usageUrl: "https://api.anthropic.com/api/oauth/usage" },
    ).get(true);
    assert.equal(expired.status, "failed");
    // The access token ages out whenever nobody runs claude for a few hours. With a refresh
    // token on file that is not a lost login, and the row must not read like one.
    assert.match(expired.message, /访问令牌到期/);
    assert.match(expired.message, /不是登录失效/);
    assert.match(expired.message, /自动续期/);
    assert.doesNotMatch(expired.message, /重新登录|登录已过期/);
    fsMod.writeFileSync(credsPath, JSON.stringify({ claudeAiOauth: { accessToken: "stale", expiresAt: past } }));
    const loggedOut = await createClaudeService(
      { credentials: { resolve: async () => undefined } },
      { credentialsPath: credsPath, usageUrl: "https://api.anthropic.com/api/oauth/usage" },
    ).get(true);
    assert.match(loggedOut.message, /登录已过期.*重新登录/, "no refresh token: only then is a login asked for");

    // Missing file entirely → in-band no-key.
    const none = await createClaudeService(
      { credentials: { resolve: async () => undefined } },
      { credentialsPath: "/nonexistent/creds.json", usageUrl: "https://api.anthropic.com/api/oauth/usage" },
    ).get(false);
    assert.equal(none.status, "no-key");

    // #2266: present but unreadable is a failed read, not "not configured".
    const brokenPath = pathMod.join(tmp, "broken.json");
    fsMod.writeFileSync(brokenPath, "{ not json");
    const unreadable = await createClaudeService(
      { credentials: { resolve: async () => undefined } },
      { credentialsPath: brokenPath, usageUrl: "https://api.anthropic.com/api/oauth/usage" },
    ).get(false);
    assert.equal(unreadable.status, "failed");
    assert.match(unreadable.message, /读不出来/);
    for (const value of [{ claudeAiOauth: {} }, {}, { claudeAiOauth: { accessToken: " " } }]) {
      fsMod.writeFileSync(credsPath, JSON.stringify(value));
      const tokenless = await svc.get(true);
      assert.equal(tokenless.status, "stale");
      assert.equal(tokenless.snapshot.totalBalance, "36");
      assert.match(tokenless.message, /没有可用 accessToken/);
      const cold = await createClaudeService({ credentials: { resolve: async () => undefined } },
        { credentialsPath: credsPath }).get(true);
      assert.equal(cold.status, "failed");
    }
    const configPath = pathMod.join(tmp, "provider-fixture.json");
    fsMod.writeFileSync(configPath, "{ broken");
    const minimax = await balance.createMinimaxService({ credentials: { resolve: async () => undefined } },
      { keyRef: "SWEEP_NO_KEY", openclawConfigPath: configPath }).get(true);
    assert.equal(minimax.status, "failed");
    assert.match(minimax.message, /配置读不出来/);
  } finally {
    globalThis.fetch = originalFetch;
    fsMod.rmSync(tmp, { recursive: true, force: true });
  }

  // Both windows absent → honest failure, never a fabricated number.
  assert.throws(() => parseClaudeUsage({}, AS_OF), /用量窗口/);
});

test("balance: codex subscription windows via the official app-server", async () => {
  const balance = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const { createCodexService, parseCodexRateLimits, readCodexRateLimits } = balance;
  const osMod = await import("node:os");
  const fsMod = await import("node:fs");
  const pathMod = await import("node:path");

  const parsed = parseCodexRateLimits({
    ordinaryUsageAllowed: true,
    rateLimits: {
      primary: { usedPercent: 18.4, windowDurationMins: 300, resetsAt: 1785196800 },
      secondary: { usedPercent: 81.2, windowDurationMins: 10080, resetsAt: 1785801600 },
    },
  }, AS_OF);
  assert.equal(parsed.isAvailable, true);
  assert.equal(parsed.totalBalance, "18");
  assert.deepEqual(parsed.windows.map((w) => [w.label, w.percent]), [["5h", 18], ["周", 81]]);
  assert.match(parsed.windows[0].resetAt, RESET_STAMP);
  assert.throws(() => parseCodexRateLimits({ ordinaryUsageAllowed: true }, AS_OF), /额度数据/);

  const tmp = fsMod.mkdtempSync(pathMod.join(osMod.tmpdir(), "codex-app-server-"));
  const fake = pathMod.join(tmp, "codex");
  fsMod.writeFileSync(fake, `#!/usr/bin/env node
const readline = require("node:readline");
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const msg = JSON.parse(line);
  if (msg.id === 0) process.stdout.write(JSON.stringify({ id: 0, result: { userAgent: "fake" } }) + "\\n");
  if (msg.id === 1) process.stdout.write(JSON.stringify({ id: 1, result: {
    ordinaryUsageAllowed: true,
    rateLimitsByLimitId: { codex: {
      primary: { usedPercent: 22, windowDurationMins: 300 },
      secondary: { usedPercent: 44, windowDurationMins: 10080 }
    } }
  } }) + "\\n");
});
`);
  fsMod.chmodSync(fake, 0o755);
  try {
    const raw = await readCodexRateLimits(fake, 2000);
    assert.equal(raw.rateLimitsByLimitId.codex.primary.usedPercent, 22, "initialize then quota RPC completes");

    const service = createCodexService(
      { credentials: { resolve: async () => undefined } },
      { command: fake, lowPct: 20, refreshMs: 300000 },
    );
    const fresh = await service.get(false);
    assert.equal(fresh.status, "fresh");
    assert.equal(fresh.snapshot.totalBalance, "22");
    assert.equal(fresh.low, false);
    assert.equal(fresh.refreshMs, 300000);
    const cached = await service.get(false);
    assert.equal(cached.status, "cached", "Codex keeps its longer app-server TTL");

    const weeklyLow = parseCodexRateLimits({
      ordinaryUsageAllowed: true,
      rateLimits: {
        primary: { usedPercent: 10, windowDurationMins: 300 },
        secondary: { usedPercent: 84, windowDurationMins: 10080 },
      },
    }, AS_OF);
    const weeklyLowFake = pathMod.join(tmp, "codex-weekly-low");
    fsMod.writeFileSync(weeklyLowFake, fsMod.readFileSync(fake, "utf8").replace(
      "primary: { usedPercent: 22,",
      "primary: { usedPercent: 10,",
    ).replace(
      "secondary: { usedPercent: 44,",
      "secondary: { usedPercent: 84,",
    ));
    fsMod.chmodSync(weeklyLowFake, 0o755);
    assert.equal(weeklyLow.windows[1].percent, 84);
    const weeklyLowResult = await createCodexService(
      { credentials: { resolve: async () => undefined } },
      { command: weeklyLowFake, lowPct: 20 },
    ).get(true);
    assert.equal(weeklyLowResult.low, true, "either Codex window crossing the watermark lights the row");

    const missing = await createCodexService(
      { credentials: { resolve: async () => undefined } },
      { command: pathMod.join(tmp, "missing-codex") },
    ).get(false);
    assert.equal(missing.status, "no-key");
    assert.match(missing.message, /未找到 Codex CLI/);
  } finally {
    fsMod.rmSync(tmp, { recursive: true, force: true });
  }
});

test("typert: the frozen artifacts carry hand-maintained wire fields on both faces", () => {
  // The clawock checkout cannot regenerate the Typert face (see build.mjs):
  // these committed files ARE the wire. A method missing here is a method
  // the client cannot call — the same class of failure as #738's alignment.
  for (const rel of ["lib/typert.host.js", "lib/typert.remote-client.js"]) {
    const src = fs.readFileSync(path.join(PLUGIN, rel), "utf8");
    assert.match(src, /id: 'clawock-dsh#clawockStudio\/balance'/, rel);
    assert.match(src, /clawock_dsh_clawockStudio_balance_parameter_0\$schema = z\.boolean\(\)/, rel + " force codec");
    assert.match(src, /typeSymbol: 'clawock-dsh\/types#BalancesResult'/, rel + " result type (multi-provider envelope)");
    assert.match(src, /'providers': z\.array\(z\.object\(/, rel + " per-provider rows on the wire");
    assert.match(src, /'unit': z\.string\(\)/, rel + " snapshot unit discriminator");
    assert.match(src, /'refreshMs': z\.number\(\)/, rel + " result schema field");
    assert.match(src, /'side': z\.union\(\[z\.literal\("add"\), z\.literal\("reduce"\), z\.literal\(null\)\]\)/,
      rel + " host-computed trade side");
  }
  const client = fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8");
  assert.match(client, /"side": union\(\[\s*literal\("add"\),\s*literal\("reduce"\),\s*literal\(null\)/,
    "the browser bundle embeds the same trade-side decoder");
});

test("typert: every shipped codec meets DSH 0.1.7's create() contract", async () => {
  for (const rel of ["lib/typert.host.js", "lib/typert.remote-client.js"]) {
    const face = await import(pathToFileURL(path.join(PLUGIN, rel)).href);
    const invocations = face.TYPERT?.invocations ?? face.TYPERT_REMOTE.descriptors;
    assert.equal(invocations.length, 11, rel);
    for (const invocation of invocations) {
      for (const codec of [...invocation.parameters.map((parameter) => parameter.codec), invocation.result]) {
        assert.equal(typeof codec.create, "function", `${rel}: ${invocation.id}`);
        assert.equal(typeof codec.create().safeParse, "function", `${rel}: ${invocation.id} schema`);
      }
    }
  }
});

test("client: the header chip headlines one provider and the panel pins the rest", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });

  // DeepSeek low + MiniMax healthy: the pill headlines the FIRST row until a
  // panel click pins another one.
  const envelope = { providers: [DS_ROW_OK, MM_ROW_OK, CL_ROW_OK, CX_ROW_OK], refreshMs: 60000 };
  const remoteFace = { balance: async () => ({ ok: true, value: envelope }) };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const __chip = ctx.slots._regs.find((r) => r.definition.id === "provider-balance");
  const Chip = __chip.Component;
  const injected = __chip.definition.inject("s1");
  const store = makeBalanceStoreStub();

  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const render = () => { reactStub._resetCursor(); return Chip({ sessionId: "s1", t: translatorFor(api), useStore: store.useStore, actions: store.actions, ...injected }); };

  // Collect chip item / panel rows separately via data-pb-role.
  const collect = (tree) => {
    const found = { chip: [], panel: [], openAttr: null, inertAttr: null, trigger: null, refresh: null, texts: [] };
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { found.texts.push(node); return; }
      const p = node.props || {};
      if (p["data-pb-role"] === "chip") found.chip.push(p);
      if (p["data-pb-role"] === "panel") found.panel.push(node);
      if (p["data-open"] !== undefined) found.openAttr = p["data-open"];
      if (p["data-open"] !== undefined) found.inertAttr = p.inert;
      if (p["aria-haspopup"] === "dialog") found.trigger = node;
      if (p["data-refresh"] === "true") found.refresh = node;
      (node.children || []).forEach(walk);
    })(tree);
    return found;
  };

  let tree = render();
  await tick(); await tick(); await tick();
  tree = render();
  let f = collect(tree);
  // Pill: exactly ONE headline reading — deepseek, the stable first row.
  assert.equal(f.chip.length, 1, "the pill headlines exactly one provider");
  assert.equal(f.chip[0]["data-pb-provider"], "deepseek", "default headline is the first configured row");
  assert.equal(f.chip[0]["data-balance-state"], "ok");
  assert.ok(f.texts.includes("¥110"), "the headlined value renders");
  const chipValueDefault = (function findChipValue(node) {
    if (node == null || Array.isArray(node)) return null;
    if (typeof node === "object" && node.props && typeof node.props.className === "string" &&
        node.props.className.includes("bchip-v")) return node.props;
    for (const child of node.children || []) { const hit = findChipValue(child); if (hit) return hit; }
    return null;
  })(tree);
  assert.equal(chipValueDefault["data-used-level"], undefined, "money headlines carry no usage tier");
  // Panel: mounted closed, every provider listed with its own tone.
  assert.equal(f.openAttr, "false", "the panel renders closed but mounted");
  assert.equal(f.inertAttr, "", "the closed panel is inert so its rows stay out of the tab order");
  assert.deepEqual(f.panel.map((n) => n.props["data-pb-provider"]), ["deepseek", "minimax", "claude", "codex"]);
  assert.ok(f.refresh, "the manual refresh lives in the panel header");

  // Open → click the minimax row → the pill re-headlines minimax (persisted).
  f.trigger.props.onClick();
  tree = render();
  f = collect(tree);
  assert.equal(f.openAttr, "true", "the panel opens from the trigger");
  assert.equal(f.inertAttr, undefined, "an open panel is interactive again");
  const mmRow = f.panel.find((n) => n.props["data-pb-provider"] === "minimax");
  assert.ok(mmRow, "panel rows are buttons");
  mmRow.props.onClick();
  tree = render();
  f = collect(tree);
  assert.equal(f.chip[0]["data-pb-provider"], "minimax", "clicking a panel row pins it as the headline");
  assert.equal(f.chip[0]["data-balance-state"], "ok");
  assert.equal(store._get().selected, "minimax", "the pin survives in registration-store state");
  assert.ok(f.texts.includes("24%"), "the pinned quota reading renders (used direction)");
  const chipValueQuota = (function findChipValue2(node) {
    if (node == null || Array.isArray(node)) return null;
    if (typeof node === "object" && node.props && typeof node.props.className === "string" &&
        node.props.className.includes("bchip-v")) return node.props;
    for (const child of node.children || []) { const hit = findChipValue2(child); if (hit) return hit; }
    return null;
  })(tree);
  assert.equal(chipValueQuota["data-used-level"], "ok", "the pill number tints by usage tier — green while usage is low");
  assert.ok(
    f.texts.some((t) => t.includes("周 10%")),
    "the weekly limit rides along on the pill as a muted sub-reading",
  );

  // Manual refresh resolves through the same remote face without throwing.
  f.refresh.props.onClick();
  await tick(); await tick();
  assert.ok(true, "manual refresh resolves without throwing");
  disposeReactEffects();
});

test("balance: every face asking at once is one upstream request, and another only after the window", async () => {
  // The lazy cadence adds askers (the badge tick, "became read", a sibling surface, the chat
  // command) — the bound on upstream traffic is still the service's, not the callers' restraint.
  const { createClaudeService } = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-join-"));
  const credsPath = path.join(tmp, "creds.json");
  fs.writeFileSync(credsPath, JSON.stringify({ claudeAiOauth: { accessToken: "t", refreshToken: "r", expiresAt: Date.now() + 3600000 } }));
  let upstream = 0;
  let release = null;
  const originalFetch = globalThis.fetch;
  const realNow = Date.now;
  globalThis.fetch = async () => {
    upstream += 1;
    await new Promise((resolve) => { release = resolve; });
    return new Response(JSON.stringify({ five_hour: { utilization: 10, resets_at: null }, seven_day: { utilization: 20, resets_at: null } }),
      { status: 200, headers: { "content-type": "application/json" } });
  };
  const settle = async () => { for (let i = 0; i < 20 && release === null; i++) await new Promise((r) => setImmediate(r)); const go = release; release = null; go(); };
  try {
    const service = createClaudeService({ credentials: { resolve: async () => undefined } }, { credentialsPath: credsPath });
    // Cold: a badge tick, the panel opening and two more faces, all before the first answer.
    const cold = Promise.all([service.get(false), service.get(false), service.get(false), service.get(false)]);
    await settle();
    assert.deepEqual((await cold).map((r) => r.status), ["fresh", "fresh", "fresh", "fresh"]);
    assert.equal(upstream, 1, "four concurrent readers, one request");
    // Inside the window any number of non-forced reads costs nothing.
    for (let i = 0; i < 10; i++) assert.equal((await service.get(false)).status, "cached");
    assert.equal(upstream, 1);
    // A manual click landing on top of a burst of non-forced reads: exactly one more request.
    const burst = Promise.all([service.get(false), service.get(true), service.get(false), service.get(true)]);
    await settle();
    await burst;
    assert.equal(upstream, 2, "a forced refresh amid polls is one request, not one per caller");
    // After the window a burst is again exactly one.
    const later = realNow() + 61000;
    Date.now = () => later;
    const next = Promise.all([service.get(false), service.get(false), service.get(false)]);
    await settle();
    await next;
    assert.equal(upstream, 3);
  } finally {
    globalThis.fetch = originalFetch;
    Date.now = realNow;
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("balance: a process that never read anything falls back on the last reading another one left", async () => {
  // dsh and the OpenClaw gateway restart; Claude's access token ages out when nobody runs claude
  // overnight. The first read after both used to be a bare dash: the last good reading lived only
  // in the memory of the process that took it, and since the rail stopped polling (#2882) a
  // process can go hours without taking one.
  const { createClaudeService, readLastGood } = await import(pathToFileURL(path.join(PLUGIN, "lib", "balance.js")).href);
  const chat = await import(pathToFileURL(path.join(PLUGIN, "lib", "chat.js")).href);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-lastgood-"));
  const credsPath = path.join(tmp, "creds.json");
  const login = (expiresAt) => fs.writeFileSync(credsPath,
    JSON.stringify({ claudeAiOauth: { accessToken: "t", refreshToken: "r", expiresAt } }));
  const config = { claudeCredentialsPath: credsPath, minimaxOpenclawConfigPath: path.join(tmp, "none.json"),
    minimaxKeyRef: "LASTGOOD_NO_KEY", codexCommand: path.join(tmp, "no-codex") };
  const credentials = { resolve: async () => undefined };
  // The file both hosts' reader (desk.ts) gives the Claude service; a new service is a new process.
  const kept = path.join(process.env.CLAWOCK_DSH_STATE_DIR, "balance-claude.json");
  const processOf = () => createClaudeService({ credentials }, { credentialsPath: credsPath, lastGoodPath: kept });
  const originalFetch = globalThis.fetch;
  const realNow = Date.now;
  const savedKey = process.env.DEEPSEEK_API_KEY;
  delete process.env.DEEPSEEK_API_KEY;
  let used = 36;
  let upstream = 0;
  globalThis.fetch = async () => {
    upstream += 1;
    return new Response(JSON.stringify({ five_hour: { utilization: used, resets_at: null }, seven_day: { utilization: 69, resets_at: null } }),
      { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    fs.rmSync(kept, { force: true });
    login(realNow() + 3600000);
    // One process reads while the token is good.
    const first = processOf();
    assert.equal((await first.get(true)).status, "fresh");
    assert.equal(readLastGood(kept).totalBalance, "36");
    assert.doesNotMatch(fs.readFileSync(kept, "utf8"), /"t"|accessToken/, "the kept reading carries no credential");

    // Hours later the token has aged out and a NEW process is asked first.
    const later = realNow() + 9 * 3600000;
    Date.now = () => later;
    login(later - 1000);
    const restarted = await processOf().get(false);
    assert.equal(restarted.status, "stale", "the last reading is shown, marked stale");
    assert.equal(restarted.snapshot.totalBalance, "36");
    assert.match(restarted.message, /访问令牌到期/);
    assert.equal(upstream, 1, "an aged-out token is not sent upstream");
    // Without the kept reading the same read has nothing to show (the service's own behaviour).
    const bare = await createClaudeService({ credentials }, { credentialsPath: credsPath }).get(false);
    assert.equal(bare.status, "failed");
    assert.equal(bare.snapshot, null);

    // The OpenClaw command is a third process; its reply carries the number and says whose it is.
    let command = null;
    chat.default({
      pluginConfig: { ...config, dispatchLogDir: path.join(tmp, "no-dispatch"), patrolStateDir: path.join(tmp, "no-patrol"),
        dispatchLimitsPath: path.join(tmp, "limits.env"), taskQueueOpsPath: path.join(tmp, "ops.py") },
      registerCommand: (registered) => { if (registered.name === "dispatch-list") command = registered; },
    });
    const reply = (await command.handler({ args: "", config: { agents: { defaults: { workspace: tmp } } } })).text;
    assert.match(reply, /36%/);
    assert.match(reply, /刷新失败（.*访问令牌到期.*），显示 .* 的读数/);

    // A long-lived process prefers a newer reading another process took over its own older one,
    // and that reading is inside the TTL, so it is not fetched again. (Real clock from here: a
    // reading is stamped with `new Date()`, and the two must be told apart.)
    Date.now = realNow;
    await new Promise((resolve) => setTimeout(resolve, 5));
    login(realNow() + 3600000);
    used = 52;
    assert.equal((await processOf().get(true)).snapshot.totalBalance, "52");
    const seen = upstream;
    const adopted = await first.get(false);
    assert.equal(adopted.snapshot.totalBalance, "52");
    assert.equal(adopted.status, "cached");
    assert.equal(upstream, seen);

    // A file that is not a reading is ignored, not shown.
    fs.writeFileSync(kept, JSON.stringify({ snapshot: { totalBalance: "99" } }));
    assert.equal(readLastGood(kept), null);
    login(realNow() - 1000);
    assert.equal((await processOf().get(false)).status, "failed");
  } finally {
    globalThis.fetch = originalFetch;
    Date.now = realNow;
    if (savedKey !== undefined) process.env.DEEPSEEK_API_KEY = savedKey;
    fs.rmSync(kept, { force: true });
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("quota line: an exhausted window says quota, names when it is back, and rules out the login", async () => {
  // ops/host/agent-dispatch/quota.mjs is the notification's reader. Its line used to end in a bare
  // 「当前不可用」; read on a phone that is indistinguishable from a broken login.
  const { execFileSync } = require("node:child_process");
  const QUOTA = path.join(__dirname, "..", "ops", "host", "agent-dispatch", "quota.mjs");
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-quota-"));
  const lib = path.join(tmp, "balance.mjs");
  fs.writeFileSync(lib, "const answer = JSON.parse(process.env.FAKE_QUOTA_RESULT)\n"
    + "export const _usedLevel = (percent, threshold) => percent >= 100 - threshold ? 'low' : percent >= 100 - 2 * threshold ? 'mid' : 'ok'\n"
    + "export const createClaudeService = () => ({ get: async () => answer })\n"
    + "export const createCodexService = createClaudeService\n");
  let n = 0;
  const line = (result, agent = "claude") => execFileSync(process.execPath, [QUOTA, agent], {
    encoding: "utf8",
    env: { ...process.env, AGENT_DISPATCH_BALANCE_LIB: lib, AGENT_DISPATCH_QUOTA_CACHE_DIR: path.join(tmp, "c" + (n += 1)), FAKE_QUOTA_RESULT: JSON.stringify(result) },
  }).trim();
  const win = (label, percent, resetAt, resetAtMs) => ({ label, percent, resetAt, resetAtMs });
  const fresh = (windows, isAvailable) => ({ status: "fresh", message: null, snapshot: { isAvailable, windows } });
  try {
    assert.equal(line(fresh([win("5h", 17, "今天 22:19", 2000), win("周", 1, "10/18 周日 20:00", 9000)], true)),
      "额度：5h 已用 17%（今天 22:19 重置） · 周 已用 1%（10/18 周日 20:00 重置）", "a usable account gains no words");
    assert.match(line({ ...fresh([win("5h", 48, "今天 04:44", 2000), win("周", 96, "明天 19:45", 9000)], true), threshold: 20 }),
      /周 已用 96% ⚠/, "the window the chip paints red is marked in the notification too");
    const weekOut = line(fresh([win("5h", 17, "今天 22:19", 2000), win("周", 100, "今天 19:59", 1000)], false));
    assert.match(weekOut, /周 已用 100% ⚠（今天 19:59 重置） · 周额度已用尽，今天 19:59 恢复（登录正常，不用重新登录）$/);
    assert.doesNotMatch(weekOut, /当前不可用/);
    const bothOut = line(fresh([win("5h", 100, "今天 21:58", 1000), win("周", 100, "10/18 周日 11:57", 9000)], false), "codex");
    assert.match(bothOut, /5h、周额度已用尽，10\/18 周日 11:57 恢复/, "back when the LAST exhausted window resets");
    assert.match(line(fresh([win("5h", 40, "今天 21:58", 1000)], false), "codex"), /当前不可用（窗口未用尽，是账号侧限用；登录正常）$/,
      "a vendor-side stop with room left in the windows is not called exhaustion");
    // A login problem stays a login problem, in the reader's own words.
    assert.equal(line({ status: "failed", message: "Claude 登录无效或已过期", snapshot: null }), "额度：读取失败（Claude 登录无效或已过期）");
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("client: the panel says each provider's story once, abnormal rows loudest", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });

  const envelope = {
    providers: [
      { provider: "deepseek", label: "DeepSeek", result: { configured: false, snapshot: null, status: "no-key", low: false, message: "未配置 DeepSeek API Key(设置 → 模型 → DeepSeek)", threshold: 20, refreshMs: 60000 } },
      MM_ROW_OK,
    ],
    refreshMs: 60000,
  };
  const ctx = {
    effect() {},
    get() { return { balance: async () => ({ ok: true, value: envelope }) }; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const __pb = ctx.slots._regs.find((r) => r.definition.id === "provider-balance");
  const Chip = __pb.Component;
  const injected = __pb.definition.inject("s1");
  const store = makeBalanceStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const render = () => { reactStub._resetCursor(); return Chip({ sessionId: "s1", t: translatorFor(api), useStore: store.useStore, actions: store.actions, ...injected }); };

  let tree = render();
  await tick(); await tick(); await tick();
  // Open the panel.
  (function findTrigger(node) {
    if (node == null || Array.isArray(node)) return null;
    if (node.props && node.props["aria-haspopup"] === "dialog") { node.props.onClick(); return node; }
    for (const child of node.children || []) { const hit = findTrigger(child); if (hit) return hit; }
    return null;
  })(tree);
  tree = render();

  const texts = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { texts.push(node); return; }
    (node.children || []).forEach(walk);
  })(tree);
  assert.ok(texts.includes("API 余额"), "panel carries its title");
  assert.ok(texts.some((t) => t.includes("未配置")), "a keyless provider is an honest row, not hidden");
  assert.ok(texts.includes("MiniMax"), "provider labels render verbatim");
  assert.ok(texts.includes("5h"), "per-window labels render as a scannable column");
  assert.ok(texts.includes("周"), "both windows surface their own line");
  const fills = [];
  (function walkFills(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walkFills); return; }
    if (typeof node === "object" && node.props !== null && typeof node.props === "object" &&
        typeof node.props.className === "string" && node.props.className.includes("bp-win-fill")) {
      fills.push(node.props);
    }
    (node.children || []).forEach(walkFills);
  })(tree);
  assert.equal(fills.length, 2, "each quota window renders one remaining-bar");
  assert.deepEqual(fills.map((p) => p.style.width), ["24%", "10%"], "bar length mirrors the window reading");
  assert.deepEqual(
    fills.map((p) => p["data-balance-state"]),
    ["ok", "ok"],
    "healthy windows stay green-tiered",
  );
  disposeReactEffects();

  // Tier colouring per window — yellow in the approach band (60–79), red
  // inside it (≥80 at the default watermark), green below. Colour ONLY:
  // every field stays on screen at every tier (#908).
  const LOW_MM = JSON.parse(JSON.stringify(MM_ROW_OK));
  LOW_MM.result.snapshot.totalBalance = "65";
  LOW_MM.result.snapshot.windows = [{ label: "5h", percent: 65, resetAt: "" }, { label: "周", percent: 88, resetAt: "" }];
  const ctx2 = {
    effect() {},
    get() { return { balance: async () => ({ ok: true, value: { providers: [LOW_MM], refreshMs: 60000 } }) }; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx2);
  for (const fn of ctx2.slots._fns) fn();
  const __pb2 = ctx2.slots._regs.find((r) => r.definition.id === "provider-balance");
  const store2 = makeBalanceStoreStub();
  const render2 = () => { reactStub._resetCursor(); return __pb2.Component({ sessionId: "s2", t: translatorFor(api), useStore: store2.useStore, actions: store2.actions, ...__pb2.definition.inject("s2") }); };
  let tree2 = render2();
  await tick(); await tick(); await tick();
  tree2 = render2();
  const fills2 = [];
  (function walkFills(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walkFills); return; }
    if (typeof node === "object" && node.props !== null && typeof node.props === "object" &&
        typeof node.props.className === "string" && node.props.className.includes("bp-win-fill")) {
      fills2.push(node.props);
    }
    (node.children || []).forEach(walkFills);
  })(tree2);
  assert.deepEqual(fills2.map((p) => p["data-balance-state"]), ["mid", "low"], "the approach band goes yellow, the watermark red — per window");
  const chipValueMid = (function findChipValue3(node) {
    if (node == null || Array.isArray(node)) return null;
    if (typeof node === "object" && node.props && typeof node.props.className === "string" &&
        node.props.className.includes("bchip-v")) return node.props;
    for (const child of node.children || []) { const hit = findChipValue3(child); if (hit) return hit; }
    return null;
  })(tree2);
  assert.equal(chipValueMid["data-used-level"], "low", "the pill tints by the tightest window: 65% headline, 88% week means red");
  disposeReactEffects();

  // #908 regression pin: at the red watermark the row used to collapse to one
  // percentage — the note XOR detail ternary dropped label/pct/bar/reset.
  // Every field must survive; the caption merely rides along.
  const RED_MM = JSON.parse(JSON.stringify(MM_ROW_OK));
  RED_MM.result.low = true;
  RED_MM.result.snapshot.totalBalance = "88";
  RED_MM.result.snapshot.windows = [{ label: "5h", percent: 88, resetAt: "21:00" }, { label: "周", percent: 95, resetAt: "周四 21:00" }];
  const ctx3 = {
    effect() {},
    get() { return { balance: async () => ({ ok: true, value: { providers: [RED_MM], refreshMs: 60000 } }) }; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx3);
  for (const fn of ctx3.slots._fns) fn();
  const __pb3 = ctx3.slots._regs.find((r) => r.definition.id === "provider-balance");
  const store3 = makeBalanceStoreStub();
  const render3 = () => { reactStub._resetCursor(); return __pb3.Component({ sessionId: "s3", t: translatorFor(api), useStore: store3.useStore, actions: store3.actions, ...__pb3.definition.inject("s3") }); };
  let tree3 = render3();
  await tick(); await tick(); await tick();
  // Open the panel so its rows mount into the tree.
  (function openPanel(node) {
    if (node == null || Array.isArray(node)) return;
    if (typeof node === "object" && node.props && node.props["aria-haspopup"] === "dialog") { node.props.onClick(); return; }
    (Array.isArray(node) ? node : node.children || []).forEach(openPanel);
  })(tree3);
  tree3 = render3();
  const redTexts = [];
  const redFills = [];
  const winLines = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { redTexts.push(node); return; }
    if (typeof node === "object" && node.props !== null && typeof node.props === "object") {
      const cn = typeof node.props.className === "string" ? node.props.className : "";
      if (cn.includes("bp-win-fill")) redFills.push(node.props);
      if (cn.includes("bp-win-line")) winLines.push(node.props);
      if (cn.includes("bp-note")) redTexts.push("__NOTE__" + ((node.children || []).join("")));
    }
    (node.children || []).forEach(walk);
  })(tree3);
  assert.deepEqual(redFills.map((p) => p["data-balance-state"]), ["low", "low"], "both windows sit in the red band");
  assert.deepEqual(redFills.map((p) => p.style.width), ["88%", "95%"], "the bars keep their full lengths at the watermark");
  assert.equal(winLines.length, 2, "per-window lines survive the red tier (#908)");
  assert.ok(redTexts.includes("5h") && redTexts.includes("周"), "window labels stay rendered");
  assert.ok(redTexts.some((t) => t.includes("88%")) && redTexts.some((t) => t.includes("95%")), "window percentages stay rendered");
  assert.ok(redTexts.includes("↻ 21:00") && redTexts.includes("↻ 周四 21:00"), "reset stamps stay rendered");
  assert.ok(
    // The window lines above already name the window that crossed the line
    // (label, percent, red bar), so a「周 已用 95%」caption would only repeat them.
    !redTexts.some((t) => t.startsWith("__NOTE__")),
    "no watermark caption repeats the per-window lines",
  );
  const redChip = (function findChip4(node) {
    if (node == null || Array.isArray(node)) return null;
    if (typeof node === "object" && node.props && typeof node.props.className === "string" &&
        node.props.className.includes("bchip-v")) return node.props;
    for (const child of node.children || []) { const hit = findChip4(child); if (hit) return hit; }
    return null;
  })(tree3);
  assert.equal(redChip["data-used-level"], "low", "the headline tints red inside the watermark");
  assert.ok(redTexts.some((t) => t.includes("88%")), "the headline number itself stays");
  assert.ok(redTexts.some((t) => t.includes("周 95%")), "the weekly sub-reading stays on the pill");
  assert.ok(redTexts.includes("↻ 21:00"), "the headline reset stamp stays on the pill");
  disposeReactEffects();
});

test("client: _rowDisplay and _balanceNote project one provider's answer", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  const snap = (total, extra = {}) => ({ isAvailable: true, unit: "money", currency: "CNY", totalBalance: total, grantedBalance: "", toppedUpBalance: "", asOf: AS_OF, note: "", windows: [], ...extra });
  const answer = (over = {}) => ({ configured: true, snapshot: snap("110.00"), status: "fresh", low: false, message: null, threshold: 20, refreshMs: 60000, ...over });
  // Money rows keep the old shape; quota rows read as used percent and
  // surface the second window (周限额) as a muted pill suffix. Colour tiers
  // (level) follow the usage direction: green low, yellow near, red inside —
  // colour only, never at the cost of a field (#908).
  assert.deepEqual(api._rowDisplay(null, translatorFor(api)), { tone: "none", value: "—", sub: null, reset: null, level: null, windows: [], windowsText: "", resets: [], title: "余额加载中" });
  const okRow = api._rowDisplay(answer(), translatorFor(api));
  assert.equal(okRow.tone, "ok");
  assert.equal(okRow.level, null, "money rows have no usage tier — colour stays tonal");
  assert.equal(okRow.sub, null, "money rows carry no window suffix");
  assert.ok(!okRow.title.includes("更新于"), "the fetch timestamp must not repeat in the row");
  assert.match(api._rowDisplay(answer({ snapshot: snap("7.50", { currency: "USD" }) }), translatorFor(api)).value, /^\$7\.5/);
  const pct = api._rowDisplay(answer({ snapshot: snap("76", { unit: "pct", currency: "" }) }), translatorFor(api));
  assert.equal(pct.value, "76%", "quota reads as percent, never money");
  assert.equal(pct.level, "mid", "76% used sits in the warning band (60–79 at the default watermark)");
  assert.equal(pct.sub, null, "a single-window plan has no suffix");
  const dual = api._rowDisplay(answer({
    snapshot: snap("76", {
      unit: "pct", currency: "",
      windows: [{ label: "5h", percent: 76, resetAt: "21:00" }, { label: "周", percent: 90, resetAt: "" }],
    }),
  }), translatorFor(api));
  assert.equal(dual.sub, "· 周 90%", "the weekly limit is the pill's second reading");
  const dualReset = api._rowDisplay(answer({
    snapshot: snap("76", {
      unit: "pct", currency: "",
      windows: [{ label: "5h", percent: 76, resetAt: "21:00" }, { label: "周", percent: 90, resetAt: "周四 21:00" }],
    }),
  }), translatorFor(api));
  assert.equal(dualReset.reset, "21:00", "the headline window's reset rides along for the chip");
  assert.equal(dualReset.sub, "· 周 90% ↻周四 21:00", "the weekly suffix carries its own reset");
  assert.equal(dualReset.level, "low", "the tier follows the tightest window (90%), not the headline (76%)");
  assert.equal(dualReset.windowsText, "5h 76% · 周 90%", "every readable window is one line for the folded row");
  assert.deepEqual(dualReset.resets, ["21:00", "周四 21:00"], "their resets come in the same order");
  // The three visible bands, each read off the tightest window. The watermark
  // stays the long-standing 60% yellow / 80% red; 60 and 75 are both the
  // warning band, which is the rule kcn asked to keep.
  const band = (a, b) => api._rowDisplay(answer({
    snapshot: snap(String(a), { unit: "pct", currency: "", windows: [
      { label: "5h", percent: a, resetAt: "" }, { label: "周", percent: b, resetAt: "" },
    ] }),
  }), translatorFor(api)).level;
  assert.deepEqual([band(40, 59), band(60, 75), band(75, 96)], ["ok", "mid", "low"],
    "green / yellow / red all derive from the same _usedLevel over the tightest window");
  const limited = api._rowDisplay(answer({ snapshot: snap("87", {
    unit: "pct", currency: "",
    note: "5h 已用 87%,今天 21:00 重置 · 当前额度受限",
    windows: [{ label: "5h", percent: 87, resetAt: "今天 21:00" }],
  }) }), translatorFor(api));
  assert.match(limited.title, /当前额度受限/, "Codex's limited state survives window localization");
  assert.match(api._rowDisplay(answer({ snapshot: snap("87", {
    unit: "pct", currency: "", note: "5h 已用 87% · 当前额度受限",
    windows: [{ label: "5h", percent: 87, resetAt: "" }],
  }) }), api.createTranslator(api.dictionaries.en)).title, /当前额度受限/,
  "an English client still receives the host's status instead of losing it");
  const extraUsage = api._rowDisplay(answer({ snapshot: snap("36", {
    unit: "pct", currency: "",
    note: "5h 已用 36% · 周 已用 69% · 附加额度已用 12%",
    windows: [{ label: "5h", percent: 36, resetAt: "" }, { label: "周", percent: 69, resetAt: "" }],
  }) }), translatorFor(api));
  assert.match(extraUsage.title, /附加额度已用 12%/, "Claude's extra-usage state survives window localization");
  assert.deepEqual(
    api._usedLevel(null, 20), "ok",
    "an unreadable reading never lights a warning colour",
  );
  assert.deepEqual([59, 60, 79, 80].map((p) => api._usedLevel(p, 20)), ["ok", "mid", "mid", "low"],
    "tier edges land exactly at 100−2·lowPct and 100−lowPct");
  const primaryGone = api._rowDisplay(answer({
    snapshot: snap("", {
      unit: "pct", currency: "", isAvailable: true,
      windows: [{ label: "会话", percent: null, resetAt: "" }, { label: "本周", percent: 31, resetAt: "" }],
    }),
  }), translatorFor(api));
  assert.equal(primaryGone.value, "31%", "when the headline window is absent the readable one steps up");
  assert.equal(primaryGone.level, "ok", "the stepped-up reading is tiered by its own number");
  assert.equal(api._rowDisplay(answer({ snapshot: snap("9.00", { isAvailable: false }) }), translatorFor(api)).tone, "low");
  // Exhausted quota (kcn 反馈): no caption anywhere — the 100% reading and
  // the reset stamp are the message; money rows keep their sentence.
  const usedUp = api._rowDisplay(answer({
    snapshot: snap("100", {
      unit: "pct", currency: "", isAvailable: false,
      windows: [{ label: "5h", percent: 100, resetAt: "21:00" }, { label: "周", percent: 100, resetAt: "周四 21:00" }],
    }),
    low: true,
  }), translatorFor(api));
  assert.equal(usedUp.value, "100%", "an exhausted window reads as a plain 100% used");
  assert.ok(!usedUp.title.includes("已用尽"), "the exhausted caption is gone from the title");
  assert.equal(usedUp.reset, "21:00", "the reset stamp survives so the user knows when it frees up");
  assert.equal(usedUp.level, "low", "100% used tints red like any other inside-watermark reading");
  assert.equal(api._balanceNote(
    answer({ snapshot: snap("100", { unit: "pct", currency: "", isAvailable: false }), low: true }),
    translatorFor(api)), null, "an exhausted quota row is silent — its bar and reset speak");
  assert.match(api._rowDisplay(answer({ snapshot: snap("9.00", { isAvailable: false }) }), translatorFor(api)).title, /余额不足/, "money rows keep the official-insufficient sentence");
  // Healthy = silence. Every abnormal reading gets exactly one sentence.
  assert.equal(api._balanceNote(null, translatorFor(api)), null);
  assert.equal(api._balanceNote(answer(), translatorFor(api)), null);
  assert.match(api._balanceNote(answer({ snapshot: snap("5.00"), low: true }), translatorFor(api)), /低于阈值 ¥20/);
  assert.match(api._balanceNote(answer({ status: "stale", message: "请求过于频繁" }), translatorFor(api)), /刷新失败.*请求过于频繁/);
  // A stale row says when the reading it still shows was taken, on the folded
  // row and in its title — not only in the open panel (#3119).
  const now = Date.now();
  const staleRow = answer({ status: "stale", message: "fetch failed",
    snapshot: snap("110.00", { asOf: new Date(now - 3 * 3600_000).toISOString() }) });
  const readAt = new Date(now - 3 * 3600_000);
  const clock = String(readAt.getHours()).padStart(2, "0") + ":" + String(readAt.getMinutes()).padStart(2, "0");
  assert.ok(api._balanceNote(staleRow, translatorFor(api), now).includes(clock), "the folded note names the reading's clock");
  assert.ok(api._rowDisplay(staleRow, translatorFor(api), now).title.includes(clock), "so does the hover title");
  assert.match(api._balanceNote({ ...staleRow, message: null }, translatorFor(api), now), /刷新失败,显示 .* 的读数/);
  assert.match(api._balanceNote({ configured: false, snapshot: null, status: "no-key", low: false, message: "未配置 DeepSeek API Key", threshold: 20, refreshMs: 60000 }, translatorFor(api)), /未配置/);
  assert.match(api._balanceNote(answer({ snapshot: null, status: "failed", message: "网络请求失败" }), translatorFor(api)), /网络请求失败/);
  assert.match(api._balanceNote(answer({ snapshot: snap("9.00", { isAvailable: false }) }), translatorFor(api)), /余额不足/);
  assert.match(
    api._balanceNote(answer({ snapshot: snap("88", { unit: "pct", currency: "", isAvailable: true }), low: true }), translatorFor(api)),
    /窗口已使用达 80%/,
    "quota lows speak in used percent (remaining watermark 20 flipped)",
  );
});

test("client: an exhausted quota row shows its 100% bars and resets instead of a caption", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });

  // MiniMax with both windows burned to 100% — the old build said
  // 「该窗口额度已用尽」 and dropped the per-window bars and resets with it.
  const EXHAUSTED_MM = {
    provider: "minimax", label: "MiniMax",
    result: { configured: true, snapshot: { isAvailable: false, unit: "pct", currency: "", totalBalance: "100", grantedBalance: "", toppedUpBalance: "", asOf: AS_OF, note: "5h 窗口已使用 100% · 周窗口已使用 100%", windows: [{ label: "5h", percent: 100, resetAt: "21:00" }, { label: "周", percent: 100, resetAt: "周四 21:00" }] }, status: "fresh", low: true, message: null, threshold: 20, refreshMs: 60000 },
  };
  const ctx = {
    effect() {},
    get() { return { balance: async () => ({ ok: true, value: { providers: [EXHAUSTED_MM], refreshMs: 60000 } }) }; },
    slots: { inject(n, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const __pb = ctx.slots._regs.find((r) => r.definition.id === "provider-balance");
  const store = makeBalanceStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const render = () => { reactStub._resetCursor(); return __pb.Component({ sessionId: "s1", t: translatorFor(api), useStore: store.useStore, actions: store.actions, ...__pb.definition.inject("s1") }); };

  let tree = render();
  await tick(); await tick(); await tick();
  tree = render();

  const texts = [];
  const fills = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { texts.push(node); return; }
    if (typeof node === "object" && node.props !== null && typeof node.props === "object" &&
        typeof node.props.className === "string" && node.props.className.includes("bp-win-fill")) {
      fills.push(node.props);
    }
    (node.children || []).forEach(walk);
  })(tree);
  assert.ok(!texts.some((t) => t.includes("已用尽")), "the exhausted state never speaks as a caption");
  assert.deepEqual(fills.map((p) => p.style.width), ["100%", "100%"], "both burned windows show a full bar");
  assert.ok(texts.includes("↻ 21:00"), "the panel row carries its reset stamp");
  assert.ok(texts.includes("↻ 周四 21:00"), "so does the weekly one");
  assert.ok(texts.some((t) => t.includes("周 100% ↻周四 21:00")), "the pill's weekly suffix carries its own reset");
  disposeReactEffects();
});

test("task queue: live waits, ended tasks and the patrol phase come from the host's own files", async () => {
  const tq = await import(pathToFileURL(path.join(PLUGIN, "lib", "taskqueue.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-queue-"));
  const logDir = path.join(root, "tasks");
  const patrolDir = path.join(root, "patrol");
  fs.mkdirSync(patrolDir, { recursive: true });
  const task = (id, meta, result, log = "") => {
    fs.mkdirSync(path.join(logDir, id), { recursive: true });
    fs.writeFileSync(path.join(logDir, id, "meta.env"), meta);
    fs.writeFileSync(path.join(logDir, id, "result.env"), result);
    if (log) fs.writeFileSync(path.join(logDir, id, "run.log"), log);
  };
  task("holder-20260923-010000", "AGENT=claude\nNAME=holder\nMODEL=claude-opus-5-5\n",
    "STATE=running\nATTEMPTS=2\nSTALLS=1\nWAITING=''\nSLOT=claude-1\nMODEL_USED=claude-opus-5-5\nSTARTED=2026-09-23\\ 01:00:00\n",
    "==== 2026-09-23 01:00:00 holder start ====\n2026-09-23 01:00:00 got run slot 1\n---- 2026-09-23 01:05:00 attempt 2/3 (append) cap=21600s session=s\n     | working\n");
  task("waiter-20260923-011000", "AGENT=claude\nNAME=waiter\n", "STATE=queued\nATTEMPTS=0\nWAITING=lock\nSLOT=''\nSTARTED=2026-09-23\\ 01:10:00\n");
  task("sleeper-20260923-012000", "AGENT=codex\nNAME=sleeper\nCREATED=2026-09-23\\ 01:20:00\n", "STATE=running\nATTEMPTS=1\nWAITING=quota\nSLOT=''\n",
    "---- 2026-09-23 01:30:00 quota; sleeping until 2026-09-23 03:40:00\n");
  // Ended: a WAITING value an interrupted runner left behind is not a wait.
  task("cancelled-20260923-000000", "AGENT=claude\nNAME=cancelled\n",
    "STATE=cancelled\nWAITING=lock\nUPDATED=2026-09-23\\ 02:32:23\n");
  const queuedAt = Math.floor(new Date(2026, 8, 23, 2, 0, 0).getTime() / 1000);
  task("done-20260923-000100", "AGENT=codex\nNAME=done\n", `STATE=ok\nOUTCOME=DONE\nQUEUED_AT=${queuedAt}\nUPDATED=2026-09-23\\ 02:47:16\n`,
    "2026-09-23 02:04:00 got run slot codex-1\nfinal | an earlier attempt\n---- 2026-09-23 02:47:16 attempt 2 (task) rc=0 kind=ok\n     | x\n" +
    "final | - merged: PR #1767\nfinal | \nfinal | STATUS: DONE\nquota | 5h 48%\n");
  task("patrol-render-20260923-000200", "AGENT=opencode\nNAME=patrol-render\n", "STATE=cancelled\nUPDATED=2026-09-23\\ 02:40:41\n");
  for (let i = 0; i < 20; i += 1) {
    task(`older-${i}`, "AGENT=claude\n", "STATE=ok\nUPDATED=2026-09-22\\ 02:00:00\n");
  }
  task("abandoned-live-state", "AGENT=codex\n", "STATE=running\nUPDATED=2026-09-24\\ 02:00:00\n");
  // Latest completion restored with an old mtime; old completions touched later.
  fs.utimesSync(path.join(logDir, "done-20260923-000100", "result.env"), 1, 1);
  const limits = path.join(root, "limits.env");
  fs.writeFileSync(limits, "# per agent\nMAX_RUNNING_CLAUDE=1\nMAX_RUNNING_CODEX=1\nMAX_RUNNING_OPENCODE=1\nMAX_RUNNING=3\n");
  fs.writeFileSync(path.join(patrolDir, "rounds.tsv"),
    "2026-09-23 02:30:07\tR137\tlogic\tpatrol-logic-x\tpreempted:cancelled\t3778s\n2026-09-23 03:55:00\tR139\tautomation\tpatrol-automation-x\tpreempted:cancelled\t4090s\n");
  const deps = (log, service = "active") => ({
    activeTaskIds: async () => ["holder-20260923-010000", "waiter-20260923-011000", "sleeper-20260923-012000", "gone-20260923-000000"],
    patrolService: async () => service,
    patrolLog: async () => log,
  });
  const config = { logDir, limitsPath: limits, patrolDir, recent: 5 };
  const r = await tq.createTaskQueueService(config, deps(["2026-09-23 03:55:00 next round in 300s"])).get(true);
  assert.equal(r.available, true);
  assert.equal(r.status, "fresh");
  assert.equal(r.maxRunning, 3, "the slot count comes from limits.env, not a constant");
  assert.deepEqual(r.slotLimits, [{ agent: "claude", max: 1 }, { agent: "codex", max: 1 }, { agent: "opencode", max: 1 }],
    "each agent's own slots, in file order");
  assert.equal(r.running, 1);
  assert.deepEqual(r.active.map((t) => [t.name, t.waiting, t.slot]),
    [["holder", "", "claude-1"], ["waiter", "lock", ""], ["sleeper", "quota", ""]],
    "live tasks oldest first; an active unit without a task dir is skipped");
  assert.equal(r.active[0].model, "claude-opus-5-5");
  assert.equal(r.active[0].attempts, 2);
  assert.deepEqual(r.active.map((t) => t.stalls), [1, 0, 0], "STALLS from result.env, 0 when absent");
  assert.equal(r.active[0].startedAtMs, new Date(2026, 8, 23, 1, 0, 0).getTime(), "%q-escaped stamps parse");
  assert.equal(r.active[2].wakeAtMs, new Date(2026, 8, 23, 3, 40, 0).getTime(), "quota wake time from the run log");
  assert.equal(r.active[0].lastEvent, "attempt 2/3 (append) cap=21600s session=s", "a live task's latest stamped runner event");
  assert.equal(r.active[0].lastEventAtMs, new Date(2026, 8, 23, 1, 5, 0).getTime());
  assert.equal(r.active[0].summary, "", "no closing report while live");
  assert.equal(r.recent[0].summary, "- merged: PR #1767",
    "the last attempt's final lines only; blanks and the STATUS line dropped");
  assert.equal(r.recent[0].lastEvent, "", "an ended task has no 'latest event'");
  assert.equal(r.recent[0].waitMs, 4 * 60000, "wait is first slot acquisition minus QUEUED_AT");
  assert.equal(r.recent[1].waitMs, null, "an older runner log cannot yield a trustworthy wait duration");
  assert.equal(r.recent[1].summary, "", "no run log, no report");
  assert.deepEqual(r.recent.map((t) => [t.name, t.state, t.waiting]), [["done", "ok", ""], ["cancelled", "cancelled", ""], ["older-0", "ok", ""], ["older-1", "ok", ""], ["older-10", "ok", ""]],
    "ended tasks newest first by UPDATED, patrol rounds excluded, stale WAITING dropped");
  assert.equal(r.patrol.phase, "waiting");
  assert.equal(r.patrol.untilMs, new Date(2026, 8, 23, 4, 0, 0).getTime(), "next round due = log stamp + gap");
  assert.deepEqual(r.patrol.rounds.map((x) => [x.round, x.result, x.seconds]),
    [["R139", "preempted:cancelled", 4090], ["R137", "preempted:cancelled", 3778]]);

  fs.writeFileSync(path.join(patrolDir, "rounds.tsv"), Array.from({ length: 10 }, (_, i) =>
    `2026-09-23 03:55:00\tR${i}\tlogic\tpatrol-${i}\tok\t20s`).join("\n") + "\n");
  const longHistory = await tq.createTaskQueueService(config, deps([])).get(true);
  assert.deepEqual(longHistory.patrol.rounds.map(x => x.round), ["R9", "R8", "R7", "R6", "R5", "R4", "R3", "R2"],
    "real host output reaches the five-round disclosure threshold with a bounded history");

  const phase = (log, service, round = "", alive = false) => tq.patrolPhase(service, round, alive, log).phase;
  assert.equal(phase(["2026-09-23 03:54:58 preempting patrol-a: x is waiting for its agent lock"], "active", "patrol-a", true), "yielding",
    "a round being cancelled for a user task reads as giving way");
  // A line the supervisor really writes (others_need_slot admission), not an invented one (#2071).
  assert.equal(phase(["2026-09-23 02:45:42 waiting: the opencode run slot is busy"], "active"), "yielding");
  assert.equal(phase(["2026-09-23 04:00:08 round R140 (recent) dispatched as patrol-b"], "active", "patrol-b", true), "running");
  assert.equal(phase(["2026-09-23 04:00:08 round R140 (recent) dispatched as patrol-b"], "inactive", "patrol-b", true), "stopped");
  // #2265: an unanswered systemctl probe is unknown, not a stopped patrol.
  assert.equal(phase(["2026-09-23 04:00:08 round R140 (recent) dispatched as patrol-b"], "", "patrol-b", true), "unknown");

  assert.equal(tq.unquoteShell("''"), "");
  assert.equal(tq.unquoteShell("$'a\\nb'"), "a\nb");
  assert.equal(tq.unquoteShell("2026-09-24\\ 02:38:43"), "2026-09-24 02:38:43");

  // A failed forced refresh stays stale for the polls inside the TTL (#1879),
  // the balance services' #1546: `fetchedAt` dates the last success only.
  let broken = false;
  const flaky = { ...deps([]), activeTaskIds: async () => { if (broken) throw new Error("systemctl down"); return []; } };
  const service = tq.createTaskQueueService(config, flaky);
  assert.equal((await service.get(true)).status, "fresh");
  broken = true;
  assert.equal((await service.get(true)).status, "stale");
  const polled = await service.get(false);
  assert.equal(polled.status, "stale", "a poll right after a failed refresh must not read as cached");
  assert.match(polled.message, /systemctl down/);
  broken = false;
  assert.equal((await service.get(true)).status, "fresh");
  assert.equal((await service.get(false)).status, "cached", "a successful refresh clears the stale mark");

  const none = await tq.createTaskQueueService({ ...config, logDir: path.join(root, "absent") }, deps([])).get(false);
  assert.equal(none.available, false, "no dispatcher on this host: the chip stays away");
  assert.deepEqual(none.active, []);
  fs.rmSync(root, { recursive: true, force: true });
});

// The detail layer's order (client.ts DETAIL_SECTIONS / DETAIL_FIELDS): the sections drawn are a
// run of the table's list for that kind of task, and each section's fields a run of its fields.
function assertDetailOrder(api, layer, kind) {
  const walk = (node, pred, out = []) => {
    if (node == null) return out;
    if (Array.isArray(node)) { node.forEach((n) => walk(n, pred, out)); return out; }
    if (typeof node !== "object") return out;
    if (pred(node.props || {})) out.push(node);
    (node.children || []).forEach((n) => walk(n, pred, out));
    return out;
  };
  const sections = walk(layer, (p) => p["data-tq-section"] !== undefined);
  const ids = sections.map((n) => n.props["data-tq-section"]);
  const order = api.DETAIL_SECTIONS[kind];
  assert.equal(ids[0], "status", "the hero comes first");
  assert.deepEqual(ids, order.filter((id) => ids.includes(id)), `${kind}: sections in DETAIL_SECTIONS order (${ids})`);
  for (const section of sections) {
    const id = section.props["data-tq-section"];
    const fields = walk(section, (p) => p["data-tq-field"] !== undefined).map((n) => n.props["data-tq-field"]);
    const table = api.DETAIL_FIELDS[id] ?? [];
    assert.ok(fields.every((f) => table.includes(f)), `${id}: only its own fields (${fields})`);
    assert.deepEqual(fields, [...fields].sort((a, b) => table.indexOf(a) - table.indexOf(b)), `${id}: fields in DETAIL_FIELDS order`);
    if (api.DETAIL_FOLDED.includes(id)) {
      assert.ok(walk(section, (p) => p["data-tq-fold"] === id).length === 1, `${id} is folded`);
    }
  }
}

// Where each control of a detail layer sits: its section, and its field when it is beside one.
function actionHomes(layer) {
  const out = {};
  (function walk(node, section, field) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach((n) => walk(n, section, field)); return; }
    if (typeof node !== "object") return;
    const p = node.props || {};
    const s = p["data-tq-section"] ?? section;
    const f = p["data-tq-field"] ?? (p["data-tq-section"] !== undefined ? undefined : field);
    if (p["data-tq-action"] !== undefined && p["data-tq-action"] !== "dismiss-confirm") {
      out[p["data-tq-action"]] = { home: f === undefined ? s : `${s}.${f}`, kind: p["data-tq-kind"] };
    }
    (node.children || []).forEach((n) => walk(n, s, f));
  })(layer, undefined, undefined);
  return out;
}

test("patrol: every give-way reason the supervisor can write gets its true label (#2071)", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const repo = path.join(__dirname, "..");
  const patrol = fs.readFileSync(path.join(repo, "ops/host/patrol.sh"), "utf8");
  const pressure = fs.readFileSync(path.join(repo, "ops/host/agent-dispatch/resource-pressure.sh"), "utf8");
  const REASONS = [
    [patrol, '"$id is waiting for an $ROUND_AGENT run slot"', "t-1 is waiting for an opencode run slot", "manual", "t-1"],
    [patrol, '"$id is waiting for its agent lock"', "t-2 is waiting for its agent lock", "manual", "t-2"],
    [patrol, '"$id is waiting for the opencode lock"', "t-3 is waiting for the opencode lock", "manual", "t-3"],
    [patrol, '"the $ROUND_AGENT run slot is busy"', "the opencode run slot is busy", "slot", ""],
    [patrol, '"$id is waiting for an $ROUND_AGENT run slot and all $AGENT_SLOTS are busy"', "t-4 is waiting for an opencode run slot and all 1 are busy", "manual", "t-4"],
    [patrol, `"$id is queued behind the round's opencode lock"`, "t-5 is queued behind the round's opencode lock", "manual", "t-5"],
    [pressure, "'memory telemetry unavailable; defer patrol'", "memory telemetry unavailable; defer patrol", "memoryUnread", ""],
    [pressure, '"memory headroom low: ${available} KiB available (< $PATROL_MIN_AVAILABLE_KB)"', "memory headroom low: 131072 KiB available (< 196608)", "memory", ""],
    [pressure, '"memory pressure: full avg60=$full (>= $PATROL_MAX_MEMORY_FULL_AVG60)"', "memory pressure: full avg60=12.3 (>= 10)", "memory", ""],
  ];
  for (const [src, template] of REASONS) assert.ok(src.includes(template), "the supervisor no longer writes: " + template);
  for (const shape of ['log "waiting: $reason"', 'log "preempting $rid${yield_at:+ after a $(( $(now) - yield_at ))s wrap-up grace}: $reason"',
    'log "asking $rid to wrap up within ${PREEMPT_GRACE}s: $demand"']) assert.ok(patrol.includes(shape), "log shape changed: " + shape);
  for (const [, , reason, kind, task] of REASONS) {
    for (const line of [`waiting: ${reason}`, `preempting patrol-a-20260928-010000: ${reason}`,
      `preempting patrol-a-20260928-010000 after a 42s wrap-up grace: ${reason}`]) {
      assert.deepEqual(api._patrolReason(line), { kind, task, wrapUp: false }, line);
    }
    assert.deepEqual(api._patrolReason(`asking patrol-a-20260928-010000 to wrap up within 300s: ${reason}`), { kind, task, wrapUp: true });
  }
  // The sentence #2066 was accepted on is not a reason anyone writes: it gets no invented label.
  assert.equal(api._patrolReason("waiting: all 2 run slots are busy").kind, "other");
  // Each kind reads differently, in both languages.
  for (const lang of ["zh", "en"]) {
    const d = api.dictionaries[lang];
    const labels = ["giveWay", "waitSlot", "memory", "memoryUnread", "otherReason"].map((k) => d["queue.patrol." + k]);
    assert.equal(new Set(labels).size, labels.length, lang + ": one label per reason kind");
  }
});

test("client: a task backing off to retry is counted on the queue headline, like one waiting on quota", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const now = Date.now();
  const live = (id, waiting) => ({ id, name: id, agent: "claude", model: "m", state: "queued", waiting, slot: "",
    attempts: 1, outcome: "", startedAtMs: now - 60000, updatedAtMs: now, wakeAtMs: now + 5 * 60000, patrol: false });
  const result = {
    available: true, status: "fresh", message: null, asOf: AS_OF, refreshMs: 15000, maxRunning: 2, running: 0,
    active: [live("retry-task", "retry"), live("quota-task", "quota")],
    recent: [],
    patrol: { service: "active", phase: "running", round: "", detail: "", untilMs: null, rounds: [] },
  };
  const zh = api._queueHeadline(result, translatorFor(api), now);
  assert.match(zh.sub, /等额度 1/);
  assert.match(zh.sub, /等重试 1/, `retry wait missing from the headline: ${zh.sub}`);
  assert.match(zh.title, /等重试 1/);
  assert.match(api._queueHeadline(result, translatorFor(api, "en"), now).sub, /1 waiting to retry/);

  // Patrol admission waiting for memory is its own reason, not a queue behind a task.
  const memory = api._queueHeadline({ ...result, active: [{ ...live("patrol-x", "memory"), agent: "opencode" }] }, translatorFor(api), now);
  assert.match(memory.sub, /等内存 1/);
  assert.doesNotMatch(memory.sub, /排队/);
  assert.equal(memory.busy, false);
  // A host older than slotLimits: lanes from the held slots alone, no maximum, nothing broken.
  const old = api._queueHeadline({ ...result, running: 2,
    active: [{ ...live("a", ""), slot: "claude-1" }, { ...live("b", ""), agent: "codex", slot: "codex-1" }] }, translatorFor(api), now);
  assert.match(old.title, /在跑 2 · claude 1 · codex 1/);
});

test("task queue host: the ops entry orders each agent's queue and is the only write door", async () => {
  const tq = await import(pathToFileURL(path.join(PLUGIN, "lib", "taskqueue.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-queue-ops-"));
  const logDir = path.join(root, "tasks");
  const task = (id, meta, result, override = "") => {
    fs.mkdirSync(path.join(logDir, id), { recursive: true });
    fs.writeFileSync(path.join(logDir, id, "meta.env"), meta);
    fs.writeFileSync(path.join(logDir, id, "result.env"), result);
    if (override) fs.writeFileSync(path.join(logDir, id, "override.env"), override);
  };
  task("old-run", "AGENT=claude\nNAME=old-run\nMODEL=claude-opus-5-5\n", "STATE=running\nSLOT=claude-1\nATTEMPTS=1\nSTARTED=2026-09-26\\ 15:06:36\n");
  task("new-wait", "AGENT=claude\nNAME=new-wait\nMODEL=claude-opus-5-5\nEFFORT=high\nNOTIFY=weixin,telegram\n",
    "STATE=running\nWAITING=lock\nATTEMPTS=0\nRUNNER_API=2\nQUEUED_AT=1790422408\nSTARTED=2026-09-26\\ 19:33:28\n",
    "MODEL=claude-haiku-4-5-20251001\nPRIORITY=2\n");
  task("budget-wait", "AGENT=claude\nNAME=budget-wait\nMAX_ATTEMPTS=3\nQUOTA_RESUMES=3\nDEADLINE_EPOCH=1791000000\n",
    "STATE=running\nWAITING=quota\nRUNNER_API=3\nMAX_ATTEMPTS=3\nQUOTA_RESUMES=3\nDEADLINE_EPOCH=1791000000\n",
    "MAX_ATTEMPTS=4\nQUOTA_RESUMES=5\nDEADLINE_EPOCH=1791007200\n");
  task("done", "AGENT=codex\nNAME=done\nNOTIFY=weixin,telegram\n",
    "STATE=ok\nOUTCOME=DONE\nNOTIFIED=telegram\nNOTIFY_FAILED=weixin\nNOTIFY_AT=2026-09-26\\ 20:00:00\nRUNNER_API=2\nUPDATED=2026-09-26\\ 20:00:00\n");
  const opsPath = path.join(root, "task_queue_ops.py");
  const repoOps = path.join(root, "repo_task_queue_ops.py");
  fs.writeFileSync(opsPath, "installed\n");
  fs.writeFileSync(repoOps, "installed\n");
  const list = {
    ok: true, ops_version: tq.fileVersion(opsPath), api: 2, fair_wait_sec: 14400, runner: { api: 2 },
    agents: {
      claude: { holder: { held: true, id: "old-run", note: "" }, quota: null,
        queue: [{ id: "old-wait", position: 1, priority: 0, protected: true, queued_at: 1790410000 },
          { id: "new-wait", position: 2, priority: 2, protected: false, queued_at: 1790422408 }] },
      codex: { holder: { held: false, id: null }, queue: [], quota: { until: 1790430000, by: "x" } },
    },
  };
  const calls = [];
  const runOps = async (_path, args) => {
    calls.push(args);
    if (args[0] === "list") return { code: 0, stdout: JSON.stringify(list), stderr: "" };
    if (args.includes("cancel")) return { code: 0, stdout: JSON.stringify({ ok: true, was: "queued", state: "cancelled", message: "cancelled before it started" }), stderr: "" };
    return { code: 3, stdout: JSON.stringify({ ok: false, code: 3, error: "refused: no RUNNER_API 2" }), stderr: "" };
  };
  const deps = { activeTaskIds: async () => ["old-run", "new-wait", "budget-wait"], patrolService: async () => "active", patrolLog: async () => [], runOps };
  const config = { logDir, limitsPath: path.join(root, "limits.env"), patrolDir: path.join(root, "patrol"), opsPath, repoOpsPath: repoOps };
  const r = await tq.createTaskQueueService(config, deps).get(true);
  const budget = r.active.find((t) => t.id === "budget-wait");
  assert.deepEqual([budget.maxAttempts, budget.quotaResumes, budget.deadlineAtMs], [4, 5, 1791007200000]);
  fs.writeFileSync(path.join(logDir, "budget-wait", "override.env"), "MAX_ATTEMPTS=\nQUOTA_RESUMES=\nDEADLINE_EPOCH=\n");
  const resetBudget = (await tq.createTaskQueueService(config, deps).get(true)).active.find((t) => t.id === "budget-wait");
  assert.deepEqual([resetBudget.maxAttempts, resetBudget.quotaResumes, resetBudget.deadlineAtMs], [3, 3, 1791000000000]);
  const wait = r.active.find((t) => t.id === "new-wait");
  assert.equal(wait.position, 2, "the queue place comes from the ops entry");
  assert.equal(wait.priority, 2);
  assert.equal(wait.queuedAtMs, 1790422408000, "QUEUED_AT, not the directory's mtime");
  assert.equal(wait.modelRequested, "claude-haiku-4-5-20251001", "the override is what the next attempt uses");
  assert.equal(wait.effortRequested, "high");
  assert.deepEqual(wait.notify, ["weixin", "telegram"]);
  assert.equal(wait.runnerApi, 2);
  assert.equal(r.active.find((t) => t.id === "old-run").runnerApi, 1, "no RUNNER_API: said so, never a queue place");
  assert.equal(r.active.find((t) => t.id === "old-run").position, null);
  const done = r.recent.find((t) => t.id === "done");
  assert.deepEqual([done.notified, done.notifyFailed], [["telegram"], ["weixin"]], "receipts from result.env, not the log");
  const claude = r.queues.find((q) => q.agent === "claude");
  assert.deepEqual([claude.holder, claude.order], ["old-run", ["old-wait", "new-wait"]]);
  assert.equal(r.queues.find((q) => q.agent === "codex").quotaUntilMs, 1790430000000);
  assert.deepEqual([r.ops.available, r.ops.version === r.ops.repoVersion], [true, true]);
  fs.writeFileSync(repoOps, "merged, not installed\n");
  const skewed = await tq.createTaskQueueService(config, deps).get(true);
  assert.notEqual(skewed.ops.version, skewed.ops.repoVersion, "a merged-but-not-installed entry shows as skew");

  // Writes: validated before any process runs; a double click is one run; a write invalidates the read.
  let invalidated = 0;
  const act = tq.createQueueActionRunner({ opsPath }, { runOps }, () => { invalidated += 1 });
  calls.length = 0;
  for (const [action, id, arg] of [["rm", "x", ""], ["cancel", "../etc", ""], ["priority", "new-wait", "first"], ["model", "new-wait", "a b|high"]]) {
    const refused = await act(action, id, arg);
    assert.equal(refused.ok, false);
    assert.equal(refused.code, 2, `${action} ${id} ${arg}`);
  }
  assert.equal(calls.length, 0, "nothing invalid reaches the ops entry");
  const [one, two] = await Promise.all([act("cancel", "new-wait", ""), act("cancel", "new-wait", "")]);
  assert.equal(one, two, "a double click shares one run");
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], ["--source", "ui", "cancel", "new-wait"]);
  assert.equal((await act("cancel", "new-wait", "")).ok, true);
  assert.equal(calls.length, 1, "a repeat inside the window returns the first answer");
  assert.equal(invalidated, 1);
  const refused = await act("priority", "old-run", "top");
  assert.deepEqual([refused.ok, refused.code, refused.message], [false, 3, "refused: no RUNNER_API 2"], "a refusal is in-band, with the entry's words");
  const wrap = tq.opsArgsFor("wrapup", "new-wait", "");
  assert.deepEqual(wrap.slice(0, 4), ["append", "new-wait", "--queue", "--text"], "wrap-up is a queued append, never an interrupt");
  const missing = await tq.createQueueActionRunner({ opsPath: path.join(root, "absent.py") }, { runOps })("cancel", "new-wait", "");
  assert.match(missing.message, /not installed/);
  fs.rmSync(root, { recursive: true, force: true });
});

test("task queue host: stats rereads the frozen summary only, never sessions; unknown is not 0", async () => {
  const tq = await import(pathToFileURL(path.join(PLUGIN, "lib/taskqueue.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-stats-"));
  const opsPath = path.join(root, "task_queue_ops.py");
  fs.writeFileSync(opsPath, "stub\n");
  const raw = {
    ok: true, since: "2026-10-05", patrol_included: false,
    agents: {
      claude: { tasks: 3, live: 1, states: { ok: 2, running: 1 }, outcomes: { DONE: 2 },
        tokens_total: 1000, tokens_unknown: 0, cost_usd_estimate: 1.5, cost_unpriced: 0, cost_free: 0 },
      codex: { tasks: 2, live: 0, states: { ok: 1, failed: 1 }, outcomes: { DONE: 1, "-": 1 },
        tokens_total: 500, tokens_unknown: 1, cost_usd_estimate: 0, cost_unpriced: 1, cost_free: 0 },
    },
    daily: {
      "2026-10-05": {
        claude: { tasks: 2, tokens: 1000, unknown: 0 },
        codex: { tasks: 1, tokens: 500, unknown: 1 },
      },
    },
  };
  const calls = [];
  const runOps = async (_path, args) => { calls.push(args); return { code: 0, stdout: JSON.stringify(raw), stderr: "" }; };
  const config = { logDir: root, limitsPath: path.join(root, "limits.env"), patrolDir: path.join(root, "patrol"), opsPath, repoOpsPath: "" };
  try {
    const stats = await tq.readStats(config, { runOps }, { days: 7 });
    assert.equal(stats.available, true);
    assert.equal(stats.days, 7);
    assert.equal(stats.since, raw.since, "the entry's own window is echoed");
    assert.deepEqual(calls[0], ["summary", "--since", tq.sinceDay(7)]);
    assert.deepEqual(stats.agents.map((a) => [a.agent, a.tasks, a.live, a.tokensTotal, a.tokensUnknown]),
      [["claude", 3, 1, 1000, 0], ["codex", 2, 0, 500, 1]]);
    assert.deepEqual(stats.agents[1].outcomes, [{ name: "DONE", count: 1 }, { name: "-", count: 1 }]);
    assert.equal(stats.agents[1].costUnpriced, 1, "an unpriced task is counted apart, not as $0");
    assert.deepEqual(stats.daily, raw.daily, "the daily rows come through the same read");
    assert.equal(stats.daily["2026-10-05"].claude.tokens, 1000);
    const noDaily = await tq.readStats(config, { runOps: async () => ({ code: 0, stdout: JSON.stringify({ ...raw, daily: undefined }), stderr: "" }) }, { days: 7 });
    assert.equal(noDaily.available, true);
    assert.equal(noDaily.daily, undefined, "an older ops entry without daily still has a usable stats card");
    const badDaily = await tq.readStats(config, { runOps: async () => ({ code: 0, stdout: JSON.stringify({ ...raw, daily: { "2026-10-05": { claude: { tasks: "2" } } } }), stderr: "" }) }, { days: 7 });
    assert.equal(badDaily.available, false);
    assert.match(badDaily.error, /unreadable daily row/);
    await tq.readStats(config, { runOps }, { days: 30, patrol: true });
    assert.deepEqual(calls[1], ["summary", "--since", tq.sinceDay(30), "--all"]);
    await tq.readStats(config, { runOps }, { since: "2026-09-01" });
    assert.deepEqual(calls[2], ["summary", "--since", "2026-09-01"]);
    await tq.readStats(config, { runOps }, {});
    assert.deepEqual(calls[3], ["summary"], "no window: every retained task");
    // A malformed row makes the whole answer unavailable; it never becomes zeroes.
    const unreadable = await tq.readStats(config, {
      runOps: async () => ({ code: 0, stdout: JSON.stringify({ ok: true, agents: { claude: { tasks: "3" } } }), stderr: "" }),
    }, { days: 7 });
    assert.equal(unreadable.available, false);
    assert.match(unreadable.error, /unreadable claude row/);
    assert.deepEqual(unreadable.agents, []);
    const missing = await tq.readStats({ ...config, opsPath: path.join(root, "absent.py") }, { runOps }, { days: 7 });
    assert.equal(missing.available, false);
    assert.match(missing.error, /not installed/);
    const service = tq.createTaskQueueService({ logDir: root, limitsPath: path.join(root, "limits.env"), patrolDir: path.join(root, "patrol"), opsPath }, {
      activeTaskIds: async () => [], patrolService: async () => "", patrolLog: async () => [], runOps,
    });
    const viaService = await service.stats({ days: 7 });
    assert.equal(viaService.available, true);
    assert.deepEqual(calls.at(-1), ["summary", "--since", tq.sinceDay(7)]);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("dispatch stats: a table for /dispatch-stats, a bar fallback, and the wire's own snapshot", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const chat = await import(pathToFileURL(path.join(PLUGIN, "lib", "chat.js")).href);
  const t = translatorFor(api);
  const stats = {
    available: true, error: "", since: "2026-10-11", days: 7, patrolIncluded: false, asOf: AS_OF,
    agents: [
      { agent: "claude", tasks: 56, live: 1,
        states: [{ name: "ok", count: 42 }, { name: "partial", count: 9 }, { name: "failed", count: 1 },
          { name: "cancelled", count: 3 }, { name: "running", count: 1 }],
        outcomes: [{ name: "DONE", count: 42 }, { name: "PARTIAL", count: 9 }],
        tokensTotal: 625213302, tokensUnknown: 1, costUsdEstimate: 261.64, costUnpriced: 1, costFree: 0 },
      { agent: "codex", tasks: 35, live: 0,
        states: [{ name: "ok", count: 23 }, { name: "partial", count: 7 }, { name: "cancelled", count: 3 },
          { name: "quota", count: 1 }, { name: "blocked", count: 1 }],
        outcomes: [{ name: "DONE", count: 23 }, { name: "PARTIAL", count: 5 }, { name: "BLOCKED", count: 2 }],
        tokensTotal: 161534676, tokensUnknown: 8, costUsdEstimate: 236.16, costUnpriced: 8, costFree: 0 },
      // A zero-task agent is not a row: it would read as a reading nobody made.
      { agent: "opencode", tasks: 0, live: 0, states: [], outcomes: [],
        tokensTotal: 0, tokensUnknown: 0, costUsdEstimate: 0, costUnpriced: 0, costFree: 0 },
    ],
    daily: {
      "2026-10-11": { claude: { tasks: 2, tokens: 1000, unknown: 0 }, codex: { tasks: 1, tokens: 500, unknown: 1 } },
    },
  };
  const reply = chat.dispatchStatsText(stats, t);
  assert.ok(reply.startsWith("# 派发统计 · 近 7 天 · 91 项（进行中 1）"), "the title carries the window, total and live count");
  assert.match(reply, /\| Agent \| 完成\/已结束 \| 部分 \| 未完成 \| token · API 估价 \|/);
  assert.match(reply, /\|---\|---\|---\|---\|---\|/);
  assert.match(reply, /\| Claude Code \| 42\/55 \| 9 \| 4 \| 625\.2M · \$261\.64 \|/);
  assert.match(reply, /\| Codex \| 23\/35 \| 5 \| 7 \| 161\.5M · \$236\.16 \|/);
  assert.match(reply, /\| 合计 \| 65\/90 \| 14 \| 11 \| 786\.7M · \$497\.80 \|/);
  assert.doesNotMatch(reply, /opencode/i, "an agent with no task is not a zero row");
  assert.doesNotMatch(reply, /token 未知|已结束任务冻结值|巡检不计/, "no trailing descriptive tail");
  // The bar fallback: no table, one token-share bar per agent, still one caveat line.
  const plain = chat.dispatchStatsText(stats, t, true);
  assert.match(plain, /^# 派发统计 · 近 7 天 · 91 项（进行中 1）/m);
  assert.match(plain, /token 786\.7M · API \$497\.80/);
  assert.match(plain, /Claude Code {2}▓{10} {2}625\.2M · \$261\.64/);
  assert.match(plain, /已结束 55 · 完成 42 · 部分 9 · 未完成 4/);
  assert.doesNotMatch(plain, /\| Agent \|/);
  assert.doesNotMatch(plain, /token 未知|API 估价非订阅额度/, "the plain fallback has no trailing prose either");
  // A label cannot add a table column or smuggle a backslash through a cell.
  const odd = { ...stats, agents: [{ ...stats.agents[0], agent: 'a|b\\c', tasks: 1, live: 0,
    states: [{ name: 'ok', count: 1 }], outcomes: [{ name: 'DONE', count: 1 }], tokensTotal: 0, tokensUnknown: 0,
    costUsdEstimate: 0, costUnpriced: 0, costFree: 0 }] };
  const guarded = chat.dispatchStatsText(odd, t);
  assert.ok(guarded.includes('a\\|b\\\\c'), `the cell escapes pipe and backslash: ${guarded}`);
  assert.doesNotMatch(guarded, /\| a\|b/);
  // Empty and failed reads are said, not drawn as zeroes.
  assert.match(chat.dispatchStatsText({ ...stats, agents: [] }, t), /没有已结束的任务/);
  const failed = chat.dispatchStatsText({ ...stats, available: false, error: "ops entry not installed" }, t);
  assert.match(failed, /近 7 天 · 读取失败/);
  assert.match(failed, /ops entry not installed/);
  // Arguments: a rolling window, a since-date, all-time, patrol, and the plain fallback.
  assert.deepEqual(chat.parseStatsArgs(""), { query: { days: 7, since: null, patrol: false }, plain: false });
  assert.deepEqual(chat.parseStatsArgs("30d patrol"), { query: { days: 30, since: null, patrol: true }, plain: false });
  assert.deepEqual(chat.parseStatsArgs("all"), { query: { days: null, since: null, patrol: false }, plain: false });
  assert.deepEqual(chat.parseStatsArgs("2026-10-01"), { query: { days: null, since: "2026-10-01", patrol: false }, plain: false });
  assert.deepEqual(chat.parseStatsArgs("plain"), { query: { days: 7, since: null, patrol: false }, plain: true });
  assert.equal(chat.parseStatsArgs("yesterday"), null);
  assert.equal(chat.parseStatsArgs("2026-02-30"), null, "a date that does not exist is not a window");
  assert.equal(chat.parseStatsArgs("366d"), null, "the rolling window is capped at a year");
  // The lazy RPC carries the whole snapshot instead of stripping it (build.mjs' hand-carried schema).
  const { TYPERT_REMOTE } = await import(pathToFileURL(path.join(PLUGIN, "lib", "typert.remote-client.js")).href);
  const schema = TYPERT_REMOTE.descriptors.find((d) => d.method === "taskStats").result.create();
  assert.deepEqual(schema.parse(stats), stats, "the taskStats codec carries the stats shape");
});

test("openclaw /dispatch-stats: the command answers from the ops entry, passes its window, refuses the rest", async () => {
  const chat = await import(pathToFileURL(path.join(PLUGIN, "lib", "chat.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-stats-cmd-"));
  const opsPath = path.join(root, "task_queue_ops.py");
  const argvFile = path.join(root, "argv.txt");
  fs.writeFileSync(opsPath, `import json, os, sys
open(os.path.join(os.path.dirname(__file__), "argv.txt"), "a").write(" ".join(sys.argv[1:]) + "\\n")
since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else None
print(json.dumps({"ok": True, "since": since, "patrol_included": False, "agents": {
  "claude": {"tasks": 2, "live": 0, "states": {"ok": 2}, "outcomes": {"DONE": 2},
             "tokens_total": 1200000, "tokens_unknown": 0, "cost_usd_estimate": 0.42,
             "cost_unpriced": 0, "cost_free": 0}}}))
`);
  const commands = {};
  chat.default({
    pluginConfig: { dispatchLogDir: root, dispatchLimitsPath: path.join(root, "limits.env"),
      patrolStateDir: path.join(root, "patrol"), taskQueueOpsPath: opsPath },
    registerCommand: (command) => { commands[command.name] = command; },
  });
  const run = (args) => commands["dispatch-stats"].handler({ args, config: { agents: { defaults: { workspace: root } } } });
  try {
    assert.ok(commands["dispatch-list"], "the queue command is still registered");
    assert.equal(commands["dispatch-stats"].acceptsArgs, true, "the window is an argument");
    const reply = await run("");
    assert.match(reply.text, /^# 派发统计 · 近 7 天 · 2 项/m);
    assert.match(reply.text, /\| Agent \| 完成\/已结束 \| 部分 \| 未完成 \| token · API 估价 \|/);
    assert.match(reply.text, /\| Claude Code \| 2\/2 \| 0 \| 0 \| 1\.2M · \$0\.42 \|/);
    assert.match(reply.text, /\| 合计 \| 2\/2 \| 0 \| 0 \| 1\.2M · \$0\.42 \|/);
    assert.doesNotMatch(reply.text, /token 未知|已结束任务冻结值|巡检不计/);
    const since7 = (await import(pathToFileURL(path.join(PLUGIN, "lib", "taskqueue.js")).href)).sinceDay(7);
    const seen = fs.readFileSync(argvFile, "utf8").trim().split("\n");
    assert.deepEqual(seen[0], "--json summary --since " + since7);
    const all = await run("all patrol");
    assert.match(all.text, /^# 派发统计 · 全部（含巡检）/m);
    assert.match(all.text, /\| 合计 \| 2\/2 \| 0 \| 0 \| 1\.2M · \$0\.42 \|/);
    assert.equal(fs.readFileSync(argvFile, "utf8").trim().split("\n")[1], "--json summary --all",
      "all-time includes patrol, and no since is passed");
    const plain = await run("plain");
    assert.doesNotMatch(plain.text, /\| Agent \|/);
    assert.match(plain.text, /Claude Code {2}▓{10} {2}1\.2M · \$0\.42/);
    assert.deepEqual(fs.readFileSync(argvFile, "utf8").trim().split("\n")[2], "--json summary --since " + since7,
      "plain is a renderer choice, not a second query");
    const bad = await run("yesterday");
    assert.match(bad.text, /用法：\/dispatch-stats/);
    assert.equal(fs.readFileSync(argvFile, "utf8").trim().split("\n").length, 3, "a refused argument never reaches the ops entry");
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('patrol coverage: full recorded lens history stays separate from eight rows; area is not inferred', async () => {
  const tq = await import(pathToFileURL(path.join(PLUGIN, 'lib/taskqueue.js')).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clawock-coverage-'));
  try {
    const axes = path.join(root, 'axes.tsv');
    fs.writeFileSync(axes, 'logic\tLogic\tScope\nsecurity\tSecurity\tScope\n');
    fs.writeFileSync(path.join(root, 'labels-known.json'), JSON.stringify(['area:data', 'area:ops']));
    fs.writeFileSync(path.join(root, 'rounds.tsv'), Array.from({ length: 12 }, (_, i) =>
      `2026-09-23 03:${String(i).padStart(2, '0')}:00\tR${i + 1}\tlogic\tpatrol-${i}\t${i === 11 ? 'preempted:cancelled' : 'ok/DONE/P2#10'}\t20s`).join('\n') + '\nbad\n');
    const result = tq.readPatrolProgress(root, axes, { labels: [['area:data', 'lens:security']], asOf: '2026-09-23T04:00:00Z' });
    assert.equal(result.rounds.length, 8);
    assert.equal(result.progress.records, 12);
    const { TYPERT_REMOTE } = await import(pathToFileURL(path.join(PLUGIN, 'lib/typert.remote-client.js')).href);
    const schema = TYPERT_REMOTE.descriptors.find(d => d.method === 'taskQueue').result.create();
    const wire = schema.shape.patrol.parse({ service: 'active', phase: 'waiting', round: '', detail: '', untilMs: null, ...result });
    assert.deepEqual(wire.progress, result.progress, 'the real RPC codec must preserve coverage instead of stripping it');
    assert.equal(result.progress.rejected, 1);
    assert.deepEqual(result.progress.lenses.map(l => [l.name, l.rounds, l.open]), [['logic', 12, 0], ['security', 0, 1]]);
    assert.equal(result.progress.lenses[0].last.result, 'preempted:cancelled');
    assert.deepEqual(result.progress.areas, [{ name: 'data', open: 1 }, { name: 'ops', open: 0 }]);
    assert.ok(!('last' in result.progress.areas[0]), 'issue ownership never becomes an area inspection timestamp');
    fs.unlinkSync(path.join(root, 'rounds.tsv'));
    const missing = tq.readPatrolProgress(root, axes, { labels: null, asOf: '' });
    assert.equal(missing.progress.records, null);
    assert.ok(missing.progress.lenses.every(l => l.rounds === null && l.open === null));
    assert.ok(missing.progress.areas.every(a => a.open === null));
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("patrol issue failures preserve the last good queue, disclose stale and retry immediately", async () => {
  const cp = await import('node:child_process');
  const { syncBuiltinESMExports } = await import('node:module');
  const original = cp.default.execFile;
  const originalNow = Date.now;
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clawock-patrol-cache-'));
  let now = 2000000000000;
  let fail = false;
  let calls = 0;
  cp.default.execFile = (cmd, args, opts, cb) => {
    assert.equal(cmd, 'gh'); calls++;
    cb(fail ? new Error('temporary gh failure') : null, fail ? '' : '[{"labels":[{"name":"area:dsh"}]}]');
  };
  syncBuiltinESMExports();
  Date.now = () => now;
  try {
    const tq = await import(pathToFileURL(path.join(PLUGIN, 'lib/taskqueue.js')).href + '?patrol-cache-test');
    const service = tq.createTaskQueueService({ logDir: root, patrolDir: root }, {
      activeTaskIds: async () => [], patrolService: async () => 'active', patrolLog: async () => [],
      patrolIssues: tq.systemDeps.patrolIssues,
    });
    const good = await service.get(true);
    assert.equal(good.status, 'fresh');
    assert.equal(good.patrol.progress.areas.find(r => r.name === 'dsh').open, 1);
    now += 301000; fail = true;
    const stale = await service.get(true);
    assert.equal(stale.status, 'stale');
    assert.match(stale.message, /gh patrol issues/);
    assert.deepEqual(stale.patrol.progress, good.patrol.progress);
    await assert.rejects(tq.systemDeps.patrolIssues(), /temporary gh failure/);
    fail = false;
    assert.equal((await service.get(true)).status, 'fresh');
    assert.equal(calls, 4);
    // With no previous snapshot a failed read is explicitly failed, never empty/fresh.
    now += 301000; fail = true;
    const empty = tq.createTaskQueueService({ logDir: root, patrolDir: root }, {
      activeTaskIds: async () => [], patrolService: async () => 'active', patrolLog: async () => [],
      patrolIssues: tq.systemDeps.patrolIssues,
    });
    assert.equal((await empty.get(true)).status, 'failed');
  } finally {
    Date.now = originalNow;
    cp.default.execFile = original; syncBuiltinESMExports();
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("workbench: the signal copy, waits and first sentence are fixed", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const t = translatorFor(api);
  const now = 1_000_000_000_000;
  const task = (id, finished, extra = {}) => ({
    id, name: id, agent: "dsh", model: "", state: "ok", waiting: "", slot: "", attempts: 1, outcome: "DONE",
    startedAtMs: null, updatedAtMs: finished + 1, wakeAtMs: null, patrol: false, summary: "", lastEvent: "",
    lastEventAtMs: null, finishedAtMs: finished, needs: "", stage: "person/review", attention: "person", ...extra,
  });
  assert.equal(api.waitShort(45 * 60_000), "45m");
  assert.equal(api.waitShort(6 * 3600_000), "6h");
  assert.equal(api.waitShort(2 * 86400_000), "2d");
  assert.equal(api.waitLong(2 * 3600_000 + 14 * 60_000), "2h 14m");
  assert.equal(api.waitLong(2 * 86400_000 + 3 * 3600_000), "2d 3h");
  assert.equal(api.waitSpoken(6 * 3600_000, t), "6 小时");

  const one = api.signalView([task("a", now - 12 * 60_000)], t, now);
  assert.equal(one.aria, "工作台，1 件待处理，最旧 12 分钟",
    "the host row carries the count and the oldest wait");
  assert.equal(one.badge, "1");
  assert.equal(one.tone, "neutral", "review work keeps the neutral badge");
  assert.equal(one.pending, 1);
  const many = api.signalView([
    task("a", now - 6 * 3600_000), task("b", now - 2 * 3600_000), task("c", now - 60_000),
  ], t, now);
  assert.equal(many.total, 3);
  assert.equal(many.oldestPendingMs, 6 * 3600_000);
  const stuck = api.signalView([task("a", now - 2 * 86400_000, { stage: "person/blocked", state: "quota" })], t, now);
  assert.equal(stuck.tone, "neutral", "the count badge stays neutral; only a provider alert turns the dot red");
  assert.equal(stuck.badge, "1", "the badge is stuck + pending, not the pending group alone");
  assert.equal(stuck.pending, 0);
  const allStuck = api.signalView([
    task("a", now - 2 * 86400_000, { stage: "person/blocked", state: "quota" }),
    task("b", now - 86400_000, { stage: "person/blocked", state: "quota" }),
    task("c", now - 3600_000, { stage: "person/blocked", state: "quota" }),
  ], t, now);
  assert.equal(allStuck.stuck, 3);
  assert.equal(allStuck.pending, 0);
  assert.equal(allStuck.badge, "3");
  const overflow = api.signalView(Array.from({ length: 10 }, (_, i) => task("x" + i, now - 3 * 86400_000 + i)), t, now);
  assert.equal(overflow.badge, "10", "the badge prints the real count");
  assert.equal(overflow.tone, "neutral");

  // Both dictionaries carry every workbench key; the new copy is not zh-only.
  const en = api.createTranslator(api.dictionaries.en);
  assert.equal(en("signal.rowLabel", { n: "7", time: "5 days" }), "Workbench, 7 pending, oldest 5 days");
  assert.equal(en("workbench.close"), "Close workbench and return to the conversation");
  assert.equal(en("workbench.group.stuck", { n: "1" }), "Stuck 1");
  assert.equal(en("workbench.group.pendingOldest", { n: "6", age: "5d" }), "Pending 6 · oldest 5d");
  assert.equal(en("workbench.group.live", { n: "4" }), "Running 4");
  assert.equal(t("workbench.group.pendingOldest", { n: "6", age: "5d" }), "待你处理 6 · 最旧 5d");
  assert.equal(t("workbench.close"), "关闭工作台，返回会话");
  assert.equal(en("workbench.rowAria", { title: "T", time: "5 days" }), "T, waited 5 days");
  assert.equal(en("time.minuteOne", { n: "1" }), "1 minute");
  assert.equal(en("time.minuteMany", { n: "12" }), "12 minutes");
  assert.equal(api.waitSpoken(6 * 3600_000, en), "6 hours");
  assert.equal(api.waitSpoken(12 * 60_000, en), "12 minutes");
  assert.equal(api.waitSpoken(2 * 86400_000 + 3 * 3600_000, en), "2d 3h");
  assert.equal(api.signalView([task("a", now - 12 * 60_000)], en, now).aria,
    "Workbench, 1 pending, oldest 12 minutes");

  assert.equal(api.firstSentence("第一句。第二句。"), "第一句。");
  assert.equal(api.firstSentence("one. two."), "one");
  assert.equal(api.firstSentence("a".repeat(200), 20).endsWith("…"), true);
});

test("workbench host: pending is ATTENTION=person only, minus continuations and answers", async () => {
  const tq = await import(pathToFileURL(path.join(PLUGIN, "lib", "taskqueue.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-workbench-"));
  const logDir = path.join(root, "tasks");
  const task = (id, result, meta = "AGENT=dsh\nNAME=" + id + "\n") => {
    fs.mkdirSync(path.join(logDir, id), { recursive: true });
    fs.writeFileSync(path.join(logDir, id, "meta.env"), meta);
    fs.writeFileSync(path.join(logDir, id, "result.env"), result);
  };
  const result = (state, finished, stage, attention, needs = "") =>
    `STATE=${state}\nATTENTION=${attention}\nSTAGE=${stage}\nNEEDS='${needs}'\nFINISHED_EPOCH=${finished}\nUPDATED=2026-11-07\\ 10:00:00\n`;
  // finished epochs are seconds; the list is oldest first.
  task("old-stuck", result("quota", 1000, "person/blocked", "person"));
  task("answered", result("ok", 1500, "person/review", "person", "already answered"));
  fs.writeFileSync(path.join(logDir, "answered", "answer.json"), JSON.stringify({ state: "resolved" }));
  task("review-old", result("partial", 2000, "person/review", "person", "第一句。第二句。"));
  task("child-parent", result("ok", 2500, "person/review", "person", "continued"));
  fs.mkdirSync(path.join(logDir, "child"), { recursive: true });
  fs.writeFileSync(path.join(logDir, "child", "meta.env"), "AGENT=dsh\nNAME=child\nPARENT_TASK_ID=child-parent\n");
  fs.writeFileSync(path.join(logDir, "child", "result.env"), "STATE=ok\nUPDATED=2026-11-07\\ 11:00:00\n");
  task("review-new", result("ok", 3000, "person/review", "person", "do the next thing"),
    "AGENT=dsh\nNAME=review-new\n");
  fs.writeFileSync(path.join(logDir, "review-new", "question.json"), JSON.stringify({ recommend: 1, options: ["a", "b"] }));
  task("legacy", "STATE=partial\nATTENTION=\nSTAGE=\nFINISHED_EPOCH=\nUPDATED=2026-10-01\\ 10:00:00\n");
  task("patrol-x", result("blocked", 1200, "person/blocked", "person"));
  task("live", "STATE=running\nATTENTION=\nSTAGE=working\nUPDATED=2026-11-07\\ 10:00:00\n");
  const deps = {
    activeTaskIds: async () => ["live"],
    patrolService: async () => "",
    patrolLog: async () => [],
  };
  const config = { logDir, limitsPath: path.join(root, "limits.env"), patrolDir: path.join(root, "patrol"), recent: 5 };
  const r = await tq.createTaskQueueService(config, deps).get(true);
  assert.deepEqual(r.pending.map((task) => task.id), ["old-stuck", "review-old", "review-new"],
    "oldest first; answered, continued and patrol tasks are not pending");
  assert.equal(r.pendingTotal, 3);
  assert.equal(r.pending[0].stage, "person/blocked");
  assert.equal(r.pending[1].needs, "第一句。第二句。", "NEEDS is carried verbatim and bounded by the runner");
  assert.equal(r.pending[1].finishedAtMs, 2_000_000, "FINISHED_EPOCH seconds become ms");
  assert.equal(r.pending[2].question, true);
  assert.equal(r.pending[2].questionRecommend, 1);
  assert.equal(r.recent.length, 5, "the recent list keeps its own newest-first window");
});

test("workbench host: the three presets run the existing dispatcher commands", async () => {
  const tq = await import(pathToFileURL(path.join(PLUGIN, "lib", "taskqueue.js")).href);
  const question = { open: true, recommend: 1 };
  const plain = { open: false, recommend: 0 };
  assert.deepEqual(tq.workbenchCommand("continue", "task-1", question), { args: ["answer", "task-1", "2"], stdin: "" });
  assert.deepEqual(tq.workbenchCommand("modify", "task-1", question),
    { args: ["answer", "task-1", "--text", tq.WORKBENCH_MODIFY_TEXT], stdin: "" });
  assert.deepEqual(tq.workbenchCommand("stop", "task-1", question), { args: ["answer", "task-1", "--resolve"], stdin: "" });
  const cont = tq.workbenchCommand("continue", "task-1", plain);
  assert.deepEqual(cont.args, ["append", "task-1"], "no ask block: continue resumes the ended session");
  assert.match(cont.stdin, /NEEDS/);
  const mod = tq.workbenchCommand("modify", "task-1", plain);
  assert.deepEqual(mod.args, ["append", "task-1"]);
  assert.match(mod.stdin, /不要直接动手/);
  assert.deepEqual(tq.workbenchCommand("stop", "task-1", plain), { args: ["cancel", "task-1"], stdin: "" });
  assert.match(tq.workbenchCommand("stop", "../bad", plain), /not a task id/);
});

test("workbench host: a refused stop surfaces the ops reason instead of success", async () => {
  const { EventEmitter } = require("node:events");
  const tq = await import(pathToFileURL(path.join(PLUGIN, "lib", "taskqueue.js")).href);
  const run = (code, stderr) => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.stdin = { end() {} };
    child.kill = () => {};
    const runner = tq.createWorkbenchActionRunner(
      { dispatchScriptPath: process.execPath, logDir: path.join(os.tmpdir(), "no-such-workbench-log") },
      { spawn: () => {
        setImmediate(() => {
          if (stderr !== "") child.stderr.emit("data", Buffer.from(stderr + "\n"));
          child.emit("close", code);
        });
        return child;
      } },
    );
    return runner("stop", "done-1");
  };
  const refused = await run(3, "task done-1 has already ended (state=ok)");
  assert.equal(refused.ok, false, "already ended is a failure, not a recorded stop");
  assert.equal(refused.code, 3);
  assert.match(refused.message, /already ended \(state=ok\)/,
    "the dispatcher's real reason survives the runner");
  const ok = await run(0, "");
  assert.equal(ok.ok, true, "a real cancel still reports success");
});

test("workbench client: one sidebar entry, a neutral count and an explained provider alert", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  const queue = (pending) => ({
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending, pendingTotal: pending.length,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
  });
  const remoteFace = {
    balance: async () => ({ ok: true, value: BALANCES_OK }),
    taskQueue: async () => ({ ok: true, value: queue([]) }),
  };
  const ctx = {
    effect() {}, locale: { register() { return () => {}; } },
    get() { return remoteFace; }, layout: { selectPanel() {} },
    slots: { inject(name, fn) { (this._fns ??= []).push(fn); }, register(definition, Component) { (this._regs ??= []).push({ definition, Component }); } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  assert.deepEqual(ctx.slots._regs.map((r) => r.definition.name).sort(),
    ["conversation.view", "main", "sidebar.panellist"],
    "there is no second footer action; the workbench is the only entry");

  const now = Date.now();
  const task = (id, finished, extra = {}) => ({
    id, name: id, agent: "dsh", model: "", state: "ok", waiting: "", slot: "", attempts: 1, outcome: "DONE",
    startedAtMs: null, updatedAtMs: finished + 1, wakeAtMs: null, patrol: false, summary: "", lastEvent: "",
    lastEventAtMs: null, finishedAtMs: finished, needs: "", stage: "person/review", attention: "person", ...extra,
  });
  const alert = {
    ...BALANCES_OK,
    providers: BALANCES_OK.providers.map((row) => row.provider === "codex" ? {
      ...row, result: { ...row.result, snapshot: { ...row.result.snapshot,
        windows: row.result.snapshot.windows.map((window, i) => i === 1 ? { ...window, percent: 100 } : window) } },
    } : row.provider === "claude" ? {
      ...row, result: { ...row.result, status: "stale" },
    } : row),
  };
  const stale = {
    ...BALANCES_OK,
    providers: BALANCES_OK.providers.map((row) => row.provider !== "claude" ? row
      : { ...row, result: { ...row.result, status: "stale" } }),
  };
  const icon = ctx.slots._regs.find((r) => r.definition.name === "sidebar.panellist");
  const face = icon.definition.inject();
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const renderIcon = (balances, pending = []) => {
    const stub = makeReactStub();
    const iconApi = loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return stub;
      throw new Error(`unexpected require: ${s}`);
    });
    return iconApi.WorkbenchIcon({
      size: 16, active: false, t: translatorFor(iconApi), rememberTrigger: () => {},
      cachedTaskQueue: () => queue(pending), fetchTaskQueue: async () => queue(pending),
      cachedBalances: () => balances, fetchBalances: async () => balances,
    });
  };
  const badgeOf = (tree) => find(tree, (p) => p["data-wb-badge"] === "true")[0];
  const danger = renderIcon(alert, [task("s", now - 2 * 86400_000, { stage: "person/blocked", state: "quota" })]);
  assert.equal(badgeOf(danger), undefined, "the row paints no numeric badge; the count is in the label");
  assert.equal(find(danger, (p) => p["data-wb-provider-alert"] !== undefined)[0].props["data-wb-provider-alert"], "Codex",
    "only the alert provider names the alert");
  assert.equal(find(danger, (p) => p["data-wb-provider-alert"] !== undefined)[0].props["aria-label"], undefined,
    "the icon keeps its glyph; the words are on the host row");
  assert.equal(find(danger, (p) => p["data-wb-rail-alert"] !== undefined).length, 1,
    "the 56px rail keeps an exclamation mark, not a colour-only dot");
  assert.equal(find(renderIcon(stale), (p) => p["data-wb-provider-alert"] !== undefined).length, 0,
    "stale never raises an alert");
  const en = api.createTranslator(api.dictionaries.en);
  const zh = api.createTranslator(api.dictionaries.zh);
  assert.equal(en("workbench.labelAlert", { alerts: en("workbench.provider.alertCountOne") }),
    "Workbench · 1 alert", "the host row says what the alert is, in words");
  assert.equal(en("workbench.labelAlert", { alerts: en("workbench.provider.alertCount", { n: 2 }) }),
    "Workbench · 2 alerts");
  assert.equal(zh("workbench.labelAlert", { alerts: zh("workbench.provider.alertCountOne") }),
    "工作台 · 1 个告警");
  assert.equal(zh("workbench.labelAlert", { alerts: zh("workbench.provider.alertCount", { n: 3 }) }),
    "工作台 · 3 个告警");
  const hundred = Array.from({ length: 100 }, (_, i) => task("m" + i, now - i * 1000));
  assert.equal(badgeOf(renderIcon(alert, hundred)), undefined,
    "no badge at 100 pending either; the host label carries the count");
  assert.equal(badgeOf(renderIcon(BALANCES_OK, [task("r", now - 60_000)])), undefined,
    "a pending count is not duplicated on the glyph");
  assert.equal(badgeOf(renderIcon(BALANCES_OK, [])), undefined, "zero pending renders no badge");
  // The sidebar entry must not print a provider number: the label says the count, nothing more.
  assert.doesNotMatch(JSON.stringify(renderIcon(alert, [])), /123\.9|5h|week/,
    "no allowance reading is rendered in the drawer");
  disposeReactEffects();
});

test("workbench client: Tasks | Providers tabs, rows and status", async () => {
  const loaded = await loadClient();
  const base = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
  };
  const now = Date.now();
  const task = (i, extra = {}) => ({
    id: "t" + i, name: "任务" + i, agent: "dsh", model: "", state: "ok", waiting: "", slot: "", attempts: 1,
    outcome: "DONE", startedAtMs: null, updatedAtMs: now, wakeAtMs: null, patrol: false, summary: "",
    lastEvent: "", lastEventAtMs: null, finishedAtMs: now - i * 60000, needs: "需要人处理",
    stage: "person/review", attention: "person", ...extra,
  });
  const alert = {
    ...BALANCES_OK,
    providers: BALANCES_OK.providers.map((row) => row.provider === "codex" ? {
      ...row, result: { ...row.result, snapshot: { ...row.result.snapshot,
        windows: row.result.snapshot.windows.map((window, i) => i === 1 ? { ...window, percent: 100 } : window) } },
    } : row.provider === "claude" ? {
      ...row, result: { ...row.result, status: "stale" },
    } : row),
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const textOf = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const make = (queue, balances) => {
    const stub = makeReactStub();
    const api = loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return stub;
      throw new Error(`unexpected require: ${s}`);
    });
    const render = () => {
      stub._resetCursor();
      return api.WorkbenchPage({
        cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
        cachedBalances: () => balances, fetchBalances: async () => balances,
        closeWorkbench: () => {},
        runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
        t: translatorFor(api),
      });
    };
    return { tree: render(), render, api };
  };
  const queue = { ...base, pending: [task(0), task(1)], pendingTotal: 2 };
  const page = make(queue, alert);
  const tabs = (tree) => find(tree, (p) => p.role === "tab");
  assert.equal(find(page.tree, (p) => p.role === "tablist").length, 1, "one segmented control");
  assert.equal(tabs(page.tree).length, 3, "Tasks | Providers | Overview");
  assert.equal(tabs(page.tree)[0].props["aria-selected"], true, "Tasks is the default segment");
  assert.equal(tabs(page.tree)[1].props["aria-selected"], false);
  assert.equal(tabs(page.tree)[0].props.tabIndex, 0, "roving tabindex starts on Tasks");
  assert.equal(tabs(page.tree)[1].props.tabIndex, -1);
  assert.equal(page.tree.props["data-wb-tab"], "tasks");
  assert.equal(find(page.tree, (p) => p["data-wb-tab-alert"] !== undefined).length, 1,
    "the Providers tab carries an exclamation mark instead");
  assert.equal(tabs(page.tree)[1].props["aria-label"], "提供方，1 个异常");

  tabs(page.tree)[1].props.onClick();
  const providers = page.render();
  assert.equal(providers.props["data-wb-tab"], "providers");
  assert.equal(tabs(providers)[0].props["aria-selected"], false);
  assert.equal(tabs(providers)[1].props["aria-selected"], true);
  assert.equal(tabs(providers)[1].props.tabIndex, 0);
  assert.equal(find(providers, (p) => p.role === "tabpanel")[0].props["data-wb-panel"], "providers");
  const rows = find(providers, (p) => p["data-wb-provider"] !== undefined);
  assert.deepEqual(rows.map((row) => row.props["data-wb-provider"]), ["codex", "claude", "deepseek", "minimax", "opencode"],
    "alert first, then stale, then the healthy rows by label");
  assert.deepEqual(rows.map((row) => row.props["data-wb-provider-signal"]), ["alert", "stale", "ok", "ok", "none"]);
  assert.equal(rows[0].props["data-wb-tone"], "alert");
  assert.match(textOf(rows[0]), /Codex 已用尽 周 100%/, "exhausted wins over the used % headline");
  assert.match(textOf(rows[0]), /至 /, "the reset is always on the second line");
  assert.match(textOf(rows[1]), /旧读数/, "stale keeps its chip");
  assert.match(textOf(rows[2]), /¥110/, "a money row leads with its balance");
  assert.match(textOf(rows[2]), /余额 ¥110/, "money detail is always visible");
  assert.match(textOf(rows[4]), /免费/, "the free pool has no number");
  assert.equal(rows[0].props["data-wb-provider-state"], "exhausted");
  assert.equal(find(rows[0], (p) => p["data-wb-provider-detail"] !== undefined).length, 0,
    "provider detail is not a second layer");
  assert.ok(rows[0].props["aria-label"].includes("已用尽"));
  assert.equal(find(providers, (p) => p["data-wb-empty-providers"] !== undefined).length, 0);

  // A stale-only page has no dot on either surface.
  const stale = { ...BALANCES_OK, providers: BALANCES_OK.providers.map((row) => row.provider !== "claude" ? row
    : { ...row, result: { ...row.result, status: "stale" } }) };
  const stalePage = make(queue, stale);
  assert.equal(find(stalePage.tree, (p) => p["data-wb-tab-alert"] !== undefined).length, 0);
  tabs(stalePage.tree)[1].props.onClick();
  assert.deepEqual(find(stalePage.render(), (p) => p["data-wb-provider"] !== undefined).map((row) => row.props["data-wb-provider-signal"]),
    ["stale", "ok", "ok", "ok", "none"]);

  // An empty/failed read says so instead of pretending every provider is healthy.
  const quiet = make({ ...queue, available: false }, QUIET_BALANCES);
  tabs(quiet.tree)[1].props.onClick();
  assert.match(textOf(quiet.render()), /还没有配置 provider/);
  disposeReactEffects();
});

test("workbench client: task groups are capped and fold with aria", async () => {
  const loaded = await loadClient();
  const base = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
  };
  const now = Date.now();
  const task = (i, extra = {}) => ({
    id: "t" + i, name: "任务" + i, agent: "dsh", model: "", state: "ok", waiting: "", slot: "", attempts: 1,
    outcome: "DONE", startedAtMs: null, updatedAtMs: now, wakeAtMs: null, patrol: false, summary: "",
    lastEvent: "", lastEventAtMs: null, finishedAtMs: now - i * 60000, needs: "需要人处理",
    stage: "person/review", attention: "person", ...extra,
  });
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const textOf = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const make = (queue, narrow = false) => {
    const stub = makeReactStub();
    const api = loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return stub;
      throw new Error(`unexpected require: ${s}`);
    });
    globalThis.window = {
      localStorage: { getItem: () => null, setItem: () => {} },
      matchMedia: (query) => ({ matches: narrow && query === "(max-width: 359px)", addEventListener() {}, removeEventListener() {} }),
    };
    const render = () => {
      stub._resetCursor();
      return api.WorkbenchPage({
        cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
        cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
        closeWorkbench: () => {},
        runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
        t: translatorFor(api),
      });
    };
    return { tree: render(), render };
  };
  const queue = {
    ...base,
    pending: [
      task(0, { state: "quota", stage: "person/blocked", finishedAtMs: now - 2 * 86400_000 }),
      ...Array.from({ length: 8 }, (_, i) => task(i + 1, { finishedAtMs: now - (i + 1) * 60000 })),
    ],
    pendingTotal: 9,
  };
  const page = make(queue);
  const headers = (tree) => find(tree, (p) => p["data-wb-group-button"] !== undefined);
  const bodies = (tree) => find(tree, (p) => p["data-wb-group-body"] !== undefined);
  const openTaskRows = (tree) => find(tree, (p) => p["data-wb-open"] === "true" && p["data-wb-group"] !== undefined)
    .flatMap((section) => find(section, (p) => p["data-wb-task"] !== undefined));
  assert.deepEqual(bodies(page.tree).map((b) => b.props["data-wb-group-body"]), ["stuck", "pending"],
    "both bodies are mounted for the height transition");
  assert.ok(headers(page.tree)[1].props["aria-controls"], "a group always points at its mounted body");
  assert.equal(openTaskRows(page.tree).length, 7, "both default-open groups show 6 pending + the stuck row");
  assert.equal(find(page.tree, (p) => p["data-wb-more"] !== undefined).length, 1);
  assert.match(textOf(find(page.tree, (p) => p["data-wb-more"] !== undefined)[0]), /还有 2 条 ›/);
  headers(page.tree)[1].props.onClick();
  const closed = page.render();
  assert.equal(openTaskRows(closed).length, 1, "closing pending leaves only the stuck row");
  assert.equal(find(closed, (p) => p["data-wb-group-button"] === "pending")[0].props["aria-expanded"], false);
  headers(closed)[1].props.onClick();
  const open = page.render();
  assert.equal(openTaskRows(open).length, 7, "reopening restores the capped pending list");
  find(open, (p) => p["data-wb-more"] !== undefined)[0].props.onClick();
  const all = page.render();
  assert.equal(openTaskRows(all).length, 9);
  assert.equal(find(all, (p) => p["data-wb-more"] !== undefined).length, 0, "the escape hatch disappears at the end");

  const narrow = make(queue, true);
  const narrowReady = narrow.render();
  headers(narrowReady)[1].props.onClick();
  const narrowOpen = narrow.render();
  assert.equal(openTaskRows(narrowOpen).length, 4, "under 360px the cap is 4 pending; the stuck group closed behind it");
  assert.match(textOf(find(narrowOpen, (p) => p["data-wb-more"] !== undefined)[0]), /还有 4 条 ›/);
  headers(narrowOpen)[0].props.onClick();
  const narrowStuck = narrow.render();
  assert.equal(find(narrowStuck, (p) => p["data-wb-group-button"] === "pending")[0].props["aria-expanded"], false,
    "under 360px opening another group closes the first");
  assert.equal(find(narrowStuck, (p) => p["data-wb-group-button"] === "stuck")[0].props["aria-expanded"], true);
  delete globalThis.window;
  disposeReactEffects();
});

test("workbench client: Overview restores patrol/stats; Providers shows detail", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const task = (i, extra = {}) => ({
    id: "t" + i, name: "任务" + i, agent: "dsh", model: "deepseek-flash", state: "running", waiting: "", slot: "dsh-1",
    attempts: 1, outcome: "", startedAtMs: now - 6 * 60000, updatedAtMs: now, wakeAtMs: null, patrol: false,
    summary: "", lastEvent: "", lastEventAtMs: null, finishedAtMs: null, needs: "需要人确认", stage: "person/review",
    attention: "person", ...extra,
  });
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 1,
    running: 1, active: [task(0)], recent: [], pending: [], pendingTotal: 0,
    slotLimits: [{ agent: "dsh", max: 1 }],
    patrol: {
      service: "active", phase: "waiting", round: "", detail: "", untilMs: now + 2 * 3600_000,
      rounds: [{ endedAt: "2026-11-07 08:00:00", round: "R1", axis: "harness", result: "ok/DONE", seconds: 720 }],
      progress: { records: 1, lensInventory: true, areaInventory: true, firstAt: "2026-11-07 08:00:00", rejected: 0, issuesAt: "",
        lenses: [{ name: "harness", rounds: 1, last: null, open: 0 }, { name: "recent", rounds: 1, last: null, open: 0 }],
        areas: [{ name: "dsh", open: 3 }, { name: "data", open: 0 }] },
    },
  };
  const stats = {
    available: true, error: "", since: "2026-11-01", days: 7, patrolIncluded: false, asOf: "",
    agents: [{
      agent: "dsh", tasks: 5, live: 2, states: [],
      outcomes: [{ name: "DONE", count: 2 }, { name: "PARTIAL", count: 1 }],
      tokensTotal: 1200000, tokensUnknown: 0, costUsdEstimate: 3.4, costUnpriced: 0, costFree: 0,
    }],
    daily: {
      "2026-11-01": { dsh: { tasks: 1, tokens: 200000, unknown: 0 } },
      "2026-11-02": { dsh: { tasks: 1, tokens: 400000, unknown: 0 } },
      "2026-11-03": { dsh: { tasks: 1, tokens: 100000, unknown: 0 } },
      "2026-11-04": { dsh: { tasks: 1, tokens: 300000, unknown: 0 } },
      "2026-11-05": { dsh: { tasks: 1, tokens: 200000, unknown: 0 } },
    },
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const textOf = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const stub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = () => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => BALANCES_OK, fetchBalances: async () => BALANCES_OK,
      fetchTaskStats: async () => stats,
      closeWorkbench: () => {},
      runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
      t: translatorFor(api, "en"),
    });
  };
  const tabs = (tree) => find(tree, (p) => p.role === "tab");
  const page = render();
  assert.equal(tabs(page).length, 3, "Tasks | Providers | Overview");
  assert.equal(tabs(page)[2].props["aria-label"], "Overview");
  // Live-only queue: Running opens by default and its row keeps the detail path.
  const live = render();
  assert.equal(find(live, (p) => p["data-wb-group-button"] === "live")[0].props["aria-expanded"], true);
  find(live, (p) => p["data-wb-task"] !== undefined)[0].props.onClick();
  const focus = render();
  assert.ok(find(focus, (p) => p["data-wb-detail"] === "t0")[0], "task row -> detail");
  find(focus, (p) => p["data-wb-back"] !== undefined)[0].props.onClick();
  render();

  // Overview: three entries to their own layers, never folds. The old
  // two-open-folds state is exactly what the single state machine removed.
  tabs(page)[2].props.onClick();
  render();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const overview = render();
  assert.ok(find(overview, (p) => p["data-wb-overview"] !== undefined)[0], "Overview mounted");
  for (const id of ["patrol", "stats", "history"]) {
    const entry = find(overview, (p) => p["data-wb-group-button"] === "overview-" + id)[0];
    assert.ok(entry, id + " entry present");
    assert.equal(entry.props["aria-expanded"], undefined, id + " is an entry to its own layer, not a fold");
    assert.equal(find(overview, (p) => p["data-wb-" + id + "-layer"] !== undefined).length, 0,
      id + " layer is not mounted in Overview");
  }
  const statsHead = find(overview, (p) => p["data-wb-group-button"] === "overview-stats")[0];
  assert.match(textOf(statsHead), /5 tasks/, "the entry keeps the totals summary");
  statsHead.props.onClick();
  const statsLayer = render();
  assert.equal(find(statsLayer, (p) => p["data-wb-stats-layer"] !== undefined).length, 1,
    "Stats opened as its own layer");
  assert.equal(find(statsLayer, (p) => p["data-wb-overview"] !== undefined).length, 0,
    "Stats is mutually exclusive with Overview");
  assert.equal(find(statsLayer, (p) => p["data-wb-overview-done"] !== undefined)[0].props["data-wb-overview-done"], "2");
  assert.match(textOf(statsLayer), /1.2M/, "token metric");
  assert.match(textOf(statsLayer), /\$3.40/, "cost metric");
  assert.equal(find(statsLayer, (p) => p["data-tq-stats-chart"] !== undefined).length, 1,
    "the old per-provider stacked chart is restored");
  assert.ok(find(statsLayer, (p) => p["data-tq-stats-bar"] !== undefined).length > 0,
    "the chart still draws one bar per provider/day");
  find(statsLayer, (p) => p["data-wb-stats-back"] !== undefined)[0].props.onClick();
  const backToOverview = render();
  assert.ok(find(backToOverview, (p) => p["data-wb-overview"] !== undefined)[0], "Back returns to Overview");
  const history = find(backToOverview, (p) => p["data-wb-group-button"] === "overview-history")[0];
  assert.match(textOf(history), /0 ended/, "the history entry counts ended tasks");
  history.props.onClick();
  const historyLayer = render();
  assert.equal(find(historyLayer, (p) => p["data-wb-history-layer"] !== undefined).length, 1,
    "History opened as its own layer");
  assert.equal(find(historyLayer, (p) => p["data-wb-overview"] !== undefined).length, 0,
    "History is mutually exclusive with Overview");
  assert.equal(find(historyLayer, (p) => p["data-wb-history"] !== undefined).length, 0,
    "an empty history mounts no rows");
  find(historyLayer, (p) => p["data-wb-history-back"] !== undefined)[0].props.onClick();
  const expanded = render();
  assert.ok(find(expanded, (p) => p["data-wb-overview"] !== undefined)[0], "Back from History returns to Overview");

  // Providers: both detail lines are always visible, no click/second layer.
  tabs(expanded)[1].props.onClick();
  const providers = render();
  const mini = find(providers, (p) => p["data-wb-provider"] === "minimax")[0];
  assert.match(textOf(mini), /24%/, "used percentage");
  assert.match(textOf(mini), /to /, "window end on line 2");
  assert.match(textOf(mini), /10%/, "week share");
  const deep = find(providers, (p) => p["data-wb-provider"] === "deepseek")[0];
  assert.match(textOf(deep), /balance ¥110/, "money balance on line 2");
  assert.equal(find(deep, (p) => p["data-wb-provider-detail"] !== undefined).length, 0);
  disposeReactEffects();
});

test("workbench client: Overview copy is pinned in Chinese", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: now + 3600_000,
      rounds: [{ endedAt: "2026-11-07 08:00:00", round: "R1", axis: "harness", result: "ok/DONE", seconds: 60 }],
      progress: { records: 1, lensInventory: true, areaInventory: true, firstAt: "", rejected: 0, issuesAt: "", lenses: [], areas: [] } },
  };
  const stats = { available: true, error: "", since: null, days: 7, patrolIncluded: false, asOf: "",
    agents: [{ agent: "dsh", tasks: 2, live: 0, states: [], outcomes: [{ name: "DONE", count: 2 }], tokensTotal: 10, tokensUnknown: 0, costUsdEstimate: 0.1, costUnpriced: 0, costFree: 0 }] };
  const stub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = () => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
      fetchTaskStats: async () => stats,
      closeWorkbench: () => {},
      runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
      t: translatorFor(api),
    });
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const textOf = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ");
  };
  const page = render();
  const tabs = find(page, (p) => p.role === "tab");
  assert.equal(tabs[1].props["aria-label"], "提供方，无异常");
  assert.equal(tabs[2].props["aria-label"], "概况");
  tabs[2].props.onClick();
  render();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const overview = render();
  assert.match(textOf(overview), /巡检/);
  assert.match(textOf(overview), /统计/);
  find(overview, (p) => p["data-wb-group-button"] === "overview-patrol")[0].props.onClick();
  const patrolLayer = render();
  assert.match(textOf(patrolLayer), /最近轮次/);
  assert.match(textOf(patrolLayer), /未决/);
  assert.match(textOf(patrolLayer), /节奏/);
  find(patrolLayer, (p) => p["data-wb-patrol-back"] !== undefined)[0].props.onClick();
  const backToOverview = render();
  find(backToOverview, (p) => p["data-wb-group-button"] === "overview-stats")[0].props.onClick();
  const expanded = render();
  assert.match(textOf(expanded), /完成 2/);
  assert.match(textOf(expanded), /Token \/ API 估价/);
  assert.match(textOf(expanded), /暂无用量数据/);
  disposeReactEffects();
});

test("workbench client: English copy, a zero balance and a failed read", async () => {
  const loaded = await loadClient();
  const base = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const textOf = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const zero = {
    ...BALANCES_OK,
    providers: BALANCES_OK.providers.map((row) => row.provider !== "deepseek" ? row : {
      ...row, result: { ...row.result, snapshot: { ...row.result.snapshot, isAvailable: false, totalBalance: "0", grantedBalance: "0" } },
    }),
  };
  const make = (balances, locale = "en", fail = false) => {
    const stub = makeReactStub();
    const api = loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return stub;
      throw new Error(`unexpected require: ${s}`);
    });
    const render = () => {
      stub._resetCursor();
      return api.WorkbenchPage({
        cachedTaskQueue: () => base, fetchTaskQueue: async () => base,
        cachedBalances: () => balances, fetchBalances: fail ? async () => { throw new Error("boom") } : async () => balances,
        closeWorkbench: () => {},
        runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
        t: translatorFor(api, locale),
      });
    };
    return { tree: render(), render, api };
  };
  const page = make(zero, "en");
  const tabs = (tree) => find(tree, (p) => p.role === "tab");
  assert.equal(tabs(page.tree)[1].props["aria-label"], "Providers, 1 alert",
    "the English tab says one alert in the singular");
  tabs(page.tree)[1].props.onClick();
  const rows = find(page.render(), (p) => p["data-wb-provider"] !== undefined);
  assert.deepEqual(rows.map((row) => row.props["data-wb-provider"]), ["deepseek", "claude", "codex", "minimax", "opencode"]);
  assert.equal(rows[0].props["data-wb-provider-signal"], "alert", "a zero balance is an alert");
  assert.match(textOf(rows[0]), /¥0/, "zero prints, not an empty cell");
  assert.equal(rows[1].props["data-wb-provider-signal"], "ok");
  assert.match(textOf(rows[4]), /Free|free/);
  assert.equal(tabs(page.tree)[0].props["aria-label"], "Tasks, 0 pending");

  // A near-limit window is amber on the reading that caused it, not on the healthy headline.
  const warn = {
    ...BALANCES_OK,
    providers: BALANCES_OK.providers.map((row) => row.provider !== "minimax" ? row : {
      ...row, result: { ...row.result, snapshot: { ...row.result.snapshot,
        windows: row.result.snapshot.windows.map((window, i) => i === 1 ? { ...window, percent: 80 } : window) } },
    }),
  };
  const warnPage = make(warn);
  tabs(warnPage.tree)[1].props.onClick();
  const mini = find(warnPage.render(), (p) => p["data-wb-provider"] === "minimax")[0];
  assert.equal(find(mini, (p) => p["data-wb-tone"] === "warn" && /wb-prov-(primary|secondary)/.test(p.className || "")).length, 1,
    "only the week reading turns amber");
  assert.equal(find(mini, (p) => p["data-wb-tone"] === "ok" && /wb-prov-primary/.test(p.className || "")).length, 1,
    "the healthy 5h headline stays green");
  // A transport failure is stated in the segment, not hidden behind the empty copy.
  const unknown = {
    ...BALANCES_OK,
    providers: [...BALANCES_OK.providers, {
      provider: "mystery", label: "Unknown",
      result: { configured: false, snapshot: null, status: "no-key", low: false, message: null, threshold: 20, refreshMs: 60000 },
    }],
  };
  const unknownPage = make(unknown, "en");
  tabs(unknownPage.tree)[1].props.onClick();
  const mystery = find(unknownPage.render(), (p) => p["data-wb-provider"] === "mystery")[0];
  assert.equal(mystery.props["data-wb-provider-state"], "unknown");
  assert.match(textOf(mystery), /Unavailable/);
  // A transport failure is stated in the segment, not hidden behind the empty copy.
  const failed = make(null, "en", true);
  tabs(failed.tree)[1].props.onClick();
  failed.tree = failed.render();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.match(textOf(failed.render()), /Could not read allowances/);
  disposeReactEffects();
});

test("workbench client: the fold choice is remembered in workbench.groups", async () => {
  const loaded = await loadClient();
  const storage = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (key) => storage.has(key) ? storage.get(key) : null,
      setItem: (key, value) => { storage.set(key, value); },
    },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  };
  const makeApi = (stub) => loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  try {
    const now = Date.now();
    const task = {
      id: "t1", name: "任务 1", agent: "dsh", model: "", state: "ok", waiting: "", slot: "", attempts: 1,
      outcome: "DONE", startedAtMs: null, updatedAtMs: now, wakeAtMs: null, patrol: false, summary: "",
      lastEvent: "", lastEventAtMs: null, finishedAtMs: now - 3600_000, needs: "x", stage: "person/review",
      attention: "person",
    };
    const queue = {
      available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
      running: 0, active: [], recent: [], pending: [task], pendingTotal: 1,
      patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
    };
    const render = (api, stub) => {
      stub._resetCursor();
      return api.WorkbenchPage({
        cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
        cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
        closeWorkbench: () => {},
        runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
        t: translatorFor(api),
      });
    };
    const findBy = (tree, pred) => {
      const out = [];
      (function walk(node) {
        if (node == null) return;
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (typeof node !== "object") return;
        if (pred(node.props || {})) out.push(node);
        (node.children || []).forEach(walk);
      })(tree);
      return out;
    };
    const stub1 = makeReactStub();
    const api1 = makeApi(stub1);
    const first = render(api1, stub1);
    findBy(first, (p) => p["data-wb-group-button"] === "pending")[0].props.onClick();
    assert.deepEqual(JSON.parse(storage.get("workbench.groups.v2")), { stuck: true, pending: false, live: false });

    const stub2 = makeReactStub();
    const api2 = makeApi(stub2);
    const next = render(api2, stub2);
    assert.equal(findBy(next, (p) => p["data-wb-group-button"] === "pending")[0].props["aria-expanded"], false,
      "a fresh mount reads the device's folded choice");
    const openRows = findBy(next, (p) => p["data-wb-open"] === "true" && p["data-wb-group"] !== undefined)
      .flatMap((section) => findBy(section, (p) => p["data-wb-task"] !== undefined));
    assert.equal(openRows.length, 0);
  } finally {
    delete globalThis.window;
    disposeReactEffects();
  }
});

test("workbench client: the old task-detail capabilities are all reachable in place", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const base = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 1,
    running: 1, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
    ops: { available: true, version: "abc", repoVersion: "abc", api: 7, runnerApi: 7, fairWaitSec: 30, error: "" },
  };
  const liveTask = {
    id: "live-1", name: "live one", agent: "dsh", model: "deepseek-flash", state: "running", waiting: "", slot: "dsh-1",
    attempts: 2, outcome: "", startedAtMs: now - 3600_000, updatedAtMs: now, wakeAtMs: null, patrol: false,
    summary: "", lastEvent: "working", lastEventAtMs: now, finishedAtMs: null, needs: "confirm the change",
    stage: "working", attention: "person", session: "session-1", runnerApi: 7,
    deadlineAtMs: now + 7200_000, maxAttempts: 3, quotaResumes: 3, quotaResumesUsed: 0,
    tokensTotal: 12000, tokensIn: 1000, tokensCacheW: 0, tokensCacheR: 10000, tokensOut: 1000,
    costUsd: "0.12", notify: ["weixin"], notified: [], notifyFailed: [], queuedAtMs: now - 7200_000,
  };
  const endedTask = {
    ...liveTask, id: "done-1", name: "done one", state: "partial", outcome: "PARTIAL", finishedAtMs: now - 60_000,
    startedAtMs: now - 7200_000, updatedAtMs: now - 60_000, summary: "shipped half", lastEvent: "", session: "session-2",
  };
  const queue = { ...base, active: [liveTask], recent: [endedTask] };
  const calls = [];
  const stub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = () => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => BALANCES_OK, fetchBalances: async () => BALANCES_OK,
      closeWorkbench: () => {},
      runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
      runQueueAction: async (action, id, arg) => {
        calls.push([action, id, arg]);
        return { ok: true, code: 0, action, id, message: "ok", detail: "" };
      },
      t: translatorFor(api),
    });
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const text = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const tabs = (tree) => find(tree, (p) => p.role === "tab");

  try {
    // Live task: every old detail section and write control is mounted in place.
    let tree = render();
  find(tree, (p) => p["data-wb-task"] === "live-1")[0].props.onClick();
  tree = render();
  assert.ok(find(tree, (p) => p["data-tq-detail"] === "live-1")[0], "row -> in-place detail");
  assert.deepEqual(find(tree, (p) => p["data-tq-section"] !== undefined).map((node) => node.props["data-tq-section"]),
    ["status", "view", "run", "allowance", "time", "usage", "notify", "end", "raw"]);
  const actions = find(tree, (p) => p["data-tq-action"] !== undefined).map((node) => node.props["data-tq-action"]);
  for (const action of ["brief", "log", "timeline", "model", "deadline", "attempts", "resumes", "wrapup", "cancel", "raw-log"]) {
    assert.ok(actions.includes(action), `detail action ${action} is reachable`);
  }
  assert.match(text(tree), /DeepSeek|deepseek-flash/i, "model is shown");
  assert.match(text(tree), /0\.12|12k|Tokens/i, "cost and tokens are shown");
  assert.match(text(tree), /微信|WeChat|weixin/i, "the notification channel is shown");
  assert.equal(find(tree, (p) => p["data-tq-field"] === "tokens").length, 1);
  const stopButton = (page) => find(page, (p) => typeof p.className === "string" && p.className.includes("wb-act-danger"));
  assert.equal(stopButton(tree).length, 0,
    "the presets are for a needs-you task; a running task has no Stop here");

  // Ended task: the history row opens the same detail, with its result and retry.
  find(render(), (p) => p["data-wb-back"] !== undefined)[0].props.onClick();
  tree = render();
  tabs(tree)[2].props.onClick();
  tree = render();
  find(tree, (p) => p["data-wb-group-button"] === "overview-history")[0].props.onClick();
  tree = render();
  const history = find(tree, (p) => p["data-wb-history"] === "done-1");
  assert.equal(history.length, 1, "the history row is mounted once its fold opens");
  history[0].props.onClick();
  tree = render();
  assert.ok(find(tree, (p) => p["data-tq-detail"] === "done-1")[0], "history -> the same task detail");
  assert.ok(find(tree, (p) => p["data-tq-section"] === "summary")[0], "the closing result is restored");
  assert.ok(find(tree, (p) => p["data-tq-action"] === "retry")[0], "an ended task can be retried");
  assert.equal(stopButton(tree).length, 0, "an ended task has no dead Stop");
  assert.equal(find(tree, (p) => p["data-tq-action"] === "cancel").length, 0,
    "an ended task has no cancel write");
  assert.match(text(tree), /shipped half/, "the frozen result is printed");
  assert.equal(calls.length, 0, "opening a detail writes nothing");
  } finally {
    disposeReactEffects();
  }
});

test("workbench client: a refused Stop shows the dispatcher's reason", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const task = {
    id: "q-done", name: "done with an open question", agent: "dsh", model: "deepseek-flash",
    state: "ok", waiting: "", slot: "", attempts: 1, outcome: "DONE",
    startedAtMs: now - 7200_000, updatedAtMs: now - 60_000, wakeAtMs: null, patrol: false,
    summary: "", lastEvent: "", lastEventAtMs: null, finishedAtMs: now - 60_000,
    needs: "answer the question", stage: "person/review", attention: "person",
    question: true, questionRecommend: 0, session: "session-q", runnerApi: 7,
    deadlineAtMs: null, maxAttempts: 3, quotaResumes: 3, quotaResumesUsed: 0,
    tokensTotal: 0, tokensIn: 0, tokensCacheW: 0, tokensCacheR: 0, tokensOut: 0,
    costUsd: "0", notify: [], notified: [], notifyFailed: [], queuedAtMs: now - 7800_000,
    waitMs: 600_000, priority: 0, protected: false, position: null,
  };
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 1,
    running: 0, active: [], recent: [], pending: [task], pendingTotal: 1,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
    ops: { available: true, version: "abc", repoVersion: "abc", api: 7, runnerApi: 7, fairWaitSec: 30, error: "" },
  };
  const calls = [];
  const stub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = () => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
      closeWorkbench: () => {},
      runWorkbenchAction: async (action, id) => {
        calls.push(action);
        return { ok: false, code: 3, action, id, message: "task q-done has already ended (state=ok)", detail: "" };
      },
      t: translatorFor(api),
    });
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  const textOf = (tree) => {
    const parts = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { parts.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  try {
    let tree = render();
    find(tree, (p) => p["data-wb-task"] === "q-done")[0].props.onClick();
    tree = render();
    const stop = () => find(tree, (p) => typeof p.className === "string" && p.className.includes("wb-act-danger"))[0];
    assert.ok(stop(), "a terminal task with an open question still has the resolve Stop");
    stop().props.onClick();
    tree = render();
    stop().props.onClick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    tree = render();
    assert.deepEqual(calls, ["stop"], "one stop request is sent");
    const toast = find(tree, (p) => p["data-wb-toast"] !== undefined)[0];
    assert.ok(toast, "the refusal is shown, not swallowed");
    assert.match(textOf(toast), /already ended \(state=ok\)/,
      "the UI shows the dispatcher's real reason");
  } finally {
    disposeReactEffects();
  }
});

test("workbench client: Full log opens the preview or says why it cannot", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const task = {
    id: "done-1", name: "done one", agent: "dsh", model: "deepseek-flash", state: "ok",
    waiting: "", slot: "", attempts: 1, outcome: "DONE",
    startedAtMs: now - 7200_000, updatedAtMs: now - 60_000, wakeAtMs: null, patrol: false,
    summary: "- shipped half\nSTATUS: DONE", lastEvent: "", lastEventAtMs: null, finishedAtMs: now - 60_000,
    needs: "review the result", stage: "person/review", attention: "person", question: false,
    session: "session-done", runnerApi: 7, deadlineAtMs: null, maxAttempts: 3,
    quotaResumes: 3, quotaResumesUsed: 0, tokensTotal: 0, tokensIn: 0, tokensCacheW: 0,
    tokensCacheR: 0, tokensOut: 0, costUsd: "0", notify: [], notified: [], notifyFailed: [],
    queuedAtMs: now - 7800_000, waitMs: 600_000, priority: 0, protected: false, position: null,
  };
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 1,
    running: 0, active: [], recent: [], pending: [task], pendingTotal: 1, logDir: "/tmp/tasks",
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
    ops: { available: true, version: "abc", repoVersion: "abc", api: 7, runnerApi: 7, fairWaitSec: 30, error: "" },
  };
  const make = (openFile) => {
    const calls = [];
    const stub = makeReactStub();
    const api = loaded.factory((s) => {
      if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
      if (s === "react") return stub;
      throw new Error(`unexpected require: ${s}`);
    });
    const render = () => {
      stub._resetCursor();
      return api.WorkbenchPage({
        cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
        cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
        closeWorkbench: () => {}, openFile,
        runQueueAction: async (action, id) => {
          calls.push([action, id]);
          return { ok: true, code: 0, action, id, message: "", detail: JSON.stringify({
            lines: ["line 1", "line 2"], timeline: { events: [], omitted_bytes: 0, omitted_events: 0, audit_truncated: false, log_missing: false },
          }) };
        },
        t: translatorFor(api),
      });
    };
    const find = (tree, pred) => {
      const out = [];
      (function walk(node) {
        if (node == null) return;
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (typeof node !== "object") return;
        if (pred(node.props || {})) out.push(node);
        (node.children || []).forEach(walk);
      })(tree);
      return out;
    };
    const textOf = (tree) => {
      const parts = [];
      (function walk(node) {
        if (node == null) return;
        if (Array.isArray(node)) { node.forEach(walk); return; }
        if (typeof node === "string") { parts.push(node); return; }
        (node.children || []).forEach(walk);
      })(tree);
      return parts.join(" ").replace(/\s+/g, " ").trim();
    };
    return { render, calls, find, textOf };
  };
  try {
    // No conversation on the global main panel: no native preview is possible.
    const absent = make(() => ({ ok: false, reason: "no-session" }));
    let tree = absent.render();
    absent.find(tree, (p) => p["data-wb-task"] === "done-1")[0].props.onClick();
    tree = absent.render();
    absent.find(tree, (p) => p["data-tq-action"] === "summary-log")[0].props.onClick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    tree = absent.render();
    assert.deepEqual(absent.calls, [["log", "done-1"]], "the inline log is loaded");
    const toast = absent.find(tree, (p) => p["data-wb-toast"] !== undefined)[0];
    assert.ok(toast, "the reason is shown");
    assert.match(absent.textOf(toast), /没有会话/);
    assert.match(absent.textOf(toast), /内联/);
    assert.doesNotMatch(absent.textOf(toast), /先进入任意会话|open any conversation/,
      "no instruction that cannot be followed on this page");

    // A host with a preview: the native path wins and nothing is said.
    const native = make(() => ({ ok: true }));
    tree = native.render();
    native.find(tree, (p) => p["data-wb-task"] === "done-1")[0].props.onClick();
    tree = native.render();
    native.find(tree, (p) => p["data-tq-action"] === "summary-log")[0].props.onClick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    tree = native.render();
    assert.deepEqual(native.calls, [], "no inline fallback when the preview opened");
    assert.equal(native.find(tree, (p) => p["data-wb-toast"] !== undefined).length, 0,
      "no warning when the preview opened");
  } finally {
    disposeReactEffects();
  }
});

test("workbench client: patrol and task are exclusive detail layers", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const task = {
    id: "live-1", name: "图层任务", agent: "dsh", model: "", state: "running", waiting: "", slot: "dsh-1", attempts: 1,
    outcome: "", startedAtMs: now - 60_000, updatedAtMs: now, wakeAtMs: null, patrol: false, summary: "",
    lastEvent: "", lastEventAtMs: now, finishedAtMs: null, needs: "检查图层", stage: "machine/running",
    attention: "person",
  };
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 1,
    running: 1, active: [task], recent: [], pending: [task], pendingTotal: 1,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: now + 3600_000,
      rounds: [{ endedAt: "2026-11-07 08:00:00", round: "R1", axis: "harness", result: "ok/DONE", seconds: 60 }],
      progress: { records: 1, lensInventory: true, areaInventory: true, firstAt: "", rejected: 0, issuesAt: "", lenses: [], areas: [] } },
  };
  const stub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = () => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
      closeWorkbench: () => {},
      runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
      t: translatorFor(api),
    });
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  try {
    const page = render();
    find(page, (p) => p.role === "tab")[2].props.onClick();
    const overview = render();
    find(overview, (p) => p["data-wb-group-button"] === "overview-patrol")[0].props.onClick();
    const patrol = render();
    assert.equal(find(patrol, (p) => p["data-wb-view"] === "patrol").length, 1, "patrol is its own view");
    assert.equal(find(patrol, (p) => p["data-wb-patrol-layer"] !== undefined).length, 1);
    assert.equal(find(patrol, (p) => p["data-wb-overview"] !== undefined).length, 0,
      "opening patrol unmounts Overview");
    assert.equal(find(patrol, (p) => p["data-wb-detail"] !== undefined).length, 0,
      "opening patrol unmounts any task detail");
    find(patrol, (p) => p["data-wb-patrol-back"] !== undefined)[0].props.onClick();
    const back = render();
    assert.equal(find(back, (p) => p["data-wb-overview"] !== undefined).length, 1, "back returns to Overview");
    assert.equal(find(back, (p) => p["data-wb-patrol-layer"] !== undefined).length, 0);
    find(back, (p) => p.role === "tab")[0].props.onClick();
    const tasks = render();
    find(tasks, (p) => p["data-wb-task"] === "live-1")[0].props.onClick();
    const detail = render();
    assert.equal(find(detail, (p) => p["data-wb-detail"] === "live-1").length, 1, "task detail mounted");
    assert.equal(find(detail, (p) => p["data-wb-patrol-layer"] !== undefined).length, 0,
      "the task layer never mounts the patrol layer");
    assert.equal(find(detail, (p) => p["data-coverage"] !== undefined).length, 0,
      "patrol coverage is not a block under the task detail");
    assert.equal(find(detail, (p) => p["data-wb-fold"] === "coverage").length, 0,
      "the old detail coverage fold is gone");
    find(detail, (p) => p["data-wb-back"] !== undefined)[0].props.onClick();
    const list = render();
    assert.equal(find(list, (p) => p["data-wb-detail"] !== undefined).length, 0, "back unmounts the task detail");
  } finally {
    disposeReactEffects();
  }
});

test("workbench client: a failed stats read offers a retry", async () => {
  const loaded = await loadClient();
  const now = Date.now();
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: now + 3600_000, rounds: [] },
  };
  const stats = {
    available: true, error: "", since: "2026-11-01", days: 1, patrolIncluded: false, asOf: "",
    agents: [{ agent: "dsh", tasks: 1, live: 0, states: [], outcomes: [{ name: "DONE", count: 1 }],
      tokensTotal: 10, tokensUnknown: 0, costUsdEstimate: 0.1, costUnpriced: 0, costFree: 0 }],
    daily: { "2026-11-01": { dsh: { tasks: 1, tokens: 10, unknown: 0 } } },
  };
  let reads = 0;
  const fetchTaskStats = async () => {
    reads += 1;
    if (reads === 1) throw new Error("stats backend down");
    return stats;
  };
  const stub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = () => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => QUIET_BALANCES, fetchBalances: async () => QUIET_BALANCES,
      fetchTaskStats,
      closeWorkbench: () => {},
      runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
      t: translatorFor(api, "en"),
    });
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  try {
    const page = render();
    find(page, (p) => p.role === "tab")[2].props.onClick();
    render();
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    const failed = render();
    find(failed, (p) => p["data-wb-group-button"] === "overview-stats")[0].props.onClick();
    const open = render();
    const retry = find(open, (p) => p["data-tq-stats-retry"] !== undefined)[0];
    assert.ok(retry, "the unavailable branch renders the retry control");
    assert.equal(reads, 1);
    retry.props.onClick();
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    const recovered = render();
    assert.equal(reads, 2, "Retry asks the host again");
    assert.equal(find(recovered, (p) => p["data-tq-stats-chart"] !== undefined).length, 1,
      "the recovered read paints the stats detail");
    assert.equal(find(recovered, (p) => p["data-tq-stats-retry"] !== undefined).length, 0);
  } finally {
    disposeReactEffects();
  }
});

test("workbench client: a provider row can be pinned to the top", async () => {
  const loaded = await loadClient();
  const storage = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (key) => storage.has(key) ? storage.get(key) : null,
      setItem: (key, value) => { storage.set(key, value); },
      removeItem: (key) => { storage.delete(key); },
    },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  };
  const now = Date.now();
  const queue = {
    available: true, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], pending: [], pendingTotal: 0,
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
  };
  const makeApi = (stub) => loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return stub;
    throw new Error(`unexpected require: ${s}`);
  });
  const render = (api, stub) => {
    stub._resetCursor();
    return api.WorkbenchPage({
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => BALANCES_OK, fetchBalances: async () => BALANCES_OK,
      closeWorkbench: () => {},
      runWorkbenchAction: async () => ({ ok: true, code: 0, action: "continue", id: "", message: "", detail: "" }),
      t: translatorFor(api, "en"),
    });
  };
  const find = (tree, pred) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node !== "object") return;
      if (pred(node.props || {})) out.push(node);
      (node.children || []).forEach(walk);
    })(tree);
    return out;
  };
  try {
    const stub = makeReactStub();
    const api = makeApi(stub);
    const page = render(api, stub);
    find(page, (p) => p.role === "tab")[1].props.onClick();
    const providers = render(api, stub);
    const order = (tree) => find(tree, (p) => p["data-wb-provider"] !== undefined).map((row) => row.props["data-wb-provider"]);
    assert.deepEqual(order(providers).slice(0, 2), ["claude", "codex"]);
    find(providers, (p) => p["data-wb-provider-pin"] === "deepseek")[0].props.onClick();
    const pinned = render(api, stub);
    assert.deepEqual(order(pinned).slice(0, 2), ["deepseek", "claude"], "pinned row moves first");
    assert.equal(find(pinned, (p) => p["data-wb-provider-pin"] === "deepseek")[0].props["aria-pressed"], true);
    assert.equal(storage.get("workbench.provider.pin.v1"), "deepseek");

    const stub2 = makeReactStub();
    const api2 = makeApi(stub2);
    const remount = render(api2, stub2);
    find(remount, (p) => p.role === "tab")[1].props.onClick();
    const remembered = render(api2, stub2);
    assert.deepEqual(order(remembered).slice(0, 2), ["deepseek", "claude"], "a fresh mount remembers the pin");
    find(remembered, (p) => p["data-wb-provider-pin"] === "deepseek")[0].props.onClick();
    const unpinned = render(api2, stub2);
    assert.deepEqual(order(unpinned).slice(0, 2), ["claude", "codex"], "a second tap unpins");
    assert.equal(storage.has("workbench.provider.pin.v1"), false);
  } finally {
    delete globalThis.window;
    disposeReactEffects();
  }
});
