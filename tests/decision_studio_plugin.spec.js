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
  return loaded;
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
        // Nine: the eight read methods plus queueAction, the task chip's one write door.
        assert.equal(descriptors.descriptors.length, 9);
        const queueDesc = descriptors.descriptors.find((d) => d.method === "taskQueue");
        assert.ok(queueDesc, "taskQueue descriptor present (hand-carried wire, see build.mjs)");
        assert.equal(queueDesc.parameters.length, 1, "taskQueue(force) must declare its argument");
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
  assert.equal(api._fmtMoney(-99.99, "HKD"), "HK$-99.99");
  assert.equal(api._fmtMoney(null, "USD"), "—");
  assert.equal(api._fmtPct(12.345), "+12.35%");
  assert.equal(api._fmtPct(0.5), "+0.50%");
  assert.equal(api._fmtPct(null), "—");
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
  const valueStale = idxOf(/_tq-value\[data-balance-state=stale\]/);
  const valueLow = idxOf(/_tq-value\[data-used-level=low\]/);
  assert.ok(valueStale > -1 && valueLow > -1 && valueStale > valueLow,
    "stale yellow must out-rank the reading cell's usage tiers in source order");
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
  assert.match(css, /\.[A-Za-z0-9_-]+_dmt,\s*\.[A-Za-z0-9_-]+_pbc\{[^}]*--fs-micro/,
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
  assert.match(css, /_dmt,\.[A-Za-z0-9_-]+_pbc\{[^}]*--glass-fill-popover/,
    "the glass recipe must resolve in both the tab and opened sidebar popovers");
  // The live DSH foot entry sits beside Settings: 42px row, 16px glyph at
  // x+8, 14/22 label; Cordis uses the same row geometry. Its material must
  // disappear completely until the anchored popover opens. Check the built
  // bundle, not only source text, so an overriding rule cannot fake this.
  const nativeFoot = css.match(/_pbc\.[A-Za-z0-9_-]+_pbf \.[A-Za-z0-9_-]+_bchip\{([^}]*)\}/)?.[1];
  assert.ok(nativeFoot, "the compiled sidebar-foot action rule must exist");
  for (const declaration of ["height:42px", "padding:0 10px 0 8px", "border:0",
    "backdrop-filter:none", "box-shadow:none", "font:400 var(--fs-lg)/22px var(--font)",
    "transform:none", "transition:none"]) {
    // transform:none belongs to :active, rather than the static rule.
    const rule = declaration === "transform:none"
      ? css.match(/_pbc\.[A-Za-z0-9_-]+_pbf \.[A-Za-z0-9_-]+_bchip:active\{([^}]*)\}/)?.[1]
      : nativeFoot;
    assert.ok(rule?.includes(declaration), `native foot action must compile ${declaration}`);
  }
  assert.match(nativeFoot, /background:(?:0 0|transparent)(?:;|$)/,
    "a closed foot action must not carry a translucent glass fill");
  assert.match(css, /_pbc\.[A-Za-z0-9_-]+_pbf \.[A-Za-z0-9_-]+_bchip:focus-visible\{outline:revert;outline-offset:revert\}/,
    "the foot action must inherit the same browser focus ring as Settings");
  assert.match(css, /_pbc\.[A-Za-z0-9_-]+_pbf\.[A-Za-z0-9_-]+_rail \.[A-Za-z0-9_-]+_bchip\{[^}]*width:36px;height:36px/,
    "collapsed foot actions must share the host's 36px rail target");
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
    /Refresh failed, showing the last reading: 429 too many requests/);
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
    assert.match(expired.message, /过期/);

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
    assert.equal(invocations.length, 9, rel);
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

test("client: the sidebar-foot provider cell lists every provider, opens on its group and stays open while you refresh", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });
  const LOW_DS = JSON.parse(JSON.stringify(DS_ROW_OK));
  LOW_DS.result.low = true;
  let forced = 0;
  let queueForced = 0;
  let emptyBalance = false;
  const remoteFace = {
    balance: async (force) => {
      if (force) forced += 1;
      return { ok: true, value: { providers: emptyBalance ? [] : [force ? LOW_DS : DS_ROW_OK, MM_ROW_OK], refreshMs: 60000 } };
    },
    // A host without the dispatcher (C3 ②): provider lines only, no empty queue.
    taskQueue: async (force) => { if (force) queueForced += 1; return { ok: true, value: { available: false, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0, running: 0, active: [], recent: [], patrol: { service: "unknown", phase: "unknown", round: "", detail: "", untilMs: null, rounds: [] } } }; },
  };
  const selected = [];
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    // DSH >= 0.1.5-rc.1. The foot must never drive panel navigation: selecting
    // a `main` panel swapped the whole conversation out from under the user.
    // `selectPanel` present is what routes the balance to the sidebar foot.
    layout: { selectPanel(id) { selected.push(id); } },
    slots: {
      inject(name, fn) { (this._seats ??= []).push(name); (this._fns ??= []).push(fn); },
      register(definition, Component) { (this._regs ??= []).push({ definition, Component }); },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  assert.deepEqual(ctx.slots._seats, ["conversation.view", "sidebar.footer.action"],
    "Decision Mind stays a conversation tab; balance + queue are ONE foot action — no `main` panel, no header chip");
  const action = ctx.slots._regs.find((r) => r.definition.id === "provider-balance");
  assert.equal(action.definition.name, "sidebar.footer.action");

  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const store = makeBalanceStoreStub();
  const face = action.definition.inject();
  const render = (wide = true) => {
    reactStub._resetCursor();
    return action.Component({ wide, t: translatorFor(api), useStore: store.useStore, actions: store.actions, ...face });
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
  const texts = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join(" ");
  };
  const lines = (tree) => find(tree, (p) => p["data-pp-row"] !== undefined);
  const popover = (tree) => find(tree, (p) => p["data-clawock-popover"] === api.BALANCE_PANEL)[0];
  const rail = (tree) => find(tree, (p) => p["data-clawock-action"] === api.BALANCE_PANEL && p["aria-haspopup"] === "dialog")[0];

  // Folded: one line per provider, in BALANCE_PROVIDERS order after the (absent) agents, each
  // naming itself first, then its reading. A provider without a queue has no state chip: where
  // its key lives is the plan on its group, the reset is on its window bars and in the label.
  render();
  await tick(); await tick(); await tick();
  let foot = render();
  assert.deepEqual(lines(foot).map((l) => l.props["data-pp-row"]), ["deepseek", "minimax"]);
  assert.equal(texts(lines(foot)[0]), "DeepSeek ¥110");
  assert.equal(texts(lines(foot)[1]), "MiniMax 24%", "resident: name and reading, nothing that needs a legend");
  assert.match(lines(foot)[1].props["aria-label"], /^MiniMax · 24% · ↻ 21:00 · /, "the headline window's reset is still read out");
  assert.equal(lines(foot)[0].props["data-balance-state"], "ok");
  assert.equal(lines(foot)[0].props["aria-expanded"], false);
  assert.equal(popover(foot).props["data-open"], "false");
  assert.match(texts(popover(foot)), /此主机没有派发队列；额度仍可查看/, "a missing dispatcher is named rather than silently omitted");
  // Closed means out of interaction, not merely transparent (React 18: `inert=""`, never `true`).
  assert.equal(popover(foot).props.inert, "", "a closed popover must be inert, not just transparent");
  const railTrigger = rail(render(false));
  assert.match(railTrigger.props.title, /DeepSeek ¥110/, "the rail keeps every reading in its title");
  assert.match(railTrigger.props["aria-label"], /MiniMax 24%/, "and reads it out");
  const railClasses = find(railTrigger, (p) => typeof p.className === "string").flatMap((node) => node.props.className.split(" "));
  assert.ok(railClasses.some((token) => token.endsWith("_bal-lead")), "the rail renders the glyph wrapper class");
  assert.ok(railClasses.some((token) => token.endsWith("_bal-glyph")), "the rail renders the gauge class");
  const statusBadge = (tree) => find(tree, (p) => typeof p.className === "string" && p.className.endsWith("_bal-badge"))[0];
  assert.equal(statusBadge(railTrigger), undefined, "nothing to act on: the rail stays neutral, no badge");
  assert.deepEqual(railClasses.filter((token) => token !== "" && !/^[A-Za-z0-9_-]+_[a-z0-9-]+$/.test(token)), [],
    "every rendered rail class must resolve through the stylesheet");

  // Open on MiniMax's line: the popover is part of the cell's own tree, one group per provider.
  lines(render())[1].props.onClick({ currentTarget: null });
  foot = render();
  assert.equal(lines(foot)[1].props["aria-expanded"], true);
  assert.equal(lines(foot)[1].props["data-active"], "", "the line that opened it stays marked");
  assert.equal(popover(foot).props["data-open"], "true");
  assert.equal(popover(foot).props.inert, undefined, "an open popover must be interactive");
  assert.deepEqual(find(popover(foot), (p) => p["data-pp-group"] !== undefined).map((g) => g.props["data-pp-group"]), ["deepseek", "minimax"]);
  assert.deepEqual(find(popover(foot), (p) => p["data-pb-role"] === "panel").map((r) => r.props["data-pb-provider"]), ["deepseek", "minimax"]);
  const ds = find(popover(foot), (p) => p["data-pp-group"] === "deepseek")[0];
  assert.match(texts(ds), /DeepSeek ¥110 本机 API 账户 赠金 ¥10.00 · 充值 ¥100.00/, "money: the amount on the head, its split under it, no bar (⑤)");
  assert.equal(find(ds, (p) => p["data-pp-provider"] === "deepseek").length, 1, "the source uses its whale glyph");
  assert.equal(find(ds, (p) => typeof p.className === "string" && p.className.endsWith("_bp-win-bar")).length, 0);
  assert.match(texts(find(popover(foot), (p) => p["data-pp-group"] === "minimax")[0]), /MiniMax 24% Token Plan · 源：OpenClaw 配置 .*5h 24% ↻ 21:00/);

  // One refresh forces both halves once, keeps the panel open and paints the low reading.
  find(popover(render()), (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick(); await tick();
  foot = render();
  assert.deepEqual([forced, queueForced], [1, 1], "one forced fetch per half");
  assert.equal(lines(foot)[0].props["data-balance-state"], "low", "the low reading shows right after the refresh");
  assert.equal(statusBadge(rail(render(false))).type, "rect", "low: a square badge, independent of its hue");
  assert.equal(popover(foot).props["data-open"], "true", "refreshing must not close the popover");

  emptyBalance = true;
  find(popover(foot), (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick(); await tick();
  foot = render();
  assert.match(texts(lines(foot)[0]), /没有可用的余额来源/, "a completed empty read must not claim it is still loading");
  assert.match(texts(popover(foot)), /没有可显示的额度或派发来源/);

  // The line (or an outside pointer / Escape, browser-only) closes it.
  lines(foot)[0].props.onClick({ currentTarget: null });
  assert.equal(popover(render()).props["data-open"], "false");
  assert.deepEqual(selected, [], "the foot never navigates the main column");
  disposeReactEffects();
});

test("client: a balance fetch that fails says so instead of loading forever (#1553)", async () => {
  // The RPC itself failing (transport down, remote error envelope) used to
  // clear the spinner and nothing else: a cold panel read 正在读取各服务余额…
  // for good, a warm one kept its old numbers with no word that they were old.
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });
  let answer = "down";
  const remoteFace = {
    balance: async () => {
      if (answer === "down") throw new Error("transport disconnected");
      if (answer === "error") return { ok: false, error: { code: "INTERNAL", message: "boom" } };
      return { ok: true, value: { providers: [DS_ROW_OK], refreshMs: 60000 } };
    },
    taskQueue: async () => ({ ok: true, value: { available: false, status: "fresh", message: null, asOf: "", refreshMs: 15000, maxRunning: 0, running: 0, active: [], recent: [], patrol: { service: "unknown", phase: "unknown", round: "", detail: "", untilMs: null, rounds: [] } } }),
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    layout: { selectPanel() {} },
    slots: {
      inject(name, fn) { (this._fns ??= []).push(fn); },
      register(definition, Component) { (this._regs ??= []).push({ definition, Component }); },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const action = ctx.slots._regs.find((r) => r.definition.id === "provider-balance");
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const store = makeBalanceStoreStub();
  const face = action.definition.inject();
  const render = () => {
    reactStub._resetCursor();
    return action.Component({ wide: true, t: translatorFor(api), useStore: store.useStore, actions: store.actions, ...face });
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
  const texts = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join(" ");
  };
  const popover = (tree) => find(tree, (p) => p["data-clawock-popover"] === api.BALANCE_PANEL)[0];
  const rail = () => { reactStub._resetCursor(); const tree = action.Component({ wide: false, t: translatorFor(api), useStore: store.useStore, actions: store.actions, ...face }); return find(tree, (p) => p["data-clawock-action"] === api.BALANCE_PANEL)[0]; };
  const line = (tree) => find(tree, (p) => p["data-pp-row"] !== undefined)[0];
  const refresh = async () => {
    find(popover(render()), (p) => p["data-refresh"] === "true")[0].props.onClick();
    await tick(); await tick(); await tick();
    return render();
  };

  // Cold, and the mount fetch fails: the panel names the failure, the foot
  // shows the hollow stale badge rather than "nothing to judge".
  render();
  await tick(); await tick(); await tick();
  let foot = render();
  assert.match(texts(popover(foot)), /余额读取失败:transport disconnected/);
  assert.doesNotMatch(texts(popover(foot)), /正在读取/);
  assert.equal(rail().props["data-balance-state"], "stale");
  const staleBadge = find(rail(), (p) => typeof p.className === "string" && p.className.endsWith("_bal-badge"))[0];
  assert.equal(staleBadge.type, "circle");
  assert.equal(staleBadge.props.r, 2.05, "stale keeps the smaller hollow badge geometry");
  assert.match(texts(line(foot)), /余额读取失败/, "the folded cell says so too, not a blank line");

  // A remote error envelope is a failure too.
  answer = "error";
  foot = await refresh();
  assert.match(texts(popover(foot)), /余额读取失败:clawockStudio\.balance failed: INTERNAL: boom/);

  // Recovered: rows back, the failure line gone.
  answer = "ok";
  foot = await refresh();
  assert.equal(line(foot).props["data-balance-state"], "ok");
  assert.doesNotMatch(texts(popover(foot)), /失败/);

  // Warm, then a refresh fails: the last numbers stay, labelled as the last ones.
  answer = "down";
  foot = await refresh();
  assert.match(texts(popover(foot)), /¥110/);
  // The two render sites used to spell this differently (`:` vs `: `); they
  // share one dictionary key now, so the tight form is gone on purpose.
  assert.match(texts(popover(foot)), /刷新失败,显示最近一次: transport disconnected/);
  disposeReactEffects();
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
  assert.equal(chipValueMid["data-used-level"], "mid", "the pill headline tints yellow in the approach band");
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
  assert.ok(redTexts.includes("88%") && redTexts.includes("95%"), "window percentages stay rendered");
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
  assert.ok(redTexts.includes("88%"), "the headline number itself stays");
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
  assert.deepEqual(api._rowDisplay(null, translatorFor(api)), { tone: "none", value: "—", sub: null, reset: null, level: null, title: "余额加载中" });
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

test("client: one provider cell carries the queue under each agent's provider and shows who waits for what", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });
  const now = Date.now();
  const QUEUE = {
    available: true, status: "fresh", message: null, asOf: AS_OF, refreshMs: 15000, maxRunning: 3, running: 2,
    slotLimits: [{ agent: "claude", max: 1 }, { agent: "codex", max: 1 }, { agent: "opencode", max: 1 }],
    active: [
      { id: "a-1", name: "patrol-source-sync", agent: "claude", model: "claude-opus-5-5", state: "running", waiting: "", slot: "claude-1",
        attempts: 2, stalls: 1, outcome: "", startedAtMs: now - 65 * 60000, updatedAtMs: now, wakeAtMs: null, patrol: false },
      { id: "b-1", name: "model-bump", agent: "claude", model: "claude-opus-5-5", state: "queued", waiting: "lock", slot: "",
        attempts: 0, outcome: "", startedAtMs: now - 60000, updatedAtMs: now, wakeAtMs: null, patrol: false },
      { id: "patrol-recent-1", name: "patrol-recent", agent: "opencode", model: "opencode/x", state: "running", waiting: "", slot: "opencode-1",
        attempts: 1, outcome: "", startedAtMs: now - 60000, updatedAtMs: now, wakeAtMs: null, patrol: true },
    ],
    recent: [{ id: "c-1", name: "merge-pr1767", agent: "codex", model: "gpt", state: "ok", waiting: "", slot: "", attempts: 1,
      outcome: "DONE", startedAtMs: now - 3600000, updatedAtMs: now - 30 * 60000, wakeAtMs: null, patrol: false }],
    patrol: { service: "active", phase: "yielding", round: "patrol-recent-1", detail: "preempting patrol-recent-1: b-1 is waiting for its agent lock",
      untilMs: null, rounds: [{ endedAt: "2026-09-23 03:55:00", round: "R139", axis: "automation", result: "preempted:cancelled", seconds: 4090 }] },
  };
  let forced = 0;
  let answer = QUEUE;
  const remoteFace = {
    balance: async () => ({ ok: true, value: QUIET_BALANCES }),
    taskQueue: async (force) => { if (force) forced += 1; return { ok: true, value: answer }; },
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    layout: { selectPanel() {} },
    slots: {
      inject(name, fn) { (this._seats ??= []).push(name); (this._fns ??= []).push(fn); },
      register(definition, Component) { (this._regs ??= []).push({ definition, Component }); },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const feet = ctx.slots._regs.filter((r) => r.definition.name === "sidebar.footer.action");
  // 2026-09-27: the balance and the queue are ONE cell. `provider-balance` is the container;
  // `dispatch-queue` is retired (it was a second cell stacked above, ordered -1).
  assert.deepEqual(feet.map((r) => r.definition.id), ["provider-balance"], "one foot cell, the provider panel");

  const face = feet[0].definition.inject();
  const t = translatorFor(api);
  const store = makeBalanceStoreStub();
  const render = (wide = true) => {
    reactStub._resetCursor();
    return feet[0].Component({ wide, t, useStore: store.useStore, actions: store.actions, ...face });
  };
  const tick = () => new Promise((resolve) => setImmediate(resolve));
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
  const texts = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join(" ");
  };
  assert.equal(find(render(), (p) => p["data-pp-row"] === "claude").length, 0, "no agent line before the queue answers");
  await tick(); await tick();
  const foot = render();
  // The fixture is an OLD host's answer (no queue fields, no ops, no queueAction): it must still
  // render, read-only. The new host's answer is exercised further down.
  const lines = find(foot, (p) => p["data-pp-row"] !== undefined);
  // Folded: one line per source, agents first (no balance providers answered here, C3 ②'s mirror).
  assert.deepEqual(lines.map((l) => l.props["data-pp-row"]), ["claude", "codex", "opencode"]);
  // The state column is ONE chip: the state that most needs the reader. b-1 queues for the claude
  // lock (its holder runs), so claude's chip is the amber queue; an idle agent has no chip at all.
  // No shapes that need a legend (the ▶ ≡ ⏸ column was the 260px stopgap this replaced).
  // Each chip is a ROLE (client.ts STATE_ROLES): its bed, glyph and word, not a grey level.
  const state = (key) => find(lines.find((l) => l.props["data-pp-row"] === key), (p) => p["data-tq-chip"] === "status")[0];
  assert.equal(texts(state("claude")), "排队 1");
  assert.deepEqual([state("claude").props["data-role"], state("claude").props["data-bed"]], ["queue", "edge"]);
  assert.equal(state("codex"), undefined, "idle: no chip, no grey word");
  assert.equal(texts(state("opencode")), "运行 1");
  assert.deepEqual([state("opencode").props["data-role"], state("opencode").props["data-bed"]], ["run", "fill"]);
  assert.doesNotMatch(texts(lines), /[▶≡⏸…]/);
  assert.match(lines[0].props["aria-label"], /^Claude Code .*排队 1 · 运行 1 .*打开 Claude Code 的额度与队列/, "each line still reads out every count");
  const classes = find(foot, (p) => typeof p.className === "string").flatMap((n) => n.props.className.split(" "));
  assert.deepEqual(classes.filter((c) => c !== "" && !/^[A-Za-z0-9_-]+_[a-z0-9-]+$/.test(c)), [],
    "every rendered class resolves through the stylesheet");

  lines[0].props.onClick({ currentTarget: null });
  const open = render();
  const popover = find(open, (p) => p["data-clawock-popover"] === api.BALANCE_PANEL)[0];
  assert.equal(popover.props["data-open"], "true");
  // Grouped by executor (each agent has its own lock, so each is its own queue), then ended, then patrol.
  assert.deepEqual(find(popover, (p) => p["data-tq-group"] !== undefined).map((g) => g.props["data-tq-group"]),
    ["claude", "codex", "opencode", "recent", "patrol"]);
  assert.match(texts(popover), /Claude Code .*槽 1\/1 .*Codex .*槽 0\/1 .*OpenCode .*槽 1\/1 .*最近结束 .*巡检/);
  assert.doesNotMatch(texts(popover), /没有任务/, "an idle group is its head alone, not a grey sentence");
  // A group's head IS its folded line (glyph · name · value), minus the state chip — the tasks it
  // counts are right below it on their well — plus its caption, in words (no chips).
  const heads = find(popover, (p) => p["data-pp-head"] !== undefined);
  const firstLine = (node) => (node.children || []).filter((c) => c && /_tq-(lead|name|value)$/.test(c.props.className || "")).map(texts).join(" ");
  for (const head of heads) {
    const line = lines.find((l) => l.props["data-pp-row"] === head.props["data-pp-head"]);
    assert.equal(firstLine(head), firstLine(line), `${head.props["data-pp-head"]}: the head repeats its folded line`);
    assert.equal(find(head, (p) => p["data-tq-chip"] !== undefined).length, 0, `${head.props["data-pp-head"]}: no chip on a source head`);
  }
  const slotsOf = (agent) => find(heads.find((h) => h.props["data-pp-head"] === agent), (p) => p.title === "运行槽按 agent 分:每个 agent 只用自己的槽,互不挤占;排队看各自那一格")[0];
  assert.deepEqual(["claude", "codex", "opencode"].map((a) => [texts(slotsOf(a)).replace(/^ · /, ""), slotsOf(a).props["data-voice"]]),
    [["槽 1/1", "warn"], ["槽 0/1", undefined], ["槽 1/1", undefined]],
    "claude's one slot is full and a claude task queues for it: that slot count is the queue's reason");
  // Two levels, never mixed: every task sits on a well under its source head, none on the panel.
  for (const group of find(popover, (p) => p["data-pp-group"] !== undefined)) {
    const wells = find(group, (p) => p["data-tq-well"] !== undefined);
    const tasks = find(group, (p) => p["data-tq-task"] !== undefined);
    assert.equal(tasks.length, wells.flatMap((w) => find(w, (p) => p["data-tq-task"] !== undefined)).length,
      `${group.props["data-pp-group"]}: its tasks are on its well`);
  }
  const rows = find(popover, (p) => p["data-tq-task"] !== undefined);
  assert.deepEqual(rows.map((r) => [r.props["data-tq-task"], r.props["data-tq-waiting"]]),
    [["a-1", ""], ["b-1", "lock"], ["patrol-recent-1", ""], ["c-1", ""]], "the holder first, then its queue, per agent");
  const chip = (node, slot) => find(node, (p) => p["data-tq-chip"] === slot)[0];
  const fact = (node, slot) => find(node, (p) => p["data-tq-fact"] === slot)[0];
  assert.equal(texts(chip(rows[0], "status")), "运行中");
  assert.equal(chip(rows[0], "status").props["data-role"], "run");
  assert.doesNotMatch(texts(rows[0]), /槽/, "one slot per agent: the group head already says whose");
  assert.match(texts(rows[0]), /运行中 Claude Opus 5\.5 第 2 次 · 卡死 1 (?:\d{1,2}\/\d{1,2} )?\d{2}:\d{2} 1 小时 5 分/,
    "the full model name, useful retry and stall numbers, then when it started and how long");
  assert.equal(fact(rows[0], "tries").props["data-voice"], "warn", "a stall is a warning, not a plain count");
  assert.match(fact(rows[0], "took").props.title, /^已跑 1 小时 5 分$/, "a bare figure in its cell, its words in the title");
  assert.equal(find(rows[0], (p) => p.className && /_tq-model-mark/.test(p.className)).length, 0, "no two-letter model tile");
  assert.equal(texts(chip(rows[2], "status")), "运行中", "slot-opencode-1: running in its own agent's slot");
  // The state chip is the short word; the whole phrase (whose lock) is its title.
  assert.equal(texts(chip(rows[1], "status")), "排队");
  assert.match(chip(rows[1], "status").props.title, /等 claude 锁/);
  assert.equal(chip(rows[1], "status").props["data-role"], "queue");
  // An ended task's ONE state folds the runner's verdict and the model's report; both are its title.
  assert.equal(texts(chip(rows[3], "status")), "完成");
  assert.equal(chip(rows[3], "status").props["data-role"], "done");
  assert.equal(chip(rows[3], "status").props.title, "执行完成 · 任务：完成");
  assert.equal(find(rows, (p) => p.className && /_tq-dot(?!-)/.test(p.className)).length, 0, "no row speaks through a dot: states are chips");
  assert.equal(find(rows[3], (p) => p["data-tq-agent"] === "codex").length, 1, "an ended row identifies its executor outside the provider groups");
  assert.equal(find(rows[0], (p) => p["data-tq-agent"] === "claude").length, 1, "a live task fills the shared lead track with its executor");
  // Every row is on the one grid: its facts are words in FACT_ORDER, and only the ones its kind lists.
  const factSlots = (node) => find(node, (p) => p["data-tq-fact"] !== undefined).map((c) => c.props["data-tq-fact"]);
  assert.deepEqual(factSlots(rows[3]), ["model", "when", "took"],
    "an ended task: model · when · took (the report axis and the first queue wait are in its detail layer)");
  assert.deepEqual(factSlots(rows[0]), ["model", "tries", "when", "took"]);
  const round = find(popover, (p) => p["data-tq-round"] === "R139")[0];
  assert.deepEqual(factSlots(round), ["when", "took"], "a round fills the same cells");
  assert.equal(find(round, (p) => p["data-tq-chip"] === "status")[0].props["data-role"], "partial");
  assert.match(texts(round), /R139 · automation 让路取消 .*1 小时 8 分/, "the last round is a readable record");
  assert.equal(round.type, "div", "a round opens nothing, so it is not a button");
  assert.equal(find(popover, (p) => p["data-tq-patrol"] !== undefined)[0].props["data-tq-patrol"], "yielding");
  const status = find(popover, (p) => p["data-tq-patrol"] !== undefined)[0];
  assert.deepEqual(find(status, (p) => p["data-tq-chip"] !== undefined).map((c) => [c.props["data-tq-chip"], texts(c), c.props["data-role"]]),
    [["status", "让路中", "wait"]], "the patrol head: its phase as its one chip");
  assert.equal(texts(find(status, (p) => /_tq-caption-line$/.test(p.className || ""))[0]), "让手工任务先行  · b-1  · 已跑 1 分",
    "then why it gives way and to whom, in words");
  // THE row grid (client.ts ROW_KINDS / FACT_ORDER / FACT_CELL): every row of the cell, folded or
  // open, is lead · name · value · state then its facts, a kind draws only what ROW_KINDS gives
  // it, each fact has its own cell, and no row carries more than RESIDENT_CHIPS chips.
  const { ROW_KINDS, FACT_ORDER, FACT_CELL, RESIDENT_CHIPS } = api;
  assert.equal(RESIDENT_CHIPS, 1);
  for (const [kind, spec] of Object.entries(ROW_KINDS)) {
    const cellsOf = spec.facts.map((slot) => `${FACT_CELL[slot].line}/${FACT_CELL[slot].track}`);
    assert.equal(new Set(cellsOf).size, cellsOf.length, `${kind}: no two of its facts share a cell`);
  }
  assert.deepEqual(Object.fromEntries(Object.entries(ROW_KINDS).map(([kind, spec]) => [kind, spec.lead])),
    { source: true, head: true, task: true, ended: true, round: true },
    "every row kind fills the common lead track; no empty 14px stripe");
  for (const [kind, spec] of Object.entries(ROW_KINDS)) {
    const at = spec.facts.map((slot) => FACT_ORDER.indexOf(slot));
    assert.ok(at.every((i, n) => i >= 0 && (n === 0 || i > at[n - 1])), `${kind}: its facts are a run of FACT_ORDER, in order`);
  }
  const gridRows = [...lines, ...find(popover, (p) => p["data-tq-row"] !== undefined)];
  assert.deepEqual([...new Set(gridRows.map((r) => r.props["data-tq-row"]))].sort(), Object.keys(ROW_KINDS).sort(),
    "this fixture renders every row kind");
  const cellName = (node) => /_(tq-[a-z-]+)$/.exec(node.props.className || "")?.[1];
  for (const row of gridRows) {
    const kind = row.props["data-tq-row"];
    const spec = ROW_KINDS[kind];
    const cells = (row.children || []).filter((c) => c && typeof c === "object");
    const order = cells.map((c) => c.props["data-tq-chip"] === "status" ? "state" : ({ "tq-lead": "lead", "tq-name": "main", "tq-value": "value", "tq-fact": "facts", "tq-caption-line": "caption" })[cellName(c)]);
    assert.ok(order.every(Boolean), `${kind}: nothing but grid cells (${cells.map(cellName)})`);
    const columns = ["lead", "main", "value", "state", "facts", "caption"];
    assert.deepEqual(order.filter((c, i) => order.indexOf(c) === i), columns.filter((c) => order.includes(c)), `${kind}: cells in column order`);
    assert.ok(find(row, (p) => p["data-tq-chip"] !== undefined).length <= RESIDENT_CHIPS, `${kind}: at most one chip`);
    assert.deepEqual(order.slice(0, 2), ["lead", "main"], `${kind}: the lead column is always there, so every name starts on one edge`);
    assert.equal(order.includes("value"), spec.value && order.includes("value"), `${kind}: a value only where the kind has one`);
    if (spec.lead) assert.ok((cells[0].children || []).filter(Boolean).length > 0, `${kind}: its lead carries a glyph`);
    else assert.equal((cells[0].children || []).filter(Boolean).length, 0, `${kind}: no glyph in the lead track`);
    const facts = cells.filter((c) => cellName(c) === "tq-fact").map((c) => c.props["data-tq-fact"]);
    assert.ok(facts.every((slot) => spec.facts.includes(slot)), `${kind}: only its own facts (${facts})`);
    assert.deepEqual(facts, [...facts].sort((a, b) => FACT_ORDER.indexOf(a) - FACT_ORDER.indexOf(b)), `${kind}: facts in FACT_ORDER`);
  }
  assert.equal(find(popover, (p) => p["data-tq-up"] !== undefined).length, 0, "an old host offers no reordering");

  // Clicking a task opens its detail layer over the (now inert) list, in the same popover.
  assert.equal(find(popover, (p) => p["data-tq-detail"] !== undefined).length, 0, "no layer until a task is picked");
  rows[1].props.onClick();
  let layered = render();
  const detail = find(layered, (p) => p["data-tq-detail"] !== undefined)[0];
  assert.equal(detail.props["data-tq-detail"], "b-1");
  assert.equal(find(layered, (p) => p["data-clawock-popover"] === api.BALANCE_PANEL)[0].props["data-open"], "true",
    "the layer lives inside the open popover — no second surface");
  assert.equal(find(layered, (p) => p.inert === "" && p["aria-hidden"] === "true").length, 1, "the list underneath is inert");
  assert.match(texts(detail), /进行中 model-bump 排队 等 claude 锁 .*模型 Claude Opus 5\.5 .*Agent Claude Code .*已运行 1 分 .*尝试次数 0 .*任务 ID b-1/,
    "the hero (name, the row's chip, the whole sentence), then the sections in DETAIL_SECTIONS order");
  assert.doesNotMatch(texts(detail), /判卡死/, "no stall row when there was none");
  assertDetailOrder(api, detail, "live");
  const heroChip = find(find(detail, (p) => p["data-tq-section"] === "status")[0], (p) => p["data-tq-chip"] === "status")[0];
  assert.deepEqual([texts(heroChip), heroChip.props["data-role"]], [texts(chip(rows[1], "status")), chip(rows[1], "status").props["data-role"]],
    "the hero carries the very chip the list row had");
  assert.equal(find(detail, (p) => /_tq-dot(?!-)/.test(p.className || "")).length, 0, "no dot repeating the chip");
  // Without the write door, only file-preview reads remain.
  assert.deepEqual(find(detail, (p) => p["data-tq-action"] !== undefined).map((n) => n.props["data-tq-action"]), ["brief", "raw-log"],
    "no write actions without the host's write door");
  // Back returns to the list; so does Escape (tested through the same back function).
  find(detail, (p) => p["data-tq-back"] === "true")[0].props.onClick();
  layered = render();
  assert.equal(find(layered, (p) => p["data-tq-detail"] !== undefined).length, 0, "back closes the layer");
  assert.equal(find(layered, (p) => p["data-clawock-popover"] === api.BALANCE_PANEL)[0].props["data-open"], "true",
    "and leaves the popover open on the list");
  // An ended task shows how it closed: took, ended, and the agent's closing report.
  answer = { ...QUEUE, recent: [{ ...QUEUE.recent[0], summary: "- merged: PR #1767\n- CI green" }] };
  find(layered, (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick();
  find(render(), (p) => p["data-tq-task"] === "c-1")[0].props.onClick();
  const ended = find(render(), (p) => p["data-tq-detail"] === "c-1")[0];
  assert.match(texts(ended), /已结束 merge-pr1767 完成 执行完成 · 任务：完成 结果摘要 - merged: PR #1767\n- CI green .*用时 30 分 .*结束 .*30 分钟前/,
    "an ended task: its verdict on both axes, then what it reported, before how it ran");
  assertDetailOrder(api, ended, "ended");
  assert.doesNotMatch(texts(ended), /最近事件/, "an ended task has no latest event row");
  const panelClasses = find(render(), (p) => typeof p.className === "string").flatMap((n) => n.props.className.split(" "));
  assert.deepEqual(panelClasses.filter((c) => c !== "" && !/^[A-Za-z0-9_-]+_[a-z0-9-]+$/.test(c)), [],
    "every class the open panel and its detail layer render resolves through the stylesheet");
  find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  answer = { ...QUEUE, recent: [
    { ...QUEUE.recent[0], id: "closed-a", state: "ok", outcome: "PARTIAL", waitMs: 7 * 60000,
      notify: ["weixin", "telegram"], notified: ["telegram"], notifyFailed: ["weixin"] },
    { ...QUEUE.recent[0], id: "closed-b", state: "failed", outcome: "DONE", waitMs: null, notify: ["weixin"] },
    { ...QUEUE.recent[0], id: "closed-c", state: "blocked", outcome: "BLOCKED" },
  ] };
  find(render(), (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick();
  const receipts = find(render(), (p) => p["data-tq-task"]?.startsWith("closed-"));
  assert.deepEqual(receipts.map((row) => row.props["data-tq-task"]), ["closed-a", "closed-b", "closed-c"],
    "ended tasks keep the host's newest-first order across agents");
  const verdict = (row) => { const c = find(row, (p) => p["data-tq-chip"] === "status")[0]; return [texts(c), c.props["data-role"], c.props.title]; };
  assert.deepEqual(receipts.map(verdict), [
    ["部分完成", "partial", "执行完成 · 任务：部分完成"],
    ["失败", "fail", "执行失败 · 任务：自报完成"],
    ["受阻", "partial", "执行受阻 · 任务：受阻"],
  ], "one state per ended task; the chip's title keeps both axes (the runner's verdict, then the model's report)");
  // Receipts: per channel, from result.env alone — delivered, failed, or no receipt at all (never
  // "delivered" by inference). Each mark says it in its glyph and words, not only its colour.
  const marks = (row) => find(row, (p) => p["data-tq-notify"] !== undefined).map((m) => [m.props["data-tq-notify"], m.props["data-state"]]);
  assert.deepEqual(receipts.map(marks), [[["weixin", "failed"], ["telegram", "sent"]], [["weixin", "unknown"]], []]);
  assert.equal(find(receipts[1], (p) => p.role === "img")[0].props["aria-label"], "微信 无回执");
  assert.equal(find(receipts[0], (p) => p["data-tq-fact"] === "receipt").length, 1, "receipts have their one cell");
  // The first queue wait is not resident (ROW_KINDS.ended): it is one tap away, recorded or not.
  assert.doesNotMatch(texts(receipts), /首次排队|排队耗时未记录/);
  for (const [id, said] of [["closed-a", /首次排队 7 分/], ["closed-b", /排队耗时未记录/]]) {
    find(render(), (p) => p["data-tq-task"] === id)[0].props.onClick();
    assert.match(texts(find(render(), (p) => p["data-tq-detail"] === id)[0]), said);
    find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  }

  // Distinct ended tasks stay visible; only long patrol history folds, as one group.
  const endedTask = (i) => ({ ...QUEUE.recent[0], id: "e-" + i, name: "ended-" + i, updatedAtMs: now - (i + 1) * 60000 });
  const rounds = [0, 1, 2, 3, 4].map((i) => ({ endedAt: `2026-09-23 0${5 - i}:00:00`, round: "R" + (140 - i), axis: "logic", result: "ok/DONE", seconds: 600 }));
  // What the newest round routed through the filing gate (patrol.sh's third `/` field): line 2.
  rounds[0].result = "ok/DONE/P1#2240 +2 digest +1 comment";
  answer = { ...QUEUE, recent: [0, 1, 2, 3, 4].map(endedTask), patrol: { ...QUEUE.patrol, rounds } };
  find(render(), (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick();
  const panel = render();
  const section = (key) => find(panel, (p) => p["data-tq-group"] === key)[0];
  const folds = (node) => find(node, (p) => p["data-tq-fold"] !== undefined);
  assert.equal(find(section("recent"), (p) => p["data-tq-task"] !== undefined).length, 5, "every ended task the host sends is on screen");
  assert.equal(folds(section("recent")).length, 0, "no ended task hides behind a fold");
  const patrolFolds = folds(section("patrol"));
  assert.deepEqual(patrolFolds.map((f) => f.props["data-tq-fold"]), ["rounds"]);
  assert.deepEqual(find(patrolFolds[0], (p) => p["data-tq-round"] !== undefined).map((r) => r.props["data-tq-round"]), ["R139", "R138", "R137", "R136"],
    "the earlier rounds fold");
  assert.equal(find(section("patrol"), (p) => p["data-tq-round"] === "R140").length, 1);
  assert.equal(find(patrolFolds[0], (p) => p["data-tq-round"] === "R140").length, 0, "the newest round stays resident");
  const newest = find(section("patrol"), (p) => p["data-tq-round"] === "R140")[0];
  assert.deepEqual(factSlots(newest), ["filed", "when", "took"], "a round that filed says so on line 2");
  assert.equal(texts(find(newest, (p) => p["data-tq-fact"] === "filed")[0]).replace(/ +/g, " "), "提报 1 · P1 #2240 · 汇总 +2 · 补充 1");
  const issueLink = find(newest, (p) => p.href !== undefined)[0];
  assert.equal(issueLink.type, "a", "filing evidence has an exit to the actual finding");
  assert.equal(issueLink.props.href, "https://github.com/KCNyu/clawock/issues/2240");
  assert.match(issueLink.props["aria-label"], /P1 #2240/);
  assert.equal(find(newest, (p) => p["data-severity"] === "P1").length, 1, "severity is text and a paint role");
  assert.equal(find(newest, (p) => p["data-tq-chip"] === "status")[0].props["data-role"], "done", "the filed field is not part of the state");
  assert.doesNotMatch(texts(section("patrol")), /preempting patrol-recent-1/, "raw supervisor output is not a task conclusion");
  for (const fold of patrolFolds) {
    const summary = fold.children.find((c) => c && c.type === "summary");
    assert.ok(summary && /_tq-fold-summary/.test(summary.props.className), "a fold opens from its own summary control");
  }

  // Boundary cases, including mixed outcomes: never split into count/state chunks.
  for (const count of [0, 1, 2, 3, 4, 5, 6]) {
    const history = Array.from({ length: count }, (_, i) => ({ ...rounds[i % rounds.length], round: 'B' + i,
      result: i % 2 === 0 ? 'ok/DONE' : 'failed/BLOCKED' }));
    answer = { ...answer, patrol: { ...answer.patrol, rounds: history } };
    find(render(), (p) => p["data-refresh"] === "true")[0].props.onClick();
    await tick(); await tick();
    const patrol = find(render(), (p) => p["data-tq-group"] === "patrol")[0];
    const disclosures = folds(patrol);
    assert.equal(disclosures.length, count <= 4 ? 0 : 1, `${count} rounds: only long history folds`);
    assert.deepEqual(find(patrol, (p) => p["data-tq-round"] !== undefined).map((r) => r.props["data-tq-round"]), history.map(r => r.round));
    if (count > 4) assert.equal(find(disclosures[0], (p) => p["data-tq-round"] !== undefined).length, count - 1);
  }

  // #2053: a cold IN-BAND failure (status 'failed': nothing was ever read) is a read failure,
  // not "showing the last read" — the same judgement the balance half makes on its rows.
  answer = { available: false, status: "failed", message: "EACCES: permission denied", asOf: "", refreshMs: 15000, maxRunning: 0,
    running: 0, active: [], recent: [], slotLimits: [], queues: [], patrol: { service: "unknown", phase: "unknown", round: "", detail: "", untilMs: null, rounds: [] } };
  find(render(), (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick();
  assert.match(texts(render()), /任务队列读取失败:EACCES: permission denied/);
  assert.doesNotMatch(texts(render()), /显示最近一次/, "nothing was read, so nothing 'last' is shown");
  answer = QUEUE;

  // The host renders list-slot items inside a `display:contents` [data-slot]
  // wrapper, so the flex row to turn into a column is the wrapper's parent.
  const bundle = fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8");
  assert.match(bundle, /:has\(>\[data-slot\]>\.\w+_pbc\.\w+_tqf\)\{flex-direction:column\}/,
    "the foot stacks through the host's slot wrapper, not only a direct child");

  const forcedBefore = forced;
  find(popover, (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick();
  assert.equal(forced, forcedBefore + 1, "the refresh button forces one host read");

  // A host without the dispatcher answers available:false: the agent lines go, nothing blank
  // is left behind (C3 ②) — the providers (none here) are what remains.
  answer = { ...QUEUE, available: false, active: [], recent: [] };
  find(popover, (p) => p["data-refresh"] === "true")[0].props.onClick();
  await tick(); await tick();
  assert.equal(find(render(), (p) => p["data-pp-row"] !== undefined && p["data-pp-row"] !== "").length, 0);
  disposeReactEffects();
});

// #2071: the give-way label was matched against a sentence the supervisor never writes. The
// reasons below are instantiated from the templates as they stand in the two files that write
// them (the test fails if a template changes), in each of the log shapes patrol.sh writes.
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

test("client: the queue can be steered in place — move up, two-step cancel, model for the next attempt", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });
  const now = Date.now();
  const live = (id, extra) => ({ id, name: id, agent: "claude", model: "claude-opus-5-5", state: "running", waiting: "", slot: "",
    attempts: 0, outcome: "", startedAtMs: now - 60000, updatedAtMs: now, wakeAtMs: null, patrol: false, summary: "", lastEvent: "",
    lastEventAtMs: null, runnerApi: 2, modelRequested: "claude-opus-5-5", effortRequested: "high",
    notify: ["weixin", "telegram"], notified: [], notifyFailed: [], session: "", ...extra });
  const QUEUE = {
    available: true, status: "fresh", message: null, asOf: AS_OF, refreshMs: 15000, maxRunning: 3, running: 1,
    slotLimits: [{ agent: "claude", max: 1 }],
    active: [
      live("holder", { slot: "claude-1", attempts: 1, session: "s-1", modelUsed: "claude-sonnet-5", effortUsed: "high" }),
      live("first", { waiting: "lock", position: 1 }),
      live("second", { waiting: "lock", position: 2, notifyFailed: ["weixin"] }),
    ],
    recent: [],
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
    queues: [{ agent: "claude", held: true, holder: "holder", order: ["first", "second"], quotaUntilMs: null, quotaBy: "" }],
    ops: { available: true, version: "abc123abc123", repoVersion: "def456def456", api: 2, runnerApi: 2, fairWaitSec: 14400, error: "" },
  };
  const calls = [];
  let holdChoices = false;
  let resolveChoices;
  const runQueueAction = async (action, id, arg) => {
    calls.push([action, id, arg]);
    if (action === "choices") {
      if (holdChoices) return new Promise((resolve) => { resolveChoices = resolve; });
      return { ok: true, code: 0, action, id, message: "", detail: JSON.stringify({ ok: true, allowed: true, reason: "",
        models: ["claude-opus-5-5", "sonnet"], efforts: { "claude-opus-5-5": ["low", "high"], sonnet: ["low", "high"] },
        effort_flag: "--effort", requested: { model: "claude-opus-5-5", effort: "high" } }) };
    }
    const detail = action === "priority" ? { ok: true, changed: true, position: 1, queue: ["second", "first"] }
      : action === "model" ? { ok: true, model_next: "sonnet", effort_next: "low" }
        : { ok: true, was: "running", session: "s-1", resume: "cd /root && claude --resume s-1" };
    return { ok: true, code: 0, action, id, message: "", detail: JSON.stringify(detail) };
  };
  const t = translatorFor(api);
  const store = makeBalanceStoreStub();
  const opened = [];
  const props = { wide: true, t, cachedTaskQueue: () => QUEUE, fetchTaskQueue: async () => QUEUE, runQueueAction,
    ...balanceProps(), useStore: store.useStore, actions: store.actions,
    openFile: (path) => { opened.push(path); return { ok: true }; } };
  const render = () => { reactStub._resetCursor(); return api.ProviderPanelSidebarAction(props); };
  const tick = () => new Promise((resolve) => setImmediate(resolve));
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
  const texts = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join(" ");
  };
  find(render(), (p) => p["data-pp-row"] === "claude")[0].props.onClick({ currentTarget: null });
  let tree = render();
  // Move up: only a reorderable waiter that is not already first.
  const ups = find(tree, (p) => p["data-tq-up"] !== undefined);
  assert.deepEqual(ups.map((b) => b.props["data-tq-up"]), ["second"]);
  assert.match(texts(tree), /Sonnet 5 · high/, "a running task shows the model it actually runs on");
  const second = find(tree, (p) => p["data-tq-task"] === "second")[0];
  const secondState = find(second, (p) => p["data-tq-chip"] === "status")[0];
  assert.equal(texts(secondState), "排队 #2", "the chip says the place in line");
  assert.equal(secondState.props.title, "等 claude 锁 · 第 2 位", "and its title the whole phrase");
  assert.match(texts(tree), /ops 入口与仓库不一致（主机 abc123abc123 \/ 仓库 def456def456）/, "version skew is visible");
  // A live row carries no receipt (its closing notification is not sent yet); the receipt of a
  // notice it already sent (a quota wait's) is in its detail layer, failed legs marked as failed.
  assert.equal(find(second, (p) => p["data-tq-notify"] !== undefined).length, 0, "no receipt on a live row");
  second.props.onClick();
  const secondDetail = find(render(), (p) => p["data-tq-detail"] === "second")[0];
  assert.equal(find(secondDetail, (p) => p["data-tq-notify"] === "weixin" && p["data-state"] === "failed").length, 1,
    "the failed leg is marked in the detail layer");
  assert.match(texts(secondDetail), /微信 失败/);
  find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  tree = render();
  ups[0].props.onClick();
  await tick(); await tick();
  assert.deepEqual(calls.at(-1), ["priority", "second", "up"]);
  assert.match(texts(render()), /现在排第 1 位（共 2）/, "the answer says where it landed");

  // Cancel a running task: the first tap only explains what it costs; the second one cancels.
  find(render(), (p) => p["data-tq-task"] === "holder")[0].props.onClick();
  tree = render();
  const cancel = () => find(render(), (p) => p["data-tq-action"] === "cancel")[0];
  assert.ok(find(tree, (p) => p["data-tq-action"] === "wrapup").length === 1, "a running task with a session can be wrapped up");
  assert.equal(find(tree, (p) => p["data-tq-action"] === "top").length, 0, "a running task is not reordered");
  const before = calls.length;
  cancel().props.onClick();
  assert.equal(calls.length, before, "one tap never cancels");
  assert.match(texts(render()), /它正在跑：本轮进度会丢；会话 s-1 可用 --resume 续/);
  assert.match(texts(cancel()), /确认取消/);
  cancel().props.onClick();
  await tick(); await tick();
  assert.deepEqual(calls.at(-1), ["cancel", "holder", ""]);
  assert.match(texts(render()), /已停止，本轮进度已丢；续跑：cd \/root && claude --resume s-1/, "the session to resume is reported");

  // Model: offered from the entry's own choices, saved for the next attempt.
  find(render(), (p) => p["data-tq-action"] === "model")[0].props.onClick();
  await tick(); await tick();
  const picker = find(render(), (p) => p["data-tq-picker"] !== undefined)[0];
  assert.match(texts(picker), /Opus 5\.5 \(claude-opus-5-5\) .*Sonnet \(sonnet\) .*下一次尝试生效/);
  find(picker, (p) => typeof p.onChange === "function")[0].props.onChange({ target: { value: "sonnet" } });
  find(render(), (p) => typeof p.onChange === "function")[1].props.onChange({ target: { value: "low" } });
  find(render(), (p) => p["data-tq-action"] === "save")[0].props.onClick();
  await tick(); await tick();
  assert.deepEqual(calls.at(-1), ["model", "holder", "sonnet|low"]);
  assert.match(texts(render()), /下一次尝试：sonnet · low/);

  // A confirmation has an explicit way out; Escape follows the same first step.
  cancel().props.onClick();
  assert.ok(find(render(), (p) => p["data-tq-action"] === "dismiss-confirm").length);
  const countBeforeKeep = calls.length;
  find(render(), (p) => p["data-tq-action"] === "dismiss-confirm")[0].props.onClick();
  assert.equal(calls.length, countBeforeKeep);
  assert.equal(find(render(), (p) => p["data-tq-confirm"] === "holder").length, 0);

  // A slow choices reply from a task left behind must not become the next task's picker.
  find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  find(render(), (p) => p["data-tq-task"] === "second")[0].props.onClick();
  holdChoices = true;
  find(render(), (p) => p["data-tq-action"] === "model")[0].props.onClick();
  assert.match(texts(find(render(), (p) => p["data-tq-action"] === "model")[0]), /读取中/);
  find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  find(render(), (p) => p["data-tq-task"] === "holder")[0].props.onClick();
  resolveChoices({ ok: true, detail: JSON.stringify({ allowed: true, models: ["sonnet"], requested: { model: "sonnet" } }) });
  await tick(); await tick();
  assert.equal(find(render(), (p) => p["data-tq-picker"] !== undefined).length, 0);
  disposeReactEffects();
});

test("client: the provider panel keeps both clocks, the pool position, stale readings, cost, the brief and the budgets", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });
  const t = translatorFor(api);
  const now = new Date(2026, 8, 26, 22, 0, 0).getTime();
  const at = (h, m) => new Date(2026, 8, 26, h, m, 0).getTime();
  // ③ the runner's wake and the window's reset are two facts, both shown.
  const sleeping = { id: "s", name: "s", agent: "claude", model: "m", state: "running", waiting: "quota", slot: "", attempts: 1, outcome: "",
    startedAtMs: now, updatedAtMs: now, wakeAtMs: at(23, 22), patrol: false };
  assert.equal(api._taskStatus(sleeping, t, now, [{ resetAtMs: at(23, 19) }, { resetAtMs: at(23, 19) + 86400000 * 2 }]).text,
    "等到 今天 23:22（窗口 今天 23:19 +3m 缓冲）");
  assert.equal(api._taskStatus(sleeping, t, now, []).text, "等到 今天 23:22（窗口重置时刻未读到）", "never one clock standing in for the other");
  assert.match(api._taskStatus(sleeping, t, now).text, /等额度 · 今天 23:22 续跑/, "no provider windows known: the runner's own clock only");

  // Scarce paid sources first, unknown costs next, then the interchangeable free pool.
  const prov = (id, label) => ({ provider: id, label, result: DS_ROW_OK.result });
  const queue = { available: true, active: [{ agent: "gemini" }], slotLimits: [{ agent: "claude", max: 1 }] };
  assert.deepEqual(api._panelSources([prov("deepseek", "DeepSeek"), prov("minimax", "MiniMax"), prov("claude", "Claude"), prov("codex", "Codex"), prov("zeta", "Zeta")], queue)
    .map((src) => [src.key, src.agent]),
  [["claude", "claude"], ["codex", "codex"], ["deepseek", null], ["minimax", null], ["gemini", "gemini"], ["zeta", null], ["opencode", "opencode"]]);
  assert.deepEqual(api._panelSources([prov("deepseek", "DeepSeek"), prov("claude", "Claude")], { available: false, active: [] })
    .map((src) => [src.key, src.agent]), [["claude", null], ["deepseek", null]], "② no dispatcher: providers only, no empty queues");

  // ④ the pool: the position comes from MODEL_USED, else the file order says so.
  const pooled = (tasks) => ({ opencodePool: ["opencode/a-free", "opencode/b-free", "opencode/c-free"], active: tasks, recent: [] });
  assert.deepEqual(api._poolPosition(pooled([{ agent: "opencode", modelUsed: "opencode/b-free", attempts: 1 }])),
    { current: "opencode/b-free", next: "opencode/c-free", fromOrder: false });
  assert.deepEqual(api._poolPosition(pooled([])), { current: "opencode/a-free", next: "opencode/b-free", fromOrder: true });
  assert.equal(api._poolPosition({ active: [], recent: [] }), null, "no pool file, no task: nothing invented");

  // Cost: an estimate, free, or a dash — never a guess.
  assert.deepEqual(api._costOf({ tokensTotal: 10, costUsd: "3.12" }), { short: "$3.12", kind: "usd" });
  assert.deepEqual(api._costOf({ tokensTotal: 10, costUsd: "free" }), { short: "free", kind: "free" });
  assert.deepEqual(api._costOf({ tokensTotal: 10, costUsd: "" }), { short: "—", kind: "unpriced" });
  assert.equal(api._costOf({ costUsd: "" }), null, "nothing recorded: no cost cell");
  assert.equal(api._fmtTokens(83123861), "83.1M");
  assert.equal(api._sessionFileAddress("s1", "/root/logs/agent-dispatch/x y/prompt.md"),
    "dsh-resource://file/session/s1//root/logs/agent-dispatch/x%20y/prompt.md", "dsh-util-workspace-path's session grammar");

  // The panel itself: ① a stale provider keeps its last reading and says when it was taken.
  const STALE_CL = JSON.parse(JSON.stringify(CL_ROW_OK));
  Object.assign(STALE_CL.result, { status: "stale", message: "429 Too Many Requests" });
  const task = (id, extra) => ({ id, name: id, agent: "claude", model: "claude-opus-5-5", state: "running", waiting: "", slot: "",
    attempts: 1, outcome: "", startedAtMs: Date.now() - 60000, updatedAtMs: Date.now(), wakeAtMs: null, patrol: false, summary: "",
    lastEvent: "", lastEventAtMs: null, runnerApi: 3, modelRequested: "claude-opus-5-5", effortRequested: "high", session: "s-1", ...extra });
  const QUEUE = {
    available: true, status: "fresh", message: null, asOf: AS_OF, refreshMs: 15000, maxRunning: 3, running: 1,
    slotLimits: [{ agent: "claude", max: 1 }, { agent: "opencode", max: 1 }], opencodePool: ["opencode/a-free", "opencode/b-free"],
    active: [task("new-run", { slot: "claude-1", maxAttempts: 3, quotaResumes: 3, quotaResumesUsed: 0, deadlineAtMs: Date.now() + 3600000,
      tokensIn: 10, tokensCacheW: 1000, tokensCacheR: 100000, tokensOut: 500, tokensTotal: 101510, costUsd: "0.04" }),
    task("old-wait", { waiting: "lock", position: 1, runnerApi: 2, attempts: 0 })],
    recent: [task("done", { state: "ok", outcome: "DONE", tokensTotal: 5, costUsd: "free", agent: "opencode" })],
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: null, rounds: [] },
    queues: [{ agent: "claude", held: true, holder: "new-run", order: ["old-wait"], quotaUntilMs: null, quotaBy: "" }],
    ops: { available: true, version: "v", repoVersion: "v", api: 3, runnerApi: 3, fairWaitSec: 14400, error: "" },
    // The host's own dispatch directory, any account's home (#2065: never a literal /root).
    logDir: "/home/someone/logs/agent-dispatch/",
  };
  const calls = [];
  let hostKnows = false;
  let briefFailure = false;
  let deferLog = false;
  let resolveLog;
  const runQueueAction = async (action, id, arg) => {
    calls.push([action, id, arg]);
    if (action === "brief") {
      if (briefFailure) return { ok: false, code: 1, action, id, message: "permission denied", detail: "" };
      return hostKnows
        ? { ok: true, code: 0, action, id, message: "", detail: JSON.stringify({ ok: true, path: "/tasks/" + id + "/prompt.md", brief_bytes: 70000, truncated: true,
          appends: [{ file: "20260927-010000-1-queue.md", path: "/tasks/" + id + "/inbox/delivered/20260927-010000-1-queue.md", stamp: "2026-09-27 01:00:00", delivered: true, bytes: 12, text: "# 缩小范围\n只修 handler" },
            { file: "20260927-020000-2-now.md", path: "/tasks/" + id + "/inbox/20260927-020000-2-now.md", stamp: "2026-09-27 02:00:00", delivered: false, bytes: 13, text: "修正验收依据" }] }) }
        : { ok: false, code: 2, action, id, message: 'unknown action "brief"', detail: "" };
    }
    if (action === "log" && deferLog) return new Promise((resolve) => { resolveLog = resolve; });
    if (action === "log") return { ok: true, code: 0, action, id, message: "", detail: JSON.stringify({
      ok: true, lines: ["log tail"], timeline: hostKnows ? { events: [
        { stamp: "2026-09-27 01:00:00", kind: "lock_wait", text: "waiting for claude lock" },
        { stamp: "2026-09-27 02:00:00", kind: "ended", text: "end state=ok" },
      ], omitted_bytes: 0, omitted_events: 0, audit_truncated: false, log_missing: false } : undefined,
    }) };
    return { ok: true, code: 0, action, id, message: "", detail: JSON.stringify({ ok: true, changed: true, message: "deadline moved" }) };
  };
  const opened = [];
  let preview = { ok: true };
  const store = makeBalanceStoreStub();
  const props = { wide: true, t, cachedTaskQueue: () => QUEUE, fetchTaskQueue: async () => QUEUE, runQueueAction,
    cachedBalances: () => ({ providers: [STALE_CL, DS_ROW_OK], refreshMs: 60000 }), fetchBalances: async () => ({ providers: [STALE_CL, DS_ROW_OK], refreshMs: 60000 }),
    useStore: store.useStore, actions: store.actions, openFile: (path) => { opened.push(path); return preview; } };
  const render = () => { reactStub._resetCursor(); return api.ProviderPanelSidebarAction(props); };
  const tick = () => new Promise((resolve) => setImmediate(resolve));
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
  const texts = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join(" ");
  };
  await tick(); await tick();
  const foldedKeys = find(render(), (p) => p["data-pp-row"] !== undefined).map((n) => n.props["data-pp-row"]);
  assert.deepEqual(foldedKeys, ["claude", "codex", "deepseek", "opencode"], "paid sources precede the free pool");
  find(render(), (p) => p["data-pp-row"] === "claude")[0].props.onClick({ currentTarget: null });
  let tree = render();
  const claude = find(tree, (p) => p["data-pp-group"] === "claude")[0];
  assert.match(texts(claude), /刷新失败（429 Too Many Requests），显示 .* 的读数/, "① the failure and the time of the reading still shown");
  assert.match(texts(claude), /会话 36%/, "① the last good windows are kept, not dropped");
  assert.match(texts(claude), /new-run .*\$0\.04/, "the row carries its cost");
  assert.match(texts(find(tree, (p) => p["data-pp-group"] === "opencode")[0]), /池 A → 下一个 B（表序）/, "④ pool position, labelled as file order");
  assert.equal(find(tree, (p) => p["data-pp-group"] === "opencode" && /\d+%/.test(texts(find(tree, (q) => q["data-pp-group"] === "opencode")[0]))).length, 0,
    "④ no percentage for the free pool");

  // Detail of a runner-api-3 task: the enforced deadline and budgets, tokens and cost.
  find(tree, (p) => p["data-tq-task"] === "new-run")[0].props.onClick();
  tree = render();
  assert.match(texts(tree), /截止 今天 \d\d:\d\d \+2h 重试 已用 1 \/ 3 \+1 额度续跑 已用 0 \/ 3 \+1 .*花费 \$0\.04 按 API 价估算，非实际扣费 · 截至上一次尝试结束 Tokens 共 102k 输入 10 · 缓存写 1\.0k · 缓存读 100k · 输出 500/,
    "each budget beside its control; a figure on its line, its breakdown or caveat under it");
  const layer = find(tree, (p) => p["data-tq-detail"] === "new-run")[0];
  assertDetailOrder(api, layer, "live");
  // The list moved these here (#2129): the plan that pays, the windows with their resets.
  assert.match(texts(find(layer, (p) => p["data-tq-section"] === "allowance")[0]),
    /额度 Agent Claude Code 槽 1 \/ 1 额度来源 Anthropic 订阅 刷新失败.*窗口 会话 36% ↻ 10:00 本周 69% ↻ 周四 10:00/);
  // Writes sit beside the fact they change; reads are one quiet row; the ending writes come last.
  const homes = actionHomes(layer);
  assert.deepEqual(Object.keys(homes), ["brief", "log", "timeline", "model", "deadline", "attempts", "resumes", "wrapup", "cancel", "raw-log"]);
  for (const [key, where] of Object.entries(homes)) {
    assert.equal(where.home, api.DETAIL_ACTIONS[key].home, `${key} lives in ${api.DETAIL_ACTIONS[key].home}`);
    assert.equal(where.kind, api.DETAIL_ACTIONS[key].kind, `${key} looks like a ${api.DETAIL_ACTIONS[key].kind}`);
  }
  // The raw record folds (the list's disclosure rule); the scroll area is a named region; the
  // answer to a write has a resident place outside it.
  const rawFold = find(find(layer, (p) => p["data-tq-section"] === "raw")[0], (p) => p["data-tq-fold"] === "raw")[0];
  assert.ok(rawFold && rawFold.type === "details" && !rawFold.props.open, "the raw record is folded");
  const scrollRegion = find(layer, (p) => p.role === "region" && /_tq-d-scroll/.test(p.className || ""))[0];
  assert.match(scrollRegion.props["aria-label"], /new-run/);
  const foot = find(layer, (p) => /_tq-d-notice/.test(p.className || ""))[0];
  assert.equal(foot.props.role, "status");
  assert.equal(find(scrollRegion, (p) => /_tq-d-notice/.test(p.className || "")).length, 0, "the answer is not inside the scroll area");
  // Budgets confirm in place and say what they cost; the second tap goes through the ops entry.
  const pill = (key) => find(render(), (p) => p["data-tq-action"] === key)[0];
  pill("raw-log").props.onClick();
  assert.equal(opened.at(-1), "/home/someone/logs/agent-dispatch/new-run/run.log", "full log uses the host's directory and file-preview door");
  assert.equal(calls.length, 0, "opening a full log does not call a queue write");
  const savedDir = QUEUE.logDir;
  delete QUEUE.logDir;
  const openedBeforeNoDir = opened.length;
  pill("raw-log").props.onClick();
  assert.equal(opened.length, openedBeforeNoDir, "an old host without a directory must not guess a path");
  assert.match(texts(render()), /未报告派发目录/);
  QUEUE.logDir = savedDir;
  pill("resumes").props.onClick();
  assert.equal(calls.length, 0, "one tap never writes");
  assert.match(texts(render()), /多给一次额度续跑：每次都会重放会话上下文，有成本（缓存读）。它在跑：本次尝试的时限不变，下一次尝试起生效。/);
  assert.equal(texts(pill("resumes")), "确认", "the armed control says what the second tap does");
  assert.equal(pill("resumes").props["aria-label"], "确认 续跑 +1");
  assert.equal(pill("resumes").props["data-armed"], "true");
  assert.ok(find(find(render(), (p) => p["data-tq-field"] === "resumes")[0], (p) => p["data-tq-confirm"] !== undefined).length === 1,
    "its confirmation sits under its own line, not at the end of an action bar");
  pill("resumes").props.onClick();
  await tick(); await tick();
  assert.deepEqual(calls.at(-1), ["resumes", "new-run", "4"]);
  assert.equal(find(render(), (p) => /_tq-d-notice/.test(p.className || ""))[0].props["data-tq-notice"], "true", "the answer lands in the resident foot");
  pill("deadline").props.onClick(); pill("deadline").props.onClick();
  await tick(); await tick();
  assert.deepEqual(calls.at(-1), ["deadline", "new-run", "+2h"]);

  pill("timeline").props.onClick();
  await tick(); await tick();
  assert.match(texts(render()), /本机队列 ops 尚未更新/);
  hostKnows = true;
  pill("timeline").props.onClick();
  await tick(); await tick();
  assert.match(texts(find(render(), (p) => p["data-tq-timeline"] === "new-run")[0]), /01:00:00 等待执行锁.*02:00:00 结束/);
  assert.deepEqual(calls.at(-1), ["log", "new-run", ""], "timeline uses the existing read-only host transport");
  hostKnows = false;

  // The brief opens in dsh's own preview; an older host half cannot list the appends and says so.
  pill("brief").props.onClick();
  await tick(); await tick();
  assert.equal(opened.at(-1), "/home/someone/logs/agent-dispatch/new-run/prompt.md", "the fallback is the host's logDir, not /root");
  assert.match(texts(render()), /追加列表要等插件 host 半边更新（需重启 dsh）/);
  hostKnows = true;
  pill("brief").props.onClick();
  await tick(); await tick();
  tree = render();
  assert.equal(opened.at(-1), "/tasks/new-run/prompt.md");
  const files = find(tree, (p) => p["data-tq-file"] !== undefined);
  assert.deepEqual(files.map((f) => f.props["data-tq-file"]), ["/tasks/new-run/prompt.md",
    "/tasks/new-run/inbox/delivered/20260927-010000-1-queue.md", "/tasks/new-run/inbox/20260927-020000-2-now.md"]);
  assert.match(texts(tree), /原文 68 KB.*追加 #1 · 2026-09-27 01:00:00 缩小范围 已投递 .*追加 #2 · 2026-09-27 02:00:00 修正验收依据 待投递/);
  files[2].props.onClick();
  assert.equal(opened.at(-1), "/tasks/new-run/inbox/20260927-020000-2-now.md", "an append opens its own file");
  preview = { ok: false, reason: "no-session" };
  files[0].props.onClick();
  assert.match(texts(render()), /右侧预览要在会话里打开：先进入任意会话，再点一次。文件：\/tasks\/new-run\/prompt\.md/, "no silent failure");
  briefFailure = true;
  const openedBeforeFailure = opened.length;
  pill("brief").props.onClick();
  await tick(); await tick();
  assert.equal(opened.length, openedBeforeFailure, "a failed brief read must not pretend a fallback file opened");
  assert.match(texts(render()), /读取失败：permission denied/);

  deferLog = true;
  pill("timeline").props.onClick();
  await tick();
  // An api-2 task: the budget pills are off and the reason is printed, not hover-only.
  find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  find(render(), (p) => p["data-tq-task"] === "old-wait")[0].props.onClick();
  tree = render();
  assert.equal(pill("deadline").props.disabled, true);
  assert.match(texts(tree), /这个任务的 runner 是 api 2/);
  resolveLog({ ok: true, code: 0, action: "log", id: "new-run", message: "", detail: JSON.stringify({
    timeline: { events: [{ stamp: "2026-09-27 03:00:00", kind: "ended", text: "late result" }],
      omitted_bytes: 0, omitted_events: 0, audit_truncated: false, log_missing: false },
  }) });
  await tick(); await tick();
  assert.equal(find(render(), (p) => p["data-tq-timeline"] !== undefined).length, 0, "a late timeline cannot paint another task");

  find(render(), (p) => p["data-tq-back"] === "true")[0].props.onClick();
  find(render(), (p) => p["data-tq-task"] === "done")[0].props.onClick();
  assert.equal(find(render(), (p) => p["data-tq-section"] === "summary").length, 0, "no summary does not consume an entire section");
  preview = { ok: false, reason: "no-session" };
  pill("raw-log").props.onClick();
  assert.match(texts(render()), /右侧预览要在会话里打开/, "the log exit reports missing preview context");
  QUEUE.recent[0].summary = "Truncated report…";
  tree = render();
  assertDetailOrder(api, find(tree, (p) => p["data-tq-detail"] === "done")[0], "ended");
  assert.equal(actionHomes(tree)["summary-log"].home, "summary", "a report has an exit to its complete source");
  preview = { ok: true };
  pill("summary-log").props.onClick();
  assert.equal(opened.at(-1), "/home/someone/logs/agent-dispatch/done/run.log");
  disposeReactEffects();

  // Touch: every new pressable is a 44px target under a coarse pointer; hover lives only behind a fine one.
  const css = fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8");
  assert.match(css, /@media \(pointer: ?coarse\)\{[^}]*_pp-row[^}]*_tq-file[^}]*\{min-height:44px/, "folded lines and brief files are finger-sized");
  assert.match(css, /@media \(hover: ?hover\) and \(pointer: ?fine\)\{[^}]*_pp-row:hover/, "the line's hover wash is fine-pointer only");
  // The fold control is a control, not a line of grey text: its own resting shape, a turning
  // chevron, the panel's focus ring, press feedback (off under reduced motion), a fine-pointer-
  // only hover and a 44px finger target (26px pill + 9px above and below).
  const rule = (sel) => css.match(new RegExp(`_${sel}\\{([^}]*)\\}`))?.[1] ?? "";
  assert.match(rule("tq-fold-summary"), /border:\.5px solid var\(--tq-pill-border\)/);
  assert.match(rule("tq-fold-summary"), /list-style:none/);
  assert.match(css, /_tq-fold\[open\]>\.[A-Za-z0-9_-]+_tq-fold-summary \.[A-Za-z0-9_-]+_tq-fold-chev\{transform:rotate\(90deg\)\}/);
  assert.match(rule("tq-fold-summary:focus-visible"), /outline:var\(--tq-focus-ring\)/);
  assert.match(rule("tq-fold-summary:active"), /transform:scale\(var\(--tq-press-scale\)\)/);
  assert.match(rule("tq-fold-summary"), /transition:[^;]*transform/, "its own transition still names transform");
  assert.match(css, /@media \(hover: ?hover\) and \(pointer: ?fine\)\{[^}]*_tq-fold-summary:hover/);
  assert.match(css, /@media \(pointer: ?coarse\)\{[^@]*_tq-fold-summary:after\{inset:-9px -8px\}/);
  assert.match(css, /@media \(pointer: ?coarse\)\{[^@]*_tq-row:not\(\.[A-Za-z0-9_-]+_tq-static\)\{min-height:44px\}/, "every row that opens a detail is finger-sized");
  assert.match(css, /@media \(prefers-reduced-motion: ?reduce\)\{[^@]*_tq-fold-summary\):active\{transform:none\}/);
});

// 2026-09-28 (kcn: 「很多地方都没有对齐显示」): one grid for the whole panel, five tracks, three
// of them fixed — lead · when · took · rest · aside — so a time, a duration, a cost and a state sit
// on one vertical line in every row. Each fact's cell is FACT_CELL in client.ts; this checks the
// stylesheet places every one of them there, and that the folded sidebar lines keep one subgrid.
test("provider panel: every row takes its columns from the one grid", async () => {
  const css = fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8");
  const rules = (sel) => [...css.matchAll(new RegExp(`${sel}(?:,[^{}]*)?\\{([^}]*)\\}`, "g"))].map((m) => m[1]).join(";");
  assert.equal((css.match(/--tq-grid:/g) ?? []).length, 1, "the columns are defined once");
  assert.match(css, /--tq-grid:var\(--tq-lead\) var\(--tq-when\) var\(--tq-took\) minmax\(0(px)?, ?1fr\) var\(--tq-aside\)/);
  for (const track of ["when", "took", "aside"]) assert.match(css, new RegExp(`--tq-${track}:\\d+px`), `--tq-${track} is a fixed width`);
  const desktop = Object.fromEntries(["when", "took", "aside"].map((track) =>
    [track, Number(css.match(new RegExp(`--tq-${track}:(\\d+)px`))?.[1])]));
  const phone = css.match(/@media \(width<=380px\)\{[^}]*--tq-when:(\d+)px;--tq-took:(\d+)px;--tq-aside:(\d+)px/);
  assert.ok(phone, "the narrow phone has a measured three-track budget");
  const narrow = { when: Number(phone[1]), took: Number(phone[2]), aside: Number(phone[3]) };
  // A 360px panel has 298px inside a well row; at 375px viewport the panel
  // is 351px and the row has 289px. Keep room for the shared lead, four 8px
  // gaps, both facts, the chip and at least 8px of elastic name track.
  for (const [label, tracks, rowWidth] of [["desktop", desktop, 298], ["phone", narrow, 289]]) {
    assert.ok(tracks.aside >= 104, `${label}: the longest resident state words and glyph fit the chip`);
    assert.ok(14 + 4 * 8 + tracks.when + tracks.took + tracks.aside + 8 <= rowWidth,
      `${label}: fixed tracks leave a name track at the real narrow sidebar width`);
  }
  assert.match(rules("_tq-chip"), /max-width:100%/, "the chip stays in the shared aside track");
  assert.doesNotMatch(rules("_tq-chip") + rules("_tq-chip-text"), /(?:text-overflow:ellipsis|overflow:hidden)/,
    "chip words are neither clipped nor ellipsised");
  assert.match(css, /--tq-main-inset:calc\(var\(--tq-lead\) \+ var\(--tq-gap\)\)/);
  assert.match(rules("\\[data-tq-row\\]"), /grid-template-columns:var\(--tq-grid\)/, "panel rows and folded lines alike");
  assert.match(rules("\\[data-tq-row\\]"), /align-items:baseline/, "the first line shares one baseline");
  assert.match(rules("_pp-row"), /grid-template-columns:subgrid/, "folded lines share the list's columns");
  assert.match(rules("_pp-rows"), /grid-template-columns:calc\(var\(--tq-lead\) \+ 8px\) minmax/, "the lead track carries the line's inset");
  // The panel's cells, as FACT_CELL says: line 1 name over when…rest, the chip or the value in aside.
  const row = "\\.[A-Za-z0-9_-]+_tq-row>";
  assert.match(rules(row + "\\.[A-Za-z0-9_-]+_tq-name"), /grid-column:2\/5/);
  assert.match(rules(row + "\\.[A-Za-z0-9_-]+_tq-value"), /grid-column:5/);
  assert.match(rules(row + "\\.[A-Za-z0-9_-]+_tq-chip\\[data-tq-chip=status\\]"), /grid-column:5;justify-self:stretch/, "one chip width per column");
  const loaded = await loadClient();
  const api = loaded.factory((s) => { if (s === "react") return makeReactStub(); return makeRuntimeStub(); });
  const cols = { main: "2/5", full: "2/6", when: "2/3", took: "3/4", aside: "5/6" };
  for (const [slot, cell] of Object.entries(api.FACT_CELL)) {
    const [from, to] = cols[cell.track].split("/");
    const placed = css.match(new RegExp(`_tq-row>(?::is\\([^)]*)?\\[data-tq-fact=${slot}\\][^{]*\\{([^}]*)\\}`))?.[1] ?? "";
    assert.match(placed, new RegExp(`grid-area:${cell.line}/${from}/${cell.line + 1}/${to}(;|$)`), `${slot} sits on line ${cell.line}, track ${cell.track}`);
  }
  assert.match(rules(row + "\\.[A-Za-z0-9_-]+_tq-caption-line"), /grid-area:2\/2\/3\/-1/);
  // Two levels: tasks sit on an inset well that starts on the name's edge; heads stay on the panel.
  assert.match(rules("_tq-well"), /margin:[^;]*var\(--tq-main-inset\)/, "the well starts on the name's edge");
  assert.match(rules("_tq-well"), /background:var\(--tq-well\)/);
  assert.match(css, /--tq-well:var\(--dsw-alias-[a-z-]+\)/, "the well is a host token");
  for (const sel of ["_tq-inset", "_tq-fold"]) assert.match(rules(sel), /var\(--tq-main-inset\)/, `${sel} starts on the name's edge`);
  assert.doesNotMatch(css, /_(tq-record|tq-line|tq-meta|tq-num|tq-group-head|pp-reading|pp-reset|pp-money)[{ ,.:[]/, "no per-row-type layout is left");
  // Every role has its bed, and no chip says anything through a grey level alone.
  for (const role of Object.keys(api.STATE_ROLES)) {
    assert.match(css, new RegExp(`_tq-chip(?::is\\([^)]*)?\\[data-role=${role}\\][^{]*\\{[^}]*color:var\\(--tq-`), `${role}: its own paint`);
  }
  assert.doesNotMatch(css, /data-tone=/, "the grey tone scale is gone");
});

// 2026-09-28 (kcn: 「问题在详情页」): the detail layer draws on the list's grid and the list's
// controls. Its fields put the label on the when track (the name's edge), the value over
// took…rest and a control in aside, where the list keeps its state chip; the hero is the row's own
// cells. Every control is the fold control's 26px capsule with the panel's focus ring outside it,
// press feedback and a 44px finger target; what it does (read / write / end) is its look.
test("detail layer: its fields sit on the list's grid and its controls are one height", () => {
  const css = fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8");
  const rules = (sel) => [...css.matchAll(new RegExp(`${sel}(?:,[^{}]*)?\\{([^}]*)\\}`, "g"))].map((m) => m[1]).join(";");
  for (const sel of ["_tq-d-field", "_tq-d-hero"]) {
    assert.match(rules(sel), /grid-template-columns:var\(--tq-grid\)/, `${sel} is on THE row grid`);
    assert.match(rules(sel), /align-items:baseline/, `${sel}: one baseline per line`);
  }
  assert.match(rules("_tq-d-k"), /grid-area:1\/2(;|$)/, "the label on the when track, the name's edge");
  assert.match(rules("_tq-d-v"), /grid-area:1\/3\/2\/-1/, "the value over took…rest");
  assert.match(rules("_tq-d-control"), /grid-area:1\/5(;|$)/, "a control in aside, where the list keeps its chip");
  assert.match(rules("_tq-d-hero>\\.[A-Za-z0-9_-]+_tq-chip"), /grid-area:1\/5;justify-self:stretch/, "the hero's chip in the row's chip column");
  assert.match(rules("_tq-d-sec-title"), /margin:0 0 2px var\(--tq-main-inset\)/, "a section starts on the name's edge");
  const pill = rules("_tq-pill");
  assert.match(pill, /height:26px/, "one control height: the fold control's");
  assert.match(rules("_tq-fold-summary"), /height:26px/);
  assert.match(pill, /transition:[^;]*transform/, "its own transition still names transform");
  assert.match(rules("_tq-pill:active"), /transform:scale\(var\(--tq-press-scale\)\)/);
  assert.match(rules("_tq-pill:focus-visible"), /outline:var\(--tq-focus-ring\);outline-offset:1px/, "the ring outside the capsule");
  assert.doesNotMatch(css, /_tq-pill,[^{]*:focus-visible\{outline:var\(--tq-focus-ring\);outline-offset:-2px/, "not the rows' inset ring");
  assert.match(css, /@media \(pointer: ?coarse\)\{[^@]*_tq-d-sec \.[A-Za-z0-9_-]+_tq-pill:after\{inset:-9px -8px\}/, "26 + 9 + 9 = a 44px target");
  assert.match(css, /@media \(hover: ?hover\) and \(pointer: ?fine\)\{[^@]*_tq-pill:hover/, "hover only on a fine pointer");
  // Kinds look apart: a read is a filled quiet bed, a write an outlined capsule, an end red; armed = its role's bed.
  const view = rules("_tq-pill\\[data-tq-kind=view\\]");
  assert.match(view, /background:var\(--tq-fill-inset\)/);
  assert.match(view, /border-color:(transparent|#0000)/, "a read has no outline");
  assert.match(pill, /border:\.5px solid var\(--tq-pill-border\)/);
  assert.match(rules("_tq-pill\\[data-armed\\]"), /background:var\(--tq-chip-warn-fill\)/);
  assert.match(rules("_tq-pill\\.[A-Za-z0-9_-]+_tq-danger\\[data-armed\\]"), /background:var\(--tq-chip-bad-fill\)/);
  // The answer to a write is resident, outside the scroll area, and never animates in.
  assert.match(rules("_tq-d-notice"), /flex:none/);
  assert.doesNotMatch(css, /_tq-d-[a-z-]+[^{]*\{[^}]*animation/, "nothing in the detail layer animates");
});

// #1955: the queue and provider panel wrote their waiting/failed WORDS in the host's state
// tokens, which are dot and icon paint — the waiting amber (--dsw-alias-state-warn-label) was
// 2.65:1 as 11px text on the panel, 2.39:1 hovered. Words now take the local semantic
// colours; this pins both halves: every state-coloured text rule reads a text role, and the
// colours those roles resolve to clear AA on the panel the host paints, hovered and pressed.
test("queue and provider panel: state-coloured words clear 4.5:1, dots keep the host paint (#1955)", () => {
  const css = fs.readFileSync(path.join(PLUGIN, "lib/client.js"), "utf8");
  assert.match(css, /--tq-text-warn:var\(--warn\)/);
  assert.match(css, /--tq-text-bad:var\(--bad\)/);
  assert.doesNotMatch(css, /--dsw-alias-state-warn-label/, "the host's warn label paint is not a text colour here");
  // The minifier folds rules with the same body into one selector list: a selector may lead one.
  const rule = (sel) => css.match(new RegExp(`_${sel}(?:,[^{}]*)?\\{([^}]*)\\}`))?.[1] ?? "";
  for (const [sel, role] of [
    ["tq-value\\[data-balance-state=stale\\]", "warn"], ["tq-value\\[data-balance-state=low\\]", "bad"],
    ["tq-value\\[data-used-level=mid\\]", "warn"], ["tq-value\\[data-used-level=low\\]", "bad"],
    ["tq-chip\\[data-role=fail\\]", "bad"], ["tq-fact\\[data-voice=warn\\]", "warn"],
    ["tq-receipt\\[data-state=failed\\]", "bad"], ["tq-receipt\\[data-state=sent\\]", "ok"],
    ["tq-d-status\\[data-balance-state=stale\\]", "warn"], ["tq-d-status\\[data-balance-state=low\\]", "bad"],
    ["tq-note\\.[A-Za-z0-9_-]+_tq-warn", "warn"], ["tq-note\\.[A-Za-z0-9_-]+_tq-bad", "bad"],
    ["tq-foot\\.[A-Za-z0-9_-]+_tq-bad", "bad"], ["tq-pill\\.[A-Za-z0-9_-]+_tq-danger", "bad"],
  ]) {
    assert.match(rule(sel), new RegExp(`color:var\\(--tq-text-${role}\\)`), `${sel} must be written in --tq-text-${role}`);
  }
  // The dots stay host paint (kcn 2026-09-26: one colour, one meaning).
  assert.match(rule("tq-dot\\[data-balance-state=stale\\]"), /background:var\(--tq-wait\)/);

  // WCAG 2 contrast. The beds are the host's own panel colour as measured on @deepseek-ai/dsh
  // 0.1.7-rc.2 (--dsw-specific-menu 58% over the sidebar fill: light #f8f9fa, dark #2d2e31) and
  // its hover/active fills (#2631480f / #2631481a) laid over the light one.
  const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const lum = (c) => hex(c).map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const over = (rgba, bed) => {
    const a = parseInt(rgba.slice(7, 9), 16) / 255;
    return "#" + hex(rgba).map((v, i) => Math.round(v * a + hex(bed)[i] * (1 - a)).toString(16).padStart(2, "0")).join("");
  };
  const local = (body, name) => body.match(new RegExp(`--${name}:(#[0-9a-f]{6})`, "i"))?.[1];
  const light = css.match(/\}\.[A-Za-z0-9_-]+_pbc\{([^}]*--warn:[^}]*)\}/)?.[1];
  const dark = css.match(/\[data-ds-dark-theme\] \.[A-Za-z0-9_-]+_pbc\{([^}]*)\}/)?.[1];
  assert.ok(light && dark, "the panel's local semantic colours must be found, light and dark");
  const beds = { light: ["#f8f9fa", over("#2631480f", "#f8f9fa"), over("#2631481a", "#f8f9fa")], dark: ["#2d2e31"] };
  for (const [theme, body] of [["light", light], ["dark", dark]]) {
    for (const name of ["warn", "bad", "ok"]) {
      for (const bed of beds[theme]) {
        // --ok paints only the delivered receipt, a glyph (WCAG 1.4.11 non-text: 3:1); the rest are words.
        const floor = name === "ok" ? 3 : 4.5;
        const r = ratio(local(body, name), bed);
        assert.ok(r >= floor, `${theme} --${name} ${local(body, name)} on ${bed}: ${r.toFixed(2)}:1 < ${floor}:1`);
      }
    }
  }
  // Verdict chips write those words on their own opaque soft fill: each pair owes 4.5:1 too.
  assert.match(css, /--tq-chip-warn-fill:var\(--warn-soft\)/);
  assert.match(css, /--tq-chip-bad-fill:var\(--bad-soft\)/);
  for (const [theme, body] of [["light", light], ["dark", dark]]) {
    for (const name of ["warn", "bad"]) {
      const r = ratio(local(body, name), local(body, name + "-soft"));
      assert.ok(r >= 4.5, `${theme} --${name} on --${name}-soft: ${r.toFixed(2)}:1 < 4.5:1`);
    }
  }
  for (const [role, text] of [["sleep", "warn"], ["partial", "warn"], ["wait", "warn"], ["fallback", "warn"], ["fail", "bad"]]) {
    assert.match(css, new RegExp(`_tq-chip(?::is\\([^)]*)?\\[data-role=${role}\\][^{]*\\{[^}]*color:var\\(--tq-text-${text}\\)`), `${role} chip words in --tq-text-${text}`);
  }
});

// The OpenClaw `/dispatch-list` reply is the provider panel as text (src/text.ts over the
// panel.ts model the sidebar draws). Its promise: for the same answers, the chat says
// every row the panel shows, in the panel's order, with the panel's own words.
test("openclaw /dispatch-list: the reply says every panel row, in order, in the panel's words", async () => {
  const loaded = await loadClient();
  const reactStub = makeReactStub();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-store") return makeRuntimeStub();
    if (s === "react") return reactStub;
    throw new Error(`unexpected require: ${s}`);
  });
  const chat = await import(pathToFileURL(path.join(PLUGIN, "lib", "chat.js")).href);
  const now = Date.now();
  const QUEUE = {
    available: true, status: "fresh", message: null, asOf: AS_OF, refreshMs: 15000, maxRunning: 3, running: 1,
    slotLimits: [{ agent: "claude", max: 1 }, { agent: "codex", max: 1 }, { agent: "opencode", max: 1 }],
    active: [
      { id: "a-1", name: "source-sync", agent: "claude", model: "claude-opus-5-5", state: "running", waiting: "", slot: "claude-1",
        attempts: 2, stalls: 0, outcome: "", startedAtMs: now - 65 * 60000, updatedAtMs: now, wakeAtMs: null, patrol: false },
      { id: "b-1", name: "model-bump", agent: "claude", model: "claude-opus-5-5", state: "queued", waiting: "lock", slot: "",
        attempts: 0, outcome: "", startedAtMs: now - 60000, updatedAtMs: now, wakeAtMs: null, patrol: false, position: 1 },
    ],
    recent: [{ id: "c-1", name: "merge-pr1767", agent: "codex", model: "gpt-6-sol", state: "ok", waiting: "", slot: "", attempts: 1,
      outcome: "DONE", startedAtMs: now - 3600000, updatedAtMs: now - 30 * 60000, wakeAtMs: null, patrol: false,
      notify: ["weixin", "telegram"], notified: ["telegram"], notifyFailed: ["weixin"], tokensTotal: 1000, costUsd: "1.25" }],
    patrol: { service: "active", phase: "waiting", round: "", detail: "", untilMs: now + 3600000,
      rounds: [{ endedAt: "2026-09-23 03:55:00", round: "R139", axis: "automation", result: "ok/DONE/P0#2241 +1 digest", seconds: 4090 }] },
    queues: [{ agent: "claude", held: true, holder: "a-1", order: ["b-1"], holderNote: "", quotaUntilMs: null, quotaBy: "" }],
  };
  const remoteFace = {
    balance: async () => ({ ok: true, value: BALANCES_OK }),
    taskQueue: async () => ({ ok: true, value: QUEUE }),
  };
  const ctx = {
    effect() {},
    locale: { register() { return () => {}; } },
    get() { return remoteFace; },
    layout: { selectPanel() {} },
    slots: {
      inject(name, fn) { (this._fns ??= []).push(fn); },
      register(definition, Component) { (this._regs ??= []).push({ definition, Component }); },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  for (const fn of ctx.slots._fns) fn();
  const foot = ctx.slots._regs.find((r) => r.definition.name === "sidebar.footer.action");
  const face = foot.definition.inject();
  const t = translatorFor(api);
  const store = makeBalanceStoreStub();
  const render = () => { reactStub._resetCursor(); return foot.Component({ wide: true, t, useStore: store.useStore, actions: store.actions, ...face }); };
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
  const texts = (tree) => {
    const out = [];
    (function walk(node) {
      if (node == null) return;
      if (Array.isArray(node)) { node.forEach(walk); return; }
      if (typeof node === "string") { out.push(node); return; }
      (node.children || []).forEach(walk);
    })(tree);
    return out.join("");
  };
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  try {
    render(); await tick(); await tick();
    find(render(), (p) => p["data-pp-row"] !== undefined)[0].props.onClick({ currentTarget: null });
    const popover = find(render(), (p) => p["data-clawock-popover"] === api.BALANCE_PANEL)[0];
    const reply = chat.dispatchListText({ balances: BALANCES_OK, balanceError: null, queue: QUEUE, queueError: null }, t, now).split("\n");

    assert.ok(reply.some((line) => /还剩 1 小时/.test(line)), "next-round wait has remaining time as well as the scheduled clock");
    const overdue = chat.dispatchListText({ balances: BALANCES_OK, balanceError: null,
      queue: { ...QUEUE, patrol: { ...QUEUE.patrol, untilMs: now - 60000 } }, queueError: null }, t, now);
    assert.match(overdue, /已到计划时间/, "a due round is not promised to have started");
    assert.doesNotMatch(overdue, /还剩 -/, "no negative countdown");
    const rows = find(popover, (p) => p["data-tq-row"] !== undefined);
    assert.ok(rows.length >= 8, `the fixture fills the panel (${rows.length} rows)`);
    const cell = (row, cls) => texts(find(row, (p) => new RegExp(`_tq-${cls}$`).test(p.className || "")));
    let at = 0;
    for (const row of rows) {
      const name = cell(row, "name");
      const line = reply.findIndex((l, i) => i >= at && l.includes(name));
      assert.ok(line >= 0, `${row.props["data-tq-row"]} "${name}" is in the reply after line ${at}:\n${reply.join("\n")}`);
      for (const said of [cell(row, "value"), texts(find(row, (p) => p["data-tq-chip"] === "status"))]) {
        if (said !== "") assert.ok(reply[line].includes(said), `"${said}" is on ${name}'s line: ${reply[line]}`);
      }
      for (const fact of find(row, (p) => p["data-tq-fact"] !== undefined && p["data-tq-fact"] !== "receipt")) {
        assert.ok(reply[line].includes(texts(fact)), `${name}'s ${fact.props["data-tq-fact"]} "${texts(fact)}" is on its line: ${reply[line]}`);
      }
      at = line + 1;
    }
    // The allowance lines under a source head: every window's label, used share and reset.
    for (const win of find(popover, (p) => /_bp-win$/.test(p.className || ""))) {
      const [label, pct, reset] = ["label", "pct", "reset"].map((c) => texts(find(win, (p) => new RegExp(`_bp-win-${c}$`).test(p.className || ""))));
      assert.ok(reply.some((l) => l.includes(label) && l.includes(pct) && l.includes(reset.replace("↻ ", "↻"))), `window ${label} ${pct} ${reset}`);
    }
    for (const count of [2, 4, 5]) {
      const rounds = Array.from({ length: count }, (_, i) => ({ ...QUEUE.patrol.rounds[0], round: 'T' + i }));
      const text = chat.dispatchListText({ balances: BALANCES_OK, balanceError: null,
        queue: { ...QUEUE, patrol: { ...QUEUE.patrol, rounds } }, queueError: null }, t, now);
      for (let i = 0; i < (count <= 4 ? count : 1); i++) assert.ok(text.includes('T' + i));
      if (count > 4) assert.ok(text.includes(t('queue.olderRounds', { n: count - 1 })));
      else assert.ok(!text.includes(t('queue.olderRounds', { n: count - 1 })));
    }
    // Receipts: the panel's glyphs are words and marks here, one per channel.
    assert.match(reply.find((l) => l.includes("merge-pr1767")), /微信✕ Telegram✓/);
  } finally {
    disposeReactEffects();
  }
});
