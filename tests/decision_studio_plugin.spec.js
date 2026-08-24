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
      // the scroll/outside-click effects must simply do nothing, and the rest
      // are plain { current } holders.
      return { current: initial === undefined ? null : initial };
    },
  };
}

/** Balance fixtures: per-provider rows and the whole-chip envelope. */
const AS_OF = "2026-08-23T10:00:00.000Z";
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
const BALANCES_OK = { providers: [DS_ROW_OK, MM_ROW_OK, CL_ROW_OK], refreshMs: 60000 };
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

async function loadClient() {
  let loaded = null;
  globalThis.window = { __ModuleLoader__: { load(entry) { loaded = entry; } } };
  await import(clientUrl());
  assert.ok(loaded, "client.js must register through the module loader");
  return loaded;
}

test("client: registers the Decision Mind tab and mounts the remote face", async () => {
  const loaded = await loadClient();
  assert.equal(loaded.id, "clawock-dsh");
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  assert.deepEqual(api.inject, ["slots", "remote"]);

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
    get(name) { assert.equal(name, "remote.clawockStudio"); return remoteFace; },
    slots: {
      inject(name, fn) { (this._seats ??= []).push(name); (this._fns ??= []).push(fn); },
      register(definition, Component) { (this._regs ??= []).push({ definition, Component }); },
    },
    remote: {
      $mount: async (descriptors) => {
        assert.equal(descriptors.descriptors.length, 7);
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

  // The chip's inject face owns the balance channel with its own cache.
  const balInjected = chipReg.definition.inject("s1");
  assert.equal(typeof balInjected.cachedBalances, "function");
  assert.equal(balInjected.cachedBalances(), null, "a fresh registration has no balances answer yet");
  const bal = await balInjected.fetchBalances(false);
  assert.deepEqual(bal.providers.map((r) => r.provider), ["deepseek", "minimax", "claude"],
    "stable display order across the three providers");
  assert.equal(bal.providers[0].result.snapshot.totalBalance, "110.00");
  assert.ok(balInjected.cachedBalances(), "the fetched answer is cached in the apply closure");
  // The chip's pinned-provider choice is registration-store state.
  assert.deepEqual(chipReg.definition.store.spec.init(), { selected: null });
});

test("client: _displayEntry projects a trace with its decision and T+1", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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
});

test("client: renders the single decision-trace view from the mounted remote", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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
  let tree = component({ sessionId: "s1", cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  await tick(); await tick(); await tick();
  tree = component({ sessionId: "s1", cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });

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
  assert.match(joined, /\+45.21/);       // realized P&L on the real sell
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
  tree = component({ sessionId: "s1", cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
  const joinedMiss = collectText();
  assert.match(joinedMiss, /SPCH/);
  assert.doesNotMatch(joinedMiss, /PLTU/); // PLTU has a decision → filtered out

  // Expand a row: the trace detail shows plan → execution → P&L.
  findButton("全部").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
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
  tree = component({ sessionId: "s1", cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
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
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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

test("client: trace list batches older days behind 'show earlier' and folds by day", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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
  const render = () => component({ sessionId: "s1", cachedTraces: injected.cachedTraces, fetchTraces: injected.fetchTraces, useStore: store.useStore, actions: store.actions });
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
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub(counter);
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
      if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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
  assert.match(css, hashed("bp-win-bar"), "per-window progress bar required");
  // Colour tiers are part of the contract: the pill number and the bar fill
  // both key off the usage direction (ok green / mid yellow / low red).
  assert.match(css, /_bchip-v\[data-used-level=ok\]/, "pill green tier selector required");
  assert.match(css, /_bchip-v\[data-used-level=mid\]/, "pill yellow tier selector required");
  assert.match(css, /_bp-win-fill\[data-balance-state=mid\]/, "bar approach-band selector required");
  // lightningcss minifies the attribute selector's quotes away; the
  // contract is the data attribute itself, not its quoting.
  assert.match(css, /_bchip-v\[data-balance-state=low\]/, "chip low value selector required");
  assert.match(css, /_bp\[data-open=false\]/, "closed-panel state selector required");
  // Tier colours must NOT paint over a stale reading (数字不可信优先于用量档,
  // 与面板 bp-win-fill 的既有优先级一致)。These attr rules share specificity
  // and co-occur on one element, so source order decides: stale must come last.
  const idxOf = (re) => { const m = re.exec(css); return m === null ? -1 : m.index; };
  const chipStale = idxOf(/_bchip-v\[data-balance-state=stale\]/);
  const chipMid = idxOf(/_bchip-v\[data-used-level=mid\]/);
  assert.ok(chipStale > -1 && chipStale > chipMid,
    "stale yellow must out-rank the pill's usage tiers in source order");
  const fillStale = idxOf(/_bp-win-fill\[data-balance-state=stale\]/);
  const fillMid = idxOf(/_bp-win-fill\[data-balance-state=mid\]/);
  assert.ok(fillStale > -1 && fillStale > fillMid,
    "bar stale yellow must keep out-ranking usage tiers in source order");
  assert.match(css, hashed("skel"), "cold-start skeleton block required");
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
  const desk = (tradeDate) => fs.writeFileSync(path.join(root, "portfolio.json"), JSON.stringify({
    portfolios: { hk_stocks: { currency: "HKD", holdings: [
      { ticker: "00700", shares: 10, current_price: 100,
        trades: [{ date: tradeDate, action: "buy", shares: 10, price: 100 }] },
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
  assert.equal(degraded.isAvailable, false);

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

    // A failed refresh keeps the last good snapshot and reports stale —
    // a transient 429 cannot erase a real number.
    globalThis.fetch = async () => { throw new Error("down"); };
    const stale = await service.get(true);
    assert.equal(stale.status, "stale");
    assert.equal(stale.snapshot.totalBalance, "9.00");
    assert.match(stale.message, /down/);
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
  assert.match(mmParsed.windows[0].resetAt, /^\d{2}:\d{2}$/);
  assert.throws(() => parseMinimaxRemains({ base_resp: { status_code: 0 } }, AS_OF), /model_remains/);
  // Epoch seconds AND milliseconds both read; garbage does not crash.
  const withReset = parseMinimaxRemains({
    base_resp: { status_code: 0 },
    model_remains: [{ model: "general", current_interval_remaining_percent: 50, end_time: 1785196800000 }],
  }, AS_OF);
  assert.match(withReset.windows[0].resetAt, /^\d{2}:\d{2}$/);

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
    assert.deepEqual(fresh.snapshot.windows.map((w) => [w.label, w.percent]), [["会话", 36], ["本周", 69]]);
    assert.match(fresh.snapshot.windows[0].resetAt, /^\d{2}:\d{2}$/);
    assert.match(fresh.snapshot.note, /会话窗口已使用 36%/);
    assert.match(fresh.snapshot.note, /本周已使用 69%/, "note mirrors the weekly window");
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
    assert.match(expired.message, /过期/);

    // Missing file entirely → in-band no-key.
    const none = await createClaudeService(
      { credentials: { resolve: async () => undefined } },
      { credentialsPath: "/nonexistent/creds.json", usageUrl: "https://api.anthropic.com/api/oauth/usage" },
    ).get(false);
    assert.equal(none.status, "no-key");
  } finally {
    globalThis.fetch = originalFetch;
    fsMod.rmSync(tmp, { recursive: true, force: true });
  }

  // Both windows absent → honest failure, never a fabricated number.
  assert.throws(() => parseClaudeUsage({}, AS_OF), /用量窗口/);
});

test("typert: the frozen artifacts carry the balance wire on both faces", () => {
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
  }
});

test("client: the header chip headlines one provider and the panel pins the rest", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });

  // DeepSeek low + MiniMax healthy: the pill headlines the FIRST row until a
  // panel click pins another one.
  const envelope = { providers: [DS_ROW_OK, MM_ROW_OK, CL_ROW_OK], refreshMs: 60000 };
  const remoteFace = { balance: async () => ({ ok: true, value: envelope }) };
  const ctx = {
    effect() {},
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
  const render = () => { reactStub._resetCursor(); return Chip({ sessionId: "s1", useStore: store.useStore, actions: store.actions, ...injected }); };

  // Collect chip item / panel rows separately via data-pb-role.
  const collect = (tree) => {
    const found = { chip: [], panel: [], openAttr: null, trigger: null, refresh: null, texts: [] };
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { found.texts.push(node); return; }
      const p = node.props || {};
      if (p["data-pb-role"] === "chip") found.chip.push(p);
      if (p["data-pb-role"] === "panel") found.panel.push(node);
      if (p["data-open"] !== undefined) found.openAttr = p["data-open"];
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
  assert.deepEqual(f.panel.map((n) => n.props["data-pb-provider"]), ["deepseek", "minimax", "claude"]);
  assert.ok(f.refresh, "the manual refresh lives in the panel header");

  // Open → click the minimax row → the pill re-headlines minimax (persisted).
  f.trigger.props.onClick();
  tree = render();
  f = collect(tree);
  assert.equal(f.openAttr, "true", "the panel opens from the trigger");
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

test("client: the panel says each provider's story once, abnormal rows loudest", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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
  const render = () => { reactStub._resetCursor(); return Chip({ sessionId: "s1", useStore: store.useStore, actions: store.actions, ...injected }); };

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
    "healthy windows stay ink-toned",
  );
  disposeReactEffects();

  // The bar colours by usage tier per window — yellow in the approach band
  // (60–79), red inside it (≥80 at the default watermark), green below.
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
  const render2 = () => { reactStub._resetCursor(); return __pb2.Component({ sessionId: "s2", useStore: store2.useStore, actions: store2.actions, ...__pb2.definition.inject("s2") }); };
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
  assert.equal(chipValueMid["data-used-level"], "mid", "the pill headline tints yellow in the approach band");
  disposeReactEffects();
});

test("client: _rowDisplay and _balanceNote project one provider's answer", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  const snap = (total, extra = {}) => ({ isAvailable: true, unit: "money", currency: "CNY", totalBalance: total, grantedBalance: "", toppedUpBalance: "", asOf: AS_OF, note: "", windows: [], ...extra });
  const answer = (over = {}) => ({ configured: true, snapshot: snap("110.00"), status: "fresh", low: false, message: null, threshold: 20, refreshMs: 60000, ...over });
  // Money rows keep the old shape; quota rows read as used percent and
  // surface the second window (周限额) as a muted pill suffix. Colour tiers
  // (level) follow the usage direction: green low, yellow near, red inside.
  assert.deepEqual(api._rowDisplay(null), { tone: "none", value: "—", sub: null, reset: null, level: null, title: "余额加载中" });
  const okRow = api._rowDisplay(answer());
  assert.equal(okRow.tone, "ok");
  assert.equal(okRow.level, null, "money rows have no usage tier — colour stays tonal");
  assert.equal(okRow.sub, null, "money rows carry no window suffix");
  assert.ok(!okRow.title.includes("更新于"), "the fetch timestamp must not repeat in the row");
  assert.match(api._rowDisplay(answer({ snapshot: snap("7.50", { currency: "USD" }) })).value, /^\$7\.5/);
  const pct = api._rowDisplay(answer({ snapshot: snap("76", { unit: "pct", currency: "" }) }));
  assert.equal(pct.value, "76%", "quota reads as percent, never money");
  assert.equal(pct.level, "mid", "76% used sits in the warning band (60–79 at the default watermark)");
  assert.equal(pct.sub, null, "a single-window plan has no suffix");
  const dual = api._rowDisplay(answer({
    snapshot: snap("76", {
      unit: "pct", currency: "",
      windows: [{ label: "5h", percent: 76, resetAt: "21:00" }, { label: "周", percent: 90, resetAt: "" }],
    }),
  }));
  assert.equal(dual.sub, "· 周 90%", "the weekly limit is the pill's second reading");
  const dualReset = api._rowDisplay(answer({
    snapshot: snap("76", {
      unit: "pct", currency: "",
      windows: [{ label: "5h", percent: 76, resetAt: "21:00" }, { label: "周", percent: 90, resetAt: "周四 21:00" }],
    }),
  }));
  assert.equal(dualReset.reset, "21:00", "the headline window's reset rides along for the chip");
  assert.equal(dualReset.sub, "· 周 90% ↻周四 21:00", "the weekly suffix carries its own reset");
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
  }));
  assert.equal(primaryGone.value, "31%", "when the headline window is absent the readable one steps up");
  assert.equal(primaryGone.level, "ok", "the stepped-up reading is tiered by its own number");
  assert.equal(api._rowDisplay(answer({ snapshot: snap("9.00", { isAvailable: false }) })).tone, "low");
  // Exhausted quota (kcn 反馈): no caption anywhere — the 100% reading and
  // the reset stamp are the message; money rows keep their sentence.
  const usedUp = api._rowDisplay(answer({
    snapshot: snap("100", {
      unit: "pct", currency: "", isAvailable: false,
      windows: [{ label: "5h", percent: 100, resetAt: "21:00" }, { label: "周", percent: 100, resetAt: "周四 21:00" }],
    }),
    low: true,
  }));
  assert.equal(usedUp.value, "100%", "an exhausted window reads as a plain 100% used");
  assert.ok(!usedUp.title.includes("已用尽"), "the exhausted caption is gone from the title");
  assert.equal(usedUp.reset, "21:00", "the reset stamp survives so the user knows when it frees up");
  assert.equal(usedUp.level, "low", "100% used tints red like any other inside-watermark reading");
  assert.equal(api._balanceNote(
    answer({ snapshot: snap("100", { unit: "pct", currency: "", isAvailable: false }), low: true }),
  ), null, "an exhausted quota row is silent — its bar and reset speak");
  assert.match(api._rowDisplay(answer({ snapshot: snap("9.00", { isAvailable: false }) })).title, /余额不足/, "money rows keep the official-insufficient sentence");
  // Healthy = silence. Every abnormal reading gets exactly one sentence.
  assert.equal(api._balanceNote(null), null);
  assert.equal(api._balanceNote(answer()), null);
  assert.match(api._balanceNote(answer({ snapshot: snap("5.00"), low: true })), /低于阈值 ¥20/);
  assert.match(api._balanceNote(answer({ status: "stale", message: "请求过于频繁" })), /刷新失败.*请求过于频繁/);
  assert.match(api._balanceNote({ configured: false, snapshot: null, status: "no-key", low: false, message: "未配置 DeepSeek API Key", threshold: 20, refreshMs: 60000 }), /未配置/);
  assert.match(api._balanceNote(answer({ snapshot: null, status: "failed", message: "网络请求失败" })), /网络请求失败/);
  assert.match(api._balanceNote(answer({ snapshot: snap("9.00", { isAvailable: false }) })), /余额不足/);
  assert.match(
    api._balanceNote(answer({ snapshot: snap("88", { unit: "pct", currency: "", isAvailable: true }), low: true })),
    /窗口已使用达 80%/,
    "quota lows speak in used percent (remaining watermark 20 flipped)",
  );
});

test("client: an exhausted quota row shows its 100% bars and resets instead of a caption", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
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
  const render = () => { reactStub._resetCursor(); return __pb.Component({ sessionId: "s1", useStore: store.useStore, actions: store.actions, ...__pb.definition.inject("s1") }); };

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



