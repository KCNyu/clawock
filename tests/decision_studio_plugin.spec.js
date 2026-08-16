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
globalThis.document = {
  getElementById() { return null; },
  createElement() { return { id: "", textContent: "" }; },
  head: { appendChild() {} },
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
  return pathToFileURL(path.join(PLUGIN, "client.js")).href + "?v=" + importCounter;
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
    if (s === "@deepseek-ai/dsh-client-runtime/client") return {};
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
  };
  const ctx = {
    effect() {},
    get(name) { assert.equal(name, "remote.clawockStudio"); return remoteFace; },
    slots: {
      inject(name, fn) { assert.equal(name, "conversation.view"); this._fn = fn; },
      register(definition, Component) { registered = definition; component = Component; },
    },
    remote: { $mount: async (descriptors) => { assert.equal(descriptors.descriptors.length, 5); } },
  };
  await api.apply(ctx);
  ctx.slots._fn();
  assert.equal(registered.id, "decision-studio");
  assert.equal(registered.order, 30);
  assert.equal(registered.label(), "Decision Mind");

  const injected = registered.inject("s1");
  assert.equal(typeof injected.ledger, "function");
  assert.equal(typeof injected.portfolio, "function");
  assert.deepEqual(await injected.ledger(), { entries: [] });
  assert.equal(typeof component, "function");
});

test("client: _displayEntry projects mind records and degrades legacy entries", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return {};
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  const conv = api._displayEntry({
    decision_id: "dec-1", source: "conversation",
    subject: { ticker: "00100", market: "HK", currency: "HKD" },
    decided_at: "2026-08-16T13:45:00+08:00", action: "reject", confidence: 0.65,
    mind: { bull: { summary: "b" }, bear: { summary: "r" }, thesis: "t", invalidation: ["c1"] },
    emotion: { pressure: "averaging_down", note: "忍住" },
    execution: { status: "unknown" },
  });
  assert.equal(conv.ticker, "00100");
  assert.equal(conv.action, "reject");
  assert.equal(conv.emotion, "averaging_down");
  assert.deepEqual(conv.invalidation, ["c1"]);

  const legacy = api._displayEntry({
    decision_id: "dec-2", plan_date: "2026-08-10", ticker: "00100",
    action: "trim_on_rebound", confidence: 0.7,
    condition: { description: "跌破 730" }, evaluation: { outcome: "not_triggered" },
  });
  assert.equal(legacy.bull, null);
  assert.equal(legacy.condition, "跌破 730");
  assert.equal(legacy.outcome, "not_triggered");
  assert.equal(legacy.emotion, null);
});

test("client: renders ledger cards from the mounted remote", async () => {
  const loaded = await loadClient();
  const api = loaded.factory((s) => {
    if (s === "@deepseek-ai/dsh-client-runtime/client") return {};
    if (s === "react") return makeReactStub();
    throw new Error(`unexpected require: ${s}`);
  });

  let registered = null;
  let component = null;
  const remoteFace = {
    ledger: async () => ({ ok: true, value: { entries: [
      { decision_id: "dec-1", source: "conversation", subject: { ticker: "00100" },
        decided_at: "2026-08-16T13:45:00+08:00", action: "reject", confidence: 0.65,
        mind: { bull: { summary: "营收 +159%" }, bear: { summary: "资不抵债" }, invalidation: ["站回 340"] },
        emotion: { pressure: "averaging_down", note: "忍住没加" },
        execution: { status: "followed" } },
      { decision_id: "dec-2", plan_date: "2026-08-10", ticker: "07226", action: "hold", confidence: 0.5,
        rationale: "测试理由: 杠杆风险已释放,持有观察",
        execution: { status: "followed" } },
      { decision_id: "dec-3", plan_date: "2026-08-11", ticker: "02208", action: "cut", confidence: 0.6,
        size: { shares: 30, pct: 0.15 }, simulated_entry_price: 10.5,
        execution: { status: "followed" } },
      { decision_id: "dec-4", plan_date: "2026-08-12", ticker: "03032", action: "trim", confidence: 0.4,
        execution: { status: "unknown" } },
    ] } }),
    portfolio: async () => ({ ok: true, value: { books: [{ name: "hk_stocks", currency: "HKD", holdings: [{ ticker: "02208", shares: 200, price: 10.58, pnlPct: -24.9 }] }], trades: [
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-15", action: "buy", shares: 10, price: 8.77, realizedPnl: null, note: "无限子弹流继续摊本(用户报告成交,微信 00:26 HKT)" },
      { ticker: "SPCH", market: "US", currency: "USD", date: "2026-08-07", action: "buy", shares: 20, price: 5.88, realizedPnl: null, note: "用户报告成交(01:34 HKT)" },
      { ticker: "PLTU", market: "US", currency: "USD", date: "2026-08-13", action: "sell", shares: 5, price: 50, realizedPnl: 45.21428571428572, note: "PLTU 清仓" },
    ] } }),
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

  const tick = () => new Promise((resolve) => setImmediate(resolve));
  let tree = component({ sessionId: "s1", ledger: injected.ledger, portfolio: injected.portfolio, plans: injected.plans });
  await tick(); await tick(); await tick();
  tree = component({ sessionId: "s1", ledger: injected.ledger, portfolio: injected.portfolio, plans: injected.plans });

  const text = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { text.push(node); return; }
    (node.children || []).forEach(walk);
    walk(node.props && node.props.value);
    walk(node.props && node.props.label);
  })(tree);
  const joined = text.join(" ");
  assert.match(joined, /决策心智/);
  // default view = actual operations (real fills), newest first
  assert.match(joined, /SPCH/);
  assert.match(joined, /加仓/);
  assert.match(joined, /10 股 @8.77/);
  assert.match(joined, /PLTU/);
  assert.match(joined, /清仓/);
  assert.match(joined, /\+45.21/); // realized P&L on the real sell

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

  // switch to 账本: executed-trades filter with counts
  findButton("账本").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", ledger: injected.ledger, portfolio: injected.portfolio, plans: injected.plans });
  const textL = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { textL.push(node); return; }
    (node.children || []).forEach(walk);
    walk(node.props && node.props.value);
    walk(node.props && node.props.label);
  })(tree);
  const joinedL = textL.join(" ");
  assert.match(joinedL, /已执行交易 1/); // count on the filter button
  assert.match(joinedL, /全部 4/);
  assert.match(joinedL, /02208/);
  assert.match(joinedL, /割肉/);
  assert.match(joinedL, /30 股 @10.5/);   // executed how much
  assert.match(joinedL, /现盈亏 -24.9%/); // and what it is worth now
  assert.doesNotMatch(joinedL, /00100/);
  assert.doesNotMatch(joinedL, /03032/);

  // switch to 全部: everything appears — reject with bull-fallback why, hold with rationale why, unknown trim
  findButton("全部").props.onClick();
  await tick();
  tree = component({ sessionId: "s1", ledger: injected.ledger, portfolio: injected.portfolio, plans: injected.plans });
  const textB = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { textB.push(node); return; }
    (node.children || []).forEach(walk);
    walk(node.props && node.props.value);
    walk(node.props && node.props.label);
  })(tree);
  const joinedB = textB.join(" ");
  assert.match(joinedB, /00100/);
  assert.match(joinedB, /不加/);
  assert.match(joinedB, /为什么: 营收/);     // conversation record: bull-fallback why
  assert.match(joinedB, /为什么: 测试理由/); // plan record: rationale why
  assert.match(joinedB, /07226/);
  assert.match(joinedB, /03032/);
  assert.match(joinedB, /· 对话/);           // conversation day tag

  // click a ledger card row: expand shows the mind detail
  const cardRows = [];
  (function collect(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(collect); return; }
    if (node.props && node.props.onClick && node.props.className === "row") cardRows.push(node);
    (node.children || []).forEach(collect);
  })(tree);
  assert.ok(cardRows.length >= 2, "expanded ledger cards");
  cardRows[0].props.onClick();
  await tick();
  tree = component({ sessionId: "s1", ledger: injected.ledger, portfolio: injected.portfolio, plans: injected.plans });
  const text2 = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { text2.push(node); return; }
    (node.children || []).forEach(walk);
    walk(node.props && node.props.value);
    walk(node.props && node.props.label);
  })(tree);
  const joined2 = text2.join(" ");
  assert.match(joined2, /营收 \+159%/);
  assert.match(joined2, /资不抵债/);
  assert.match(joined2, /站回 340/);
  assert.match(joined2, /忍住没加/);
});
