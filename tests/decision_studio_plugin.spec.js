#!/usr/bin/env node
/**
 * Decision Studio plugin tests (clawock-dsh node + client halves).
 *
 * Run: node tests/decision_studio_plugin.spec.js
 * CI: harness-regression.yml runs it when plugin files change.
 *
 * What is verified without a browser:
 *   - scan.js: workspace listing, run detail, run-id path-safety boundary
 *   - client.js: module-loader registration shape, inject face, model
 *     projection, and a stub-react render of the run list
 * The visual tab boot remains a source-machine verification (no GUI here).
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const test = require("node:test");

const PLUGIN = path.join(__dirname, "..", "examples", "dsh", "plugin");

function makeWorkspace() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-studio-"));
  const runId = "0123456789abcdef0123456789abcdef";
  const work = path.join(root, ".clawock", "work", runId);
  fs.mkdirSync(work, { recursive: true });
  fs.writeFileSync(path.join(work, "request.json"), JSON.stringify({
    schema_version: 1,
    run_id: runId,
    generation_id: "fedcba9876543210fedcba9876543210",
    task: "Produce decision.json for an evidence-linked investment decision.",
    context: { documents: [{ name: "CONTEXT.md", sha256: "aa".repeat(32) }] },
    workflow: {
      id: "investment-decision", version: "1.1.0",
      parameters: { min_supporting_evidence: 1, min_opposing_evidence: 1, max_confidence_without_primary_source: 0.65 },
    },
    subject: { ticker: "DEMO", market: "US", currency: "USD" },
    as_of: "2026-08-16T12:00:00+00:00",
  }));
  fs.mkdirSync(path.join(root, ".clawock", "runs", runId), { recursive: true });
  fs.writeFileSync(path.join(root, ".clawock", "runs", runId, "manifest.json"), JSON.stringify({
    generation_id: "fedcba9876543210fedcba9876543210",
    artifacts: [{ name: "decision.json" }],
  }));
  fs.writeFileSync(path.join(root, "decision.json"), JSON.stringify({ decision: { action: "watch" } }));
  return { root, runId };
}

test("scan: lists a prepared run with decision and receipt presence", async () => {
  const scan = await import(pathToFileURL(path.join(PLUGIN, "lib", "scan.js")).href);
  const { root, runId } = makeWorkspace();
  try {
    const runs = scan.listRuns(root);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].runId, runId);
    assert.equal(runs[0].subject.ticker, "DEMO");
    assert.equal(runs[0].documentCount, 1);
    assert.equal(runs[0].decisionPresent, true);
    assert.equal(runs[0].receiptPresent, true);
    assert.equal(runs[0].gates.min_opposing_evidence, 1);

    const detail = scan.getRun(root, runId);
    assert.equal(detail.request.workflow.id, "investment-decision");
    assert.deepEqual(detail.decision.decision, { action: "watch" });
    assert.equal(detail.manifest.artifacts[0].name, "decision.json");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("scan: ignores non-run directories and missing workspaces", async () => {
  const scan = await import(pathToFileURL(path.join(PLUGIN, "lib", "scan.js")).href);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "clawock-studio-"));
  try {
    fs.mkdirSync(path.join(root, ".clawock", "work", "not-a-run"), { recursive: true });
    fs.writeFileSync(path.join(root, ".clawock", "work", "not-a-run", "request.json"), "{}");
    assert.deepEqual(scan.listRuns(root), []);

    const missing = scan.getRun(root, "0123456789abcdef0123456789abcdef");
    assert.equal(missing.request, null);
    assert.deepEqual(scan.listRuns(path.join(root, "does-not-exist")), []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("scan: run ids are the path-safety boundary", async () => {
  const scan = await import(pathToFileURL(path.join(PLUGIN, "lib", "scan.js")).href);
  for (const bad of ["..", "../secret", "abc", "0123456789abcdef0123456789abcdeg", "", null, 42]) {
    assert.throws(() => scan.getRun("/tmp", bad), TypeError, `run id ${JSON.stringify(bad)} must be rejected`);
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

test("client: registers the Decision Studio conversation.view tab", async () => {
  let loaded = null;
  globalThis.window = { __ModuleLoader__: { load(entry) { loaded = entry; } } };
  const reactStub = makeReactStub();
  const requireStub = (specifier) => {
    if (specifier === "@deepseek-ai/dsh-client-runtime/client") return {};
    if (specifier === "react") return reactStub;
    throw new Error(`unexpected client require: ${specifier}`);
  };

  await import(clientUrl());
  assert.ok(loaded, "client.js must register through the module loader");
  assert.equal(loaded.id, "clawock-dsh");

  const api = loaded.factory(requireStub);
  assert.deepEqual(api.inject, ["slots", "remote", "remote.clawockStudio"]);
  assert.equal(typeof api.apply, "function");

  let registered = null;
  let component = null;
  const remoteList = async () => ({ ok: true, value: { runs: [] } });
  const ctx = {
    effect() {},
    slots: {
      inject(name, fn) { assert.equal(name, "conversation.view"); this._fn = fn; },
      register(definition, Component) { registered = definition; component = Component; },
    },
    remote: { clawockStudio: { list: remoteList } },
  };
  api.apply(ctx);
  ctx.slots._fn(); // slots.inject registers lazily once the slot exists
  assert.ok(registered, "apply must register into conversation.view");
  assert.equal(registered.name, "conversation.view");
  assert.equal(registered.id, "decision-studio");
  assert.equal(registered.order, 30);
  assert.equal(registered.label(), "Decision Studio");

  const injected = registered.inject("session-1");
  assert.equal(typeof injected.list, "function");
  const result = await injected.list();
  assert.deepEqual(result, { runs: [] });
  assert.equal(typeof component, "function");
});

test("client: _buildStudioModel projects run files for the tab", async () => {
  let loaded = null;
  globalThis.window = { __ModuleLoader__: { load(entry) { loaded = entry; } } };
  await import(clientUrl());
  const api = loaded.factory((specifier) => {
    if (specifier === "@deepseek-ai/dsh-client-runtime/client") return {};
    if (specifier === "react") return makeReactStub();
    throw new Error(`unexpected client require: ${specifier}`);
  });

  const empty = api._buildStudioModel({ runId: "0123456789abcdef0123456789abcdef", request: null });
  assert.equal(empty.empty, true);

  const full = api._buildStudioModel({
    runId: "0123456789abcdef0123456789abcdef",
    request: {
      subject: { ticker: "DEMO", market: "US", currency: "USD" },
      as_of: "2026-08-16T12:00:00+00:00",
      workflow: { parameters: { min_opposing_evidence: 1 } },
      context: { documents: [{ name: "CONTEXT.md" }] },
    },
    decision: {
      evidence: [{ id: "e1", stance: "opposing", summary: "risk", source: "market", source_class: "market", observed_at: "t" }],
      debate: { bull_case: {}, bear_case: {} },
      thesis: { statement: "s", confidence: 0.7 },
      decision: { action: "watch" },
    },
    manifest: { generation_id: "g1" },
  });
  assert.equal(full.empty, false);
  assert.equal(full.subject.ticker, "DEMO");
  assert.equal(full.gates.min_opposing_evidence, 1);
  assert.equal(full.evidence[0].stance, "opposing");
  assert.equal(full.action.action, "watch");
  assert.equal(full.receiptStatus, "published");
  assert.equal(full.generationId, "g1");
});

test("client: the tab component renders the run list from the remote", async () => {
  let loaded = null;
  globalThis.window = { __ModuleLoader__: { load(entry) { loaded = entry; } } };
  const reactStub = makeReactStub();
  const requireStub = (specifier) => {
    if (specifier === "@deepseek-ai/dsh-client-runtime/client") return {};
    if (specifier === "react") return reactStub;
    throw new Error(`unexpected client require: ${specifier}`);
  };
  await import(clientUrl());
  const api = loaded.factory(requireStub);

  let component = null;
  let registered = null;
  const ctx = {
    effect() {},
    slots: {
      inject(name, fn) { this._fn = fn; },
      register(definition, Component) { registered = definition; component = Component; },
    },
    remote: {
      clawockStudio: {
        list: async () => ({
          ok: true,
          value: { runs: [{ runId: "0123456789abcdef0123456789abcdef", subject: { ticker: "DEMO" }, asOf: "2026-08-16T12:00:00+00:00", decisionPresent: true, receiptPresent: true }] },
        }),
      },
    },
  };
  api.apply(ctx);
  ctx.slots._fn();
  const injected = registered.inject("s1"); // the real injected face unwraps the remote envelope

  const tree = (await (async () => {
    component({ sessionId: "s1", list: injected.list });
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    return component({ sessionId: "s1", list: injected.list });
  })());

  const text = [];
  (function walk(node) {
    if (node == null) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node === "string") { text.push(node); return; }
    (node.children || []).forEach(walk);
    walk(node.props && node.props.value);
    walk(node.props && node.props.label);
    walk(node.props && node.props.name);
  })(tree);
  const joined = text.join(" ");
  assert.match(joined, /DEMO/);
  assert.match(joined, /1/);
});
