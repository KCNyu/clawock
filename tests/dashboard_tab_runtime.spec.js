#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const DETAIL_PATH = "/assets/js/dashboard.render.js";
// Every detail tab: all of them share one lazy bundle and one full-dashboard
// fetch, and every one of them is walked by the missing-number sweep below.
const TABS = ["drill", "risk", "market", "plan", "reflect"];
// Everything after the first paint reads the data branch instead of this origin
// (#367). Every page here stubs it: left unrouted it would put a live call to
// raw.githubusercontent.com on CI's critical path, and the bytes it would return
// are the ones already sitting in assets/data.
const LIVE_DATA_ORIGIN = "https://raw.githubusercontent.com/KCNyu/clawock/data-plane/";
const MIME = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function serveWorkspace() {
  return http.createServer((request, response) => {
    const urlPath = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    const relative = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
    const sourceRoot = relative.startsWith("assets/data/")
      ? ROOT
      : path.resolve(ROOT, "site");
    const filename = path.resolve(sourceRoot, relative);
    if (!filename.startsWith(sourceRoot + path.sep) || !fs.existsSync(filename) || fs.statSync(filename).isDirectory()) {
      response.writeHead(404).end("not found");
      return;
    }
    response.writeHead(200, {
      "content-type": MIME[path.extname(filename)] || "application/octet-stream",
      "cache-control": "no-store",
    });
    fs.createReadStream(filename).pipe(response);
  });
}

// Activate one dashboard view the way a reader does: click its tab.
async function clickTab(page, tab) {
  await page.click(`.tab-btn[data-tab="${tab}"]`);
}

// Records which data files were served from the live branch, so a test can
// assert both that the first paint never went there and that a poll always does.
async function stubLiveOrigin(page, options = {}) {
  const served = [];
  // 首帧的 overview.json 走同源（index.html 里那条 head 抢跑的 fetch），
  // 只拦 LIVE origin 的话 patch 会漏掉第一帧、断言跑在真实数据上。
  if (options.patch) {
    await page.route("**/assets/data/*.json", async route => {
      const name = path.basename(new URL(route.request().url()).pathname);
      const file = path.resolve(ROOT, "assets/data", name);
      if (!fs.existsSync(file)) return route.fallback();
      const patched = options.patch(name, JSON.parse(fs.readFileSync(file, "utf8")));
      if (!patched) return route.fallback();
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify(patched),
      });
    });
  }
  await page.route(LIVE_DATA_ORIGIN + "**", async route => {
    const name = path.basename(new URL(route.request().url()).pathname);
    served.push(name);
    if (options.fail) return route.abort("failed");
    const file = path.resolve(ROOT, "assets/data", name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: "not found" });
    let body = fs.readFileSync(file, "utf8");
    // 有些断言要的是「某个形状的 payload 会被渲染成什么」，而不是今天这份
    // 数据长什么样。patch 让用例自己造那个形状，免得闸随当日数据时灵时不灵。
    if (options.patch) {
      const patched = options.patch(name, JSON.parse(body));
      if (patched) body = JSON.stringify(patched);
    }
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      },
      body,
    });
  });
  return served;
}

function observe(page) {
  const result = { detailRequests: 0, fullRequests: 0, overviewRequests: 0, failures: [], errors: [] };
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === DETAIL_PATH) result.detailRequests += 1;
    // Counted on either origin: the point of the assertion is that detail tabs
    // share one request for the full document, not where it was served from.
    if (pathname.endsWith("/assets/data/dashboard.json")) result.fullRequests += 1;
    // Same either-origin rule: the cold load must fetch the LCP projection
    // exactly once no matter who started it (head boot fetch vs loadData).
    if (pathname.endsWith("/assets/data/overview.json")) result.overviewRequests += 1;
  });
  page.on("response", response => {
    const url = new URL(response.url());
    if (url.hostname === "127.0.0.1" && response.status() >= 400) {
      result.failures.push(`${response.status()} ${url.pathname}`);
    }
  });
  page.on("pageerror", error => result.errors.push(error.message));
  return result;
}

async function waitForData(page) {
  await page.waitForFunction(() => {
    const panel = document.querySelector('.panel[data-panel="hero"]');
    return DATA?.projection === "overview" &&
      !panel?.hasAttribute("aria-busy") &&
      !panel?.querySelector(".card.is-pending");
  });
}

async function waitForTab(page, tab) {
  // A bare `waitForFunction` timeout says only "30s elapsed", and the four
  // conditions it waits on (panel active / core data / aria-busy / a pending
  // card) fail for completely different reasons. Report which one held. This
  // was added while moving the switcher into the picker, where a mis-aimed
  // synthetic click produced exactly this timeout three times.
  const readState = () => page.evaluate((t) => {
    const d = (typeof DATA === "undefined") ? null : DATA;
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    const snaps = d && d.snapshots;
    return {
      dataLoaded: !!d,
      projection: (d && d.projection) || null,
      snapshots: Array.isArray(snaps) ? `${snaps.length} rows` : typeof snaps,
      rowsHaveDate: Array.isArray(snaps) && snaps.length
        ? snaps.slice(0, 3).every(r => r && !Array.isArray(r) && typeof r.date === "string")
        : null,
      panelActive: panel ? panel.classList.contains("active") : null,
      ariaBusy: panel ? panel.hasAttribute("aria-busy") : null,
      pendingCard: panel ? !!panel.querySelector(".card.is-pending") : null,
      loadError: panel ? !!panel.querySelector(".panel-load-retry") : null,
      siteMenuOpen: !!document.getElementById("site-menu")?.open,
      activeTab: document.querySelector(".tab-btn.active")?.dataset.tab || null,
    };
  }, tab).catch(e => ({ probeFailed: e.message }));

  try {
    await page.waitForFunction(tab => {
      const panel = document.querySelector(`.panel[data-panel="${tab}"]`);
      // Rows, not merely an array (#1215): the equity series ships column-packed
      // and `Array.isArray` is true of both shapes, so the old check would have
      // gone on passing with the loader's unpack removed and every chart blank.
      const snaps = DATA?.snapshots;
      const coreReady = tab === "hero"
        ? DATA?.projection === "overview"
        : Array.isArray(snaps) && snaps.length > 0 &&
          snaps.every(row => row && typeof row === "object" &&
                      !Array.isArray(row) && typeof row.date === "string");
      return panel?.classList.contains("active") &&
        coreReady &&
        !panel.hasAttribute("aria-busy") &&
        !panel.querySelector(".card.is-pending");
    }, tab);
  } catch (error) {
    throw new Error(
      `waitForTab(${tab}) timed out: ${JSON.stringify(await readState())} — ${error.message}`);
  }
}

async function dispatchTouch(session, type, points) {
  await session.send("Input.dispatchTouchEvent", { type, touchPoints: points });
}

async function testRuntime(browser, base) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const state = observe(page);
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await page.waitForFunction(() =>
    document.getElementById("latest-brief-link")?.getAttribute("href")?.startsWith("memory/"));
  const latestBrief = await page.evaluate(() => ({
    date: document.getElementById("latest-brief-date").textContent.trim(),
    summary: document.getElementById("latest-brief-summary").textContent.trim(),
    href: document.getElementById("latest-brief-link").getAttribute("href"),
  }));
  const projection = JSON.parse(fs.readFileSync(
    path.resolve(ROOT, "assets/data/brief_projection.json"), "utf8"));
  assert(latestBrief.date.startsWith(projection.as_of),
    `latest brief card shows ${latestBrief.date}, expected ${projection.as_of}`);
  assert.equal(latestBrief.summary, projection.portfolio_judgment.assessment,
    "latest brief card does not expose the brief's current assessment");
  assert.equal(latestBrief.href, `memory/${projection.as_of}-pre-open.html`,
    "latest brief card does not link straight to the dated brief");
  assert.equal(state.detailRequests, 0, "Overview downloaded the detail renderer");
  assert.equal(state.fullRequests, 0, "Overview downloaded the full dashboard document");
  // The head boot fetch and the loadData() fetch must dedupe into one request:
  // two downloads of the LCP projection would mean the adoption handoff broke
  // and every cold visitor pays the projection twice.
  assert.equal(state.overviewRequests, 1,
    "cold load fetched the Overview projection more than once");
  await page.evaluate(() => {
    const original = window.render;
    window.__coreRenderCalls = 0;
    window.render = (...args) => {
      window.__coreRenderCalls += 1;
      return original(...args);
    };
  });
  await page.evaluate(() => loadData(false));
  assert.equal(await page.evaluate(() => window.__coreRenderCalls), 0,
    "unchanged Overview poll replayed the core renderer");
  // The boot handle is gone after the cold load, so this poll does its own fetch.
  assert.equal(state.overviewRequests, 2,
    "the poll did not issue its own Overview request (boot handle leaked?)");

  for (const tab of TABS) {
    await clickTab(page, tab);
    await waitForTab(page, tab);
  }
  assert.equal(state.detailRequests, 1, "detail tabs did not share one bundle request");
  assert.equal(state.fullRequests, 1, "detail tabs did not share one full dashboard request");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);

  const deep = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const deepState = observe(deep);
  await stubLiveOrigin(deep);
  await deep.goto(base + "#reflect", { waitUntil: "domcontentloaded" });
  await waitForTab(deep, "reflect");
  assert.equal(deepState.detailRequests, 1, "deep link did not load one detail bundle");
  assert.equal(deepState.fullRequests, 1, "deep link did not load one full dashboard");
  assert.deepEqual(deepState.failures, []);
  assert.deepEqual(deepState.errors, []);

  const rapid = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const rapidState = observe(rapid);
  await stubLiveOrigin(rapid);
  await rapid.route(`**${DETAIL_PATH}`, async route => {
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.continue();
  });
  await rapid.goto(base, { waitUntil: "networkidle" });
  await waitForData(rapid);
  await rapid.evaluate(tabs => tabs.forEach(tab =>
    document.querySelector(`.tab-btn[data-tab="${tab}"]`).click()), TABS);
  // The click order above makes the LAST tab in `TABS` the active one, and this
  // used to be spelled "reflect" — the tab that happened to be last. Adding a tab
  // then waited on a panel the test had already navigated away from, which reads
  // as a timeout in the runtime, not as the stale assumption it is.
  await waitForTab(rapid, TABS[TABS.length - 1]);
  assert.equal(rapidState.detailRequests, 1, "rapid activation duplicated the bundle request");
  assert.equal(rapidState.fullRequests, 1, "rapid activation duplicated the full dashboard request");
  assert.deepEqual(rapidState.failures, []);
  assert.deepEqual(rapidState.errors, []);

  const mismatch = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const mismatchState = observe(mismatch);
  await stubLiveOrigin(mismatch);
  let fullAttempt = 0;
  await mismatch.route(/\/assets\/data\/dashboard\.json(?:\?.*)?$/, async route => {
    fullAttempt += 1;
    if (fullAttempt > 1) return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.generated_at = "1999-01-01T00:00:00Z";
    await route.fulfill({
      status: response.status(),
      headers: { ...response.headers(), "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  });
  await mismatch.goto(base + "#risk", { waitUntil: "domcontentloaded" });
  await waitForTab(mismatch, "risk");
  assert.equal(fullAttempt, 2,
    "generation mismatch was not rejected and retried without cache");
  assert.deepEqual(mismatchState.failures, []);
  assert.deepEqual(mismatchState.errors, []);
}

// The publisher reads the FX cache offline and still serves one the daily
// refresh stopped updating — the peg keeps that a small error — but the hero's
// provenance line has to say so instead of looking like a fresh quote (#1781).
async function testAStaleFxRateSaysSoOnTheHero(browser, base) {
  const warning = "USDHKD cache is 121h old (not refreshed within 96h); using the stale cached rate";
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  const state = observe(page);
  await stubLiveOrigin(page, {
    patch: (_name, payload) => payload.fx ? ({
      ...payload,
      fx: { ...payload.fx, stale: true, age_hours: 121.4, warning },
    }) : null,
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  const fx = page.locator("#fx-rate-usd");
  assert.match(await fx.textContent(), /USDHKD \d\.\d{4} .*⚠ 缓存 121h 未刷新$/,
    "a stale FX cache rendered like a fresh quote");
  assert.equal(await fx.getAttribute("title"), warning);
  assert.deepEqual(state.errors, []);
  await context.close();

  const freshContext = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const fresh = await freshContext.newPage();
  await stubLiveOrigin(fresh, {
    patch: (_name, payload) => payload.fx ? ({
      ...payload,
      fx: { ...payload.fx, stale: false, age_hours: 9.5, warning: null },
    }) : null,
  });
  await fresh.goto(base, { waitUntil: "networkidle" });
  await waitForData(fresh);
  assert.doesNotMatch(await fresh.locator("#fx-rate-usd").textContent(), /⚠/,
    "a cache inside its tolerance was flagged as degraded");
  await freshContext.close();
}

async function testMissingFxDoesNotFabricateCombinedValues(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const state = observe(page);
  await stubLiveOrigin(page, {
    patch: (_name, payload) => ({
      ...payload,
      fx: { ...(payload.fx || {}), usdhkd: null },
    }),
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  assert.equal(await page.locator("#fx-rate-usd").textContent(), "FX unavailable");

  await clickTab(page, "reflect");
  await waitForTab(page, "reflect");
  await page.waitForFunction(() => window.echarts &&
    window.echarts.getInstanceByDom(document.getElementById("chart-daily-pnl")) &&
    window.echarts.getInstanceByDom(document.getElementById("chart-realized")));

  const values = await page.evaluate(() => {
    const option = id => window.echarts.getInstanceByDom(document.getElementById(id)).getOption();
    const daily = option("chart-daily-pnl").series;
    const realized = option("chart-realized").series;
    return {
      floatPct: document.getElementById("kpi-floatpct").textContent.trim(),
      maxDrawdown: document.getElementById("kpi-maxdd").textContent.trim(),
      bestDayDate: document.getElementById("kpi-bestday-date").textContent.trim(),
      worstDayDate: document.getElementById("kpi-worstday-date").textContent.trim(),
      combinedAssets: document.getElementById("ext-region-combined").textContent,
      daily: daily.flatMap(s => s.data.map(v => v && typeof v === "object" ? v.value : v)),
      realizedHk: realized.map(s => s.data[1]),
    };
  });

  assert.equal(values.floatPct, "—", "Reflect fabricated a combined floating return without FX");
  assert.equal(values.maxDrawdown, "—", "Reflect fabricated a combined drawdown without FX");
  assert.equal(values.bestDayDate, "no data", "the best-day tile dated a day it could not judge");
  assert.equal(values.worstDayDate, "no data", "the worst-day tile dated a day it could not judge");
  assert(!values.combinedAssets.includes("真实总资产"),
    "the combined asset card silently converted HKD without FX");
  assert(values.daily.length > 0 && values.daily.every(v => v == null),
    "the combined daily P&L chart silently converted HKD without FX");
  assert(values.realizedHk.length > 0 && values.realizedHk.every(v => v == null),
    "the realized chart silently converted its HK leg without FX");

  // Not fabricating is half the rule; the other half is saying why the numbers
  // are gone. An unexplained empty chart reads as "no data", not "no FX".
  const notes = await page.evaluate(() => {
    const option = id => window.echarts.getInstanceByDom(document.getElementById(id)).getOption();
    const bm = document.getElementById("benchmark-stale");
    return {
      equityLine: bm.style.display === "none" ? "" : bm.textContent,
      daily: JSON.stringify(option("chart-daily-pnl").graphic || []),
      realized: JSON.stringify(option("chart-realized").graphic || []),
    };
  });
  assert(notes.equityLine.includes("汇率缺失"),
    `the equity card did not say why the combined curve is empty: ${JSON.stringify(notes.equityLine)}`);
  assert(notes.daily.includes("汇率缺失"),
    "the combined daily P&L chart went blank without naming the missing FX rate");
  assert(notes.realized.includes("汇率缺失"),
    "the realized chart dropped its HK leg without naming the missing FX rate");
  assert.deepEqual(state.errors, [], `missing FX raised page errors: ${state.errors.join(" | ")}`);
  await context.close();
}

async function testNewsDigestGeneratedTimeUsesHkt(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    timezoneId: "America/Los_Angeles",
  });
  const page = await context.newPage();
  await stubLiveOrigin(page, {
    patch: (name, payload) => {
      if (name !== "us_news_digest.json") return null;
      return {
        ...payload,
        generated_at: "2026-09-20T03:37:35.717Z",
        digest_markdown: "### Test\n- material update",
      };
    },
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "market");
  await waitForTab(page, "market");
  await page.waitForFunction(() =>
    document.querySelector("#news-digest .digest-meta")?.textContent.includes("generated:"));

  const meta = (await page.locator("#news-digest .digest-meta").textContent()).trim();
  assert(meta.includes("2026/9/20 11:37:35"),
    `news digest generated time did not render in HKT: ${meta}`);
  assert(!meta.includes("2026/9/19"),
    `news digest generated time leaked the viewer's local date: ${meta}`);
  // An unlabelled timestamp still reads as local time to a viewer outside HKT —
  // the same " HKT" suffix every other timestamp on this page carries.
  assert(meta.endsWith("HKT"),
    `news digest generated time did not name its zone: ${meta}`);
  await context.close();
}

async function testCurrentHoldingsOwnDecisionMatrixMembership(browser, base) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const state = observe(page);
  await stubLiveOrigin(page);
  await page.route(/\/assets\/data\/brief_projection\.json(?:\?.*)?$/, async route => {
    const payload = JSON.parse(fs.readFileSync(
      path.resolve(ROOT, "assets/data/brief_projection.json"), "utf8"));
    const dashboard = JSON.parse(fs.readFileSync(
      path.resolve(ROOT, "assets/data/dashboard.json"), "utf8"));
    const active = [...(dashboard.holdings?.us || []), ...(dashboard.holdings?.hk || [])]
      .filter(row => row && row.is_active !== false && (row.shares ?? 0) > 0);
    assert(active.length > 1, "fixture needs current holdings");
    // Remove a genuinely active name and add a zero-share name. The old
    // implementation rendered the sidecar verbatim, so it both retained
    // CLOSED and silently dropped the active name.
    payload.tickers = (payload.tickers || [])
      .filter(row => row.ticker !== active[0].ticker)
      .concat([{
        ticker: "CLOSED", leg: "US", facts: {}, technical: {}, risk: {},
        status: { rank: 5, label: "stale", state: "neutral" },
      }]);
    payload.add_campaign = {
      status: "current", packet_generated_at: "2026-08-13T08:00:00+08:00",
      diagnostics: { held_names: active.length, authority_candidate_count: 0,
        observed_candidate_count: 2, observed_idea_count: 1,
        early_exploration_ready_count: 0, early_exploration_ready_idea_count: 0,
        tier_counts: { validated: 0, exploration: 0, none: active.length } },
      candidates: [
        { ticker: active[0].ticker, leg: "US", state: "insufficient_evidence",
          tier: "none", evidence_families: [], authority_blockers:
          ["independent_evidence_families"], execution_blockers: [],
          target_tranche_level: 0, max_add_shares: 0 },
        { ticker: active[1].ticker, leg: "HK", state: "waiting_timing",
          source_ticker: active[1].ticker, is_proxy: false,
          tier: "exploration", evidence_families:
          ["price_relative", "point_in_time_information"],
          sources: ["factor", "information"], authority_blockers: [],
          execution_blockers: [], target_tranche_level: 0.25, max_add_shares: 1 },
      ],
      run_card: { run_id: "add_alpha_walkforward-fixture", coverage: {
        factor_dates: 11, information_dates: 12, overlap_dates: 10,
        prospective_information_dates: 0,
        authority_classifications: { none: 186, exploration: 6, validated: 0 },
        early_trend: { observed_candidates: 2, information_confirmed: 1,
          exploration_ready: 0 },
      }, markets: {
        us: { t1: { n: 4, mean_return: .03, hit_rate: 1 },
          t5: { n: 0, status: "collecting" }, t20: { n: 0, status: "collecting" } },
        hk: { t1: { n: 2, mean_return: .01, hit_rate: .5 },
          t5: { n: 0, status: "collecting" }, t20: { n: 0, status: "collecting" } },
      }, early_trend: {
        us: { observed: { t1: { n: 1, mean_return: .02, hit_rate: 1 },
          t5: { n: 1, mean_return: .05, hit_rate: 1 } } },
        hk: { observed: { t1: { n: 1, mean_return: -.01, hit_rate: 0 },
          t5: { n: 0, status: "collecting" } } },
      }},
    };
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify(payload) });
  });
  await page.goto(base + "#drill", { waitUntil: "domcontentloaded" });
  await waitForTab(page, "drill");

  const membership = await page.evaluate(() => {
    const active = [...(DATA.holdings?.us || []), ...(DATA.holdings?.hk || [])]
      .filter(row => row && row.is_active !== false && (row.shares ?? 0) > 0)
      .map(row => row.ticker).sort();
    const rendered = [...document.querySelectorAll("#book-tbody tr.book-row td:first-child .ticker")]
      .map(cell => cell.textContent.trim()).sort();
    return { active, rendered };
  });
  assert.deepEqual(membership.rendered, membership.active,
    "stale brief projection still owns current-holdings membership");
  assert(!membership.rendered.includes("CLOSED"), "sold-out projection row survived");
  assert.match(await page.locator("#add-campaign-card").innerText(), /US ·|HK ·/,
    "campaign did not keep markets separate");
  assert.match(await page.locator("#add-campaign-card").innerText(), /collecting · n=0/,
    "zero sample was rendered as performance instead of collecting");
  assert.match(await page.locator("#add-campaign-card").innerText(), /early candidate replay/,
    "early candidate evidence stayed hidden from the rendered campaign");
  assert.match(await page.locator("#add-campaign-card").innerText(), /early ideas 1/,
    "underlying-deduplicated early idea count was not rendered");

  await clickTab(page, "reflect");
  await waitForTab(page, "reflect");
  const legacy = page.locator("#plan-bucket-bars .name", {
    hasText: "add_only_on_trigger",
  });
  if (await legacy.count()) assert.match(await legacy.first().innerText(), /legacy\/mixed/);
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await page.close();
}

async function testLiveDataOrigin(browser, base) {
  // The first paint must stay on this origin. `overview.json` is the only fetch
  // on the LCP path, so a second origin's handshake there is paid by every cold
  // visit — Lighthouse included — to save a wait nobody is watching yet.
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const state = observe(page);
  const served = await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  assert.deepEqual(served, [], "the first paint reached across origins for its data");

  // Every poll after it must read the branch, which is ~14 minutes ahead of
  // this origin during a session (#367). A poll that keeps reading Pages is the
  // regression this whole change exists to prevent.
  await page.evaluate(() => loadData(false));
  assert.deepEqual(served, ["overview.json"],
    "the background poll did not read the data branch");

  // The full document has to follow overview.json across, or the two halves of
  // one generation come from origins ~14 minutes apart and never line up.
  await clickTab(page, "risk");
  await waitForTab(page, "risk");
  assert.ok(served.includes("dashboard.json"),
    "the full document was not read from the data branch");
  assert.equal(state.fullRequests, 1, "the full document was fetched more than once");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await page.close();

  // A data branch we cannot reach must cost one attempt, not one per poll, and
  // must leave a working page behind.
  const offline = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const offlineState = observe(offline);
  const attempts = await stubLiveOrigin(offline, { fail: true });
  await offline.goto(base, { waitUntil: "networkidle" });
  await waitForData(offline);
  await offline.evaluate(() => loadData(false));
  // Asserted here, before the next poll succeeds and repairs the label: the one
  // honest statement on screen is how old the generation being rendered is, and
  // a failed background poll must not overwrite it with a string that says
  // nothing about it.
  assert.match(await offline.evaluate(() =>
    document.getElementById("last-updated").textContent), /生成于/,
    "a failed poll replaced the age of the generation still on screen");
  // Three polls, not two. The second falls back and succeeds, and it is the
  // third that catches a fallback which forgets — re-promoting the dead origin
  // after every recovery makes every other poll fail.
  await offline.evaluate(() => loadData(false));
  await offline.evaluate(() => loadData(false));
  assert.equal(attempts.length, 1,
    "an unreachable data branch was retried on every poll instead of being dropped");
  await waitForData(offline);
  assert.deepEqual(offlineState.failures, []);
  assert.deepEqual(offlineState.errors, []);
  await offline.close();
}

async function testEquityTouch(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  const state = observe(page);
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  // Equity Curve 已从 Overview 挪进 Reflect（首屏曲线减负），触屏契约跟着卡片走。
  await clickTab(page, "reflect");
  await waitForTab(page, "reflect");
  await page.locator(".native-equity-canvas").scrollIntoViewIfNeeded();
  const box = await page.locator(".native-equity-canvas").boundingBox();
  assert(box, "equity canvas has no layout box");
  const session = await context.newCDPSession(page);
  const y = box.y + box.height / 2;

  await dispatchTouch(session, "touchStart", [{ x: box.x + box.width / 2, y }]);
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForTimeout(100);
  assert(await page.locator(".native-equity-tooltip").isVisible(), "chart tap did not open its tooltip");

  await page.locator('.mkt-seg-btn[data-mkt="hk"]').first().click();
  await page.waitForFunction(() =>
    document.querySelector("#equity-title")?.textContent.includes("港股 HKD"));
  await dispatchTouch(session, "touchStart", [{ x: box.x + box.width / 2, y }]);
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForTimeout(100);
  const hkTooltip = await page.locator(".native-equity-tooltip").innerText();
  assert.match(hkTooltip, /回撤:\s*(?:−?HK\$[\d,]+|[-\d.]+%)/,
    "HK drawdown still rendered as an empty dash");
  assert.match(hkTooltip, /% 不适用/,
    "negative-profit HK drawdown did not explain its amount fallback");

  // Reflect 已是 pager 最后一页：向左滑没有下一页，改为向右滑回上一页（plan），
  // 验证的仍是「离开图表所在页后，悬停/点选留下的 tooltip 必须清掉」。
  const xs = [45, 100, 150, 200, 250, 300, box.x + box.width - 5];
  await dispatchTouch(session, "touchStart", [{ x: xs[0], y }]);
  for (const x of xs.slice(1)) {
    await dispatchTouch(session, "touchMove", [{ x, y }]);
    await page.waitForTimeout(20);
  }
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForFunction(() => {
    const pager = document.getElementById("pager");
    const panel = document.querySelector('.panel[data-panel="plan"]');
    return document.querySelector(".tab-btn.active")?.dataset.tab === "plan" &&
      Math.abs(panel.getBoundingClientRect().left - pager.getBoundingClientRect().left) <= 1;
  }, null, { polling: "raf", timeout: 5000 });
  assert.equal(await page.locator(".native-equity-tooltip").isVisible(), false,
    "pager swipe left a stale chart tooltip");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await context.close();
}

// `currentTab()` used to read pager.scrollLeft/clientWidth, which forces layout,
// and the hero render loop calls it between renderers — right after each one's
// DOM writes. That interleave cost 162ms of the 1,016ms spent in layout on a
// mobile startup profile (#442). It now reads an index updated only by explicit
// navigation or after native scrolling settles.
//
// The guard exists to stop a render in flight when the user navigates away, so
// "it no longer forces layout" is only half of what has to hold: the cache must
// also still tell the truth about where the pager is.
async function testTabGuardWithoutForcedLayout(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 412, height: 823 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  // 1. A full hero render must not read the pager's geometry at all. Counting on
  //    the element shadows the prototype getter, so this measures real accesses
  //    rather than trusting the source.
  const reads = await page.evaluate(async () => {
    const pager = document.getElementById("pager");
    const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, "scrollLeft");
    let count = 0;
    Object.defineProperty(pager, "scrollLeft", {
      configurable: true,
      get() { count += 1; return descriptor.get.call(this); },
    });
    loadData(false);
    await new Promise(resolve => setTimeout(resolve, 1500));
    delete pager.scrollLeft;
    return count;
  });
  assert.equal(reads, 0,
    `hero render forced ${reads} layout-inducing read(s) of pager.scrollLeft`);

  // 2. The guard must observe a tab change immediately. This is stricter than
  //    the geometry was: scrollTo is smooth, so scrollLeft kept reporting the
  //    OLD tab for the length of the animation, and the render it was supposed
  //    to abort carried on until the scroll caught up.
  const afterGoTo = await page.evaluate(() => {
    goToTab("risk");
    return currentTab();
  });
  assert.equal(afterGoTo, "risk", "currentTab() did not follow goToTab synchronously");

  // 3. And it must follow a scroll the code did not initiate once the browser
  //    says native momentum + snap have settled. Live gesture frames deliberately
  //    do no application-state or layout work.
  //
  //    Wait for the browser to emit the instant navigation's scroll event so
  //    the next write starts from a fully committed page rather than racing
  //    the cached index update.
  await page.waitForFunction(() => {
    const pager = document.getElementById("pager");
    const at = Math.round(pager.scrollLeft / (pager.clientWidth || 1));
    // Arrived AND stopped: keep the assertion about a committed position, not
    // merely the first frame whose rounded index happens to match.
    if (at !== TAB_ORDER.indexOf("risk")) { window.__settleAt = null; return false; }
    const stable = window.__settleAt === pager.scrollLeft;
    window.__settleAt = pager.scrollLeft;
    return stable;
  }, null, { polling: "raf", timeout: 5000 });
  await page.evaluate(() => {
    const pager = document.getElementById("pager");
    pager.scrollLeft = TAB_ORDER.indexOf("market") * pager.clientWidth;
    pager.dispatchEvent(new Event("scroll"));
    pager.dispatchEvent(new Event("scrollend"));
  });
  await page.waitForFunction(() => currentTab() === "market", null, { timeout: 4000 })
    .catch(() => { throw new Error("currentTab() drifted from an uninstrumented scroll"); });

  await context.close();
}

// The nav follows a horizontal drag while expensive panel activation waits for
// native snap. The settled position uses the real panel offset; JS never
// corrects native momentum afterward.
async function testMobilePagerCommitsStateAtTheRealSnapPoint(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  const duringGesture = await page.evaluate(async () => {
    const pager = document.getElementById("pager");
    // Hold a deterministic in-between position; this test is for the JS state
    // boundary, while CI's native swipe cases keep CSS snap on.
    pager.style.scrollSnapType = "none";
    pager.dispatchEvent(new Event("touchstart"));
    const indicator = document.querySelector(".tab-progress-indicator");
    const before = new DOMMatrix(getComputedStyle(indicator).transform).m41;
    pager.scrollLeft = pager.clientWidth * 0.6;
    pager.dispatchEvent(new Event("scroll"));
    await new Promise(requestAnimationFrame);
    return {
      active: document.querySelector(".tab-btn.active")?.dataset.tab,
      current: currentTab(),
      panel: document.querySelector(".panel.active")?.dataset.panel,
      indicatorDelta: new DOMMatrix(getComputedStyle(indicator).transform).m41 - before,
    };
  });
  assert.equal(duringGesture.current, "hero",
    "application state changed before native scrolling settled");
  assert.equal(duringGesture.active, "drill",
    "the nav did not follow the visually dominant page during the gesture");
  assert.equal(duringGesture.panel, "hero",
    "panel rendering changed while the touch gesture still owned the pager");
  assert(duringGesture.indicatorDelta > 0,
    "the mobile indicator did not move with the finger");

  const settled = await page.evaluate(async () => {
    const pager = document.getElementById("pager");
    const panel = document.querySelector('.panel[data-panel="drill"]');
    const target = () => pager.scrollLeft
      + panel.getBoundingClientRect().left - pager.getBoundingClientRect().left;
    const nativeScrollTo = pager.scrollTo.bind(pager);
    let positionWrites = 0;
    pager.scrollTo = (...args) => {
      positionWrites += 1;
      return nativeScrollTo(...args);
    };
    pager.scrollLeft = target() + 7;
    pager.dispatchEvent(new Event("scroll"));
    pager.dispatchEvent(new Event("touchend"));
    pager.dispatchEvent(new Event("scrollend"));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const result = {
      active: document.querySelector(".tab-btn.active")?.dataset.tab,
      error: Math.abs(pager.scrollLeft - target()),
      positionWrites,
    };
    pager.scrollTo = nativeScrollTo;
    return result;
  });
  assert.equal(settled.active, "drill", "the settled page did not become active");
  assert.equal(await page.locator('.panel[data-panel="drill"]').evaluate(
    panel => getComputedStyle(panel).contentVisibility), "auto",
    "settling toggled content visibility and repainted the page");
  assert.equal(settled.positionWrites, 0,
    "JS rewrote the position after a native gesture instead of observing it");
  assert(settled.error >= 6,
    "the synthetic off-snap position was hidden by a forced correction");

  // A tab click may cross several pages. `scroll-snap-stop: always` correctly
  // keeps a finger swipe to one page, but it also forced the old smooth
  // programmatic scroll to stop at each intermediate snap point: Overview →
  // Risk visibly stranded on Holdings in mobile WebKit. Direct selection must
  // be atomic without weakening the one-page gesture contract.
  await page.evaluate(() => {
    document.getElementById("pager").style.scrollSnapType = "";
    document.querySelector('.tab-btn[data-tab="reflect"]').click();
  });
  await page.waitForFunction(() => {
    const pager = document.getElementById("pager");
    const panel = document.querySelector('.panel[data-panel="reflect"]');
    return document.querySelector(".tab-btn.active")?.dataset.tab === "reflect"
      && Math.abs(panel.getBoundingClientRect().left - pager.getBoundingClientRect().left) <= 1;
  }, null, { polling: "raf", timeout: 5000 }).catch(() => {
    throw new Error("a cross-page tab click stopped at an intermediate snap point");
  });
  await context.close();
}

// Exercise the browser-owned path rather than simulating scrollLeft: successive
// flicks must remain interruptible, a vertical/cancelled gesture must not turn
// into a page change, and an outward edge gesture must return to the edge snap.
async function testNativePagerGestureSequences(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  const session = await context.newCDPSession(page);
  const box = await page.locator("#pager").boundingBox();
  assert(box, "pager has no layout box");
  // A direct-child section divider is ordinary page chrome, not a nested
  // table/chart scroller whose existing contract contains horizontal overscroll.
  // Hero has no divider at its top, so use the panel's own padding there.
  const gestureY = async () => {
    const dividers = page.locator(".panel.active > .sect-divider");
    const divider = await dividers.count() ? await dividers.first().boundingBox() : null;
    if (divider && divider.y >= box.y && divider.y < box.y + box.height) {
      return divider.y + divider.height / 2;
    }
    return box.y + 5;
  };

  const flickLeft = async () => {
    const y = await gestureY();
    // The nav can reach the next label before momentum ends. Wait for the
    // browser's settle signal before starting another native finger gesture.
    const settled = page.evaluate(() => new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("pager did not emit scrollend")), 5000);
      document.getElementById("pager").addEventListener("scrollend", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
    }));
    for (const [i, x] of [385, 325, 265, 205, 145, 85, 5].entries()) {
      await dispatchTouch(session, i ? "touchMove" : "touchStart", [{ x, y }]);
      if (i) await page.waitForTimeout(20);
    }
    await dispatchTouch(session, "touchEnd", []);
    await settled;
  };
  const waitAligned = async tab => page.waitForFunction(t => {
    const pager = document.getElementById("pager");
    const panel = document.querySelector(`.panel[data-panel="${t}"]`);
    return document.querySelector(".tab-btn.active")?.dataset.tab === t
      && Math.abs(panel.getBoundingClientRect().left - pager.getBoundingClientRect().left) <= 1;
  }, tab, { polling: "raf", timeout: 5000 }).catch(async () => {
    const state = await page.evaluate(() => ({
      active: document.querySelector(".tab-btn.active")?.dataset.tab,
      left: document.getElementById("pager").scrollLeft,
    }));
    throw new Error(`native pager did not align ${tab}: ${JSON.stringify(state)}`);
  });

  assert.equal(await page.locator('.panel[data-panel="risk"]').evaluate(
    panel => getComputedStyle(panel).contentVisibility), "auto",
    "a second-away page was forced hidden before a rapid follow-up swipe");
  await flickLeft();
  await waitAligned("drill");
  await page.waitForTimeout(50);
  await flickLeft();
  await waitAligned("risk");

  // Predominantly vertical motion is owned by the panel scroller. Ending it as
  // cancelled covers Safari handing the stream to vertical scrolling/system UI.
  const y = await gestureY();
  await dispatchTouch(session, "touchStart", [{ x: 205, y: y + 150 }]);
  await dispatchTouch(session, "touchMove", [{ x: 195, y: y + 20 }]);
  await dispatchTouch(session, "touchCancel", []);
  await page.waitForTimeout(250);
  await waitAligned("risk");

  // At the leading edge the native scroller may rubber-band visually, but it
  // must settle back to the real first snap without a JS position correction.
  await page.locator('.tab-btn[data-tab="hero"]').click();
  await waitAligned("hero");
  for (const [i, x] of [45, 100, 165, 235, 300, 350].entries()) {
    await dispatchTouch(session, i ? "touchMove" : "touchStart", [{ x, y }]);
    if (i) await page.waitForTimeout(12);
  }
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForTimeout(250);
  await waitAligned("hero");
  await context.close();
}

// The refresh button is a ghost icon now: no label to swap, so the old CJK
// line-break failure mode is structurally gone. What must still hold is the
// geometry contract the old test guarded: clicking never changes the button's
// footprint (36px desktop / 44px touch circle), the brand never overlaps the nav links, and the
// flash classes (ok-flash / fresh-flash) still toggle as shape feedback.
// Measure geometry, don't grep stylesheet properties.
async function testTopbarFitsWhenRefreshLabelSwaps(browser, base) {
  // 360px is the narrowest width the wordmark is promised in full. 320px is
  // past that: there the brand may reach its ellipsis, but it still may not be
  // painted over the links — an un-clipped h1 in a shrunk flex item overlaps
  // them instead of getting narrower.
  const phones = [{ width: 320, mayTruncate: true }, { width: 360 },
                  { width: 390 }, { width: 412 }];
  for (const { width, mayTruncate } of phones) {
    const context = await browser.newContext({
      viewport: { width, height: 800 }, isMobile: true, hasTouch: true,
    });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);

    const idle = await page.locator("#refresh-btn").boundingBox();
    await page.click("#refresh-btn");
    // Click must toggle one of the two outcome flashes (new generation vs
    // already current) — the icon carries the feedback now, no text swap.
    await page.waitForFunction(
      () => {
        const b = document.querySelector("#refresh-btn");
        return b.classList.contains("fresh-flash") || b.classList.contains("ok-flash");
      },
      null, { timeout: 5000 },
    ).catch(() => { throw new Error(`refresh at ${width}px never flashed`); });

    const box = await page.evaluate(() => {
      const rect = el => el.getBoundingClientRect();
      const btn = document.getElementById("refresh-btn");
      const h1 = document.querySelector(".brand h1");
      // The four destinations are one disclosure in the top-right now. Its
      // panel is measured (it is where the four live), and the trigger is what
      // must not collide with the wordmark when the row is squeezed to 320px.
      const links = [...document.querySelectorAll(".site-menu-item")];
      const nav = document.querySelector(".site-menu-btn");
      const h1Box = rect(h1);
      const overlapsBrand = links.some(item => {
        const box = rect(item);
        return box.left < h1Box.right && box.right > h1Box.left &&
          box.top < h1Box.bottom && box.bottom > h1Box.top;
      });
      return {
        hasLabel: !!btn.querySelector(".lbl"),
        height: rect(btn).height,
        width: rect(btn).width,
        nav: links.map(item => item.textContent.trim()),
        linkHeights: links.map(item => rect(item).height),
        trigger: { left: Math.round(rect(nav).left), right: Math.round(rect(nav).right),
                   height: Math.round(rect(nav).height) },
        pageName: (nav.querySelector(".site-menu-label") || nav).textContent.trim(),
        overlapsBrand,
        clipped: h1.scrollWidth > h1.clientWidth + 0.5,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        // What a finger gets, which is not what the eye gets: the refresh
        // control is a bare glyph with an invisible pseudo-element for a
        // target, so its painted box is deliberately smaller than 44px.
        reach: (() => {
          const box = rect(btn);
          const x = box.left + box.width / 2, y = box.top + box.height / 2;
          const owns = (dx, dy) => {
            const hit = document.elementFromPoint(x + dx, y + dy);
            return hit === btn || btn.contains(hit);
          };
          let up = 0, down = 0, left = 0, right = 0;
          while (up < 60 && owns(0, -up - 1)) up += 1;
          while (down < 60 && owns(0, down + 1)) down += 1;
          while (left < 60 && owns(-left - 1, 0)) left += 1;
          while (right < 60 && owns(right + 1, 0)) right += 1;
          return [left + right + 1, up + down + 1];
        })(),
      };
    });
    assert(box.hasLabel === false, `refresh button must be icon-only at ${width}px`);
    assert(box.height <= idle.height + 1 && box.width <= idle.width + 1,
      `refresh button grew to ${box.width}x${box.height} at ${width}px (idle ${idle.width}x${idle.height})`);
    assert.deepEqual(box.nav, ["Dashboard", "Briefs", "FAQ", "GitHub"],
      `the site menu's destinations differ at ${width}px`);
    assert(box.trigger.height >= 44,
      `the site menu trigger is ${box.trigger.height}px tall at ${width}px`);
    assert(box.reach[0] >= 44 && box.reach[1] >= 44,
      `refresh touch target reaches ${box.reach.join("x")} at ${width}px `
      + `(painted box ${box.width}x${box.height})`);
    assert.equal(box.pageName, "Dashboard",
      `the trigger names "${box.pageName}" at ${width}px — it has to answer "where am I"`);
    assert(!box.overlapsBrand, `brand overlaps the site menu at ${width}px`);
    assert(box.trigger.right <= idle.x + idle.width + 1,
      `the site menu runs past the refresh button at ${width}px`);
    assert(mayTruncate || !box.clipped, `brand wordmark is truncated at ${width}px`);
    assert(box.overflow <= 1, `page overflows by ${box.overflow}px at ${width}px`);
    await context.close();
  }

  // The button is icon-only at every width now — no label to drop on phones,
  // no text to wrap on desktops. The geometry contract is the same everywhere:
  // the click never changes the footprint, and the two outcomes stay apart by
  // shape (✓ only for a new generation), not by colour alone.
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await stubLiveOrigin(desktop);
  await desktop.goto(base, { waitUntil: "networkidle" });
  await waitForData(desktop);
  assert(await desktop.locator("#refresh-btn .lbl").count() === 0,
    "refresh button must be icon-only on desktop too");
  await desktop.close();

  // Shape separates the outcomes: ok-flash keeps the ↻ (coloured green),
  // fresh-flash morphs it to ✓ (accent). Colour is never the sole carrier.
  const feedback = await browser.newPage({ viewport: { width: 390, height: 800 } });
  await stubLiveOrigin(feedback);
  await feedback.goto(base, { waitUntil: "networkidle" });
  await waitForData(feedback);
  const marks = await feedback.evaluate(() => {
    const btn = document.getElementById("refresh-btn");
    const ic = btn.querySelector(".ic");
    const visibleMark = state => {
      btn.classList.remove("ok-flash", "fresh-flash");
      if (state) btn.classList.add(state);
      // A zeroed font size means the element's own text is gone and whatever
      // ::after draws is what the user actually sees.
      return getComputedStyle(ic).fontSize === "0px"
        ? getComputedStyle(ic, "::after").content
        : ic.textContent;
    };
    return { idle: visibleMark(null), ok: visibleMark("ok-flash"), fresh: visibleMark("fresh-flash") };
  });
  assert(marks.ok !== marks.fresh,
    `both refresh outcomes draw the same mark (${marks.ok})`);
  assert(marks.fresh !== marks.idle,
    "a new generation left the refresh icon unchanged");
  await feedback.close();

  // The old label wrap failure mode is structurally gone (no text), so the
  // geometry stress it guarded becomes: a click at any width must not grow
  // the button.
  const stress = await browser.newPage({ viewport: { width: 600, height: 900 } });
  await stubLiveOrigin(stress);
  await stress.goto(base, { waitUntil: "networkidle" });
  await waitForData(stress);
  const grew = await stress.evaluate(() => {
    const btn = document.getElementById("refresh-btn");
    const before = btn.getBoundingClientRect().height;
    btn.click();
    return btn.getBoundingClientRect().height - before;
  });
  assert(grew <= 1, `refresh button changed its footprint by ${grew}px after a click`);
  await stress.close();
}

// The header is full-bleed by design — background, shadow and rule cross the
// whole viewport — but everything it holds belongs to the same column as the
// cards. `main` stops at 1600px; the header's padding did not, so past that
// width the wordmark and whatever sat at the right kept walking outward while
// the content stood still (172px of drift at 1920, 492px at 2560).
//
// The left anchor is the wordmark; the right edge is Refresh, with the site
// menu just inside it. The tab strip is back and spans the same column, which
// is what the old `tabLeft` assertion was for.
async function testHeaderSharesTheContentColumn(browser, base) {
  for (const width of [1280, 1920, 2560]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    const m = await page.evaluate(() => {
      const box = el => el.getBoundingClientRect();
      const main = document.querySelector("main");
      const style = getComputedStyle(main);
      return {
        columnLeft: box(main).left + parseFloat(style.paddingLeft),
        columnRight: box(main).right - parseFloat(style.paddingRight),
        brandLeft: box(document.querySelector(".brand-mark")).left,
        // The strip is full-bleed like the header, and its own inline padding
        // is what puts its first button on the column — measuring the <nav>
        // box would compare 0..viewport against the column and always fail.
        tabsLeft: box(document.querySelector(".tab-btn")).left,
        tabsPadding: parseFloat(getComputedStyle(document.querySelector(".tabs")).paddingLeft),
        menuRight: box(document.querySelector(".site-menu-btn")).right,
        refreshRight: box(document.getElementById("refresh-btn")).right,
      };
    });
    const off = (a, b) => Math.abs(a - b);
    assert(off(m.brandLeft, m.columnLeft) <= 1,
      `wordmark is ${off(m.brandLeft, m.columnLeft)}px off the content column at ${width}px`);
    assert(off(m.refreshRight, m.columnRight) <= 1,
      `refresh is ${off(m.refreshRight, m.columnRight)}px off the column's right edge at ${width}px`);
    assert(off(m.tabsLeft, m.columnLeft) <= 1,
      `the tab strip starts ${off(m.tabsLeft, m.columnLeft)}px off the content column at ${width}px`);
    assert(m.tabsPadding >= 28,
      `the strip's inline padding is ${m.tabsPadding}px at ${width}px — below the column inset`);
    assert(m.menuRight <= m.columnRight + 1,
      `the site menu is ${m.menuRight - m.columnRight}px past the column at ${width}px`);
    await page.close();
  }
}

// #736: the decision-trace summary row is a nowrap flex line whose min-content
// is ~367px — wider than any phone — and .tr-row clips instead of scrolling, so
// on a 390px iPhone the P&L number lost its last characters and at 320px it sat
// entirely outside the row, together with the disclosure arrow. Measured, not
// eyeballed: scrollWidth vs clientWidth on the summary, plus every child's right
// edge against the row's.
async function testTraceRowsFitPhoneWidths(browser, base) {
  for (const width of [320, 360, 390, 414]) {
    const page = await browser.newPage({ viewport: { width, height: 780 } });
    await stubLiveOrigin(page);
    await page.goto(base + "#reflect", { waitUntil: "domcontentloaded" });
    await waitForTab(page, "reflect");
    const m = await page.evaluate(() => {
      const rows = [...document.querySelectorAll("#trace-list .tr-row")];
      if (!rows.length) return {rows: 0};
      const overflow = [];
      const outside = [];
      for (const row of rows) {
        const summary = row.querySelector("summary");
        if (summary.scrollWidth > summary.clientWidth + 1) {
          overflow.push(`${row.querySelector(".tr-tk")?.textContent}: ${summary.scrollWidth} > ${summary.clientWidth}`);
        }
        const right = row.getBoundingClientRect().right;
        for (const child of summary.children) {
          const box = child.getBoundingClientRect();
          if (box.width > 0 && box.right > right + 1) {
            outside.push(`${child.className} (${Math.round(box.right)} > ${Math.round(right)})`);
          }
        }
      }
      // The card exists at all only when the payload carries traces.
      const card = document.getElementById("decision-traces-card");
      return {rows: rows.length, overflow, outside, docWidth: document.documentElement.scrollWidth,
              cardHidden: card ? card.style.display === "none" : true};
    });
    if (m.rows === 0) {
      assert(m.cardHidden !== false, "the trace card is showing with no rows in it");
      await page.close();
      continue;
    }
    assert.deepEqual(m.overflow, [], `clipped trace summary rows at ${width}px`);
    assert.deepEqual(m.outside, [], `trace summary children outside their row at ${width}px`);
    assert(m.docWidth <= width, `the page scrolls horizontally at ${width}px (${m.docWidth})`);
    await page.close();
  }
}

// 首屏与持仓表的「截断」回归闸（2026-08-24）。三个缺陷都不是布局取舍，
// 而是数字/证据被切掉后页面看起来仍然正常，所以只有量出来才发现：
//   1 hero 副行 `nowrap + ellipsis` 在 390px 上稳定截在「今日 +$807.18…」，
//     今日涨跌幅从来没显示过。
//   2 冻结列写的是 `background`（一个简写），行 hover/active 的半透明 tint
//     把它整个替换掉 ⇒ 横向滚动时下面的单元格透上来和 ticker 叠字。
//   3 展开的证据行是一个和整张表一样宽的 td，也匹配 `td:first-child` 的
//     sticky 规则，但没有可走的距离 ⇒ 跟着表滚出去，左半边被切（实测
//     left = -363px）。
async function testHoldingsAndHeroNeverTruncate(browser, base) {
  // — 首屏副行：三段都必须完整，且必须带上今日涨跌幅 —
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    const sub = await page.evaluate(() => {
      const el = document.getElementById("hero-sub");
      const segs = [...el.querySelectorAll(".hds-seg")];
      return {
        text: el.textContent,
        lineClipped: el.scrollWidth > el.clientWidth + 1,
        segClipped: segs.filter(s => s.scrollWidth > s.clientWidth + 1).map(s => s.textContent),
        segCount: segs.length,
      };
    });
    // 副行现在是两段：「今日」连同它的涨跌幅搬进了统计轨自己的一格（#911，
    // 去掉一屏内说两遍同一个数）。这条闸守的是「数字不许被静默切掉」，所以
    // 它跟着搬 —— 断言从「副行里有 %」改成「今日那个 % 仍然在首屏、且没被
    // 截断」。只放松不跟随，等于把闸删了。
    assert.equal(sub.segCount, 2, "hero sub-line should render 已实现 / 浮动 as two segments");
    assert.equal(sub.lineClipped, false, "hero sub-line is clipped at 390px");
    assert.deepEqual(sub.segClipped, [], "a hero sub-line segment is clipped");

    // 「今日」在 #911 里从统计轨的一格搬成了自己一行（柱图挤在 ~230px 的格子
    // 里缩略看像随机方块），同时把美股/港股当日分项补了回来 —— 并成一格时
    // 那两个数被合掉了。闸跟着搬：合计的 %、两个市场的分项、以及那张柱图，
    // 三样都必须在首屏且不被截断。
    const today = await page.evaluate(() => {
      const row = document.getElementById("hero-today");
      if (!row || !row.textContent.trim()) return null;
      const parts = [...row.querySelectorAll(".ht-total, .ht-leg, .rc-cap")];
      return {
        text: row.textContent,
        legs: row.querySelectorAll(".ht-leg").length,
        clipped: parts.filter(p => p.scrollWidth > p.clientWidth + 1).map(p => p.textContent),
        bars: row.querySelectorAll(".rc-bars > i").length,
      };
    });
    assert(today, "the 今日 row is gone — today's move left the first screen");
    assert.match(today.text, /%/, "the 今日 row dropped the today percentage");
    assert.equal(today.legs, 2, "the 今日 row must keep the US / HK split, not just the total");
    assert.match(today.text, /美股/, "the 今日 row lost the US leg");
    assert.match(today.text, /港股/, "the 今日 row lost the HK leg");
    assert.deepEqual(today.clipped, [], "the 今日 row truncates a value");
    assert(today.bars > 5, `今日 row drew ${today.bars} daily bars — the chart is missing`);

    // 统计轨每一格的说明行同理：它们带着样本量和「未能核验」的条数，
    // nowrap + ellipsis 一挤就把这些数字整段吃掉。
    const caps = await page.evaluate(() => [...document.querySelectorAll(".hero-rail .rc-cap, .hero-today .rc-cap")]
      .filter(c => c.scrollWidth > c.clientWidth + 1).map(c => c.textContent));
    assert.deepEqual(caps, [], "a hero rail caption is truncated at 390px");
    await context.close();
  }

  // — 持仓表：横向滚到底 + 展开一行，冻结列不透明、展开面板留在视口内 —
  {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    await clickTab(page, "drill");
    await waitForTab(page, "drill");
    await page.waitForSelector("table.book-table tbody tr.book-row");
    await page.click("table.book-table tbody tr.book-row");
    // 展开是 CSS grid-template-rows 0fr->1fr 的过渡，点完到有高度中间隔了几帧；
    // 直接量会偶发量到 0（这条断言第一版就是这么随机红的）。
    await page.waitForFunction(() => {
      const row = document.querySelector("table.book-table tbody tr.book-row");
      const detail = row && row.nextElementSibling;
      return row && row.dataset.open === "1"
        && detail && detail.classList.contains("book-detail")
        && detail.offsetHeight > 10;
    }, null, { timeout: 5000 });
    const openedTicker = await page.locator("table.book-table tbody tr.book-row[data-open='1']")
      .getAttribute("data-ticker");
    await page.click("table.book-table thead button");
    await page.waitForFunction((ticker) => {
      const row = document.querySelector(`table.book-table tbody tr.book-row[data-ticker="${ticker}"]`);
      return row?.dataset.open === "1" && row.getAttribute("aria-expanded") === "true"
        && row.nextElementSibling?.dataset.open === "1";
    }, openedTicker, { timeout: 3000 });
    // A re-render must not drop keyboard focus off the row it rebuilds (#1624).
    // `click()` from script re-sorts without moving focus to the header button.
    const refocused = await page.evaluate((ticker) => {
      const row = document.querySelector(`table.book-table tbody tr.book-row[data-ticker="${ticker}"]`);
      row.focus();
      document.querySelector("table.book-table thead button").click();
      return document.activeElement?.matches?.(`tr.book-row[data-ticker="${ticker}"]`)
        && document.activeElement.isConnected;
    }, openedTicker);
    assert.ok(refocused, "re-rendering the book must keep focus on the same row");
    await page.evaluate(() => {
      const wrap = document.querySelector("table.book-table").closest(".table-wrap");
      wrap.scrollLeft = wrap.scrollWidth;
      wrap.dispatchEvent(new Event("scroll"));
    });
    await page.waitForFunction(() => {
      const wrap = document.querySelector("table.book-table").closest(".table-wrap");
      return wrap.scrollLeft > 1 && wrap.classList.contains("is-scrolled");
    }, null, { timeout: 3000 });

    const m = await page.evaluate(() => {
      const table = document.querySelector("table.book-table");
      const wrap = table.closest(".table-wrap");
      const firstCell = table.querySelector("tbody tr.book-row td:first-child");
      const detail = [...table.querySelectorAll("tbody tr.book-detail")]
        .find(row => row.offsetHeight > 10);
      const inner = detail && detail.querySelector(".bd-inner");
      const rect = inner && inner.getBoundingClientRect();
      return {
        scrolled: wrap.scrollLeft,
        frozenBg: getComputedStyle(firstCell).backgroundColor,
        frozenShadow: getComputedStyle(firstCell).boxShadow,
        wrapLeft: Math.round(wrap.getBoundingClientRect().left),
        wrapWidth: wrap.clientWidth,
        innerLeft: rect ? Math.round(rect.left) : null,
        innerWidth: rect ? Math.round(rect.width) : null,
      };
    });

    assert(m.scrolled > 1, "the holdings table did not scroll horizontally at 390px");
    // 「不透明」= 不是 rgba(...,0) 也不是 transparent。半透明底就是漏字的那个 bug。
    assert(/^rgb\(/.test(m.frozenBg),
      `frozen column is not opaque while scrolled (${m.frozenBg})`);
    assert.notEqual(m.frozenShadow, "none",
      "frozen column shows no scroll edge while the table is scrolled");
    assert.notEqual(m.innerLeft, null, "the expanded evidence panel did not render");
    assert(Math.abs(m.innerLeft - m.wrapLeft) <= 2,
      `expanded evidence panel drifted out of view (left ${m.innerLeft} vs wrap ${m.wrapLeft})`);
    assert(Math.abs(m.innerWidth - m.wrapWidth) <= 2,
      `expanded evidence panel is not the visible width (${m.innerWidth} vs ${m.wrapWidth})`);
    await context.close();
  }

  // — 统计轨不得重复副行已经给过的数字 —
  // 「已实现 · USD-eq」和「浮动 · USD-eq」曾各占一格，而它们和主数下面那行
  // 是逐字相同的两个值，相距 30px。同一个数字在一屏内说两遍不是信息更全。
  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    const dup = await page.evaluate(() => {
      const sub = document.getElementById("hero-sub").textContent.replace(/\s+/g, "");
      return [...document.querySelectorAll(".hero-rail-cell")]
        .map(cell => ({
          k: cell.querySelector(".hero-rail-k")?.textContent.trim(),
          // 只比「值」本身，不含它自己的变化幅度：变化幅度是这一格独有的。
          v: (cell.querySelector(".hero-rail-v")?.firstChild?.textContent || "").trim(),
        }))
        .filter(c => c.v && sub.includes(c.v.replace(/\s+/g, "")));
    });
    assert.deepEqual(dup, [],
      "a hero rail cell restates a number the sub-line already shows");
    await context.close();
  }

  // — 首屏统计轨必须自己占住高度 —
  // 数据到达前 #hero-rail 是空的。在给它 min-height 之前它高 1px，填满后
  // 85px（桌面），每次加载都跳一次 —— 实测这一下就是整页 CLS 的大头
  // (0.26 -> 0.04)。这里量的是「预留 == 实测」，比断言一个 CLS 数字稳。
  // 六格 → 四格 → 今日搬进自己那一行后是美股/港股/距峰值/遵守率四格。
  // 这条闸量的从来不是格数本身，而是「预留 == 实测」，格数只是用来钉住
  // 某次改版没有把断点改塌。
  for (const [width, expectCols] of [[390, 2], [900, 4], [1440, 4]]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    // 必须在数据到达之前量，所以不能等 networkidle。
    await page.goto(base, { waitUntil: "domcontentloaded" });
    const reserved = await page.evaluate(() =>
      Math.round(document.querySelector(".hero-rail").getBoundingClientRect().height));
    await waitForData(page);
    await page.waitForFunction(() =>
      document.querySelectorAll(".hero-rail .hero-rail-cell").length > 0,
      null, { timeout: 5000 });
    const after = await page.evaluate(() => {
      const rail = document.querySelector(".hero-rail");
      return {
        height: Math.round(rail.getBoundingClientRect().height),
        cols: getComputedStyle(rail).gridTemplateColumns.split(" ").length,
      };
    });
    assert.equal(after.cols, expectCols, `hero rail column count changed at ${width}px`);
    assert.equal(reserved, after.height,
      `hero rail shifts by ${after.height - reserved}px when data lands at ${width}px`);

    // 每日盈亏柱必须整体落在自己的槽位容器里：柱子按槽位中心对齐后，首末
    // 柱两侧各留半个槽位。此前 left:i/n 把第一根柱的中心压在容器左缘，
    // max-width 9px 的柱有一半（4.5px）悬在容器外 —— 修的是落点，不是粗细：
    // 「疏密随宽度变、粗细不变」的规矩由 max-width 继续承担，这里只闸
    // 「柱体不得溢出容器左右缘」。
    const barFit = await page.evaluate(() => {
      const bars = document.querySelector(".ht-chart .rc-bars");
      if (!bars) return null;
      const bc = bars.getBoundingClientRect();
      let minL = Infinity, maxR = -Infinity, count = 0;
      for (const b of bars.querySelectorAll("i")) {
        const r = b.getBoundingClientRect();
        minL = Math.min(minL, r.left); maxR = Math.max(maxR, r.right); count += 1;
      }
      // clearance 语义：≥0 = 柱体在容器内，负数 = 溢出该侧的像素数。
      return count ? { clearL: minL - bc.left, clearR: bc.right - maxR, count } : null;
    });
    assert(barFit && barFit.count > 5, `daily bars missing at ${width}px`);
    assert(barFit.clearL >= -0.5 && barFit.clearR >= -0.5,
      `daily bars overflow their container at ${width}px ` +
      `(left ${barFit.clearL.toFixed(1)}px, right ${barFit.clearR.toFixed(1)}px)`);

    // 数据健康里「正常」的槽位必须是品牌蓝，不是灰墨也不是涨跌色（#920 判据：
    // 数据状态不参与赚亏表述）。color-mix 的计算值序列化成 color(srgb …)，
    // 和 rgb() 形式的 token 比字符串永不相等 —— 期望值用探针走同一条
    // color-mix 路径解析出来，两边同一序列化才比得出真伪。
    const health = await page.evaluate(() => {
      const probe = document.createElement("span");
      document.body.appendChild(probe);
      const tint = c => {
        probe.style.color = "";
        probe.style.color = c;
        return getComputedStyle(probe).color;
      };
      const okSegs = [...document.querySelectorAll(".dh-slots i[data-s='ok']")];
      const fills = okSegs.map(s => getComputedStyle(s).backgroundColor);
      // 探针读完再摘：摘掉之后 getComputedStyle 读的是游离节点，颜色恒为空。
      const accentBlue = tint("var(--accent)");
      const oldGrey = tint("color-mix(in srgb, var(--text) 38%, transparent)");
      const negRed = tint("var(--negative)");
      probe.remove();
      return { accentBlue, oldGrey, negRed, fills };
    });
    if (health.fills.length) {
      assert(health.fills.every(f => f === health.accentBlue),
        `in-period health segments drifted off the brand blue: ${health.fills[0]} vs ${health.accentBlue}`);
      assert(health.fills[0] !== health.oldGrey,
        "in-period health segments render as plain ink — the ok state went back to grey");
      assert(health.fills[0] !== health.negRed,
        "in-period health segments carry a P&L colour — data state is not an up/down");
    }
    await context.close();
  }

  // — 首屏缩略走势：必须画的是主数自己，而且必须由首帧 bundle 画出来 —
  // 这条走势线在 dashboard.hero.js（首屏加载的那份）和 dashboard.render.js
  // 之间是手工双份。本轮第一次实现时只落进了 render.js，于是生产路径上
  // 它根本不存在，而页面零报错。这里在**没有进过任何详情 tab**的状态下断言，
  // 走的就是首帧那条路。
  {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "domcontentloaded" });
    // 数据到达前容器就得占住高度，否则它一画出来就是一次 CLS。
    const reserved = await page.evaluate(() =>
      Math.round(document.getElementById("hero-spark").getBoundingClientRect().height));
    assert(reserved > 40, `hero spark reserves no height before data (${reserved}px)`);
    await waitForData(page);
    await page.waitForSelector(".hero-spark-svg", { timeout: 5000 });

    const spark = await page.evaluate(() => {
      const host = document.getElementById("hero-spark");
      const svg = host.querySelector(".hero-spark-svg");
      const area = svg.querySelector(".hs-area");
      const cs = area && getComputedStyle(area);
      const root = getComputedStyle(document.documentElement);
      const probe = document.createElement("span");
      document.body.appendChild(probe);
      const tint = c => {
        probe.style.color = "";
        probe.style.color = root.getPropertyValue(c).trim();
        return getComputedStyle(probe).color;
      };
      return {
        height: Math.round(host.getBoundingClientRect().height),
        label: svg.getAttribute("aria-label") || "",
        points: (svg.querySelector(".hs-line")?.getAttribute("d") || "").split("L").length,
        // 面积填充：整段 fill 声明 + 两个 stop 的解析色。中性材质不能带涨跌色。
        areaFill: cs ? cs.fill : "",
        stopColors: [...svg.querySelectorAll("linearGradient stop")]
          .map(s => getComputedStyle(s).stopColor),
        // token 值经探针解析成 rgb() 再比：直接比 `#F05B67` 和 `rgb(240,91,103)`
        // 永远不相等，那样的断言是恒真的，等于没闸。
        pnlTokens: ["--positive", "--negative", "--text-primary"].map(tint),
        foot: host.querySelector(".hs-foot")?.textContent.trim() || "",
        // 脚注横向溢出＝数字被静默切掉。带数字的那半句必须整段在框内。
        footLowFits: (() => {
          const f = host.querySelector(".hs-foot");
          const low = host.querySelector(".hs-foot-low");
          if (!f || !low) return false;
          const fb = f.getBoundingClientRect(), lb = low.getBoundingClientRect();
          return low.scrollWidth <= Math.ceil(lb.width) + 1
            && lb.right <= Math.ceil(fb.right) + 1 && lb.left >= Math.floor(fb.left) - 1;
        })(),
        lowMark: !!svg.querySelector(".hs-low"),
        headline: document.getElementById("hero-pnl").textContent.trim(),
        tone: svg.classList.contains("neg") ? "neg"
          : svg.classList.contains("pos") ? "pos" : "flat",
      };
    });
    // 探针留在页面上会污染后面的断言，evaluate 里取完就删。
    await page.evaluate(() => document.body.lastElementChild?.remove());

    assert.equal(spark.height, reserved,
      `hero spark shifts by ${spark.height - reserved}px when it draws`);
    assert(spark.points > 10, `hero spark drew only ${spark.points} points`);
    // 画的必须是主数本身：aria-label 的「当前」值要和大数字逐字相同。
    // 不比对的话，这条线画成「账面市值」「净值」都不会有人发现。
    const current = /当前\s*(\S+)$/.exec(spark.label);
    assert(current, `hero spark aria-label has no 当前 value: ${spark.label}`);
    assert.equal(current[1], spark.headline,
      "hero spark does not end at the headline number — it is plotting a different series");
    // 面积是材质不是信号：不许带涨跌色。以前它按零轴分成红/绿两段，那是为了
    // 「别把盈利期涂成亏损色」；现在整片中性，结构上就撒不了那个谎，代价是
    // 得钉住「没人后来又把涨跌色加回填充里」——首屏那片红正是这么来的。
    const [posRGB, negRGB, inkRGB] = spark.pnlTokens;
    // 反空转：三个 token 必须解析成互不相同的 rgb()，否则下面那条比对
    // 会因为「什么都相等/什么都不等」而恒真。
    assert(posRGB && negRGB && inkRGB && posRGB !== inkRGB && negRGB !== inkRGB,
      `P&L / ink tokens did not resolve distinctly: ${spark.pnlTokens.join(" | ")}`);
    assert(spark.stopColors.length >= 2,
      `hero spark area has no gradient stops (${spark.stopColors.length})`);
    // 面积可以有颜色（#911 从中性墨换成品牌蓝，因为中性那版把首屏读成灰卡），
    // 但**不能是涨跌色**：那正是「一屏四块红」的来路，而且面积一旦上涨跌色，
    // 零轴两侧就有一侧在说谎。守的是这条，不是某个具体色值。
    for (const c of spark.stopColors) {
      assert(c !== posRGB && c !== negRGB,
        `hero spark area fill carries a P&L colour (${c}) — the area is material, not signal`);
    }
    // 脚注三件事：区间、最低点、自最低回来多少。少一件这条线就退回纯形状。
    for (const want of ["个交易日", "最低", "自最低"]) {
      assert(spark.foot.includes(want),
        `hero spark footer is missing 「${want}」: ${spark.foot}`);
    }
    assert(spark.lowMark, "hero spark has no low-point marker line");
    assert(spark.footLowFits,
      "hero spark footer clips the numbers — 最低/自最低 must never be truncated");
    await context.close();
  }

  // — 名称列：可以省略号，但完整名字必须留在 title 里 —
  for (const width of [1024, 1280, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    await clickTab(page, "drill");
    await waitForTab(page, "drill");
    await page.waitForSelector("table.book-table .name-cell");
    const lost = await page.evaluate(() =>
      [...document.querySelectorAll("table.book-table .name-cell")]
        .filter(c => c.scrollWidth > c.clientWidth + 1)
        .filter(c => c.getAttribute("title") !== c.textContent.trim())
        .map(c => c.textContent.trim()));
    assert.deepEqual(lost, [],
      `holdings name is truncated with no full value in title at ${width}px`);
    await context.close();
  }
}

// 判定牌组第八次迭代（kcn：「几张卡留白很多，切来切去其实就几个文字」）钉两条：
//   1. 牌是绝对定位、撑满台面的，所以「牌里有多少空高」= 地板 − 正文。正文
//      必须吃满盒子，剩余高度归异动条那一带 —— 否则地板每抬一档就多一段空气。
//   2. 牌上只有三个槽位，选哪三条必须按数据自己的严重度，不按数组下标：
//      hard stop（critical，已跌穿 -18% 硬止损线）不能被同为 high 的限额条挤掉。
async function testVerdictDeckFillsItsBoxAndRanksGatesBySeverity(browser, base) {
  const RANK = { critical: 3, high: 2, medium: 1 };
  for (const [width, height] of [[1200, 900], [390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    await stubLiveOrigin(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    await page.waitForSelector("#today-movers .hl-movers", { timeout: 5000 });

    const fill = await page.evaluate(() => {
      const card = document.querySelector(".verdict-deck .deck-card");
      const movers = document.querySelector("#today-movers .hl-movers");
      const bars = document.querySelectorAll("#today-movers .hl-mv-bar i");
      const cs = getComputedStyle(card);
      const inner = card.getBoundingClientRect().bottom - parseFloat(cs.paddingBottom);
      return {
        slack: inner - movers.getBoundingClientRect().bottom,
        moversHeight: movers.getBoundingClientRect().height,
        bars: bars.length,
        widest: Math.max(0, ...[...bars].map(b => b.getBoundingClientRect().width)),
      };
    });
    // 反空转：没有柱就谈不上「柱区吃满」，这条断言必须有东西可量。
    assert(fill.bars > 0, `no mover bars rendered at ${width}px`);
    assert(fill.widest > 1, `mover bars have no width at ${width}px`);
    assert(fill.slack <= 16 && fill.slack >= -1,
      `verdict card leaves ${Math.round(fill.slack)}px of dead air below its content `
      + `at ${width}px — the reserved floor must be spent on the chart, not on air`);

    const gate = await page.evaluate(() => {
      // DATA 是脚本顶层的 let，不是 window 的属性 —— 走 window.DATA 会恒空，
      // 于是下面的排序断言变成「空 vs 空」的恒真闸。
      const g = (typeof DATA === "undefined" ? null : DATA.risk_guardrail) || {};
      const all = [
        ...(g.breaches || []).map(b => b.severity || "high"),
        ...(g.hard_stop_watch || []).map(s => s.severity || "critical"),
      ];
      const list = document.getElementById("overview-guardrail-list");
      const shown = [...list.querySelectorAll(".risk-alert")]
        .map(el => [...el.classList].find(c => c !== "risk-alert") || "high");
      const more = list.querySelector(".overview-gates-more");
      return { all, shown, more: more ? more.textContent.trim() : null };
    });
    assert(gate.all.length > 0 && gate.shown.length > 0,
      `gate card rendered nothing to rank at ${width}px`);
    const ranked = gate.all.map(s => RANK[s] || 0).sort((a, b) => b - a);
    const shownRanks = gate.shown.map(s => RANK[s] || 0).sort((a, b) => b - a);
    assert.deepEqual(shownRanks, ranked.slice(0, gate.shown.length),
      `gate card shows ${gate.shown.join("/")} but the payload's worst are `
      + `${gate.all.slice().sort((a, b) => (RANK[b] || 0) - (RANK[a] || 0)).slice(0, gate.shown.length).join("/")}`);
    const hidden = gate.all.length - gate.shown.length;
    if (hidden > 0) {
      assert(gate.more && gate.more.includes(String(hidden)),
        `gate card hides ${hidden} rows without saying so (tail: ${gate.more})`);
    }
    await context.close();
  }
}

// The pager number, the exposed card and the picture must name one card while
// the deck is moving — not only after its spring happens to settle. This also
// pins the DOM-order labels and the compact add-side decision input added to the
// first card; detail-only add-side tables do not belong in the first-paint deck.
async function testVerdictDeckPagerTracksTheVisualCard(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 1200, height: 900 }, reducedMotion: "no-preference",
  });
  const page = await context.newPage();
  await stubLiveOrigin(page, {
    patch: (name, json) => {
      if (name !== "overview.json" && name !== "dashboard.json") return null;
      json.add_side = {
        pending: false, cold_start: true,
        counts: { candidate: 0, wait: 7, reject: 0 },
        why_no_candidate: "全部持仓未站上前 20 日高，最接近 QQQ -0.4%",
        closest: { ticker: "QQQ", verdict: "wait", pct_from_high: -0.37,
                   needs: "站上 724.13" },
        rows: [{ ticker: "QQQ", verdict: "wait", pct_from_high: -0.37,
                 needs: "站上 724.13" }],
      };
      return json;
    },
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  const read = () => page.evaluate(() => ({
    cards: [...document.querySelectorAll("#verdict-deck .deck-card")].map(el => ({
      theme: el.dataset.theme, hidden: el.getAttribute("aria-hidden"), inert: el.inert,
    })),
    dots: [...document.querySelectorAll("#verdict-deck-dots .deck-dot")].map(el => ({
      label: el.getAttribute("aria-label"), current: el.getAttribute("aria-current"),
    })),
  }));
  const assertActive = async expected => {
    const state = await read();
    assert.equal(state.cards.length, state.dots.length,
      "the pager count diverged from the card count");
    assert.deepEqual(state.dots.map(dot => dot.label),
      state.cards.map((card, i) => `第 ${i + 1} 张：${card.theme}`),
      "pager numbers no longer follow the cards' visual/DOM order");
    assert.deepEqual(state.dots.map(dot => dot.current),
      state.cards.map((_, i) => i === expected ? "true" : "false"),
      "aria-current names a different card from the visual top card");
    assert.deepEqual(state.cards.map(card => card.hidden),
      state.cards.map((_, i) => i === expected ? "false" : "true"),
      "there must be exactly one exposed card during a transition");
    assert.deepEqual(state.cards.map(card => card.inert),
      state.cards.map((_, i) => i !== expected),
      "the interactive card and the numbered current card disagree");
  };

  const addChip = page.locator("#today-highlights .hl-chip", { hasText: "加仓面" });
  assert.equal(await addChip.count(), 1, "the first-paint verdict lost its add-side input");
  assert.match(await addChip.innerText(), /等 7.*QQQ.*-0\.4%/s,
    "the compact add-side verdict lost its count or nearest actionable name");
  assert.match(await addChip.getAttribute("title"), /全部持仓未站上前 20 日高/,
    "the ellipsized add-side reason is not recoverable");

  await assertActive(0);
  const stage = page.locator("#verdict-deck-stage");
  await page.locator(".deck-dot").nth(1).click();
  await page.waitForFunction(() => {
    const stage = document.getElementById("verdict-deck-stage");
    const card = stage.querySelector(".deck-card");
    return new DOMMatrix(card.style.transform).m41 < -stage.clientWidth * .55;
  });
  await assertActive(1); // while the spring is still moving
  await page.waitForTimeout(900);
  await assertActive(1);

  // ArrowLeft bubbles from a control in the active card to the stage handler.
  await page.locator("#verdict-deck .deck-card").nth(1).locator("button").focus();
  await page.keyboard.press("ArrowLeft");
  await page.waitForFunction(() =>
    document.querySelector(".deck-dot")?.getAttribute("aria-current") === "true");
  await assertActive(0);
  await page.waitForTimeout(900);

  // Hold a swipe beyond halfway without releasing: the pager and ARIA state
  // must already follow the visually dominant second card.
  const box = await stage.boundingBox();
  await page.mouse.move(box.x + box.width * .8, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .2, box.y + box.height / 2, { steps: 8 });
  await assertActive(1);
  await page.mouse.up();
  await page.waitForTimeout(900);
  await assertActive(1);
  await context.close();
}

// 数据健康卡：降级/恢复必须点名是哪一档（kcn 2026-08-25：「如果有降级的应该
// 标注出来是哪个」），微信单通道掉投必须可数、可点名（#771 让它在 summarizer
// 里可数，但那个计数从没进过任何读者能看到的地方）。
// 点名的位置从判词挪到了「投递」泳道（kcn 2026-09-01：「我也不知道该怎么看」
// ⇒ 判词只回答「页面上的数字能不能信」，一个任务没落地不改变这个答案）。
// 断言跟着挪，但要求不变：**不展开就能读到是哪一档、发生了什么**。
async function testAddSideCardExplainsWhyThereIsNoAdd(browser, base) {
  // 47 天里 48 次收盘突破对 0 条加仓建议，而面板上没有任何地方能问「为什么」。
  // 这张牌就是那个答案，它有三部分且三部分都是数字：证据族开机到哪了、今天的
  // 读数是什么、每种入场形态历史上值多少。这里钉住的是最容易被做丢的那两样：
  // 「没有候选的原因」必须显示出来（静默的零就是当初那 47 天），以及形态表必须
  // 带基线行（命中 50% 在基线也是 50% 的地方毫无意义）。
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await stubLiveOrigin(page, {
    patch: (name, json) => {
      if (name !== "overview.json" && name !== "dashboard.json") return null;
      json.add_side = {
        as_of: "2026-09-05", pending: false, cold_start: true,
        counts: { candidate: 0, wait: 9, reject: 1 },
        why_no_candidate: "3 只已收盘站上前 20 日高，但 z≥2 判为追高：ROBN z=2.96",
        families: [
          { name: "price_relative_factor", active: false,
            progress: { counter: "prospective_dates", have: 8, need: 24 },
            blockers: ["prospective_dates"] },
          { name: "point_in_time_information", active: false,
            progress: { counter: "history_dates", have: 16, need: 24 },
            blockers: ["history_dates"] },
        ],
        rows: [{ ticker: "CRCL", verdict: "wait", why: "窗口内无一手公告",
                 needs: "站上 96.4", prior_20d_high: 96.4, pct_from_high: -7.09 }],
        shapes: {
          names: 25, run_id: "add_shapes-20260905-deadbeef",
          shapes: {
            breakout: { t1: [93, .548, 1.44], t5: [93, .591, 3.77], t20: [84, .655, 20.06] },
            pullback_in_uptrend: { t1: [436, .456, -.24], t5: [413, .455, .64], t20: [313, .383, 3.99] },
          },
          baseline: { t1: [3135, .506, .26], t5: [3035, .486, 1.13], t20: [2660, .501, 5.24] },
        },
        track_record: { cut: { hit_rate: .5258, win: 112, loss: 101, settled: 213 } },
      };
      return json;
    },
  });
  const state = observe(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "plan");
  await waitForTab(page, "plan");

  const card = page.locator("#add-side-card");
  await card.waitFor({ state: "visible" });
  const text = await card.innerText();
  assert.match(text, /没有候选的原因/,
    "a silent zero add side is exactly the 47 days this card exists to end");
  assert.match(text, /ROBN z=2\.96/, "the reason lost the names and numbers behind it");
  assert.match(text, /基线 · 随便哪一天/,
    "the shape table lost its baseline row — every hit rate now reads as better than it is");
  assert.match(text, /冷启动/, "the cold-start state was not surfaced");
  assert.match(text, /8\/24|16\/24/, "the family warm-up counters are not rendered");

  const bars = await page.locator("#add-side-card .add-family-bar i").evaluateAll(
    nodes => nodes.map(node => node.style.width));
  assert(bars.length >= 2 && bars.every(width => /%$/.test(width)),
    "the warm-up bars carry no width, so the progress is invisible");

  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await page.close();
}

async function testALeveragedRowWithoutVolatilityPrintsNoUndefined(browser, base) {
  // 2026-09-11 live, Holdings tab: SPCH is a 2x whose underlying (SPCX) has no
  // volatility yet, so `compute_breakeven_math` leaves its drag figures out —
  // and the book card printed「横盘 decay ≈undefined%/月」. The Risk tab's copy
  // of the same row already skipped it. Every holding gets such a row here so
  // the case does not depend on which tickers the CI build happens to carry.
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await stubLiveOrigin(page, {
    patch: (name, json) => {
      if (name !== "dashboard.json") return null;
      const holdings = [...((json.holdings || {}).us || []), ...((json.holdings || {}).hk || [])];
      json.breakeven_math = {
        rows: holdings.map(h => ({ ticker: h.ticker, pnl_pct: -18.8,
                                    breakeven_need_pct: 23.2, leveraged: true })),
        note: "",
      };
      return json;
    },
  });
  const state = observe(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  for (const tab of ["drill", "risk"]) {
    await clickTab(page, tab);
    await waitForTab(page, tab);
  }
  const book = await page.locator("#book-card").textContent();
  assert.match(book, /回本需\s*\+23\.2%/, "the breakeven row itself must still render");
  const pageText = await page.evaluate(() =>
    [...document.querySelectorAll(".panel")].map(panel => panel.textContent).join("\n"));
  assert.doesNotMatch(pageText, /(?:undefined|NaN)\s*%/,
    "a missing number was formatted as text instead of being left out");

  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await page.close();
}

// Every numeric field of every object in the payload, nulled out ("null") or
// removed ("absent"). Array elements are left alone — a series of nulls is a
// different contract (the charts own it) — and so are the counters the loader
// itself validates.
function sparsePayload(value, mode) {
  if (Array.isArray(value)) {
    return value.map(item => (item && typeof item === "object") ? sparsePayload(item, mode) : item);
  }
  if (!value || typeof value !== "object") return value;
  const keep = /version|^v$|count$|_n$|^n$|^known$|limit|window|size|bytes/;
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "number" && !keep.test(key)) {
      if (mode === "null") out[key] = null;
      continue;
    }
    out[key] = sparsePayload(item, mode);
  }
  return out;
}

// 「缺失数字」的判据：这些词只有在**值的位置**才算漏格式化。
//
// 判红过两次，两次都不是渲染器的错，是**被引用的正文**：
//   · `https://truthsocial.com/users/…/117255718355537976I am calling…`
//     —— 帖子 id 的结尾正好是 `null`，紧跟一个字母（#1473 扩源后第一次出现）
//   · `…the so-called “Infinity” sculpture that stands…`
//     —— 一条帖子正文里的英文单词
//
// 原来的写法是「正文里出现这些词就报」，于是这条闸会随着**被引用的内容**漂移：
// 谁转发一条含 "Infinity" 的帖子，它就把 master 判红。而它本来盯的是渲染器。
//
// 值的位置 = 整段就是它 / 出现在末尾 / 前面是货币或数值运算符。
// 逐条验过 18 个用例（10 条真值 + 8 条散文）：**0 判错**。
// 有意不把 `=` 和 `:` 算作值前运算符 —— 模型在散文里写
// `swap_mandate = null 无 1x 替代` 是描述字段为空，不是漏格式化的数字，
// 而「末尾的值」那条已经覆盖了真正拼在句子尾部的漏格式化。
//
// 模式写成字符串：这段代码跑在 page.evaluate 里（浏览器上下文），Node 作用域的
// 常量过不去，所以传进去再 new RegExp。
const VALUE_LEAK_PATTERNS = [
  "\\[object Object\\]",
  "^(?:undefined|NaN|[-+]?Infinity|null)(?:%| ?(?:bps|股|倍))?$",
  "(?:^|[\\s:：,，、=(（])(?:undefined|NaN|[-+]?Infinity|null)(?:%| ?(?:bps|股|倍))?[\\s.。)]*$",
  "[@$/≈]\\s*(?:undefined|NaN|[-+]?Infinity|null)(?![\\w-])",
  "[+=−-]\\s*(?:undefined|NaN|[-+]?Infinity)\\b",
];

async function testNoTabPrintsAMissingNumber(browser, base) {
  // 2026-09-11 live: 「横盘 decay ≈undefined%/月」 on the Holdings tab, because one
  // renderer guarded a field and its twin did not. Rendering every tab with the
  // numbers taken away found eleven more of the same shape the next day —
  // `浮亏 undefined% → 回本需 +undefined%`, `卖出 null 股 @ $null`, `p10 null`…
  // — none visible on real data, all one missing field away. `numText` /
  // `fmtNum` / `fmtPct` / `fmtMoney` print DASH for a missing number; a raw
  // `${field}` does not.
  for (const mode of ["null", "absent"]) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await stubLiveOrigin(page, { patch: (_name, json) => sparsePayload(json, mode) });
    const state = observe(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    const hits = [];
    for (const tab of TABS) {
      await clickTab(page, tab);
      await waitForTab(page, tab);
      hits.push(...(await page.evaluate(patterns => {
        const out = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (node.parentElement.closest("script, style")) continue;
          const text = node.textContent.trim();
          if (patterns.some(src => new RegExp(src).test(text))) {
            const holder = node.parentElement.closest("[id]");
            out.push(`${holder ? holder.id : "?"}: ${text.slice(0, 80)}`);
          }
        }
        return out;
      }, VALUE_LEAK_PATTERNS)));
    }
    assert.deepEqual([...new Set(hits)], [],
      `a missing number was printed as text (mode=${mode}) — format it with numText/fmtNum`);
    assert.deepEqual(state.errors, [], `a renderer threw on a payload with ${mode} numbers`);
    await context.close();
  }
}

// 验证台账（Reflect）。这张卡的可读性就是它的全部价值：判定分三种、样本/来源
// 各一行、每节 6–9 个数字行、最后一段读数。原来的独立页把这些压进一张
// markdown 表，所以这里断言的是**结构**——判定可见、tone 正确、读数里没有
// markdown 的星号漏出来（那正是搬到看板时最容易炸的地方）、窄屏不横滚。
async function testTheValidationLedgerRendersItsVerdictsAndFitsAPhone(browser, base) {
  const payload = {
    schema_version: 1,
    generated_at: "2026-09-12T00:00:00Z",
    sections: [
      {
        title: "杠杆刻度盘（生产 tier 映射）",
        verdict: "🔴 未通过", verdict_key: "failed", tone: "bad",
        sample: "1370 根日线 · 2021-01-04 → 2026-07-31",
        source: "run card `regime_dial_validation-20260802-896b2145`",
        reading: "观测到的改善比随机重排同一条敞口路径的中位数还差（10.2%）。"
          + "p = 0.925 是未能拒绝原假设，不是证伪。",
        rows: [
          { label: "样本内改善（对比一直 2x）", value: "-91.6% vs -95.5%，即 +3.9pp" },
          { label: "置换检验 p 值（回撤 / 收益）", value: "0.925 / 0.970" },
        ],
      },
      {
        title: "截面因子（预注册）",
        verdict: "⏳ 尚未到期", verdict_key: "pending", tone: "wait",
        sample: "预注册于 2026-08-16",
        source: "`assets/data/cross_sectional_factor.json`",
        reading: "这不是一条没通过的检验，是还没到期。",
        rows: [{ label: "`registered_at`", value: "0 / 需要 20 · ⚪ 未达标" }],
      },
    ],
  };

  for (const [label, width] of [["desktop", 1280], ["mobile", 390]]) {
    const context = await browser.newContext({ viewport: { width, height: 844 } });
    const page = await context.newPage();
    const state = observe(page);
    await stubLiveOrigin(page, {
      patch: (name, json) => (name === "evidence.json" ? payload : null),
    });
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    await clickTab(page, "reflect");
    await waitForTab(page, "reflect");

    const seen = await page.evaluate(() => {
      const card = document.getElementById("ledger-card");
      if (!card) return { missing: true };
      const sections = [...card.querySelectorAll(".lg-section")];
      return {
        sections: sections.length,
        verdicts: sections.map(s => s.querySelector(".lg-verdict").textContent.trim()),
        tones: sections.map(s => s.dataset.tone),
        rows: sections.map(s => s.querySelectorAll(".lg-row").length),
        // 读数里不许出现 markdown 的强调标记 —— 看板把文本当文本印。
        stars: (card.innerText.match(/\*\*/g) || []).length,
        codeSpans: card.querySelectorAll(".lg-reading code, .lg-row code").length,
        sampleShown: !!card.querySelector(".lg-metabar"),
        overflow: card.scrollWidth - card.clientWidth,
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        height: Math.round(card.getBoundingClientRect().height),
      };
    });

    assert(!seen.missing, `${label}: the ledger card is not in the Reflect panel`);
    assert.equal(seen.sections, 2, `${label}: the ledger dropped a section`);
    assert.deepEqual(seen.verdicts, ["🔴 未通过", "⏳ 尚未到期"],
      `${label}: the verdict is not stated on the section`);
    assert.deepEqual(seen.tones, ["bad", "wait"],
      `${label}: the verdict tone is not carried through — a failed test and a
       not-yet-due one would paint the same`);
    assert.deepEqual(seen.rows, [2, 1], `${label}: the numbers are missing`);
    assert.equal(seen.stars, 0,
      `${label}: markdown emphasis leaked into the card — the reading prints literal asterisks`);
    assert(seen.codeSpans >= 1, `${label}: identifiers lost their monospace span`);
    assert(seen.sampleShown, `${label}: the section printed no sample/source line`);
    assert.equal(seen.overflow, 0, `${label}: the ledger card scrolls sideways`);
    assert.equal(seen.pageOverflow, 0, `${label}: the ledger widened the page`);
    assert.deepEqual(state.errors, [], `${label}: a ledger renderer threw`);
    await context.close();
  }
}

// 搜索可见性的独立小卡（Overview）。它原本是数据健康卡里的一条 meta，那条 bit
// 在窄屏上固定 428px 宽 —— 比容器还宽，占满一整行，把卡顶高。抽出来之后判据是
// **一个数字一格，换行交给 grid**，所以这里量的是格数与溢出，不是某段文字。
// Every row inside an Add Campaign panel starts on the same line.
//
// `.add-campaign-leg` (Holdings) and `.campaign-market` (its run-card evidence)
// are the same inset panel, and each row type wrote its own horizontal padding:
// the header 11px, the run-card horizon rows 10px, and the collapsed fold — a
// `<summary>` styled 600 lines away with the rest of the fold — 0. So the
// one-line 「全部 N 只同态」 summary sat flush against the panel's border while
// the header directly above it was indented, which is the left edge kcn saw on
// the Holdings 量化 × 信息 card.
//
// Measured rather than read off the sheet: the offending declaration was valid
// CSS in a rule that never mentions the panel, so only the rendered result
// says whether a row is on the line. Both fold states, because the rows under
// the summary only exist when it is open.
async function testEveryAddCampaignRowStartsOnTheSameLine(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "drill");
  await page.waitForSelector(".add-campaign-leg", { timeout: 10000 });

  const measure = () => page.evaluate(() => {
    const inset = (el, origin) => {
      const cs = getComputedStyle(el), r = el.getBoundingClientRect();
      return +(r.left + (parseFloat(cs.borderLeftWidth) || 0)
        + (parseFloat(cs.paddingLeft) || 0) - origin).toFixed(1);
    };
    // Every element that paints a row's text directly in the panel. Listed by
    // role, not by class, so a row type added later is measured too.
    const ROWS = ":scope > h4, :scope > .add-campaign-row, :scope > .campaign-horizon,"
      + " :scope > .empty-state, :scope > .campaign-fold > summary,"
      + " :scope > .campaign-fold > .add-campaign-row";
    return [...document.querySelectorAll(".add-campaign-leg, .campaign-market")].map(panel => {
      const ps = getComputedStyle(panel), pr = panel.getBoundingClientRect();
      const origin = pr.left + (parseFloat(ps.borderLeftWidth) || 0)
        + (parseFloat(ps.paddingLeft) || 0);
      const rows = [...panel.querySelectorAll(ROWS)]
        .filter(el => getComputedStyle(el).display !== "none"
          && el.getBoundingClientRect().width > 10)
        .map(el => ({
          what: el.tagName.toLowerCase()
            + (el.className ? "." + String(el.className).split(/\s+/)[0] : ""),
          inset: inset(el, origin),
        }));
      return { panel: String(panel.className).split(/\s+/)[0], rows };
    }).filter(p => p.rows.length > 1);
  });

  const check = async label => {
    const panels = await measure();
    assert.ok(panels.length, `${label}: no Add Campaign panel had rows to measure`);
    for (const panel of panels) {
      const insets = [...new Set(panel.rows.map(row => row.inset))];
      assert.equal(insets.length, 1,
        `${label}: rows in .${panel.panel} start at different left edges — `
        + panel.rows.map(row => `${row.what}=${row.inset}`).join(", "));
      assert.ok(insets[0] > 0,
        `${label}: rows in .${panel.panel} sit flush against the panel border `
        + `(inset ${insets[0]})`);
    }
  };

  await check("fold closed");
  await page.evaluate(() => document.querySelectorAll(".campaign-fold")
    .forEach(fold => { fold.open = true; }));
  await page.waitForTimeout(300);
  await check("fold open");

  await context.close();
}

async function testTheSearchVisibilityCardFitsWithoutOverflowing(browser, base) {
  for (const [label, width, expectedCols] of [["desktop", 1280, 4], ["mobile", 390, 2]]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const state = observe(page);
    // The figures are pinned in the payload, not read from the published
    // generation: the weekly reading moves (28 天 51 → 53 on 2026-09-17) and a
    // layout check must not go red because Google counted two more impressions.
    await stubLiveOrigin(page, {
      patch: (name, json) => {
        if (name !== "overview.json" && name !== "dashboard.json") return null;
        json.crawl_visibility = {
          available: true, as_of: "2026-09-11", window_days: 7,
          impressions: 44, clicks: 0, impressions_28d: 51, position: 6.98,
          pages_with_impressions: 1, queries_reported: 5, sitemap_fetched: null,
        };
        return json;
      },
    });
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    await page.waitForSelector("#search-card", { timeout: 5000 });

    const seen = await page.evaluate(() => {
      const card = document.getElementById("search-card");
      const cells = [...card.querySelectorAll(".sv-cell")];
      const cols = new Set(cells.map(c => Math.round(c.getBoundingClientRect().left)));
      const meta = document.getElementById("dh-meta");
      const bits = [...document.querySelectorAll("#dh-meta .dh-meta-bit")];
      return {
        cells: cells.length,
        columns: cols.size,
        texts: cells.map(c => c.innerText.replace(/\s+/g, " ").trim()),
        cellOverflow: cells.filter(c => c.scrollWidth > c.clientWidth + 1).length,
        cardOverflow: card.scrollWidth - card.clientWidth,
        cardHeight: Math.round(card.getBoundingClientRect().height),
        // 数据健康卡那一行：搜索那一段必须已经不在里面了，而且剩下的段不被切。
        metaText: meta ? meta.innerText : "",
        metaClipped: bits.filter(b => b.scrollWidth > b.clientWidth + 1).length,
        metaOverflow: meta ? meta.scrollWidth - meta.clientWidth : 0,
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });

    assert.equal(seen.cells, 4, `${label}: the card lost a figure`);
    assert.equal(seen.columns, expectedCols,
      `${label}: expected ${expectedCols} columns, found ${seen.columns}`);
    assert.deepEqual(seen.texts, [
      "曝光 · 7 天 44 28 天 51",
      "点击 · 7 天 0 没有点击",
      "被收录的页 1 全站 107 条 URL",
      "平均排名 6.98 5 个搜索词有曝光",
    ], `${label}: the figures changed shape`);
    assert.equal(seen.cellOverflow, 0, `${label}: a cell's content overflows its box`);
    assert.equal(seen.cardOverflow, 0, `${label}: the card scrolls sideways`);
    assert(seen.cardHeight <= 300,
      `${label}: the card is ${seen.cardHeight}px — it was supposed to be a small card`);
    assert(!/搜索/.test(seen.metaText),
      `${label}: the search line is still in the data-health meta — that is the 428px box this card replaced`);
    assert.equal(seen.metaClipped, 0, `${label}: a data-health meta bit is clipped`);
    assert.equal(seen.metaOverflow, 0, `${label}: the data-health meta overflows`);
    assert.equal(seen.pageOverflow, 0, `${label}: the page scrolls sideways`);
    assert.deepEqual(state.errors, [], `${label}: a renderer threw`);
    await page.close();
  }
}

async function testAPanelSaysWhenItsDataDidNotLoad(browser, base) {
  // A detail tab needs dashboard.json (191 KB, normally from the data branch)
  // before it can paint. When that request failed the only trace was
  // `console.error`: `aria-busy` came back off and the panel kept its card
  // chrome and an empty table, which reads as "you hold nothing" rather than
  // "this did not load". Refuse the document on both origins and check the
  // panel says so — then let it through and check 重试 actually fills it.
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await stubLiveOrigin(page);
  let refuse = true;
  await page.route(/\/assets\/data\/dashboard\.json(?:\?.*)?$/, async route => {
    if (refuse) return route.abort("failed");
    const body = fs.readFileSync(path.resolve(ROOT, "assets/data/dashboard.json"), "utf8");
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      },
      body,
    });
  });
  await page.goto(base, { waitUntil: "domcontentloaded" });
  await waitForData(page);

  await clickTab(page, "drill");
  const panel = page.locator('.panel[data-panel="drill"]');
  const box = panel.locator(".panel-load-error");
  await box.waitFor({ state: "visible", timeout: 15000 });
  assert.equal(await panel.getAttribute("data-load-error"), "true",
    "the state the CSS selects on must be on the panel itself");
  assert.equal(await panel.getAttribute("aria-busy"), null,
    "a panel that failed is not still busy");
  const retry = box.locator("button");
  assert.equal(await retry.count(), 1, "the retry must be one real button");
  assert.equal(
    await retry.evaluate(el => el === document.activeElement ||
      el.tagName === "BUTTON" && !el.disabled),
    true, "the retry has to be reachable by keyboard");
  assert.equal(await panel.locator("#book-table tbody tr").count(), 0,
    "nothing painted, which is exactly why the message has to be there");

  refuse = false;
  await retry.click();
  await waitForTab(page, "drill");
  assert.equal(await box.count(), 0, "the message must clear once the data lands");
  assert.ok(await panel.locator("#book-table tbody tr").count() > 0,
    "retry did not actually re-fetch");
  await page.close();
}

// ── 数据健康 ─────────────────────────────────────────────────────────────
// 这块牌三层：判词 + 四个领域读数 → 定时任务监测板 → 选中后就地展开的明细。
// payload 由用例自己造（形状固定，不随当日数据时灵时不灵），量的是浏览器
// 真排出来的东西。
function dataHealthFixture(json, { stale = false } = {}) {
  json.build_status = json.build_status || {};
  json.build_status.integrity = { error_count: 0, warn_count: 1, top: [
    { level: "WARN", code: "quote.us_stale", msg: "SKHY 报价 3 小时未更新" }] };
  json.build_status.files = (json.build_status.files || []).map(f => ({ ...f, present: true, stale: false }));
  json.workflow_outcomes = {
    window_hours: 36,
    counts: { success: 9, recovered: 1 },
    wechat_dropped_telegram_covered: 3,
    degraded_slots: [{ job: "港股收盘报告", slot: "2026-08-25T16:00:00+08:00", status: "recovered" }],
    wechat_dropped_slots: [
      { job: "港股收盘报告", slot: "2026-08-25T16:00:00+08:00" },
      { job: "盘中盯盘", slot: "2026-08-25T15:30:00+08:00" },
    ],
  };
  const hkt = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Hong_Kong" }).format(new Date());
  json.cron_schedule = { date: stale ? "2026-09-20" : hkt, jobs: [
    { job: "正常任务", last_success_at: "2026-09-24T08:05:00+08:00",
      slots: [{ at: "08:00", state: "ok" }, { at: "08:30", state: "ok" }] },
    { job: "尚未到期任务", slots: [{ at: "23:50", state: "upcoming" }] },
    { job: "需关注任务", slots: [{ at: "09:00", state: "degraded",
      note: { disposition: "watch", text: "已送达，但发布延迟" } }] },
    { job: "失败任务", slots: [{ at: "10:00", state: "failed",
      note: { disposition: "needs_action", text: "成品没有送达" } }] },
    { job: "状态未知的很长很长很长很长很长很长很长的任务名称 with-an-english-suffix",
      slots: [{ at: "12:00", state: "unknown" }] },
    { job: "Memory Dreaming Promotion", unmonitored: true, slots: [{ at: "03:00", state: "unmonitored",
      note: { disposition: "normal", text: "这个 job 没有 harness，账本本来就看不到它的记录，不代表没跑" } }] },
  ] };
  return json;
}

async function openDataHealth(browser, base, width, options = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 },
    isMobile: width < 768, hasTouch: width < 768 });
  const page = await context.newPage();
  const state = observe(page);
  await stubLiveOrigin(page, { patch: (name, json) =>
    (name === "overview.json" || name === "dashboard.json") ? dataHealthFixture(json, options) : null });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await page.waitForSelector("#data-health:not(.is-pending)", { timeout: 5000 });
  return { context, page, state };
}

// 没有一样东西伸出卡片的内容边：不横滚、不被切、不贴边。
function dataHealthEdges() {
  const card = document.getElementById("data-health");
  const box = card.getBoundingClientRect();
  const style = getComputedStyle(card);
  const left = box.left + parseFloat(style.paddingLeft) - 0.5;
  const right = box.right - parseFloat(style.paddingRight) + 0.5;
  const shown = el => el.getClientRects().length && getComputedStyle(el).visibility !== "hidden";
  return {
    overflow: card.scrollWidth - card.clientWidth,
    page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    outside: [...card.querySelectorAll("*")].filter(shown).filter(el => {
      const r = el.getBoundingClientRect();
      return r.width && (r.left < left || r.right > right);
    }).map(el => `${el.tagName}.${el.className}`).slice(0, 5),
    clipped: [...card.querySelectorAll("*")].filter(shown).filter(el =>
      el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0
      && getComputedStyle(el).textOverflow !== "ellipsis"
      && getComputedStyle(el).webkitLineClamp === "none").map(el => el.className).slice(0, 5),
  };
}

async function testDataHealthAnswersIsAnythingWrongAtEveryWidth(browser, base) {
  for (const width of [390, 1280]) {
    const { context, page, state } = await openDataHealth(browser, base, width);
    const seen = await page.evaluate(() => {
      const card = document.getElementById("data-health");
      const text = el => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
      const dot = el => getComputedStyle(el, "::before");
      const rows = [...card.querySelectorAll(".dh-job")];
      const sum = text(document.getElementById("dh-board-sum"));
      return {
        verdict: text(document.getElementById("dh-title")),
        meta: text(document.getElementById("dh-meta")),
        cells: [...card.querySelectorAll(".dh-cell")].map(c => ({ key: c.dataset.key, tag: c.tagName,
          label: text(c.querySelector(".dh-cell-label")), state: text(c.querySelector(".dh-state")),
          value: text(c.querySelector(".dh-cell-value")), note: text(c.querySelector(".dh-cell-note")),
          expanded: c.getAttribute("aria-expanded") })),
        todo: [...card.querySelectorAll("#dh-todo .dh-item")].map(r => ({
          name: text(r.querySelector(".dh-item-name")), why: text(r.querySelector(".dh-item-detail")),
          shown: r.getBoundingClientRect().height > 0 })),
        rows: rows.map(r => ({ job: r.dataset.job, tone: r.dataset.tone,
          state: text(r.querySelector(".dh-job-row > .dh-state")),
          last: text(r.querySelector(".dh-job-last")),
          slots: r.querySelectorAll(".dh-slots i").length,
          height: Math.round(r.querySelector(".dh-job-row").getBoundingClientRect().height),
          sameLine: r.querySelector(".dh-job-row > .dh-state").getBoundingClientRect().top
            < r.querySelector(".dh-job-name").getBoundingClientRect().bottom })),
        okDot: dot(card.querySelector(".dh-job[data-tone='ok'] .dh-state")).backgroundColor,
        pendingDot: dot(card.querySelector(".dh-job[data-tone='pending'] .dh-state")).backgroundColor,
        total: Number((sum.match(/(\d+) 槽/) || [])[1]),
        parts: [...sum.matchAll(/(\d+) (落地|兜底|降级|没落地|进行中|待跑|账本看不到|未知)/g)]
          .reduce((a, m) => a + Number(m[1]), 0),
        caption: text(document.getElementById("dh-caption")),
      };
    });
    const label = `${width}px`;
    // 一件事一处说：一个任务没落地是「需处理」，但页面上的数字仍然可用（#1270）。
    assert.match(seen.verdict, /^1 项需处理 · \d+ 项观察$/, `${label}: verdict ${seen.verdict}`);
    assert(seen.meta.startsWith("页面数字可用"), `${label}: a failed task moved the trust line: ${seen.meta}`);
    assert(/微信掉投 3 档/.test(seen.meta), `${label}: the WeChat drop count is gone: ${seen.meta}`);
    assert.deepEqual(seen.cells.map(c => c.key), ["files", "integrity", "delivery", "cron"]);
    assert.deepEqual(seen.cells.map(c => c.tag), ["BUTTON", "BUTTON", "BUTTON", "DIV"]);
    assert(seen.cells.every(c => c.state && c.value && c.note), `${label}: a reading lacks its state: ${JSON.stringify(seen.cells)}`);
    const delivery = seen.cells.find(c => c.key === "delivery");
    assert.equal(delivery.state, "观察", `${label}: a recovered slot is watch-only`);
    assert(/港股收盘报告 恢复/.test(delivery.note), `${label}: the recovered slot is not named: ${delivery.note}`);
    assert.equal(seen.cells.find(c => c.key === "cron").state, "需处理");
    // 需处理不藏在点击后面；watch 级的槽不混进来。
    assert.deepEqual(seen.todo.map(t => t.name), ["失败任务"], `${label}: ${JSON.stringify(seen.todo)}`);
    assert(seen.todo[0].shown && seen.todo[0].why.includes("成品没有送达"));
    // 每个任务一行、自己的状态；有事的在上，安静的按时刻表原序。
    assert.deepEqual(seen.rows.map(r => r.tone), ["bad", "warn", "stale", "idle", "ok", "pending"],
      `${label}: row order ${JSON.stringify(seen.rows.map(r => r.job))}`);
    assert.deepEqual(seen.rows.map(r => r.state), ["需处理", "观察", "状态未知", "账本看不到", "正常", "待跑"]);
    assert.deepEqual(seen.rows.map(r => r.slots), [1, 1, 1, 1, 2, 1], `${label}: a row lost its slots`);
    assert(seen.rows.every(r => r.last), `${label}: a row has no last-success reading`);
    assert(seen.rows.every(r => r.sameLine), `${label}: a status fell onto its own line`);
    assert(seen.rows.every(r => r.height >= 44), `${label}: a row is below a thumb-sized target`);
    // #1816：健康永远不长得像「还没到点」。
    assert.notEqual(seen.okDot, seen.pendingDot, `${label}: a healthy row reads like a not-yet-due one`);
    assert.equal(seen.parts, seen.total, `${label}: the slot breakdown does not add up to its total`);
    ["需处理", "观察", "已知不修"].forEach(word => assert(seen.caption.includes(word),
      `${label}: the disposition legend does not explain ${word}`));
    const edges = await page.evaluate(dataHealthEdges);
    assert.deepEqual(edges, { overflow: 0, page: 0, outside: [], clipped: [] }, `${label}: ${JSON.stringify(edges)}`);
    assert.deepEqual(state.errors, [], `${label}: a renderer threw`);
    await context.close();
  }
}

async function testDataHealthDrillsDownWhereYouTapAndSurvivesARefresh(browser, base) {
  for (const width of [390, 1280]) {
    const { context, page, state } = await openDataHealth(browser, base, width);
    const label = `${width}px`;
    // 一个任务：键盘就能打开，明细就地摊开，带原始字段与来源。
    const row = page.locator(".dh-job-row").first();
    await row.focus();
    await page.keyboard.press("Enter");
    assert.equal(await row.getAttribute("aria-expanded"), "true", `${label}: Enter did not open the row`);
    const detail = page.locator(".dh-job-detail").first();
    assert(await detail.isVisible(), `${label}: the row's detail stayed hidden`);
    assert.match(await detail.innerText(), /10:00[\s\S]*未落地[\s\S]*成品没有送达/);
    assert.match(await detail.innerText(), /last_success_at:[\s\S]*schedule\.date:/);
    assert.equal(await detail.locator("a").count(), 1, `${label}: the detail has no source artifact`);

    // 一个领域：像 tab，一次只开一个，再按一次收起。
    await page.click("button.dh-cell[data-key='files']");
    const panels = () => page.evaluate(() => [...document.querySelectorAll(".dh-panel")]
      .filter(p => !p.hidden).map(p => p.id));
    assert.deepEqual(await panels(), ["dh-panel-files"]);
    const files = await page.evaluate(() => ({
      rows: document.querySelectorAll("#dh-panel-files .dh-item").length,
      expected: document.querySelectorAll("#dh-panel-files .dh-state").length,
      below: document.getElementById("dh-panel-files").getBoundingClientRect().top
        >= document.getElementById("dh-cells").getBoundingClientRect().bottom - 1,
    }));
    assert(files.rows > 0 && files.rows === files.expected, `${label}: the file ledger is empty or stateless`);
    assert(files.below, `${label}: the ledger does not open under the readings`);
    await page.click("button.dh-cell[data-key='integrity']");
    assert.deepEqual(await panels(), ["dh-panel-integrity"], `${label}: two ledgers are open at once`);
    assert.match(await page.locator("#dh-panel-integrity").innerText(), /SKHY 报价 3 小时未更新/);
    const edges = await page.evaluate(dataHealthEdges);
    assert.deepEqual(edges, { overflow: 0, page: 0, outside: [], clipped: [] }, `${label} open: ${JSON.stringify(edges)}`);

    // 刷新是每几分钟一次的事：读者刚打开的东西不能被合回去。
    await page.evaluate(() => renderDataHealth());
    assert.deepEqual(await panels(), ["dh-panel-integrity"], `${label}: a refresh closed the ledger`);
    assert.equal(await page.locator(".dh-job-row").first().getAttribute("aria-expanded"), "true",
      `${label}: a refresh closed the open row`);
    await page.click("button.dh-cell[data-key='integrity']");
    assert.deepEqual(await panels(), [], `${label}: pressing the open reading again did not close it`);
    assert.deepEqual(state.errors, []);
    await context.close();
  }
}

async function testAnOldScheduleIsOneWatchItemNotOnePerJob(browser, base) {
  const { context, page } = await openDataHealth(browser, base, 390, { stale: true });
  const seen = await page.evaluate(() => ({
    verdict: document.getElementById("dh-title").textContent.trim(),
    states: [...document.querySelectorAll(".dh-job-row > .dh-state")].map(el => el.textContent.trim()),
    sum: document.getElementById("dh-board-sum").textContent,
    todo: document.querySelectorAll("#dh-todo .dh-item").length,
  }));
  assert(seen.states.every(s => s === "过期"), `stale schedule rows: ${seen.states}`);
  assert(/时刻表停在 2026-09-20/.test(seen.sum), seen.sum);
  // 旧时刻表上的「失败」不是今天的待办；它和其它观察项合起来也只算一件。
  assert.equal(seen.todo, 0);
  assert.equal(seen.verdict, "3 项观察中", seen.verdict);
  await context.close();
}

async function testMoversSayWhichSessionTheyAreFrom(browser, base) {
  // 「今日异动」印的是 portfolio.json 里的 today_change_pct，也就是最近一次
  // 报价的涨跌。周末打开面板，那是周五的数字，却顶着「今日」；周一开盘前同样。
  // 一周里大约三分之一的时间这两个字是错的。同一张牌下面十行的 catalyst 块
  // 早就拒绝用浏览器的「今天」（它从 last_updated 取日期），这里是同一条拒绝。
  for (const [label, lastUpdated, generatedAt, expected] of [
    ["weekend", "2026/09/05 04:03 HKT", "2026-09-06T16:40:05Z", "异动 · 最近收盘"],
    ["live session", "2026/09/04 16:10 HKT", "2026-09-04T08:15:00Z", "今日异动"],
  ]) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await stubLiveOrigin(page, {
      patch: (name, json) => {
        if (name !== "overview.json" && name !== "dashboard.json") return null;
        json.last_updated = lastUpdated;
        json.generated_at = generatedAt;
        json.today_movers = [
          { ticker: "SKHY", name: "SK", region: "us", today_change_pct: 8.14, current_price: 177 },
          { ticker: "07226", name: "XL", region: "hk", today_change_pct: 4.4, current_price: 3.18 },
        ];
        return json;
      },
    });
    const state = observe(page);
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);

    const head = page.locator(".hl-mv-head");
    await head.waitFor({ state: "visible" });
    assert.equal((await head.innerText()).trim(), expected,
      `${label}: the movers card claims the wrong session`);

    const aria = await page.locator(".hl-movers").getAttribute("aria-label");
    assert(aria && aria.startsWith(expected),
      `${label}: the screen-reader label still says something else: ${aria}`);

    assert.deepEqual(state.failures, []);
    assert.deepEqual(state.errors, []);
    await context.close();
  }
}

// 手机上打开一个「有 sidecar 的 tab」，那份 sidecar 必须真的落到卡上。
//
// 实测的坏法：mobile 的 tab 切换走 pager 滚动，activateTabData 的 promise 常
// 常在 pager 还没停稳时兑现 ⇒ `currentTab() !== t` ⇒ 整个 .then 直接 return，
// 于是抓回来的 sidecar 从来没被写进 DATA。之后每次再进这个 tab 都走「什么都
// 不缺」的快路径（sidecar 确实 ready 了），而那条路径也不写 DATA —— 于是那张
// 卡在这一整个会话里都是空的，只有整页刷新能救。桌面宽度不复现（没有 pager）。
// 辩论留痕：一场辩论一行，点开看全文。
//
// 2026-09-09 实测线上 390px：30 场辩论的全文一次全摊开 = **8908px** 的一块，
// 自评卡整张 12287px（十四个屏幕）。一场辩论是读者心里的一个单位，所以摘要
// 行印「谁 · 哪天 · 判了什么 · Judge 的一句话」，全文在展开后一个字不改。
//
// payload 是这个用例自己造的：`decision_audit.json` 不进仓库，CI 上根本没有
// 这份文件，靠当日数据的断言在那里等于没跑。造的是**输入的形状**（多少场、
// 每场多长），量的仍然是浏览器真排出来的高度与可达性。
// Plan Timeline：先扫得动，再读得下去。
//
// 2026-09-09 实测线上 390px：15 条决策卡把 rationale 全文一次全摊开 =
// **4615px**（一条 209-369px），一张卡五个屏幕。理由的第一行往往就是那句话的
// 要点，所以是**夹**（两行 + 展开）而不是藏；卡的尾巴照例折起来。
async function testThePlanTimelineClampsItsRationales(browser, base) {
  const total = 15, head = 6;
  const long = "这条是为了让理由确实超过两行而写的长文：" + "因为".repeat(120);
  const plan = [];
  for (let i = 0; i < total; i++) {
    plan.push({
      date: "2026-09-0" + (i % 9 + 1), ticker: `T${1000 + i}`, action: "hold_and_watch",
      strategy_id: "core_position", condition: { type: "manual" }, confidence: 0.5,
      outcome: "pending", execution: "unknown",
      // 最后一条故意是短理由：短理由不该配一个什么都不展开的按钮。
      rationale: i === total - 1 ? "一句话就说完了。" : `第 ${i + 1} 条：${long}`,
    });
  }
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page, {
    patch: (name, json) => {
      // The timeline ships in the decision-trail sidecar since 2026-09-12.
      if (name !== "decision_trail.json") return null;
      json.plan_timeline = plan;
      return json;
    },
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "plan");
  await waitForTab(page, "plan");
  await page.waitForFunction(() => document.querySelectorAll("#plan-timeline .pt-row").length > 0,
    null, { timeout: 15000 })
    .catch(() => { throw new Error("the plan timeline never rendered") });

  const shape = await page.evaluate(() => {
    const wrap = document.getElementById("plan-timeline");
    const rows = [...wrap.querySelectorAll(".pt-row")];
    const fold = wrap.querySelector(".pt-fold");
    const clamped = [...wrap.querySelectorAll(".pt-rationale.is-clamped")];
    return {
      rows: rows.length,
      onScreen: rows.filter(row => row.getBoundingClientRect().height > 0).length,
      cardHeight: Math.round(wrap.closest(".card").getBoundingClientRect().height),
      rowHeights: rows.slice(0, 4).map(r => Math.round(r.getBoundingClientRect().height)),
      clamped: clamped.length,
      // 夹住的那一段必须真的比它显示出来的高——否则 is-clamped 只是个类名。
      trulyClipped: clamped.filter(el => el.scrollHeight > el.clientHeight + 4).length,
      expands: wrap.querySelectorAll(".pt-expand").length,
      controls: [...wrap.querySelectorAll(".pt-expand")]
        .filter(b => document.getElementById(b.getAttribute("aria-controls"))).length,
      fold: fold ? fold.textContent.trim() : null,
    };
  });
  assert.equal(shape.rows, total, `the timeline rendered ${shape.rows} of ${total} actions`);
  assert.equal(shape.onScreen, head,
    `${shape.onScreen} actions are on screen before any tap — the newest ${head} are the list`);
  assert.equal(shape.clamped, total - 1,
    `${shape.clamped} rationales are clamped; the short one must not be`);
  assert.equal(shape.expands, total - 1,
    "a short rationale was given an expander that opens nothing");
  assert.equal(shape.controls, shape.expands,
    "an expander does not point at the rationale it opens");
  assert(shape.trulyClipped >= 3,
    `only ${shape.trulyClipped} clamped rationales are actually cut off — `
    + "is-clamped is decorating text that already fits");
  assert(shape.rowHeights.every(h => h > 0 && h <= 260),
    `a clamped row is ${shape.rowHeights.join("/")}px tall`);
  // 不夹不折是 4600px 起。这条断言是这次改动的全部理由。
  assert(shape.cardHeight <= 1600,
    `the plan timeline is ${shape.cardHeight}px on a phone — five screens of one card`);
  assert(shape.fold && shape.fold.includes(String(total - head)),
    `the tail does not say how many actions it is holding: ${shape.fold}`);

  const opened = await page.evaluate(async () => {
    const wrap = document.getElementById("plan-timeline");
    wrap.querySelector(".pt-expand").click();
    await new Promise(resolve => setTimeout(resolve, 150));
    const first = wrap.querySelector(".pt-rationale");
    return {
      clampedLeft: wrap.querySelectorAll(".pt-rationale.is-clamped").length,
      label: wrap.querySelector(".pt-expand").textContent.trim(),
      expanded: wrap.querySelector(".pt-expand").getAttribute("aria-expanded"),
      grew: first.scrollHeight <= first.clientHeight + 4,
    };
  });
  assert.equal(opened.clampedLeft, total - 2, "expanding one rationale unclamped the others");
  assert.equal(opened.expanded, "true", "the expander did not report itself as open");
  assert(opened.grew, "the rationale is still cut off after being expanded");
  assert(opened.label.includes("收起"),
    `the expander still says "${opened.label}" after opening`);

  const tail = await page.evaluate(async () => {
    document.querySelector("#plan-timeline .pt-fold").click();
    await new Promise(resolve => setTimeout(resolve, 150));
    return [...document.querySelectorAll("#plan-timeline .pt-row")]
      .filter(row => row.getBoundingClientRect().height > 0).length;
  });
  assert.equal(tail, total, `opening the tail showed ${tail} of ${total} actions`);
  await context.close();
}

async function testTheDebateTrailIsAListOfCasesNotAWallOfText(browser, base) {
  const total = 12, head = 6;
  const long = "这一段是为了让每一场辩论在展开时确实很高而写的长文：" + "论据".repeat(60);
  const rows = [];
  for (let i = 0; i < total; i++) {
    rows.push({
      ticker: `T${1000 + i}`, date: "2026-09-0" + (i % 9 + 1), action: "hold_and_watch",
      confidence: 0.5, bull: long, bear: long, attacked_consensus: long,
      judge: `第 ${i + 1} 场的判词：` + long, frames: ["mean_reversion"],
    });
  }
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  // stubLiveOrigin 之后注册：playwright 后注册的路由先匹配，反过来的话这份
  // 造出来的 payload 会被真实文件盖掉（实测：断言拿到的是当日的 30 场）。
  await page.route("**/decision_audit.json*", route => route.fulfill({
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8",
               "access-control-allow-origin": "*" },
    body: JSON.stringify({ debates: { rows, limit: total } }),
  }));
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "reflect");
  await waitForTab(page, "reflect");
  await page.waitForFunction(() => document.querySelectorAll(".dbt-case").length > 0,
    null, { timeout: 15000 })
    .catch(() => { throw new Error("the debate trail never rendered") });

  const shape = await page.evaluate(() => {
    const cases = [...document.querySelectorAll(".dbt-case")];
    const block = document.getElementById("debate-body");
    const more = document.querySelector(".dbt-more");
    return {
      cases: cases.length,
      onScreen: cases.filter(c => c.getBoundingClientRect().height > 0).length,
      openBodies: [...document.querySelectorAll(".dbt-body")]
        .filter(body => !body.hidden).length,
      rowHeights: cases.slice(0, 3).map(c => Math.round(c.getBoundingClientRect().height)),
      blockHeight: Math.round(block.getBoundingClientRect().height),
      toggles: document.querySelectorAll(".dbt-toggle").length,
      gists: [...document.querySelectorAll(".dbt-gist")]
        .map(g => g.textContent.trim()).filter(Boolean).length,
      firstGist: (document.querySelector(".dbt-gist") || {}).textContent || "",
      more: more ? more.textContent.trim() : null,
      moreExpanded: more ? more.getAttribute("aria-expanded") : null,
    };
  });

  assert.equal(shape.cases, total, `the trail rendered ${shape.cases} of ${total} debates`);
  assert.equal(shape.onScreen, head,
    `${shape.onScreen} debates are on screen before any tap — the newest ${head} are the list`);
  assert.equal(shape.openBodies, 0, "a debate starts with its full text open");
  assert.equal(shape.toggles, total, "a debate case is not a button you can open");
  assert.equal(shape.gists, total,
    "a collapsed case does not say what the debate concluded");
  assert(shape.firstGist.startsWith("Judge"),
    `the summary line must carry the Judge's verdict, got "${shape.firstGist.slice(0, 30)}"`);
  assert(shape.rowHeights.every(h => h > 0 && h <= 110),
    `a collapsed case is ${shape.rowHeights.join("/")}px tall — that is not one row`);
  // 不折是 3000px 起（每场 250-420px）。这条断言是这次改动的全部理由。
  assert(shape.blockHeight <= 900,
    `the debate trail is ${shape.blockHeight}px on a phone — it is a wall again`);
  assert(shape.more && shape.more.includes(String(total - head)),
    `the tail does not say how many debates it is holding: ${shape.more}`);
  assert.equal(shape.moreExpanded, "false", "the older debates start unfolded");

  // 点一场，只开那一场；再点尾巴，其余的才出来。
  const opened = await page.evaluate(async () => {
    document.querySelector(".dbt-toggle").click();
    await new Promise(resolve => setTimeout(resolve, 150));
    const first = document.querySelector(".dbt-case");
    return {
      open: [...document.querySelectorAll(".dbt-body")].filter(b => !b.hidden).length,
      expanded: first.querySelector(".dbt-toggle").getAttribute("aria-expanded"),
      height: Math.round(first.getBoundingClientRect().height),
      hasBull: !!first.querySelector(".dbt-bull .dbt-text"),
      judgeInFull: (first.querySelector(".dbt-body") || {}).textContent.includes("第 1 场的判词"),
    };
  });
  assert.equal(opened.open, 1, `tapping one case opened ${opened.open} of them`);
  assert.equal(opened.expanded, "true", "the case did not report itself as open");
  assert(opened.height > 150, `the opened case is only ${opened.height}px — nothing came out`);
  assert(opened.hasBull && opened.judgeInFull,
    "the opened case is missing the argument it was hiding");

  const tail = await page.evaluate(async () => {
    document.querySelector(".dbt-more").click();
    await new Promise(resolve => setTimeout(resolve, 150));
    return [...document.querySelectorAll(".dbt-case")]
      .filter(c => c.getBoundingClientRect().height > 0).length;
  });
  assert.equal(tail, total, `opening the tail showed ${tail} of ${total} debates`);
  await context.close();
}

async function testASidecarStillReachesItsCardWhenThePagerIsStillSettling(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "reflect");
  await waitForTab(page, "reflect");

  // 决策地图整块牌就是 decision_map 这个 sidecar 的消费者：它有行，就说明
  // sidecar 被应用了；它印着「没有载入」，就说明这条路径又断了。
  await page.waitForFunction(
    () => document.querySelectorAll("#dm-board tbody tr").length > 0,
    null, { timeout: 15000 },
  ).catch(() => { throw new Error("the decision map never got its sidecar on a phone"); });

  const state = await page.evaluate(() => ({
    rows: document.querySelectorAll("#dm-board tbody tr").length,
    kpi: document.getElementById("dm-kpi").textContent.trim(),
    applied: !!(DATA && DATA.decision_map),
  }));
  assert(state.applied, "DATA.decision_map is null although the payload was fetched");
  assert(state.rows > 0, "the board rendered no rows");
  assert(!state.kpi.includes("没有载入"),
    `the card is showing its load-failure copy with the payload in hand: ${state.kpi}`);
  await context.close();
}

async function testFailedSidecarRefreshKeepsTheLastGoodValue(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  let requests = 0;
  await page.route("**/decision_audit.json*", route => {
    requests += 1;
    if (requests === 1) {
      return route.fulfill({
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8",
                   "access-control-allow-origin": "*" },
        body: JSON.stringify({ sentinel: "last-good-sidecar" }),
      });
    }
    return route.abort("failed");
  });

  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await clickTab(page, "reflect");
  await waitForTab(page, "reflect");
  await page.waitForFunction(() => DATA?.decision_audit?.sentinel === "last-good-sidecar");

  // Refresh marks loaded sidecars stale. The live request and its same-origin
  // fallback both fail, reproducing the deployment-window/network-error path.
  await page.click("#refresh-btn");
  for (let i = 0; i < 50 && requests < 3; i += 1) await page.waitForTimeout(50);
  assert(requests >= 3, "the failed sidecar revalidation did not exercise both origins");
  await page.waitForTimeout(100);
  const retained = await page.evaluate(() => DATA?.decision_audit?.sentinel || null);
  assert.equal(retained, "last-good-sidecar",
    "a failed sidecar refresh replaced the last good value with null");
  await context.close();
}

// 卡片节奏：同一个宽度下，六个 tab 的「卡与卡之间」必须是同一档，分节间距
// 必须明显大于卡间距。kcn：「我所有卡片之间的间距…现在间距都不统一，可以适当
// 的收紧，但不要完全统一」。
//
// 收敛前 1440×900 的渲染实测：Overview 走 .overview-command 的 16，其余五个
// tab 走 masonry 的 22 —— 同一个宽度、同一种关系，换个 tab 就换一个值；分隔线
// 下方的留白三个值（Risk 18 / Holdings 14 / 手机 4）；指挥台网格与紧随其后的
// 那张卡是 0px（网格的 gap 管不到自己的外沿）；卡内分块两份配方
// （sub-block 18+16，trig-block 16+16）。
//
// 这条闸量几何，不读 CSS 文本：换 token、改选择器、重排规则全都照样过，只有
// 渲染出来的间距真的变了才红。分节间距用「分隔线到它前后最远 / 最近一块的
// 距离」—— 分隔线在桌面上是 column-span:all，两列收尾高度不同，逐列配对量到
// 的是较短的那列，会得到一个比真实值大的数。
const RHYTHM_SAMPLE = ({ tabs }) => {
  const round = n => Math.round(n * 10) / 10;
  const out = {};
  for (const tab of tabs) {
    const panel = document.querySelector(`.panel[data-panel="${tab}"]`);
    if (!panel || getComputedStyle(panel).display === "none") continue;
    // Hero 的指挥台卡片在 .overview-command 里；摊平之后六个 tab 的「顶层块」
    // 才是同一种东西。
    const blocks = [];
    for (const el of panel.children) {
      const group = el.classList.contains("overview-command") ? [...el.children] : [el];
      for (const item of group) {
        const r = item.getBoundingClientRect();
        const cs = getComputedStyle(item);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        if (r.height < 2 || r.width < 2) continue; // 视觉隐藏的 <h2> 不参与
        blocks.push({
          cls: typeof item.className === "string" ? item.className : "",
          left: round(r.left), width: round(r.width),
          top: round(r.top + window.scrollY), bottom: round(r.bottom + window.scrollY),
        });
      }
    }
    const cards = blocks.filter(b => !b.cls.includes("sect-divider"));
    const dividers = blocks.filter(b => b.cls.includes("sect-divider"));
    // 同列配对：先按列分组（桌面 masonry 的 DOM 顺序不等于视觉顺序），再在
    // 同一列里按 y 排。列内相邻两张卡之间的空白就是读者看到的「卡与卡之间」。
    const gaps = [];
    const columns = new Map();
    for (const b of cards) {
      if (!columns.has(b.left)) columns.set(b.left, []);
      columns.get(b.left).push(b);
    }
    for (const column of columns.values()) {
      column.sort((a, b) => a.top - b.top);
      for (let i = 1; i < column.length; i += 1) {
        const gap = round(column[i].top - column[i - 1].bottom);
        if (gap < 0 || gap >= 200) continue;
        // 中间隔着分节线的两张卡量到的是「分节」，不是卡片节奏：分开算，
        // 它只需要比卡片节奏松。
        const straddles = dividers.some(d => d.top >= column[i - 1].bottom - 1 && d.top <= column[i].top + 1);
        gaps.push({ gap, straddles, from: column[i - 1].cls, to: column[i].cls });
      }
    }
    const above = [];
    const below = [];
    for (const d of dividers) {
      const before = blocks.filter(b => b !== d && b.top < d.top);
      const after = blocks.filter(b => b !== d && b.top > d.bottom);
      if (before.length) above.push(round(d.top - Math.max(...before.map(b => b.bottom))));
      if (after.length) below.push(round(Math.min(...after.map(b => b.top)) - d.bottom));
    }
    // 每个 tab 的第一块：面板开头可能有按数据显隐的卡（Plan 的 add-side /
    // watch-levels），它们不占位置但会把「第一块」的位置占掉 —— 真正露出来的
    // 那一张如果按普通卡片推一档，这个 tab 的首块就会比别的 tab 低一格。
    const first = blocks.slice().sort((a, b) => a.top - b.top)[0] || null;
    out[tab] = {
      cards: cards.length,
      gaps: gaps.map(g => g.gap),
      gapDetail: gaps,
      above, below,
      panelTop: round(panel.getBoundingClientRect().top + window.scrollY),
      firstTop: first ? first.top : null,
      firstKind: first ? (first.cls.includes("sect-divider") ? "divider" : "block") : null,
    };
  }
  return out;
};

async function rhythmOf(browser, base, { width, height, isMobile, tabs, settle = 350 }) {
  const context = await browser.newContext({
    viewport: { width, height }, isMobile: !!isMobile, hasTouch: !!isMobile,
  });
  const page = await context.newPage();
  await stubLiveOrigin(page);
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  const seen = {};
  for (const tab of tabs) {
    if (tab !== "hero") {
      await clickTab(page, tab);
      await waitForTab(page, tab);
      await page.waitForTimeout(settle);
    }
    Object.assign(seen, await page.evaluate(RHYTHM_SAMPLE, { tabs: [tab] }));
  }
  await context.close();
  return seen;
}

async function testCardRhythmIsOneScalePerTier(browser, base) {
  const tabs = ["hero", "drill", "risk", "market", "plan", "reflect"];
  // 桌面档：卡间距 16（--space-4）、分节线上方 24（--space-5）、线下方 16
  const desktop = await rhythmOf(browser, base, { width: 1440, height: 900, tabs });
  for (const tab of tabs) {
    const sample = desktop[tab];
    assert(sample, `${tab}: the panel never rendered`);
    const within = sample.gapDetail.filter(row => !row.straddles);
    assert(within.length > 0,
      `${tab}: no two cards share a column — the rhythm check went vacuous`);
    for (const row of within) {
      assert.equal(row.gap, 16,
        `${tab}: ${row.from} → ${row.to} is ${row.gap}px apart; the desktop card rhythm is 16px. ` +
        `Whole tab: ${JSON.stringify(sample.gapDetail.map(r => r.gap))}`);
    }
    for (const row of sample.gapDetail.filter(r => r.straddles)) {
      assert(row.gap > 16,
        `${tab}: a section break measures ${row.gap}px, no looser than the 16px card gap — ` +
        `the grouping it draws would disappear`);
    }
    for (const gap of sample.above) {
      assert.equal(gap, 24,
        `${tab}: the section divider sits ${gap}px below the previous card, expected 24px (--space-5)`);
    }
    for (const gap of sample.below) {
      assert.equal(gap, 16,
        `${tab}: the first card of a section sits ${gap}px below the divider, expected 16px (--space-4)`);
    }
  }
  // 首块的位置：同类首块在六个 tab 里必须落在同一条线上。Hero 的上面挂着
  // 桌面摘要条（只在 Overview 显示），所以它不参与这条比较。
  const byKind = { block: [], divider: [] };
  for (const tab of tabs) {
    if (tab === "hero") continue;
    const sample = desktop[tab];
    if (!sample.firstTop) continue;
    byKind[sample.firstKind].push({ tab, top: sample.firstTop });
  }
  for (const [kind, rows] of Object.entries(byKind)) {
    assert(rows.length > 0, `no tab starts with a ${kind} — the first-block check went vacuous`);
    const tops = rows.map(r => r.top);
    assert(Math.max(...tops) - Math.min(...tops) <= 2,
      `the first ${kind} does not line up across tabs: ${rows.map(r => `${r.tab}@${r.top}`).join(", ")} — ` +
      `a block that is hidden by data still occupies the "first block" position, so the first visible one must not be pushed down an extra tier`);
  }

  // 「不要完全统一」：分节必须比卡间距松，否则分组就没了。至少有一个 tab 真的
  // 画了分节线，这条断言才不是空转。
  const withDivider = tabs.map(t => desktop[t]).filter(t => t.above.length);
  assert(withDivider.length > 0,
    "no tab rendered a section divider — the hierarchy half of this check went vacuous");
  for (const sample of withDivider) {
    assert(sample.above[0] > 16,
      `a section divider is only ${sample.above[0]}px below the previous card; it has to read looser than the 16px card gap`);
  }

  // 窄屏档：同一套节奏的密档 —— 卡间距 12、分节线上方 16、线下方 12。
  const phone = await rhythmOf(browser, base, {
    width: 390, height: 844, isMobile: true, tabs: ["hero", "drill"],
  });
  for (const tab of ["hero", "drill"]) {
    const sample = phone[tab];
    const within = sample ? sample.gapDetail.filter(row => !row.straddles) : [];
    assert(within.length > 0, `${tab} (phone): no stacked cards to measure`);
    for (const row of within) {
      assert.equal(row.gap, 12, `${tab} (phone): ${row.from} → ${row.to} is ${row.gap}px apart, expected 12px`);
    }
  }
  for (const gap of phone.drill.above) {
    assert.equal(gap, 16, `drill (phone): the divider sits ${gap}px below the previous card, expected 16px`);
  }
  for (const gap of phone.drill.below) {
    assert.equal(gap, 12, `drill (phone): the section opens ${gap}px below the divider, expected 12px`);
  }
}


/** Every control a finger has to hit, measured on a phone.

    The widget audit (2026-09-20) found the header holding 44px while the
    controls inside the cards ran 30–38px: `.mkt-seg-btn` 30, `.dh-toggle` 32,
    `.dm-actionbar button` 32, `.dm-controls select` 36, `.desk-rail-toggle` 38.
    Each was individually plausible and collectively a page where the hit area
    depends on which card you are in. A stylesheet rule cannot be asserted by
    reading it, so this opens the real page at 390px with touch and measures.

    `.deck-dot` is the exception and stays one: six pager dots sit on a 12px
    pitch, so a 44px box would swallow its neighbours — the same trade the
    timeline dots already make. It is checked on reach, not on box height. */
// Every control answers a press, and answers it the same way.
//
// `--press-scale` exists so a press feels identical everywhere; its own comment
// says an inconsistent one reads as "some buttons are softer". Seven components
// wrote it. The sort headers, every fold and toggle, the Overview jump links,
// the retry, the decision-map controls and the drawer's buttons did not move at
// all — and the static gate above could not see it, because it only checks that
// a press which *exists* uses the token.
//
// Read out of the CSSOM rather than by synthesising a press: WebKit does not
// reliably put `:active` on an element under an automated mouse-down, so a
// press-and-measure gate would report engine noise as a design defect. This
// asks the question the stylesheet can answer exactly — does a rule that is
// live at this viewport give this element a press?
async function testEveryControlAnswersAPress(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  // A press that is deliberately not a scale. `.dm-cell` is a `<td>`: scaling
  // one drags its column's width with it, so its press is the outline it
  // already draws. Anything new here has to earn its line.
  const NOT_SCALED = new Set(["td.dm-cell"]);

  const scan = () => page.evaluate(() => {
    const pressRules = [];
    const optOut = [];
    const collect = (rules, live) => {
      for (const rule of rules) {
        if (rule.media) { collect(rule.cssRules, live && matchMedia(rule.conditionText).matches); continue; }
        if (rule.cssRules && !rule.selectorText) { collect(rule.cssRules, live); continue; }
        if (!live || !rule.selectorText || !rule.selectorText.includes(":active")) continue;
        const transform = rule.style && rule.style.transform;
        if (!transform) continue;
        for (const part of rule.selectorText.split(",")) {
          if (!part.includes(":active")) continue;
          const base = part.replace(/:active/g, "").trim();
          (transform === "none" ? optOut : pressRules).push(base);
        }
      }
    };
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch { continue; }
      collect(rules, true);
    }
    const scope = [
      ".topbar button", ".topbar summary", ".tabs button",
      ".panel.active button", ".panel.active summary",
      ".panel.active [role='button']",
      ".site-menu[open] .site-menu-item", ".dm-drawer.is-open button",
    ].join(",");
    const out = [];
    for (const el of new Set(document.querySelectorAll(scope))) {
      const box = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (!box.width || !box.height || style.visibility === "hidden"
          || style.display === "none" || el.closest("[inert]")) continue;
      const matches = list => list.some(selector => { try { return el.matches(selector); } catch { return false; } });
      const cls = typeof el.className === "string"
        ? el.className.trim().split(/\s+/)[0] : "";
      out.push({
        name: el.tagName.toLowerCase() + (cls ? "." + cls : ""),
        pressed: matches(pressRules),
        excused: matches(optOut),
      });
    }
    return out;
  });

  const missing = new Set(), excused = new Set();
  for (const tab of ["hero", "drill", "risk", "market", "plan", "reflect"]) {
    await page.evaluate(name => document.getElementById(`tab-${name}`)?.click(), tab);
    await page.waitForTimeout(400);
    for (const row of await scan()) {
      if (row.excused) excused.add(row.name);
      else if (!row.pressed) missing.add(`${tab} ${row.name}`);
    }
  }
  await page.locator(".site-menu-btn").click();
  await page.waitForTimeout(300);
  for (const row of await scan()) {
    if (!row.pressed && !row.excused) missing.add(`site-menu-open ${row.name}`);
  }
  await page.keyboard.press("Escape");

  assert.deepEqual([...missing], [],
    "these controls do not move when pressed; the baseline is "
    + "`button/summary/[role=button]:active { transform: scale(var(--press-scale)) }`: "
    + [...missing].join(", "));
  assert.deepEqual([...excused].filter(name => !NOT_SCALED.has(name)), [],
    "a control that opts out of the press scale has to be named in NOT_SCALED "
    + "with the reason: " + [...excused].join(", "));

  await context.close();
}

async function testEveryPhoneControlIsAFingerTarget(browser, base) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  const FLOOR = 44;
  const short = [];
  const scan = () => page.evaluate(() => {
    const selector = [
      ".topbar button", ".topbar summary", ".tabs button",
      ".panel.active button:not(.deck-dot):not(.dm-dot)",
      ".panel.active summary", ".panel.active select", ".panel.active input",
      ".panel.active [role='button']", ".panel.active [tabindex='0']",
      ".site-menu[open] .site-menu-item", ".dm-drawer.is-open button",
    ].join(",");
    window.__targets = [...new Set(document.querySelectorAll(selector))]
      .filter(el => {
        const box = el.getBoundingClientRect(), style = getComputedStyle(el);
        return box.width > 0 && box.height > 0 && style.visibility !== "hidden"
          && style.display !== "none" && !el.closest("[inert]");
      });
    return window.__targets.map((el, index) => {
      const box = el.getBoundingClientRect();
      const name = (el.getAttribute("aria-label") || el.textContent || "")
        .trim().replace(/\s+/g, " ").slice(0, 36);
      const cls = typeof el.className === "string"
        ? el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      return { index, element: `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}`
        + `${cls ? `.${cls}` : ""}[${name}]`,
        width: Math.round(box.width), height: Math.round(box.height) };
    });
  });
  // A control may paint smaller than it is touchable — the refresh glyph has an
  // invisible pseudo-element for a target, which is the right shape for an
  // icon-only control (draw the mark, not a picture of the hit area). So a box
  // under the floor is re-measured through `elementFromPoint` before it counts
  // as a defect; only a control a finger really cannot reach is reported.
  const reachOf = selectorIndex => page.evaluate(index => {
    const el = window.__targets[index];
    el.scrollIntoView({ block: "center", behavior: "instant" });
    const box = el.getBoundingClientRect();
    if (box.top < 0 || box.bottom > innerHeight) return null;
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const owns = (dx, dy) => {
      const hit = document.elementFromPoint(x + dx, y + dy);
      return hit === el || el.contains(hit);
    };
    let up = 0, down = 0, left = 0, right = 0;
    while (up < 60 && owns(0, -up - 1)) up += 1;
    while (down < 60 && owns(0, down + 1)) down += 1;
    while (left < 60 && owns(-left - 1, 0)) left += 1;
    while (right < 60 && owns(right + 1, 0)) right += 1;
    return [left + right + 1, up + down + 1];
  }, selectorIndex);
  const collect = async label => {
    const rows = await scan();
    for (const row of rows) {
      if (row.width >= FLOOR && row.height >= FLOOR) continue;
      const reach = await reachOf(row.index);
      if (reach && reach[0] >= FLOOR && reach[1] >= FLOOR) continue;
      short.push(`${label} ${row.element}: ${row.width}×${row.height}px`
        + (reach ? ` (reach ${reach.join("×")})` : ""));
    }
  };
  for (const tab of ["hero", "drill", "risk", "market", "plan", "reflect"]) {
    await page.evaluate(name => document.getElementById(`tab-${name}`)?.click(), tab);
    await page.waitForTimeout(400);
    if (tab === "hero") {
      await page.evaluate(() => document.querySelectorAll("#data-health button.dh-cell, #data-health .dh-job-row")
        .forEach(el => el.click()));
      await page.waitForTimeout(200);
    }
    await collect(tab);
  }

  // The menu and drawer do not exist in the painted interaction tree until a
  // reader opens them. Scan those states too; the old whitelist never did.
  await page.locator(".site-menu-btn").click();
  await page.waitForTimeout(300);
  await collect("site-menu-open");
  await page.keyboard.press("Escape");
  await page.evaluate(() => document.getElementById("tab-reflect")?.click());
  await page.waitForTimeout(500);
  const bucket = page.locator(".dm-cell[tabindex='0']").first();
  if (await bucket.count()) {
    await bucket.click();
    await page.waitForTimeout(300);
    await collect("drawer-open");
    await page.keyboard.press("Escape");
  }
  assert.deepEqual(short, [],
    `these controls are mouse-sized on a phone (the floor is ${FLOOR}px): ` + short.join(", "));

  // The pager dots: a 5px dot with the reach of a 5px dot is a dot nobody hits.
  await page.evaluate(name => document.getElementById(`tab-${name}`)?.click(), "hero");
  await page.waitForTimeout(400);
  // Scroll first and settle, then measure: `elementFromPoint` answers about the
  // *viewport*, so a dot below the fold reports no reach at all — which is how
  // this assertion failed on CI while passing locally, on identical CSS.
  await page.evaluate(() => document.querySelector(".deck-dot")
    ?.scrollIntoView({ block: "center", behavior: "instant" }));
  await page.waitForTimeout(300);
  const dot = await page.evaluate(() => {
    const el = document.querySelector(".deck-dot");
    if (!el) return null;
    const box = el.getBoundingClientRect();
    const onscreen = box.top >= 0 && box.bottom <= innerHeight
      && box.left >= 0 && box.right <= innerWidth;
    const size = [Math.round(box.width), Math.round(box.height)];
    if (!onscreen) return { size, onscreen };
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const owns = (dx, dy) => {
      const hit = document.elementFromPoint(x + dx, y + dy);
      return hit === el || el.contains(hit);
    };
    let up = 0, down = 0, left = 0, right = 0;
    while (up < 40 && owns(0, -up - 1)) up += 1;
    while (down < 40 && owns(0, down + 1)) down += 1;
    while (left < 20 && owns(-left - 1, 0)) left += 1;
    while (right < 20 && owns(right + 1, 0)) right += 1;
    const dots = [...document.querySelectorAll(".deck-dot")];
    let bleeds = false;
    if (dots.length > 1) {
      const a = dots[0].getBoundingClientRect(), b = dots[1].getBoundingClientRect();
      const midpoint = (a.right + b.left) / 2;
      const hit = document.elementFromPoint(midpoint, a.top + a.height / 2);
      bleeds = (hit === dots[0] || dots[0].contains(hit))
        && (hit === dots[1] || dots[1].contains(hit));
    }
    return { size, onscreen, reachV: up + down + 1, reachH: left + right + 1, bleeds,
      clips: dots.map(d => getComputedStyle(d).backgroundClip) };
  });
  if (dot) {
    // The box is what the stylesheet decides, so it is asserted either way: a
    // 5×5 button is the defect this exists for. The reach is what the browser
    // decides, and `elementFromPoint` answers about the viewport — so it is
    // only asserted when the dot really is in it. (Measuring a dot below the
    // fold is how this assertion failed on CI while passing locally, on
    // identical CSS.)
    assert(dot.size[0] >= 10 && dot.size[1] >= 24,
      `the deck dot's touch box is ${dot.size.join("×")}px; a 5px dot is a 5px target`);
    assert(dot.clips.every(clip => clip === "content-box"),
      `a deck dot paints its tall touch box (${dot.clips.join("/")}) instead of its 5px content box`);
    if (dot.onscreen) {
      assert(dot.reachV >= 20,
        `a finger has ${dot.reachV}px of vertical reach on a deck dot`);
      assert(dot.reachH >= 10,
        `a finger has ${dot.reachH}px of horizontal reach on a deck dot`);
      assert(!dot.bleeds, "a deck dot's hit area reaches its neighbour");
    }
    // The regression follows aria-current: before the fix the newly current
    // dot's `background` shorthand reset background-clip to border-box, so the
    // 11×33px invisible touch target became a visible vertical ellipse.
    await page.locator(".deck-dot").nth(1).click();
    await page.waitForFunction(() =>
      document.querySelectorAll(".deck-dot")[1]?.getAttribute("aria-current") === "true");
    const switchedClips = await page.locator(".deck-dot").evaluateAll(dots =>
      dots.map(dot => getComputedStyle(dot).backgroundClip));
    assert(switchedClips.every(clip => clip === "content-box"),
      `switching cards paints the dot's tall touch box: ${switchedClips.join("/")}`);
  }
  await context.close();
}

// Both user-visible age labels contain CJK prose. Exercise the short and longer
// states at actual iPhone widths, assert each glyph advances, and — separately
// — assert the market age never occupies the title's rectangle. The latter is
// the iOS Safari regression: both strings fit, but a fixed top offset placed
// them on top of each other.
async function testRelativeAgeLabelsKeepTheirGlyphsApart(browser, base) {
  for (const width of [1200, 430, 393, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 844 } });
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "networkidle" });
    await waitForData(page);
    const collisions = await page.evaluate(() => {
      const samples = {
        "market-asof": ["(刚刚)", "(3 分钟前)", "(2 小时前)", "(1 天前)"],
        "last-updated": [
          "· 生成于 刚刚 · 06:44 UTC",
          "· 生成于 3 分钟前 · 06:41 UTC",
          "· 生成于 2 小时前 · 04:44 UTC",
        ],
      };
      const bad = [];
      for (const [id, values] of Object.entries(samples)) {
        const el = document.getElementById(id);
        for (const value of values) {
          el.textContent = value;
          const node = el.firstChild, boxes = [];
          for (let i = 0; i < value.length; i++) {
            const range = document.createRange();
            range.setStart(node, i); range.setEnd(node, i + 1);
            boxes.push(range.getBoundingClientRect());
          }
          for (let i = 1; i < boxes.length; i++) {
            if (boxes[i].left < boxes[i - 1].right - .25)
              bad.push(`${id} ${value}: glyph ${i} starts before glyph ${i - 1} ends`);
          }
          if (getComputedStyle(el).display !== "none" && el.scrollWidth > el.clientWidth + 1)
            bad.push(`${id} ${value}: ${el.scrollWidth}px text is squeezed into ${el.clientWidth}px`);
          if (id === "market-asof") {
            const title = el.closest(".overview-strip-link")
              ?.querySelector(".overview-strip-heading > span:first-child");
            const a = el.getBoundingClientRect(), b = title?.getBoundingClientRect();
            if (b && !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top))
              bad.push(`${id} ${value}: age overlaps the market title`);
          }
        }
      }
      return bad;
    });
    assert.deepEqual(collisions, [],
      `relative-time glyphs overlap at ${width}px: ${collisions.join("; ")}`);
    await context.close();
  }
}


/** No rounded block on the page is painted the colour of what it sits on.

    The static check in `tests/test_dashboard_component_language.py` catches a
    rule that fills with the card's own colour. It cannot catch the other half
    of the same mistake — a block filled with `--fill-inset` *inside* another
    block that is already `--fill-inset`, which is how `.risk-age`, `.tr-chip`
    and `.tr-align.na` came out invisible the moment their containers stopped
    being card-coloured. Nesting is a DOM fact, so this measures the DOM.

    Skipped, with reasons: translucent fills (a tint resolves against whatever
    it lands on and is checked for contrast elsewhere), gradient surfaces (the
    card material's sheen), pills (`border-radius >= height/2`, which read as
    chips without a fill step), and anything under 12×8px. */
async function testNoBlockIsPaintedTheColourOfWhatItSitsOn(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);

  const scan = () => {
    const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const alpha = value => Number((value.match(/[\d.]+/g) || [])[3] ?? 1);
    const luminance = channels => {
      const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(channels[0]) + 0.7152 * f(channels[1]) + 0.0722 * f(channels[2]);
    };
    const ratio = (a, b) => {
      const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
      return Math.round(((hi + 0.05) / (lo + 0.05)) * 1000) / 1000;
    };
    const found = [];
    for (const el of document.querySelectorAll(
      ".panel.active *, .desk-rail *, .topbar *, .site-menu[open] *, "
      + ".dm-drawer.is-open, .dm-drawer.is-open *, .native-equity-tooltip:not([hidden])")) {
      // The open disclosure is signalled by its rotated chevron and the
      // adjacent visible panel. Its quiet fill is a pressed/open state, not a
      // nested block that needs a separate surface rung.
      if (el.matches(".site-menu-btn")) continue;
      const style = getComputedStyle(el), box = el.getBoundingClientRect();
      if (box.width < 12 || box.height < 8) continue;
      if (alpha(style.backgroundColor) < 1) continue;
      if (style.backgroundImage !== "none") continue;
      const radius = parseFloat(style.borderTopLeftRadius) || 0;
      if (radius < 4 || radius >= box.height / 2) continue;
      let node = el.parentElement, behind = null;
      while (node && !behind) {
        const parent = getComputedStyle(node);
        if (parent.backgroundColor && alpha(parent.backgroundColor) === 1
            && parent.backgroundColor !== "transparent") behind = rgb(parent.backgroundColor);
        node = node.parentElement;
      }
      if (!behind) continue;
      const separation = ratio(rgb(style.backgroundColor), behind);
      if (separation < 1.02) {
        found.push(`${(el.className || "").toString().split(" ").slice(0, 2).join(".")}: ${separation}`);
      }
    }
    return [...new Set(found)];
  };

  const invisible = new Set();
  for (const tab of ["hero", "drill", "risk", "market", "plan", "reflect"]) {
    await page.evaluate(name => document.getElementById(`tab-${name}`)?.click(), tab);
    await page.waitForTimeout(700);
    // Open the data-health rows; their details only lay out once expanded.
    await page.evaluate(() => document.querySelectorAll("#data-health button.dh-cell, #data-health .dh-job-row")
      .forEach(el => el.click()));
    await page.waitForTimeout(300);
    for (const row of await page.evaluate(scan)) invisible.add(`${tab} ${row}`);
  }
  await page.locator(".site-menu-btn").click();
  await page.waitForTimeout(300);
  for (const row of await page.evaluate(scan)) invisible.add(`site-menu-open ${row}`);
  await page.keyboard.press("Escape");
  const bucket = page.locator(".dm-cell[tabindex='0']").first();
  if (await bucket.count()) {
    await bucket.click();
    await page.waitForTimeout(300);
    for (const row of await page.evaluate(scan)) invisible.add(`drawer-open ${row}`);
    await page.keyboard.press("Escape");
  }
  const canvas = page.locator(".native-equity-canvas").first();
  if (await canvas.count()) {
    await canvas.hover({ position: { x: 120, y: 80 } });
    await page.waitForTimeout(300);
    assert(await page.locator(".native-equity-tooltip").isVisible(),
      "the interaction scan never opened the equity tooltip");
    for (const row of await page.evaluate(scan)) invisible.add(`tooltip-open ${row}`);
  }
  assert.deepEqual([...invisible], [],
    "these rounded blocks are the colour of the surface under them — step to "
    + "var(--fill-inset) or var(--fill-inset-2): " + [...invisible].join(", "));
  await context.close();
}


async function main() {
  const server = serveWorkspace();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const executablePath = process.env.CHROME_EXE || undefined;
  const browser = await chromium.launch(executablePath ? {
    executablePath, args: ["--no-sandbox"],
  } : {});
  // `SPEC_ONLY=name,name` runs a subset. A browser contract measured before the
  // layout settles is load-sensitive (see the verdict-deck case), and re-running
  // one case used to mean editing this list and remembering to put it back.
  const only = (process.env.SPEC_ONLY || "").split(",").map(s => s.trim()).filter(Boolean);
  const run = async (name, fn) => {
    if (only.length && !only.includes(name)) return;
    await fn();
  };
  try {
    await run("runtime", () => testRuntime(browser, base));
    await run("testAStaleFxRateSaysSoOnTheHero", () => testAStaleFxRateSaysSoOnTheHero(browser, base));
    await run("testMissingFxDoesNotFabricateCombinedValues", () => testMissingFxDoesNotFabricateCombinedValues(browser, base));
    await run("testNewsDigestGeneratedTimeUsesHkt", () => testNewsDigestGeneratedTimeUsesHkt(browser, base));
    await run("testCurrentHoldingsOwnDecisionMatrixMembership", () => testCurrentHoldingsOwnDecisionMatrixMembership(browser, base));
    await run("testLiveDataOrigin", () => testLiveDataOrigin(browser, base));
    await run("testEquityTouch", () => testEquityTouch(browser, base));
    await run("testTabGuardWithoutForcedLayout", () => testTabGuardWithoutForcedLayout(browser, base));
    await run("testMobilePagerCommitsStateAtTheRealSnapPoint", () =>
      testMobilePagerCommitsStateAtTheRealSnapPoint(browser, base));
    await run("testNativePagerGestureSequences", () =>
      testNativePagerGestureSequences(browser, base));
    await run("testTopbarFitsWhenRefreshLabelSwaps", () => testTopbarFitsWhenRefreshLabelSwaps(browser, base));
    await run("testHeaderSharesTheContentColumn", () => testHeaderSharesTheContentColumn(browser, base));
    await run("testTraceRowsFitPhoneWidths", () => testTraceRowsFitPhoneWidths(browser, base));
    await run("testHoldingsAndHeroNeverTruncate", () => testHoldingsAndHeroNeverTruncate(browser, base));
    await run("testVerdictDeckFillsItsBoxAndRanksGatesBySeverity", () => testVerdictDeckFillsItsBoxAndRanksGatesBySeverity(browser, base));
    await run("testVerdictDeckPagerTracksTheVisualCard", () => testVerdictDeckPagerTracksTheVisualCard(browser, base));
    await run("testASidecarStillReachesItsCardWhenThePagerIsStillSettling", () => testASidecarStillReachesItsCardWhenThePagerIsStillSettling(browser, base));
    await run("testFailedSidecarRefreshKeepsTheLastGoodValue", () => testFailedSidecarRefreshKeepsTheLastGoodValue(browser, base));
    await run("testTheDebateTrailIsAListOfCasesNotAWallOfText", () => testTheDebateTrailIsAListOfCasesNotAWallOfText(browser, base));
    await run("testThePlanTimelineClampsItsRationales", () => testThePlanTimelineClampsItsRationales(browser, base));
    await run("testAddSideCardExplainsWhyThereIsNoAdd", () => testAddSideCardExplainsWhyThereIsNoAdd(browser, base));
    await run("testALeveragedRowWithoutVolatilityPrintsNoUndefined", () => testALeveragedRowWithoutVolatilityPrintsNoUndefined(browser, base));
    await run("testNoTabPrintsAMissingNumber", () => testNoTabPrintsAMissingNumber(browser, base));
    await run("testDataHealthAnswersIsAnythingWrongAtEveryWidth", () => testDataHealthAnswersIsAnythingWrongAtEveryWidth(browser, base));
    await run("testDataHealthDrillsDownWhereYouTapAndSurvivesARefresh", () => testDataHealthDrillsDownWhereYouTapAndSurvivesARefresh(browser, base));
    await run("testAnOldScheduleIsOneWatchItemNotOnePerJob", () => testAnOldScheduleIsOneWatchItemNotOnePerJob(browser, base));
    await run("testTheSearchVisibilityCardFitsWithoutOverflowing", () => testTheSearchVisibilityCardFitsWithoutOverflowing(browser, base));
    await run("testEveryAddCampaignRowStartsOnTheSameLine", () => testEveryAddCampaignRowStartsOnTheSameLine(browser, base));
    await run("testTheValidationLedgerRendersItsVerdictsAndFitsAPhone", () => testTheValidationLedgerRendersItsVerdictsAndFitsAPhone(browser, base));
    await run("testAPanelSaysWhenItsDataDidNotLoad", () => testAPanelSaysWhenItsDataDidNotLoad(browser, base));
    await run("testMoversSayWhichSessionTheyAreFrom", () => testMoversSayWhichSessionTheyAreFrom(browser, base));
    await run("testCardRhythmIsOneScalePerTier", () => testCardRhythmIsOneScalePerTier(browser, base));
    await run("testEveryPhoneControlIsAFingerTarget", () => testEveryPhoneControlIsAFingerTarget(browser, base));
    await run("testEveryControlAnswersAPress", () => testEveryControlAnswersAPress(browser, base));
    await run("testRelativeAgeLabelsKeepTheirGlyphsApart", () => testRelativeAgeLabelsKeepTheirGlyphsApart(browser, base));
    await run("testNoBlockIsPaintedTheColourOfWhatItSitsOn", () => testNoBlockIsPaintedTheColourOfWhatItSitsOn(browser, base));
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
