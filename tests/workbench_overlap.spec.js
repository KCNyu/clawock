#!/usr/bin/env node
/**
 * Workbench overlap + type-computation contract (Playwright).
 *
 * Run: NODE_PATH=<dir with playwright> node tests/workbench_overlap.spec.js
 * CI:  ci.yml's `workbench-overlap` job (Chromium desktop + WebKit mobile).
 *
 * For every state in the matrix it renders the REAL `lib/client.js` bundle in a
 * real React root at a real viewport, collects every visible interactive block,
 * row, group header, tab, badge, sheet, toast, sticky control and text block,
 * and intersects their clipped getBoundingClientRect boxes. Any pair over
 * 0.5px² fails unless it is one of the documented exceptions:
 *   - an ancestor/descendant pair (a container is not a "block");
 *   - the explicit z-axis overlay (sheet over the page, toast over the page);
 *   - the sticky tab bar over already-scrolled content (scrollTop > 0).
 * All exceptions are written to the JSON and the summary table with a reason.
 *
 * On top of that scan, an explicit geometry contract names the pairs the
 * 2026-11-08 screenshots broke: adjacent sidebar rows and the label/alert
 * boxes inside the host's 36px row (with no numeric badge on the glyph), the
 * closing-report card vs its Full log row, and the patrol coverage tables
 * (one column on a phone). The wide row keeps the count in the host label;
 * the rail keeps only the non-numeric alert mark. `sidebar-control` is a
 * negative control: it deliberately overlaps adjacent rows and the same
 * check must report them, so the positive states cannot pass vacuously.
 *
 * It also records computed font-size/line-height/weight for the provider rows
 * in normal / near-limit / alert / stale / free / unknown states and in both
 * themes; the same semantic role must resolve to the same values.
 *
 * Environment:
 *   WORKBENCH_BUNDLE   path to a client.js (default: the package's built lib)
 *   WORKBENCH_OUT      JSON output path (default: OS temp dir)
 *   WORKBENCH_SHOTS    screenshot directory (default: beside the JSON)
 *   WORKBENCH_STATES   comma-separated state names to run
 *   WORKBENCH_LEGACY   "1" for a pre-detail-layer bundle (no stats/history/sheet)
 *   WORKBENCH_EXPECT_ALL "0" to allow missing states (baseline capture)
 */
"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const PKG = path.join(ROOT, "examples", "dsh", "packages", "clawock-dsh");
const bundlePath = process.env.WORKBENCH_BUNDLE
  ? path.resolve(process.env.WORKBENCH_BUNDLE)
  : path.join(PKG, "lib", "client.js");
const outPath = process.env.WORKBENCH_OUT
  ? path.resolve(process.env.WORKBENCH_OUT)
  : path.join(os.tmpdir(), "workbench-overlap.json");
const shotsDir = process.env.WORKBENCH_SHOTS ? path.resolve(process.env.WORKBENCH_SHOTS) : outPath.replace(/\.json$/, "-shots");
const legacy = process.env.WORKBENCH_LEGACY === "1";
const expectAll = process.env.WORKBENCH_EXPECT_ALL !== "0";
const only = process.env.WORKBENCH_STATES ? new Set(process.env.WORKBENCH_STATES.split(",").map((s) => s.trim())) : null;
const bundle = fs.readFileSync(bundlePath, "utf8");
const bundleSha = crypto.createHash("sha256").update(bundle).digest("hex");

function resolvePackageFile(id, sub) {
  const pkg = require.resolve(id + "/package.json", { paths: [PKG, ROOT] });
  return path.join(path.dirname(pkg), sub);
}
const reactFile = resolvePackageFile("react", path.join("umd", "react.production.min.js"));
const reactDomFile = resolvePackageFile("react-dom", path.join("umd", "react-dom.production.min.js"));

// ---------------------------------------------------------------------------
// The harness page. No host app: the bundle's own CSS + React are enough; the
// host tokens below stand in for dsh-client-ui-theme (colours only — the type
// ladder lives in the package, which is the point of the typography test).
// ---------------------------------------------------------------------------
const HOST_CSS = `
html,body{height:100%;margin:0}
body{--dsw-font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
 --ds-font-family-code:ui-monospace,SFMono-Regular,Menlo,monospace;
 --dsw-alias-bg-layer-1:#fff;--dsw-alias-bg-base:#f7f8fa;--dsw-alias-label-primary:#15171b;
 --dsw-alias-label-secondary:#61666b;--dsw-alias-label-tertiary:#81858c;--dsw-alias-label-caption:#adb2b8;
 --dsw-alias-label-primary-inverted:#fff;--dsw-alias-border-l1:rgba(17,24,39,.06);
 --dsw-alias-border-l2:rgba(17,24,39,.10);--dsw-alias-border-l3:rgba(17,24,39,.16);
 --dsw-alias-interactive-bg-hover:rgba(17,24,39,.05);--dsw-alias-interactive-bg-active:rgba(17,24,39,.08);
 --dsw-alias-button-ghost-active-fill:#f1f3f5;--dsw-alias-state-warn-primary:#b45309;
 --dsw-alias-state-success-primary:#18763e;--dsw-alias-state-error-primary:#dc2626;--dsw-alias-link:#2563eb;
 --dsw-alias-brand-primary:#15171b;--dsw-static-neutral-bluish-75:#f1f3f5;--dsw-static-neutral-bluish-100:#ebeef2;
 --dsw-radius-sm:8px;--dsw-radius-md:8px;--dsw-focus-ring-width:2px;--dsw-focus-ring-color:#15171b;
 --dsh-frame-top-clearance:0px;--dsh-chat-content-width:748px;--ds-ease-out:cubic-bezier(.2,.7,.3,1)}
body[data-ds-dark-theme]{--dsw-alias-bg-layer-1:#171a1f;--dsw-alias-bg-base:#0f1115;
 --dsw-alias-label-primary:#f2f4f7;--dsw-alias-label-secondary:#b8bec7;--dsw-alias-label-tertiary:#8f97a3;
 --dsw-alias-label-caption:#737b86;--dsw-alias-label-primary-inverted:#0f1115;
 --dsw-alias-border-l1:rgba(255,255,255,.07);--dsw-alias-border-l2:rgba(255,255,255,.12);
 --dsw-alias-border-l3:rgba(255,255,255,.19);--dsw-alias-interactive-bg-hover:rgba(255,255,255,.07);
 --dsw-alias-interactive-bg-active:rgba(255,255,255,.11);--dsw-alias-button-ghost-active-fill:#232830;
 --dsw-alias-state-warn-primary:#f59e0b;--dsw-alias-state-success-primary:#34d399;
 --dsw-alias-state-error-primary:#f87171;--dsw-alias-link:#60a5fa;--dsw-alias-brand-primary:#f2f4f7;
 --dsw-focus-ring-color:#f2f4f7}
#root{height:100%;position:relative}
.wb-stage{height:100%;display:flex}
.wb-stage > *{flex:1 1 auto;min-width:0}
.wb-stage > *{flex:1 1 auto;min-width:0}
/* dsh's sidebar.panellist host, measured on the live desk at 390x844 (after
   the wb-icon change): 36px rows, a 16px glyph slot, a 14px/22px label and a
   6px glyph-to-label gap. The rail is the same list at 56px with 36px hit
   boxes and a 12px gap. */
.host-sidebar{width:264px;min-height:100%;box-sizing:border-box;padding:8px;background:#f7f8fa;font:14px/22px system-ui,-apple-system,"Segoe UI",sans-serif;color:#15171b}
.host-sidebar.host-rail{width:56px;padding:12px 10px}
.host-panel-list{display:flex;flex-direction:column;gap:2px}
.host-panel-row{display:flex;align-items:center;gap:6px;width:100%;height:36px;box-sizing:border-box;margin:0;padding:0 10px;border:0;border-radius:8px;background:transparent;color:inherit;font:inherit;text-align:left}
.host-panel-row[aria-current=true]{background:rgba(38,49,72,.06)}
.host-panel-glyph{flex:none;display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px}
.host-panel-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.host-rail .host-panel-list{gap:12px}
.host-rail .host-panel-row{width:36px;justify-content:center;padding:0}
.host-rail .host-panel-title{display:none}
`;

const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>${HOST_CSS}</style>
<style>*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}</style>
</head><body><div id="root"></div>
<script src="/react.js"></script><script src="/react-dom.js"></script>
<script>window.__ModuleLoader__={load(entry){window.__entry=entry}};</script>
<script src="/client.js"></script>
<script src="/harness.js"></script>
</body></html>`;

const HARNESS_JS = String.raw`
(function(){
  const React = window.React, ReactDOM = window.ReactDOM;
  const mod = window.__entry.factory((id) => {
    if (id === 'react') return React;
    if (id === 'react-dom') return { createPortal: (children) => children };
    if (id === '@deepseek-ai/dsh-client-store') {
      return { defineStore: (spec) => ({ spec, create: () => ({ getSnapshot: () => spec.init(), subscribe: () => () => {} }) }) };
    }
    throw new Error('unexpected require: ' + id);
  });
  const params = new URLSearchParams(location.search);
  const scenario = params.get('scenario') || 'normal';
  const theme = params.get('theme') || 'light';
  if (theme === 'dark') document.body.dataset.dsDarkTheme = 'dark';
  const now = Date.now();
  const BASE = {
    available: true, status: 'fresh', message: null, asOf: new Date(now - 60000).toISOString(), refreshMs: 15000,
    maxRunning: 4, running: 1, active: [], recent: [], pending: [], pendingTotal: 0,
    logDir: '/tmp/tasks', ops: { available: true, version: 'c8e72e9e3849', runnerApi: 7 },
    queues: [], opencodePool: [], slotLimits: [],
    patrol: {
      service: 'active', phase: 'waiting', round: 'R1188', detail: '', untilMs: now + 6 * 3600_000,
      rounds: [
        { round: 'R1188', axis: 'harness', endedAt: '2026-11-07 21:21', result: 'failed/P1#3135', seconds: 61 },
        { round: 'R1187', axis: 'dsh', endedAt: '2026-11-07 15:21', result: 'ok/DONE', seconds: 633 },
      ],
      progress: {
        areas: ['dashboard','data','debt','delivery','docs','dsh','harness','ops','risk','security'].map((name, i) => ({ name, open: i === 2 ? 3 : 0 })),
        lenses: ['automation','coupling','debt','docs','dsh','harness','ops','risk','security','signals'].map((name, i) => ({
          name, open: i === 5 ? 2 : 0, rounds: 40 + i, last: { endedAt: '2026-11-07 21:21', result: i === 5 ? 'failed' : 'ok/DONE', round: 'R' + (1180 + i), seconds: 61 + i },
        })),
        conclusion: '2 areas need a look', areaInventory: true, lensInventory: true,
        firstAt: '2026-09-17 04:00:19', issuesAt: '2026-11-07T14:08:42.564Z',
      },
    },
  };
  const task = (i, extra) => Object.assign({
    id: 'task-' + i, name: '任务 ' + i, agent: 'dsh', model: 'deepseek-official/deepseek-flash',
    modelRequested: 'deepseek-official/deepseek-flash', modelUsed: 'deepseek-official/deepseek-flash',
    effortRequested: 'max', effortUsed: 'max', state: 'ok', waiting: '', slot: '', attempts: 1,
    outcome: 'DONE', startedAtMs: null, updatedAtMs: now - i * 60000, wakeAtMs: null, patrol: false,
    summary: '', lastEvent: '', lastEventAtMs: null, finishedAtMs: now - i * 60000,
    needs: '请按 MATRIX.md 与 REVIEW.md 验收，第二句话不应出现在行里。', stage: 'person/review',
    attention: 'person', notify: ['weixin', 'telegram'], notified: [], notifyFailed: [], notifyAtMs: null,
    priority: 0, protected: false, question: false, questionRecommend: 0, position: null,
    deadlineAtMs: now + 3600_000, maxAttempts: 3, quotaResumes: 3, quotaResumesUsed: 0,
    runnerApi: 7, session: 'session-' + i, tokensIn: 120000, tokensOut: 8000, tokensCacheW: 0,
    tokensCacheR: 900000, tokensTotal: 1028000, costUsd: '1.64', stalls: 0, cancelling: false,
  }, extra || {});
  const closing = [
    '- 风险 3：live top 3 仍是 5/8，说明字面召回是当前瓶颈；下一步可考虑给高频高 salience topic 补 tag，或单独改排序，不在本 PR 混入。',
    'RESTART: ops/host/restart_gateway.sh 2026-11-08 01:39 CST success（首次因 systemd user bus 缺失失败，设置 XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS 后重试；日志确认 shared-memory-corpus 插件已加载）',
    'NEEDS: none',
    'STATUS: DONE',
  ].join('\n');
  const pending = [
    task(0, { name: 'workbench-parity-restore', summary: closing, needs: '请安排 MiniMax 子会话按 /root/scratch/workbench-parity/MATRIX.md、REVIEW.md 与 shots/ 证据验收' }),
    task(1, { name: '巡检修复：dsh 工作台与 provider 行', needs: '确认一下窄屏下的断行与置顶按钮' }),
    task(2, { name: 'A-very-long-task-name-that-must-ellipsize-without-crossing-the-age-cell', needs: '检查长标题、百分比、第二行与角标' }),
    task(3, { name: '任务 3', needs: '再做一次' }),
  ];
  const live = task(9, { id: 'live-1', name: '正在跑的长任务', state: 'running', outcome: '', stage: 'working',
    startedAtMs: now - 120000, finishedAtMs: null, waiting: '', slot: 'dsh-1', position: 1, needs: '等待中' });
  const recent = [task(10, { id: 'recent-1', name: '已结束的任务', finishedAtMs: now - 3600_000 }),
    task(11, { id: 'recent-2', name: '另一个已结束任务', finishedAtMs: now - 7200_000, outcome: 'PARTIAL' }),
    task(12, { id: 'recent-3', name: '第三个已结束任务', finishedAtMs: now - 86400_000 })];
  const goodQueue = Object.assign({}, BASE, {
    pending, pendingTotal: pending.length, active: [live], running: 1, recent,
  });
  const emptyQueue = Object.assign({}, BASE, { pending: [], active: [], recent: [], pendingTotal: 0, running: 0 });
  const failQueue = Object.assign({}, BASE, { available: false, status: 'failed', message: 'taskQueue read failed: fixture', pending: [], active: [], recent: [] });

  const provider = (provider, label, snapshot, status, extra) => Object.assign({
    provider, label, result: { configured: true, snapshot: Object.assign({
      isAvailable: true, unit: 'pct', currency: '', totalBalance: '20', grantedBalance: '', toppedUpBalance: '',
      asOf: new Date(now - 60000).toISOString(), note: '', windows: [{ label: '5h', percent: 20, resetAt: '21:00' }, { label: '周', percent: 41, resetAt: '周四 21:00' }],
    }, snapshot), status: status || 'fresh', low: false, message: null, threshold: 20, refreshMs: 60000 },
  }, extra || {});
  const goodBalances = { refreshMs: 60000, providers: [
    provider('deepseek', 'DeepSeek', { unit: 'money', currency: 'CNY', totalBalance: '109.21', grantedBalance: '0.00', toppedUpBalance: '109.21', windows: [] }),
    provider('codex', 'Codex', { totalBalance: '100', windows: [{ label: '周', percent: 100, resetAt: '周四 10:00' }] }, 'fresh'),
    provider('claude', 'Claude', { totalBalance: '85', windows: [{ label: '本周', percent: 85, resetAt: '周四 10:00' }] }, 'fresh'),
    provider('minimax', 'MiniMax', { totalBalance: '69', windows: [{ label: '周', percent: 69, resetAt: '周四 21:00' }] }, 'stale'),
    provider('opencode', 'OpenCode', { unit: 'pct', totalBalance: '0', windows: [] }, 'fresh', { result: { configured: true, snapshot: { isAvailable: false, unit: 'pct', currency: '', totalBalance: '0', grantedBalance: '', toppedUpBalance: '', asOf: new Date(now - 60000).toISOString(), note: '', windows: [] }, status: 'fresh', low: false, message: null, threshold: 20, refreshMs: 60000 } }),
  ] };
  const calmBalances = { refreshMs: 60000, providers: [
    provider('deepseek', 'DeepSeek', { unit: 'money', currency: 'CNY', totalBalance: '109.21', grantedBalance: '0.00', toppedUpBalance: '109.21', windows: [] }),
    provider('codex', 'Codex', { totalBalance: '100', windows: [{ label: '周', percent: 40, resetAt: '周四 10:00' }] }, 'fresh'),
  ] };
  const emptyBalances = { refreshMs: 60000, providers: [] };
  const failBalances = { refreshMs: 60000, providers: [] };
  const goodStats = {
    available: true, error: '', since: null, days: 7, patrolIncluded: false, asOf: new Date(now - 60000).toISOString(),
    agents: [
      { agent: 'dsh', tasks: 37, live: 1, tokensTotal: 1207549203, tokensUnknown: 6, costUsdEstimate: 14.07, costUnpriced: 6, costFree: 0, outcomes: [{ name: 'DONE', count: 28 }, { name: '-', count: 7 }, { name: 'PARTIAL', count: 1 }], states: [] },
      { agent: 'codex', tasks: 12, live: 0, tokensTotal: 73557977, tokensUnknown: 0, costUsdEstimate: 86.79, costUnpriced: 0, costFree: 0, outcomes: [{ name: 'DONE', count: 9 }, { name: '-', count: 2 }, { name: 'PARTIAL', count: 1 }], states: [] },
      { agent: 'claude', tasks: 0, live: 0, tokensTotal: 0, tokensUnknown: 0, costUsdEstimate: 0, costUnpriced: 0, costFree: 0, outcomes: [], states: [] },
    ],
    daily: {},
  };
  const noStats = { available: false, error: 'taskStats read failed: fixture', since: null, days: 7, patrolIncluded: false, asOf: '', agents: [] };
  const emptyStats = { available: true, error: '', since: null, days: 7, patrolIncluded: false, asOf: '', agents: [], daily: {} };

  function queueFor(name) {
    if (name === 'empty') return emptyQueue;
    if (name === 'read-failed') return failQueue;
    if (name === 'toast') return Object.assign({}, goodQueue, { logDir: '' });
    return goodQueue;
  }
  const balancesFor = (name) => name === 'empty' ? emptyBalances : name === 'read-failed' ? failBalances : name === 'sidebar-quiet' ? calmBalances : goodBalances;
  const statsFor = (name) => name === 'empty' ? emptyStats : name === 'read-failed' ? noStats : goodStats;

  const never = () => new Promise(() => {});
  const answer = (action, id) => {
    if (action === 'brief') return { ok: true, code: 0, action, id, message: '', detail: JSON.stringify({ path: '/tmp/tasks/' + id + '/prompt.md', brief: '# task\n\nline one\nline two', brief_bytes: 4096, truncated: false, appends: [{ file: 'append-1.md', path: '/tmp/tasks/' + id + '/append-1.md', stamp: '2026-11-07 19:45', delivered: true, bytes: 2048, text: '【kcn 追加（逐字）】这是一段足够长的追加正文，用来验证任务书浮层里文件名、摘要与投递标签不会互相压住。' }] }) };
    if (action === 'log') return { ok: true, code: 0, action, id, message: '', detail: JSON.stringify({ lines: ['line 1', 'line 2', 'line 3'], timeline: { events: [{ stamp: '21:21', kind: 'start', text: 'started' }, { stamp: '21:22', kind: 'end', text: 'done' }], omitted_bytes: 0, omitted_events: 0, audit_truncated: false, log_missing: false } }) };
    if (action === 'choices') return { ok: true, code: 0, action, id, message: '', detail: JSON.stringify({ models: ['deepseek-official/deepseek-flash', 'deepseek-official/deepseek-pro'], efforts: { 'deepseek-official/deepseek-flash': ['max', 'high'] }, effort_flag: 'effort', allowed: true, reason: '', requested: { model: 'deepseek-official/deepseek-flash', effort: 'max' } }) };
    return { ok: true, code: 0, action, id, message: '', detail: '{}' };
  };

  let queue = queueFor(scenario), balances = balancesFor(scenario), stats = statsFor(scenario);
  function props() {
    const fail = scenario === 'read-failed', loading = scenario === 'loading';
    return {
      cachedTaskQueue: () => fail || loading ? null : queue,
      fetchTaskQueue: () => loading ? never() : fail ? Promise.reject(new Error('taskQueue read failed: fixture')) : Promise.resolve(queue),
      cachedBalances: () => fail || loading ? null : balances,
      fetchBalances: () => loading ? never() : fail ? Promise.reject(new Error('balances read failed: fixture')) : Promise.resolve(balances),
      fetchTaskStats: () => loading ? never() : fail ? Promise.reject(new Error('taskStats read failed: fixture')) : Promise.resolve(stats),
      runQueueAction: async (action, id, arg) => {
        if (scenario === 'toast' && action === 'brief') return { ok: false, code: 1, action, id, message: 'brief read failed: fixture', detail: '' };
        return answer(action, id);
      },
      runWorkbenchAction: async (action, id) => ({ ok: true, code: 0, action, id, message: '', detail: '' }),
      openFile: () => ({ ok: true }),
      closeWorkbench: () => {},
      t: mod.createTranslator(mod.dictionaries.zh),
    };
  }
  function mountWorkbench() {
    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(React.createElement('div', { className: 'wb-stage' }, React.createElement(mod.WorkbenchPage, props())));
  }
  // A host-like sidebar list: the four panellist rows dsh draws above
  // Workspaces, with the real row geometry. The Workbench row is the plugin's
  // own icon; the neighbours are plain glyphs so a badge that leaves its row
  // has something to collide with.
  const SIDEBAR_ROWS = [
    ['plugin', 'Plugins', 'M3.2 8.2 8 1.8l4.8 6.4v5.3a.7.7 0 0 1-.7.7H3.9a.7.7 0 0 1-.7-.7z'],
    ['workbench', 'Workbench', null],
    ['automation', 'Automation tasks', 'M8 1.8a6.2 6.2 0 1 0 0 12.4A6.2 6.2 0 0 0 8 1.8Zm0 2.6V8l2.6 1.5'],
    ['more', 'More', 'M3 3h3v3H3zM10 3h3v3h-3zM3 10h3v3H3zM10 10h3v3h-3z'],
  ];
  function mountSidebar(mode) {
    const stage = document.createElement('div');
    stage.className = 'host-sidebar' + (mode === 'rail' ? ' host-rail' : '');
    const list = document.createElement('div');
    list.className = 'host-panel-list';
    let mount = null;
    for (const [key, label, path] of SIDEBAR_ROWS) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'host-panel-row';
      button.setAttribute('data-wb-sidebar-row', key);
      button.setAttribute('aria-label', label);
      if (key === 'workbench') button.setAttribute('aria-current', 'true');
      const glyph = document.createElement('span');
      glyph.className = 'host-panel-glyph';
      if (path === null) {
        const slot = document.createElement('div');
        slot.style.display = 'contents';
        glyph.appendChild(slot);
        mount = slot;
      } else {
        glyph.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.35" aria-hidden="true"><path d="' + path + '"></path></svg>';
      }
      const title = document.createElement('span');
      title.className = 'host-panel-title hHd-Xa_panelTitle';
      title.textContent = label;
      button.appendChild(glyph);
      button.appendChild(title);
      list.appendChild(button);
    }
    stage.appendChild(list);
    document.getElementById('root').appendChild(stage);
    const root = ReactDOM.createRoot(mount);
    root.render(React.createElement(mod.WorkbenchIcon, {
      size: 16, active: false, t: mod.createTranslator(mod.dictionaries.zh),
      cachedTaskQueue: () => queue, fetchTaskQueue: async () => queue,
      cachedBalances: () => balances, fetchBalances: async () => balances,
      rememberTrigger: () => {},
    }));
    if (scenario === 'sidebar-control') {
      // Negative control: a real 10px overlap between adjacent rows must be
      // reported by the same check the positive states rely on.
      const broken = document.createElement('style');
      broken.textContent = '.host-panel-row + .host-panel-row{ margin-top:-12px }';
      document.head.appendChild(broken);
    }
  }
  if (scenario === 'sidebar' || scenario === 'sidebar-rail' || scenario === 'sidebar-quiet' || scenario === 'sidebar-control') {
    mountSidebar(scenario === 'sidebar-rail' ? 'rail' : 'wide');
  } else {
    mountWorkbench();
  }
  window.__workbenchReady = () => document.querySelector('[data-wb], [data-wb-icon]') !== null;
})();
`;

// ---------------------------------------------------------------------------
// Browser-side geometry + typography probe. Runs in the page.
// ---------------------------------------------------------------------------
function collectInPage(options) {
  const scrollTop = options.scrollTop || 0;
  const viewport = { w: document.documentElement.clientWidth, h: window.innerHeight };
  const seen = new Set();
  const out = [];
  const directText = (el) => {
    let text = "";
    for (const node of el.childNodes) if (node.nodeType === 3) text += node.nodeValue;
    return text.trim();
  };
  const wanted = (el) => {
    if (!(el instanceof HTMLElement)) return false;
    if (el.matches("script,style,link,meta")) return false;
    if (el.closest("[data-wb-scrim]")) return false;
    if (el.matches("button,a,summary,[role=tab],p,h1,h2,h3,h4,li,dt,dd,pre,time,strong")) return true;
    if (el.matches("[data-wb-task],[data-wb-provider],[data-wb-group],[data-wb-overview-group],[data-wb-history],[data-wb-fold],[data-wb-detail],[data-wb-sheet],[data-wb-toast],[data-wb-badge],[data-wb-tab-alert],[data-wb-rail-alert],[data-wb-tab-count],[data-wb-provider-pin],[data-wb-tabs],[data-wb-stats-layer],[data-wb-history-layer],[data-wb-patrol-layer]")) return true;
    if (el.className && typeof el.className === "string" && /_wb-|_tq-/.test(el.className)) return el.children.length === 0 || directText(el) !== "";
    return false;
  };
  const clip = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0.01 || rect.height <= 0.01) return null;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return null;
    let left = rect.left, top = rect.top, right = rect.right, bottom = rect.bottom;
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      const pstyle = getComputedStyle(parent);
      if (/(hidden|auto|scroll|clip)/.test(pstyle.overflow + pstyle.overflowX + pstyle.overflowY)) {
        const p = parent.getBoundingClientRect();
        left = Math.max(left, p.left); top = Math.max(top, p.top);
        right = Math.min(right, p.right); bottom = Math.min(bottom, p.bottom);
      }
    }
    left = Math.max(left, 0); top = Math.max(top, 0);
    right = Math.min(right, viewport.w); bottom = Math.min(bottom, viewport.h);
    if (right - left <= 0.01 || bottom - top <= 0.01) return null;
    return { x: left, y: top, w: right - left, h: bottom - top };
  };
  const localName = (el) => {
    const names = [...el.classList].filter((name) => /_/.test(name)).map((name) => name.split("_").slice(1).join("_"));
    return names.length ? names[0] : "";
  };
  const selectorOf = (el) => {
    for (const attr of el.getAttributeNames()) {
      if (attr.startsWith("data-wb-") || attr === "role" || attr === "aria-label") {
        const value = el.getAttribute(attr) || "";
        if (value !== "" && value.length < 40) return el.tagName.toLowerCase() + "[" + attr + "=\"" + value.replace(/"/g, "'") + "\"]";
      }
    }
    const cls = localName(el);
    let selector = el.tagName.toLowerCase() + (cls ? "." + cls : "");
    const parent = el.parentElement;
    if (parent) {
      const same = [...parent.children].filter((child) => child.tagName === el.tagName);
      if (same.length > 1) selector += ":nth-of-type(" + (same.indexOf(el) + 1) + ")";
    }
    return selector;
  };
  const overlayOf = (el) => el.closest("[data-wb-sheet],[data-wb-toast]");
  const stickyAncestor = (el) => el.closest("[data-wb-tabs]");
  const blocks = [];
  for (const el of document.querySelectorAll("*")) {
    if (seen.has(el) || !wanted(el)) continue;
    seen.add(el);
    const rect = clip(el);
    if (rect === null) continue;
    blocks.push({
      el, rect,
      selector: selectorOf(el),
      tag: el.tagName.toLowerCase(),
      text: ((el.innerText || el.getAttribute("aria-label") || "").trim()).slice(0, 80),
      overlay: overlayOf(el) === null ? null : (el.closest("[data-wb-sheet]") ? "sheet" : "toast"),
      sticky: stickyAncestor(el) !== null,
    });
  }
  const failures = [];
  const allowed = [];
  for (let i = 0; i < blocks.length; i += 1) {
    for (let j = i + 1; j < blocks.length; j += 1) {
      const a = blocks[i], b = blocks[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const x = Math.max(a.rect.x, b.rect.x), y = Math.max(a.rect.y, b.rect.y);
      const x2 = Math.min(a.rect.x + a.rect.w, b.rect.x + b.rect.w);
      const y2 = Math.min(a.rect.y + a.rect.h, b.rect.y + b.rect.h);
      const area = Math.max(0, x2 - x) * Math.max(0, y2 - y);
      if (area <= 0.5) continue;
      const pair = {
        a: a.selector, b: b.selector, area: Number(area.toFixed(2)),
        rects: { a: { x: a.rect.x, y: a.rect.y, w: a.rect.w, h: a.rect.h }, b: { x: b.rect.x, y: b.rect.y, w: b.rect.w, h: b.rect.h } },
        text: [a.text, b.text],
      };
      // Explicit z-axis exceptions, recorded with a reason.
      if (a.overlay !== b.overlay && (a.overlay !== null || b.overlay !== null)) {
        allowed.push({ ...pair, reason: "z-axis: " + (a.overlay || b.overlay) + " overlay above the page" });
        continue;
      }
      if (scrollTop > 0.5 && a.sticky !== b.sticky) {
        allowed.push({ ...pair, reason: "z-axis: sticky tab bar over scrolled content" });
        continue;
      }
      failures.push(pair);
    }
  }
  return {
    scrollTop,
    blocks: blocks.map(({ el, ...rest }) => rest),
    failures,
    allowed,
  };
}

function typographyInPage() {
  const read = (selector) => {
    const el = document.querySelector(selector);
    if (el === null) return null;
    const style = getComputedStyle(el);
    return { fontSize: style.fontSize, lineHeight: style.lineHeight, fontWeight: style.fontWeight, fontFamily: style.fontFamily };
  };
  const rows = [...document.querySelectorAll("[data-wb-provider]")].map((row) => ({
    state: row.getAttribute("data-wb-provider-state"),
    signal: row.getAttribute("data-wb-provider-signal"),
    name: read('[data-wb-provider="' + row.getAttribute("data-wb-provider") + '"] [class*="_wb-prov-name"]'),
    primary: read('[data-wb-provider="' + row.getAttribute("data-wb-provider") + '"] [class*="_wb-prov-primary"]'),
    meta: read('[data-wb-provider="' + row.getAttribute("data-wb-provider") + '"] [class*="_wb-prov-meta"]'),
  }));
  const tab = read('[role=tab] [class*="_wb-tab-label"]');
  const group = read('[data-wb-group-button="pending"] [class*="_wb-group-title"]');
  return { rows, tab, group };
}

// ---------------------------------------------------------------------------
// Explicit geometry contracts. These are stricter than the generic overlap
// scan: they name the pair that must not intersect and the gap that must stay
// positive, so a regression says which row/card/column broke.
// ---------------------------------------------------------------------------
function gaugeInPage(mode) {
  const box = (el) => {
    if (el === null || el === undefined) return null;
    const r = el.getBoundingClientRect();
    if (r.width <= 0.01 || r.height <= 0.01) return null;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") return null;
    return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom };
  };
  const area = (a, b) => {
    if (a === null || b === null) return 0;
    const w = Math.min(a.right, b.right) - Math.max(a.x, b.x);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y);
    return Math.max(0, w) * Math.max(0, h);
  };
  const inside = (inner, outer) => inner !== null && outer !== null &&
    inner.x >= outer.x - 0.5 && inner.y >= outer.y - 0.5 &&
    inner.right <= outer.right + 0.5 && inner.bottom <= outer.bottom + 0.5;
  const round = (n) => Math.round(n * 100) / 100;

  if (mode === "sidebar") {
    const rows = [...document.querySelectorAll("[data-wb-sidebar-row]")].map((el) => ({
      name: el.getAttribute("data-wb-sidebar-row"),
      rail: el.getAttribute("data-wb-rail") === "true",
      row: box(el),
      title: box(el.querySelector(".host-panel-title")),
      titleText: (() => { const t = el.querySelector(".host-panel-title"); return t === null ? null : t.textContent; })(),
      icon: box(el.querySelector("[data-wb-icon]")),
      badgeNodes: el.querySelectorAll("[data-wb-badge]").length,
      alert: box(el.querySelector("[data-wb-rail-alert]")),
    }));
    const intersections = [];
    for (let i = 0; i < rows.length; i += 1) {
      for (let j = i + 1; j < rows.length; j += 1) {
        const overlap = area(rows[i].row, rows[j].row);
        if (overlap > 0.5) intersections.push({ a: rows[i].name, b: rows[j].name, area: round(overlap) });
      }
    }
    const containment = rows.map((row) => ({
      name: row.name,
      titleInside: row.title === null || inside(row.title, row.row),
      iconInside: row.icon === null || inside(row.icon, row.row),
      alertInside: row.alert === null || inside(row.alert, row.row),
      rowHeight: row.row === null ? 0 : round(row.row.h),
    }));
    return { mode, rows, intersections, containment };
  }

  if (mode === "detail") {
    const summary = document.querySelector('[data-tq-section="summary"] [class*="_tq-d-summary"]');
    if (summary === null) return { mode, present: false };
    const section = summary.parentElement;
    const actions = section.querySelector(':scope > [class*="_tq-actions"]');
    const pill = actions === null ? null : actions.querySelector('[class*="_tq-pill"]');
    const summaryBox = box(summary);
    const actionsBox = box(actions);
    return {
      mode, present: true,
      summary: summaryBox,
      actions: actionsBox,
      pill: box(pill),
      gap: summaryBox === null || actionsBox === null ? null : round(actionsBox.y - summaryBox.bottom),
      pillGap: summaryBox === null || box(pill) === null ? null : round(box(pill).y - summaryBox.bottom),
      clipped: Math.max(0, Math.round(summary.scrollHeight - summary.clientHeight)),
      widthOverflow: Math.max(0, Math.round(summary.scrollWidth - summary.clientWidth)),
    };
  }

  if (mode === "coverage") {
    const cov = document.querySelector('[data-wb-ov-sec="coverage"]');
    if (cov === null) return { mode, present: false };
    const covBox = box(cov);
    const blocks = [...cov.querySelectorAll('[data-coverage]')].map((el) => ({
      kind: el.getAttribute('data-coverage'),
      box: box(el),
      scrollOverflow: Math.max(0, Math.round(el.scrollWidth - el.clientWidth)),
    }));
    const sideBySide = [];
    for (let i = 1; i < blocks.length; i += 1) {
      const prev = blocks[i - 1].box, next = blocks[i].box;
      if (prev === null || next === null) continue;
      if (next.y < prev.bottom - 0.5) sideBySide.push({ a: blocks[i - 1].kind, b: blocks[i].kind, dy: round(next.y - prev.bottom) });
    }
    return {
      mode, present: true,
      display: getComputedStyle(cov).display,
      cov: covBox,
      blocks,
      sideBySide,
      widthOverflow: Math.max(0, Math.round(cov.scrollWidth - cov.clientWidth)),
      narrowest: blocks.reduce((min, b) => b.box === null ? min : Math.min(min, b.box.w), Infinity),
    };
  }

  if (mode === "providers") {
    const rows = [...document.querySelectorAll('[data-wb-provider]')].map((el) => ({
      key: el.getAttribute('data-wb-provider'),
      name: box(el.querySelector('[class*="_wb-prov-name"]')),
      primary: box(el.querySelector('[class*="_wb-prov-primary"]')),
      secondary: box(el.querySelector('[class*="_wb-prov-secondary"]')),
      metaLeft: box(el.querySelector('[class*="_wb-prov-left"]')),
      metaRight: box(el.querySelector('[class*="_wb-prov-right"]')),
      widthOverflow: Math.max(0, Math.round(el.scrollWidth - el.clientWidth)),
    }));
    const collisions = [];
    for (const row of rows) {
      for (const [a, b] of [["name", "primary"], ["name", "secondary"], ["primary", "secondary"], ["metaLeft", "metaRight"]]) {
        const overlap = area(row[a], row[b]);
        if (overlap > 0.5) collisions.push({ key: row.key, a, b, area: round(overlap) });
      }
    }
    return { mode, present: rows.length > 0, rows, collisions };
  }
  return { mode, present: false };
}

// ---------------------------------------------------------------------------
// Server + browser matrix
// ---------------------------------------------------------------------------
function serve() {
  const server = http.createServer((req, res) => {
    const url = req.url.split("?")[0];
    const send = (status, type, body) => {
      res.writeHead(status, { "content-type": type, "cache-control": "no-store" }); res.end(body);
    };
    if (url === "/" || url === "/index.html") return send(200, "text/html; charset=utf-8", PAGE);
    if (url === "/client.js") return send(200, "application/javascript; charset=utf-8", bundle);
    if (url === "/react.js") return send(200, "application/javascript; charset=utf-8", fs.readFileSync(reactFile));
    if (url === "/react-dom.js") return send(200, "application/javascript; charset=utf-8", fs.readFileSync(reactDomFile));
    if (url === "/harness.js") return send(200, "application/javascript; charset=utf-8", HARNESS_JS);
    return send(404, "text/plain", "not found");
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

const STATES = [
  { name: "tasks", width: 390, height: 844, scenario: "normal", drive: null },
  { name: "providers", width: 390, height: 844, scenario: "normal", drive: "providers", gauge: "providers" },
  { name: "overview", width: 390, height: 844, scenario: "normal", drive: "overview" },
  { name: "patrol", width: 390, height: 844, scenario: "normal", drive: "patrol", gauge: "coverage" },
  { name: "stats", width: 390, height: 844, scenario: "normal", drive: "stats" },
  { name: "history", width: 390, height: 844, scenario: "normal", drive: "history" },
  { name: "task", width: 390, height: 844, scenario: "normal", drive: "task", gauge: "detail" },
  { name: "sheet", width: 390, height: 844, scenario: "normal", drive: "sheet" },
  { name: "toast", width: 390, height: 844, scenario: "toast", drive: "toast" },
  { name: "empty", width: 390, height: 844, scenario: "empty", drive: "empty" },
  { name: "read-failed", width: 390, height: 844, scenario: "read-failed", drive: "providers" },
  { name: "loading", width: 390, height: 844, scenario: "loading", drive: "providers" },
  { name: "320-tasks", width: 320, height: 568, scenario: "normal", drive: null },
  { name: "task-375", width: 375, height: 667, scenario: "normal", drive: "task", gauge: "detail" },
  { name: "patrol-375", width: 375, height: 667, scenario: "normal", drive: "patrol", gauge: "coverage" },
  { name: "providers-375", width: 375, height: 667, scenario: "normal", drive: "providers", gauge: "providers" },
  { name: "sidebar", width: 390, height: 844, scenario: "sidebar", drive: null, gauge: "sidebar" },
  { name: "sidebar-375", width: 375, height: 667, scenario: "sidebar", drive: null, gauge: "sidebar" },
  { name: "sidebar-quiet", width: 390, height: 844, scenario: "sidebar-quiet", drive: null, gauge: "sidebar" },
  { name: "sidebar-control", width: 390, height: 844, scenario: "sidebar-control", drive: null, gauge: "sidebar", control: "row-overlap" },
  { name: "320-sticky", width: 320, height: 568, scenario: "normal", drive: "sticky" },
  { name: "320-providers", width: 320, height: 568, scenario: "normal", drive: "providers" },
  { name: "320-task", width: 320, height: 568, scenario: "normal", drive: "task", gauge: "detail" },
  { name: "320-sheet", width: 320, height: 568, scenario: "normal", drive: "sheet" },
  { name: "keyboard", width: 390, height: 420, scenario: "normal", drive: "task-bottom" },
  { name: "dark-tasks", width: 390, height: 844, scenario: "normal", theme: "dark", drive: null },
  { name: "dark-providers", width: 390, height: 844, scenario: "normal", theme: "dark", drive: "providers" },
  { name: "rail", width: 390, height: 844, scenario: "sidebar-rail", drive: null, gauge: "sidebar" },
  { name: "desktop-tasks", width: 1440, height: 900, scenario: "normal", desktop: true, drive: null },
  { name: "desktop-providers", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "providers" },
  { name: "desktop-overview", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "overview" },
  { name: "desktop-patrol", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "patrol" },
  { name: "desktop-stats", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "stats" },
  { name: "desktop-history", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "history" },
  { name: "desktop-task", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "task" },
  { name: "desktop-sheet", width: 1440, height: 900, scenario: "normal", desktop: true, drive: "sheet" },
  { name: "desktop-empty", width: 1440, height: 900, scenario: "empty", desktop: true, drive: "empty" },
  { name: "desktop-read-failed", width: 1440, height: 900, scenario: "read-failed", desktop: true, drive: "providers" },
  { name: "desktop-loading", width: 1440, height: 900, scenario: "loading", desktop: true, drive: "providers" },
  { name: "768-tasks", width: 768, height: 1024, scenario: "normal", drive: null },
  { name: "768-providers", width: 768, height: 1024, scenario: "normal", drive: "providers", gauge: "providers" },
  { name: "768-task", width: 768, height: 1024, scenario: "normal", drive: "task", gauge: "detail" },
  { name: "768-patrol", width: 768, height: 1024, scenario: "normal", drive: "patrol", gauge: "coverage" },
  { name: "834-tasks", width: 834, height: 1112, scenario: "normal", drive: null },
  { name: "834-providers", width: 834, height: 1112, scenario: "normal", drive: "providers", gauge: "providers" },
  { name: "834-task", width: 834, height: 1112, scenario: "normal", drive: "task", gauge: "detail" },
  { name: "834-patrol", width: 834, height: 1112, scenario: "normal", drive: "patrol", gauge: "coverage" },
  { name: "1024-tasks", width: 1024, height: 768, scenario: "normal", drive: null },
  { name: "1024-providers", width: 1024, height: 768, scenario: "normal", drive: "providers", gauge: "providers" },
  { name: "1024-task", width: 1024, height: 768, scenario: "normal", drive: "task", gauge: "detail" },
  { name: "1024-patrol", width: 1024, height: 768, scenario: "normal", drive: "patrol", gauge: "coverage" },
  { name: "1280-tasks", width: 1280, height: 800, scenario: "normal", desktop: true, drive: null },
  { name: "1280-providers", width: 1280, height: 800, scenario: "normal", desktop: true, drive: "providers" },
];

// Legacy bundles predate stats/history layers and the detail sheet; capture
// only the states both bundles have, so a before/after comparison is honest.
const LEGACY_STATES = new Set(["tasks", "providers", "overview", "task", "rail", "desktop-tasks", "desktop-providers", "desktop-overview", "desktop-task", "1280-tasks", "1280-providers"]);

async function drive(page, name) {
  const click = async (selector) => { await page.locator(selector).first().click(); await page.waitForTimeout(120); };
  const tabs = "[data-wb-tabs] [role=tab]";
  if (name === "providers" || name === "empty") {
    if (await page.locator(tabs).count()) await click(tabs + " >> nth=1");
  } else if (name === "overview") {
    await click(tabs + " >> nth=2");
  } else if (name === "patrol" || name === "stats" || name === "history") {
    await click(tabs + " >> nth=2");
    await click('[data-wb-group-button="overview-' + name + '"]');
    await page.waitForSelector(name === "patrol" ? "[data-wb-patrol-layer]" : name === "stats" ? "[data-wb-stats-layer]" : "[data-wb-history-layer]", { timeout: 5000 });
  } else if (name === "task") {
    if (await page.locator(tabs).count()) await click(tabs + " >> nth=0");
    await click("[data-wb-task]");
  } else if (name === "sheet") {
    if (await page.locator(tabs).count()) await click(tabs + " >> nth=0");
    await click("[data-wb-task]");
    await click("[data-tq-action=brief]");
    await page.waitForSelector("[data-wb-sheet]", { timeout: 5000 });
  } else if (name === "toast") {
    if (await page.locator(tabs).count()) await click(tabs + " >> nth=0");
    await click("[data-wb-task]");
    await click("[data-tq-action=brief]");
    await page.waitForSelector("[data-wb-toast]", { timeout: 5000 });
  } else if (name === "sticky") {
    await page.evaluate(() => { const scroller = document.querySelector("[data-wb-scroll]"); if (scroller) scroller.scrollTop = 240; });
    await page.waitForTimeout(200);
  } else if (name === "task-bottom") {
    if (await page.locator(tabs).count()) await click(tabs + " >> nth=0");
    await click("[data-wb-task]");
    await page.evaluate(() => { const scroller = document.querySelector("[data-wb-scroll]"); if (scroller) scroller.scrollTop = scroller.scrollHeight; });
    await page.waitForTimeout(200);
  }
}

async function scrollTopOf(page) {
  return page.evaluate(() => document.querySelector("[data-wb-scroll]")?.scrollTop || 0);
}

async function measureTypography(page) {
  const light = await page.evaluate(typographyInPage);
  await page.evaluate(() => { document.body.dataset.dsDarkTheme = "dark"; });
  await page.waitForTimeout(80);
  const dark = await page.evaluate(typographyInPage);
  await page.evaluate(() => { delete document.body.dataset.dsDarkTheme; });
  return { light, dark };
}

function assertGauge(state, gauge) {
  if (gauge === null) return;
  if (state.gauge === "sidebar") {
    if (state.control === "row-overlap") {
      assert.ok(gauge.intersections.length > 0,
        state.name + ": the detector must still see a deliberate adjacent-row overlap");
      console.log("  CONTROL row overlap detected: " + JSON.stringify(gauge.intersections));
      return;
    }
    assert.equal(gauge.rows.length, 4, state.name + ": four panellist rows are measured");
    assert.deepEqual(gauge.intersections, [], state.name + ": adjacent panellist rows must not intersect");
    for (const row of gauge.containment) {
      assert.equal(row.rowHeight, 36, state.name + ": " + row.name + " keeps the host's 36px row");
      assert.ok(row.titleInside, state.name + ": " + row.name + " label leaves its row");
      assert.ok(row.iconInside, state.name + ": " + row.name + " glyph leaves its row");
      assert.ok(row.alertInside, state.name + ": " + row.name + " alert leaves its row");
    }
    const workbench = gauge.rows.find((row) => row.name === "workbench");
    if (workbench === undefined) return;
    assert.equal(workbench.badgeNodes, 0,
      state.name + ": the row has no numeric badge node; the count is words in the host label");
    if (workbench.rail === false) {
      assert.ok(typeof workbench.titleText === "string" && workbench.titleText.length > 0,
        state.name + ": the wide row keeps a visible label");
      if (state.scenario === "sidebar") {
        assert.ok(/告警/.test(workbench.titleText),
          state.name + ": an alert is written into the label (got " + workbench.titleText + ")");
      }
      if (state.scenario === "sidebar-quiet") {
        assert.doesNotMatch(workbench.titleText, /告警|alert/,
          state.name + ": zero alerts add no suffix (got " + workbench.titleText + ")");
      }
    } else {
      assert.ok(workbench.alert !== null, state.name + ": the rail keeps the non-numeric alert mark");
    }
    return;
  }
  if (state.gauge === "detail") {
    if (legacy && !gauge.present) return;
    assert.equal(gauge.present, true, state.name + ": the closing report is rendered");
    assert.ok(gauge.gap !== null && gauge.gap >= 8,
      state.name + ": the Full log row must clear the closing-report card by 8px (got " + gauge.gap + ")");
    assert.ok(gauge.pillGap !== null && gauge.pillGap >= 8,
      state.name + ": the Full log pill must clear the closing-report card by 8px (got " + gauge.pillGap + ")");
    assert.equal(gauge.clipped, 0, state.name + ": the closing report must not clip its last line");
    assert.equal(gauge.widthOverflow, 0, state.name + ": the closing report must not overflow horizontally");
    return;
  }
  if (state.gauge === "coverage") {
    assert.equal(gauge.present, true, state.name + ": the patrol coverage tables are rendered");
    assert.ok(gauge.blocks.length >= 2, state.name + ": both coverage tables are rendered");
    assert.deepEqual(gauge.sideBySide, [], state.name + ": coverage tables must stack in one column on a phone");
    assert.equal(gauge.widthOverflow, 0, state.name + ": the coverage table must not overflow horizontally");
    assert.ok(gauge.narrowest >= (gauge.cov === null ? 0 : gauge.cov.w) - 2,
      state.name + ": a coverage table is narrower than its container");
    return;
  }
  if (state.gauge === "providers") {
    assert.equal(gauge.present, true, state.name + ": provider rows are rendered");
    assert.deepEqual(gauge.collisions, [], state.name + ": provider name/value pairs must not intersect");
    for (const row of gauge.rows) {
      assert.ok(row.widthOverflow <= 1, state.name + ": provider " + row.key + " overflows horizontally by " + row.widthOverflow + "px");
    }
  }
}

async function main() {
  if (!fs.existsSync(bundlePath)) throw new Error("missing bundle: " + bundlePath);
  fs.mkdirSync(shotsDir, { recursive: true });
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const { chromium, webkit } = require("playwright");
  const server = await serve();
  const origin = "http://127.0.0.1:" + server.address().port;
  const selected = STATES.filter((state) => {
    if (only !== null && !only.has(state.name)) return false;
    if (legacy && !LEGACY_STATES.has(state.name)) return false;
    if (!expectAll && !legacy) return true;
    return true;
  });
  const results = [];
  const typography = [];
  const gaugeFailures = [];
  let browserFailures = 0;
  try {
    for (const engineName of ["webkit", "chromium"]) {
      const browser = await (engineName === "webkit" ? webkit : chromium).launch();
      const engineStates = selected.filter((state) => {
        if (engineName === "webkit") return !state.desktop;
        return state.desktop === true;
      });
      for (const state of engineStates) {
        const context = await browser.newContext({
          viewport: { width: state.width, height: state.height },
          isMobile: engineName === "webkit" && state.width < 768,
          hasTouch: engineName === "webkit" && state.width < 768,
          deviceScaleFactor: 1,
          locale: "zh-CN",
          colorScheme: state.theme === "dark" ? "dark" : "light",
        });
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", (error) => errors.push(String(error)));
        const query = "?scenario=" + encodeURIComponent(state.scenario) + "&theme=" + (state.theme || "light");
        await page.goto(origin + "/" + query, { waitUntil: "load" });
        try {
          await page.waitForFunction(() => window.__workbenchReady && window.__workbenchReady(), null, { timeout: 8000 });
        } catch (error) {
          console.error("state " + state.name + " failed to become ready", errors);
          console.error((await page.content()).slice(0, 1200));
          throw error;
        }
        await page.waitForTimeout(120);
        if (state.drive) await drive(page, state.drive);
        await page.waitForTimeout(120);
        const scrollTop = await scrollTopOf(page);
        const geometry = await page.evaluate(collectInPage, { scrollTop });
        const safeArea = await page.evaluate(() => {
          const nodes = [
            ...document.querySelectorAll("[data-wb-panel='tasks'] [class*='_wb-queue-body']"),
            ...document.querySelectorAll("[data-wb-providers]"),
            ...document.querySelectorAll("[data-wb-overview]"),
          ];
          const reserves = nodes.map((node) => ({
            className: typeof node.className === "string" ? node.className : "",
            paddingBottom: Number.parseFloat(getComputedStyle(node).paddingBottom) || 0,
          }));
          return { reserves, max: reserves.reduce((max, row) => Math.max(max, row.paddingBottom), 0) };
        });
        if (state.width < 768 && safeArea.reserves.length > 0) {
          assert.ok(safeArea.max >= 72,
            state.name + ": the phone scroll body must reserve the 72px host/safe-area bottom (got "
            + JSON.stringify(safeArea.reserves) + ")");
        }
        let rail = null;
        if (state.name === "rail") {
          rail = await page.evaluate(() => {
            const badge = document.querySelector("[data-wb-badge]");
            const alert = document.querySelector("[data-wb-rail-alert]");
            return { badge: badge !== null, alert: alert !== null };
          });
          assert.equal(rail.badge, false, "rail state has no numeric badge");
          assert.equal(rail.alert, true, "rail state keeps the alert !");
        }
        const gauge = state.gauge ? await page.evaluate(gaugeInPage, state.gauge) : null;
        let gaugeError = null;
        try {
          assertGauge(state, gauge);
        } catch (error) {
          gaugeError = error.message;
          gaugeFailures.push({ state: state.name, engine: engineName, message: error.message });
          console.error("  GAUGE FAIL " + error.message);
        }
        const shot = path.join(shotsDir, engineName + "-" + state.name + ".png");
        await page.screenshot({ path: shot, fullPage: false });
        const failures = state.control === undefined ? geometry.failures : [];
        const record = {
          name: state.name, engine: engineName, width: state.width, height: state.height,
          scenario: state.scenario, theme: state.theme || "light", scrollTop, control: state.control,
          blocks: geometry.blocks.length, failures, allowed: geometry.allowed,
          gauge, gaugeError, safeArea, rail, errors, screenshot: shot,
        };
        results.push(record);
        browserFailures += failures.length;
        if ((state.drive === "providers" || state.name === "providers") && !legacy) {
          typography.push({ state: state.name, engine: engineName, ...(await measureTypography(page)) });
        }
        console.log([engineName, state.name, state.width + "x" + state.height,
          "blocks=" + geometry.blocks.length, "overlaps=" + failures.length,
          "allowed=" + geometry.allowed.length, "errors=" + errors.length].join(" "));
        for (const failure of (state.control === undefined ? geometry.failures : []).slice(0, 8)) {
          console.log("  OVERLAP " + failure.area + "px2 " + failure.a + " <> " + failure.b + "  " + JSON.stringify(failure.text));
        }
        await context.close();
      }
      await browser.close();
    }
  } finally {
    server.close();
  }

  // Typography invariants: one role, one computed reading in every state/theme.
  const typographyChecks = [];
  for (const sample of typography) {
    for (const mode of ["light", "dark"]) {
      const rows = sample[mode].rows.filter((row) => row.name !== null);
      for (const field of ["name", "primary", "meta"]) {
        const values = new Set(rows.map((row) => row[field].fontSize + "/" + row[field].lineHeight + "/" + row[field].fontWeight));
        typographyChecks.push({
          engine: sample.engine, state: sample.name, mode, field,
          values: [...values], states: rows.map((row) => row.state), ok: values.size <= 1,
        });
      }
    }
  }
  const typographyFailures = typographyChecks.filter((check) => !check.ok);

  const payload = {
    generatedAt: new Date().toISOString(),
    bundle: bundlePath,
    bundleSha256: bundleSha,
    legacy,
    summary: {
      states: results.length,
      passing: results.filter((record) => record.failures.length === 0).length,
      failing: results.filter((record) => record.failures.length > 0).map((record) => record.name),
      overlaps: browserFailures,
      allowedOverlays: results.reduce((sum, record) => sum + record.allowed.length, 0),
      pageErrors: results.reduce((sum, record) => sum + record.errors.length, 0),
      typographyChecks: typographyChecks.length,
      typographyFailures: typographyFailures.length,
      gaugeChecks: results.filter((record) => record.gauge !== null).length,
      gaugeFailures: gaugeFailures.length,
    },
    gaugeFailures,
    results,
    typography: { checks: typographyChecks, failures: typographyFailures, samples: typography },
  };
  fs.writeFileSync(outPath, JSON.stringify(payload, null, 1));

  console.log("\n| state | engine | viewport | blocks | overlaps | allowed z-axis |");
  console.log("| --- | --- | --- | --- | --- | --- |");
  for (const record of results) {
    console.log("| " + record.name + " | " + record.engine + " | " + record.width + "x" + record.height
      + " | " + record.blocks + " | " + record.failures.length + " | " + record.allowed.length + " |");
  }
  console.log("overlaps=" + browserFailures + " gaugeFailures=" + gaugeFailures.length
    + " typographyFailures=" + typographyFailures.length
    + " pageErrors=" + payload.summary.pageErrors + " json=" + outPath);
  if (browserFailures > 0) {
    console.error("\nFAIL: " + browserFailures + " overlapping visible block pair(s)");
    process.exitCode = 1;
  }
  if (gaugeFailures.length > 0) {
    console.error("\nFAIL: " + gaugeFailures.length + " explicit geometry contract(s)");
    console.error(JSON.stringify(gaugeFailures.slice(0, 8), null, 1));
    process.exitCode = 1;
  }
  if (typographyFailures.length > 0) {
    console.error("\nFAIL: " + typographyFailures.length + " type role(s) change across states/themes");
    console.error(JSON.stringify(typographyFailures.slice(0, 8), null, 1));
    process.exitCode = 1;
  }
  assert.equal(payload.summary.pageErrors, 0, "no page errors while rendering the states");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
