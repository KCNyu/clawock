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
  await page.route(LIVE_DATA_ORIGIN + "**", async route => {
    const name = path.basename(new URL(route.request().url()).pathname);
    served.push(name);
    if (options.fail) return route.abort("failed");
    const file = path.resolve(ROOT, "assets/data", name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: "not found" });
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      },
      body: fs.readFileSync(file, "utf8"),
    });
  });
  return served;
}

function observe(page) {
  const result = { detailRequests: 0, fullRequests: 0, failures: [], errors: [] };
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === DETAIL_PATH) result.detailRequests += 1;
    // Counted on either origin: the point of the assertion is that detail tabs
    // share one request for the full document, not where it was served from.
    if (pathname.endsWith("/assets/data/dashboard.json")) result.fullRequests += 1;
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
    const coreReady = tab === "hero"
      ? DATA?.projection === "overview"
      : Array.isArray(DATA?.snapshots);
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
    const rendered = [...document.querySelectorAll("#decision-matrix-tbody tr td:first-child strong")]
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

  const xs = [box.x + box.width - 5, 300, 250, 200, 150, 100, 45];
  await dispatchTouch(session, "touchStart", [{ x: xs[0], y }]);
  for (const x of xs.slice(1)) {
    await dispatchTouch(session, "touchMove", [{ x, y }]);
    await page.waitForTimeout(20);
  }
  await dispatchTouch(session, "touchEnd", []);
  await page.waitForFunction(() => document.querySelector(".tab-btn.active")?.dataset.tab === "drill");
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
  await page.evaluate(() => {
    const pager = document.getElementById("pager");
    pager.scrollLeft = TAB_ORDER.indexOf("market") * pager.clientWidth;
    pager.dispatchEvent(new Event("scroll"));
  });
  await page.waitForFunction(() => currentTab() === "market", null, { timeout: 4000 })
    .catch(() => { throw new Error("currentTab() drifted from an uninstrumented scroll"); });

  await context.close();
}

// The refresh button swaps its label to a CJK string ("已是最新" / "已更新 ✓") for
// 1.8s after a click. CJK has a line-break opportunity between every character,
// so a shrinkable flex item breaks it one glyph per line: the 36px pill became
// an 82px-tall column, and the topbar it overflowed painted the brand on top of
// the nav links. Both states are geometry, so measure them rather than grep the
// stylesheet for the properties that happen to fix them today.
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

    const idleHeight = (await page.locator("#refresh-btn").boundingBox()).height;
    await page.click("#refresh-btn");
    await page.waitForFunction(
      () => document.querySelector("#refresh-btn .lbl").textContent !== "Refresh",
      null, { timeout: 5000 },
    ).catch(() => { throw new Error(`refresh at ${width}px never reported back`); });

    const box = await page.evaluate(() => {
      const rect = el => el.getBoundingClientRect();
      const btn = document.getElementById("refresh-btn");
      const h1 = document.querySelector(".brand h1");
      const link = document.querySelector(".topbar-actions .nav-link");
      const row = document.querySelector(".topbar-row");
      return {
        label: btn.querySelector(".lbl").textContent,
        height: rect(btn).height,
        gap: rect(link).left - rect(h1).right,
        clipped: h1.scrollWidth > h1.clientWidth + 0.5,
        overflow: row.scrollWidth - row.clientWidth,
      };
    });
    assert(box.label !== "Refresh", `label did not swap at ${width}px`);
    assert(box.height <= idleHeight + 1,
      `refresh button grew to ${box.height}px showing "${box.label}" at ${width}px`);
    assert(box.gap >= 0,
      `brand overlaps the nav links by ${-box.gap}px at ${width}px`);
    assert(mayTruncate || !box.clipped, `brand wordmark is truncated at ${width}px`);
    assert(box.overflow <= 0, `topbar row overflows by ${box.overflow}px at ${width}px`);
    await context.close();
  }

  // The narrow layout drops the label to keep the row inside its width. That
  // must stay a narrow-viewport concession: on a desktop the button keeps its
  // text, and the feedback is the text.
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await stubLiveOrigin(desktop);
  await desktop.goto(base, { waitUntil: "networkidle" });
  await waitForData(desktop);
  assert(await desktop.locator("#refresh-btn .lbl").isVisible(),
    "desktop refresh button lost its text label");
  await desktop.close();

  // Hiding the label costs the phone layout the one thing the label carried:
  // that "已更新 ✓" and "已是最新" are different answers. Whatever replaces it
  // has to keep them apart by shape, not by border colour alone.
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
    `both refresh outcomes draw the same mark (${marks.ok}) below 560px`);
  assert(marks.fresh !== marks.idle,
    "a new generation left the refresh icon unchanged below 560px");
  await feedback.close();

  // Hiding the label below 560px means today's two strings can no longer be
  // squeezed hard enough to break — which would leave the button's own
  // single-line guarantee untested until someone widens that breakpoint or adds
  // a fourth nav link. Feed it a label long enough to put the row over budget:
  // the button may become wide, it may not become tall.
  const stress = await browser.newPage({ viewport: { width: 600, height: 900 } });
  await stubLiveOrigin(stress);
  await stress.goto(base, { waitUntil: "networkidle" });
  await waitForData(stress);
  const grew = await stress.evaluate(() => {
    const btn = document.getElementById("refresh-btn");
    const before = btn.getBoundingClientRect().height;
    btn.querySelector(".lbl").textContent = "已是最新的一份生成数据";
    return btn.getBoundingClientRect().height - before;
  });
  assert(grew <= 1, `refresh button wrapped its label onto ${grew}px of extra lines`);
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
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
