#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const DETAIL_PATH = "/assets/js/dashboard.render.js";
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
    await page.click(`.tab-btn[data-tab="${tab}"]`);
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
  await waitForTab(rapid, "reflect");
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

  await page.click('.tab-btn[data-tab="reflect"]');
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
  await page.click('.tab-btn[data-tab="risk"]');
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
  await page.locator('.tab-btn[data-tab="reflect"]').click();
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
  await page.waitForFunction(() => document.querySelector(".tab-btn.active")?.dataset.tab === "plan");
  assert.equal(await page.locator(".native-equity-tooltip").isVisible(), false,
    "pager swipe left a stale chart tooltip");
  assert.deepEqual(state.failures, []);
  assert.deepEqual(state.errors, []);
  await context.close();
}

// `currentTab()` used to read pager.scrollLeft/clientWidth, which forces layout,
// and the hero render loop calls it between renderers — right after each one's
// DOM writes. That interleave cost 162ms of the 1,016ms spent in layout on a
// mobile startup profile (#442). It now reads an index the scroll handler
// already maintains every frame.
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

  // 3. And it must not drift from a scroll the code did not initiate — a real
  //    swipe moves scrollLeft with no goToTab call anywhere.
  //
  //    goToTab above scrolls with `behavior: smooth`, and that animation is
  //    still running when this step writes scrollLeft. Chromium does not treat
  //    the write as a cancel: the in-flight smooth scroll carries on, and with
  //    scroll-snap on the pager it lands on the LAST page — which made this
  //    assertion fail roughly one run in three on master, unrelated to any
  //    change under test. Let the pager come to rest first (two consecutive
  //    frames at the same offset) so the step measures what it means to.
  await page.waitForFunction(() => {
    const pager = document.getElementById("pager");
    const at = Math.round(pager.scrollLeft / (pager.clientWidth || 1));
    // Arrived AND stopped: "two equal frames" alone is not enough, because a
    // smooth scroll has not necessarily started moving by frame two.
    if (at !== TAB_ORDER.indexOf("risk")) { window.__settleAt = null; return false; }
    const stable = window.__settleAt === pager.scrollLeft;
    window.__settleAt = pager.scrollLeft;
    return stable;
  }, null, { polling: "raf", timeout: 5000 });
  await page.evaluate(() => {
    const pager = document.getElementById("pager");
    pager.scrollLeft = TAB_ORDER.indexOf("market") * pager.clientWidth;
    pager.dispatchEvent(new Event("scroll"));
  });
  await page.waitForFunction(() => currentTab() === "market", null, { timeout: 4000 })
    .catch(() => { throw new Error("currentTab() drifted from an uninstrumented scroll"); });

  await context.close();
}

// The refresh button is a ghost icon now: no label to swap, so the old CJK
// line-break failure mode is structurally gone. What must still hold is the
// geometry contract the old test guarded: clicking never changes the button's
// footprint (34x34 circle), the brand never overlaps the nav links, and the
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
      const link = document.querySelector(".topbar-actions .nav-link");
      const row = document.querySelector(".topbar-row");
      return {
        hasLabel: !!btn.querySelector(".lbl"),
        height: rect(btn).height,
        width: rect(btn).width,
        gap: rect(link).left - rect(h1).right,
        clipped: h1.scrollWidth > h1.clientWidth + 0.5,
        overflow: row.scrollWidth - row.clientWidth,
      };
    });
    assert(box.hasLabel === false, `refresh button must be icon-only at ${width}px`);
    assert(box.height <= idle.height + 1 && box.width <= idle.width + 1,
      `refresh button grew to ${box.width}x${box.height} at ${width}px (idle ${idle.width}x${idle.height})`);
    assert(box.gap >= 0,
      `brand overlaps the nav links by ${-box.gap}px at ${width}px`);
    assert(mayTruncate || !box.clipped, `brand wordmark is truncated at ${width}px`);
    assert(box.overflow <= 0, `topbar row overflows by ${box.overflow}px at ${width}px`);
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
// width the wordmark and the tab strip kept walking outward while the content
// stood still (172px of drift at 1920, 492px at 2560).
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
      const tabs = document.querySelector(".tabs");
      const topbar = document.querySelector(".topbar");
      const tabsRule = parseFloat(getComputedStyle(tabs).borderBottomWidth) || 0;
      return {
        columnLeft: box(main).left + parseFloat(style.paddingLeft),
        columnRight: box(main).right - parseFloat(style.paddingRight),
        brandLeft: box(document.querySelector(".brand-mark")).left,
        tabLeft: box(document.querySelector(".tab-btn")).left,
        refreshRight: box(document.getElementById("refresh-btn")).right,
        // A rule that stops at the column edge, one pixel above the header's
        // own full-bleed rule, draws a visible step where they part company.
        doubledRule: tabsRule > 0 &&
          box(topbar).bottom - box(tabs).bottom <= 2 &&
          box(tabs).width < box(topbar).width,
      };
    });
    const off = (a, b) => Math.abs(a - b);
    assert(off(m.brandLeft, m.columnLeft) <= 1,
      `wordmark is ${off(m.brandLeft, m.columnLeft)}px off the content column at ${width}px`);
    assert(off(m.tabLeft, m.columnLeft) <= 1,
      `tab strip is ${off(m.tabLeft, m.columnLeft)}px off the content column at ${width}px`);
    assert(off(m.refreshRight, m.columnRight) <= 1,
      `refresh button is ${off(m.refreshRight, m.columnRight)}px off the column's right edge at ${width}px`);
    assert(!m.doubledRule,
      `a column-width rule sits on the header's full-bleed rule at ${width}px`);
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
    await page.click('.tab-btn[data-tab="drill"]');
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

    // 数据健康的「在期」分段必须是品牌蓝，不是灰墨也不是涨跌色（#920 判据：
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
      const okSegs = [...document.querySelectorAll(".dh-seg.is-ok i")];
      const fills = okSegs.map(s => getComputedStyle(s).backgroundColor);
      // 探针读完再摘：摘掉之后 getComputedStyle 读的是游离节点，颜色恒为空。
      const accentBlue = tint("color-mix(in srgb, var(--accent) 82%, transparent)");
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
    await page.click('.tab-btn[data-tab="drill"]');
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

// 数据健康卡：降级/恢复必须点名是哪一档（kcn 2026-08-25：「如果有降级的应该
// 标注出来是哪个」），微信单通道掉投必须可数、可点名（#771 让它在 summarizer
// 里可数，但那个计数从没进过任何读者能看到的地方）。
async function testDataHealthNamesTheDegradedSlotAndWeChatDrops(browser, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await stubLiveOrigin(page, {
    patch: (name, json) => {
      // overview 与 dashboard 两份都要打：首帧吃 overview，随后整份 dashboard
      // 会把 DATA 换掉 —— 只打一份的话断言会跑在被覆盖后的真实数据上。
      if (name !== "overview.json" && name !== "dashboard.json") return null;
      // 体检干净、数据面全部在期 —— 把判词的其它分支让开，只留「恢复/降级」。
      json.build_status = json.build_status || {};
      json.build_status.integrity = { error_count: 0, warn_count: 0 };
      json.build_status.files = (json.build_status.files || []).map(f => ({
        ...f, present: true, stale: false,
      }));
      json.workflow_outcomes = {
        counts: { success: 9, recovered: 1 },
        raw_error_but_product_usable: 2,
        wechat_dropped_telegram_covered: 3,
        degraded_slots: [
          { job: "港股收盘报告", slot: "2026-08-25T16:00:00+08:00", status: "recovered" },
        ],
        wechat_dropped_slots: [
          { job: "港股收盘报告", slot: "2026-08-25T16:00:00+08:00" },
          { job: "盘中盯盘", slot: "2026-08-25T15:30:00+08:00" },
        ],
        recent: [
          {
            job: "港股收盘报告", slot: "2026-08-25T16:00:00+08:00",
            raw_execution: { status: "error" },
            final_product: { status: "recovered" },
            primary_delivery: { wechat_ok: false, telegram_ok: true },
          },
          {
            job: "盘中盯盘", slot: "2026-08-25T15:30:00+08:00",
            raw_execution: { status: "ok" },
            final_product: { status: "success" },
            primary_delivery: { wechat_ok: false, telegram_ok: true },
          },
        ],
      };
      return json;
    },
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await waitForData(page);
  await page.waitForSelector("#data-health:not(.is-pending)", { timeout: 5000 });

  const head = await page.evaluate(() => ({
    verdict: (document.getElementById("dh-verdict") || document.getElementById("dh-title")).textContent.trim(),
    meta: document.getElementById("dh-meta").textContent.trim(),
  }));
  assert(head.verdict.includes("港股收盘报告"),
    `data-health verdict does not name the degraded slot: ${head.verdict}`);
  assert(head.verdict.includes("恢复"),
    `data-health verdict does not say what happened to it: ${head.verdict}`);
  assert(/微信掉投\s*3\s*档/.test(head.meta),
    `data-health meta does not carry the WeChat drop count: ${head.meta}`);

  await page.click("#dh-toggle");
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll("#dh-files .dh-row")].map(r => r.textContent.replace(/\s+/g, " ").trim()));
  const dropRows = rows.filter(t => t.includes("TG 已兜"));
  assert.equal(dropRows.length, 2,
    `expected both WeChat-dropped slots listed, got ${dropRows.length}: ${dropRows.join(" | ")}`);
  assert(dropRows.some(t => t.includes("港股收盘报告") && t.includes("2026-08-25 16:00")),
    `dropped slot rows do not name job + slot: ${dropRows.join(" | ")}`);
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
  try {
    await testRuntime(browser, base);
    await testCurrentHoldingsOwnDecisionMatrixMembership(browser, base);
    await testLiveDataOrigin(browser, base);
    await testEquityTouch(browser, base);
    await testTabGuardWithoutForcedLayout(browser, base);
    await testTopbarFitsWhenRefreshLabelSwaps(browser, base);
    await testHeaderSharesTheContentColumn(browser, base);
    await testTraceRowsFitPhoneWidths(browser, base);
    await testHoldingsAndHeroNeverTruncate(browser, base);
    await testVerdictDeckFillsItsBoxAndRanksGatesBySeverity(browser, base);
    await testDataHealthNamesTheDegradedSlotAndWeChatDrops(browser, base);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
