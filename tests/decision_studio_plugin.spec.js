#!/usr/bin/env node
/**
 * Decision Mind plugin tests (clawock-dsh node + client halves).
 *
 * Run: node tests/decision_studio_plugin.spec.js
 * CI: harness-regression.yml runs it when plugin files change.
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

const PLUGIN = path.join(__dirname, "..", "examples", "dsh", "plugin");

// The bundle injects its stylesheet through `document` at factory time;
// node:test has no DOM, so provide the minimal surface the factory touches.
// `injectedStyleText` also feeds the CSS-contract regression test below.
let injectedStyleText = "";
globalThis.document = {
  getElementById() { return null; },
  createElement() { return { id: "", textContent: "" }; },
  querySelector() { return null; },
  head: { appendChild(el) { injectedStyleText = el.textContent || ""; } },
};

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

function makeReactStub() {
  let state = null;
  return {
    createElement(type, props, ...children) {
      if (typeof type === "function") {
        // Mini-renderer: invoke function components so their subtrees appear.
        return type(Object.assign({}, props, { children }));
      }
      return { type, props: props || {}, children };
    },
    useState(initial) {
      if (state === null) state = typeof initial === "function" ? initial() : initial;
      return [
        state,
        (updater) => {
          state = typeof updater === "function" ? updater(state) : updater;
        },
      ];
    },
    useEffect(fn) {
      fn(); // React runs effects after render; cleanup only on unmount/re-run
    },
  };
}

/** defineStore surface from the runtime stub: the factory builds its store
 *  handle at apply time, so the stub must provide the contract. */
function makeRuntimeStub() {
  return {
    defineStore(spec) {
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

  let registered = null;
  let component = null;
  const remoteFace = {
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
    traces: async () => ({ ok: true, value: { trades: [], rate: null } }),
    get: async (runId) => ({ ok: true, value: { runId } }),
  };
  const ctx = {
    effect() {},
    get(name) { assert.equal(name, "remote.clawockStudio"); return remoteFace; },
    slots: {
      inject(name, fn) { assert.equal(name, "conversation.view"); this._fn = fn; },
      register(definition, Component) { registered = definition; component = Component; },
    },
    remote: {
      $mount: async (descriptors) => {
        assert.equal(descriptors.descriptors.length, 6);
        // gateway invoke() validates args against descriptor.parameters.length —
        // get(runId) must declare its argument or every call would throw.
        const getDesc = descriptors.descriptors.find((d) => d.method === "get");
        assert.ok(getDesc, "get descriptor present");
        assert.equal(getDesc.parameters.length, 1, "get(runId) must declare its argument");
        assert.equal(getDesc.parameters[0].name, "runId");
      },
    },
  };
  await api.apply(ctx);
  ctx.slots._fn();
  assert.equal(registered.id, "decision-studio");
  assert.equal(registered.order, 30);
  assert.equal(registered.label(), "Decision Mind");
  // Official registration store: UI state survives the ring's unmount/remount.
  assert.ok(registered.store, "registration must declare a per-session store");
  assert.deepEqual(registered.store.spec.init(), { filter: "all", open: null, visibleDateCount: 3, foldedDates: [], scrollTop: 0 });

  const injected = registered.inject("s1");
  assert.equal(typeof injected.traces, "function");
  assert.equal(typeof injected.ledger, "function");
  assert.deepEqual(await injected.traces(), { trades: [], rate: null });
  assert.deepEqual(await injected.get("abc123"), { runId: "abc123" }, "get(runId) must forward its argument");
  assert.equal(typeof component, "function");
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

  let registered = null;
  let component = null;
  const remoteFace = {
    traces: async () => ({ ok: true, value: { trades: [
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-15", action: "buy",
        shares: 10, price: 8.77, realizedPnl: null, note: "无限子弹流继续摊本(微信 00:26 HKT)",
        t1: null, holdPnl: -28.0,
        decision: { planDate: "2026-08-14", action: "cut", confidence: 0.82,
          drivenBy: "risk_rule", rationale: "超限硬止损", execution: "unknown",
          sizeShares: 200, plannedPrice: 9.21 } },
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-07", action: "buy",
        shares: 20, price: 5.88, realizedPnl: null, note: "用户报告成交(01:34 HKT)",
        t1: { date: "2026-08-10", price: 5.6, delta: -4.76, verdict: "跌", tone: "loss" } },
      { ticker: "PLTU", market: "US", currency: "USD", date: "2026-08-13", action: "sell",
        shares: 5, price: 50, realizedPnl: 45.21428571428572, note: "PLTU 清仓",
        t1: { date: "2026-08-14", price: 49.24, delta: -1.52, verdict: "卖对", tone: "win" },
        decision: { planDate: "2026-08-10", action: "trim_on_rebound", confidence: 0.6,
          drivenBy: "technical", rationale: "浮盈保护", execution: "followed",
          condition: "反弹至 50 减仓" } },
    ], rate: 7.8473 } }),
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
  };
  const ctx = {
    effect() {},
    get() { return remoteFace; },
    slots: {
      inject(name, fn) { this._fn = fn; },
      register(definition, Component) { registered = definition; component = Component; },
    },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  ctx.slots._fn();
  const injected = registered.inject("s1");

  const store = makeStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  let tree = component({ sessionId: "s1", traces: injected.traces, ledger: injected.ledger, portfolio: injected.portfolio, useStore: store.useStore, actions: store.actions });
  await tick(); await tick(); await tick();
  tree = component({ sessionId: "s1", traces: injected.traces, ledger: injected.ledger, portfolio: injected.portfolio, useStore: store.useStore, actions: store.actions });

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
  // The denominator must be rendered, not implied (#710): the ratio only
  // covers fills whose close actually landed inside the T+1 window.
  assert.match(joined, /基于 \d+ 笔/, "the T+1 scorecard must show what it is computed over");

  // The chip class must come from the host's `tone`, not from a threshold the
  // client re-derives (#713). Walk the tree for the real className so a
  // fixture that drops `tone` cannot keep this test green.
  const classes = [];
  (function walkClass(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walkClass); return; }
    if (typeof node === "string") return;
    const cn = node.props && node.props.className;
    if (typeof cn === "string") classes.push(cn);
    (node.children || []).forEach(walkClass);
  })(tree);
  assert.ok(classes.includes("t1 win") || classes.includes("t1 up"),
    `a tone:"win" trace must render an up/win chip, got: ${classes.filter((c) => c.startsWith("t1")).join(", ")}`);
  assert.ok(!classes.some((c) => /undefined|null/.test(c)),
    `no className may contain undefined — a fixture missing t1.tone would show up here: ${classes.filter((c) => /undefined|null/.test(c)).join(", ")}`);
  assert.match(joined, /SPCH/);
  assert.match(joined, /买入/);
  assert.match(joined, /10 @8.77/);
  assert.match(joined, /PLTU/);
  assert.match(joined, /卖出/);
  assert.match(joined, /\+45.21/);       // realized P&L on the real sell
  assert.match(joined, /卖对/);           // T+1 verdict chip
  assert.doesNotMatch(joined, /\+\+/);   // header stat must not double-prepend the sign

  // Filter: 无决策 keeps only SPCH fills without a decision.
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
  findButton("无决策").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", traces: injected.traces, ledger: injected.ledger, portfolio: injected.portfolio, useStore: store.useStore, actions: store.actions });
  const joinedMiss = collectText();
  assert.match(joinedMiss, /SPCH/);
  assert.doesNotMatch(joinedMiss, /PLTU/); // PLTU has a decision → filtered out

  // Expand a row: the trace detail shows plan → execution → P&L.
  findButton("全部").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", traces: injected.traces, ledger: injected.ledger, portfolio: injected.portfolio, useStore: store.useStore, actions: store.actions });
  const cell = [];
  (function collect(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(collect); return; }
    if (node.props && node.props.onClick && String(node.props.className || "").indexOf("cell") === 0) cell.push(node);
    (node.children || []).forEach(collect);
  })(tree);
  assert.ok(cell.length >= 2, "trace rows present");
  cell[0].props.onClick();
  await tick();
  tree = component({ sessionId: "s1", traces: injected.traces, ledger: injected.ledger, portfolio: injected.portfolio, useStore: store.useStore, actions: store.actions });
  const joined2 = collectText();
  assert.match(joined2, /决策轨迹 · /);   // expand header
  assert.match(joined2, /割肉/);           // plan action
  assert.match(joined2, /执行/);
  assert.match(joined2, /盈亏/);
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

  let registered = null;
  let component = null;
  const remoteFace = {
    traces: async () => ({ ok: true, value: { trades, rate: null } }),
    ledger: async () => ({ ok: true, value: { entries: [] } }),
    portfolio: async () => ({ ok: true, value: { books: [] } }),
    plans: async () => ({ ok: true, value: { plans: [] } }),
  };
  const ctx = {
    effect() {},
    get() { return remoteFace; },
    slots: { inject(n, fn) { this._fn = fn; }, register(definition, Component) { registered = definition; component = Component; } },
    remote: { $mount: async () => {} },
  };
  await api.apply(ctx);
  ctx.slots._fn();
  const injected = registered.inject("s1");

  const store = makeStoreStub();
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const render = () => component({ sessionId: "s1", traces: injected.traces, ledger: injected.ledger, portfolio: injected.portfolio, useStore: store.useStore, actions: store.actions });
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
      if (String(node.props && node.props.className || "").indexOf("day fold") === 0) found = node;
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
});

test("client: stylesheet keeps the dark-theme and tone contract (#704/#685 regression gate)", async () => {
  // The factory injects its stylesheet through the document stub on first
  // execution; assert the blocks whose regressions are invisible to text
  // assertions — the dark-theme overrides and the P&L/T+1 tone colors.
  injectedStyleText = "";
  const loaded = await loadClient();
  loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return makeRuntimeStub();
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });
  assert.ok(injectedStyleText.length > 1000, "factory must inject a real stylesheet");
  assert.match(injectedStyleText, /body\[data-ds-dark-theme\] \.dmt\{/, "dark-theme override block required (#704)");
  assert.match(injectedStyleText, /\.dmt \.t1\.up/, "T+1 up tone class required (#685)");
  assert.match(injectedStyleText, /\.dmt \.t1\.down/, "T+1 down tone class required (#685)");
  assert.match(injectedStyleText, /\.dmt \.detail\{display:grid;grid-template-rows:0fr/, "folded detail must default to 0fr");
  assert.match(injectedStyleText, /\.dmt \.stats/, "header stats block required");
  assert.match(injectedStyleText, /\.dmt \.filters/, "filter row block required");
  assert.match(injectedStyleText, /\.dmt \.skel/, "cold-start skeleton block required");
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

test("freshness: signature moves on each of the three data sources", async () => {
  const freshness = await import(pathToFileURL(path.join(PLUGIN, "lib", "freshness.js")).href);
  const root = makeDesk();
  const barsDir = path.join(root, "memory", "bars");
  fs.mkdirSync(barsDir, { recursive: true });
  try {
    const before = freshness.workspaceSignature(root);
    assert.ok(before.length > 0);
    assert.equal(before.split("|").length, 3, "shape: portfolio stat | bars digest | decisions stat");
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


